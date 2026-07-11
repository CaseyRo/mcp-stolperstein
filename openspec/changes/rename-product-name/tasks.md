## 1. Code changes (on a branch)

- [x] 1.1 Rename Python package `mcp_stolperstein` → `mcp_stolperfalle` (module dir, `pyproject.toml` name + entry point)
- [x] 1.2 Rename CLI command `mcp-stolperstein` → `mcp-stolperfalle` in `pyproject.toml` `[project.scripts]`
- [x] 1.3 Rename env var prefixes throughout `config.py`/`auth.py`/hook handlers: `STOLPERSTEIN_*` → `STOLPERFALLE_*`, `MCP_STOLPERSTEIN_*` → `MCP_STOLPERFALLE_*`
- [x] 1.4 Rename MCP tool registrations in `server.py` — discovered the six tools are just named `query`/`propose`/`confirm`/`flag`/`reflect`/`status` in Python; the `stolperstein_` prefix is applied downstream by the Cloudflare MCP Portal from the server's declared name. Satisfied by renaming `FastMCP("mcp-stolperstein", ...)` → `FastMCP("mcp-stolperfalle", ...)`.
- [x] 1.5 Rename the Claude Code plugin directory `plugin/stolperstein/` → `plugin/stolperfalle/`; update `marketplace.json` and `hooks.json` (including the top-level `.claude-plugin/marketplace.json`, which pointed at the old path)
- [x] 1.6 Update hook handler tool-name references (`on_prompt.py`/`on_bash.py`/`on_stop.py`) to the new tool names
- [x] 1.7 Update Dockerfile/compose service names and `.env.example` — kept the volume NAMES `stolperstein-data`/`stolperstein-key` unchanged, and discovered/fixed the same risk one level deeper: the on-disk filenames `stolperstein.db`/`stolperstein.key` (config.py's `cq_local_db_path` default, provenance.py's `DEFAULT_KEY_PATH`) also had to stay unchanged, not just the volume name — a blind rename of these would have made a redeploy silently create a fresh DB / rotate the signing key
- [x] 1.8 Update README.md, CLAUDE.md, USING.md prose to the new name — preserved the `stolperstein:*` wire-namespace references and the data-path filenames
- [x] 1.9 Update `docs/cq-extensions.md` framing text — also renamed the `stolperstein-specific` status label used in the extension registry table (a doc convention, not a wire value)

Also done, not originally itemized: updated `komodo.toml` (stack name, repo path, env var names — `CQ_SIYUAN_NOTEBOOK` deliberately left as `Stolpersteine`, an external SiYuan notebook name, same continuity risk as the DB/key files), `.wiki-compiler.json`'s `name` field, and this repo's own compiled wiki (`docs/wiki/`) — renamed product mentions throughout, preserved wire keys and the historical `stolperstein-mvp-scaffold` openspec directory citations (that directory is intentionally not renamed).

## 2. Local verification

- [x] 2.1 `uv sync` + full `pytest` suite green under the renamed package (200 passed)
- [x] 2.2 Build the Docker image locally, boot it, confirm the renamed CLI command and MCP tool names resolve (confirmed `mcp-stolperfalle` CLI, server banner, `/health` 200, and `/data/stolperstein.db`+`.key` correctly preserved inside the container)
- [x] 2.3 Confirm `stolperstein:*` wire-namespace keys are **unchanged** in `to_cq_json_strict()` output — covered by `tests/test_cq_schema.py`'s passing assertions
- [x] 2.4 `ruff check` + `mypy` clean

## 3. Repo + PR

**RESEQUENCED (2026-07-11):** the user chose the zero-downtime "prep new stack in parallel, then flip" cutover. That inverts the original order — merging to `main` FIRST would auto-trigger the old auto-deploying stack to redeploy the renamed code against its old `MCP_STOLPERSTEIN_*` env-var names, breaking prod auth. So the GitHub repo rename (3.1) and the merge (3.4) move to the END, after the Komodo cutover. The new stack builds directly from the `rename-to-stolperfalle` branch in the still-old-named repo until then.

- [ ] 3.1 Rename the GitHub repo `CaseyRo/mcp-stolperstein` → `CaseyRo/mcp-stolperfalle` — **MOVED to the end** (after cutover); blocked once by the auto-mode classifier as a production action pending explicit go-ahead
- [x] 3.2 Push the rename branch (`rename-to-stolperfalle`), open a PR — PR #35 opened against `CaseyRo/mcp-stolperstein` `main`, carries a "do not merge before the Komodo cutover" warning
- [x] 3.3 Confirm CI passes on the PR — `test` + `security` both green on PR #35
- [ ] 3.4 Merge — **MOVED to the final step**, after the Komodo cutover + repo rename (also: PR #34 touches README.md too and will conflict; whichever merges second rebases)

## 4. Deploy

- [ ] 4.1 Snapshot pre-rename state: record the current `proposer_did` and KU `total` via `status(debug=True)` against the live (old-named) server
- [ ] 4.2 Create the new Komodo stack config pointed at the renamed repo; mount the **existing** `stolperstein-data`/`stolperstein-key` volumes — do not let Komodo provision fresh ones
- [ ] 4.3 Copy (not regenerate) every env var **value** into the new `STOLPERFALLE_*`/`MCP_STOLPERFALLE_*` var names in the Komodo stack config
- [ ] 4.4 Deploy the new stack
- [ ] 4.5 Verify: `status(debug=True)` on the new deployment shows the **same** `proposer_did` and KU `total` as the 4.1 snapshot (data + DID continuity gate)
- [ ] 4.6 Verify container health and a live tool-call round-trip under the new tool names

## 5. Cloudflare / DNS cutover

- [ ] 5.1 Add a new Cloudflare Access catalog entry + DNS record for the new subdomain (e.g. `mcp-stolperfalle.cdit-dev.de`)
- [ ] 5.2 Leave the old `mcp-stolperstein.cdit-dev.de` entry resolving in parallel — no immediate teardown
- [ ] 5.3 Verify the new subdomain is reachable and healthy end-to-end through Cloudflare Access

## 6. Fleet + Portal update (do this last)

- [ ] 6.1 Update this fleet's Cloudflare MCP Portal catalog entry to the new tool names / new origin
- [ ] 6.2 Reconnect the Claude Code MCP connector so the new tool names are visible (the Portal caches its server list at connect time — reconnect is required, not optional)
- [ ] 6.3 Confirm a real tool call succeeds through the Portal under the new names

## 7. Decommission (after a soak period)

- [ ] 7.1 Confirm no errors/traffic on the old subdomain for the agreed soak window
- [ ] 7.2 Remove the old Cloudflare Access entry + DNS record
- [ ] 7.3 Remove the old Komodo stack (`git-mcp-stolperstein-nebula`)

## 8. Fleet documentation sync

- [ ] 8.1 Update the parent `CDiT-infrastructure` repo's wiki topic (`docs/wiki/topics/mcp-stolperstein.md`) and mcp-fleet roster entry to the new name
- [ ] 8.2 Recompile that wiki (`/wiki-compile` in `CDiT-infrastructure`) once the above lands
