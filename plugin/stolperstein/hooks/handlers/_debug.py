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


# Rotate the trace file once it exceeds this size. One ~150-byte line per
# hook decision across ALL sessions adds up; without a cap the file grows
# forever. At most cap + one .1 backup (~2 MiB total) lives on disk.
_MAX_BYTES = 1_048_576  # 1 MiB


def _enabled() -> bool:
    val = os.environ.get("STOLPERSTEIN_HOOKS_DEBUG", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def trace_path() -> Path:
    return Path(tempfile.gettempdir()) / "stolperstein-hooks-debug.jsonl"


def _rotate_if_needed(path: Path) -> None:
    """Move an oversized trace file to `<name>.1` (replacing any existing
    backup) so the next append starts fresh. Never raises — trace failures
    must not break hooks."""
    try:
        if path.exists() and path.stat().st_size > _MAX_BYTES:
            path.replace(path.with_name(path.name + ".1"))
    except OSError:
        pass


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
        path = trace_path()
        _rotate_if_needed(path)
        with open(path, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass
