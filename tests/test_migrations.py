"""Migration framework tests.

The fixture is built programmatically rather than checked in as a binary —
keeps the v0 shape visible at the top of the file and stays stable across
SQLite versions.
"""

from __future__ import annotations

import json
import sqlite3

import jsonschema
import pytest

from stolperstein import migrations


_V0_SCHEMA_DDL = """
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
"""


@pytest.fixture
def v0_db(tmp_path):
    """Build a v0-shaped SQLite DB with representative rows and return the path."""
    db_path = str(tmp_path / "v0.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_V0_SCHEMA_DDL)

    # Row with 24-hex id, gap-signal kind, superseded_by in related[].
    conn.execute(
        "INSERT INTO knowledge_units (id, domain, summary, detail, action, "
        "first_observed, last_confirmed, kind, related) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            "ku_a1b2c3d4e5f6a1b2c3d4e5f6",  # 24 hex
            '["swift"]',
            "old summary", "old detail", "old action",
            "2026-03-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00",
            "gap-signal",
            '[{"type":"superseded_by","target_id":"ku_999fff999fff999fff999fff"}]',
        ],
    )
    # Row referenced by the first — also 24 hex.
    conn.execute(
        "INSERT INTO knowledge_units (id, domain, summary, detail, action, "
        "first_observed, last_confirmed, kind, related) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            "ku_999fff999fff999fff999fff",
            '["swift"]',
            "new summary", "new detail", "new action",
            "2026-03-02T00:00:00+00:00", "2026-03-02T00:00:00+00:00",
            "pitfall",
            "[]",
        ],
    )
    conn.commit()
    conn.close()
    return db_path


def _open(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_fresh_db_goes_to_current_version(tmp_path):
    """Fresh install: no baseline needed, migrations apply cleanly."""
    db_path = str(tmp_path / "fresh.db")
    conn = _open(db_path)
    conn.executescript(_V0_SCHEMA_DDL)
    conn.commit()

    result = migrations.run(conn, db_path=db_path)
    assert result.from_version == 0
    assert result.to_version == 6
    assert len(result.applied) == 6


def test_v0_db_fully_migrates(v0_db):
    """Every v0 row survives, is conformant, and validates against upstream."""
    conn = _open(v0_db)
    result = migrations.run(conn, db_path=v0_db)
    assert result.to_version == 6

    rows = conn.execute("SELECT * FROM knowledge_units").fetchall()
    assert len(rows) == 2

    # All ids are now 32-hex.
    import re
    for row in rows:
        assert re.match(r"^ku_[0-9a-f]{32}$", row["id"]), row["id"]

    # gap-signal row became tool-gap-signal (grandfathered).
    gap_row = next(r for r in rows if r["summary"] == "old summary")
    assert gap_row["kind"] == "tool-gap-signal"
    assert gap_row["provenance_emergent"] == 0
    # superseded_by hoisted out of related[].
    assert gap_row["superseded_by"].startswith("ku_")
    assert len(gap_row["superseded_by"]) == 35  # ku_ + 32 hex
    assert json.loads(gap_row["related"]) == []
    # last_confirmed renamed and backfilled.
    assert gap_row["last_confirmed_at"] == "2026-03-01T00:00:00+00:00"

    # proposer_did + owner_org backfilled on every row.
    for row in rows:
        assert row["proposer_did"].startswith("did:key:z")
        assert row["owner_org"].startswith("did:key:z")

    # Every row's to_cq_json_strict() validates against vendored schema.
    from pathlib import Path
    from stolperstein.store import KnowledgeStore
    schema = json.loads(
        (Path(__file__).parent / "fixtures" / "cq" / "knowledge_unit.json").read_text()
    )
    # Build a store pointing at the migrated DB — reuses _row_to_ku.
    conn.close()
    s = KnowledgeStore(v0_db)
    db = s._get_db()
    for row in db.execute("SELECT * FROM knowledge_units").fetchall():
        ku = s._row_to_ku(row)
        jsonschema.validate(ku.to_cq_json_strict(), schema)


def test_migration_is_idempotent(v0_db):
    """Second run is a no-op."""
    conn = _open(v0_db)
    migrations.run(conn, db_path=v0_db)
    result2 = migrations.run(conn, db_path=v0_db)
    assert result2.from_version == 6
    assert result2.to_version == 6
    assert result2.applied == []


def test_breaking_migration_takes_snapshot(v0_db):
    """`.bak-pre-vN` is created for every breaking migration that runs."""
    from pathlib import Path
    conn = _open(v0_db)
    result = migrations.run(conn, db_path=v0_db)
    # Breaking migrations: versions 1, 2, 3, 4 (ku_id format fix, CQ rename,
    # extensions, provenance). Each takes its own pre-migration snapshot.
    for v in (1, 2, 3, 4):
        bak = Path(v0_db + f".bak-pre-v{v}")
        assert bak.exists(), f"expected snapshot {bak} missing"
    # No snapshot for the non-breaking ones.
    for v in (5, 6):
        bak = Path(v0_db + f".bak-pre-v{v}")
        assert not bak.exists()
    assert len(result.snapshots) == 4


def test_snapshot_refuses_overwrite(v0_db, tmp_path):
    """A pre-existing .bak-pre-v<N> blocks the migration with a clear error."""
    from pathlib import Path
    existing = Path(v0_db + ".bak-pre-v1")
    existing.write_text("pretend this is an older backup")
    conn = _open(v0_db)
    with pytest.raises(RuntimeError, match="already exists"):
        migrations.run(conn, db_path=v0_db)


def test_rollback_on_mid_migration_failure(v0_db, monkeypatch):
    """If a migration raises, schema_version stays at pre-migration value."""
    conn = _open(v0_db)

    # Sabotage m0003 to raise.
    original_run = migrations.run
    import stolperstein.migrations.m0003_stolperstein_extensions as m3
    original_up = m3.up

    def _sabotage(conn):  # noqa: F811 — intentional override
        original_up(conn)
        raise RuntimeError("simulated failure mid-migration")

    monkeypatch.setattr(m3, "up", _sabotage)

    with pytest.raises(RuntimeError, match="simulated failure"):
        original_run(conn, db_path=v0_db)

    # m0001 + m0002 should be applied; m0003 rolled back.
    assert migrations.current_version(conn) == 2
