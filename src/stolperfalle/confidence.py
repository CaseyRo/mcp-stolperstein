"""Confidence scoring algorithm — pure functions, no side effects.

Compatible with CQ's confidence model, extended with Stolperfalle's severity:

- Base confidence 0.5 on creation.
- Diversity-weighted: distinct `owner_org` values in `contributing_orgs`
  matter more than raw confirmation count.
- Temporal decay: linear after staleness threshold (0.01 per day past).
- Dispute penalty: capped at 0.5.
- Severity-aware floor: `critical` keeps a 0.2 floor (never fully decays);
  other severities floor at 0.1.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from stolperfalle.models import KUSeverity


def calculate_confidence(
    base: float,
    confirmations: int,
    contributing_orgs_count: int,
    last_confirmed: datetime,
    staleness_days: int,
    is_disputed: bool,
    severity: KUSeverity = KUSeverity.medium,
) -> float:
    """Calculate confidence score for a Knowledge Unit.

    `contributing_orgs_count` should be the count of DISTINCT owner_org /
    DID values that have contributed — not session count.
    """
    if confirmations > 0:
        raw_boost = math.log2(1 + confirmations) * 0.1
        diversity = math.sqrt(contributing_orgs_count) / math.sqrt(max(confirmations, 1))
        confirmation_boost = raw_boost * (0.5 + 0.5 * diversity)
    else:
        confirmation_boost = 0.0

    now = datetime.now(timezone.utc)
    days_since = (now - last_confirmed).total_seconds() / 86400
    if days_since > staleness_days:
        days_past = days_since - staleness_days
        decay = days_past * 0.01
    else:
        decay = 0.0

    score = base + confirmation_boost - decay

    if is_disputed:
        score = min(score, 0.5)

    floor = 0.2 if severity == KUSeverity.critical else 0.1
    return round(max(floor, min(1.0, score)), 4)
