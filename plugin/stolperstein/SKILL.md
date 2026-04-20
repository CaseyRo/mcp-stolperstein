---
name: stolperstein
description: Query and contribute to the Stolperstein knowledge base — experiential knowledge for AI coding agents
metadata:
  priority: 50
---

# Stolperstein — Experiential Knowledge for AI Agents

You have access to a knowledge base of problem-solution pairs (Knowledge Units) captured from past coding sessions. Use it to avoid rediscovering known issues.

## When to Query

- **Before tackling unfamiliar technology** — check if there are known pitfalls.
- **When you hit an error** — hooks will auto-query for you on structured error signals; you can also call `query()` directly for the full KU (hook injections only carry the top result's action).
- **When switching context** — query for domain-specific gotchas.

```
query(text="Swift concurrency strict checking", domain=["swift", "xcode"])
```

## When to Propose

After solving a novel problem that would help a future agent:

```
propose(
  summary="Xcode 16 requires explicit Swift 6 concurrency opt-in",
  detail="When targeting Swift 6 language mode, all sendable violations become errors...",
  action="Add -strict-concurrency=complete to build settings.",
  domains=["swift", "xcode"],
  kind="pitfall",
  context_languages=["swift"],
  context_frameworks=["swiftui"],
  context_environment="xcode-16",
  context_pattern="concurrency",
  severity="high",
)
```

**Required fields:** `summary`, `detail`, `action`, `domains` (non-empty list), `kind` (one of `pitfall | workaround | tool-recommendation`).

**Optional `context_*` + `severity`:** pre-filled by `reflect()`, so you can pass its candidates straight through. Useful because `severity="critical"` raises the decay floor — critical KUs never fully forget themselves.

**Note:** `gap-signal` is no longer a proposable kind. Tool gaps emerge automatically from query-miss patterns.

## What's strict CQ vs Stolperstein extension

- **Strict upstream CQ fields** (go out on every graduated payload): `id`, `domains`, `insight.*`, `context.languages/frameworks/pattern`, `evidence.confidence/confirmations/first_observed/last_confirmed`, `created_by`, `superseded_by`, `flags[]`.
- **Stolperstein extensions** (local-only; stripped when we graduate to upstream): `kind`, `status`, `staleness_policy`, `related[]`, `owner_org`, `provenance.proposer_did/graduation_history/emergent`, `evidence.severity`, `evidence.contributing_orgs`, `context.environment`.

We're proposing our extensions upstream at [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286). See `docs/cq-extensions.md` for the full registry.

## When to Confirm

When you encounter a KU that helped and was accurate:

```
confirm(ku_id="ku_abc...")
```

Not idempotent — each call increments confirmations and boosts confidence. Diversity-weighted: a confirmation from a new install carries more than one from the same install repeatedly.

## When to Flag

When a KU is outdated, incorrect, superseded, or dangerous:

```
flag(ku_id="ku_abc...", reason="incorrect", detail="No longer applies after HA 2025.4")
flag(ku_id="ku_old...", reason="superseded", superseded_by="ku_new...")
```

**Valid reasons:** `stale | incorrect | superseded | dangerous | duplicate`. On the wire, `dangerous` maps to `incorrect` (upstream schema doesn't have `dangerous`). `superseded` requires `superseded_by=<ku_id>` and archives the old KU.

## When to Reflect

At the end of a substantive debugging or development session, run `/stolperstein:reflect` to extract generalizable learnings. Candidates come pre-filled with `context_*` and `severity` so you can go straight to `propose()` without re-reading docs.

## Status

```
status()              # default — token-frugal (total, by_status, staleness, tool_gap_signals)
status(debug=True)    # operator mode — adds schema_version, proposer_did, migrations, etc.
```

## Hooks active in this project

Three hooks ship with the plugin:

- **`UserPromptSubmit`** — when your prompt contains a *structured* error signal (exception class name, traceback marker, non-zero exit code mention, HTTP status string, `fatal:`/`panic:`/`Error:` prefix), the hook runs `query()` in the background and injects a sanitized, temporally-qualified hint if the top match has confidence ≥ 0.5.
  - Conversational prose like "my regex failed" does NOT trigger — only structured signals do.
- **`PostToolUse` (matcher=`Bash`)** — when a Bash tool call exits non-zero or its stderr contains a structured signal, the hook calls `query()` and lands a hint for the agent's next turn. Fire-and-forget with a 500ms budget; never delays your tool response.
- **`Stop`** — at end of session, nudges `/stolperstein:reflect` if the session had ≥ `STOLPERSTEIN_REFLECT_THRESHOLD` tool-call turns (default 20) AND at least one non-zero bash exit OR one `flag`/`confirm` call. Trivial sessions produce no nudge.
  - **Opt-in: `STOLPERSTEIN_REFLECT_VIA_HOOK=true`** — when set, the Stop hook skips the nudge and instead POSTs a locally-derived session summary directly to `POST /hook/reflect` on the origin server. This bypasses both the MCP Portal and Anthropic's connector relay, avoiding WAF false positives on reflect-sized payloads. Fire-and-forget; failures mark the session as unreachable and stay silent. Requires the server running Phase 2 of `mcp-hook-rest-and-waf-extension` (stolperstein ≥ 0.2.0) and the same `MCP_STOLPERSTEIN_PUBLIC_URL` + `MCP_STOLPERSTEIN_API_KEY` vars the other hooks already use.

**Hook injections are rate-limited and sanitized.** A per-hook 30-second cooldown + 5-minute per-KU dedupe prevents flooding. Every KU `action` field is tag-stripped (`re.sub(r'<[^>]+>', '', action)`) before injection, so a crafted KU whose `action` contains `<system-reminder>` tags cannot impersonate a privileged instruction.

**Hook injections carry only the top match's action (one field).** For the full KU shape — including detail, context, provenance, owner_org — call `query()` directly.

## Disabling hooks

- **Temporarily, one hook:** `STOLPERSTEIN_HOOKS_DISABLED=UserPromptSubmit` (comma-separated list supports multiple).
- **Adjust thresholds:** `STOLPERSTEIN_HOOK_COOLDOWN_S=30`, `STOLPERSTEIN_REFLECT_THRESHOLD=20`.
- **Route reflect through hook channel:** `STOLPERSTEIN_REFLECT_VIA_HOOK=true` (documented above under `Stop`).
- **Project-specific error patterns:** `STOLPERSTEIN_ERROR_PATTERNS` (JSON array of regex strings) in `.claude/settings.json` replaces the default signal set.
- **Fully off:** remove the `stolperstein` plugin's hook block from `.claude/settings.json`.

## Requirements

Hooks require the MCP server running in HTTP mode with:

- `MCP_STOLPERSTEIN_PUBLIC_URL` — reachable URL (Tailscale / Cloudflare Access / localhost:8716).
- `MCP_STOLPERSTEIN_API_KEY` — bearer token.

Without these, hook handlers exit 0 silently (no-op). A session-wide "Stolperstein was unreachable" notice prints once at `Stop` if any hook attempt failed to reach the server.
