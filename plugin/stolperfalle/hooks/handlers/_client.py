"""Stdlib-only HTTP client for hook handlers.

Claude Code runs these scripts with `python3` from the user's $PATH — that
Python doesn't necessarily have `fastmcp` or `httpx` installed. To keep the
plugin zero-dependency, hooks POST to plain REST endpoints exposed by the
server (`/hook/query`, `/hook/reflect`), each wrapping the corresponding
MCP tool.

Design:

- **HTTP-only.** Requires `MCP_STOLPERFALLE_PUBLIC_URL` + `MCP_STOLPERFALLE_API_KEY`.
  Without either, helpers return None (silent no-op).
- **Token safety.** Exception handlers never propagate raw error text
  (which may embed the auth header); sanitized errors are raised via
  `MCPUnreachable`.
- **Budgets.** Per-helper timeout ceiling. Missed deadline → abandon.
  `call_query` defaults to 1.5s (TLS handshake + Cloudflare proxy RTT is
  ~200-400ms before the server even starts the FTS5 + vec0 search; the
  original 500ms budget false-negatived on any cold connection).
  `call_reflect` defaults to 5s (LLM-backed candidate extraction).
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

_DEFAULT_BUDGET_S = 1.5
_REFLECT_BUDGET_S = 5.0


class MCPUnreachable(Exception):
    """Hook couldn't reach the MCP server within the time budget."""


def _do_http_post(url: str, body: bytes, auth_header: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth_header,
            # Cloudflare bot protection 403s the default Python-urllib/x.y
            # User-Agent before the request ever reaches the server.
            "User-Agent": "stolperfalle-hook/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


async def _call_hook(path: str, payload: dict[str, Any], budget_s: float) -> dict | None:
    """Shared hook POST: env-gate, build auth header, dispatch, sanitize errors.

    Returns None when env is unset. Raises MCPUnreachable on failure.
    """
    url = os.environ.get("MCP_STOLPERFALLE_PUBLIC_URL", "").strip()
    if not url:
        return None
    token = os.environ.get("MCP_STOLPERFALLE_API_KEY", "").strip()
    if not token:
        return None

    endpoint = url.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    auth_header = f"Bearer {token}"

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None, _do_http_post, endpoint, body, auth_header, budget_s
            ),
            timeout=budget_s,
        )
        return result
    except asyncio.TimeoutError:
        raise MCPUnreachable("budget exceeded") from None
    except urllib.error.HTTPError as e:
        # Never include the bearer token in the raised message.
        raise MCPUnreachable(f"HTTP {e.code}") from None
    except urllib.error.URLError:
        raise MCPUnreachable("connection failed") from None
    except Exception:
        # Catch-all: never let raw exception text (which may contain headers)
        # propagate out. Re-raise sanitized.
        raise MCPUnreachable("request failed") from None


async def call_query(
    text: str,
    limit: int = 1,
    confidence_min: float = 0.5,
    *,
    budget_s: float = _DEFAULT_BUDGET_S,
) -> dict | None:
    """Wrap POST /hook/query. Returns KU match dict or None when unreachable."""
    return await _call_hook(
        "/hook/query",
        {"text": text, "limit": limit, "confidence_min": confidence_min},
        budget_s,
    )


async def call_reflect(
    session_summary: str,
    *,
    budget_s: float = _REFLECT_BUDGET_S,
) -> dict | None:
    """Wrap POST /hook/reflect. Returns `{candidates: [...], ...}` or None.

    Longer default budget because the server-side reflect invokes an LLM to
    generate candidate KUs from the summary. 500ms is too tight; 5s covers
    typical first-token latency + payload assembly.
    """
    return await _call_hook(
        "/hook/reflect",
        {"session_summary": session_summary},
        budget_s,
    )
