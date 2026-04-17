"""In-repo migration runner.

Design (openspec/changes/cq-v1-alignment-and-hooks/design.md §2):

- Migrations are Python modules under this package named `mNNNN_<slug>.py`,
  each exposing `version: int`, `breaking: bool`, `slug: str`, and
  `up(conn: sqlite3.Connection) -> None`.
- The highest applied version is recorded in a single-row `schema_version`
  table, created on first run.
- `run(conn)` applies every registered migration whose version exceeds the
  stored one, in ascending order, each in its own transaction.
- Before any `breaking=True` migration, the runner takes a file-copy snapshot
  at `<db>.bak-pre-v<N>` and refuses to overwrite an existing backup.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class MigrationModule(Protocol):
    version: int
    breaking: bool
    slug: str

    def up(self, conn: sqlite3.Connection) -> None: ...


@dataclass(frozen=True)
class Migration:
    version: int
    breaking: bool
    slug: str
    up: Callable[[sqlite3.Connection], None]

    @property
    def id(self) -> str:
        return f"m{self.version:04d}_{self.slug}"


def _discover_migrations() -> list[Migration]:
    """Find all `mNNNN_*.py` submodules and turn them into Migration objects.
    Order: ascending by version. Duplicates raise.
    """
    pkg_path = Path(__file__).parent
    found: list[Migration] = []
    seen_versions: set[int] = set()
    for m in pkgutil.iter_modules([str(pkg_path)]):
        name = m.name
        if not (name.startswith("m") and name[1:5].isdigit()):
            continue
        mod = importlib.import_module(f"{__name__}.{name}")
        version = int(getattr(mod, "version"))
        if version in seen_versions:
            raise RuntimeError(f"duplicate migration version {version} in {name}")
        seen_versions.add(version)
        found.append(
            Migration(
                version=version,
                breaking=bool(getattr(mod, "breaking")),
                slug=str(getattr(mod, "slug")),
                up=getattr(mod, "up"),
            )
        )
    found.sort(key=lambda x: x.version)
    return found


def registered() -> list[Migration]:
    """Return the discovered migrations. Re-discovers on each call so tests
    can add fixtures dynamically.
    """
    return _discover_migrations()


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  id INTEGER PRIMARY KEY CHECK (id = 1),"
        "  version INTEGER NOT NULL DEFAULT 0,"
        "  updated_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (id, version, updated_at) "
        "VALUES (1, 0, datetime('now'))"
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_schema_version_table(conn)
    row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return int(row[0]) if row else 0


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "UPDATE schema_version SET version = ?, updated_at = datetime('now') WHERE id = 1",
        [version],
    )


def _snapshot(db_path: str, target_version: int) -> str:
    """Copy the DB file to <db>.bak-pre-v<N>. Raise if the backup exists."""
    src = Path(db_path)
    bak = src.with_suffix(src.suffix + f".bak-pre-v{target_version}")
    if bak.exists():
        raise RuntimeError(
            f"Pre-migration backup already exists at {bak}. "
            "Refusing to overwrite. Either restore from it or remove it manually "
            "with `mcp-stolperstein prune-backups --confirm`."
        )
    shutil.copy2(str(src), str(bak))
    logger.info("Snapshot: %s -> %s", src, bak)
    return str(bak)


@dataclass
class RunResult:
    from_version: int
    to_version: int
    applied: list[str]
    snapshots: list[str]


def run(conn: sqlite3.Connection, db_path: str | None = None) -> RunResult:
    """Apply all pending migrations. Takes pre-migration snapshots for
    breaking migrations (requires `db_path`). Returns the run summary.
    """
    migrations = registered()
    from_version = current_version(conn)
    applied: list[str] = []
    snapshots: list[str] = []

    for m in migrations:
        if m.version <= from_version:
            continue
        if m.breaking:
            if db_path is None:
                raise RuntimeError(
                    f"Migration {m.id} is breaking but no db_path provided; "
                    "cannot take pre-migration snapshot."
                )
            snapshots.append(_snapshot(db_path, m.version))

        logger.info("Applying %s (breaking=%s)", m.id, m.breaking)
        try:
            m.up(conn)
            _set_version(conn, m.version)
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Migration %s failed; rolled back", m.id)
            raise
        applied.append(m.id)

    return RunResult(
        from_version=from_version,
        to_version=current_version(conn),
        applied=applied,
        snapshots=snapshots,
    )
