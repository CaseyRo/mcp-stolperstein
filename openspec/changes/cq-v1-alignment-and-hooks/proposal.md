## Why

Stolperstein began as a "CQ-compatible local node" — a single-operator knowledge base for coding agents. When we re-checked `mozilla-ai/cq` upstream (vendored at commit `92b35de`) we found two things we didn't expect:

1. **The current upstream schema is much smaller than the blog copy suggested.** No `severity`, no DID-based provenance, no `graduation_history`, no `kind` enum, no state machine. It's a tight base: insight + context + confidence + a flag log. The richer concepts we read about in Mozilla's announcements are aspirational, not yet shipped.
2. **Our existing v0 implementation is already in several ways ahead of upstream**, but names things slightly wrong: we use `domain` (upstream: `domains`), `id` at 24 hex chars (upstream: strict 32), `version` as a string (upstream: integer), and `last_confirmed` at top level (upstream: inside `evidence`).

This reframes the work. We're not catching up to CQ v1 — we're **conforming** to its strict, small base **and deliberately extending it** with the concepts Stolperstein needs (severity, rich provenance, org boundaries, a state machine, emergent-signal detection, a kind enum). Those extensions are what makes Stolperstein a working implementation of the larger thesis — the machine-readable org layer that lets agent-to-agent awareness replace the middle-management-as-compression-layer that status meetings, reports, and dashboards exist to compensate for.

The strategic bet is the same as before — Stolperstein as the atomic data layer for the machine-readable org layer (tracked in CDI-999). What changes is the narrative: we are not a fork; we are a conforming-plus-extending reference implementation. Extensions we find useful get proposed upstream so the protocol grows. An issue with the first batch of proposed extensions has been drafted at `openspec/changes/cq-v1-alignment-and-hooks/upstream-issue-draft.md` and will be filed against `mozilla-ai/cq` as part of this change.

Three operational reasons still force all of this into one change:

1. **Strict conformance is currently broken.** Our `domain/domains`, ID format, version type, and `last_confirmed` location all fail upstream validation. Any consumer who validates our wire output against the pinned schema will reject us.
2. **No migration path exists.** Existing KUs in `/data/stolperstein.db` will silently diverge on any schema change because `store._init_db` is CREATE-IF-NOT-EXISTS-only. The first breaking migration is now.
3. **Hooks are metadata-only.** `plugin/stolperstein/hooks/hooks.json` today is aspirational; nothing fires. Agents rediscover failures the KB could have warned them about, undermining the thesis.

A four-agent review (ux / mcp-tool / security / strategy) surfaced fixes we fold into this change so we don't ship broken foundations.

## What Changes

### 1 — Strict CQ conformance (wire format only)

The *wire* representation used for CQ team/global sync and any external validation SHALL conform exactly to the upstream schema as vendored. That means:

- **Rename `domain` → `domains`** (plural, the upstream name) in the CQ JSON payload; internal code may keep either alias.
- **KU id format** SHALL be `^ku_[0-9a-f]{32}$` for newly-generated IDs. Existing 24-hex IDs SHALL be padded deterministically to 32 hex in migration `m0000_ku_id_format_fix`, with all cross-references (`superseded_by`, `related[].target_id`) rewritten in the same transaction.
- **`version`** in CQ JSON SHALL be the integer `1`, not the string `"1.0.0"` or `"1.1.0"`. Our internal model may still carry a semver string for Stolperstein-level versioning; it is not emitted in the CQ shape.
- **`context.languages`** is an array of strings (not `language` singular); other fields we use locally (`context.environment`) are **NOT** emitted in strict CQ output because upstream's schema is `additionalProperties: false`.
- **`evidence.last_confirmed`** is inside the evidence block (not a top-level `last_confirmed_at`); our local storage column keeps the `last_confirmed_at` name but the CQ serializer places it correctly.
- **Flag reasons** SHALL map to upstream's enum (`stale | incorrect | duplicate`) on the wire. Our local `dangerous` maps to `incorrect` + an extension marker (internal only); `superseded` is never a flag — it's expressed as the top-level `superseded_by` field, matching upstream.
- **Two serializers**: `to_cq_json_strict()` emits the upstream-valid shape with all our extensions stripped; `to_cq_json_rich()` emits the internal shape with extensions present for local dumps, debugging, or consumers that want them. `to_cq_v0()` emits the pre-change legacy shape for Siyuan until that sync is updated.
- **Inbound validation** of any KU received from a CQ team API SHALL succeed against the vendored schema before ingest.

