"""Tests for CQ interchange format conformance.

Validates two serializer surfaces:

1. `to_cq_json_strict()` — must validate against the vendored upstream
   `knowledge_unit.json` schema (no Stolperfalle extensions).
2. `to_cq_json_rich()` — carries extensions; does NOT validate against
   upstream strict, by design.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from stolperfalle.models import (
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
    """to_cq_json_rich() includes every Stolperfalle extension."""
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


def test_strict_extensions_only_inside_the_slot():
    """Extension fields never appear as first-class properties — only under
    `extensions` with `stolperstein:*` keys."""
    ku = _make_ku()
    data = ku.to_cq_json_strict()
    for field in (
        "kind", "status", "owner_org", "provenance", "staleness_policy", "related"
    ):
        assert field not in data, f"extension field '{field}' leaked into strict output"
    assert "severity" not in data["evidence"]
    assert "environment" not in data.get("context", {})

    ext = data["extensions"]
    assert ext["stolperstein:severity"] == "high"
    assert ext["stolperstein:kind"] == "pitfall"
    assert ext["stolperstein:status"] == "active"
    assert ext["stolperstein:owner_org"] == "did:key:zA"
    assert ext["stolperstein:staleness_policy"] == "confirm_or_decay_after_90d"
    assert ext["stolperstein:environment"] == "xcode-16"
    assert ext["stolperstein:contributing_orgs"] == ["did:key:zA", "did:key:zB"]
    assert ext["stolperstein:related"] == [{"type": "extends", "target_id": "ku_" + "b" * 32}]


def test_strict_extension_keys_match_upstream_format():
    """Every emitted extensions key satisfies the upstream key pattern."""
    import re
    key_re = re.compile(r"^[a-z0-9][a-z0-9_-]*:\S+$")
    ext = _make_ku().to_cq_json_strict()["extensions"]
    for key in ext:
        assert key_re.match(key), f"extensions key '{key}' violates upstream format"
    assert len(ext) <= 20  # upstream maxProperties


def test_strict_empty_extension_values_produce_no_keys():
    """Null/empty extension values are omitted; always-present fields remain."""
    ku = _make_ku(
        context=Context(languages=["swift"]),  # no environment
        evidence=Evidence(severity=KUSeverity.medium),  # no contributing_orgs
        related=[],
        provenance=Provenance(proposer_did="did:key:zA"),  # emergent None
    )
    ext = ku.to_cq_json_strict()["extensions"]
    for absent in (
        "stolperstein:environment", "stolperstein:contributing_orgs",
        "stolperstein:related", "stolperstein:emergent",
    ):
        assert absent not in ext
    assert None not in ext.values()
    # Always-valued fields still ride the slot.
    assert ext["stolperstein:severity"] == "medium"
    assert ext["stolperstein:kind"] == "pitfall"
