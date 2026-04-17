"""Pad pre-v1 KU ids to the 32-hex format required by upstream CQ.

Upstream `mozilla-ai/cq` requires `^ku_[0-9a-f]{32}$`. Our v0 generator used
`secrets.token_hex(12)` (24 hex), so existing rows fail strict validation.
This migration deterministically pads the hex portion with leading zeros to
32 chars and rewrites every reference: FTS5 UNINDEXED id copy, vec0 primary
key `ku_id`, and any `related[].target_id` mentions in other rows.

Breaking because ids are primary keys. Takes a pre-migration snapshot.
"""

from __future__ import annotations

import json
import re
import sqlite3

version = 1
breaking = True
slug = "ku_id_format_fix"

_CONFORMANT_RE = re.compile(r"^ku_[0-9a-f]{32}$")
_LEGACY_RE = re.compile(r"^ku_[0-9a-f]{1,31}$")


def _pad(old_id: str) -> str:
    hex_part = old_id.removeprefix("ku_")
    return "ku_" + hex_part.zfill(32)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
        [name],
    ).fetchone()
    return row is not None


def up(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "knowledge_units"):
        # Fresh install — no rows, nothing to fix.
        return

    rows = conn.execute("SELECT id FROM knowledge_units").fetchall()
    rename_map: dict[str, str] = {}
    for row in rows:
        old = row[0]
        if _CONFORMANT_RE.match(old):
            continue
        if not _LEGACY_RE.match(old):
            # Not a recognized id shape — leave alone, log.
            continue
        new = _pad(old)
        if old == new:
            continue
        rename_map[old] = new

    if not rename_map:
        return

    has_fts = _table_exists(conn, "ku_fts")
    has_vec = _table_exists(conn, "ku_embeddings")

    # Apply renames. Order: knowledge_units first (PK change), then side tables.
    for old, new in rename_map.items():
        conn.execute("UPDATE knowledge_units SET id = ? WHERE id = ?", [new, old])
        if has_fts:
            conn.execute("UPDATE ku_fts SET id = ? WHERE id = ?", [new, old])
        if has_vec:
            conn.execute("UPDATE ku_embeddings SET ku_id = ? WHERE ku_id = ?", [new, old])

    # Rewrite cross-references in `related` JSON. We scan every row since any
    # row could reference any id.
    for row in conn.execute("SELECT id, related FROM knowledge_units").fetchall():
        related_json = row[1]
        if not related_json or related_json == "[]":
            continue
        try:
            related = json.loads(related_json)
        except json.JSONDecodeError:
            continue
        changed = False
        for entry in related:
            tid = entry.get("target_id")
            if tid in rename_map:
                entry["target_id"] = rename_map[tid]
                changed = True
        if changed:
            conn.execute(
                "UPDATE knowledge_units SET related = ? WHERE id = ?",
                [json.dumps(related), row[0]],
            )
