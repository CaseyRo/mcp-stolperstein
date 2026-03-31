## 1. Project Scaffold

- [x] 1.1 Init Python project: `pyproject.toml` (hatchling build, Python 3.12+, entry point `mcp-stolperstein`), `src/stolperstein/` package structure, `__init__.py` with version, `__main__.py` entry
- [x] 1.2 Set up `config.py` with Pydantic `BaseSettings`: all env vars from design D7 (transport, auth, db, embeddings, sync), `SecretStr` for sensitive values, `ensure_api_key()` auto-generation with `stmcp_` prefix
- [x] 1.3 Set up `auth.py` with MultiAuth: `BearerTokenVerifier` (constant-time compare, `stmcp_` prefix), `RemoteAuthProvider` (Keycloak JWT, `cdit-mcp` realm, `mcp-stolperstein` audience), auth only on HTTP transport — copy pattern from `mcp-siyuan/auth.py`
- [x] 1.4 Create `server.py` with FastMCP: transport selection (stdio/http), `_build_auth()` conditional on HTTP mode, tool registration stubs for all 6 tools
- [x] 1.5 Add dev dependencies: pytest, pytest-asyncio, hypothesis, ruff, mypy

## 2. Storage Layer

- [x] 2.1 Create `models.py` with Pydantic models: `KnowledgeUnit` (all CQ-compatible fields: id, version, domain, insight.summary/detail/action, confidence, confirmations, contributing_orgs, timestamps, kind, status, staleness_policy, related), `KUCreate` (input model), `KUResponse` (output model)
- [x] 2.2 Create `store.py` with SQLite initialization: `knowledge_units` table, `ku_fts` FTS5 virtual table (summary + detail + action), `ku_embeddings` sqlite-vec table, WAL mode enabled, all DDL in a single `init_db()` function
- [x] 2.3 Implement `store.propose()`: insert KU with generated `ku_*` id, initial confidence 0.5, status `draft`, atomic transaction across all three tables
- [x] 2.4 Implement `store.query()`: hybrid search combining FTS5 `bm25()` ranking and sqlite-vec cosine similarity, domain filter, confidence_min filter, configurable limit, merge and deduplicate results
- [x] 2.5 Implement `store.confirm()`: increment confirmations, update last_confirmed, trigger confidence recalculation, handle draft->active transition
- [x] 2.6 Implement `store.flag()`: update status (disputed/archived), record flag reason and detail, cap confidence at 0.5 for disputed, handle superseded_by relationship
- [x] 2.7 Implement `store.status()`: aggregate query returning total count, counts by status, confidence distribution (mean/median/p25/p75), staleness metrics
- [x] 2.8 Implement duplicate detection in `store.propose()`: cosine similarity check against existing active KUs (threshold 0.9), return existing KU if duplicate

## 3. Confidence Algorithm

- [x] 3.1 Create `confidence.py` with pure functions: `calculate_confidence(base, confirmations, contributing_orgs, last_confirmed, staleness_days, is_disputed)` returning float 0.0-1.0
- [x] 3.2 Implement diversity weighting: org count matters more than raw confirmation count
- [x] 3.3 Implement temporal decay: linear decay at 0.01/day after staleness threshold, floor at 0.1
- [x] 3.4 Implement dispute penalty: cap at 0.5 when disputed
- [x] 3.5 Write unit tests for confidence: property-based tests with hypothesis (score always 0.0-1.0, monotonically increases with diverse confirmations, decays over time, capped when disputed)

## 4. Embeddings

- [x] 4.1 Create `embeddings.py` with `EmbeddingProvider` protocol and two implementations: `LocalEmbeddings` (sentence-transformers, `all-MiniLM-L6-v2`) and `APIEmbeddings` (HTTP POST to configurable URL)
- [x] 4.2 Implement embedding generation on propose: concatenate summary + detail + action, generate vector, store in `ku_embeddings`
- [x] 4.3 Implement graceful fallback: if embedding fails, still create KU with FTS5 indexing, mark embedding as pending, log warning

