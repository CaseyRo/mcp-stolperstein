"""Claude Code hook handlers for Stolperfalle.

Four hooks are registered (see `../hooks.json`):

- `on_session_start.py` — SessionStart — injects a static one-line pull
  discipline (query before non-trivial work; confirm/flag afterwards) so
  every session knows the KB exists.

- `on_prompt.py` — UserPromptSubmit — queries the KB when a user prompt
  contains a structured error signal (exception class name, non-zero exit
  code mention, traceback marker, HTTP status string, or explicit error
  prefix). Injects a temporally-qualified, sanitized hint on ≥0.5 confidence.

- `on_bash.py` — PostToolUse (matcher=Bash) + PostToolUseFailure (all
  tools) — queries the KB when any tool call fails, or Bash output
  contains a structured error signal.
  Fire-and-forget: 500ms budget; the hook returns immediately and the hint
  lands in the agent's next turn.

- `on_stop.py` — Stop — nudges `/stolperfalle:reflect` if the session was
  substantive (≥20 tool turns AND at least one non-zero bash exit OR one
  flag/confirm call). Also prints a one-time "Stolperfalle unreachable"
  notice if any hook attempt failed during the session.

All handlers share:

- `_common.py` — env gating, session id, unreachable marker, and the
  query → confidence-gate → rate-limit → inject pipeline.
- `_client.py` — stdlib HTTP client with per-call budget + bearer token
  sanitization.
- `_rate_limit.py` — fcntl.flock-guarded state file; 30s cooldown per hook
  type; 5min per-KU dedupe; schema-validated on read.
- `_inject.py` — fixed-template wrapper + sanitization (strips `<[^>]+>`)
  before any text reaches agent context.

Disabled via env var `STOLPERFALLE_HOOKS_DISABLED` (comma-separated list
of hook names) or by removing the hook block from settings.
"""
