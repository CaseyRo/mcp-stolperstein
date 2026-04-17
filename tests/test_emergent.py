"""Tests for emergent-signal aggregation."""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

import pytest


def _emb_bytes(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _plant_miss(store, text: str, embedding: list[float], offset_hours: int = 0) -> None:
    db = store._get_db()
    ts = (datetime.now(timezone.utc) - timedelta(hours=offset_hours)).isoformat()
    db.execute(
        "INSERT INTO query_misses (text, embedding, created_at) VALUES (?, ?, ?)",
        [text, _emb_bytes(embedding), ts],
    )
    db.commit()


@pytest.mark.asyncio
async def test_insufficient_misses_emits_nothing(store):
    from stolperstein.emergent import detect_emergent
    # Only 2 misses — below the default EMERGENT_MIN_MISSES=5 threshold.
    for i in range(2):
        _plant_miss(store, f"obscure {i}", [0.5] * 384)
    assert detect_emergent(store) == []


@pytest.mark.asyncio
async def test_clustered_misses_emit_tool_gap_signal(store, monkeypatch):
    from stolperstein.emergent import detect_emergent

    # Plant 6 similar misses across 3 different hour-buckets.
    for i in range(6):
        _plant_miss(store, f"missing batch operation #{i}", [1.0] * 384, offset_hours=i)

    emitted = detect_emergent(store)
    assert len(emitted) == 1

    db = store._get_db()
    row = db.execute(
        "SELECT kind, provenance_emergent, owner_org FROM knowledge_units WHERE id = ?",
        [emitted[0]],
    ).fetchone()
    assert row["kind"] == "tool-gap-signal"
    assert row["provenance_emergent"] == 1
    assert row["owner_org"].startswith("did:key:z")


@pytest.mark.asyncio
async def test_disabled_flag_suppresses(store, monkeypatch):
    from stolperstein.emergent import detect_emergent
    for i in range(8):
        _plant_miss(store, f"something #{i}", [1.0] * 384, offset_hours=i)

    import stolperstein.config
    monkeypatch.setattr(stolperstein.config.settings, "stolperstein_emergent_disabled", True)
    assert detect_emergent(store) == []


@pytest.mark.asyncio
async def test_ttl_prune_drops_old_misses(store):
    from stolperstein.emergent import detect_emergent

    # Plant misses older than 30 days + fresh ones below threshold.
    for i in range(10):
        _plant_miss(store, f"ancient #{i}", [1.0] * 384, offset_hours=24 * 40)

    detect_emergent(store)
    # After TTL prune the ancient rows are gone.
    db = store._get_db()
    remaining = db.execute("SELECT COUNT(*) FROM query_misses").fetchone()[0]
    assert remaining == 0


@pytest.mark.asyncio
async def test_dedupe_prevents_reemission(store):
    from stolperstein.emergent import detect_emergent

    for i in range(6):
        _plant_miss(store, f"miss A #{i}", [1.0] * 384, offset_hours=i)
    emitted_first = detect_emergent(store)
    assert len(emitted_first) == 1

    # Plant another cluster with the same centroid — should hit the 7-day dedupe.
    for i in range(6):
        _plant_miss(store, f"miss A dup #{i}", [1.0] * 384, offset_hours=i)
    emitted_second = detect_emergent(store)
    assert emitted_second == []
