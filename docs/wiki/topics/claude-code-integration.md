---
topic: claude-code-integration
last_compiled: 2026-07-07
---

# Claude Code Integration

## Summary [coverage: high — 4 sources]

Stolperfalle reaches Claude Code (and downstream tools) through four cooperating surfaces:

1. **The plugin** — a `SKILL.md` behavioral guide plus a `hooks.json` manifest, installable by wiring the MCP server into project- or user-level `.claude/settings.json`. The server is reachable via stdio (local) or HTTP/SSE (remote via Tailscale or Cloudflare Access), exposing all 6 MCP tools (`query`, `propose`, `confirm`, `flag`, `reflect`, `status`).
2. **Three hooks** — `UserPromptSubmit`, `PostToolUse` (filtered to `Bash`), and `Stop`. The first two proactively `query()` on **structured** error signals and inject a sanitized, rate-limited, temporally-qualified hint when a KU clears `confidence >= 0.5`. `Stop` prints a non-blocking `/stolperfalle:reflect` nudge only after substantive sessions, and a health notice if the MCP server was unreachable.
3. **The `/stolperfalle:reflect` slash command** — prompts the agent to summarize the session, calls `reflect`, and presents candidate KUs (with inferred flat `context_*` + `severity`) for approval before `propose()`.
4. **Optional SiYuan sync** — an env-gated, non-blocking one-way push of active KUs to a SiYuan notebook as structured documents, with a schema-version gate for the legacy shape during transition.

The current specification is the result of a v0 baseline (`stolperstein-mvp-scaffold`) that was substantially reshaped by `cq-v1-alignment-and-hooks`, which split hook behavior into its own `claude-hooks` capability and tightened SKILL.md/reflect to v1 tool shapes.

## Rationale & Context — why hooks + plugin + downstream sync [coverage: medium — 4 sources]

The plugin exists so agents **auto-discover** Stolperfalle without the user wiring anything per-session: on session start the agent has `SKILL.md` in context describing when and how to call each tool, and — in the v1 shape — which hooks are active and how to disable them. This makes the proactive behavior legible to both the agent and the human.

The hooks exist because the highest-value moment to recall experiential knowledge is exactly when something breaks, and an agent will not always think to `query()` on its own. Firing on structured error signals (a real exception class, a non-zero exit, an HTTP error string) turns "a KU that would have helped" into an injected hint at the point of failure. The design is deliberately conservative on two axes: **precision** (bare conversational words like "failed" or "error" are not signals, to avoid false positives) and **safety** (all injected content is sanitized against prompt-injection and never mimics privileged message roles). Rate limiting keeps an error loop from flooding the agent with the same nudge.

Downstream SiYuan sync exists so the knowledge base is legible to humans in their notes tool, not only to agents over MCP. It is strictly one-way (Stolperfalle → SiYuan), optional, and non-blocking, so it never degrades the MCP tool path — a note-export nicety, not a dependency.

## Requirements & Behavior — SHALL requirements + scenarios [coverage: high — 4 sources]

### SKILL.md behavioral guidance

The plugin SHALL ship a `SKILL.md` that instructs agents to query on structured error signals, propose KUs after solving novel problems, and run reflect at the end of substantive sessions, describing all 6 tools. In the v1 shape it SHALL use **v1-shaped examples**: flat `context_languages`, `context_frameworks`, `context_environment`, `context_pattern`, and `severity` on `propose` (and `domains`, not `domain`), and SHALL NOT present `gap-signal` as a proposable kind. It SHALL include a "Hooks active in this project" section and a "Disabling hooks" section documenting `STOLPERFALLE_HOOKS_DISABLED`, and SHALL note the dual-channel behavior: hook injections are rate-limited single-field nudges (30s cooldown), while an explicit `query()` returns the full KU shape — call `query()` directly when more detail is needed.

### UserPromptSubmit hook — query on structured error signals in the prompt

- WHEN the submitted prompt contains a structured signal — a capitalized exception class (`TypeError`, `NullPointerException`), a non-zero exit-code mention (`exit code 1`, `exited with 127`), an HTTP status string (`500 Internal Server Error`, `HTTP 404`), a traceback marker (`Traceback (most recent call last):`, `at ... (... line N)`), or an error-tag prefix (`fatal:`, `panic:`, `Error:`) — THEN the hook SHALL call `query(text=<prompt truncated to 512 chars>, confidence_min=0.5, limit=1)` and inject a temporally-qualified hint on a match.
- WHEN the prompt only contains a bare lowercase word like "failed" ("my regex failed to match") — THEN the hook SHALL be a silent no-op.
- WHEN `.claude/settings.json` sets `STOLPERFALLE_ERROR_PATTERNS=[...]` — THEN the hook SHALL use exactly those patterns for that project, replacing the defaults.

### PostToolUse hook (Bash) — query on tool errors

