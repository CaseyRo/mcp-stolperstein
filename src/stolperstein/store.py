"""SQLite storage layer — CRUD, FTS5, sqlite-vec, lifecycle, visibility filter.

Schema evolution goes through `stolperstein.migrations`. This module is the
read/write layer that sits on top of the migrated shape.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
import struct
from datetime import datetime, timezone
from statistics import median

import sqlite_vec
from fastmcp.exceptions import ToolError

from stolperstein import migrations
from stolperstein.confidence import calculate_confidence
from stolperstein.config import settings
from stolperstein.models import (
    Context,
    Evidence,
    GraduationEntry,
    Insight,
    KnowledgeUnit,
    KUCreate,
    KUKind,
    KURelation,
    KUResponse,
    KUSeverity,
    KUStatus,
    Provenance,
    StoreStatus,
)
from stolperstein.provenance import get_or_create_install_did

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2
_KU_ID_STRICT = re.compile(r"^ku_[0-9a-f]{32}$")


def _serialize_f32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def _generate_ku_id() -> str:
    return f"ku_{secrets.token_hex(16)}"  # 32 hex chars — upstream-conformant


def _parse_staleness_days(policy: str) -> int:
    try:
        return int(policy.split("_")[-1].rstrip("d"))
    except (ValueError, IndexError):
        return 90


class KnowledgeStore:
    """SQLite-backed knowledge unit store."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: sqlite3.Connection | None = None
        self._embeddings = None
        self._install_did: str | None = None

    def _get_db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = sqlite3.connect(self._db_path)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.enable_load_extension(True)
            sqlite_vec.load(self._db)
            self._db.enable_load_extension(False)
            self._init_baseline()
            migrations.run(self._db, db_path=self._db_path)
            self._install_did = self._read_install_did()
        return self._db

    def _init_baseline(self) -> None:
        """Create the v0-baseline tables if they don't exist. Migrations then
        transform them to current (v6). For fresh installs this plus the
        full migration chain converges to the current schema in one connect.
        """
        db = self._db
        assert db is not None
        db.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_units (
                id TEXT PRIMARY KEY,
                version INTEGER NOT NULL DEFAULT 1,
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
        db.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS ku_embeddings USING vec0(
                ku_id TEXT PRIMARY KEY,
                embedding float[{EMBEDDING_DIM}]
            )
        """)
        db.commit()

    def _read_install_did(self) -> str:
        """Return the install's DID. Must be called after migrations ran."""
        assert self._db is not None
        row = self._db.execute(
            "SELECT did FROM install_identity LIMIT 1"
        ).fetchone()
        if row is not None:
            return row["did"]
        # Fallback: generate now (migration didn't run yet or install_identity missing)
        return get_or_create_install_did(self._db)

    @property
    def install_did(self) -> str:
        if self._install_did is None:
            self._get_db()
        assert self._install_did is not None
        return self._install_did

    def _get_embedder(self):
        if self._embeddings is None:
            from stolperstein.embeddings import get_embedder
            self._embeddings = get_embedder()
        return self._embeddings

    # --- row → model ---

    def _row_to_ku(self, row: sqlite3.Row) -> KnowledgeUnit:
        ctx = Context(
            languages=json.loads(row["context_languages"] or "[]"),
            frameworks=json.loads(row["context_frameworks"] or "[]"),
            environment=row["context_environment"],
            pattern=row["context_pattern"],
        )
        ev = Evidence(
            confidence=row["confidence"],
            confirmations=row["confirmations"],
            first_observed=_parse_dt(row["first_observed"]),
            last_confirmed=_parse_dt(row["last_confirmed_at"]),
            contributing_orgs=json.loads(row["contributing_orgs"] or "[]"),
            severity=KUSeverity(row["evidence_severity"]),
        )
        grad_raw = json.loads(row["graduation_history"] or "[]")
        grad_history = [
            GraduationEntry(
                timestamp=_parse_dt(g["timestamp"]),
                target=g["target"],
                reviewer_did=g["reviewer_did"],
                agent=g.get("agent", True),
            )
            for g in grad_raw
        ]
        emergent = row["provenance_emergent"]
        prov = Provenance(
            proposer_did=row["proposer_did"],
            graduation_history=grad_history,
            emergent=(bool(emergent) if emergent is not None else None),
        )
        return KnowledgeUnit(
            id=row["id"],
            version=int(row["version"]) if str(row["version"]).isdigit() else 1,
            domains=json.loads(row["domains"]),
            insight=Insight(
                summary=row["summary"],
                detail=row["detail"],
                action=row["action"],
            ),
            context=ctx,
            evidence=ev,
            kind=KUKind(row["kind"]),
            status=KUStatus(row["status"]),
            superseded_by=row["superseded_by"],
            flags=[],  # flags are not stored in this schema yet — future enhancement
            provenance=prov,
            owner_org=row["owner_org"],
            staleness_policy=row["staleness_policy"],
            related=[KURelation(**r) for r in json.loads(row["related"] or "[]")],
            last_queried_at=_parse_dt(row["last_queried_at"]) if row["last_queried_at"] else None,
            graduated_to_team=bool(row["graduated_to_team"]),
        )

    # --- propose ---

    async def propose(
        self,
        summary: str,
        detail: str,
        action: str,
        domains: list[str] | None = None,
        kind: str = "pitfall",
        context_languages: list[str] | None = None,
        context_frameworks: list[str] | None = None,
        context_environment: str | None = None,
        context_pattern: str | None = None,
        severity: str = "medium",
        staleness_policy: str = "confirm_or_decay_after_90d",
        domain: list[str] | None = None,  # legacy alias for `domains`
    ) -> dict:
        """Create a new KU. Rejects `kind='gap-signal'` with recovery hint.

        `domain` is accepted as a legacy alias for `domains` and silently promoted.
        """
        db = self._get_db()
        if domains is None and domain is not None:
            domains = domain
        if not domains:
            raise ToolError("domains (non-empty list) is required")

        if kind == "gap-signal":
            raise ToolError(
                "kind 'gap-signal' is no longer proposable in CQ v1. "
                "Tool gaps are detected automatically from query-miss patterns. "
                "To capture this insight, use kind='workaround' or kind='pitfall' "
                "and describe the gap in the detail field."
            )

        try:
            kind_enum = KUKind(kind)
        except ValueError:
            raise ToolError(
                f"Invalid kind '{kind}'. Must be one of: pitfall, workaround, "
                "tool-recommendation. (tool-gap-signal is emergent-only; "
                "gap-signal is deprecated — see query-miss patterns.)"
            )
        if kind_enum == KUKind.tool_gap_signal:
            raise ToolError(
                "kind 'tool-gap-signal' is emergent-only — produced by the "
                "aggregation job, never by propose(). Use 'workaround' or 'pitfall'."
            )

        try:
            severity_enum = KUSeverity(severity)
        except ValueError:
            raise ToolError(
                f"Invalid severity '{severity}'. Must be one of: low, medium, high, critical."
            )

        # Validate domains
        if not domains or not isinstance(domains, list):
            raise ToolError("domains must be a non-empty list of strings")

        # Build the input model (validates summary length, etc.)
        try:
            ku_input = KUCreate(
                summary=summary,
                detail=detail,
                action=action,
                domains=domains,
                kind=kind_enum,
                context_languages=context_languages or [],
                context_frameworks=context_frameworks or [],
                context_environment=context_environment,
                context_pattern=context_pattern,
                severity=severity_enum,
                staleness_policy=staleness_policy,
            )
        except Exception as e:
            raise ToolError(f"Invalid propose input: {e}")

        # Duplicate detection via embedding similarity
        duplicate_response = await self._check_duplicate(ku_input)
        if duplicate_response is not None:
            return duplicate_response

        # Insert
        ku_id = _generate_ku_id()
        now = datetime.now(timezone.utc).isoformat()
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
            ) VALUES (?, 1, ?, ?, ?, ?, 0.5, 0, '[]', ?, ?, ?, 'draft', ?, '[]', 0,
                      ?, ?, ?, ?, ?, ?, ?, '[]', NULL, NULL)
            """,
            [
                ku_id,
                json.dumps(ku_input.domains),
                ku_input.summary,
                ku_input.detail,
                ku_input.action,
                now,
                now,
                ku_input.kind.value,
                ku_input.staleness_policy,
                ku_input.severity.value,
                json.dumps(ku_input.context_languages),
                json.dumps(ku_input.context_frameworks),
                ku_input.context_environment,
                ku_input.context_pattern,
                self.install_did,
                self.install_did,
            ],
        )

        # FTS row
        rowid = db.execute(
            "SELECT rowid FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()[0]
        db.execute(
            "INSERT INTO ku_fts(rowid, id, summary, detail, action) VALUES (?, ?, ?, ?, ?)",
            [rowid, ku_id, ku_input.summary, ku_input.detail, ku_input.action],
        )

        # Embedding
        try:
            text = _embedding_text(ku_input.summary, ku_input.detail, ku_input.action,
                                   ku_input.context_pattern)
            embedding = await self._get_embedder().embed(text)
            if embedding:
                db.execute(
                    "INSERT INTO ku_embeddings(ku_id, embedding) VALUES (?, ?)",
                    [ku_id, _serialize_f32(embedding)],
                )
        except Exception:
            logger.warning("Embedding generation failed for %s, FTS only", ku_id, exc_info=True)

        db.commit()

        row = db.execute("SELECT * FROM knowledge_units WHERE id = ?", [ku_id]).fetchone()
        ku = self._row_to_ku(row)
        return KUResponse(ku=ku).model_dump(mode="json")

    async def _check_duplicate(self, ku_input: KUCreate) -> dict | None:
        db = self._db
        assert db is not None
        try:
            text = _embedding_text(ku_input.summary, ku_input.detail, ku_input.action,
                                   ku_input.context_pattern)
            embedding = await self._get_embedder().embed(text)
            if not embedding:
                return None
            dup_rows = db.execute(
                "SELECT ku_id, distance FROM ku_embeddings "
                "WHERE embedding MATCH ? AND k = 1 ORDER BY distance",
                [_serialize_f32(embedding)],
            ).fetchall()
            if dup_rows and dup_rows[0]["distance"] < 0.1:
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
        return None

    # --- query ---

    @staticmethod
    def _sanitize_fts_query(text: str) -> str | None:
        cleaned = re.sub(r"[^\w\s]", "", text)
        terms = [t for t in cleaned.split() if t.strip()]
        if not terms:
            return None
        return " OR ".join(f'"{t}"' for t in terms)

    def _visibility_filter_sql(self) -> tuple[str, list]:
        """Return a WHERE fragment + params implementing TRUSTED_ORGS filter."""
        trusted = settings.trusted_orgs_list
        if "*" in trusted:
            return "", []
        # Own install always visible. Plus explicit trusted list.
        placeholders = ",".join(["?"] * len(trusted))
        sql = f"(ku.owner_org = ? OR ku.owner_org IN ({placeholders}))"
        params: list = [self.install_did] + trusted
        return sql, params

    async def query(
        self,
        text: str,
        domain: list[str] | None = None,
        confidence_min: float = 0.3,
        limit: int = 10,
    ) -> dict:
        """Hybrid search: FTS5 + vec cosine, severity tiebreaker, TRUSTED_ORGS visibility."""
        db = self._get_db()
        vis_sql, vis_params = self._visibility_filter_sql()
        vis_where = f" AND {vis_sql}" if vis_sql else ""

        results: dict[str, dict] = {}

        fts_query = self._sanitize_fts_query(text)
        if fts_query:
            try:
                fts_rows = db.execute(
                    f"""
                    SELECT ku.*, bm25(ku_fts) as rank
                    FROM ku_fts
                    JOIN knowledge_units ku ON ku.id = ku_fts.id
                    WHERE ku_fts MATCH ?
                      AND ku.status NOT IN ('archived')
                      AND ku.confidence >= ?{vis_where}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    [fts_query, confidence_min, *vis_params, limit * 2],
                ).fetchall()
                for row in fts_rows:
                    ku = self._row_to_ku(row)
                    fts_score = -row["rank"] if row["rank"] else 0.0
                    results[ku.id] = {"ku": ku, "fts_score": fts_score, "vec_score": 0.0}
            except Exception:
                logger.warning("FTS5 query failed for: %s", fts_query, exc_info=True)

        query_embedding = None
        try:
            query_embedding = await self._get_embedder().embed(text)
            if query_embedding:
                vec_rows = db.execute(
                    "SELECT ku_id, distance FROM ku_embeddings "
                    "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
                    [_serialize_f32(query_embedding), limit * 2],
                ).fetchall()
                for vrow in vec_rows:
                    ku_id = vrow["ku_id"]
                    vec_score = max(0.0, 1.0 - vrow["distance"])
                    if ku_id in results:
                        results[ku_id]["vec_score"] = vec_score
                    else:
                        row = db.execute(
                            f"""
                            SELECT * FROM knowledge_units ku
                            WHERE ku.id = ? AND ku.status != 'archived' AND ku.confidence >= ?
                            {vis_where}
                            """,
                            [ku_id, confidence_min, *vis_params],
                        ).fetchone()
                        if row:
                            ku = self._row_to_ku(row)
                            results[ku_id] = {"ku": ku, "fts_score": 0.0, "vec_score": vec_score}
        except Exception:
            logger.warning("Vector search failed, using FTS only", exc_info=True)

        # Domain filter (client-side intersection on JSON array)
        if domain:
            domain_set = set(domain)
            results = {
                k: v for k, v in results.items()
                if domain_set.intersection(v["ku"].domains)
            }

        # Rank: combined score + severity tiebreaker
        max_fts = max((r["fts_score"] for r in results.values()), default=1.0) or 1.0
        ranked = sorted(
            results.values(),
            key=lambda r: (
                (r["fts_score"] / max_fts) * 0.5 + r["vec_score"] * 0.5,
                _severity_rank(r["ku"].evidence.severity),
            ),
            reverse=True,
        )[:limit]

        # Update last_queried_at
        now = datetime.now(timezone.utc).isoformat()
        for r in ranked:
            db.execute(
                "UPDATE knowledge_units SET last_queried_at = ? WHERE id = ?",
                [now, r["ku"].id],
            )
        if ranked:
            db.commit()

        # Record miss for emergent detection if zero results
        if not ranked:
            try:
                embedding_blob = (
                    _serialize_f32(query_embedding) if query_embedding else None
                )
                db.execute(
                    "INSERT INTO query_misses (text, embedding, created_at) VALUES (?, ?, ?)",
                    [text[:512], embedding_blob, now],
                )
                db.commit()
                self._maybe_trigger_emergent()
            except Exception:
                logger.warning("Failed to record query miss", exc_info=True)

        return {
            "results": [r["ku"].model_dump(mode="json") for r in ranked],
            "count": len(ranked),
        }

    def _maybe_trigger_emergent(self) -> None:
        """Every Nth miss, fire background aggregation. Fire-and-forget."""
        if settings.stolperstein_emergent_disabled:
            return
        every_n = max(0, settings.emergent_detect_every_n)
        if every_n == 0:
            return
        db = self._db
        assert db is not None
        total = db.execute("SELECT COUNT(*) FROM query_misses").fetchone()[0]
        if total % every_n != 0:
            return
        try:
            import asyncio
            from stolperstein.emergent import detect_emergent

            async def _run() -> None:
                # detect_emergent is sync but may do IO; run in default executor.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, detect_emergent, self)

            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            # No running loop (e.g. CLI context) — no background trigger.
            logger.debug("No event loop for emergent trigger; skipping background run")
        except Exception:
            logger.warning("Failed to launch emergent trigger", exc_info=True)

    # --- confirm ---

    async def confirm(self, ku_id: str) -> dict:
        db = self._get_db()
        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        if not row:
            raise ToolError(
                f"KU not found: {ku_id}. Call query() first to obtain a valid ku_id."
            )

        ku = self._row_to_ku(row)
        now = datetime.now(timezone.utc)
        new_confirmations = ku.evidence.confirmations + 1

        new_status = ku.status
        if ku.status in (KUStatus.draft, KUStatus.stale):
            new_status = KUStatus.active

        staleness_days = _parse_staleness_days(ku.staleness_policy)
        # Count distinct orgs among contributing (ensure current install counted)
        contributors = set(ku.evidence.contributing_orgs)
        contributors.add(self.install_did)
        distinct_orgs = len(contributors) or 1
        new_confidence = calculate_confidence(
            base=0.5,
            confirmations=new_confirmations,
            contributing_orgs_count=distinct_orgs,
            last_confirmed=now,
            staleness_days=staleness_days,
            is_disputed=new_status == KUStatus.disputed,
            severity=ku.evidence.severity,
        )

        db.execute(
            """
            UPDATE knowledge_units
            SET confirmations = ?, last_confirmed_at = ?, confidence = ?,
                status = ?, contributing_orgs = ?
            WHERE id = ?
            """,
            [
                new_confirmations, now.isoformat(), new_confidence,
                new_status.value, json.dumps(sorted(contributors)), ku_id,
            ],
        )
        db.commit()

        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        return KUResponse(ku=self._row_to_ku(row)).model_dump(mode="json")

    # --- flag ---

    async def flag(
        self,
        ku_id: str,
        reason: str,
        detail: str = "",
        superseded_by: str | None = None,
    ) -> dict:
        db = self._get_db()
        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        if not row:
            raise ToolError(
                f"KU not found: {ku_id}. Call query() first to obtain a valid ku_id."
            )

        ku = self._row_to_ku(row)

        if reason == "superseded":
            if not superseded_by:
                raise ToolError(
                    "flag(reason='superseded') requires superseded_by=<ku_id>"
                )
            new_status = KUStatus.archived
            db.execute(
                "UPDATE knowledge_units SET status = ?, superseded_by = ? WHERE id = ?",
                [new_status.value, superseded_by, ku_id],
            )
        elif reason in ("incorrect", "dangerous"):
            new_status = KUStatus.disputed
            new_confidence = min(ku.evidence.confidence, 0.5)
            db.execute(
                "UPDATE knowledge_units SET status = ?, confidence = ? WHERE id = ?",
                [new_status.value, new_confidence, ku_id],
            )
        elif reason == "stale":
            new_status = KUStatus.stale
            db.execute(
                "UPDATE knowledge_units SET status = ? WHERE id = ?",
                [new_status.value, ku_id],
            )
        elif reason == "duplicate":
            new_status = KUStatus.archived
            db.execute(
                "UPDATE knowledge_units SET status = ?, superseded_by = ? WHERE id = ?",
                [new_status.value, superseded_by, ku_id],
            )
        else:
            raise ToolError(
                f"Invalid reason '{reason}'. Must be one of: stale, incorrect, "
                "superseded, dangerous, duplicate."
            )

        db.commit()

        row = db.execute(
            "SELECT * FROM knowledge_units WHERE id = ?", [ku_id]
        ).fetchone()
        ku = self._row_to_ku(row)
        msg = f"Flagged as {reason}" + (f": {detail}" if detail else "")
        if superseded_by:
            msg += f" (superseded by {superseded_by})"
        return KUResponse(ku=ku, message=msg).model_dump(mode="json")

    # --- status ---

    async def status(self, debug: bool = False) -> dict:
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

        now = datetime.now(timezone.utc)
        active_rows = db.execute(
            "SELECT last_confirmed_at, staleness_policy FROM knowledge_units "
            "WHERE status = 'active'"
        ).fetchall()
        approaching = 0
        past = 0
        for row in active_rows:
            last = _parse_dt(row["last_confirmed_at"])
            threshold = _parse_staleness_days(row["staleness_policy"])
            days_since = (now - last).days
            if days_since > threshold:
                past += 1
            elif days_since > threshold * 0.75:
                approaching += 1

        # tool-gap-signal partition
        tgs_rows = db.execute(
            "SELECT provenance_emergent, COUNT(*) as cnt FROM knowledge_units "
            "WHERE kind = 'tool-gap-signal' GROUP BY provenance_emergent"
        ).fetchall()
        tgs_counts = {"grandfathered": 0, "emergent": 0}
        for row in tgs_rows:
            if row["provenance_emergent"] == 1:
                tgs_counts["emergent"] = row["cnt"]
            else:
                tgs_counts["grandfathered"] += row["cnt"]

        result = StoreStatus(
            total=total,
            by_status=by_status,
            confidence_distribution=conf_dist,
            staleness={"approaching_threshold": approaching, "past_threshold": past},
            tool_gap_signals=tgs_counts,
        ).model_dump()

        if debug:
            result["schema_version"] = migrations.current_version(db)
            result["proposer_did"] = self.install_did
            result["applied_migrations"] = [m.id for m in migrations.registered()]

            org_rows = db.execute(
                "SELECT owner_org, COUNT(*) as cnt FROM knowledge_units "
                "GROUP BY owner_org ORDER BY cnt DESC LIMIT 20"
            ).fetchall()
            result["by_owner_org"] = {row["owner_org"]: row["cnt"] for row in org_rows}

            recent_rows = db.execute(
                "SELECT id FROM knowledge_units WHERE provenance_emergent = 1 "
                "ORDER BY first_observed DESC LIMIT 10"
            ).fetchall()
            result["recent_emergent"] = [row["id"] for row in recent_rows]

            miss_count = db.execute(
                "SELECT COUNT(*) FROM query_misses "
                "WHERE created_at > datetime('now', '-30 days')"
            ).fetchone()[0]
            result["query_misses_window"] = miss_count

        return result


# --- helpers ---

def _parse_dt(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _severity_rank(sev: KUSeverity) -> int:
    """Rank critical > high > medium > low (higher first)."""
    return {
        KUSeverity.critical: 3,
        KUSeverity.high: 2,
        KUSeverity.medium: 1,
        KUSeverity.low: 0,
    }[sev]


def _embedding_text(summary: str, detail: str, action: str, pattern: str | None) -> str:
    parts = [summary, detail, action]
    if pattern:
        parts.append(pattern)
    return " ".join(parts)


# Module-level singleton
store = KnowledgeStore(settings.cq_local_db_path)
