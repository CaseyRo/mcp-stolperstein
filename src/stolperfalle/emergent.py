"""Emergent signal detection — aggregates query misses into tool-gap-signal KUs.

Algorithm (design.md §9):

1. Load recent `query_misses` rows with embeddings (TTL-prune old).
2. Cluster by cosine similarity (≥0.8 threshold).
3. For clusters with ≥ EMERGENT_MIN_MISSES across ≥ EMERGENT_MIN_SESSIONS
   (approximated by distinct 1-hour time buckets): emit a new
   `tool-gap-signal` KU with `provenance.emergent=true`.
4. 7-day dedupe: don't re-emit from a cluster that has already produced a KU
   with ≥0.8 cosine similarity in the past 7 days.

Simple by design — the aggregation algorithm can be iterated without schema
changes.
"""

from __future__ import annotations

import json
import logging
import math
import secrets
import struct
from datetime import datetime, timedelta, timezone

from stolperfalle.config import settings

logger = logging.getLogger(__name__)

_TTL_DAYS = 30
_DEDUPE_DAYS = 7
_COSINE_THRESHOLD = 0.8


def _deserialize_f32(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _cluster_misses(misses: list[dict]) -> list[list[dict]]:
    """Greedy clustering: each miss joins the first cluster whose centroid is ≥0.8 similar."""
    clusters: list[list[dict]] = []
    for m in misses:
        emb = m["embedding"]
        placed = False
        for cluster in clusters:
            # Compare against cluster's first miss as centroid proxy.
            if _cosine(emb, cluster[0]["embedding"]) >= _COSINE_THRESHOLD:
                cluster.append(m)
                placed = True
                break
        if not placed:
            clusters.append([m])
    return clusters


def _session_buckets(misses: list[dict]) -> int:
    """Distinct 1-hour time buckets that show at least one miss."""
    buckets: set[str] = set()
    for m in misses:
        ts = m["created_at"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        buckets.add(ts.replace(minute=0, second=0, microsecond=0).isoformat())
    return len(buckets)


def detect_emergent(store) -> list[str]:
    """Run one aggregation pass. Returns list of emitted KU ids."""
    if settings.stolperfalle_emergent_disabled:
        logger.info("Emergent detection disabled via env")
        return []

    db = store._get_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=_TTL_DAYS)).isoformat()

    # TTL prune
    db.execute("DELETE FROM query_misses WHERE created_at < ?", [cutoff])
    db.commit()

    # Load remaining misses with embeddings
    rows = db.execute(
        "SELECT id, text, embedding, created_at FROM query_misses "
        "WHERE embedding IS NOT NULL ORDER BY created_at"
    ).fetchall()
    if len(rows) < settings.emergent_min_misses:
        return []

    misses = [
        {
            "id": row["id"],
            "text": row["text"],
            "embedding": _deserialize_f32(row["embedding"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
        }
        for row in rows
    ]

    # Load existing emergent KU embeddings for dedupe window
    dedupe_cutoff = (now - timedelta(days=_DEDUPE_DAYS)).isoformat()
    existing_rows = db.execute(
        "SELECT ku.id, emb.embedding FROM knowledge_units ku "
        "JOIN ku_embeddings emb ON emb.ku_id = ku.id "
        "WHERE ku.provenance_emergent = 1 AND ku.first_observed > ?",
        [dedupe_cutoff],
    ).fetchall()
    existing_embeddings = [
        _deserialize_f32(row["embedding"]) for row in existing_rows
    ]

    emitted: list[str] = []
    for cluster in _cluster_misses(misses):
        if len(cluster) < settings.emergent_min_misses:
            continue
        if _session_buckets(cluster) < settings.emergent_min_sessions:
            continue

        # Dedupe against recently-emitted emergent KUs
        centroid = cluster[0]["embedding"]
        if any(_cosine(centroid, e) >= _COSINE_THRESHOLD for e in existing_embeddings):
            continue

        ku_id = _emit_tool_gap_signal(store, db, cluster, now)
        if ku_id:
            emitted.append(ku_id)

    return emitted


def _emit_tool_gap_signal(store, db, cluster: list[dict], now: datetime) -> str | None:
    """Create a new tool-gap-signal KU from a cluster."""
    first_text = cluster[0]["text"]
    summary = (
        f"Emergent tool-gap: agents keep searching for '{first_text[:80]}' "
        f"with no matching KU"
    )[:280]
    detail = (
        f"Aggregated from {len(cluster)} recent query misses across "
        f"{_session_buckets(cluster)} distinct time buckets. "
        f"Representative queries:\n"
    )
    for m in cluster[:5]:
        detail += f"- {m['text'][:120]}\n"
    action = (
        "Investigate whether a covering KU should exist, or propose one via "
        "propose(kind='pitfall' or 'workaround' or 'tool-recommendation')."
    )

    ku_id = f"ku_{secrets.token_hex(16)}"
    ts = now.isoformat()
    db.execute(
        """
        INSERT INTO knowledge_units (
            id, version, domains, summary, detail, action,
            confidence, confirmations, contributing_orgs,
            first_observed, last_confirmed_at,
            kind, status, staleness_policy, related, graduated_to_team,
            evidence_severity, context_languages, context_frameworks,
            context_environment, context_pattern,
            proposer_did, owner_org, graduation_history, provenance_emergent,
            superseded_by
        ) VALUES (?, 1, ?, ?, ?, ?, 0.5, 0, '[]', ?, ?, 'tool-gap-signal',
                  'draft', 'confirm_or_decay_after_90d', '[]', 0,
                  'medium', '[]', '[]', NULL, NULL,
                  ?, ?, '[]', 1, NULL)
        """,
        [
            ku_id,
            json.dumps(["emergent"]),
            summary,
            detail,
            action,
            ts,
            ts,
            store.install_did,
            store.install_did,
        ],
    )

    # FTS row
    rowid = db.execute(
        "SELECT rowid FROM knowledge_units WHERE id = ?", [ku_id]
    ).fetchone()[0]
    db.execute(
        "INSERT INTO ku_fts(rowid, id, summary, detail, action) VALUES (?, ?, ?, ?, ?)",
        [rowid, ku_id, summary, detail, action],
    )

    # Use the cluster centroid as the emergent KU's embedding so dedupe works.
    from stolperfalle.store import _serialize_f32
    db.execute(
        "INSERT INTO ku_embeddings(ku_id, embedding) VALUES (?, ?)",
        [ku_id, _serialize_f32(cluster[0]["embedding"])],
    )

    db.commit()
    logger.info("Emitted emergent tool-gap-signal KU %s from %d misses", ku_id, len(cluster))
    return ku_id
