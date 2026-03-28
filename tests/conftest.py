"""Shared test fixtures."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Ensure tests don't use real config."""
    monkeypatch.setenv("CQ_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TRANSPORT", "stdio")


@pytest.fixture
def tmp_db(tmp_path):
    """Return path to a temporary SQLite database."""
    return str(tmp_path / "test_stolperstein.db")


@pytest.fixture
def store(tmp_db, monkeypatch):
    """Create a KnowledgeStore with a temp DB and NoOp embeddings."""
    monkeypatch.setenv("CQ_LOCAL_DB_PATH", tmp_db)
    monkeypatch.setenv("CQ_EMBEDDING_API_URL", "")

    # Force NoOp embeddings for tests (no sentence-transformers needed)
    from stolperstein.embeddings import NoOpEmbeddings
    from stolperstein.store import KnowledgeStore

    s = KnowledgeStore(tmp_db)
    s._embeddings = NoOpEmbeddings()
    return s
