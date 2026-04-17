"""Stdlib-only HTTP client for hook handlers.

Claude Code runs these scripts with `python3` from the user's $PATH — that
Python doesn't necessarily have `fastmcp` or `httpx` installed. To keep the
plugin zero-dependency, hooks POST to a plain REST endpoint (`/hook/query`)
exposed by the server, wrapped around the MCP `query` tool.

Design:

- **HTTP-only.** Requires `MCP_STOLPERSTEIN_PUBLIC_URL` + `MCP_STOLPERSTEIN_API_KEY`.
  Without either, `call_query` returns None (silent no-op).
- **Token safety.** Bearer token is held in a local `_token` variable that
  gets `del`-eted after the request. The exception handler never propagates
  the raw header; sanitized errors are raised via `MCPUnreachable`.
- **Budget.** 500ms total ceiling. Missed deadline → abandon.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request

_BUDGET_S = 0.5


class MCPUnreachable(Exception):
    """Hook couldn't reach the MCP server within the time budget."""


def _do_http_post(url: str, body: bytes, auth_header: str) -> dict:
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": auth_header,
        },
    )
    with urllib.request.urlopen(req, timeout=_BUDGET_S) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


async def call_query(text: str, limit: int = 1, confidence_min: float = 0.5) -> dict | None:
    url = os.environ.get("MCP_STOLPERSTEIN_PUBLIC_URL", "").strip()
    if not url:
        return None
    _token = os.environ.get("MCP_STOLPERSTEIN_API_KEY", "").strip()
    if not _token:
        return None

    endpoint = url.rstrip("/") + "/hook/query"
    body = json.dumps({
        "text": text,
        "limit": limit,
        "confidence_min": confidence_min,
    }).encode("utf-8")

    auth_header = f"Bearer {_token}"
    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _do_http_post, endpoint, body, auth_header),
            timeout=_BUDGET_S,
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
    finally:
        del _token
        del auth_header
