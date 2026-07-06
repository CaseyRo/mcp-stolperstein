"""Tests for Pydantic Settings configuration."""

from __future__ import annotations



def test_default_settings(monkeypatch):
    """Settings load with sane defaults."""
    monkeypatch.setenv("TRANSPORT", "stdio")
    monkeypatch.setenv("CQ_LOCAL_DB_PATH", "/tmp/test.db")

    from stolperstein.config import Settings

    s = Settings()
    assert s.transport == "stdio"
    assert s.port == 8716
    assert s.cq_embedding_model == "all-MiniLM-L6-v2"
    assert s.trusted_orgs == "*"


def test_ensure_api_key_generates(monkeypatch):
    """ensure_api_key() auto-generates stmcp_ key when not set."""
    monkeypatch.setenv("MCP_STOLPERSTEIN_API_KEY", "")

    from stolperstein.config import Settings

    s = Settings()
    key = s.ensure_api_key()
    assert key.startswith("stmcp_")
    # Second call returns the same key
    assert s.ensure_api_key() == key


def test_ensure_api_key_preserves_existing(monkeypatch):
    """ensure_api_key() returns existing key when set."""
    monkeypatch.setenv("MCP_STOLPERSTEIN_API_KEY", "stmcp_existing_key")

    from stolperstein.config import Settings

    s = Settings()
    assert s.ensure_api_key() == "stmcp_existing_key"


def test_base_url_from_public_url(monkeypatch):
    """base_url uses public URL when set."""
    monkeypatch.setenv("MCP_STOLPERSTEIN_PUBLIC_URL", "https://mcp-stolperstein.cdit-dev.de")

    from stolperstein.config import Settings

    s = Settings()
    assert s.base_url == "https://mcp-stolperstein.cdit-dev.de"


def test_base_url_computed_from_host_port(monkeypatch):
    """base_url computed from host:port when no public URL."""
    monkeypatch.setenv("MCP_STOLPERSTEIN_PUBLIC_URL", "")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8716")

    from stolperstein.config import Settings

    s = Settings()
    assert s.base_url == "http://0.0.0.0:8716"
