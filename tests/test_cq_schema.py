"""Tests for CQ interchange format compatibility."""

from __future__ import annotations

from datetime import datetime, timezone

from stolperstein.models import (
    Insight,
    KnowledgeUnit,
    KUKind,
    KURelation,
    KUStatus,
)


def test_ku_serializes_to_cq_json():
    """KU serializes to CQ-compatible JSON with all required fields."""
    ku = KnowledgeUnit(
        id="ku_abc123",
        version="1.0.0",
        domain=["swift", "xcode"],
        insight=Insight(
            summary="Xcode 16 strict concurrency",
            detail="Swift 6 mode makes sendable violations errors.",
            action="Add -strict-concurrency=complete.",
        ),
        confidence=0.75,
        confirmations=3,
        contributing_orgs=["cdit"],
        first_observed=datetime(2026, 3, 25, tzinfo=timezone.utc),
        last_confirmed=datetime(2026, 3, 27, tzinfo=timezone.utc),
        last_queried_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        kind=KUKind.pitfall,
        status=KUStatus.active,
        staleness_policy="confirm_or_decay_after_90d",
        related=[KURelation(type="extends", target_id="ku_xyz789")],
    )

    data = ku.to_cq_json()

    # All CQ-required fields present
    assert data["id"] == "ku_abc123"
    assert data["version"] == "1.0.0"
    assert data["domain"] == ["swift", "xcode"]
    assert data["insight"]["summary"] == "Xcode 16 strict concurrency"
    assert data["insight"]["detail"] is not None
    assert data["insight"]["action"] is not None
    assert data["confidence"] == 0.75
    assert data["confirmations"] == 3
    assert data["contributing_orgs"] == ["cdit"]
    assert data["first_observed"] is not None
    assert data["last_confirmed"] is not None
    assert data["last_queried_at"] is not None
    assert data["kind"] == "pitfall"
    assert data["status"] == "active"
    assert data["staleness_policy"] == "confirm_or_decay_after_90d"
    assert len(data["related"]) == 1
    assert data["related"][0]["type"] == "extends"


def test_cq_json_roundtrip():
    """KU survives JSON serialization → deserialization without data loss."""
    ku = KnowledgeUnit(
        id="ku_roundtrip",
        domain=["python", "fastmcp"],
        insight=Insight(
            summary="FastMCP needs >= 3.1.0 for MultiAuth",
            detail="Earlier versions don't support MultiAuth provider.",
            action="Pin fastmcp>=3.1.0 in pyproject.toml.",
        ),
        kind=KUKind.tool_recommendation,
        confidence=0.85,
        confirmations=5,
        contributing_orgs=["cdit", "mozilla"],
    )

    data = ku.to_cq_json()
    restored = KnowledgeUnit.from_cq_json(data)

    assert restored.id == ku.id
    assert restored.domain == ku.domain
    assert restored.insight.summary == ku.insight.summary
    assert restored.insight.detail == ku.insight.detail
    assert restored.insight.action == ku.insight.action
    assert restored.confidence == ku.confidence
    assert restored.confirmations == ku.confirmations
    assert restored.contributing_orgs == ku.contributing_orgs
    assert restored.kind == ku.kind
    assert restored.status == ku.status


def test_cq_json_import_external():
    """A CQ-format JSON from an external source imports correctly."""
    external_data = {
        "id": "ku_external_001",
        "version": "1.0.0",
        "domain": ["docker", "networking"],
        "insight": {
            "summary": "Docker bridge networks don't resolve hostnames",
            "detail": "Containers on the default bridge network cannot resolve each other by name.",
            "action": "Use a user-defined bridge network for container-to-container communication.",
        },
        "confidence": 0.9,
        "confirmations": 12,
        "contributing_orgs": ["mozilla", "docker-inc", "cdit"],
        "first_observed": "2026-03-01T00:00:00+00:00",
        "last_confirmed": "2026-03-25T00:00:00+00:00",
        "last_queried_at": None,
        "kind": "pitfall",
        "status": "active",
        "staleness_policy": "confirm_or_decay_after_90d",
        "related": [],
        "graduated_to_team": False,
    }

    ku = KnowledgeUnit.from_cq_json(external_data)
    assert ku.id == "ku_external_001"
    assert ku.confidence == 0.9
    assert len(ku.contributing_orgs) == 3
    assert ku.kind == KUKind.pitfall

    # Re-export matches
    re_exported = ku.to_cq_json()
    assert re_exported["id"] == external_data["id"]
    assert re_exported["confidence"] == external_data["confidence"]