### 2 — Stolperstein extensions (local + discussed upstream)

These fields are **not** in upstream but are the core of Stolperstein's value. They are stored locally, returned on local `query()` responses, and stripped at the CQ-strict serializer boundary:

- `evidence.severity` enum (`low | medium | high | critical`), affecting ranking tiebreaker and decay floor.
- `context.environment` string, for build/runtime version scoping.
- `kind` enum (`pitfall | workaround | tool-recommendation`) at KU top level, replacing the now-removed `gap-signal`. Emergent `tool-gap-signal` is produced only by aggregation, not by `propose()`.
- `status` state machine (`draft | active | stale | disputed | archived`).
- `staleness_policy` string per KU.
- `related[]` relationship graph.
- `owner_org` plus a `TRUSTED_ORGS` visibility filter (Phase 1 foundation for multi-tenant).
- `provenance.proposer_did`, `provenance.graduation_history`, `provenance.emergent` — our richer version of the single upstream `created_by` string. We emit `proposer_did` as `created_by` for strict CQ output.

All of the above ship in `upstream-issue-draft.md` as candidates for upstream adoption.

### 3 — Migration + data preservation (new capability)

- First-class `src/stolperstein/migrations/` with a `schema_version` table, ordered `mNNNN_*.py` modules, idempotent runner, boot-time auto-apply, `mcp-stolperstein migrate` CLI, and `prune-backups` subcommand.
- Pre-migration `.bak-pre-v<N>` snapshots for any migration that renames/removes/retypes; refuse-overwrite guard; explicit operator cleanup step.
- Migrations: `m0000_ku_id_format_fix` (pad IDs + rewrite refs), `m0001_cq_conformance_rename` (domain→domains, version type, last_confirmed location, context.languages), `m0002_stolperstein_extensions` (adds severity, kind, environment, status, staleness_policy, related), `m0003_provenance_and_org` (install_identity table + private-key file separation + owner_org + proposer_did backfill + graduation_history), `m0004_gap_signal_rename` (gap-signal → tool-gap-signal grandfathering), `m0005_emergent_scaffolding` (query_misses rolling table).

### 4 — Tool surface (BREAKING)

- `propose()` — flat `context_languages[]` / `context_frameworks[]` / `context_environment` / `context_pattern` params + optional `severity` (default `medium`); rejects `kind="gap-signal"` with recovery-hint `McpError`.
- `query()` — severity only as tiebreaker, no `severity_min` filter; applies `TRUSTED_ORGS` visibility; records zero-result misses for emergent detection.
- `confirm()` / `flag()` annotations corrected to `idempotentHint=False`; `McpError(InvalidParams, ...)` replaces bare `ValueError` on lookup misses.
- `status()` default output scoped — `schema_version` / `proposer_did` move behind `debug=True`.
- Docstrings rewritten to reflect the new shape and call out what's strict CQ vs. Stolperstein extension.

### 5 — Provenance + identity (new capability)

- Ed25519 keypair per install → `did:key:z...` identifier for `provenance.proposer_did` (and emitted as `created_by` on the wire).
- **Private key stored OUTSIDE the SQLite DB** — dedicated `/data/stolperstein.key` file (`chmod 600`) or `MCP_STOLPERSTEIN_SIGNING_KEY` env var. DB holds only the public DID (fix for security review H1).
- `propose()` stamps `provenance.proposer_did`; graduation events append to `graduation_history[]` with `{timestamp, target, reviewer_did, agent: true}` marker so automated entries are distinguishable.

