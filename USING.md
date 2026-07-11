# Using Stolperfalle

A practical runbook for day-to-day use with Claude Code. If something isn't clear in 30 seconds, tell me and I'll fix it.

---

## The short version (read this first)

**Stolperfalle is shared muscle memory for every Claude Code session you run.** You don't operate it directly — the agent in the session does. What you notice is that Claude gets better at avoiding pitfalls it's never seen in this particular repo before, because it's drawing on a KB captured from every past session across all your projects.

**Your only recurring intentional act is `/stolperfalle:reflect`** at the end of a substantive session — and even then, the Stop hook reminds you when it matters. Everything else (hooks firing, query / confirm / flag / propose calls) is Claude-driven, not you-driven.

- **Hooks fire in the background, silently.** You don't see them. They inject a one-line hint into Claude's context before Claude reads your next message, so Claude knows about a relevant KU without having to be asked.
- **Claude calls `query()`, `confirm()`, `flag()` itself.** The `SKILL.md` bundled with the plugin tells it to. You never type these unless you want to override Claude's judgment.
- **`/stolperfalle:reflect` is the one human-in-the-loop step.** You type it, Claude walks you through candidate KUs, you say yes/no, Claude proposes the keepers.

If you just want to *use* Stolperfalle: do the one-time setup below, then forget about it. Run `/stolperfalle:reflect` when the Stop hook nudges you (or whenever you felt a session taught you something worth preserving). Done.

---

## One-time setup (do this once per machine)

### 1. Make sure the server is reachable

Stolperfalle hooks need to call the MCP server over HTTP. The production URL is `https://mcp-stolperfalle.cdit-dev.de` (Cloudflare Access protected). You need:

```bash
# ~/.zshenv or your shell rc
export MCP_STOLPERFALLE_PUBLIC_URL="https://mcp-stolperfalle.cdit-dev.de"
export MCP_STOLPERFALLE_API_KEY="stmcp_…"   # the bearer token from 1Password
```

Confirm it works:

```bash
curl -s -H "Authorization: Bearer $MCP_STOLPERFALLE_API_KEY" \
  -X POST "$MCP_STOLPERFALLE_PUBLIC_URL/hook/query" \
  -d '{"text": "hello", "limit": 1}' | head -c 200
```

You should see a JSON response (either with a match or `{"results": [], "count": 0}`). If you get `401` or `503`, the env vars are wrong.

### 2. Install the plugin

From this repo:

```bash
cd ~/dev/stolpersteine
# Register the local marketplace with Claude Code (one-time)
claude plugins marketplace add ./.claude-plugin/marketplace.json
claude plugins install stolperfalle
```

This merges `plugin/stolperfalle/hooks/hooks.json` into your `.claude/settings.json` so the three hooks fire automatically.

### 3. Verify the hooks are wired

```bash
grep -A 10 '"stolperfalle"' ~/.claude/settings.json
```

You should see three hook entries: `UserPromptSubmit`, `PostToolUse` (matcher `Bash`), and `Stop`.

---

## Every new project — 30-second check

When you open a project where you expect Stolperfalle to help:

1. **Confirm env is loaded** in your shell: `echo $MCP_STOLPERFALLE_PUBLIC_URL` — should show the URL.
2. **Open Claude Code as usual** (`claude` or the desktop app).
3. **That's it.** Hooks fire automatically on real error signals. No per-project config needed unless you want to tighten patterns (see "Customize per project" below).

If a project uses an unusual error signature Stolperfalle doesn't recognize (e.g., `ACME-42` for some internal system), add this to the project's `.claude/settings.json`:

```json
{
  "env": {
    "STOLPERFALLE_ERROR_PATTERNS": "[\"ACME-\\\\d+\", \"Build failed:\"]"
  }
}
```

---

## What happens automatically, and when

| When | Hook | What fires |
|---|---|---|
| You paste a stack trace / exception into Claude Code | `UserPromptSubmit` | Looks for a matching KU. If confidence ≥ 0.5, injects a one-line hint before Claude reads your prompt. |
| A Bash command you run fails with exit code != 0 (or stderr looks like an error) | `PostToolUse` (Bash) | Same query, hint lands in Claude's next turn. Never delays the command output. |
| Session ends after ≥ 20 tool turns *and* at least one failing bash OR one `confirm`/`flag` call | `Stop` | Prints a single nudge: "Run `/stolperfalle:reflect`..." |
| Session ends short / exploratory | `Stop` | Silent — no nudge. |

**You don't call anything.** Hooks handle query-on-error for you. The channels are rate-limited: 30s cooldown per hook type, 5min per-KU dedupe. If the same KU would fire twice in a row, the second is suppressed.

---

## When to override Claude manually

Claude will call `query` / `confirm` / `flag` on its own when it decides they're useful. You only need to step in when you want to override that judgment. Examples of things you might say to Claude:

