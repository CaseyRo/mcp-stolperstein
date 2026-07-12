## Why

"Stolperstein" names a specific, solemn thing: Gunter Demnig's brass memorial
plaques for victims of Nazi persecution, embedded in sidewalks across Germany.
Using it as a casual name for an error/pitfall knowledge-base tool risks
reading as trivializing that memorial — a real reputational risk for a
Berlin-based operator working with German clients. No published writing or
blog content references the current name yet, so the window to rename cheaply
(before external content accumulates) is now.

Rename to **Stolperfalle** — keeps the `stolpern` (to stumble) root and the
project's origin story, but is an ordinary German hazard-sign word (the term
on ✱Vorsicht, Stolperfalle!✱ trip-hazard warnings), not a memorial reference.
It also happens to be a near-literal German rendering of `kind: pitfall`,
already a first-class value in the KU schema.

## What Changes

- Rename every public/product-facing surface from `stolperstein` to
  `stolperfalle`: GitHub repo, Python package (`mcp_stolperstein` →
  `mcp_stolperfalle`), CLI command, Docker volume names, Komodo stack name,
  Cloudflare Access catalog entry + DNS subdomain
  (`mcp-stolperstein.cdit-dev.de` → `mcp-stolperfalle.cdit-dev.de`), the
  Claude Code plugin directory/marketplace entry (`plugin/stolperstein/` →
  `plugin/stolperfalle/`), and the MCP tool name prefix surfaced to agents
  (`stolperstein_query` etc. → `stolperfalle_query` etc.).
- **BREAKING**: env var prefixes change (`STOLPERSTEIN_*` /
  `MCP_STOLPERSTEIN_*` → `STOLPERFALLE_*` / `MCP_STOLPERFALLE_*`). Every
  deployed config value (Komodo stack env, escrowed 1Password items like the
  base64 signing key, any `.env` files) must move in lockstep with the
  deploy, or the server silently falls back to defaults / fails auth.
- **BREAKING**: MCP tool names change. Every consumer referencing
  `stolperstein_*` tools — the Claude Code plugin's hook handlers, the
  Cloudflare MCP Portal catalog entry, this very `CLAUDE.md`/wiki fleet
  roster in the parent `CDiT-infrastructure` repo — needs updating.
- **Deliberately NOT changed**: the wire-protocol extension namespace
  `stolperstein:*` stays exactly as-is. It's baked into a merged upstream
  Mozilla AI PR ([mozilla-ai/cq#453](https://github.com/mozilla-ai/cq/pull/453))
  and referenced in an open discussion
  ([#286](https://github.com/mozilla-ai/cq/discussions/286)). It becomes a
  permanent internal/legacy protocol namespace, decoupled from the product's
  public name — same pattern as any product carrying an old internal
  codename nobody outside ever sees.
- This proposal scopes and sequences the rename; it does not pick
  implementation details or execute anything. Design and task breakdown are a
  follow-on pass once this is agreed.

## Capabilities

### New Capabilities
(none — this is a rename/rebrand, not new product behavior)

### Modified Capabilities
(none — no spec-level requirement changes; the wire protocol, KU schema, and
all six MCP tools' *behavior* are unaffected. Only names change.)

## Impact

- **Code**: package rename, CLI entry point, `server.py` tool registrations,
  every env var read in `config.py`/`auth.py`/hook handlers.
- **Data continuity risk**: the production `stolperstein-data` /
  `stolperstein-key` Docker volumes hold live KU data and the Ed25519 signing
  key. The new stack must mount the *existing* volumes (or an explicit
  migration step) — a naive rename-and-redeploy that creates fresh volumes
  would silently reset the knowledge base and rotate the install DID.
- **Infra**: GitHub repo rename (GitHub auto-redirects the old URL), PyPI (if
  published — needs checking), Cloudflare Access catalog + DNS record,
  Komodo stack rename.
- **Claude Code plugin**: directory rename, `marketplace.json`,
  `hooks.json`. Anyone with the plugin already installed needs to
  update/reinstall.
- **Fleet-wide**: the parent `CDiT-infrastructure` repo's wiki
  (`docs/wiki/topics/mcp-stolperstein.md`) and mcp-fleet roster reference the
  old name and need updating once this lands.
- **Not touched**: the `stolperstein:*` wire namespace, the upstream Mozilla
  discussion/PR (#286, #453) — those keep the old name permanently, by
  design.
