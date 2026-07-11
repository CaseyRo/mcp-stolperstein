"""Build a safe injection payload for hook-delivered KU hints.

Rules (see design.md §7, security review M1/M3):

1. Strip all angle-bracket content from the KU's `action` field before
   rendering. No crafted `<system-reminder>...` tags can reach the agent.
2. Fixed template prefix so stale hints are contextually dismissable.
3. Never use `<system-reminder>`-shaped tags in the wrapper itself — the
   host model may elevate those.
"""

from __future__ import annotations

import re

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text or "")


def wrap_injection(ku: dict, source: str) -> str:
    """Render a hint for injection into agent context.

    `ku` is expected to have `id`, `insight.summary`, `insight.action`,
    and `evidence.confidence` (rich shape) OR a flat `confidence` /
    `summary` / `action` (legacy). Both shapes handled.

    `source` is a short phrase like "Bash error" or "submitted prompt"
    used in the temporal qualifier.
    """
    ku_id = ku.get("id", "?")
    insight = ku.get("insight") or {}
    summary = _strip_tags(insight.get("summary") or ku.get("summary") or "")
    action = _strip_tags(insight.get("action") or ku.get("action") or "")
    evidence = ku.get("evidence") or {}
    confidence = evidence.get("confidence", ku.get("confidence", 0.0))

    return (
        f"Note from Stolperfalle (from your previous {source}): "
        f"[KU {ku_id}, confidence {confidence:.2f}] {summary} "
        f"— Recommended action: {action}"
    )
