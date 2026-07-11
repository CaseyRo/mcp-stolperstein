"""Create the `query_misses` rolling table feeding emergent-signal detection.

A zero-result `query()` inserts a row here. The `emergent` module reads from
this table to cluster misses and produce `tool-gap-signal` KUs. Rows are
pruned by TTL (30 days).
"""

from __future__ import annotations

import sqlite3

version = 6
breaking = False
slug = "emergent_scaffolding"


def up(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS query_misses ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  text TEXT NOT NULL,"
        "  embedding BLOB,"
        "  created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_query_misses_created_at "
        "ON query_misses(created_at)"
    )
