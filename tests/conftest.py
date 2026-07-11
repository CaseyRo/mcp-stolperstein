"""Shared test fixtures."""

from __future__ import annotations

import base64

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Ensure tests don't use real config, don't touch /data, and don't
    generate a new DID per test (use a deterministic zero-key)."""
    monkeypatch.setenv("CQ_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TRANSPORT", "stdio")
    # Deterministic signing key = no filesystem side effects for tests.
    monkeypatch.setenv(
        "MCP_STOLPERFALLE_SIGNING_KEY",
        base64.b64encode(b"\x00" * 32).decode(),
    )


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database."""
    return str(tmp_path / "test_stolperfalle.db")


@pytest.fixture
def store(tmp_db, monkeypatch):
    """Create a KnowledgeStore with a temp DB and NoOp embeddings."""
    monkeypatch.setenv("CQ_LOCAL_DB_PATH", tmp_db)
    monkeypatch.setenv("CQ_EMBEDDING_API_URL", "")

    from stolperfalle.embeddings import NoOpEmbeddings
    from stolperfalle.store import KnowledgeStore

    s = KnowledgeStore(tmp_db)
    s._embeddings = NoOpEmbeddings()
    return s
