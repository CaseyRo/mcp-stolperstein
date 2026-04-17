"""FastMCP server for Stolperstein — experiential knowledge capture."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import Icon, ToolAnnotations

from stolperstein.auth import create_auth, create_bearer_only_auth
from stolperstein.config import settings


def _build_auth():
    """Build auth provider for HTTP transport.

    Two modes:

    - **Behind CF MCP Portal (default)**: bearer-token-only. No OIDC config
      needed — the Portal handles upstream identity; we just validate the
      static bearer token that Claude Code / hooks present in the header.
    - **Standalone with OIDC**: set `CF_ACCESS_CLIENT_ID` +
      `CF_ACCESS_CLIENT_SECRET` to enable Cloudflare Access for SaaS OIDC
      flow alongside bearer auth (for browser OAuth clients).

    Stdio transport has no auth layer.
    """
    if settings.transport != "http":
        return None
    api_key = settings.ensure_api_key()

    # Bearer-only mode (the current CDiT fleet pattern — MCP Portal in front).
    if not settings.cf_access_client_secret:
        logger = logging.getLogger(__name__)
        logger.info("CF Access OIDC disabled; bearer-token auth only")
        return create_bearer_only_auth(api_key=api_key, base_url=settings.base_url)

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


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    """Unauthenticated liveness + schema_version probe.

    Returns 200 with a small JSON payload when the server can read its own
    store and report a schema version. Used by the Docker HEALTHCHECK and
    by any upstream (Komodo / Cloudflare / Tailscale) that wants a
    no-auth GET endpoint to verify the container is serving.

    Intentionally does NOT reveal `proposer_did` or KU content — just
    shape health (can we reach SQLite + run migrations).
    """
    from starlette.responses import JSONResponse
    try:
        from stolperstein import migrations as m
        from stolperstein.store import store
        db = store._get_db()
        version = m.current_version(db)
        return JSONResponse({
            "status": "ok",
            "schema_version": version,
            "transport": settings.transport,
        })
    except Exception as e:
        return JSONResponse(
            {"status": "degraded", "error": type(e).__name__},
            status_code=503,
        )


@mcp.custom_route("/hook/query", methods=["POST"])
async def hook_query(request):
    """Stdlib-friendly REST endpoint for Claude Code hook handlers.

    Hook handlers are plain Python scripts run by Claude Code; they shouldn't
    need to speak full MCP over streamable-HTTP. This endpoint is a thin
    JSON-in / JSON-out wrapper around `query()` with bearer-token auth.

    Request: `POST /hook/query`
    Headers: `Authorization: Bearer <MCP_STOLPERSTEIN_API_KEY>`
    Body: `{"text": "...", "limit": 1, "confidence_min": 0.5}`
    Response: `{"results": [...], "count": N}` (same as MCP tool)
    """
    import hmac

    from starlette.responses import JSONResponse

    if settings.transport != "http":
        return JSONResponse({"error": "http transport required"}, status_code=503)

    api_key = settings.mcp_stolperstein_api_key
    if not api_key:
        return JSONResponse({"error": "server has no API key configured"}, status_code=503)

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse({"error": "bearer token required"}, status_code=401)
    provided = auth[len("Bearer "):].strip()
    if not hmac.compare_digest(provided, api_key):
        return JSONResponse({"error": "invalid bearer token"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    text = payload.get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    limit = int(payload.get("limit", 1))
    confidence_min = float(payload.get("confidence_min", 0.5))
    domain = payload.get("domain")

    from stolperstein.store import store
    result = await store.query(
        text=text, domain=domain, confidence_min=confidence_min, limit=limit
    )
    return JSONResponse(result)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def query(
    text: str,
    domain: list[str] | None = None,
    confidence_min: float = 0.3,
    limit: int = 10,
) -> dict:
    """Search knowledge units by natural language, error signatures, or technology tags.

    Uses hybrid search combining FTS5 keyword relevance and vector cosine similarity.
    Severity acts as a tiebreaker at equal rank (critical > high > medium > low).

    Args:
        text: Natural-language query. Error messages, symptoms, tech stacks — all fine.
        domain: Optional tag list to filter by, e.g. ["swift", "xcode"]. Intersection
            with KU's domains[] field. Default None = no filter.
        confidence_min: Exclude KUs below this confidence score. Default 0.3. Raise
            to 0.5+ when you want only well-confirmed advice.
        limit: Max results (default 10).

    Returns:
        {"results": [KU dicts...], "count": N}. Each KU carries full v1 shape
        including context, evidence.severity, provenance, and owner_org.
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
    domains: list[str],
    kind: str,
    context_languages: list[str] | None = None,
    context_frameworks: list[str] | None = None,
    context_environment: str | None = None,
    context_pattern: str | None = None,
    severity: str = "medium",
) -> dict:
    """Propose a new Knowledge Unit from a discovered insight.

    Args:
        summary: One-line description, max 280 chars. ("What happened.")
        detail: Why it matters, full context. Markdown allowed.
        action: Imperative — what to do when encountering this. Plain text; angle
            brackets are stripped from KU actions before they're injected into
            agent context, so inline HTML examples belong in `detail`, not here.
        domains: REQUIRED, non-empty. Technology tags, e.g. ["swift", "xcode"].
            Called `domains` on the wire (upstream CQ name).
        kind: One of `pitfall`, `workaround`, `tool-recommendation`.
            `gap-signal` is deprecated — tool gaps are detected automatically
            from query-miss patterns.
        context_languages: Optional, e.g. ["swift"]. Language tags.
        context_frameworks: Optional, e.g. ["swiftui", "combine"].
        context_environment: Optional, e.g. "xcode-16" — version scope
            (Stolperstein extension; proposed upstream).
        context_pattern: Optional, e.g. "concurrency" — pattern tag.
        severity: Optional `low | medium | high | critical`, default `medium`.
            Default escalates decay floor to 0.2 for `critical` so critical
            KUs never fully decay (Stolperstein extension; proposed upstream).

    Example:
        propose(
          summary="Xcode 16 requires explicit Swift 6 concurrency opt-in",
          detail="When targeting Swift 6 language mode, all sendable violations...",
          action="Add -strict-concurrency=complete to build settings.",
          domains=["swift", "xcode"],
          kind="pitfall",
          context_languages=["swift"],
          context_environment="xcode-16",
          context_pattern="concurrency",
          severity="high",
        )
    """
    from stolperstein.store import store
    return await store.propose(
        summary=summary,
        detail=detail,
        action=action,
        domains=domains,
        kind=kind,
        context_languages=context_languages,
        context_frameworks=context_frameworks,
        context_environment=context_environment,
        context_pattern=context_pattern,
        severity=severity,
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
async def confirm(ku_id: str) -> dict:
    """Confirm an existing Knowledge Unit — increments confirmations and confidence.

    NOT idempotent: calling twice increments confirmations twice and changes the
    confidence score. Diversity-weighted: a confirmation from a new owner_org boosts
    more than one from an already-contributing org.

    Args:
        ku_id: The KU's id (format `ku_[0-9a-f]{32}`). If not found, raises an
            InvalidParams error with guidance to call query() first.
    """
    from stolperstein.store import store
    return await store.confirm(ku_id=ku_id)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False))