- **Force a lookup before Claude assumes it knows:**
  > Before you touch the Xcode project, check Stolperfalle for Swift concurrency traps.

  Claude calls `query(...)` even though no hook triggered.

- **Tell Claude a hint helped even if it didn't say so:**
  > That last injected tip saved us — confirm ku_abc123.

  Claude calls `confirm(...)`.

- **Tell Claude a hint was bad:**
  > That Stolperfalle suggestion was wrong, the workaround doesn't apply anymore — flag it as incorrect.

  Claude calls `flag(...)`.

- **Inspect the KB:**
  > Show me Stolperfalle status with debug info.

  Claude calls `status(debug=True)`.

You're always in "talking to Claude" mode, never "running tools directly" mode.

---

## End of session — /stolperfalle:reflect (the ONE thing you trigger)

The Stop hook will nudge you when a session was substantive. If you want to capture what you learned (or you want to capture something even on a short session), type:

```
/stolperfalle:reflect
```

What happens — **Claude does all of it, you just approve**:

1. Claude asks you to summarize the session in plain prose. (One paragraph. What broke, what you fixed, what was non-obvious.)
2. Claude calls `reflect(session_summary="…")` — returns candidate KUs pre-filled with summary / detail / action / domains / kind / severity / context_*.
3. Claude walks each candidate and asks you "keep this one? y/n."
4. For each "yes," Claude calls `propose(...)` and shows you the new KU id.

You never type `propose(...)` yourself. You just read what Claude proposes and say yes or no.

Good candidates:

- Error patterns that took multiple attempts to diagnose.
- Version-specific pitfalls (`xcode-16`, `node-22`).
- Workarounds for framework bugs.
- Tool configuration that isn't well-documented.

Not candidates:

- Project-specific business logic.
- One-time setup steps.
- Anything already obvious in the docs.

---

## Severity

When proposing, the `severity` field tells future queries how seriously to weight a match:

| Severity | Use when | Effect |
|---|---|---|
| `low` | Cosmetic, nice-to-know | Normal ranking, decays to 0.1 floor |
| `medium` (default) | Standard pitfall | Normal ranking |
| `high` | Broken build / local dev blocker | Ranked above equal-confidence mediums |
| `critical` | Breaks production if ignored | Never decays below 0.2 floor |

Don't set everything to `critical` — it dilutes the signal. Save it for genuine "ignore this and something bad happens" cases.

---

## Customize per project

Add to a project's `.claude/settings.json`:

```json
{
  "env": {
    "STOLPERFALLE_HOOKS_DISABLED": "UserPromptSubmit",
    "STOLPERFALLE_REFLECT_THRESHOLD": "30",
    "STOLPERFALLE_HOOK_COOLDOWN_S": "60",
    "STOLPERFALLE_ERROR_PATTERNS": "[\"MySpecificError:\", \"ACME-\\\\d+\"]"
  }
}
```

All optional. Leave empty to use global defaults.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Hooks never fire | `echo $MCP_STOLPERFALLE_PUBLIC_URL $MCP_STOLPERFALLE_API_KEY` — both set? |
| "Stolperfalle was unreachable during this session" at session end | Server / Cloudflare Access auth issue. Confirm with the `curl` test above. |
| Wrong hint injected after an error | Flag the KU: `flag(ku_id="…", reason="incorrect", detail="…")`. Stays in dedupe window for 5min so you won't see it again immediately. |
| Hints are too noisy | Raise the threshold: `STOLPERFALLE_HOOK_COOLDOWN_S=120`. Or disable a hook: `STOLPERFALLE_HOOKS_DISABLED=UserPromptSubmit`. |
| Nudge at `Stop` is too frequent | Raise threshold: `STOLPERFALLE_REFLECT_THRESHOLD=30` (default 20). |
| Need to disable everything temporarily | `STOLPERFALLE_HOOKS_DISABLED=UserPromptSubmit,PostToolUse,Stop` |
| Need to see what's in the store | In Claude Code: "Call status(debug=True) on Stolperfalle." |

---

## For the curious: where the data lives

- **KU data + public key + DID**: `/data/stolperstein.db` (in the Komodo-managed Docker volume `stolperstein-data`). Filenames/volume name intentionally unchanged by the product rename.
- **Private signing key**: `/data/stolperstein.key` (mode 0o600). **Treat as sensitive.** Excluded from volume backups.
- **OAuth client cache (FastMCP)**: `/data/fastmcp/`.
- **Pre-migration backups**: `/data/stolperstein.db.bak-pre-v<N>` — created automatically on breaking schema changes, preserved until you run `mcp-stolperfalle prune-backups --confirm`.

---

## What's next (Phase 2)

- Enforceable org boundaries (currently `owner_org` is recorded; `TRUSTED_ORGS` is read-filter only).
- Richer emergent clustering beyond count-based thresholds.
- UI for reviewing / graduating KUs to a team or global tier.
- Upstream CQ adoption of the extensions tracked in [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286).
