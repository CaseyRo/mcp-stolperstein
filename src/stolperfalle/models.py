"""Pydantic models for Knowledge Units.

Stolperfalle carries a richer model than upstream `mozilla-ai/cq` currently
defines. The internal model is the superset. Serialization to the wire goes
through one of two explicit functions:

- `to_cq_json_strict()` emits the upstream-valid wire shape
  (see `tests/fixtures/cq/knowledge_unit.json`). Stolperfalle extension
  fields ride the upstream `extensions` slot as `stolperstein:*` keys
  (mozilla-ai/cq#453) instead of appearing as first-class fields.
- `to_cq_json_rich()` emits the full superset with extensions as
  first-class fields. Intended for local consumers, debugging, and any
  downstream aware of our internal shape.

See `docs/cq-extensions.md` for the registry of every field that exists in
`rich` but not in `strict`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, model_serializer


class KUKind(str, Enum):
    pitfall = "pitfall"
    workaround = "workaround"
    tool_recommendation = "tool-recommendation"
    tool_gap_signal = "tool-gap-signal"


class KUStatus(str, Enum):
    draft = "draft"
    active = "active"
    stale = "stale"
    disputed = "disputed"
    archived = "archived"


class KUSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class KURelation(BaseModel):
    """Typed relationship between KUs. Stolperfalle extension — not in upstream."""

    type: str  # supersedes (legacy), contradicts, extends, requires
    target_id: str


class Insight(BaseModel):
    """Tripartite insight: what happened, why it matters, what to do."""

    summary: str = Field(max_length=280)
    detail: str
    action: str


class Context(BaseModel):
    """Language/framework/pattern context.

    `languages` and `frameworks` match upstream (arrays). `pattern` matches
    upstream. `environment` is a Stolperfalle extension.
    """

    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    environment: str | None = None  # extension
    pattern: str | None = None


class Evidence(BaseModel):
    """Confidence and confirmation metrics.

    `confidence`, `confirmations`, `first_observed`, `last_confirmed` match
    upstream. `contributing_orgs` and `severity` are Stolperfalle extensions.
    """

    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    confirmations: int = 0
    first_observed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_confirmed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    contributing_orgs: list[str] = Field(default_factory=list)  # extension
    severity: KUSeverity = KUSeverity.medium  # extension


class Provenance(BaseModel):
    """Rich provenance.

    `proposer_did` maps to upstream's `created_by` on the wire.
    `emergent` is a Stolperfalle extension.
    """

    proposer_did: str
    emergent: bool | None = None  # extension — None for pre-v1 grandfathered rows


class KnowledgeUnit(BaseModel):
    """Full Knowledge Unit — Stolperfalle internal superset.

    Only fields that appear in upstream's `schema/knowledge_unit.json` are
    emitted by `to_cq_json_strict()`. See `docs/cq-extensions.md`.
    """

    id: str  # matches ^ku_[0-9a-f]{32}$ after m0000 migration
    version: int = 1  # upstream is integer; string semver held at module level
    domains: list[str] = Field(min_length=1)
    insight: Insight
    context: Context = Field(default_factory=Context)
    evidence: Evidence = Field(default_factory=Evidence)
    kind: KUKind  # extension
    status: KUStatus = KUStatus.draft  # extension
    superseded_by: str | None = None  # top-level in upstream
    provenance: Provenance  # proposer_did required
    owner_org: str  # extension; defaults to proposer_did at propose time
    staleness_policy: str = "confirm_or_decay_after_90d"  # extension
    related: list[KURelation] = Field(default_factory=list)  # extension
    last_queried_at: datetime | None = None  # not in upstream; internal metric
    graduated_to_team: bool = False  # internal

    # --- serializers ---

    def to_cq_json_strict(self) -> dict[str, Any]:
        """Emit the upstream-valid wire shape.

        Stolperfalle extension fields are carried inside the optional
        `extensions` object under `stolperstein:*` keys (upstream key
        format `^[a-z0-9][a-z0-9_-]*:\\S+$`, max 20 properties); empty and
        null extension values produce no key.
        """
        out: dict[str, Any] = {
            "id": self.id,
            "version": 1,
            "domains": list(self.domains),
            "insight": {
                "summary": self.insight.summary,
                "detail": self.insight.detail,
                "action": self.insight.action,
            },
        }

        ctx: dict[str, Any] = {}
        if self.context.languages:
            ctx["languages"] = list(self.context.languages)
        if self.context.frameworks:
            ctx["frameworks"] = list(self.context.frameworks)
        if self.context.pattern is not None:
            ctx["pattern"] = self.context.pattern
        if ctx:
            out["context"] = ctx

        ev: dict[str, Any] = {
            "confidence": self.evidence.confidence,
            "confirmations": self.evidence.confirmations,
            "first_observed": _iso(self.evidence.first_observed),
            "last_confirmed": _iso(self.evidence.last_confirmed),
        }
        out["evidence"] = ev

        # created_by = proposer_did
        out["created_by"] = self.provenance.proposer_did

        if self.superseded_by is not None:
            out["superseded_by"] = self.superseded_by

        ext: dict[str, Any] = {
            "stolperstein:severity": self.evidence.severity.value,
            "stolperstein:kind": self.kind.value,
            "stolperstein:status": self.status.value,
            "stolperstein:staleness_policy": self.staleness_policy,
            "stolperstein:owner_org": self.owner_org,
        }
        if self.evidence.contributing_orgs:
            ext["stolperstein:contributing_orgs"] = list(self.evidence.contributing_orgs)
        if self.context.environment is not None:
            ext["stolperstein:environment"] = self.context.environment
        if self.related:
            ext["stolperstein:related"] = [r.model_dump() for r in self.related]
        if self.provenance.emergent is not None:
            ext["stolperstein:emergent"] = self.provenance.emergent
        if ext:
            out["extensions"] = ext

        return out

    def to_cq_json_rich(self) -> dict[str, Any]:
        """Emit the full internal superset. Extensions present."""
        return self.model_dump(mode="json")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class KUCreate(BaseModel):
    """Input model for proposing a new KU. Flat params match the MCP tool
    signature — store assembles the nested Context/Evidence/Provenance.
    """

    # Caps at the WRITE boundary only (not on Insight/KnowledgeUnit, which
    # deserialize existing DB rows) — an unbounded detail/action/domains was a
    # persistent storage + query-serialization DoS. Ceilings are generous;
    # real KUs are a few KB.
    summary: str = Field(max_length=280)
    detail: str = Field(max_length=100_000)
    action: str = Field(max_length=10_000)
    domains: list[Annotated[str, Field(max_length=128)]] = Field(min_length=1, max_length=50)
    kind: KUKind
    context_languages: list[Annotated[str, Field(max_length=128)]] = Field(
        default_factory=list, max_length=50
    )
    context_frameworks: list[Annotated[str, Field(max_length=128)]] = Field(
        default_factory=list, max_length=50
    )
    context_environment: str | None = Field(default=None, max_length=256)
    context_pattern: str | None = Field(default=None, max_length=256)
    severity: KUSeverity = KUSeverity.medium
    staleness_policy: str = "confirm_or_decay_after_90d"


class KUResponse(BaseModel):
    """Response wrapping a KU with optional metadata."""

    ku: KnowledgeUnit
    duplicate_of: str | None = None
    message: str | None = None


class StoreStatus(BaseModel):
    """Aggregate store statistics (default — token-frugal)."""

    total: int
    by_status: dict[str, int]
    confidence_distribution: dict[str, float]
    staleness: dict[str, int]
    tool_gap_signals: dict[str, int]  # {grandfathered, emergent}


class _DropNoneModel(BaseModel):
    """Mixin: omit None fields on serialization."""

    @model_serializer(mode="wrap")
    def _drop_none(self, handler):  # type: ignore[no-untyped-def]
        data = handler(self)
        return {k: v for k, v in data.items() if v is not None}


class StatusReport(StoreStatus, _DropNoneModel):
    """Tool-facing status return.

    Superset of `StoreStatus`: the token-frugal fields are always present;
    the operator/debug fields are optional and only populated when the
    `status` tool is called with `debug=True`. `None` debug fields are
    dropped on serialization so the `debug=False` payload stays byte-for-byte
    identical to the legacy frugal dict.
    """

    schema_version: int | None = None
    proposer_did: str | None = None
    applied_migrations: list[str] | None = None
    by_owner_org: dict[str, int] | None = None
    recent_emergent: list[str] | None = None  # KU ids
    query_misses_window: int | None = None


class QueryResult(BaseModel):
    """Typed result of `query()` — ranked KUs plus a count.

    Matches the legacy `{"results": [...], "count": N}` wire shape exactly;
    declaring it as the tool return lets fastmcp advertise an output schema so
    clients can reason about KU shape without parsing the docstring.
    """

    results: list[KnowledgeUnit] = Field(default_factory=list)
    count: int = 0


class ReflectResult(_DropNoneModel):
    """Typed result of `reflect()` — ranked candidate KUs plus metadata.

    Each candidate is a `ReflectCandidate` (flat `context_*` + `severity`)
    ready to pass straight to `propose()`.
    """

    candidates: list[ReflectCandidate] = Field(default_factory=list)
    method: str | None = None  # "llm" | "heuristic"; absent when no candidates
    message: str | None = None


class ReflectCandidate(BaseModel):
    """A candidate KU from session reflection. Flat context_* + severity
    so the caller can pass straight to propose() without re-reading docs.
    """

    summary: str
    detail: str
    action: str
    domains: list[str]
    kind: KUKind
    generalizability_score: float = Field(ge=0.0, le=1.0)
    context_languages: list[str] = Field(default_factory=list)
    context_frameworks: list[str] = Field(default_factory=list)
    context_environment: str | None = None
    context_pattern: str | None = None
    severity: KUSeverity = KUSeverity.medium
