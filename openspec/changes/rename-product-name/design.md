## Context

Production today: GitHub repo `CaseyRo/mcp-stolperstein`, one Komodo stack
(`git-mcp-stolperstein-nebula`) on `nebula-1`, fronted by a co-located
Cloudflare tunnel at `mcp-stolperstein.cdit-dev.de`, live KU data in the
`stolperstein-data` Docker volume, the Ed25519 signing key in
`stolperstein-key`, a Claude Code plugin at `plugin/stolperstein/`
registered in a marketplace, and MCP tools surfaced to agents as
`stolperstein_query`/`propose`/`confirm`/`flag`/`reflect`/`status`. The
proposal decided the new public name is **Stolperfalle** and that the
wire-protocol extension namespace `stolperstein:*` (load-bearing in the
merged upstream Mozilla AI PR #453) does not change.

## Goals / Non-Goals

**Goals:**
- Rename every public/product-facing identifier to `stolperfalle` with zero
  KU data loss and no signing-key/DID rotation.
- Keep the upstream Mozilla relationship (wire namespace, discussion #286,
  PR #453) completely untouched.
- Sequence the cutover so there's always a working, reachable server —
  no window where the tool is simply down.
- Leave the parent `CDiT-infrastructure` fleet wiki/roster in sync once done.

**Non-Goals:**
- Not changing the wire namespace, the KU schema, or any of the six MCP
  tools' behavior — names change, nothing else.
- Not re-litigating the new name (Stolperfalle is decided).
- Not retroactively fixing external content (none exists).
- Not deciding PyPI publishing status here (open question below).

## Decisions

**1. Rename the GitHub repo in place (GitHub's own rename), not a fresh repo.**
Preserves issue/PR/star history and GitHub's automatic redirect for old
clone URLs and git remotes — existing local checkouts (including this one)
keep working without an immediate forced update.
*Alternative considered:* new repo + archive old — rejected, loses history
and the redirect safety net for no benefit.

**2. Reuse the existing Docker volumes under their current names.**
Only the Komodo *stack* and *container* names change; `stolperstein-data`
and `stolperstein-key` keep their literal volume names. Volume names are
invisible infrastructure plumbing — renaming them means an explicit
stop-copy-restart dance that risks the KU DB or signing key for a purely
cosmetic win.
*Alternative considered:* rename volumes to `stolperfalle-*` for full
naming consistency — rejected on risk/reward grounds.

**3. Signing key / DID continuity is a hard constraint, not a hope.**
As long as `stolperstein-key` is mounted at the same in-container path
post-rename, `/data/stolperstein.key` is untouched and the DID does not
rotate. This gets an explicit verification gate (below), not just an
assumption.

**4. Staged cutover, not big-bang.**
Land code on a branch → rename the GitHub repo → merge via PR → redeploy
Komodo under the new stack name (same volumes, copied-not-regenerated env
vars) → verify → cut Cloudflare/DNS over with the old entry kept alive in
parallel → update this fleet's own Claude Code / Portal connection last →
update the parent wiki once everything is live.
*Alternative considered:* single big-bang cutover — rejected, removes the
verification gate between steps that catches a volume-mount or env-var
mistake before it compounds.

## Risks / Trade-offs

- [Risk] Renamed Komodo stack provisions **fresh** volumes instead of
  mounting the existing ones → KU base silently resets, DID rotates.
  → **Mitigation:** pre-flight check (`docker volume ls | grep stolperstein`)
  before first deploy of the new stack; post-deploy gate comparing
  `status(debug=True)`'s `proposer_did` and KU `total` against a pre-rename
  snapshot.
- [Risk] DNS/Cloudflare Access cutover breaks an in-flight client (this very
  Claude Code session, other agents, hooks) if done without a transition
  window. → **Mitigation:** keep the old DNS/Access entry live in parallel;
  update this fleet's own Portal connection *last*, only after the new
  endpoint is confirmed healthy.
- [Risk] Tool-name rename breaks the three Claude Code hooks
  (`on_prompt.py`/`on_bash.py`/`on_stop.py`), which call the old tool
  names. → **Mitigation:** rename server-side tool registrations and hook
  handler references in the same commit — one atomic deploy, not staged.
- [Risk] GitHub repo rename confuses in-flight PRs (#33, #34) or forks.
  → **Mitigation:** both are already merged/mergeable before rename starts;
  GitHub's redirect handles clone/fetch URLs transparently regardless.
- [Trade-off] `stolperstein:*` lives on forever as the wire namespace —
  invisible to users, visible to anyone reading `models.py` or the Mozilla
  discussion thread. **Accepted deliberately**: renaming the wire namespace
  reopens the upstream relationship for a purely cosmetic, internal-facing
  win.

## Migration Plan

1. Branch: package/module rename, env var rename, CLI entry point, MCP tool
   registration names, plugin dir + `marketplace.json` + `hooks.json`,
   Dockerfile/compose references, README/CLAUDE.md/USING.md text.
2. Local verification: build the renamed package, full test suite green,
   CLI + tool names resolve under the new names.
3. Rename the GitHub repo (before merging, so the branch's own remote
   doesn't need a mid-flight fixup).
4. Merge via PR (`main` is branch-protected).
5. Komodo: new stack config pointed at the renamed repo, same volume
   mounts, env vars **copied**, not regenerated, under the new var names.
6. Deploy; verify health, DID continuity, and KU count against the
   pre-rename baseline.
7. Cloudflare: add the new Access catalog entry + DNS record; leave the old
   one resolving in parallel.
8. Update this fleet's own Portal connection / MCP config to the new tool
   names.
9. After a short soak, decommission the old Access entry, DNS record, and
   Komodo stack.
10. Update the parent `CDiT-infrastructure` wiki
    (`docs/wiki/topics/mcp-stolperstein.md`) and mcp-fleet roster.

**Rollback:** before step 6's verification passes, rollback is simply not
cutting over — the old stack runs untouched through steps 1–5. After step 9
(old stack decommissioned), rollback follows this repo's existing
documented procedure: redeploy the last-good pre-rename commit SHA onto a
fresh stack pointed at the (still-existing) volumes.

## Open Questions

- Package name: `mcp_stolperfalle` (matches every other fleet repo's
  `mcp_<service>` convention) vs. dropping the `mcp_` prefix — recommend
  keeping the convention unless there's a reason to break it.
- Length of the DNS/Access parallel-run window before decommissioning the
  old subdomain.
- Whether to leave a breadcrumb (GitHub repo description/topics) pointing
  from the old name to the new one for discoverability.
- Whether this package is published to PyPI today and needs its own
  rename/deprecation notice there — not confirmed in this proposal.
