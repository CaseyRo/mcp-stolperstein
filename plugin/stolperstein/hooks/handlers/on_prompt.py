#!/usr/bin/env python3
"""UserPromptSubmit hook — queries the KB when a user prompt contains a
structured error signal and injects a sanitized, temporally-qualified hint
on ≥0.5 confidence.

Silent no-op on: conversational prompts, unconfigured MCP URL, MCP
unreachable within the query budget, rate limit suppression, KU dedupe,
or this hook being listed in `STOLPERSTEIN_HOOKS_DISABLED`. Set
`STOLPERSTEIN_HOOKS_DEBUG=1` to trace every decision to
`$TMPDIR/stolperstein-hooks-debug.jsonl`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Make sibling modules importable when Claude Code runs this script directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _client import MCPUnreachable, call_query  # noqa: E402
from _debug import trace  # noqa: E402
from _inject import wrap_injection  # noqa: E402
from _rate_limit import should_inject  # noqa: E402
from _signals import is_structured_error  # noqa: E402

_MAX_PROMPT_CHARS = 512
_HOOK_NAME = "UserPromptSubmit"


def _disabled(hook_name: str) -> bool:
    disabled = os.environ.get("STOLPERSTEIN_HOOKS_DISABLED", "").strip()
    return hook_name in {n.strip() for n in disabled.split(",") if n.strip()}


def _session_id(event: dict) -> str:
    """Claude Code passes `session_id` in the hook event payload (there is
    no CLAUDE_SESSION_ID env var); the env fallback keeps old tests working."""
    return event.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "default"


def _mark_unreachable(session_id: str) -> None:
    """Tell the Stop hook the server was unreachable at least once this session."""
    import tempfile
    from pathlib import Path
    marker = Path(tempfile.gettempdir()) / f"stolperstein-unreachable-{session_id}"
    try:
        marker.touch()
    except OSError:
        pass


async def _run() -> int:
    if _disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    prompt = (event.get("prompt") or "").strip()
    if not prompt or not is_structured_error(prompt):
        trace(_HOOK_NAME, "no-error-signal")
        return 0

    try:
        result = await call_query(prompt[:_MAX_PROMPT_CHARS], limit=1)
    except MCPUnreachable as e:
        trace(_HOOK_NAME, "unreachable", error=str(e))
        _mark_unreachable(_session_id(event))
        return 0
    if not result:
        trace(_HOOK_NAME, "env-unset")
        return 0

    results = result.get("results") or []
    if not results:
        trace(_HOOK_NAME, "no-results")
        return 0
    top = results[0]
    confidence = (top.get("evidence") or {}).get("confidence", 0)
    if confidence < 0.5:
        trace(_HOOK_NAME, "low-confidence", confidence=confidence)
        return 0

    if not should_inject(_HOOK_NAME, top.get("id", "")):
        trace(_HOOK_NAME, "rate-limited", ku_id=top.get("id", ""))
        return 0

    trace(_HOOK_NAME, "injected", ku_id=top.get("id", ""))

    out = {
        "hookSpecificOutput": {
            "hookEventName": _HOOK_NAME,
            "additionalContext": wrap_injection(top, source="submitted prompt"),
        },
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
