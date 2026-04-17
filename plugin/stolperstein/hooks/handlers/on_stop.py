#!/usr/bin/env python3
"""Stop hook — nudges `/stolperstein:reflect` if the session was
substantive: ≥ STOLPERSTEIN_REFLECT_THRESHOLD tool-call turns AND at
least one non-zero bash exit OR one flag()/confirm() call.

Also prints a one-time "Stolperstein unreachable" notice if any prior hook
attempt in this session failed to reach the MCP server. Safe to call on
short/exploratory sessions — prints nothing when the bar isn't met.

Reads the session's tool-call transcript from the hook event input (Claude
Code passes `transcript_path` to the Stop hook, pointing at a JSONL file
of the session's messages).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_HOOK_NAME = "Stop"
_DEFAULT_THRESHOLD = 20


def _disabled(hook_name: str) -> bool:
    disabled = os.environ.get("STOLPERSTEIN_HOOKS_DISABLED", "").strip()
    return hook_name in {n.strip() for n in disabled.split(",") if n.strip()}


def _threshold() -> int:
    try:
        return int(os.environ.get("STOLPERSTEIN_REFLECT_THRESHOLD", _DEFAULT_THRESHOLD))
    except ValueError:
        return _DEFAULT_THRESHOLD


def _unreachable_marker() -> Path:
    session_id = os.environ.get("CLAUDE_SESSION_ID") or "default"
    return Path(tempfile.gettempdir()) / f"stolperstein-unreachable-{session_id}"


def _analyze_transcript(transcript_path: str) -> tuple[int, bool]:
    """Return (tool_turn_count, had_substantive_signal).

    Substantive = at least one non-zero Bash exit OR at least one MCP call
    to `flag` or `confirm` (any KB mutation by the agent counts).
    """
    tool_turns = 0
    substantive = False
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
    except (OSError, json.JSONDecodeError):
        return 0, False
    return tool_turns, substantive


def _print_unreachable_notice() -> None:
    marker = _unreachable_marker()
    if marker.exists():
        print(
            "Stolperstein was unreachable during this session — "
            "hook-based queries were skipped.",
            file=sys.stderr,
        )
        try:
            marker.unlink()
        except OSError:
            pass


def run() -> int:
    if _disabled(_HOOK_NAME):
        return 0

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        event = {}

    _print_unreachable_notice()

    transcript_path = event.get("transcript_path") or event.get("transcriptPath")
    if not transcript_path or not os.path.exists(transcript_path):
        return 0

    tool_turns, substantive = _analyze_transcript(transcript_path)
    if tool_turns < _threshold() or not substantive:
        return 0

    print("Run `/stolperstein:reflect` to capture session learnings.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(run())
