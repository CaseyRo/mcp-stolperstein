#!/usr/bin/env python3
"""Stop hook — nudges `/stolperstein:reflect` if the session was
substantive: ≥ STOLPERSTEIN_REFLECT_THRESHOLD tool-call turns AND at
least one non-zero bash exit OR one flag()/confirm() call.

Two modes:

- **Default**: emits a one-line nudge telling the user to invoke
  `/stolperstein:reflect` manually. The skill then drives the model
  through the reflect → propose flow.
- **Opt-in via STOLPERSTEIN_REFLECT_VIA_HOOK=true**: skips the nudge,
  derives a local session summary, and POSTs directly to the server's
  /hook/reflect endpoint (bypassing the MCP Portal and Anthropic's
  connector relay). Fire-and-forget — failures go to the unreachable
  marker, nothing is printed.

User-facing output goes through the `systemMessage` field of the hook's
JSON stdout — Claude Code does NOT display a Stop hook's stderr on exit 0,
so stderr prints are invisible (this silently ate every nudge and
unreachable notice in plugin ≤1.0.6).

Also emits a one-time "Stolperstein unreachable" notice if any prior hook
attempt in this session failed to reach the MCP server. Safe to call on
short/exploratory sessions — prints nothing when the bar isn't met.

Reads the session's tool-call transcript from the hook event input (Claude
Code passes `transcript_path` to the Stop hook, pointing at a JSONL file
of the session's messages).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _debug import trace  # noqa: E402

_HOOK_NAME = "Stop"
_DEFAULT_THRESHOLD = 20
_MAX_SUMMARY_TOOL_NAMES = 20
_MAX_SUMMARY_ERROR_SNIPPETS = 5
_MAX_ERROR_SNIPPET_LEN = 200


def _disabled(hook_name: str) -> bool:
    disabled = os.environ.get("STOLPERSTEIN_HOOKS_DISABLED", "").strip()
    return hook_name in {n.strip() for n in disabled.split(",") if n.strip()}


def _threshold() -> int:
    try:
        return int(os.environ.get("STOLPERSTEIN_REFLECT_THRESHOLD", _DEFAULT_THRESHOLD))
    except ValueError:
        return _DEFAULT_THRESHOLD


def _reflect_via_hook_enabled() -> bool:
    """Opt-in flag for routing reflect through POST /hook/reflect.

    False by default. When true, on_stop.py derives a compact summary
    from the transcript and calls the server directly, suppressing the
    nudge-based flow.
    """
    val = os.environ.get("STOLPERSTEIN_REFLECT_VIA_HOOK", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _session_id(event: dict) -> str:
    """Claude Code passes `session_id` in the hook event payload (there is
    no CLAUDE_SESSION_ID env var); the env fallback keeps old tests working."""
    return event.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "default"


def _unreachable_marker(session_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"stolperstein-unreachable-{session_id}"


def _analyze_transcript(
    transcript_path: str,
) -> tuple[int, bool, list[str], list[str]]:
    """Return (tool_turn_count, had_substantive_signal, tool_names, error_snippets).

    Substantive = at least one non-zero Bash exit OR at least one MCP call
    to `flag` or `confirm` (any KB mutation by the agent counts).
    `tool_names` and `error_snippets` are capped-size lists used to derive
    the session summary for direct /hook/reflect calls.
    """
    tool_turns = 0
    substantive = False
    tool_names: list[str] = []
    error_snippets: list[str] = []
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = entry.get("message") or entry
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    tool_turns += 1
                    name = block.get("name", "")
                    if len(tool_names) < _MAX_SUMMARY_TOOL_NAMES:
                        tool_names.append(name)
                    # MCP tool invocations for our server
                    if name in {"flag", "confirm"} or name.endswith("__flag") or name.endswith("__confirm"):
                        substantive = True
                    if name == "Bash":
                        # exit code lives on the tool_result in a later message;
                        # without scanning forward, we conservatively mark any
                        # Bash as potentially substantive — the threshold alone
                        # prevents noise on trivial sessions.
                        pass

                # Check tool_result blocks for non-zero Bash exit.
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_text = json.dumps(block).lower()
                        if "exit" in result_text and any(
                            f"exit code {i}" in result_text for i in range(1, 256)
                        ):
                            substantive = True
                            if len(error_snippets) < _MAX_SUMMARY_ERROR_SNIPPETS:
                                snippet = json.dumps(block)[:_MAX_ERROR_SNIPPET_LEN]
                                error_snippets.append(snippet)
    except (OSError, json.JSONDecodeError):
        return 0, False, [], []
    return tool_turns, substantive, tool_names, error_snippets


def _derive_session_summary(
    tool_turns: int,
    tool_names: list[str],
    error_snippets: list[str],
) -> str:
    """Build a compact session-summary string for POST /hook/reflect.

    The server-side reflect tool feeds this into an LLM to extract
    generalizable KU candidates, so give it enough signal without the
    full transcript: tool-use counts, the sequence of tool names, and
    any captured error snippets.
    """
    lines = [
        f"Session: {tool_turns} tool-call turns.",
    ]
    if tool_names:
        counts: dict[str, int] = {}
        for name in tool_names:
            counts[name] = counts.get(name, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(
            "Tools used: " + ", ".join(f"{n}×{c}" for n, c in top[:10])
        )
    if error_snippets:
        lines.append("Error signals:")
        for snip in error_snippets:
            lines.append(f"- {snip}")
    return "\n".join(lines)


def _consume_unreachable_notice(session_id: str) -> str | None:
    """Return the unreachable notice (and clear the marker) if one is due."""
    marker = _unreachable_marker(session_id)
    if not marker.exists():
        return None
    try:
        marker.unlink()
    except OSError:
        pass
    return (
        "Stolperstein was unreachable during this session — "
        "hook-based queries were skipped."
    )


def _emit_system_message(*parts: str | None) -> None:
    """Surface text to the user via the hook JSON `systemMessage` field.

    Stop-hook stderr is swallowed by Claude Code on exit 0; this is the
    only channel that reliably reaches the user.
    """
    messages = [p for p in parts if p]
    if not messages:
        return
    print(json.dumps({"systemMessage": " ".join(messages)}))


def _mark_unreachable(session_id: str) -> None:
    """Write the unreachable marker so the next Stop hook reports it."""
    try:
        _unreachable_marker(session_id).touch(exist_ok=True)
    except OSError:
        pass


async def _call_reflect_safely(summary: str, session_id: str) -> None:
    """Call /hook/reflect with all failures swallowed — fire-and-forget.

    The reflect endpoint's LLM-backed candidate extraction is best-effort
    from a hook context. Any failure gets recorded to the unreachable
    marker for the next Stop hook to surface; nothing is printed now.
    """
    try:
        from _client import MCPUnreachable, call_reflect
    except Exception:
        _mark_unreachable(session_id)
        return
    try:
        await call_reflect(summary)
    except MCPUnreachable:
        _mark_unreachable(session_id)
    except Exception:
        _mark_unreachable(session_id)


async def _run() -> int:
    if _disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    session_id = _session_id(event)
    notice = _consume_unreachable_notice(session_id)

    transcript_path = event.get("transcript_path") or event.get("transcriptPath")
    if not transcript_path or not os.path.exists(transcript_path):
        _emit_system_message(notice)
        return 0

    tool_turns, substantive, tool_names, error_snippets = _analyze_transcript(transcript_path)
    if tool_turns < _threshold() or not substantive:
        trace(_HOOK_NAME, "below-threshold", tool_turns=tool_turns, substantive=substantive)
        _emit_system_message(notice)
        return 0

    if _reflect_via_hook_enabled():
        summary = _derive_session_summary(tool_turns, tool_names, error_snippets)
        await _call_reflect_safely(summary, session_id)
        trace(_HOOK_NAME, "reflect-via-hook", tool_turns=tool_turns)
        _emit_system_message(notice)
        return 0

    trace(_HOOK_NAME, "nudge", tool_turns=tool_turns)
    _emit_system_message(
        notice, "Run `/stolperstein:reflect` to capture session learnings."
    )
    return 0


def run() -> int:
    """Synchronous entrypoint. Wraps the async pipeline with asyncio.run."""
    try:
        return asyncio.run(_run())
    except Exception:
        # Never let a hook failure propagate up; worst case, mark the
        # session as having had an unreachable attempt and move on.
        _mark_unreachable("default")
        return 0


if __name__ == "__main__":
    sys.exit(run())
