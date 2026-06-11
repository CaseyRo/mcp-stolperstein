#!/usr/bin/env python3
"""PostToolUse + PostToolUseFailure hook (matcher=Bash) — queries the KB
when a Bash tool call fails or its output contains a structured error
signal. Injects a sanitized, temporally-qualified hint for the agent's
next turn.

Registered for BOTH events because PostToolUse only fires on tool
SUCCESS (exit 0) — nonzero-exit Bash calls, the exact moment this hook
exists for, are delivered exclusively via PostToolUseFailure
(anthropics/claude-code#6371). The success registration still matters:
exit-0 commands whose output contains error text (grep over logs, test
runners that swallow exit codes) are real signal too.

Fire-and-forget within the client query budget. Never blocks the tool
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


def _texts_from(resp: object) -> list[str]:
    """Collect text from a tool_response of any shape.

    Claude Code's Bash tool_response is not one stable shape: success
    payloads carry `stdout`/`stderr` keys, failure payloads can be a bare
    string or `{"content": [{"type": "text", "text": ...}]}` blocks.
    Assuming the stdout/stderr shape made the hook silently skip exactly
    the events it exists for (nonzero exits).
    """
    if isinstance(resp, str):
        return [resp] if resp.strip() else []
    if isinstance(resp, list):
        out: list[str] = []
        for item in resp:
            out.extend(_texts_from(item))
        return out
    if isinstance(resp, dict):
        out = []
        for key in ("stderr", "stdout", "output", "error", "text"):
            val = resp.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
        if "content" in resp:
            out.extend(_texts_from(resp["content"]))
        return out
    return []


def _extract_signal(event: dict) -> str | None:
    """Given a Bash PostToolUse event payload, decide whether to fire and
    return the text to query with (or None for no-op).
    """
    if event.get("tool_name") != "Bash":
        return None
    resp = event.get("tool_response") or {}
    combined = "\n".join(_texts_from(resp)).strip()

    exit_code = 0
    if isinstance(resp, dict):
        exit_code = resp.get("exitCode", resp.get("exit_code", 0)) or 0

    if exit_code == 0 and not is_structured_error(combined):
        return None

    return combined[-_STDERR_CHARS:] if combined else None


async def _run() -> int:
    if _disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    # PostToolUse or PostToolUseFailure — echo the real event name in the
    # output so the harness accepts it; rate-limiting stays in one shared
    # bucket (_HOOK_NAME) so the two registrations can't double-inject.
    hook_event = event.get("hook_event_name") or _HOOK_NAME

    signal_text = _extract_signal(event)
    if not signal_text:
        resp = event.get("tool_response")
        trace(
            hook_event,
            "no-error-signal",
            resp_shape=sorted(resp.keys()) if isinstance(resp, dict) else type(resp).__name__,
        )
        return 0

    try:
        result = await call_query(signal_text, limit=1)
    except MCPUnreachable as e:
        trace(hook_event, "unreachable", error=str(e))
        _mark_unreachable(_session_id(event))
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

    if not should_inject(_HOOK_NAME, top.get("id", "")):
        trace(hook_event, "rate-limited", ku_id=top.get("id", ""))
        return 0

    trace(hook_event, "injected", ku_id=top.get("id", ""))

    out = {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "additionalContext": wrap_injection(top, source="Bash error"),
        },
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
