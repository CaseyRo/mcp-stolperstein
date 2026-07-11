#!/usr/bin/env python3
"""UserPromptSubmit hook — queries the KB when a user prompt contains a
structured error signal and injects a sanitized, temporally-qualified hint
on ≥0.5 confidence.

Silent no-op on: conversational prompts, unconfigured MCP URL, MCP
unreachable within the query budget, rate limit suppression, KU dedupe,
or this hook being listed in `STOLPERFALLE_HOOKS_DISABLED`. Set
`STOLPERFALLE_HOOKS_DEBUG=1` to trace every decision to
`$TMPDIR/stolperfalle-hooks-debug.jsonl`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Make sibling modules importable when Claude Code runs this script directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import disabled, query_and_emit, session_id  # noqa: E402
from _debug import trace  # noqa: E402
from _signals import is_structured_error  # noqa: E402

_MAX_PROMPT_CHARS = 512
_HOOK_NAME = "UserPromptSubmit"


async def _run() -> int:
    if disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    prompt = (event.get("prompt") or "").strip()
    if not prompt or not is_structured_error(prompt):
        trace(_HOOK_NAME, "no-error-signal")
        return 0

    return await query_and_emit(
        prompt[:_MAX_PROMPT_CHARS],
        hook_event=_HOOK_NAME,
        rate_bucket=_HOOK_NAME,
        source="submitted prompt",
        sid=session_id(event),
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
