"""MCP tool integration tests — full round-trip via the store layer."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_full_roundtrip(store):
    """propose → query → confirm → query (higher confidence) → flag → query (disputed)."""
    r = await store.propose(
        summary="HA REST API returns 200 with error body on rate limit",
        detail="When rate-limited, HA returns HTTP 200 with an error JSON body instead of 429.",
        action="Check response body for 'error' key even on 200 status codes.",
        domains=["homeassistant", "rest"],
        kind="pitfall",
    )
    ku_id = r["ku"]["id"]
    assert r["ku"]["status"] == "draft"
    assert r["ku"]["evidence"]["confidence"] == 0.5

    q = await store.query(text="HA rate limit 200 error")
    assert q["count"] >= 1
    assert ku_id in [ku["id"] for ku in q["results"]]

    c = await store.confirm(ku_id)
    assert c["ku"]["status"] == "active"
    assert c["ku"]["evidence"]["confidence"] > 0.5
    confidence_after_confirm = c["ku"]["evidence"]["confidence"]

    q2 = await store.query(text="HA rate limit 200 error")
    matching = [ku for ku in q2["results"] if ku["id"] == ku_id]
    assert len(matching) == 1
    assert matching[0]["evidence"]["confidence"] == confidence_after_confirm

    f = await store.flag(ku_id, reason="incorrect", detail="Fixed in HA 2026.1")
    assert f["ku"]["status"] == "disputed"
    assert f["ku"]["evidence"]["confidence"] <= 0.5


@pytest.mark.asyncio
async def test_multiple_confirms_increase_confidence(store):
    """Multiple confirmations progressively increase confidence."""
    r = await store.propose(
        summary="Docker bridge DNS resolution",
        detail="Default bridge network has no DNS resolution between containers.",
        action="Use a user-defined bridge network.",
        domains=["docker"],
        kind="pitfall",
    )
    ku_id = r["ku"]["id"]

    prev_confidence = r["ku"]["evidence"]["confidence"]
    for _ in range(5):
        c = await store.confirm(ku_id)
        assert c["ku"]["evidence"]["confidence"] >= prev_confidence
        prev_confidence = c["ku"]["evidence"]["confidence"]

    assert prev_confidence > 0.5


@pytest.mark.asyncio
async def test_status_reflects_operations(store):
    """Status counts update after propose, confirm, flag."""
    s0 = await store.status()
    assert s0["total"] == 0

    r = await store.propose(
        summary="Test", detail="D", action="A", domains=["test"], kind="workaround"
    )
    s1 = await store.status()
    assert s1["total"] == 1
    assert s1["by_status"].get("draft") == 1

    await store.confirm(r["ku"]["id"])
    s2 = await store.status()
    assert s2["by_status"].get("active") == 1
    assert s2["by_status"].get("draft", 0) == 0

    await store.flag(r["ku"]["id"], reason="incorrect")
    s3 = await store.status()
    assert s3["by_status"].get("disputed") == 1


@pytest.mark.asyncio
async def test_supersede_flow(store):
    """Supersede: old KU archived with top-level superseded_by, new KU queryable."""
    old = await store.propose(
        summary="Old workaround for X", detail="D", action="A",
        domains=["test"], kind="workaround",
    )
    new = await store.propose(
        summary="New fix for X", detail="D", action="A",
        domains=["test"], kind="workaround",
    )

    await store.flag(
        old["ku"]["id"], reason="superseded", superseded_by=new["ku"]["id"]
    )

    s = await store.status()
    assert s["by_status"].get("archived") == 1

    q = await store.query(text="workaround for X")
    archived_ids = [ku["id"] for ku in q["results"] if ku["status"] == "archived"]
    assert old["ku"]["id"] not in archived_ids


@pytest.mark.asyncio
async def test_reflect_returns_structure():
    """Reflect returns expected structure."""
    from stolperstein.reflect import reflect_with_dedup

    result = await reflect_with_dedup(
        session_summary="Fixed a Swift concurrency issue with Xcode 16"
    )
    assert "candidates" in result
    assert isinstance(result["candidates"], list)