async def flag(
    ku_id: str,
    reason: str,
    detail: str = "",
    superseded_by: str | None = None,
) -> dict:
    """Flag a Knowledge Unit as stale, incorrect, superseded, dangerous, or duplicate.

    NOT idempotent: transitions state and updates the KU's flags/superseded_by.

    Args:
        ku_id: The KU's id.
        reason: One of `stale | incorrect | superseded | dangerous | duplicate`.
            `superseded` and `duplicate` require `superseded_by`.
            `dangerous` is a Stolperstein extension (maps to `incorrect` on the wire).
        detail: Optional explanation — server-side only, never shown to querying agents.
        superseded_by: KU id of the replacing KU. Required when reason is `superseded`
            or `duplicate`.
    """
    from stolperstein.store import store
    return await store.flag(
        ku_id=ku_id, reason=reason, detail=detail, superseded_by=superseded_by
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def reflect(session_summary: str) -> dict:
    """Extract generalizable learnings from a session summary.

    Returns ranked candidate KUs scored by generalizability, each pre-filled
    with context_* and severity so you can pass them straight to propose()
    without re-reading docs.

    Hook channel vs tool channel: auto-injected hook hints (from PostToolUse,
    UserPromptSubmit) are rate-limited, sanitized nudges — they carry summary
    and action only. For the full KU (evidence, provenance, context,
    related, owner_org), call query() directly.
    """
    from stolperstein.reflect import reflect_with_dedup
    from stolperstein.store import store
    return await reflect_with_dedup(session_summary, store=store)


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def status(debug: bool = False) -> dict:
    """Report store health.

    Default (token-frugal): total, by_status, confidence_distribution, staleness,
    tool_gap_signals (grandfathered vs emergent counts).

    With debug=True: also includes schema_version, proposer_did, applied
    migrations, by_owner_org breakdown, recent_emergent KU ids, query_misses
    window size. Use for operator troubleshooting, not routine agent calls.
    """
    from stolperstein.store import store
    return await store.status(debug=debug)


# --- CLI subcommands ---

def _cmd_migrate(args: argparse.Namespace) -> int:
    """Apply pending migrations to `CQ_LOCAL_DB_PATH` without starting the server."""
    import sqlite3
    import sqlite_vec
    from stolperstein import migrations

    db_path = args.db_path or settings.cq_local_db_path

    # Scope check: refuse arbitrary paths outside configured DB parent dir.
    configured_parent = Path(settings.cq_local_db_path).resolve().parent
    if args.db_path:
        requested = Path(args.db_path).resolve()
        if configured_parent not in requested.parents and requested.parent != configured_parent:
            print(
                f"error: --db-path must be within {configured_parent}; got {requested.parent}",
                file=sys.stderr,
            )
            return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    except Exception:
        # vec0 not required for migrations themselves, but the baseline schema
        # would fail without it. Try to proceed; bubble up if it matters.
        pass
    conn.enable_load_extension(False)

    from_version = migrations.current_version(conn)
    try:
        result = migrations.run(conn, db_path=db_path)
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        return 1
    if not result.applied:
        print(f"already at version {result.to_version}")
        return 0
    print(f"Applied {len(result.applied)} migrations ({from_version} → {result.to_version}):")
    for m in result.applied:
        print(f"  - {m}")
    if result.snapshots:
        print(f"Pre-migration snapshots: {result.snapshots}")
    return 0


def _cmd_prune_backups(args: argparse.Namespace) -> int:
    """List or delete .bak-pre-v* files in the DB directory."""
    db_dir = Path(settings.cq_local_db_path).resolve().parent
    pattern = f"{Path(settings.cq_local_db_path).name}.bak-pre-v*"
    backups = sorted(db_dir.glob(pattern))
    if not backups:
        print("No pre-migration backup files found.")
        return 0

    if not args.confirm:
        print(f"Would delete {len(backups)} backup(s) (dry run — pass --confirm to delete):")
        for b in backups:
            size = b.stat().st_size
            print(f"  - {b} ({size:,} bytes)")
        return 0

    for b in backups:
        b.unlink()
        print(f"Deleted {b}")
    return 0


def _cmd_detect_emergent(args: argparse.Namespace) -> int:
    """Run emergent-signal detection manually."""
    if settings.stolperstein_emergent_disabled or settings.emergent_detect_every_n == 0:
        print("emergent detection is disabled; "
              "set STOLPERSTEIN_EMERGENT_DISABLED=false to run")
        return 0
    try:
        from stolperstein.emergent import detect_emergent
        from stolperstein.store import store
    except ImportError:
        print("emergent module not yet implemented", file=sys.stderr)
        return 2
    emitted = detect_emergent(store)
    print(f"Emitted {len(emitted)} emergent tool-gap-signal KU(s).")
    for ku_id in emitted:
        print(f"  - {ku_id}")
    return 0


def main() -> None:
    """Entry point for mcp-stolperstein."""
    parser = argparse.ArgumentParser(prog="mcp-stolperstein")
    sub = parser.add_subparsers(dest="cmd")

    p_migrate = sub.add_parser("migrate", help="Apply pending DB migrations and exit.")
    p_migrate.add_argument("--db-path", default=None,
                           help=f"Override DB path (default: {settings.cq_local_db_path})")
    p_migrate.set_defaults(func=_cmd_migrate)

    p_prune = sub.add_parser("prune-backups", help="List/delete pre-migration .bak files.")
    p_prune.add_argument("--confirm", action="store_true",
                         help="Actually delete (default is dry-run).")
    p_prune.set_defaults(func=_cmd_prune_backups)

    p_detect = sub.add_parser("detect-emergent",
                              help="Run emergent-signal aggregation manually.")
    p_detect.set_defaults(func=_cmd_detect_emergent)

    args = parser.parse_args()

    if getattr(args, "func", None):
        sys.exit(args.func(args))

    # Default: start the MCP server.
    # Pre-warm the store so migrations run before the first tool call.
    from stolperstein.store import store
    store._get_db()

    if settings.transport == "http":
        mcp.run(transport="http", host=settings.host, port=settings.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