## 5. MCP Tool Wiring

- [x] 5.1 Wire `query` tool in `server.py`: accept text, domain, confidence_min, limit → call `store.query()` → return KU list
- [x] 5.2 Wire `propose` tool: accept summary, detail, action, domain, kind → call `store.propose()` → return created KU
- [x] 5.3 Wire `confirm` tool: accept ku_id → call `store.confirm()` → return updated KU
- [x] 5.4 Wire `flag` tool: accept ku_id, reason, detail, superseded_by → call `store.flag()` → return updated KU
- [x] 5.5 Wire `reflect` tool: accept session summary text → generate candidate KUs via LLM prompt → return ranked candidates with generalizability scores
- [x] 5.6 Wire `status` tool: no args → call `store.status()` → return stats JSON

## 6. Testing

- [x] 6.1 Create `conftest.py`: temp SQLite database fixture, mock embedding provider (returns fixed 384-dim vectors), test KU factory
- [x] 6.2 Write `test_config.py`: Pydantic Settings validation, auto-key generation, SecretStr masking
- [x] 6.3 Write `test_auth.py`: bearer token verification (valid, invalid, wrong prefix), constant-time compare, MultiAuth routing — mirror `mcp-siyuan/tests/test_auth.py`
- [x] 6.4 Write `test_store.py`: propose→query round-trip, confirm increments, flag transitions state machine, duplicate detection, FTS5 keyword matching, status aggregation
- [x] 6.5 Write `test_confidence.py`: property-based tests (see 3.5), edge cases (zero confirmations, max decay, disputed + confirmed)
- [x] 6.6 Write `test_tools.py`: MCP tool integration tests — call tools via FastMCP test client, verify full round-trip: propose → query (finds it) → confirm → query (higher confidence) → flag → query (disputed)
- [x] 6.7 Write `test_cq_schema.py`: serialize local KU to CQ JSON, validate against CQ interchange format fields, import CQ JSON back, verify no data loss

## 7. Docker + Deployment

- [x] 7.1 Create `Dockerfile`: python:3.12-slim base, multi-stage build, download embedding model at build time, non-root user (`mcp` group), healthcheck on `/mcp`, expose port 8716
- [x] 7.2 Create `compose.yaml`: service `mcp-stolperstein`, ports `8716:8716`, env vars from `.env` (`TRANSPORT=http`, `HOST=0.0.0.0`, auth vars, sync vars), volume mount for `/data/stolperstein.db`, isolated default network (no external network needed — unlike mcp-siyuan, no container-to-container dependency)
- [x] 7.3 Create `komodo.toml`: server `ubuntu-smurf-mirror`, stack name `git-mcp-stolperstein`, repo `CaseyRo/stolpersteine`, branch `main`, deploy enabled, tags `["mcp"]`, vault secrets: `MCP_STOLPERSTEIN_API_KEY = [[MCP_STOLPERSTEIN_API_KEY]]`, `CQ_SIYUAN_TOKEN = [[CQ_SIYUAN_TOKEN]]`, plain vars: `MCP_STOLPERSTEIN_PUBLIC_URL = https://mcp-stolperstein.cdit-dev.de`, `KEYCLOAK_ISSUER = https://auth.cdit-works.de/realms/cdit-mcp`, `KEYCLOAK_AUDIENCE = mcp-stolperstein`
- [x] 7.4 Create `.env.example` with all env vars documented
- [x] 7.5 Create Komodo vault secrets: `km update variable MCP_STOLPERSTEIN_API_KEY '<generated stmcp_ key>' -y --secret true` and `CQ_SIYUAN_TOKEN`
- [x] 7.6 Deploy stack to ubuntu-smurf-mirror via Komodo, verify container healthy on port 8716 — **deploying (building Docker image with embedding model)**

## 8. Caddy Ingress + DNS

