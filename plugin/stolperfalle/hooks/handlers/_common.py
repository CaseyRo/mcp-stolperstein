"""Shared helpers for the hook entry scripts (on_prompt, on_bash, on_stop).

Stdlib-only, like everything under handlers/ — Claude Code runs these with
whatever `python3` is on $PATH.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from _client import MCPUnreachable, call_query
from _debug import trace
from _inject import wrap_injection
from _rate_limit import should_inject


def disabled(hook_name: str) -> bool:
    """True if `hook_name` is listed in STOLPERFALLE_HOOKS_DISABLED."""
    raw = os.environ.get("STOLPERFALLE_HOOKS_DISABLED", "").strip()
    return hook_name in {n.strip() for n in raw.split(",") if n.strip()}


def session_id(event: dict) -> str:
    """Claude Code passes `session_id` in the hook event payload (there is
    no CLAUDE_SESSION_ID env var); the env fallback keeps old tests working."""
    return event.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "default"


def unreachable_marker(sid: str) -> Path:
    return Path(tempfile.gettempdir()) / f"stolperfalle-unreachable-{sid}"


def mark_unreachable(sid: str) -> None:
    """Tell the Stop hook the server was unreachable at least once this session."""
    try:
        unreachable_marker(sid).touch()
    except OSError:
        pass


async def query_and_emit(
    signal_text: str,
    *,
    hook_event: str,
    rate_bucket: str,
    source: str,
    sid: str,
) -> int:
    """Shared query → confidence-gate → rate-limit → inject pipeline.

    `hook_event` is echoed in the hook JSON output (must match the firing
    event name); `rate_bucket` keys the cooldown state so multiple
    registrations of the same handler share one bucket.
    """
    try:
        result = await call_query(signal_text, limit=1)
    except MCPUnreachable as e:
        trace(hook_event, "unreachable", error=str(e))
        mark_unreachable(sid)
        return 0
    if not result:
        trace(hook_event, "env-unset")
        return 0

    results = result.get("results") or []
    if not results:
        trace(hook_event, "no-results")
        return 0
    top = results[0]
    confidence = (top.get("evidence") or {}).get("confidence", 0)
    if confidence < 0.5:
        trace(hook_event, "low-confidence", confidence=confidence)
        return 0

    if not should_inject(rate_bucket, top.get("id", "")):
        trace(hook_event, "rate-limited", ku_id=top.get("id", ""))
        return 0

    trace(hook_event, "injected", ku_id=top.get("id", ""))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "additionalContext": wrap_injection(top, source=source),
        },
    }))
    return 0
