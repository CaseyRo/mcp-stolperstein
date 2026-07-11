#!/usr/bin/env python3
"""SessionStart hook — injects a one-line pull discipline for the KB.

Static text, zero network. The point: every session knows the KB exists
and when to query it, without depending on the MCP server instructions
having been loaded in that session. Actual pulls stay model-driven (the
`query` tool) or error-driven (on_prompt / on_bash).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import disabled  # noqa: E402

_HOOK_NAME = "SessionStart"

# ponytail: static nudge, no store round-trip — there is no reliable query
# text at session start; upgrade to a live query if a good signal appears.
_NUDGE = (
    "Stolperfalle (experiential knowledge base) is active. Pull before you "
    "rediscover: on any non-trivial task — unfamiliar error, API, or tech "
    "stack — call the stolperfalle `query` tool first. When a recalled KU's "
    "advice holds, call `confirm(ku_id)`; when it is wrong or stale, `flag` "
    "it. Error-driven recall also fires automatically via hooks."
)


def main() -> int:
    if disabled(_HOOK_NAME):
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": _HOOK_NAME,
            "additionalContext": _NUDGE,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
