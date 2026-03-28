"""FastMCP server for Stolperstein — experiential knowledge capture."""

from __future__ import annotations

from fastmcp import FastMCP

from stolperstein.auth import create_auth
from stolperstein.config import settings


def _build_auth():
    """Build auth provider if running in HTTP mode."""
    if settings.transport != "http":
        return None
    api_key = settings.ensure_api_key()
    return create_auth(
        api_key=api_key,
        base_url=settings.base_url,
        keycloak_issuer=settings.keycloak_issuer,
        keycloak_audience=settings.keycloak_audience,
    )


mcp = FastMCP("mcp-stolperstein", auth=_build_auth())


@mcp.tool
async def query(
    text: str,
    domain: list[str] | None = None,
    confidence_min: float = 0.3,
    limit: int = 10,
) -> dict:
    """Search knowledge units by natural language, error signatures, or technology tags.

    Uses hybrid search combining FTS5 keyword relevance and vector cosine similarity.
    """
    from stolperstein.store import store

    return await store.query(
        text=text, domain=domain, confidence_min=confidence_min, limit=limit
    )


@mcp.tool
async def propose(
    summary: str,
    detail: str,
    action: str,
    domain: list[str],
    kind: str,
) -> dict:
    """Propose a new Knowledge Unit from a discovered insight.

    Kind must be one of: pitfall, workaround, tool-recommendation, gap-signal.
    """
    from stolperstein.store import store

    return await store.propose(
        summary=summary, detail=detail, action=action, domain=domain, kind=kind
    )


@mcp.tool
async def confirm(ku_id: str) -> dict:
    """Confirm an existing Knowledge Unit — increments confidence."""
    from stolperstein.store import store

    return await store.confirm(ku_id=ku_id)


@mcp.tool
async def flag(
    ku_id: str,
    reason: str,
    detail: str = "",
    superseded_by: str | None = None,
) -> dict:
    """Flag a Knowledge Unit as stale, incorrect, superseded, or dangerous."""
    from stolperstein.store import store

    return await store.flag(
        ku_id=ku_id, reason=reason, detail=detail, superseded_by=superseded_by
    )


@mcp.tool
async def reflect(session_summary: str) -> dict:
    """Extract generalizable learnings from a session summary.

    Returns ranked candidate KUs scored by generalizability.
    Call propose on any candidates you want to keep.
    """
    # TODO: implement LLM-based candidate extraction
    return {"candidates": [], "message": "Reflect not yet implemented"}


@mcp.tool
async def status() -> dict:
    """Report store health: KU counts, confidence distribution, staleness metrics."""
    from stolperstein.store import store

    return await store.status()


def main() -> None:
    """Entry point for the mcp-stolperstein server."""
    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
