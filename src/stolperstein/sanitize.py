"""Shared text-sanitization helpers.

The KU `action`, `summary`, and `detail` fields are free text that ends up
in agent context via hook injections or agent query responses. A crafted KU
whose `action` contains `<system-reminder>...`-shaped tags could be read by
the host model as a privileged instruction. Sanitization strips that shape
before any such content reaches an agent, and also bounds field lengths.

Applied identically at:
- hook injection time (`plugin/stolperstein/hooks/handlers/_sanitize.py`)
- team-sync ingest time (`sync/cq_team.py`)
- future import CLIs
"""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")

MAX_SUMMARY = 280
MAX_DETAIL = 8000
MAX_ACTION = 2000


def strip_tags(text: str) -> str:
    """Remove all angle-bracket content. Idempotent."""
    if not text:
        return text
    return _TAG_RE.sub("", text)


def sanitize_action(text: str) -> str:
    """Sanitize a KU's `action` field for safe injection into agent context.

    Same rules as `strip_tags` — callers may prefer the named alias for
    readability at the call site.
    """
    return strip_tags(text)


class OversizedError(ValueError):
    """Raised when a sanitized-on-ingest field exceeds its length cap."""


def sanitize_ku_dict(
    payload: dict,
    max_summary: int = MAX_SUMMARY,
    max_detail: int = MAX_DETAIL,
    max_action: int = MAX_ACTION,
) -> dict:
    """Return a copy of `payload` with insight fields sanitized and bounded.

    Used on ingest paths (team sync, import). Raises OversizedError if any
    field exceeds its cap; reject-the-payload policy, no partial ingest.
    """
    out = dict(payload)
    insight = dict(out.get("insight") or {})
    summary = strip_tags(insight.get("summary", "") or "")
    detail = strip_tags(insight.get("detail", "") or "")
    action = strip_tags(insight.get("action", "") or "")

    if len(summary) > max_summary:
        raise OversizedError(
            f"insight.summary exceeds {max_summary} chars ({len(summary)})"
        )
    if len(detail) > max_detail:
        raise OversizedError(
            f"insight.detail exceeds {max_detail} chars ({len(detail)})"
        )
    if len(action) > max_action:
        raise OversizedError(
            f"insight.action exceeds {max_action} chars ({len(action)})"
        )

    insight["summary"] = summary
    insight["detail"] = detail
    insight["action"] = action
    out["insight"] = insight
    return out
