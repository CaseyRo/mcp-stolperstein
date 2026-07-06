"""Tests for CQ interchange format conformance.

Validates two serializer surfaces:

1. `to_cq_json_strict()` — must validate against the vendored upstream
   `knowledge_unit.json` schema (no Stolperstein extensions).
2. `to_cq_json_rich()` — carries extensions; does NOT validate against
   upstream strict, by design.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from stolperstein.models import (
    Context,
    Evidence,
    Insight,
    KnowledgeUnit,
    KUKind,
    KURelation,
    KUSeverity,
    KUStatus,
    Provenance,
)

_SCHEMA_PATH = Path(__file__).parent / "fixtures" / "cq" / "knowledge_unit.json"


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def _make_ku(**overrides) -> KnowledgeUnit:
    """Build a KU with reasonable defaults for tests."""
    base = dict(
        id="ku_" + "a" * 32,
        version=1,
        domains=["swift", "xcode"],
        insight=Insight(
            summary="Xcode 16 strict concurrency",
            detail="Swift 6 mode makes sendable violations errors.",
            action="Add -strict-concurrency=complete.",
        ),
        context=Context(
            languages=["swift"],
            frameworks=["swiftui"],
            environment="xcode-16",
            pattern="concurrency",
        ),
        evidence=Evidence(
            confidence=0.75,
            confirmations=3,
            first_observed=datetime(2026, 3, 25, tzinfo=timezone.utc),
            last_confirmed=datetime(2026, 3, 27, tzinfo=timezone.utc),
            contributing_orgs=["did:key:zA", "did:key:zB"],
            severity=KUSeverity.high,
        ),
        kind=KUKind.pitfall,
        status=KUStatus.active,
        provenance=Provenance(proposer_did="did:key:zA"),
        owner_org="did:key:zA",
        last_queried_at=datetime(2026, 3, 27, tzinfo=timezone.utc),
        related=[KURelation(type="extends", target_id="ku_" + "b" * 32)],
    )
    base.update(overrides)
    return KnowledgeUnit(**base)


def test_strict_serializer_validates_against_upstream_schema():
    """to_cq_json_strict() output passes upstream schema validation."""
    schema = _load_schema()
    ku = _make_ku()
    data = ku.to_cq_json_strict()
    jsonschema.validate(data, schema)  # raises on failure

    # Required upstream fields present
    assert data["id"] == ku.id
    assert data["version"] == 1  # upstream wants integer
    assert data["domains"] == ["swift", "xcode"]  # plural
    assert data["insight"]["summary"] == "Xcode 16 strict concurrency"
    assert data["evidence"]["last_confirmed"] is not None  # inside evidence
    assert data["created_by"] == "did:key:zA"  # proposer_did maps here


def test_rich_serializer_carries_all_extensions():
    """to_cq_json_rich() includes every Stolperstein extension."""
    ku = _make_ku()
    rich = ku.to_cq_json_rich()
    assert rich["kind"] == "pitfall"
    assert rich["status"] == "active"
    assert rich["owner_org"] == "did:key:zA"
    assert rich["provenance"]["proposer_did"] == "did:key:zA"
    assert rich["evidence"]["severity"] == "high"
    assert rich["context"]["environment"] == "xcode-16"
    assert rich["related"][0]["type"] == "extends"
    assert rich["staleness_policy"] == "confirm_or_decay_after_90d"


def test_rich_output_fails_strict_schema_by_design():
    """rich has extensions that additionalProperties:false rejects."""
    schema = _load_schema()
    ku = _make_ku()
    rich = ku.to_cq_json_rich()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(rich, schema)


def test_strict_omits_stolperstein_extensions():
    """Extension fields are not on the wire."""
    ku = _make_ku()
    data = ku.to_cq_json_strict()
    for field in (
        "kind", "status", "owner_org", "provenance", "staleness_policy", "related"
    ):
        assert field not in data, f"extension field '{field}' leaked into strict output"
    # evidence.severity must not be there either
    assert "severity" not in data["evidence"]
    assert "environment" not in data.get("context", {})
