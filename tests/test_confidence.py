"""Tests for the confidence scoring algorithm — including property-based tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from stolperstein.confidence import calculate_confidence


# --- Property-based tests ---


@given(
    confirmations=st.integers(min_value=0, max_value=1000),
    orgs=st.integers(min_value=1, max_value=100),
    staleness=st.integers(min_value=1, max_value=365),
    is_disputed=st.booleans(),
)
@settings(max_examples=200)
def test_score_always_in_range(confirmations, orgs, staleness, is_disputed):
    """Confidence score is always between 0.1 and 1.0."""
    score = calculate_confidence(
        base=0.5,
        confirmations=confirmations,
        contributing_orgs_count=min(orgs, confirmations) if confirmations > 0 else 1,
        last_confirmed=datetime.now(timezone.utc),
        staleness_days=staleness,
        is_disputed=is_disputed,
    )
    assert 0.1 <= score <= 1.0


def test_disputed_capped_at_05():
    """Disputed KUs are capped at 0.5 regardless of confirmations."""
    score = calculate_confidence(
        base=0.5,
        confirmations=100,
        contributing_orgs_count=50,
        last_confirmed=datetime.now(timezone.utc),
        staleness_days=90,
        is_disputed=True,
    )
    assert score <= 0.5


def test_confidence_increases_with_confirmations():
    """More confirmations = higher confidence."""
    now = datetime.now(timezone.utc)
    score_low = calculate_confidence(
        base=0.5, confirmations=1, contributing_orgs_count=1,
        last_confirmed=now, staleness_days=90, is_disputed=False,
    )
    score_high = calculate_confidence(
        base=0.5, confirmations=10, contributing_orgs_count=5,
        last_confirmed=now, staleness_days=90, is_disputed=False,
    )
    assert score_high > score_low


def test_diversity_matters():
    """3 orgs confirming beats 3 confirmations from 1 org."""
    now = datetime.now(timezone.utc)
    score_diverse = calculate_confidence(
        base=0.5, confirmations=3, contributing_orgs_count=3,
        last_confirmed=now, staleness_days=90, is_disputed=False,
    )
    score_single = calculate_confidence(
        base=0.5, confirmations=3, contributing_orgs_count=1,
        last_confirmed=now, staleness_days=90, is_disputed=False,
    )
    assert score_diverse > score_single


def test_temporal_decay():
    """Confidence decays after staleness threshold."""
    recent = datetime.now(timezone.utc)
    old = datetime.now(timezone.utc) - timedelta(days=120)

    score_fresh = calculate_confidence(
        base=0.5, confirmations=5, contributing_orgs_count=3,
        last_confirmed=recent, staleness_days=90, is_disputed=False,
    )
    score_stale = calculate_confidence(
        base=0.5, confirmations=5, contributing_orgs_count=3,
        last_confirmed=old, staleness_days=90, is_disputed=False,
    )
    assert score_fresh > score_stale


def test_no_decay_before_threshold():
    """No decay when within staleness threshold."""
    now = datetime.now(timezone.utc)
    just_before = now - timedelta(days=89)

    score_now = calculate_confidence(
        base=0.5, confirmations=3, contributing_orgs_count=2,
        last_confirmed=now, staleness_days=90, is_disputed=False,
    )
    score_before = calculate_confidence(
        base=0.5, confirmations=3, contributing_orgs_count=2,
        last_confirmed=just_before, staleness_days=90, is_disputed=False,
    )
    assert score_now == score_before


def test_floor_at_01():
    """Confidence never drops below 0.1 even with extreme decay."""
    very_old = datetime.now(timezone.utc) - timedelta(days=500)
    score = calculate_confidence(
        base=0.5, confirmations=0, contributing_orgs_count=1,
        last_confirmed=very_old, staleness_days=90, is_disputed=False,
    )
    assert score == 0.1


def test_zero_confirmations():
    """Zero confirmations gives base score."""
    score = calculate_confidence(
        base=0.5, confirmations=0, contributing_orgs_count=1,
        last_confirmed=datetime.now(timezone.utc), staleness_days=90,
        is_disputed=False,
    )
    assert score == 0.5
