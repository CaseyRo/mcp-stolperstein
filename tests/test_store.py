"""Integration tests for the SQLite knowledge store."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError


@pytest.mark.asyncio
async def test_propose_creates_ku(store):
    """Propose creates a KU with draft status and default evidence.confidence 0.5."""
    result = await store.propose(
        summary="Xcode 16 requires explicit Swift 6 concurrency opt-in",
        detail="When targeting Swift 6 language mode, all sendable violations become errors.",
        action="Add -strict-concurrency=complete to build settings to catch issues early.",
        domains=["swift", "xcode"],
        kind="pitfall",
    )
    ku = result["ku"]
    assert ku["id"].startswith("ku_")
    assert len(ku["id"]) == len("ku_") + 32  # strict-format 32 hex
    assert ku["status"] == "draft"
    assert ku["evidence"]["confidence"] == 0.5
    assert ku["evidence"]["confirmations"] == 0
    assert ku["insight"]["summary"] == "Xcode 16 requires explicit Swift 6 concurrency opt-in"
    assert ku["domains"] == ["swift", "xcode"]
    assert ku["kind"] == "pitfall"
    assert ku["owner_org"]
    assert ku["provenance"]["proposer_did"]


@pytest.mark.asyncio
async def test_propose_accepts_domain_alias(store):
    """Legacy `domain=` arg is silently promoted to `domains`."""
    result = await store.propose(
        summary="legacy alias",
        detail="D",
        action="A",
        domain=["legacy"],
        kind="pitfall",
    )
    assert result["ku"]["domains"] == ["legacy"]


@pytest.mark.asyncio
async def test_propose_rejects_gap_signal(store):
    """gap-signal is no longer proposable; server returns a ToolError with recovery hint."""
    with pytest.raises(ToolError, match="gap-signal"):
        await store.propose(
            summary="x", detail="y", action="z", domains=["a"], kind="gap-signal"
        )


@pytest.mark.asyncio
async def test_propose_query_roundtrip(store):
    """Proposed KU can be found via FTS query."""
    await store.propose(
        summary="HA WebSocket reconnects silently drop subscriptions",
        detail="After a WebSocket reconnect, event subscriptions are not restored.",
        action="Re-subscribe to all events after auth_ok on reconnect.",
        domains=["homeassistant", "websocket"],
        kind="pitfall",
    )
    result = await store.query(text="WebSocket reconnect subscriptions")
    assert result["count"] >= 1
    assert any(
        "WebSocket" in r["insight"]["summary"] for r in result["results"]
    )


@pytest.mark.asyncio
async def test_confirm_increments(store):
    """Confirm increments confirmations and transitions draft -> active."""
    propose_result = await store.propose(
        summary="Test KU for confirm",
        detail="Detail",
        action="Action",
        domains=["test"],
        kind="workaround",
    )
    ku_id = propose_result["ku"]["id"]

    confirm_result = await store.confirm(ku_id)
    ku = confirm_result["ku"]
    assert ku["evidence"]["confirmations"] == 1
    assert ku["status"] == "active"
    assert ku["evidence"]["confidence"] > 0.5  # Boosted by confirmation


@pytest.mark.asyncio
async def test_confirm_nonexistent_raises(store):
    """Confirm on nonexistent KU raises ToolError with recovery hint."""
    with pytest.raises(ToolError, match="KU not found"):
        await store.confirm("ku_" + "0" * 32)


@pytest.mark.asyncio
async def test_flag_disputed(store):
    """Flagging as incorrect sets disputed status and caps confidence."""
    propose_result = await store.propose(
        summary="Test KU for flag",
        detail="Detail",
        action="Action",
        domains=["test"],
        kind="workaround",
    )
    ku_id = propose_result["ku"]["id"]

    await store.confirm(ku_id)

    flag_result = await store.flag(ku_id, reason="incorrect", detail="No longer applies")
    ku = flag_result["ku"]
    assert ku["status"] == "disputed"
    assert ku["evidence"]["confidence"] <= 0.5


@pytest.mark.asyncio
async def test_flag_superseded(store):
    """Flagging as superseded archives the KU and sets top-level superseded_by."""
    r1 = await store.propose(
        summary="Old approach",
        detail="D",
        action="A",
        domains=["test"],
        kind="workaround",
    )
    r2 = await store.propose(
        summary="New approach",
        detail="D",
        action="A",
        domains=["test"],
        kind="workaround",
    )
    old_id = r1["ku"]["id"]
    new_id = r2["ku"]["id"]

    result = await store.flag(old_id, reason="superseded", superseded_by=new_id)
    ku = result["ku"]
    assert ku["status"] == "archived"
    assert ku["superseded_by"] == new_id
    # Not in related[] anymore — the field is top-level.
    assert not any(r["type"] == "superseded_by" for r in ku["related"])


@pytest.mark.asyncio
async def test_flag_nonexistent_raises(store):
    """Flag on nonexistent KU raises ToolError."""
    with pytest.raises(ToolError, match="KU not found"):
        await store.flag("ku_" + "0" * 32, reason="stale")


@pytest.mark.asyncio
async def test_status_aggregates(store):
    """Status returns correct aggregate counts + tool_gap_signals partition."""
    await store.propose(
        summary="KU 1", detail="D", action="A", domains=["test"], kind="pitfall"
    )
    await store.propose(
        summary="KU 2", detail="D", action="A", domains=["test"], kind="workaround"
    )

    status = await store.status()
    assert status["total"] == 2
    assert status["by_status"]["draft"] == 2
    assert "mean" in status["confidence_distribution"]
    assert "approaching_threshold" in status["staleness"]
    assert status["tool_gap_signals"] == {"grandfathered": 0, "emergent": 0}
    # Default status is token-frugal — no proposer_did / schema_version leak.
    assert "proposer_did" not in status
    assert "schema_version" not in status


@pytest.mark.asyncio
async def test_status_debug_surfaces_detail(store):
    """Debug status includes schema_version, proposer_did, migration list."""
    status = await store.status(debug=True)
    assert status["schema_version"] == 6
    assert status["proposer_did"].startswith("did:key:z")
    assert len(status["applied_migrations"]) == 6


@pytest.mark.asyncio
async def test_query_domain_filter(store):
    """Query with domain filter only returns matching KUs."""
    await store.propose(
        summary="Swift issue", detail="D", action="A", domains=["swift"], kind="pitfall"
    )
    await store.propose(
        summary="Python issue", detail="D", action="A", domains=["python"], kind="pitfall"
    )

    result = await store.query(text="issue", domain=["swift"])
    assert all("swift" in r["domains"] for r in result["results"])


@pytest.mark.asyncio
async def test_query_confidence_filter(store):
    """Query respects confidence_min filter."""
    await store.propose(
        summary="Low confidence KU", detail="D", action="A", domains=["test"], kind="pitfall"
    )
    result = await store.query(text="Low confidence", confidence_min=0.6)
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_query_empty_returns_empty(store):
    """Query with no matches returns empty results and records a miss."""
    result = await store.query(text="nonexistent gibberish xyz123")
    assert result["count"] == 0
    assert result["results"] == []
    # Miss recorded in query_misses
    db = store._get_db()
    miss_count = db.execute("SELECT COUNT(*) FROM query_misses").fetchone()[0]
    assert miss_count == 1
