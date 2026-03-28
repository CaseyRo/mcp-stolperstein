## Context

This is a greenfield Python MCP server (`mcp-stolperstein`) that captures and retrieves experiential knowledge for AI coding agents. It runs as a Docker container on Zentralwerk (Komodo-managed, Tailscale-accessible) and integrates with Claude Code via MCP protocol and with Siyuan Note via its HTTP API.

The project aligns with Mozilla AI's CQ standard (March 2026) — same KU interchange format, same confidence model — but adds local UX (Siyuan sync, Claude Code hooks) that CQ doesn't provide. We build a CQ-compatible local node, not a fork.

## Goals / Non-Goals

**Goals:**
- Working MCP server with all 6 tools passing round-trip smoke tests
- Solid architecture: clean module boundaries, async I/O, typed models
- Decent testing: unit tests for confidence algorithm, integration tests for MCP tool round-trips, schema validation tests for CQ compat
- Reliable MCP connection: stdio for local dev, HTTP/SSE for remote via Tailscale
- MVP validated against real Hauswart development sessions

**Non-Goals:**
- Web UI or dashboard (Siyuan is the human interface)
- Multi-user / multi-tenant (single-operator system)
- CQ global commons contribution (team tier sync is MVP, global is future)
- Custom embedding model training (use off-the-shelf sentence-transformers or API)
- Real-time sync (Siyuan sync is async, best-effort)

## Decisions

### D1: Python + FastMCP over TypeScript

**Choice:** Python 3.13 with FastMCP

**Why:** FastMCP is the most mature MCP server framework, CQ itself is Python, sqlite-vec and sentence-transformers have first-class Python support. TypeScript MCP SDK exists but would mean fighting the embedding ecosystem.

**Alternatives considered:**
- TypeScript + `@modelcontextprotocol/sdk` — better for Vercel/Node ecosystem but worse for ML/embedding tooling
- Rust — overkill for a solo-operator tool, slower iteration

### D2: SQLite + sqlite-vec over Postgres + pgvector

**Choice:** Single SQLite file with FTS5 and sqlite-vec extensions

**Why:** Zero operational overhead — no separate database service, single file backup, trivial Docker volume mount. sqlite-vec provides cosine similarity search at the scale we need (thousands of KUs, not millions). WAL mode handles concurrent reads during writes.

**Alternatives considered:**
- Postgres + pgvector — more powerful but adds a service dependency, overkill for single-operator scale
- ChromaDB / Qdrant — adds another container, another API, another failure mode
- JSON files — no search capability

### D3: Embedding strategy — local sentence-transformers with API fallback

**Choice:** `all-MiniLM-L6-v2` via sentence-transformers in-process, with optional API fallback via `CQ_EMBEDDING_API_URL`

**Why:** ~80MB model, fast inference on CPU, no API costs, works offline. The model runs in the same Python process — no sidecar needed. For teams that prefer API-based embeddings (OpenAI, Voyage), the `CQ_EMBEDDING_API_URL` env var switches to HTTP-based embedding generation.

**Alternatives considered:**
- API-only (OpenAI embeddings) — adds latency, cost, and external dependency for every propose
- Larger models (e5-large) — better quality but 1.3GB, slow on CPU
- No embeddings (FTS5 only) — misses semantic matches, defeats the purpose

### D4: Project structure — single package, layered modules

