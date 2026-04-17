"""Add Stolperstein extension columns (not in upstream CQ schema).

- `evidence_severity`: enum string, default `medium`, used for ranking
  tiebreaker and decay-floor adjustment.
- `context_environment`: build/runtime environment version scope.

Both are carried through `to_cq_json_rich()` and stripped by
`to_cq_json_strict()`. Registered in `docs/cq-extensions.md`.
"""

from __future__ import annotations

import sqlite3

version = 3
breaking = True
slug = "stolperstein_extensions"


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if row[1] == col:
            return True
    return False


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        [name],
    ).fetchone()
    return row is not None


def up(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "knowledge_units"):
        return
    if not _column_exists(conn, "knowledge_units", "evidence_severity"):
        conn.execute(
            "ALTER TABLE knowledge_units ADD COLUMN "
            "evidence_severity TEXT NOT NULL DEFAULT 'medium'"
        )
    if not _column_exists(conn, "knowledge_units", "context_environment"):
        conn.execute(
            "ALTER TABLE knowledge_units ADD COLUMN context_environment TEXT"
        )
