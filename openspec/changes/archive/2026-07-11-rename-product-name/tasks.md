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

## 4. Deploy — DONE 2026-07-11 (via update-in-place, not new-stack; see note)

**APPROACH CHANGE:** executed as an **update-in-place** of the existing stack `git-mcp-stolperstein-nebula` rather than a parallel new stack. Rationale: same stack resource → same compose project → the existing `stolperstein-data`/`fastmcp-data` volumes are reused *automatically* (no `project_name` pinning trick, no two-resources-one-project hazard), only 3 config fields change, and it neutralizes the merge-trap (stack now builds from the branch, so a later `main` merge won't auto-redeploy). The auto-mode permission system blocked the agent from executing the production writes directly; the operator ran the prepped scratchpad scripts via `!` under direct authorization.

- [x] 4.1 Snapshot baseline: `proposer_did=did:key:z6MknmCWEfBfraxGGpwiQ1rS8paUwsh9Z4UmdCSne9x8rxVL`, KU `total=119`. Corrected: no separate `stolperstein-key` volume — only `stolperstein-data` (holds both `stolperstein.db` + `stolperstein.key`) and `fastmcp-data`.
- [x] 4.2 (as update-in-place) Updated the live stack config via raw Komodo API (repo `CaseyRo/stolpersteine`→`CaseyRo/mcp-stolperstein`, branch `main`→`rename-to-stolperfalle`, env block), read-back-verified before deploy. Same resource → existing volumes reused automatically.
- [x] 4.3 Env: renamed only `MCP_STOLPERSTEIN_API_KEY`→`MCP_STOLPERFALLE_API_KEY` reusing the same `[[MCP_STOLPERSTEIN_API_KEY]]` secret ref (no rotation); everything else (`CQ_*`) identical to the live env block; used raw API to preserve newlines (km update stack's query-string form collapses them). Public URL comes from the renamed compose default.
- [x] 4.4 Deployed. Note: Komodo's `compose up` built + created the new `mcp-stolperfalle` container but couldn't start it (port 8716 held by the still-running old service — service rename meant compose didn't auto-stop the old one). Completed the handoff manually (stop old → the new container then had a stuck host-port binding from the failed first start → `docker rm` + `docker compose up -d --remove-orphans` in `/etc/komodo/stacks/git-mcp-stolperstein-nebula` recreated it cleanly with the port bound and removed the old orphan).
- [x] 4.5 Continuity gate PASSED: new deployment shows the same `proposer_did` and KU `total=119`. Same volume, DB, and signing key.
- [x] 4.6 Verified: container healthy, host `:8716` + external `mcp-stolperstein.cdit-dev.de/health` → 200, AND a live `stolperstein_status` MCP call through the full Portal→CF→tunnel path returned 119 KUs (API key carried over, tools still resolve).

## 5. Cloudflare / DNS cutover

- [ ] 5.1 Add a new Cloudflare Access catalog entry + DNS record for the new subdomain (e.g. `mcp-stolperfalle.cdit-dev.de`)
- [ ] 5.2 Leave the old `mcp-stolperstein.cdit-dev.de` entry resolving in parallel — no immediate teardown
- [ ] 5.3 Verify the new subdomain is reachable and healthy end-to-end through Cloudflare Access

## 6. Fleet + Portal update (do this last)

- [ ] 6.1 Update this fleet's Cloudflare MCP Portal catalog entry to the new tool names / new origin
- [ ] 6.2 Reconnect the Claude Code MCP connector so the new tool names are visible (the Portal caches its server list at connect time — reconnect is required, not optional)
- [ ] 6.3 Confirm a real tool call succeeds through the Portal under the new names

## 7. Decommission (after a soak period)

**Mostly moot under update-in-place:** there is no separate "old stack" to remove — `git-mcp-stolperstein-nebula` is the same resource, now running the `mcp-stolperfalle` container. The old orphan container was already removed by `compose --remove-orphans` during 4.4. The old subdomain `mcp-stolperstein.cdit-dev.de` is currently the *working* domain (serving the new container), so it is NOT decommissioned — it's kept.

- [x] 7.1 Old orphan container removed during the deploy handoff (4.4).
- [ ] 7.2 (optional/deferred) Rename the Komodo stack *resource* `git-mcp-stolperstein-nebula` → `git-mcp-stolperfalle-nebula` for naming consistency — cosmetic, internal-only, fiddly; leave unless it bothers you.
- [ ] 7.3 (optional/deferred) Once the new `mcp-stolperfalle.cdit-dev.de` domain is live (task 5) and soaked, decide whether to retire the old `mcp-stolperstein.cdit-dev.de` alias or keep it as a permanent redirect.

## 8. Fleet documentation sync

- [ ] 8.1 Update the parent `CDiT-infrastructure` repo's wiki topic (`docs/wiki/topics/mcp-stolperstein.md`) and mcp-fleet roster entry to the new name
- [ ] 8.2 Recompile that wiki (`/wiki-compile` in `CDiT-infrastructure`) once the above lands
