# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`mcp-stolperfalle` — a FastMCP server that captures and recalls experiential knowledge ("Knowledge Units" / KUs) for AI coding agents. Internal model is a superset of Mozilla AI's upstream `cq` schema; strict-mode serializer (`to_cq_json_strict()`) emits upstream-valid payloads, `to_cq_json_rich()` emits the full internal shape with Stolperfalle extensions. Upstream discussion of the extensions we propose: [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286). Registry of extensions: `docs/cq-extensions.md`.

This project is Phase 1 of the **machine-readable org layer** we're building at [CDiT](https://cdit-works.de). Multi-tenant primitives (`owner_org`, `TRUSTED_ORGS` visibility) and emergent-signal detection are foundations, not the whole product.

## Commands

Dependency + env management is `uv`.

```bash
uv sync                              # install deps (incl. dev group)
uv run mcp-stolperfalle              # run the server (stdio or HTTP per TRANSPORT env)
uv run mcp-stolperfalle migrate      # apply pending DB migrations + exit
uv run mcp-stolperfalle prune-backups [--confirm]   # clean .bak-pre-v<N> files
uv run mcp-stolperfalle detect-emergent             # run emergent-signal aggregation
uv run pytest                        # full test suite
uv run pytest tests/test_store.py::test_name        # single test
uv run ruff check src tests plugin   # lint
uv run mypy src                      # type-check
docker compose up --build            # HTTP mode on :8716 with persistent volumes
```

Tests force `TRANSPORT=stdio`, inject a deterministic zero-signing-key via `MCP_STOLPERFALLE_SIGNING_KEY`, and use `NoOpEmbeddings`. Do not rely on sentence-transformers being loaded in unit tests.

## Architecture

Six MCP tools: `query`, `propose`, `confirm`, `flag`, `reflect`, `status` (see `server.py`). A thin tool layer over `KnowledgeStore` in `store.py`.

**Schema evolution goes through `migrations/`.** `store._init_baseline()` creates the v0-shape tables on a fresh install; then `migrations.run()` applies the ordered `mNNNN_*.py` modules to bring the DB to current (currently schema_version 6). Every migration declares `version: int`, `breaking: bool`, `slug: str`, and `up(conn)`. Before any `breaking=True` migration, the runner copies the DB to `<db>.bak-pre-v<N>` and refuses to overwrite an existing backup.

**KU model (`models.py`).** Nested Pydantic: `Context`, `Evidence`, `Provenance`. On the wire:
- `to_cq_json_strict()` — upstream-valid, extensions stripped, `created_by` from `proposer_did`, flag reasons mapped (`dangerous` → `incorrect` + local marker).
- `to_cq_json_rich()` — full internal superset.
- `to_cq_v0()` — legacy shape for the Siyuan sync transition (gated by `CQ_SIYUAN_SCHEMA_VERSION`).

Stolperfalle extensions (all local-only, all documented in `docs/cq-extensions.md`): `evidence.severity`, `evidence.contributing_orgs`, `context.environment`, top-level `kind`/`status`/`staleness_policy`/`related[]`/`owner_org`, `provenance.graduation_history`/`emergent`.

**Store layer (`store.py`).** `knowledge_units` carries flat columns (one per scalar, JSON for arrays). FTS5 (`ku_fts`) + vec0 (`ku_embeddings`) virtual tables for hybrid search. `query()` applies the `TRUSTED_ORGS` visibility filter BEFORE confidence/severity ranking; zero-result queries record a row in `query_misses` for emergent detection. Every Nth miss triggers `emergent.detect_emergent` as a fire-and-forget background task.

**Provenance (`provenance.py`).** One Ed25519 keypair per install, identifier is `did:key:z6Mk...`. The private key lives OUTSIDE the DB — either `/data/stolperstein.key` (mode 0o600, on-disk filename intentionally unchanged by the product rename — see `provenance.py`) or `MCP_STOLPERFALLE_SIGNING_KEY` env var (base64). DB stores only the public key and DID string. This is security-critical (see security-review H1) — a DB leak must not compromise signing capability.

**Emergent signals (`emergent.py`).** Simple clustering: cosine ≥0.8 on miss embeddings, ≥5 misses across ≥2 distinct hour-buckets → emits a new `tool-gap-signal` KU with `provenance.emergent=true`. 7-day dedupe against recent emergent KUs. Runtime-disableable via `STOLPERFALLE_EMERGENT_DISABLED` or `EMERGENT_DETECT_EVERY_N=0`.

**Reflect (`reflect.py`).** LLM-driven extraction (OpenAI-compatible endpoint) with a heuristic NLP fallback. Candidates return flat `context_*` + `severity` so callers pass straight to `propose()`.

