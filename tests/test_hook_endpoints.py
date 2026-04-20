"""Tests for the /hook/* REST endpoints on the stolperstein MCP server.

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
    monkeypatch.setenv("TRANSPORT", "http")
    monkeypatch.setenv("MCP_STOLPERSTEIN_API_KEY", "stmcp_test_key")
    from stolperstein.config import settings as cfg
    monkeypatch.setattr(cfg, "transport", "http")
    monkeypatch.setattr(cfg, "mcp_stolperstein_api_key", "stmcp_test_key")
    return cfg


# --- /hook/reflect --------------------------------------------------------


class TestHookReflectAuth:
    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, http_settings):
        from stolperstein.server import hook_reflect
        resp = await hook_reflect(_MockRequest(headers={}))
        assert resp.status_code == 401
        assert (await _body(resp))["error"] == "bearer token required"

    @pytest.mark.asyncio
    async def test_wrong_bearer_returns_401(self, http_settings):
        from stolperstein.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers={"authorization": "Bearer wrong"})
        )
        assert resp.status_code == 401
        assert (await _body(resp))["error"] == "invalid bearer token"


class TestHookReflectValidation:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, http_settings):
        from stolperstein.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body="not-json")
        )
        assert resp.status_code == 400
        assert (await _body(resp))["error"] == "invalid JSON body"

    @pytest.mark.asyncio
    async def test_non_object_body_returns_400(self, http_settings):
        from stolperstein.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body=["array", "not", "object"])
        )
        assert resp.status_code == 400
        assert "JSON body must be an object" in (await _body(resp))["error"]

    @pytest.mark.asyncio
    async def test_missing_session_summary_returns_400(self, http_settings):
        from stolperstein.server import hook_reflect
        resp = await hook_reflect(
            _MockRequest(headers=_auth_headers(), body={})
        )
        assert resp.status_code == 400
        b = await _body(resp)
        assert b["error"] == "validation"
        assert "session_summary" in b["message"]

    @pytest.mark.asyncio
    async def test_empty_session_summary_returns_400(self, http_settings):
        from stolperstein.server import hook_reflect
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

        import stolperstein.reflect as reflect_mod
        monkeypatch.setattr(reflect_mod, "reflect_with_dedup", fake_reflect)

        from stolperstein.server import hook_reflect
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

        import stolperstein.reflect as reflect_mod
        monkeypatch.setattr(reflect_mod, "reflect_with_dedup", fake_reflect)

        from stolperstein.server import hook_reflect
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


# --- /hook/propose --------------------------------------------------------


class TestHookProposeAuth:
    @pytest.mark.asyncio
    async def test_missing_bearer_returns_401(self, http_settings):
        from stolperstein.server import hook_propose
        resp = await hook_propose(_MockRequest(headers={}))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_bearer_returns_401(self, http_settings):
        from stolperstein.server import hook_propose
        resp = await hook_propose(
            _MockRequest(headers={"authorization": "Bearer wrong"})
        )
        assert resp.status_code == 401


class TestHookProposeValidation:
    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, http_settings):
        from stolperstein.server import hook_propose
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body="not-json")
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_empty_body_lists_all_missing_fields(self, http_settings):
        from stolperstein.server import hook_propose
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body={})
        )
        assert resp.status_code == 400
        b = await _body(resp)
        assert b["error"] == "validation"
        for field in ("summary", "detail", "action", "domains", "kind"):
            assert field in b["message"]

    @pytest.mark.asyncio
    async def test_domains_must_be_list_of_strings(self, http_settings):
        from stolperstein.server import hook_propose
        payload = {
            "summary": "s", "detail": "d", "action": "a",
            "domains": "not-a-list", "kind": "pitfall",
        }
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body=payload)
        )
        assert resp.status_code == 400
        assert "domains" in (await _body(resp))["message"]

    @pytest.mark.asyncio
    async def test_domains_rejects_non_string_items(self, http_settings):
        from stolperstein.server import hook_propose
        payload = {
            "summary": "s", "detail": "d", "action": "a",
            "domains": ["ok", 42], "kind": "pitfall",
        }
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body=payload)
        )
        assert resp.status_code == 400


class TestHookProposeSuccess:
    @pytest.mark.asyncio
    async def test_required_fields_only_invokes_store_propose(self, http_settings, monkeypatch):
        captured: dict[str, Any] = {}
        fake_result = {"ku": {"id": "ku_deadbeef"}, "duplicate_of": None, "message": None}

        async def fake_propose(**kwargs):
            captured.update(kwargs)
            return fake_result

        import stolperstein.store as store_mod
        monkeypatch.setattr(store_mod.store, "propose", fake_propose)

        from stolperstein.server import hook_propose
        payload = {
            "summary": "hooks-reachable summary",
            "detail": "full detail body",
            "action": "do the thing",
            "domains": ["python", "testing"],
            "kind": "pitfall",
        }
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body=payload)
        )
        assert resp.status_code == 200
        assert await _body(resp) == fake_result
        assert captured["summary"] == "hooks-reachable summary"
        assert captured["domains"] == ["python", "testing"]
        assert captured["severity"] == "medium"  # default applied

    @pytest.mark.asyncio
    async def test_all_optional_fields_pass_through(self, http_settings, monkeypatch):
        captured: dict[str, Any] = {}

        async def fake_propose(**kwargs):
            captured.update(kwargs)
            return {"ku": {"id": "ku_1"}, "duplicate_of": None, "message": None}

        import stolperstein.store as store_mod
        monkeypatch.setattr(store_mod.store, "propose", fake_propose)

        from stolperstein.server import hook_propose
        payload = {
            "summary": "s", "detail": "d", "action": "a",
            "domains": ["swift"], "kind": "pitfall",
            "severity": "high",
            "context_languages": ["swift"],
            "context_frameworks": ["swiftui"],
            "context_environment": "xcode-16",
            "context_pattern": "concurrency",
        }
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body=payload)
        )
        assert resp.status_code == 200
        assert captured["severity"] == "high"
        assert captured["context_languages"] == ["swift"]
        assert captured["context_environment"] == "xcode-16"

    @pytest.mark.asyncio
    async def test_handler_exception_returns_sanitized_500(self, http_settings, monkeypatch):
        async def fake_propose(**kwargs):
            raise ValueError("internal validation detail")

        import stolperstein.store as store_mod
        monkeypatch.setattr(store_mod.store, "propose", fake_propose)

        from stolperstein.server import hook_propose
        payload = {
            "summary": "s", "detail": "d", "action": "a",
            "domains": ["x"], "kind": "pitfall",
        }
        resp = await hook_propose(
            _MockRequest(headers=_auth_headers(), body=payload)
        )
        assert resp.status_code == 500
        b = await _body(resp)
        assert b["error"] == "internal"
        assert "internal validation detail" not in json.dumps(b)
        assert b["message"] == "ValueError"


# --- /hook/query regression ----------------------------------------------


class TestHookQueryRegression:
    """Ensure the refactor to use _hook_authorize didn't change behavior."""

    @pytest.mark.asyncio
    async def test_missing_text_returns_400(self, http_settings):
        from stolperstein.server import hook_query
        resp = await hook_query(
            _MockRequest(headers=_auth_headers(), body={})
        )
        assert resp.status_code == 400
        assert (await _body(resp))["error"] == "text required"

    @pytest.mark.asyncio
    async def test_wrong_bearer_still_401(self, http_settings):
        from stolperstein.server import hook_query
        resp = await hook_query(
            _MockRequest(headers={"authorization": "Bearer nope"})
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_query_invokes_store(self, http_settings, monkeypatch):
        async def fake_query(*, text, domain, confidence_min, limit):
            return {"results": [{"stub": text}], "count": 1}

        import stolperstein.store as store_mod
        monkeypatch.setattr(store_mod.store, "query", fake_query)

        from stolperstein.server import hook_query
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
        from stolperstein.config import settings as cfg
        monkeypatch.setattr(cfg, "transport", "stdio")
        monkeypatch.setattr(cfg, "mcp_stolperstein_api_key", "stmcp_test_key")

        from stolperstein.server import hook_reflect, hook_propose, hook_query
        for handler in (hook_query, hook_reflect, hook_propose):
            resp = await handler(_MockRequest(headers=_auth_headers()))
            assert resp.status_code == 503