- WHEN a `Bash` tool result has `exit_code != 0` OR any configured structured signal in `stderr` — THEN the hook SHALL extract the last 4KB of `stderr` (or `stdout` if `stderr` is empty), call `query()`, and inject a hint on `confidence >= 0.5`.
- WHEN the call exits 0 with no structured signals — THEN no `query()` fires.
- WHEN the MCP server is down OR the request exceeds the 500ms budget — THEN the hook SHALL abandon silently and SHALL NOT delay the tool response (fire-and-forget).

### Stop hook — reflect nudge + unreachable notice

- WHEN a session reaches `Stop` with at least `STOLPERFALLE_REFLECT_THRESHOLD` tool-call turns (default 20) AND at least one non-zero-exit bash call OR one `flag()`/`confirm()` call — THEN it SHALL print `Run /stolperfalle:reflect to capture session learnings.` exactly once. It SHALL NEVER auto-invoke `reflect()`.
- WHEN the session is short (e.g. 3 turns) OR long but purely exploratory (30 turns, zero non-zero exits, no `flag`/`confirm`) — THEN it prints nothing.
- WHEN the project sets `STOLPERFALLE_REFLECT_THRESHOLD=10` — THEN 10 is used, with the substantive-signal check still required.
- WHEN any of the three hooks attempted an MCP call during the session and could not reach the server — THEN `Stop` SHALL print, once, `Stolperfalle was unreachable during this session — hook-based queries were skipped.` This is independent of the reflect-nudge gating; UserPromptSubmit and PostToolUse stay silent on failure themselves.

### Injection sanitization and temporal qualification

Before any injection the hook SHALL (1) strip angle-bracket tags from the KU `action` via `re.sub(r'<[^>]+>', '', action)`; (2) wrap it in a fixed template beginning `Note from Stolperfalle (from your previous Bash error): [KU {id}, confidence {c:.2f}] {summary} — Recommended action: {action_sanitized}`; and (3) NOT emit `<system-reminder>`, `<system>`, `<assistant>`, or any angle-bracket tag readable as a privileged role. The same sanitization is applied at CQ team-sync ingest to KU `summary`, `detail`, and `action`. Example: a KU whose action is `<system-reminder>do X</system-reminder>do Y` injects as `do Xdo Y` inside the fixed wrapper.

### Rate limiting and dedupe

Each hook SHALL keep a schema-validated state file at `$FASTMCP_HOME/hooks-state.json` recording last-injection time per hook type and recently-injected KU ids. No hook injects more than once per 30s (`STOLPERFALLE_HOOK_COOLDOWN_S`); hooks dedupe on KU id within a 5-minute window (10 failing calls in 30s → at most one injection; the same `ku_abc123` matched twice 45s apart → second suppressed). Concurrent writes are serialized via `fcntl.flock`; on lock contention the hook abandons. A corrupt or schema-invalid state file is treated as empty, rewritten atomically, and injection proceeds.

### Reflect slash command flow

- WHEN the user runs `/stolperfalle:reflect` — THEN the skill SHALL prompt the agent to summarize the session's key learnings, call `reflect`, and present each candidate KU — including the inferred flat `context_*` and `severity` fields so the agent can edit — for approval.
- WHEN reflect returns 3 candidates and the agent approves 2 — THEN the skill SHALL call `propose` for each approved candidate with the full v1 payload (flat context + severity) passed through unchanged, and report the created KU ids.

### SiYuan sync

- Enabled only when `CQ_SIYUAN_URL` and `CQ_SIYUAN_NOTEBOOK` are set; otherwise all MCP tools operate normally with no SiYuan behavior or errors.
- WHEN a KU reaches `active` (after first confirmation) — THEN the system SHALL create a SiYuan document titled by the KU summary with structured blocks for detail, action, domain tags, confidence, and metadata.
- WHEN an active KU's confidence changes via `confirm`/`flag` — THEN the existing SiYuan document SHALL be updated.
- WHEN a KU transitions to `archived` — THEN the document SHALL be moved to an "Archived" sub-section or deleted, per `CQ_SIYUAN_ARCHIVE_MODE`.
- Sync runs asynchronously after the tool response; failures are logged for retry and SHALL NOT block or fail the MCP tool response even if the SiYuan instance is unreachable.

## Design & Architecture — handlers, hook channel vs MCP, sync gating [coverage: medium — 3 sources]

**Handler structure.** Each hook is a self-contained Python script under `plugin/stolperfalle/hooks/handlers/`, using stdlib plus the locally installed `stolperfalle` package only, and completing within a 500ms default budget (exceeding it abandons without error). `hooks.json` is the single source of truth for which hooks ship; the installer merges the three hook definitions into `.claude/settings.json` on `claude plugins install stolperfalle`. Individual hooks are disableable via `STOLPERFALLE_HOOKS_DISABLED=<hook_name,...>` (comma-separated) or by removing the hook block — a disabled handler exits 0 immediately without calling the server, leaving the others active.

