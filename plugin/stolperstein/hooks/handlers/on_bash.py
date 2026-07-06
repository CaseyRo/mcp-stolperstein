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

from _common import disabled, query_and_emit, session_id  # noqa: E402
from _debug import trace  # noqa: E402
from _signals import is_structured_error  # noqa: E402

_HOOK_NAME = "PostToolUse"
_STDERR_CHARS = 4096


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
    """Given a Bash PostToolUse/PostToolUseFailure event payload, decide
    whether to fire and return the text to query with (or None for no-op).
    """
    if event.get("tool_name") != "Bash":
        return None
    if event.get("is_interrupt"):
        # User cancellation, not an error worth recalling knowledge for.
        return None

    texts = _texts_from(event.get("tool_response") or {})

    # PostToolUseFailure events carry NO tool_response at all — the failure
    # text lives in a top-level `error` string ("Exit code N\n<stderr>").
    # Observed live 2026-06-11; do not trust docs claiming otherwise.
    err = event.get("error")
    failed = isinstance(err, str) and bool(err.strip())
    if failed:
        texts.append(err.strip())

    combined = "\n".join(texts).strip()

    exit_code = 0
    resp = event.get("tool_response")
    if isinstance(resp, dict):
        exit_code = resp.get("exitCode", resp.get("exit_code", 0)) or 0

    if not failed and exit_code == 0 and not is_structured_error(combined):
        return None

    return combined[-_STDERR_CHARS:] if combined else None


async def _run() -> int:
    if disabled(_HOOK_NAME):
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
            event_keys=sorted(event.keys()),
        )
        return 0

    return await query_and_emit(
        signal_text,
        hook_event=hook_event,
        rate_bucket=_HOOK_NAME,
        source="Bash error",
        sid=session_id(event),
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
