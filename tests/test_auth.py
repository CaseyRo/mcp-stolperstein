"""Tests for authentication — mirrors mcp-siyuan/tests/test_auth.py."""

from __future__ import annotations

import pytest

from stolperfalle.auth import (
    BearerTokenVerifier,
    create_bearer_only_auth,
    generate_api_key,
)


@pytest.mark.asyncio
async def test_bearer_valid_token():
    """Valid token is accepted."""
    verifier = BearerTokenVerifier("stmcp_test_key_123")
    result = await verifier.verify_token("stmcp_test_key_123")
    assert result is not None
    assert result.client_id == "mcp-stolperfalle-client"
    assert "all" in result.scopes


@pytest.mark.asyncio
async def test_bearer_invalid_token():
    """Invalid token is rejected."""
    verifier = BearerTokenVerifier("stmcp_test_key_123")
    result = await verifier.verify_token("stmcp_wrong_key")
    assert result is None


@pytest.mark.asyncio
async def test_bearer_empty_token():
    """Empty token is rejected."""
    verifier = BearerTokenVerifier("stmcp_test_key_123")
    result = await verifier.verify_token("")
    assert result is None


def test_generate_api_key_prefix():
    """Generated keys have stmcp_ prefix."""
    key = generate_api_key()
    assert key.startswith("stmcp_")


def test_generate_api_key_unique():
    """Generated keys are unique."""
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_generate_api_key_length():
    """Generated keys are sufficiently long."""
    key = generate_api_key()
    # stmcp_ + 43 chars of base64url = 49+ chars
    assert len(key) >= 40


def test_bearer_only_auth_builds_without_oidc():
    """create_bearer_only_auth returns a MultiAuth with no OIDC server,
    usable behind the CF MCP Portal (no OIDC discovery URL required).
    """
    from fastmcp.server.auth import MultiAuth

    auth = create_bearer_only_auth(api_key="stmcp_test", base_url="http://localhost:8716")
    assert isinstance(auth, MultiAuth)
    # Sanity: the OIDC `server` slot is None so no discovery URL is fetched
    # (which is the whole point — we don't have an OIDC provider).
    assert auth.server is None