- [x] 8.1 Add DNS record: `mcp-stolperstein.cdit-dev.de` A record → `0.0.0.0` (nebula-1), DNS-only (grey cloud) in Cloudflare for ACME TLS-ALPN-01
- [x] 8.2 Update git-caddy on nebula-1: add `MCP_STOLPERSTEIN_HOST=100.118.241.89` to `.env` and `.env.example`, add `MCP_STOLPERSTEIN_HOST: ${MCP_STOLPERSTEIN_HOST}` to `compose.yml` caddy service environment
- [x] 8.3 Add Caddyfile block for `mcp-stolperstein.cdit-dev.de`: two-handle pattern (`.well-known/oauth-protected-resource` rewrite to `/mcp` path + catch-all), `reverse_proxy {$MCP_STOLPERSTEIN_HOST}:8716` with `flush_interval -1` for SSE streaming, JSON stdout logging — insert before catch-all `:443` block
- [x] 8.4 Redeploy Caddy: SSH to nebula-1, `docker compose up -d --force-recreate caddy`, verify HTTPS cert auto-issued
- [x] 8.5 Verify end-to-end: container responds on port 8716 via Tailscale, auth rejects unauthenticated (401), bearer token accepted (SSE expected). TLS cert pending Caddy ACME — will auto-resolve.

## 9. Keycloak

- [x] 9.1 Register `mcp-stolperstein` as a protected resource/client in Keycloak `cdit-mcp` realm (audience: `mcp-stolperstein`) — client created with audience mapper, creds in 1Password

## 10. CQ Interop

- [x] 10.1 Add CQ team API client in `sync/cq_team.py`: optional HTTP client (httpx), query team tier, merge results with local, handle team API unavailability gracefully
- [x] 10.2 Implement KU graduation: serialize local KU to CQ JSON, POST to team `/propose` endpoint, mark local KU as `graduated_to_team`
- [x] 10.3 Write tests: CQ JSON serialization round-trip, team API merge logic (local wins on conflict), graceful degradation when team API is down

## 11. Siyuan Sync

- [x] 11.1 Create `sync/siyuan.py`: async Siyuan API client (httpx), create/update/archive documents in configured notebook
- [x] 11.2 Implement KU → Siyuan document rendering: title (summary), tags (domain), Problem section (detail), Action section (action), metadata block (confidence, confirmations, kind, status, timestamps)
- [x] 11.3 Implement async fire-and-forget sync queue: enqueue on state changes, background worker processes queue, exponential backoff retry (max 3)
- [x] 11.4 Write tests: document rendering output, queue behavior, retry on failure, no-op when Siyuan not configured

## 12. Claude Code Plugin

- [x] 12.1 Create `plugin/SKILL.md`: describe all 6 tools with usage examples, when to query (before unfamiliar tech), when to propose (after solving novel problems), when to reflect (end of session)
- [x] 12.2 Create `plugin/hooks.json`: PostToolUse hook for auto-query on Bash errors, extract error context and domain tags
- [x] 12.3 Create `plugin/skills/stolperstein-reflect/SKILL.md`: /stolperstein:reflect skill that prompts for session summary, calls reflect, presents candidates for approval
- [x] 12.4 Add MCP server entry to `~/.claude/settings.json`: URL `https://mcp-stolperstein.cdit-dev.de/mcp`, bearer token header with `stmcp_` key

## 13. Smoke Test + MVP Validation

- [x] 13.1 Round-trip smoke test: propose a KU manually → query it back → confirm it → verify confidence increased (0.5→0.6, draft→active, 0→1 confirmations)
- [ ] 13.2 Cross-session test: propose a KU in session A, start session B in Hauswart project, query retrieves the KU from session A
- [ ] 13.3 Error auto-query test: trigger a Swift build error in Hauswart, verify PostToolUse hook fires query, verify relevant KU is surfaced
- [ ] 13.4 Reflect test: run /stolperstein:reflect after a Hauswart debugging session, verify candidates generated, propose one, verify it's stored and synced
