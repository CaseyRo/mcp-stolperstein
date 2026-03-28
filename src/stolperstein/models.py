"""Pydantic models for Knowledge Units — CQ-compatible interchange format."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class KUKind(str, Enum):
    pitfall = "pitfall"
    workaround = "workaround"
    tool_recommendation = "tool-recommendation"
    gap_signal = "gap-signal"


class KUStatus(str, Enum):
    draft = "draft"
    active = "active"
    stale = "stale"
    disputed = "disputed"
    archived = "archived"


class KURelation(BaseModel):
    """Typed relationship between Knowledge Units."""

    type: str  # supersedes, contradicts, extends, requires
    target_id: str


class Insight(BaseModel):
    """The core content of a Knowledge Unit."""

    summary: str = Field(max_length=280)
    detail: str
    action: str


class KnowledgeUnit(BaseModel):
    """Full Knowledge Unit — CQ-compatible interchange format."""

    id: str
    version: str = "1.0.0"
    domain: list[str]
    insight: Insight
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    confirmations: int = 0
    contributing_orgs: list[str] = Field(default_factory=list)
    first_observed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_confirmed: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_queried_at: datetime | None = None
    kind: KUKind
    status: KUStatus = KUStatus.draft
    staleness_policy: str = "confirm_or_decay_after_90d"
    related: list[KURelation] = Field(default_factory=list)
    graduated_to_team: bool = False

    def to_cq_json(self) -> dict[str, Any]:
        """Serialize to CQ interchange format."""
        return self.model_dump(mode="json")

    @classmethod
    def from_cq_json(cls, data: dict[str, Any]) -> KnowledgeUnit:
        """Deserialize from CQ interchange format."""
        return cls.model_validate(data)


class KUCreate(BaseModel):
    """Input model for proposing a new KU."""

    summary: str = Field(max_length=280)
    detail: str
    action: str
    domain: list[str]
    kind: KUKind
    staleness_policy: str = "confirm_or_decay_after_90d"


class KUResponse(BaseModel):
    """Response model wrapping a KU with optional metadata."""

    ku: KnowledgeUnit
    duplicate_of: str | None = None
    message: str | None = None


class StoreStatus(BaseModel):
    """Aggregate store statistics."""

    total: int
    by_status: dict[str, int]
    confidence_distribution: dict[str, float]  # mean, median, p25, p75
    staleness: dict[str, int]  # approaching_threshold, past_threshold


class ReflectCandidate(BaseModel):
    """A candidate KU from session reflection."""

    summary: str
    detail: str
    action: str
    domain: list[str]
    kind: KUKind
    generalizability_score: float = Field(ge=0.0, le=1.0)
