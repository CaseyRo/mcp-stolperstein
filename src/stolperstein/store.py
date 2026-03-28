"""SQLite storage layer — CRUD, FTS5, sqlite-vec, and lifecycle operations."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import struct
from datetime import datetime, timezone
from statistics import median

import sqlite_vec

from stolperstein.confidence import calculate_confidence
from stolperstein.config import settings
from stolperstein.models import (
    Insight,
    KnowledgeUnit,
    KUCreate,
    KUKind,
    KURelation,
    KUResponse,
    KUStatus,
    StoreStatus,
)

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def _serialize_f32(vector: list[float]) -> bytes:
    """Serialize a list of floats to compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)


def _generate_ku_id() -> str:
    return f"ku_{secrets.token_hex(12)}"


def _parse_staleness_days(policy: str) -> int:
    """Extract days from staleness policy string like 'confirm_or_decay_after_90d'."""
    try:
        return int(policy.split("_")[-1].rstrip("d"))
    except (ValueError, IndexError):
        return 90


class KnowledgeStore:
    """SQLite-backed knowledge unit store with FTS5 and vector search."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: sqlite3.Connection | None = None
        self._embeddings = None

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self._db_path)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.enable_load_extension(True)
            sqlite_vec.load(self._db)
            self._db.enable_load_extension(False)
            self._init_db()
        return self._db

    def _init_db(self) -> None:
        db = self._db
        db.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_units (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL DEFAULT '1.0.0',
                domain TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL,
                detail TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                confirmations INTEGER NOT NULL DEFAULT 0,
                contributing_orgs TEXT NOT NULL DEFAULT '[]',
                first_observed TEXT NOT NULL,
                last_confirmed TEXT NOT NULL,
                last_queried_at TEXT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                staleness_policy TEXT NOT NULL DEFAULT 'confirm_or_decay_after_90d',
                related TEXT NOT NULL DEFAULT '[]',
                graduated_to_team INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_ku_status ON knowledge_units(status);
            CREATE INDEX IF NOT EXISTS idx_ku_confidence ON knowledge_units(confidence);
        """)

        # FTS5 virtual table
        db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS ku_fts USING fts5(
                id UNINDEXED,
                summary,
                detail,
                action,
                content=knowledge_units,
                content_rowid=rowid
            )
        """)

        # sqlite-vec virtual table
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS ku_embeddings USING vec0(
                ku_id TEXT PRIMARY KEY,
                embedding float[{EMBEDDING_DIM}]
            )
        """)

    def _get_embedder(self):
        """Lazy-load the embedding provider."""
        if self._embeddings is None:
            from stolperstein.embeddings import get_embedder

            self._embeddings = get_embedder()
        return self._embeddings

    def _row_to_ku(self, row: sqlite3.Row) -> KnowledgeUnit:
        return KnowledgeUnit(
            id=row["id"],
            version=row["version"],
            domain=json.loads(row["domain"]),
            insight=Insight(
                summary=row["summary"],
                detail=row["detail"],
                action=row["action"],
            ),
            confidence=row["confidence"],
            confirmations=row["confirmations"],
            contributing_orgs=json.loads(row["contributing_orgs"]),
            first_observed=datetime.fromisoformat(row["first_observed"]),
            last_confirmed=datetime.fromisoformat(row["last_confirmed"]),
            last_queried_at=(
                datetime.fromisoformat(row["last_queried_at"])
                if row["last_queried_at"]
                else None
            ),
            kind=KUKind(row["kind"]),
            status=KUStatus(row["status"]),
            staleness_policy=row["staleness_policy"],
            related=[
                KURelation(**r) for r in json.loads(row["related"])
            ],
            graduated_to_team=bool(row["graduated_to_team"]),
        )

    async def propose(
        self,
        summary: str,
        detail: str,
        action: str,
        domain: list[str],
        kind: str,
        staleness_policy: str = "confirm_or_decay_after_90d",
    ) -> dict:
        """Create a new Knowledge Unit."""
        db = self._get_db()
        ku_input = KUCreate(
            summary=summary,
            detail=detail,
            action=action,
            domain=domain,
            kind=KUKind(kind),
            staleness_policy=staleness_policy,
        )

        # Check for duplicates via embedding similarity
        try:
            embedder = self._get_embedder()
            text = f"{summary} {detail} {action}"
            embedding = await embedder.embed(text)

            if embedding:
                dup_rows = db.execute(
                    """
                    SELECT ku_id, distance
                    FROM ku_embeddings
                    WHERE embedding MATCH ?
                      AND k = 1
                    ORDER BY distance
                    """,
                    [_serialize_f32(embedding)],
                ).fetchall()

                if dup_rows and dup_rows[0]["distance"] < 0.1:  # cosine distance < 0.1 ≈ similarity > 0.9
                    dup_id = dup_rows[0]["ku_id"]
                    dup_row = db.execute(
                        "SELECT * FROM knowledge_units WHERE id = ? AND status != 'archived'",
                        [dup_id],
                    ).fetchone()
                    if dup_row:
                        ku = self._row_to_ku(dup_row)
                        return KUResponse(
                            ku=ku, duplicate_of=dup_id, message="Duplicate detected"
                        ).model_dump(mode="json")
        except Exception:
            logger.warning("Duplicate check failed, proceeding with creation", exc_info=True)

        # Create the KU
        ku_id = _generate_ku_id()
        now = datetime.now(timezone.utc).isoformat()

        db.execute(
            """
            INSERT INTO knowledge_units
                (id, domain, summary, detail, action, confidence, confirmations,
                 contributing_orgs, first_observed, last_confirmed, kind, status,
                 staleness_policy, related)
            VALUES (?, ?, ?, ?, ?, 0.5, 0, '[]', ?, ?, ?, 'draft', ?, '[]')
            """,
            [
                ku_id,
                json.dumps(ku_input.domain),
                ku_input.summary,
                ku_input.detail,
                ku_input.action,
                now,
                now,
                ku_input.kind.value,
                ku_input.staleness_policy,
            ],
        )

        # Sync FTS
        rowid = db.execute(
            "SELECT rowid FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()[0]
        db.execute(
            "INSERT INTO ku_fts(rowid, id, summary, detail, action) VALUES (?, ?, ?, ?, ?)",
            [rowid, ku_id, ku_input.summary, ku_input.detail, ku_input.action],
        )

        # Generate and store embedding
        try:
            embedder = self._get_embedder()
            text = f"{ku_input.summary} {ku_input.detail} {ku_input.action}"
            embedding = await embedder.embed(text)
            if embedding:
                db.execute(
                    "INSERT INTO ku_embeddings(ku_id, embedding) VALUES (?, ?)",
                    [ku_id, _serialize_f32(embedding)],
                )
        except Exception:
            logger.warning("Embedding generation failed for %s, FTS only", ku_id, exc_info=True)

        db.commit()

        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        ku = self._row_to_ku(row)
        return KUResponse(ku=ku).model_dump(mode="json")

    async def query(
        self,
        text: str,
        domain: list[str] | None = None,
        confidence_min: float = 0.3,
        limit: int = 10,
    ) -> dict:
        """Hybrid search: FTS5 + sqlite-vec cosine similarity."""
        db = self._get_db()
        results: dict[str, dict] = {}

        # FTS5 keyword search
        fts_query = text.replace('"', '""')
        try:
            fts_rows = db.execute(
                """
                SELECT ku.*, bm25(ku_fts) as rank
                FROM ku_fts
                JOIN knowledge_units ku ON ku.id = ku_fts.id
                WHERE ku_fts MATCH ?
                  AND ku.status NOT IN ('archived')
                  AND ku.confidence >= ?
                ORDER BY rank
                LIMIT ?
                """,
                [fts_query, confidence_min, limit * 2],
            ).fetchall()

            for row in fts_rows:
                ku = self._row_to_ku(row)
                # bm25 returns negative scores (more negative = more relevant)
                fts_score = -row["rank"] if row["rank"] else 0.0
                results[ku.id] = {"ku": ku, "fts_score": fts_score, "vec_score": 0.0}
        except Exception:
            logger.warning("FTS5 query failed", exc_info=True)

        # Vector similarity search
        try:
            embedder = self._get_embedder()
            embedding = await embedder.embed(text)
            if embedding:
                vec_rows = db.execute(
                    """
                    SELECT ku_id, distance
                    FROM ku_embeddings
                    WHERE embedding MATCH ?
                      AND k = ?
                    ORDER BY distance
                    """,
                    [_serialize_f32(embedding), limit * 2],
                ).fetchall()

                for vrow in vec_rows:
                    ku_id = vrow["ku_id"]
                    # cosine distance -> similarity score (1 - distance)
                    vec_score = max(0.0, 1.0 - vrow["distance"])

                    if ku_id in results:
                        results[ku_id]["vec_score"] = vec_score
                    else:
                        row = db.execute(
                            "SELECT * FROM knowledge_units WHERE id = ? AND status != 'archived' AND confidence >= ?",
                            [ku_id, confidence_min],
                        ).fetchone()
                        if row:
                            ku = self._row_to_ku(row)
                            results[ku_id] = {"ku": ku, "fts_score": 0.0, "vec_score": vec_score}
        except Exception:
            logger.warning("Vector search failed, using FTS only", exc_info=True)

        # Domain filter
        if domain:
            domain_set = set(domain)
            results = {
                k: v
                for k, v in results.items()
                if domain_set.intersection(v["ku"].domain)
            }

        # Combined ranking: weighted sum (FTS normalized + vec score)
        max_fts = max((r["fts_score"] for r in results.values()), default=1.0) or 1.0
        ranked = sorted(
            results.values(),
            key=lambda r: (r["fts_score"] / max_fts) * 0.5 + r["vec_score"] * 0.5,
            reverse=True,
        )[:limit]

        # Update last_queried_at for returned KUs
        now = datetime.now(timezone.utc).isoformat()
        for r in ranked:
            db.execute(
                "UPDATE knowledge_units SET last_queried_at = ? WHERE id = ?",
                [now, r["ku"].id],
            )
        if ranked:
            db.commit()

        return {
            "results": [
                r["ku"].model_dump(mode="json") for r in ranked
            ],
            "count": len(ranked),
        }

    async def confirm(self, ku_id: str) -> dict:
        """Confirm a KU — increment confirmations and recalculate confidence."""
        db = self._get_db()
        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()

        if not row:
            raise ValueError(f"KU not found: {ku_id}")

        ku = self._row_to_ku(row)
        now = datetime.now(timezone.utc)
        new_confirmations = ku.confirmations + 1

        # Draft -> active on first confirmation
        new_status = ku.status
        if ku.status == KUStatus.draft:
            new_status = KUStatus.active
        elif ku.status == KUStatus.stale:
            new_status = KUStatus.active

        staleness_days = _parse_staleness_days(ku.staleness_policy)
        new_confidence = calculate_confidence(
            base=0.5,
            confirmations=new_confirmations,
            contributing_orgs_count=len(ku.contributing_orgs) or 1,
            last_confirmed=now,
            staleness_days=staleness_days,
            is_disputed=new_status == KUStatus.disputed,
        )

        db.execute(
            """
            UPDATE knowledge_units
            SET confirmations = ?, last_confirmed = ?, confidence = ?, status = ?
            WHERE id = ?
            """,
            [new_confirmations, now.isoformat(), new_confidence, new_status.value, ku_id],
        )
        db.commit()

        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        ku = self._row_to_ku(row)
        return KUResponse(ku=ku).model_dump(mode="json")

    async def flag(
        self,
        ku_id: str,
        reason: str,
        detail: str = "",
        superseded_by: str | None = None,
    ) -> dict:
        """Flag a KU as disputed, stale, or archived."""
        db = self._get_db()
        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()

        if not row:
            raise ValueError(f"KU not found: {ku_id}")

        ku = self._row_to_ku(row)

        if reason == "superseded" and superseded_by:
            new_status = KUStatus.archived
            related = ku.related + [
                KURelation(type="superseded_by", target_id=superseded_by)
            ]
        elif reason in ("incorrect", "dangerous"):
            new_status = KUStatus.disputed
            related = ku.related
        elif reason == "stale":
            new_status = KUStatus.stale
            related = ku.related
        else:
            new_status = KUStatus.disputed
            related = ku.related

        # Cap confidence at 0.5 for disputed
        new_confidence = min(ku.confidence, 0.5) if new_status == KUStatus.disputed else ku.confidence

        db.execute(
            """
            UPDATE knowledge_units
            SET status = ?, confidence = ?, related = ?
            WHERE id = ?
            """,
            [new_status.value, new_confidence, json.dumps([r.model_dump() for r in related]), ku_id],
        )
        db.commit()

        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        ku = self._row_to_ku(row)
        resp = KUResponse(ku=ku, message=f"Flagged as {reason}: {detail}" if detail else f"Flagged as {reason}")

        if superseded_by:
            sup_row = db.execute(
                "SELECT * FROM knowledge_units WHERE id = ?", [superseded_by]
            ).fetchone()
            if sup_row:
                resp.message += f" (superseded by {superseded_by})"

        return resp.model_dump(mode="json")

    async def status(self) -> dict:
        """Aggregate store statistics."""
        db = self._get_db()

        total = db.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]

        status_rows = db.execute(
            "SELECT status, COUNT(*) as cnt FROM knowledge_units GROUP BY status"
        ).fetchall()
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        conf_rows = db.execute(
            "SELECT confidence FROM knowledge_units WHERE status != 'archived'"
        ).fetchall()
        confidences = [row["confidence"] for row in conf_rows]

        if confidences:
            confidences_sorted = sorted(confidences)
            n = len(confidences_sorted)
            conf_dist = {
                "mean": round(sum(confidences) / n, 3),
                "median": round(median(confidences), 3),
                "p25": round(confidences_sorted[n // 4], 3),
                "p75": round(confidences_sorted[(3 * n) // 4], 3),
            }
        else:
            conf_dist = {"mean": 0.0, "median": 0.0, "p25": 0.0, "p75": 0.0}

        # Staleness metrics
        now = datetime.now(timezone.utc)
        active_rows = db.execute(
            "SELECT last_confirmed, staleness_policy FROM knowledge_units WHERE status = 'active'"
        ).fetchall()

        approaching = 0
        past = 0
        for row in active_rows:
            last = datetime.fromisoformat(row["last_confirmed"])
            threshold = _parse_staleness_days(row["staleness_policy"])
            days_since = (now - last).days
            if days_since > threshold:
                past += 1
            elif days_since > threshold * 0.75:
                approaching += 1

        return StoreStatus(
            total=total,
            by_status=by_status,
            confidence_distribution=conf_dist,
            staleness={"approaching_threshold": approaching, "past_threshold": past},
        ).model_dump()


# Module-level singleton
store = KnowledgeStore(settings.cq_local_db_path)