**Auth (`auth.py`).** FastMCP's `MultiAuth`: Cloudflare Access OIDC for browser OAuth clients + static bearer tokens for Claude Code / n8n. Only engages when `TRANSPORT=http`. `hmac.compare_digest` for token comparison. `komodo.toml` still references the old `KEYCLOAK_*` vars — source of truth for new deployments is `compose.yaml` + `.env.example`.

**Sync (`sync/`).** `cq_team.py` emits strict-CQ on graduation and validates inbound payloads against the vendored schema before sanitizing + storing. `siyuan.py` honors `CQ_SIYUAN_SCHEMA_VERSION` (0 = legacy shape during transition). Both are gated behind env and fully optional.

**Hook handlers (`plugin/stolperfalle/hooks/handlers/`).** `on_prompt.py`, `on_bash.py`, `on_stop.py` + shared helpers (`_client.py`, `_rate_limit.py`, `_inject.py`, `_signals.py`, `_debug.py`). Require the server reachable over HTTP — hooks use `MCP_STOLPERFALLE_PUBLIC_URL` + `MCP_STOLPERFALLE_API_KEY`. Handlers are fully stdlib (no fastmcp import — Claude Code runs them with whatever `python3` is on $PATH); `_client.py` POSTs to the `/hook/*` REST endpoints (1.5s query budget, bearer-token sanitization in error surfaces). All decisions are traceable via `STOLPERFALLE_HOOKS_DEBUG=1` → `$TMPDIR/stolperfalle-hooks-debug.jsonl`; user-facing Stop-hook output must go through the JSON `systemMessage` field (stderr is invisible on exit 0). `on_bash.py` is registered for BOTH `PostToolUse` and `PostToolUseFailure` — PostToolUse never fires on nonzero exits (claude-code#6371), so without the failure registration the hook misses exactly the events it exists for. For a local-path marketplace install, hooks execute from THIS repo (`CLAUDE_PLUGIN_ROOT` = the repo's plugin dir), not the `~/.claude/plugins/cache` copy — handler edits are live for the next hook firing, but `hooks.json` registration changes need a Claude Code restart.

## Adding a new MCP tool

1. Add the method to `KnowledgeStore` (async, returns a dict via `.model_dump(mode="json")`).
2. Register in `server.py` with `@mcp.tool(annotations=ToolAnnotations(...))`. Be honest about `idempotentHint` — `confirm` and `flag` are explicitly `False` because they mutate counters / state.
3. Raise `fastmcp.exceptions.ToolError` with an actionable recovery hint on validation failure (never bare `ValueError` — LLM clients see it as an opaque internal error).
4. Add a test in `tests/` using the `store` fixture (temp DB + NoOp embeddings + zero-signing-key).

## Schema changes

Never edit existing columns in place. Add a new migration module:

```python
# src/stolperfalle/migrations/m000N_your_slug.py
version = N
breaking = True   # or False if purely additive
slug = "your_slug"

def up(conn: sqlite3.Connection) -> None:
    ...  # DDL + backfill
```

- Tag renames, drops, retypes as `breaking=True` so the runner takes a snapshot.
- Migrations run inside a single transaction each — raises roll back automatically.
- If you add a field that would ship on the wire, decide between strict upstream and Stolperfalle extension: extensions go in `models.py` AND get a row in `docs/cq-extensions.md`.

## Plugin

`plugin/stolperfalle/` is a Claude Code plugin (registered via `.claude-plugin/marketplace.json`) that wraps these tools with `SKILL.md` (usage guidance + what's strict-CQ vs extension) and a real `hooks.json` manifest firing the three Python handlers above. See `plugin/stolperfalle/SKILL.md` for the `STOLPERFALLE_HOOKS_DISABLED` escape hatch and per-project overrides.

## Deployment

Production runs via Komodo on server `nebula-1` (stack `git-mcp-stolperfalle-nebula`, auto-deploys from `main`), exposed at `https://mcp-stolperfalle.cdit-dev.de` through the co-located `git-cloudflared` tunnel on the same host. The container persists SQLite to the `stolperstein-data` volume (on-disk volume name intentionally unchanged by the product rename — see `openspec/changes/rename-product-name/design.md`) and FastMCP's OAuth client cache to `fastmcp-data` (`FASTMCP_HOME=/data/fastmcp`); both live on Hetzner volume `HC_Volume_105339184`. (Former host `ubuntu-smurf-mirror` is EOL and removed from Komodo.)

**The private signing key (`/data/stolperstein.key`) is sensitive.** Filename intentionally unchanged by the rename. Exclude from volume backups and `docker cp`. Deploy-time checklist + rollback procedure in `README.md`.

**Phase 1 vs Phase 2.** `owner_org` + `TRUSTED_ORGS` land as **foundation only** — read-filter visibility, default-trust-all. Enforceable write-side org permissions, per-org UI, selective graduation are Phase 2 scope in a follow-up change. Don't attempt them here.
