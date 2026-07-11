# mcp-stolperstein

Experiential knowledge capture and recall MCP server for AI coding agents. A conforming-plus-extending implementation of Mozilla AI's [cq](https://github.com/mozilla-ai/cq) — Phase 1 of the machine-readable org layer we're building at [CDiT](https://cdit-works.de).

## Quick start

```bash
uv sync
uv run mcp-stolperstein                   # stdio mode (for direct MCP clients)
uv run mcp-stolperstein migrate           # apply DB migrations + exit
uv run pytest                             # full test suite
docker compose up --build                 # HTTP mode on :8716, persistent volume
```

## What this is

Stolperstein is the local node — one per install — where Knowledge Units (KUs) live: problem→action pairs, with confidence, severity, provenance, and org ownership. Agents `query()`, `propose()`, `confirm()`, `flag()`, and `reflect()` against it.

On the wire, it conforms to the upstream cq schema strictly. Locally it carries a richer superset (severity, status state machine, kind enum, rich provenance, multi-tenant `owner_org`). See [`docs/cq-extensions.md`](docs/cq-extensions.md) for the extension registry. Upstream discussion of proposed additions: [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286).

## Relationship with upstream (mozilla-ai/cq)

Stolperstein is not a fork — it's an independent, cq-compatible local node that stays strictly valid on the wire and proposes anything it needs beyond that back upstream rather than diverging quietly.

**History so far:** filed [discussion #286](https://github.com/mozilla-ai/cq/discussions/286) proposing a set of local extensions (severity, kind, status, org ownership, etc.) → scoped as [issue #406](https://github.com/mozilla-ai/cq/issues/406), proposing a generic `extensions` slot instead of relaxing `additionalProperties` → **merged upstream as [PR #453](https://github.com/mozilla-ai/cq/pull/453) on 2026-06-23**. That slot is now how Stolperstein carries its own fields (`stolperstein:*` namespaced keys — see [`docs/cq-extensions.md`](docs/cq-extensions.md)) without ever breaking strict conformance.

**Current standing on individual fields:** `severity`, `contributing_orgs`, and `kind` were declined for core promotion (upstream's call: importance should emerge from usage, not self-declaration) — they stay local-only, riding the slot. `context.environment` and `proposer_did` attribution are deferred, open threads. `status`, `staleness_policy`, `related[]`, `owner_org`, and `emergent` were never proposed for core — they're Stolperstein-specific by design.

**Open loop:** an adopter comment for #286, announcing production slot emission, is drafted (`openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/upstream-comment-draft.md`) but not yet posted — held for review.

## Migration workflow

The server runs pending migrations automatically on boot. For operators:

```bash
uv run mcp-stolperstein migrate           # apply pending migrations + exit
uv run mcp-stolperstein prune-backups     # list pre-migration .bak files (dry run)
uv run mcp-stolperstein prune-backups --confirm
uv run mcp-stolperstein detect-emergent   # run emergent-signal aggregation manually
```

### Deploying a breaking schema change

1. **Pre-deploy**: tag the current prod commit. Snapshot the `stolperstein-data` Docker volume to `stolperstein-data-pre-vN`.
2. **Deploy**: Komodo redeploys the container. On first boot, the migration runner copies `stolperstein.db` to `stolperstein.db.bak-pre-v<N>` before each breaking migration, applies the chain inside per-migration transactions, and stamps `schema_version`.
3. **Verify**: `mcp-stolperstein status --debug` must show the expected `schema_version`, no `proposer_did IS NULL`, no `owner_org IS NULL`, and KU totals matching pre-migration.
4. **48h later**: run `mcp-stolperstein prune-backups --confirm` to remove the `.bak-pre-v*` files once you're confident no rollback is needed.

### Rollback

There are no image tags — the stack builds from source on `nebula-1` (`build: .`, no registry), so rollback is git- and volume-based:

- **Code rollback**: `git revert <bad-sha>` and open a PR (`main` is branch-protected; CI must pass), or pin the Komodo stack to the last-good commit SHA for an immediate targeted redeploy. Budget ~5 min for the rebuild (it re-installs the CPU torch wheel and re-downloads the embedding model).
- **DB rollback** (a breaking migration went wrong): stop the container, copy `stolperstein.db.bak-pre-v<N>` over `stolperstein.db`, then deploy the code SHA that matches that schema. Migrations run on boot, so *old code on a newer-migrated DB* is exactly what the `.bak` guards against — and `.bak-pre-v<N>` only exists for breaking migrations.
- If `/data/stolperstein.key` was lost, the install generates a new keypair on next boot (KUs remain intact, but subsequent proposals get a new DID — the provenance chain breaks at the rollback point, recoverable but visible). Escrow the key (see below) to avoid this.

## Private signing key (`/data/stolperstein.key`)

The install's Ed25519 private key is stored **outside** the SQLite DB for good reason — a DB leak does not compromise signing capability. Treat `/data/stolperstein.key` as sensitive:

- **A whole-volume snapshot of `stolperstein-data` includes the key** — you can't exclude one file from a block/volume snapshot, so snapshot access = signing access; scope who can read those snapshots accordingly. For DB-only backups, copy `stolperstein.db` + `*.bak-pre-v*` at the file level instead.
- **Escrow it.** There is otherwise exactly one copy — a volume loss permanently rotates the install DID. Base64 the key into a 1Password item so it's recoverable: `docker exec <container> base64 -w0 /data/stolperstein.key` → store as a 1Password field, then recover by setting `MCP_STOLPERSTEIN_SIGNING_KEY` in Komodo env.
- Don't include it in `docker cp` / dump operations.
- To inject the key via env (recovery, CI, or ephemeral deployments), set `MCP_STOLPERSTEIN_SIGNING_KEY` to the base64-encoded 32-byte key. The env var takes priority over the file.

## Claude Code plugin

`plugin/stolperstein/` ships a real hook manifest (`hooks.json`) with three hooks: `UserPromptSubmit`, `PostToolUse(Bash)`, `Stop`. They fire on **structured** error signals only (exception class names, tracebacks, non-zero exit codes, HTTP status strings, explicit `fatal:`/`panic:`/`Error:` prefixes) — not bare conversational English. 30s cooldown + 5min per-KU dedupe via `fcntl.flock`-guarded state file at `$FASTMCP_HOME/hooks-state.json`. See `plugin/stolperstein/SKILL.md` for tool usage and the `STOLPERSTEIN_HOOKS_DISABLED` escape hatch.

Hooks require the MCP server reachable over HTTP; set `MCP_STOLPERSTEIN_PUBLIC_URL` + `MCP_STOLPERSTEIN_API_KEY`. Without those, hook handlers exit 0 silently (no-op).

## License

MIT.
