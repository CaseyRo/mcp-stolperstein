#!/usr/bin/env python3
"""PostToolUse hook (matcher=Bash) — queries the KB when a Bash tool call
exits non-zero or stderr contains a structured error signal. Injects a
sanitized, temporally-qualified hint for the agent's next turn.

Fire-and-forget within the 500ms client budget. Never blocks the tool
response.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _client import MCPUnreachable, call_query  # noqa: E402
from _debug import trace  # noqa: E402
from _inject import wrap_injection  # noqa: E402
from _rate_limit import should_inject  # noqa: E402
from _signals import is_structured_error  # noqa: E402

_HOOK_NAME = "PostToolUse"
_STDERR_CHARS = 4096


def _disabled(hook_name: str) -> bool:
    disabled = os.environ.get("STOLPERSTEIN_HOOKS_DISABLED", "").strip()
    return hook_name in {n.strip() for n in disabled.split(",") if n.strip()}


def _session_id(event: dict) -> str:
    """Claude Code passes `session_id` in the hook event payload (there is
    no CLAUDE_SESSION_ID env var); the env fallback keeps old tests working."""
    return event.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "default"


def _mark_unreachable(session_id: str) -> None:
    import tempfile
    from pathlib import Path
    marker = Path(tempfile.gettempdir()) / f"stolperstein-unreachable-{session_id}"
    try:
        marker.touch()
    except OSError:
        pass


def _extract_signal(event: dict) -> str | None:
    """Given a Bash PostToolUse event payload, decide whether to fire and
    return the text to query with (or None for no-op).
    """
    if event.get("tool_name") != "Bash":
        return None
    resp = event.get("tool_response") or {}
    exit_code = resp.get("exitCode", resp.get("exit_code", 0))
    stderr = (resp.get("stderr") or "").strip()
    stdout = (resp.get("stdout") or "").strip()

    if exit_code == 0 and not is_structured_error(stderr) and not is_structured_error(stdout):
        return None

    candidate = stderr or stdout
    return candidate[-_STDERR_CHARS:] if candidate else None


async def _run() -> int:
    if _disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    signal_text = _extract_signal(event)
    if not signal_text:
        trace(_HOOK_NAME, "no-error-signal")
        return 0

    try:
        result = await call_query(signal_text, limit=1)
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
            "additionalContext": wrap_injection(top, source="Bash error"),
        },
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