### 6 — Claude Code observability hooks (new capability)

Replaces the current metadata-only stub. Three real hooks:

- `UserPromptSubmit` matches **structured** error signals (exception class names, non-zero exit codes, HTTP status strings, traceback markers, `fatal:`/`panic:`/`Error:` prefixes) — NOT bare lowercase conversational words like `error`/`failed`. Per-project pattern override. Injects on `confidence >= 0.5` top-1 match.
- `PostToolUse` (matcher=Bash) fires on non-zero exit OR structured stderr signal; fire-and-forget within 500ms.
- `Stop` nudges `/stolperstein:reflect` only if the session had ≥20 tool-call turns AND ≥1 non-zero bash OR ≥1 `flag()`/`confirm()`.

Injection content (security M1 fix): `action_sanitized = re.sub(r'<[^>]+>', '', action)`; fixed wrapper template `Note from Stolperstein (from your previous {source}): [KU {id}, confidence {c:.2f}] {summary} — Recommended action: {sanitized}`; never wrapped in `<system-reminder>`-shaped tags. Same sanitization applied at team-sync ingest (M3 fix).

Rate limit + dedupe (30s cooldown, 5min per-KU) via `fcntl.flock`-guarded `$FASTMCP_HOME/hooks-state.json`, schema-validated on read.

Bearer-token hygiene (H2 fix): HTTP handler wraps requests in `try/except` that re-raises sanitized errors without the `Authorization` header; `_token` var `del`-eted after request; never passed to `subprocess(env=...)`.

`STOLPERSTEIN_HOOKS_DISABLED` escape hatch documented in SKILL.md (UX-7 fix).

### 7 — Multi-tenant primitives (new capability — foundation only)

- KUs gain `owner_org` (defaults to install DID). Ingested team KUs preserve upstream `owner_org`.
- `TRUSTED_ORGS` env default `"*"` (trust-all, preserves current single-install behavior).
- Diversity weighting counts distinct `owner_org` values.
- Phase 1 is read-filter only. Write-side permissions, per-org UI, and cross-org graduation are Phase 2.

### 8 — Emergent signal detection (new capability — scoped foundation)

- `tool-gap-signal` produced only by aggregation, marked `provenance.emergent=true`.
- Simple count-based miss-clustering: cosine ≥0.8, ≥5 misses, ≥2 sessions, 7-day dedupe.
- Cadence: every N-th `query()` triggers background detection; `STOLPERSTEIN_EMERGENT_DISABLED=true` opts out.
- `status()` surfaces grandfathered vs emergent counts.

### 9 — SKILL.md + agent guidance

- v1 examples (flat `context_*`, severity, no `gap-signal` as proposable kind).
- New "Hooks active in this project" section + "Disabling hooks" escape hatch.
- Note on hook-vs-tool dual channel: hook injections are rate-limited nudges; `query()` returns full KU.
- Note on what's strict-CQ and what's a Stolperstein extension, so agents reading SKILL.md understand the portability boundary.

### 10 — Upstream engagement (new, non-code)

File `upstream-issue-draft.md` (already drafted in this change folder) on `mozilla-ai/cq` proposing the extensions we're shipping. Tracked as part of the change so the relationship between our code and their protocol is visible. Link lands in cdit-works.de positioning page once the issue is live.

## Capabilities

### New Capabilities

