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

Stop the container, copy `stolperstein.db.bak-pre-v<N>` over `stolperstein.db`, redeploy the previous image tag. If `/data/stolperstein.key` was lost, the install will generate a new keypair on next boot (KUs remain intact but subsequent proposals get a new DID — the audit chain breaks at the rollback point, which is recoverable but visible).

## Private signing key (`/data/stolperstein.key`)

The install's Ed25519 private key is stored **outside** the SQLite DB for good reason — a DB leak does not compromise signing capability. Treat `/data/stolperstein.key` as sensitive:

- Exclude it from volume backups (`stolperstein-data-pre-v*` snapshots are the DB only; don't bundle the key file in).
- Don't include it in `docker cp` / dump operations.
- To inject the key via env (for CI or ephemeral deployments), set `MCP_STOLPERSTEIN_SIGNING_KEY` to the base64-encoded 32-byte key. The env var takes priority over the file.

## Claude Code plugin

`plugin/stolperstein/` ships a real hook manifest (`hooks.json`) with three hooks: `UserPromptSubmit`, `PostToolUse(Bash)`, `Stop`. They fire on **structured** error signals only (exception class names, tracebacks, non-zero exit codes, HTTP status strings, explicit `fatal:`/`panic:`/`Error:` prefixes) — not bare conversational English. 30s cooldown + 5min per-KU dedupe via `fcntl.flock`-guarded state file at `$FASTMCP_HOME/hooks-state.json`. See `plugin/stolperstein/SKILL.md` for tool usage and the `STOLPERSTEIN_HOOKS_DISABLED` escape hatch.

Hooks require the MCP server reachable over HTTP; set `MCP_STOLPERSTEIN_PUBLIC_URL` + `MCP_STOLPERSTEIN_API_KEY`. Without those, hook handlers exit 0 silently (no-op).

## License

MIT.
