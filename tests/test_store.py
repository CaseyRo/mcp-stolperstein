"""Integration tests for the SQLite knowledge store."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_propose_creates_ku(store):
    """Propose creates a KU with draft status and confidence 0.5."""
    result = await store.propose(
        summary="Xcode 16 requires explicit Swift 6 concurrency opt-in",
        detail="When targeting Swift 6 language mode, all sendable violations become errors.",
        action="Add -strict-concurrency=complete to build settings to catch issues early.",
        domain=["swift", "xcode"],
        kind="pitfall",
    )
    ku = result["ku"]
    assert ku["id"].startswith("ku_")
    assert ku["status"] == "draft"
    assert ku["confidence"] == 0.5
    assert ku["confirmations"] == 0
    assert ku["insight"]["summary"] == "Xcode 16 requires explicit Swift 6 concurrency opt-in"
    assert ku["domain"] == ["swift", "xcode"]
    assert ku["kind"] == "pitfall"


@pytest.mark.asyncio
async def test_propose_query_roundtrip(store):
    """Proposed KU can be found via FTS query."""
    await store.propose(
        summary="HA WebSocket reconnects silently drop subscriptions",
        detail="After a WebSocket reconnect, event subscriptions are not restored.",
        action="Re-subscribe to all events after auth_ok on reconnect.",
        domain=["homeassistant", "websocket"],
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
        domain=["test"],
        kind="workaround",
    )
    ku_id = propose_result["ku"]["id"]

    confirm_result = await store.confirm(ku_id)
    ku = confirm_result["ku"]
    assert ku["confirmations"] == 1
    assert ku["status"] == "active"
    assert ku["confidence"] > 0.5  # Boosted by confirmation


@pytest.mark.asyncio
async def test_confirm_nonexistent_raises(store):
    """Confirm on nonexistent KU raises ValueError."""
    with pytest.raises(ValueError, match="KU not found"):
        await store.confirm("ku_nonexistent")


@pytest.mark.asyncio
async def test_flag_disputed(store):
    """Flagging as incorrect sets disputed status and caps confidence."""
    propose_result = await store.propose(
        summary="Test KU for flag",
        detail="Detail",
        action="Action",
        domain=["test"],
        kind="workaround",
    )
    ku_id = propose_result["ku"]["id"]

    # Confirm first to boost confidence
    await store.confirm(ku_id)

    flag_result = await store.flag(ku_id, reason="incorrect", detail="No longer applies")
    ku = flag_result["ku"]
    assert ku["status"] == "disputed"
    assert ku["confidence"] <= 0.5


@pytest.mark.asyncio
async def test_flag_superseded(store):
    """Flagging as superseded archives the KU and records relation."""
    r1 = await store.propose(
        summary="Old approach",
        detail="D",
        action="A",
        domain=["test"],
        kind="workaround",
    )
    r2 = await store.propose(
        summary="New approach",
        detail="D",
        action="A",
        domain=["test"],
        kind="workaround",
    )
    old_id = r1["ku"]["id"]
    new_id = r2["ku"]["id"]

    result = await store.flag(old_id, reason="superseded", superseded_by=new_id)
    ku = result["ku"]
    assert ku["status"] == "archived"
    assert any(r["type"] == "superseded_by" and r["target_id"] == new_id for r in ku["related"])


@pytest.mark.asyncio
async def test_flag_nonexistent_raises(store):
    """Flag on nonexistent KU raises ValueError."""
    with pytest.raises(ValueError, match="KU not found"):
        await store.flag("ku_nonexistent", reason="stale")


@pytest.mark.asyncio
async def test_status_aggregates(store):
    """Status returns correct aggregate counts."""
    await store.propose(
        summary="KU 1", detail="D", action="A", domain=["test"], kind="pitfall"
    )
    await store.propose(
        summary="KU 2", detail="D", action="A", domain=["test"], kind="workaround"
    )

    status = await store.status()
    assert status["total"] == 2
    assert status["by_status"]["draft"] == 2
    assert "mean" in status["confidence_distribution"]
    assert "approaching_threshold" in status["staleness"]


@pytest.mark.asyncio
async def test_query_domain_filter(store):
    """Query with domain filter only returns matching KUs."""
    await store.propose(
        summary="Swift issue", detail="D", action="A", domain=["swift"], kind="pitfall"
    )
    await store.propose(
        summary="Python issue", detail="D", action="A", domain=["python"], kind="pitfall"
    )

    result = await store.query(text="issue", domain=["swift"])
    assert all("swift" in r["domain"] for r in result["results"])


@pytest.mark.asyncio
async def test_query_confidence_filter(store):
    """Query respects confidence_min filter."""
    r = await store.propose(
        summary="Low confidence KU", detail="D", action="A", domain=["test"], kind="pitfall"
    )
    # Default confidence is 0.5, so searching with min 0.6 should exclude it
    result = await store.query(text="Low confidence", confidence_min=0.6)
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_query_empty_returns_empty(store):
    """Query with no matches returns empty results."""
    result = await store.query(text="nonexistent gibberish xyz123")
    assert result["count"] == 0
    assert result["results"] == []
