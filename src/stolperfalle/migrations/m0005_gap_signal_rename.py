"""Rewrite `kind='gap-signal'` rows to `kind='tool-gap-signal'` with
`provenance_emergent=0` (grandfathered — not produced by the emergent
aggregation job, but preserved as queryable content).

`gap-signal` is no longer accepted by `propose()` going forward; this
migration preserves every existing row's data untouched apart from the
taxonomy rename.
"""

from __future__ import annotations

import sqlite3

version = 5
breaking = False
slug = "gap_signal_rename"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        [name],
    ).fetchone()
    return row is not None


def up(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "knowledge_units"):
        return
    conn.execute(
        "UPDATE knowledge_units SET kind = 'tool-gap-signal', provenance_emergent = 0 "
        "WHERE kind = 'gap-signal'"
    )
