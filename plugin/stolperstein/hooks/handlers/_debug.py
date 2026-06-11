"""Opt-in debug trace for hook handlers.

Set `STOLPERSTEIN_HOOKS_DEBUG=1` and every handler appends one JSON line
per decision to `$TMPDIR/stolperstein-hooks-debug.jsonl` — including the
no-op paths that are otherwise silent by design. This exists because the
hooks fail closed everywhere; without a trace, "hooks never worked" is
indistinguishable from "hooks never fired."
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path


def _enabled() -> bool:
    val = os.environ.get("STOLPERSTEIN_HOOKS_DEBUG", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def trace_path() -> Path:
    return Path(tempfile.gettempdir()) / "stolperstein-hooks-debug.jsonl"


def trace(hook: str, decision: str, **fields: object) -> None:
    """Append a decision record. Never raises; no-op unless debug is on."""
    if not _enabled():
        return
    record: dict[str, object] = {
        "ts": round(time.time(), 3),
        "hook": hook,
        "decision": decision,
    }
    record.update(fields)
    try:
        with open(trace_path(), "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
