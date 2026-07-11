"""Tests for the /hook/* REST endpoints on the stolperfalle MCP server.

These exercise the handler functions directly with a mock request to avoid
bringing up a full starlette app. The handlers themselves hold all the auth,
parsing, and validation logic we want to verify.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


class _MockRequest:
    """Minimal stand-in for a starlette Request with the fields our handlers touch."""

    def __init__(self, headers: dict[str, str] | None = None, body: Any = None):
        self.headers = headers or {}
        self._body = body

    async def json(self) -> Any:
        if isinstance(self._body, str):
            return json.loads(self._body)  # will raise for bad JSON
        if isinstance(self._body, (dict, list)):
            return self._body
        raise ValueError("body is not JSON")


def _auth_headers(token: str = "stmcp_test_key") -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


async def _body(response) -> dict:
    """Extract the JSON body from a starlette JSONResponse."""
    return json.loads(bytes(response.body).decode())


@pytest.fixture
def http_settings(monkeypatch):
    """Force the server into HTTP mode with a known API key for this test."""
    from pydantic import SecretStr

    monkeypatch.setenv("TRANSPORT", "http")
    monkeypatch.setenv("MCP_STOLPERFALLE_API_KEY", "stmcp_test_key")
    from stolperfalle.config import settings as cfg
    monkeypatch.setattr(cfg, "transport", "http")
    monkeypatch.setattr(cfg, "mcp_stolperfalle_api_key", SecretStr("stmcp_test_key"))
    return cfg


# --- /hook/reflect --------------------------------------------------------


class TestHookReflectAuth:
    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(_MockRequest(headers={}))
        assert resp.status_code == 401
        assert (await _body(resp))["error"] == "bearer token required"

    @pytest.mark.asyncio
    async def test_wrong_bearer_returns_401(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers={"authorization": "Bearer wrong"})
        )
        assert resp.status_code == 401
        assert (await _body(resp))["error"] == "invalid bearer token"


class TestHookReflectValidation:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body="not-json")
        )
        assert resp.status_code == 400
        assert (await _body(resp))["error"] == "invalid JSON body"

    @pytest.mark.asyncio
    async def test_non_object_body_returns_400(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body=["array", "not", "object"])
        )
        assert resp.status_code == 400
        assert "JSON body must be an object" in (await _body(resp))["error"]

    @pytest.mark.asyncio
    async def test_missing_session_summary_returns_400(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body={})
        )
        assert resp.status_code == 400
        b = await _body(resp)
        assert b["error"] == "validation"
        assert "session_summary" in b["message"]

    @pytest.mark.asyncio
    async def test_empty_session_summary_returns_400(self, http_settings):
        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body={"session_summary": "   "})
        )
        assert resp.status_code == 400


class TestHookReflectSuccess:
    @pytest.mark.asyncio
    async def test_valid_body_invokes_reflect_with_dedup(self, http_settings, monkeypatch):
        fake_result = {"candidates": [], "dedup_info": "none"}

        async def fake_reflect(summary, *, store):
            assert summary == "real summary"
            return fake_result

        import stolperfalle.reflect as reflect_mod
        monkeypatch.setattr(reflect_mod, "reflect_with_dedup", fake_reflect)

        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(
                headers=_auth_headers(),
                body={"session_summary": "real summary"},
            )
        )
        assert resp.status_code == 200
        assert await _body(resp) == fake_result

    @pytest.mark.asyncio
    async def test_handler_exception_returns_sanitized_500(self, http_settings, monkeypatch):
        async def fake_reflect(summary, *, store):
            raise RuntimeError("sensitive-looking internal detail")

        import stolperfalle.reflect as reflect_mod
        monkeypatch.setattr(reflect_mod, "reflect_with_dedup", fake_reflect)

        from stolperfalle.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(
                headers=_auth_headers(),
                body={"session_summary": "trigger"},
            )
        )
        assert resp.status_code == 500
        b = await _body(resp)
        assert b["error"] == "internal"
        # Only the exception type name leaks — not the message
        assert "sensitive-looking" not in json.dumps(b)
        assert b["message"] == "RuntimeError"


# --- /hook/query regression ----------------------------------------------


class TestHookQueryRegression:
    """Ensure the refactor to use _hook_authorize didn't change behavior."""

    @pytest.mark.asyncio
    async def test_missing_text_returns_400(self, http_settings):
        from stolperfalle.server import hook_query
        resp = await hook_query(
            _MockRequest(headers=_auth_headers(), body={})
        )
        assert resp.status_code == 400
        assert (await _body(resp))["error"] == "text required"

    @pytest.mark.asyncio
    async def test_wrong_bearer_still_401(self, http_settings):
        from stolperfalle.server import hook_query
        resp = await hook_query(
            _MockRequest(headers={"authorization": "Bearer nope"})
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_query_invokes_store(self, http_settings, monkeypatch):
        async def fake_query(*, text, domain, confidence_min, limit):
            return {"results": [{"stub": text}], "count": 1}

        import stolperfalle.store as store_mod
        monkeypatch.setattr(store_mod.store, "query", fake_query)

        from stolperfalle.server import hook_query
        resp = await hook_query(
            _MockRequest(
                headers=_auth_headers(),
                body={"text": "searchable"},
            )
        )
        assert resp.status_code == 200
        assert (await _body(resp))["count"] == 1


# --- transport guard ------------------------------------------------------


class TestTransportGuard:
    """When server is in stdio mode, /hook/* endpoints refuse to work."""

    @pytest.mark.asyncio
    async def test_stdio_transport_returns_503(self, monkeypatch):
        from stolperfalle.config import settings as cfg
        monkeypatch.setattr(cfg, "transport", "stdio")
        monkeypatch.setattr(cfg, "mcp_stolperfalle_api_key", "stmcp_test_key")

        from stolperfalle.server import hook_reflect, hook_query
        for handler in (hook_query, hook_reflect):
            resp = await handler(_MockRequest(headers=_auth_headers()))
            assert resp.status_code == 503