**Choice:**
```
mcp-stolperstein/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── src/stolperstein/
│   ├── __init__.py
│   ├── server.py          # FastMCP server, tool definitions
│   ├── auth.py             # MultiAuth (Keycloak JWT + Bearer stmcp_)
│   ├── models.py           # Pydantic models (KU, CQ schema)
│   ├── store.py            # SQLite operations (CRUD, FTS, vec)
│   ├── confidence.py       # Scoring algorithm
│   ├── embeddings.py       # Embedding generation (local + API)
│   ├── sync/
│   │   ├── siyuan.py       # Siyuan API sync
│   │   └── cq_team.py      # CQ team API sync
│   └── config.py           # Pydantic Settings (env vars, SecretStr)
├── tests/
│   ├── test_auth.py        # MultiAuth, bearer token, JWT validation
│   ├── test_config.py      # Pydantic Settings validation
│   ├── test_store.py       # SQLite operations
│   ├── test_confidence.py  # Scoring algorithm
│   ├── test_tools.py       # MCP tool integration tests
│   ├── test_cq_schema.py   # CQ JSON interchange validation
│   └── conftest.py         # Fixtures (temp db, mock embeddings)
└── plugin/                  # Claude Code plugin files
    ├── SKILL.md
    ├── hooks.json
    └── skills/
        └── stolperstein-reflect/
            └── SKILL.md
```

**Why:** Flat enough to navigate, layered enough to test in isolation. `store.py` owns all SQLite access, `server.py` is thin (route to store, return results), `confidence.py` is pure functions (easy to unit test). Sync modules are optional — they import conditionally based on config.

### D5: MCP transport + auth — matching mcp-things/mcp-siyuan pattern

**Choice:** FastMCP serves both stdio (local, no auth) and HTTP (remote, MultiAuth). Follows the exact same pattern proven in `mcp-things` and `mcp-siyuan`:

- **Transport:** `TRANSPORT` env var — `stdio` (default for local dev) or `http` (Docker/remote)
- **Auth (HTTP only):** FastMCP `MultiAuth` combining:
  - **Keycloak JWT** — for Claude.ai connectors and OAuth clients. Realm `cdit-mcp`, audience `mcp-stolperstein`, JWKS from issuer URL
  - **Bearer token** — for Claude Code, n8n, direct clients. Prefix `stmcp_`, constant-time comparison (`hmac.compare_digest`)
- **Auto-key generation:** If `MCP_STOLPERSTEIN_API_KEY` not set, auto-generate `stmcp_*` key and warn
- **No auth on stdio** — local Claude Code sessions have zero overhead
- **Docker port:** 8716 (HTTP)
- **Claude Code config:** Bearer token in `~/.claude/settings.json` header, same as `tmcp_`/`smcp_` pattern

**Why:** This is the same auth stack running in production for mcp-things and mcp-siyuan. Proven reliable, supports both Claude.ai (OAuth/JWT) and Claude Code (static bearer token) simultaneously. No reason to innovate here.

**Reference implementations:**
- `mcp-siyuan/mcp_siyuan/auth.py` — MultiAuth, BearerTokenVerifier, RemoteAuthProvider
- `mcp-siyuan/mcp_siyuan/config.py` — Pydantic Settings with SecretStr
- `mcp-things` — same pattern, `tmcp_` prefix

### D6: Testing strategy — three layers

**Choice:**
1. **Unit tests** — confidence algorithm (pure functions, property-based with hypothesis), KU model validation, CQ schema serialization
2. **Integration tests** — MCP tool round-trips against a real temp SQLite database (propose -> query -> confirm -> query again, verify confidence changed)
3. **Schema tests** — serialize local KUs to CQ JSON, validate against CQ's published schema

**Why:** The confidence algorithm is the most complex pure logic — it deserves thorough unit tests. The MCP tools are thin wrappers around store operations — integration tests catch the real bugs (SQL typos, missing indexes, transaction boundaries). Schema tests guarantee CQ compatibility doesn't drift.

**Alternatives considered:**
- Mocking SQLite in tool tests — hides the real bugs (query construction, FTS5 syntax)
- E2E tests via Claude Code — too slow, too flaky for CI

### D7: Configuration — environment variables, no config file

**Choice:** All configuration via Pydantic `BaseSettings` with env vars (same pattern as mcp-siyuan):

**Core:**
- `CQ_LOCAL_DB_PATH` (default: `/data/stolperstein.db`)
- `CQ_LOG_LEVEL` (default: `INFO`)

