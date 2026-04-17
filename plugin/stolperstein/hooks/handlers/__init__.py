"""Claude Code hook handlers for Stolperstein.

Three hooks are registered (see `../hooks.json`):

- `on_prompt.py` — UserPromptSubmit — queries the KB when a user prompt
  contains a structured error signal (exception class name, non-zero exit
  code mention, traceback marker, HTTP status string, or explicit error
  prefix). Injects a temporally-qualified, sanitized hint on ≥0.5 confidence.

- `on_bash.py` — PostToolUse (matcher=Bash) — queries the KB when a Bash
  tool call exits non-zero or stderr contains a structured error signal.
  Fire-and-forget: 500ms budget; the hook returns immediately and the hint
  lands in the agent's next turn.

- `on_stop.py` — Stop — nudges `/stolperstein:reflect` if the session was
  substantive (≥20 tool turns AND at least one non-zero bash exit OR one
  flag/confirm call). Also prints a one-time "Stolperstein unreachable"
  notice if any hook attempt failed during the session.

All handlers share:

- `_client.py` — HTTP MCP client with 500ms budget + bearer token sanitization.
- `_rate_limit.py` — fcntl.flock-guarded state file; 30s cooldown per hook
  type; 5min per-KU dedupe; schema-validated on read.
- `_inject.py` — fixed-template wrapper + sanitization (strips `<[^>]+>`)
  before any text reaches agent context.

Disabled via env var `STOLPERSTEIN_HOOKS_DISABLED` (comma-separated list
of hook names) or by removing the hook block from settings.
"""
