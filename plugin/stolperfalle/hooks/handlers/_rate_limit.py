"""Rate limit + per-KU dedupe for Stolperfalle hook handlers.

Shared state lives at `$FASTMCP_HOME/hooks-state.json` (default
`~/.fastmcp/hooks-state.json`). Protected by `fcntl.flock` so concurrent
hook firings from parallel sessions don't clobber each other.

Semantics:

- **Cooldown**: no hook of the given type may inject more than once per
  `STOLPERFALLE_HOOK_COOLDOWN_S` seconds (default 30).
- **Dedupe**: the same `ku_id` is not re-injected within a 5-minute window,
  even if the cooldown has elapsed. Prevents a flaky loop from hammering
  the agent with the same hint repeatedly.
- **Schema validation on read**: corrupt or type-invalid state → reset to
  empty + rewrite atomically.
- **Lock contention**: if the advisory lock can't be acquired within 100ms,
  the hook abandons (fails closed — no injection over locked contention).
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

_DEDUPE_S = 300  # 5 minutes
_DEFAULT_COOLDOWN_S = 30
_KU_ID_RE = re.compile(r"^ku_[0-9a-f]{1,64}$")


def _state_path() -> Path:
    home = os.environ.get("FASTMCP_HOME", "").strip()
    if home:
        base = Path(home)
    else:
        base = Path.home() / ".fastmcp"
    base.mkdir(parents=True, exist_ok=True)
    return base / "hooks-state.json"


def _cooldown_s() -> int:
    try:
        return int(os.environ.get("STOLPERFALLE_HOOK_COOLDOWN_S", _DEFAULT_COOLDOWN_S))
    except ValueError:
        return _DEFAULT_COOLDOWN_S


@dataclass
class State:
    last_injection: dict[str, float]  # hook_name → epoch seconds
    recent_ku_ids: dict[str, float]   # ku_id → epoch seconds when last injected

    @classmethod
    def empty(cls) -> State:
        return cls(last_injection={}, recent_ku_ids={})

    def to_json(self) -> str:
        return json.dumps({
            "last_injection": self.last_injection,
            "recent_ku_ids": self.recent_ku_ids,
        })

    @classmethod
    def from_json(cls, raw: str) -> State | None:
        """Returns None if the state is schema-invalid (caller resets)."""
        try:
            data = json.loads(raw)
            last = data.get("last_injection", {})
            recent = data.get("recent_ku_ids", {})
            if not isinstance(last, dict) or not isinstance(recent, dict):
                return None
            last = {str(k): float(v) for k, v in last.items() if isinstance(v, (int, float))}
            recent = {
                str(k): float(v)
                for k, v in recent.items()
                if _KU_ID_RE.match(str(k)) and isinstance(v, (int, float))
            }
            return cls(last_injection=last, recent_ku_ids=recent)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None


def _prune(state: State, now: float) -> None:
    """Drop KU ids outside the dedupe window; don't prune cooldown entries
    (they naturally age out as time passes)."""
    stale = [k for k, v in state.recent_ku_ids.items() if now - v > _DEDUPE_S]
    for k in stale:
        del state.recent_ku_ids[k]


class _LockTimeout(RuntimeError):
    pass


def _acquire_lock(fd: int, timeout_s: float = 0.1) -> None:
    """Try to flock with a deadline. Raise _LockTimeout on contention."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise _LockTimeout()
            time.sleep(0.005)


def should_inject(hook_name: str, ku_id: str) -> bool:
    """Check + record an injection attempt atomically.

    Returns True if the hook may inject (and records the attempt). Returns
    False if cooldown / dedupe suppresses this one, or if the state file
    is locked by another process.
    """
    path = _state_path()
    # Open/create
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            _acquire_lock(fd, timeout_s=0.1)
        except _LockTimeout:
            return False

        now = time.time()

        # Read current state
        os.lseek(fd, 0, 0)
        raw = os.read(fd, 1024 * 32).decode("utf-8", errors="replace")
        state = State.from_json(raw) if raw.strip() else None
        if state is None:
            state = State.empty()
        _prune(state, now)

        cooldown = _cooldown_s()
        last = state.last_injection.get(hook_name, 0.0)
        if now - last < cooldown:
            return False
        if ku_id in state.recent_ku_ids:
            # Within dedupe window — suppress
            return False

        # Record + atomically rewrite via tmp-then-rename
        state.last_injection[hook_name] = now
        state.recent_ku_ids[ku_id] = now
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(state.to_json())
        tmp.replace(path)
        return True
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