- `data-migration`: Versioned, idempotent SQLite migration framework with pre-migration snapshots, CLI entrypoint, and prune-backups subcommand. Splits private-key material OUT of the DB file.
- `claude-hooks`: Real Claude Code hook integration (UserPromptSubmit, PostToolUse Bash, Stop). Owns rate limiting, dedupe, action-field sanitization, temporal qualification on injections, and the disable surface.
- `emergent-signals`: First-class aggregation of `tool-gap-signal` KUs from query-miss patterns, marked `provenance.emergent=true`. Foundation for the hivemind's "things nobody asked but the agents keep hitting."
- `org-boundaries`: Per-KU `owner_org` field and `TRUSTED_ORGS` visibility filter. Foundation for multi-tenant cross-department data flow. Phase 1 adds the field and default-trust; Phase 2 tightens.

### Modified Capabilities

- `cq-interop`: Wire format conforms strictly to upstream `knowledge_unit.json`. All Stolperstein extensions (severity, kind, environment, status, related, staleness_policy, rich provenance, owner_org) are **local-only** until/unless adopted upstream. Two serializers: strict and rich. Inbound validation enforced. **Ingest path sanitizes `summary`/`detail`/`action`** to close prompt-injection vector via team sync.
- `ku-lifecycle`: Provenance recorded on every mutation; `gap-signal` is emergent-only; `superseded_by` top-level (matches upstream); critical-severity raises decay floor; new `owner_org` carried through lifecycle.
- `knowledge-capture`: `propose()` takes flat `context_*` params + optional `severity`, rejects `gap-signal` with recovery-hint error, stamps `provenance.proposer_did` + `owner_org`. `confirm()`/`flag()` use `McpError` + honest annotations. `status()` default output scoped.
- `knowledge-retrieval`: Hybrid rank keeps severity as tiebreaker, drops `severity_min` filter, applies `owner_org` visibility filter. Embedding input extended with `context.pattern`.
- `claude-code-integration`: SKILL.md reflects new shape + documents hook behavior + disable hatch + strict-vs-extension boundary.

## Impact

- **Code**: `models.py` (extension-aware Pydantic with rich/strict serializers), `store.py` (schema + visibility filter + rank), `server.py` (tool signatures + docstrings + McpError), `confidence.py` (severity-aware floor, distinct-org diversity), `reflect.py` (returns flat context + severity), new `migrations/`, new `provenance.py`, new `emergent.py`, new `plugin/stolperstein/hooks/handlers/*`.
- **Data**: All existing KUs migrate via `m0000` → `m0005`; pre-migration snapshot preserved; ID format normalized; all existing cross-references rewritten in the same transaction; `owner_org` backfilled to local install DID.
- **Filesystem**: New `/data/stolperstein.key` file (private key), documented as sensitive.
- **APIs / MCP tool surface**: Breaking on `propose()` / `query()` / `status()` / `flag()` / `confirm()` responses (new shape, new errors). Tool consumers must update; SKILL.md and bundled plugin do.
- **Plugin**: `hooks.json` becomes a real manifest; three Python handlers under `plugin/stolperstein/hooks/handlers/`; SKILL.md rewritten.
- **Tests**: `test_cq_schema.py` pins real upstream schema; validates both strict and rich serializers; new `test_migrations.py`, `test_hooks.py` (including sanitization cases), `test_provenance.py`, `test_emergent.py`, `test_org_boundaries.py`.
- **Dependencies**: `cryptography` (Ed25519, already transitively present), `jsonschema` (dev group).
- **Deployment**: Komodo redeploy triggers migration chain; operator checklist adds volume snapshot, post-deploy verify, `prune-backups` cleanup.
- **Downstream**: Siyuan sync + CQ team sync re-serialize; Siyuan gets the `CQ_SIYUAN_SCHEMA_VERSION=0` escape hatch until its follow-up change lands. CQ team sync uses `to_cq_json_strict()`.
- **Upstream**: `upstream-issue-draft.md` filed on `mozilla-ai/cq` proposing extensions for adoption. Linked from cdit-works.de positioning.
- **Strategic**: This change is explicitly **Phase 1 of the machine-readable org layer** (CDI-999). Phase 2 (enforceable org boundaries, selective graduation UX, richer emergent aggregation) will land as a follow-up once Phase 1 proves the shape.