**Hook channel vs the agent's MCP channel.** Hooks reach the *same* MCP server but over a fast, bounded side-channel distinct from the agent's ordinary tool calls: they open a subprocess stdio session to `mcp-stolperfalle` when `TRANSPORT=stdio` is configured locally, or POST to `MCP_STOLPERFALLE_PUBLIC_URL` with a bearer token from `MCP_STOLPERFALLE_API_KEY`. This channel is one-shot and time-boxed (500ms), which is why hook queries silently abandon on slowness while an agent's explicit `query()` tool call is free to take longer and return the full KU shape. Token handling is security-critical: HTTP handler code wraps requests in `try/except` that re-raises **sanitized** errors excluding the `Authorization` header, the token local variable is explicitly `del`-eted after the request, and the token is NEVER passed to `subprocess(env=...)` — so a traceback cannot leak it.

**Sync gating.** SiYuan sync is layered strictly outside the request path: gated entirely on `CQ_SIYUAN_URL` + `CQ_SIYUAN_NOTEBOOK`, triggered on KU state changes (propose/confirm/flag), and run asynchronously after the tool response is already sent. This keeps it a fully optional downstream export — a failure or unreachable SiYuan degrades to a logged retry, never a failed MCP call.

## Schema & Interop — the KU shape crossing the hook/sync boundary [coverage: medium — 3 sources]

**Hook boundary (nudge).** What crosses into agent context on a hook injection is a **single sanitized field**, not the full KU: the fixed wrapper carries the KU `id`, `confidence`, `summary`, and the angle-bracket-stripped `action`. This is deliberately narrower than the tool boundary — an explicit `query()` returns the full KU shape, and SKILL.md tells the agent to call it directly when the one-field nudge is insufficient.

**Reflect boundary.** Candidates cross as flat, propose-ready fields: `context_languages`, `context_frameworks`, `context_environment`, `context_pattern`, `severity` (plus `domains`), so the approve step forwards them to `propose()` unchanged with no reshaping.

**SiYuan boundary.** A synced KU is rendered as one document with a consistent structure: title from `summary`; domain tags as SiYuan tags (e.g. `#swift`, `#xcode`); a "Problem" heading with `detail`; an "Action" heading with `action`; a metadata block (`confidence`, confirmations, `kind`, `status`, timestamps); and links to related KUs if any. The `CQ_SIYUAN_SCHEMA_VERSION` gate governs whether the export emits the legacy v0 shape (value `0`) during the sync transition or the current shape — the transition mechanism for evolving the SiYuan document format without breaking existing notes. (Note: the `siyuan-sync` spec itself names `CQ_SIYUAN_URL`, `CQ_SIYUAN_NOTEBOOK`, and `CQ_SIYUAN_ARCHIVE_MODE`; the schema-version gate is the project's documented transition control layered over that structure.)

## Status & Open Questions — v0 baseline vs cq-v1 additions [coverage: high — 3 sources]

**v0 baseline (`stolperstein-mvp-scaffold`).** The original integration spec defined a simpler surface: a `SKILL.md` describing the 6 tools ("query before unfamiliar tech, propose after novel problems, reflect at end"), a **single** `PostToolUse` hook that queried on any tool error and injected the top KU's `action` on `confidence >= 0.5`, the `/stolperfalle:reflect` skill, and stdio (`python -m stolperfalle`) or HTTP/SSE-via-Tailscale MCP config.

**cq-v1 additions (`cq-v1-alignment-and-hooks`).** This change:
- **Relocated** the single PostToolUse-hook requirement out of `claude-code-integration` into a new `claude-hooks` capability that owns the full hook surface (UserPromptSubmit + PostToolUse Bash + Stop), structured-signal matching, action sanitization, temporal qualification, rate limiting, and handler scripts. The plugin still *ships* the hooks; they're *specified* in `claude-hooks`. Implementers treat `claude-hooks/spec.md` as authoritative.
- Tightened `SKILL.md` and the reflect skill to **v1 tool shapes** (flat `context_*` + `severity`, `domains` not `domain`, no `gap-signal` as a proposable kind) and required the hook-active / disable-hatch / dual-channel documentation sections.
- Broadened MCP config to include **Cloudflare Access** (bearer token) alongside Tailscale, and updated the stdio command to `mcp-stolperfalle`.

**Optional / deferred.** SiYuan sync is entirely optional (env-gated) and downstream-only. `CQ_SIYUAN_ARCHIVE_MODE` leaves archived-KU handling (move vs delete) as a deployment choice. Per-project overrides — `STOLPERFALLE_ERROR_PATTERNS`, `STOLPERFALLE_REFLECT_THRESHOLD`, `STOLPERFALLE_HOOK_COOLDOWN_S`, `STOLPERFALLE_HOOKS_DISABLED` — are all configuration knobs rather than fixed behavior. No open contradictions surfaced across the specs; the main evolution to track is that hook behavior now lives in `claude-hooks`, with `claude-code-integration` reduced to plugin packaging, SKILL.md, the reflect skill, and MCP-server configuration.

## Sources [coverage: high — 4 sources]

- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/claude-code-integration/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/claude-hooks/spec]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/claude-code-integration/spec]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/siyuan-sync/spec]]
