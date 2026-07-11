"""Rename `domain` → `domains`; add last_confirmed_at, superseded_by,
context_languages, context_frameworks, context_pattern; hoist superseded_by
from related[]; drop last_confirmed column.

Aligns on-disk column names with upstream CQ's wire format so our strict
serializer can emit conformant payloads without per-field translation.
"""

from __future__ import annotations

import json
import sqlite3

version = 2
breaking = True
slug = "cq_conformance_rename"


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        [name],
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    for row in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if row[1] == col:
            return True
    return False


def up(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "knowledge_units"):
        # Fresh install — nothing to rename/hoist. Subsequent migrations will
        # still run; the baseline is created by _init_db before migrations.
        return

    if _column_exists(conn, "knowledge_units", "domain") and not _column_exists(
        conn, "knowledge_units", "domains"
    ):
        conn.execute("ALTER TABLE knowledge_units RENAME COLUMN domain TO domains")

    _add_if_missing(conn, "last_confirmed_at", "TEXT")
    _add_if_missing(conn, "superseded_by", "TEXT")
    _add_if_missing(conn, "context_languages", "TEXT NOT NULL DEFAULT '[]'")
    _add_if_missing(conn, "context_frameworks", "TEXT NOT NULL DEFAULT '[]'")
    _add_if_missing(conn, "context_pattern", "TEXT")

    if _column_exists(conn, "knowledge_units", "last_confirmed"):
        conn.execute(
            "UPDATE knowledge_units SET last_confirmed_at = last_confirmed "
            "WHERE last_confirmed_at IS NULL"
        )

    # Hoist superseded_by from related[].
    rows = conn.execute(
        "SELECT id, related FROM knowledge_units WHERE related IS NOT NULL AND related != '[]'"
    ).fetchall()
    for row in rows:
        ku_id = row[0]
        try:
            related = json.loads(row[1])
        except json.JSONDecodeError:
            continue
        superseded_entries = [e for e in related if e.get("type") == "superseded_by"]
        if not superseded_entries:
            continue
        # Keep the LAST one (most recent in insertion order); drop all from related[].
        target = superseded_entries[-1].get("target_id")
        remaining = [e for e in related if e.get("type") != "superseded_by"]
        conn.execute(
            "UPDATE knowledge_units SET superseded_by = ?, related = ? WHERE id = ?",
            [target, json.dumps(remaining), ku_id],
        )

    # Drop last_confirmed column if present. SQLite >= 3.35 supports DROP COLUMN.
    if _column_exists(conn, "knowledge_units", "last_confirmed"):
        conn.execute("ALTER TABLE knowledge_units DROP COLUMN last_confirmed")


def _add_if_missing(conn: sqlite3.Connection, col: str, decl: str) -> None:
    if not _column_exists(conn, "knowledge_units", col):
        conn.execute(f"ALTER TABLE knowledge_units ADD COLUMN {col} {decl}")
