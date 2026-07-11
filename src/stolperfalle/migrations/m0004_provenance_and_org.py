"""Create install identity (public-key-only in DB), add provenance + owner_org
columns, backfill.

The private key for the generated DID lives OUTSIDE the DB — either at
`/data/stolperstein.key` (mode 0o600, on-disk filename unchanged by the
product rename) or in the `MCP_STOLPERFALLE_SIGNING_KEY` env var. This
split means a DB leak does not compromise signing capability.
"""

from __future__ import annotations

import sqlite3

from stolperfalle.provenance import get_or_create_install_did

version = 4
breaking = True
slug = "provenance_and_org"


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
    # install_identity lives alongside knowledge_units; its existence is not
    # conditional on any KU rows.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS install_identity ("
        "  did TEXT PRIMARY KEY,"
        "  public_key BLOB NOT NULL,"
        "  created_at TEXT NOT NULL"
        ")"
    )

    # Make rows row-factory aware for get_or_create_install_did.
    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        did = get_or_create_install_did(conn)
    finally:
        conn.row_factory = old_factory

    if not _table_exists(conn, "knowledge_units"):
        return

    if not _column_exists(conn, "knowledge_units", "proposer_did"):
        conn.execute("ALTER TABLE knowledge_units ADD COLUMN proposer_did TEXT")
    if not _column_exists(conn, "knowledge_units", "graduation_history"):
        conn.execute(
            "ALTER TABLE knowledge_units ADD COLUMN "
            "graduation_history TEXT NOT NULL DEFAULT '[]'"
        )
    if not _column_exists(conn, "knowledge_units", "provenance_emergent"):
        conn.execute(
            "ALTER TABLE knowledge_units ADD COLUMN provenance_emergent INTEGER"
        )
    if not _column_exists(conn, "knowledge_units", "owner_org"):
        conn.execute("ALTER TABLE knowledge_units ADD COLUMN owner_org TEXT")

    # Backfill proposer_did + owner_org to the local install DID on rows that
    # don't have them yet.
    conn.execute(
        "UPDATE knowledge_units SET proposer_did = ? WHERE proposer_did IS NULL",
        [did],
    )
    conn.execute(
        "UPDATE knowledge_units SET owner_org = ? WHERE owner_org IS NULL",
        [did],
    )
