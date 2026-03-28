"""Confidence scoring algorithm — pure functions, no side effects.

Compatible with CQ's confidence model:
- Base confidence 0.5 on creation
- Diversity-weighted: org count matters more than raw confirmation count
- Temporal decay: linear after staleness threshold
- Dispute penalty: capped at 0.5
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def calculate_confidence(
    base: float,
    confirmations: int,
    contributing_orgs_count: int,
    last_confirmed: datetime,
    staleness_days: int,
    is_disputed: bool,
) -> float:
    """Calculate confidence score for a Knowledge Unit.

    Returns a float between 0.0 and 1.0.

    The algorithm weights organizational diversity over raw confirmation count:
    an insight confirmed by 3 agents from 3 orgs carries more weight than
    one confirmed by 10 agents from 1 org.
    """
    # Confirmation boost: diminishing returns, diversity-weighted
    if confirmations > 0:
        # log2(1 + confirmations) gives diminishing returns
        raw_boost = math.log2(1 + confirmations) * 0.1
        # Diversity multiplier: sqrt(orgs) / sqrt(confirmations) ranges 0-1
        diversity = math.sqrt(contributing_orgs_count) / math.sqrt(max(confirmations, 1))
        confirmation_boost = raw_boost * (0.5 + 0.5 * diversity)
    else:
        confirmation_boost = 0.0

    # Temporal decay: linear after staleness threshold
    now = datetime.now(timezone.utc)
    days_since = (now - last_confirmed).total_seconds() / 86400
    if days_since > staleness_days:
        days_past = days_since - staleness_days
        decay = days_past * 0.01  # 0.01 per day past threshold
    else:
        decay = 0.0

    # Combine
    score = base + confirmation_boost - decay

    # Dispute penalty: cap at 0.5
    if is_disputed:
        score = min(score, 0.5)

    # Clamp to [0.1, 1.0] — floor at 0.1, never fully zeroed
    return round(max(0.1, min(1.0, score)), 4)