**Transport + Auth (matching mcp-siyuan/mcp-things):**
- `TRANSPORT` (default: `stdio`, options: `stdio` | `http`)
- `HOST` (default: `127.0.0.1`)
- `PORT` (default: `8716`)
- `MCP_STOLPERSTEIN_API_KEY` (SecretStr, auto-generated if empty, prefix `stmcp_`)
- `MCP_STOLPERSTEIN_PUBLIC_URL` (optional, for OAuth discovery)
- `KEYCLOAK_ISSUER` (default: `https://auth.cdit-works.de/realms/cdit-mcp`)
- `KEYCLOAK_AUDIENCE` (default: `mcp-stolperstein`)

**Embeddings:**
- `CQ_EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)
- `CQ_EMBEDDING_API_URL` (optional, overrides local model)

**Sync (all optional):**
- `CQ_TEAM_ADDR` (enables team sync)
- `CQ_TEAM_API_KEY` (auth for team API)
- `CQ_SIYUAN_URL` (enables Siyuan sync)
- `CQ_SIYUAN_NOTEBOOK` (target notebook name)
- `CQ_SIYUAN_TOKEN` (Siyuan API auth)

**Why:** Docker-native, Komodo-compatible (env vars are the stack config interface, secrets via `[[VAR]]` vault injection), no file to mount or manage. Pydantic Settings with `SecretStr` for sensitive values matches the proven mcp-siyuan pattern.

### D8: Siyuan sync — async fire-and-forget with retry queue

**Choice:** After each state-changing MCP tool response, enqueue a sync task to an in-process asyncio queue. A background worker processes the queue, pushing to Siyuan API. Failed syncs retry with exponential backoff (max 3 retries).

**Why:** Sync must never block or fail an MCP tool response. An in-process queue is simpler than a separate job system for a single-operator tool. If Siyuan is down, KUs still work — sync catches up when it recovers.

**Alternatives considered:**
- Synchronous sync after tool response — blocks the agent, fragile
- Cron-based batch sync — stale data between syncs, more complex
- External queue (Redis, Vercel Queues) — overengineered for single-operator

## Risks / Trade-offs

**[sqlite-vec maturity]** sqlite-vec is relatively new. → Mitigation: FTS5 is the primary search path; vector search is additive. If sqlite-vec breaks, we degrade to keyword-only search with a logged warning.

**[Embedding model size in Docker image]** sentence-transformers + all-MiniLM-L6-v2 adds ~500MB to the image. → Mitigation: Use a multi-stage Docker build, download model at build time (not runtime). For lighter deploys, switch to API-based embeddings via `CQ_EMBEDDING_API_URL`.

**[CQ schema stability]** CQ is 3 weeks old — the interchange format may change. → Mitigation: Our `models.py` Pydantic models are the single source of truth. A schema version field lets us handle migrations. We pin to a known CQ schema version and update explicitly.

**[Single SQLite file = single point of failure]** → Mitigation: Docker volume mount + Komodo backup policy. SQLite is a file — rsync/rclone backup is trivial. For disaster recovery, re-seed from Siyuan (human-reviewed KUs are the source of truth).

**[Reflect tool quality depends on LLM]** The `reflect` tool asks an LLM to extract generalizable learnings — quality varies. → Mitigation: Reflect produces *candidates*, not committed KUs. An agent or human must explicitly `propose` each one. Bad candidates are discarded, not stored.

## Open Questions

- **Embedding dimension**: all-MiniLM-L6-v2 produces 384-dim vectors. Is that sufficient for KU-level semantic search, or should we go to 768-dim (e5-base)?
- **Hook granularity**: Should PostToolUse auto-query fire on ALL tool errors, or only specific tools (Bash, Read)? Firing on everything could be noisy.
- **CQ team API authentication**: CQ's team tier uses API keys — should we support OIDC as well for future-proofing?
- **KU deduplication threshold**: 0.9 cosine similarity is proposed — needs validation against real KU data to avoid false positives/negatives.
