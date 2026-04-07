"""FastMCP server for Stolperstein — experiential knowledge capture."""

from __future__ import annotations

from fastmcp import FastMCP
from mcp.types import Icon, ToolAnnotations

from stolperstein.auth import create_auth
from stolperstein.config import settings


def _build_auth():
    """Build auth provider if running in HTTP mode."""
    if settings.transport != "http":
        return None
    if not settings.cf_access_client_secret:
        import logging

        logging.getLogger(__name__).warning(
            "CF_ACCESS_CLIENT_SECRET not set — OIDC proxy auth disabled"
        )
        return None
    api_key = settings.ensure_api_key()
    return create_auth(
        api_key=api_key,
        base_url=settings.base_url,
        cf_access_config_url=settings.cf_access_config_url,
        cf_access_client_id=settings.cf_access_client_id,
        cf_access_client_secret=settings.cf_access_client_secret,
    )


mcp = FastMCP(
    "mcp-stolperstein",
    auth=_build_auth(),
    icons=[
        Icon(
            src="data:image/png;base64,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",
            mimeType="image/png",
            sizes=["96x96"],
        ),
    ],
)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
async def confirm(ku_id: str) -> dict:
    """Confirm an existing Knowledge Unit — increments confidence."""
    from stolperstein.store import store

    return await store.confirm(ku_id=ku_id)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True))
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def reflect(session_summary: str) -> dict:
    """Extract generalizable learnings from a session summary.

    Returns ranked candidate KUs scored by generalizability.
    Call propose on any candidates you want to keep.
    """
    from stolperstein.reflect import reflect_with_dedup
    from stolperstein.store import store

    return await reflect_with_dedup(session_summary, store=store)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
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
