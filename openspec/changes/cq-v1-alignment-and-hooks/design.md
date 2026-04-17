## Context

Stolperstein v0.1 shipped 2026-04-09 as a CQ-compatible local node. Two strategic forces now reshape its ceiling:

1. Upstream `mozilla-ai/cq` is iterating quickly (last push 2026-04-16): new `context`, `evidence.severity`, DID-based `provenance`, `tool-gap-signal` emergent-only. Drift breaks the interop we sell.
2. Casey reframed the project from "personal knowledge base" to "atomic data layer for the machine-readable org layer that replaces status meetings" (see `proposal.md`, CDI-999). This change is now Phase 1 of that larger ambition, not a personal-tool polish pass.

Two operational constraints force us to get the foundation right in one change rather than iteratively:

- Existing KUs in the production `stolperstein-data` Docker volume must survive any schema migration intact. `store._init_db` today is CREATE-IF-NOT-EXISTS-only — no versioning, no snapshot, no migrations. The first breaking migration is now.
- A four-agent review (ux-auditor, mcp-tool-reviewer, security-auditor, sharp-business-strategist) surfaced issues that are cheap to fix in the same change and catastrophic to ship past. We fold them in rather than queue a follow-up cleanup.

Stakeholders: Casey (solo operator + consulting owner), future Mittelstand consulting prospects who will see this as the reference implementation of the positioning, downstream Siyuan sync, future CQ team/global tier consumers, and future org-scale deployments where KUs cross department boundaries.

## Goals / Non-Goals

**Goals:**

- Every existing KU survives the upgrade — no data loss, confidence / confirmations / relationship graph intact.
- Round-trip conformance against pinned `mozilla-ai/cq` v1 `knowledge-unit.schema.json`.
- Claude Code agents receive proactive `query()` on real error signals (not conversational English) and proactive `reflect()` offers after substantive sessions — with rate-limited, temporally-qualified, injection-safe delivery.
- Schema versioning becomes a first-class concern so future CQ drift and future org-layer expansion can land as additive migrations, not rewrites.
- Per-install Ed25519 `did:key` identity, with the private key stored OUT of the DB, usable for `provenance.proposer_did` stamping and eventual inter-install trust decisions.
- Multi-tenant primitives (`owner_org`, `TRUSTED_ORGS`) land as foundation even though enforceable boundaries are deferred. Adding the field to the data model now is cheap; retrofitting later is expensive.
- Emergent-signal capability scaffolded as a real module (not an open question) so `tool-gap-signal` aggregation can be iterated without a structural refactor.
- Security review fixes (private-key separation, action-field sanitization at hook injection AND team-sync ingest, honest tool annotations, Mcp-shaped errors) land atomically.

**Non-Goals:**

- Enforceable cross-org permissions (visibility rules exist but default-trust preserves current behavior — Phase 2 tightens).
- Rich emergent-aggregation heuristics. Phase 1 ships count-based miss-clustering; ML clustering / LLM summarization of emergent clusters is Phase 2.
- Human-facing review UI for graduation. `graduation_history` is recorded passively; explicit graduation API stays as today.
- Full W3C DID document resolution. `did:key:z...` is an opaque identifier; no DID registry, no resolver.
- Backfilling `context_*` fields by re-inferring from existing summaries. Migration sets them `NULL`; future `confirm()` or a cleanup tool fills them on touch.
- Reworking Siyuan / CQ-team sync protocols. Only payload shape changes; HTTP semantics unchanged.
- Billing, tenancy provisioning, and UX for "onboarding an org" — the wedge product the positioning implies is a consulting engagement, not a SaaS, so these don't exist yet.

## Decisions

### 1. Schema shape: flat columns, nested Pydantic

**Chosen:** SQLite keeps flat columns (`context_language`, `context_environment`, etc.); JSON columns only for actual arrays/objects (`context_frameworks`, `contributing_orgs`, `related`, `graduation_history`). Pydantic presents the nested CQ shape (`insight`, `context`, `evidence`, `provenance`) in-memory and on-wire.

**MCP tool signatures use the flat form too** (`context_language: str | None = None`, etc.) — the review surfaced that LLMs handle flat params significantly better than nested objects. Internal model assembles the `Context` object from the flat params.

**Why:** Existing FTS5/vec0 virtual tables reference `knowledge_units.rowid`; normalization would add joins on every read. Nested-on-wire was the original proposal; flattening for the MCP surface is a straight LLM-ergonomics win with zero storage cost.

**Rejected:** Fully normalized (4x join cost, migrations harder); single `payload JSON` blob (breaks indexable `confidence`/`status`/`severity`); nested in MCP schema (LLM ergonomics regression).

### 2. Migration framework — in-repo, not Alembic

**Chosen:** `src/stolperstein/migrations/__init__.py` with a registry; `mNNNN_<slug>.py` modules each exposing `version: int` and `up(conn) -> None`; single-row `schema_version` table; runner invoked at the head of `_get_db()` inside a transaction.

CLI: `mcp-stolperstein migrate [--db-path ...]`. Companion: `mcp-stolperstein prune-backups --confirm` to clean `.bak-pre-v*` files (review M2 fix; operator-visible rather than auto-cleaned).

**Why:** Alembic's ORM bias fights raw `sqlite3` + `sqlite_vec.load`. Expected lifetime migration count is small (<20) and linear. 50-line runner beats a framework dep.

**Pre-migration snapshots:** for migrations flagged `breaking: True` (renames, drops, retypes) — not for pure additions. `.bak-pre-v<N>` written via file copy; runner refuses to overwrite an existing backup (forces operator intervention, avoids silently clobbering a prior aborted migration). Snapshots preserved until an operator prunes them.

### 3. Private-key separation from data DB (review H1)

**Chosen:** Private key stored in `/data/stolperstein.key` (`chmod 600`, `chown mcp:mcp`) OR injected at boot via `MCP_STOLPERSTEIN_SIGNING_KEY` (base64-encoded) env var. The SQLite `install_identity` table holds only the `did` string and the public key bytes.

**Migration behavior:** `m0002_provenance` generates the keypair, writes public key + DID to `install_identity`, writes private key to the separate file with restrictive perms, never writes the private key into any `.bak` backup.

**Why:** Docker volume backups, `docker cp`, misconfigured mounts all expose the data DB. Co-locating the signing key means any DB leak is a signing-key leak — and signing-key compromise lets an attacker forge `proposer_did` attribution, destroying the audit trail the DID exists to provide. Separation means DB leaks preserve signing integrity.

**Rejected:** Env-var-only (loses across container recreation if the operator forgets to set it — DID rotates, provenance chain breaks); HSM (overkill for a solo-operator tool); keep in DB with `chmod 600` (insufficient per H1).

### 4. `last_confirmed` → `last_confirmed_at` and `superseded_by` hoist

**Chosen:** Additive first (new column), backfill from old, drop old — all in `m0001`. For `superseded_by`: scan `related[]` JSON for entries with `type="superseded_by"`, move the first `target_id` into the new top-level column, strip those entries from the array. If multiple exist (shouldn't — supersedence is 1:1 per CQ spec): keep newest by timestamp, log the rest.

**Why:** CQ v1 validation requires these names/positions; partial rename keeps FTS5 content linkage simpler via temp-table swap for the drop.

### 5. `gap-signal` deprecation with grandfathering

**Chosen:** `propose(kind="gap-signal")` returns an `McpError(InvalidParams, ...)` with a specific, actionable message (review UX-2 fix): `"kind 'gap-signal' is no longer proposable in CQ v1. Tool gaps are detected automatically from query-miss patterns. To capture this insight, use kind='workaround' or kind='pitfall' and describe the gap in the detail field."`

Migration `m0003` rewrites existing `kind='gap-signal'` rows to `kind='tool-gap-signal'` with `provenance.emergent=false` (grandfathered). Emergent-aggregation job (see Decision 9) sets `provenance.emergent=true` for its own contributions, distinguishing them from migrated rows.

**Why:** CQ says emergent-only; nuking user data for a taxonomy rename is hostile; grandfathering is cheap + auditable.

### 6. DID generation and provenance

**Chosen:** Ed25519 keypair via `cryptography` (stdlib-adjacent, already transitively present via `sentence-transformers`). `did:key:z...` derived via multicodec + multibase on the public key. One DID per install, never auto-rotated.

`provenance.proposer_did` stamped on every `propose()`. `graduation_history[]` appended only on explicit graduation events (not on `confirm()`), each entry: `{timestamp, target, reviewer_did, agent: true}` — the `agent: true` marker (review L2 fix) distinguishes automated from human-initiated graduation without requiring DID-document infrastructure.

**Rejected:** UUIDv4 per install (not CQ-shaped, no cryptographic attribution); `did:web` (requires hosting `.well-known/did.json`); per-session DIDs (inflates `contributing_orgs` cardinality, breaks diversity-weighted confidence math).

### 7. Claude Code hook wiring — observability entry point

**Chosen:** Real `hooks.json` with three hooks; Python handlers in `plugin/stolperstein/hooks/handlers/` (stdlib + local `stolperstein` package only).

**Hook 1 — `UserPromptSubmit`**: matches prompt against **structured error signals**, not conversational English. Signals:
- Capitalized exception class names (`TypeError`, `NullPointerException`, `FileNotFoundError`);
- Non-zero exit-code mentions (`exit code 1`, `exited with 127`);
- HTTP status strings (`500 Internal Server Error`, `404`);
- Traceback markers (`Traceback (most recent call last):`, `at ... (... line \d+)`);
- Explicit error-tag mentions (`fatal:`, `panic:`, `Error: `).

Bare lowercase words (`error`, `failed`, `denied`, `timeout`) removed from the default set (review UX-1 fix). Per-project pattern override via `.claude/settings.json`. Threshold: only injects on `confidence >= 0.5` with top-1 match.

**Hook 2 — `PostToolUse` (matcher=Bash)**: inspects exit code + stderr. Fires on non-zero exit OR structured-signal match in stderr. 4KB stderr cap; fire-and-forget (500ms budget, returns tool response immediately, injection lands next agent turn).

**Hook 3 — `Stop`**: nudges `/stolperstein:reflect` only if the session had ≥20 tool-call turns AND at least one non-zero-exit bash call OR one `flag()`/`confirm()` call (review UX-6 fix). Trivial exploratory sessions don't trigger.

**Injection content** (review UX-3 + security M1 fix):
- Temporal qualifier: `Note from Stolperstein (from your previous Bash error):`
- Body: `[KU {id}, confidence {c:.2f}] {summary} — Recommended action: {action_sanitized}`
- `action_sanitized = re.sub(r'<[^>]+>', '', action)` — strips all angle-bracket content before injection. Applied identically in all three handlers and at team-sync ingest time.
- Fixed wrapper template; never wrapped in `<system-reminder>`-shaped tags (the agent's host model may elevate those).

**Rate limit + dedupe:** `fcntl.flock`-guarded JSON state file at `$FASTMCP_HOME/hooks-state.json`. Cooldown 30s global per hook type; per-KU dedupe 5min. Validated schema on read (review L1 fix); reject-and-reset on structural violation.

**Bearer token hygiene** (review H2 fix): HTTP handler wraps request in `try/except` that re-raises sanitized errors not including the `Authorization` header; `_token` local explicitly `del`-eted after request; never passed to `subprocess(env=...)`.

### 8. `query()` parameter discipline

**Chosen:** No `severity_min` filter parameter. Severity remains a tiebreaker in ranking but is not a caller-exposed filter (review MCP-2 fix). Rationale: callers don't know what severity values exist in the store; exposing the filter adds decision-cost with near-zero payoff.

Embedding input extended to include `context.pattern` when present, so pattern-tagged KUs cluster better in semantic space. Other `context_*` fields NOT added to embedding input — too sparse, would dilute signal.

### 9. Emergent signals as first-class capability

**Chosen:** New `src/stolperstein/emergent.py` module running a simple periodic aggregation (default: on every 10th `query()` call, or via `mcp-stolperstein detect-emergent` CLI):

1. Scan recent `query()` calls that returned 0 results above `confidence_min=0.3` (stored in a small `query_misses` rolling table, TTL 30 days).
2. Cluster misses by embedding similarity (cosine ≥ 0.8) into bins.
3. For any bin with ≥5 misses from ≥2 distinct sessions: emit a `tool-gap-signal` KU with `provenance.emergent=true`, `kind='tool-gap-signal'`, summary + detail extracted from representative miss queries.

Simple. Not ML-sophisticated. The point is that the capability EXISTS so later changes can swap the algorithm without schema/tool churn.

**Why first-class now:** Casey's strategic framing (proposal) makes emergent signals *the* feature that justifies the org-layer thesis — things nobody asked but the agents keep hitting. Leaving it as an open question signals it's deprioritizable; it isn't.

### 10. Multi-tenant primitives: `owner_org` + `TRUSTED_ORGS`

**Chosen:** Add `owner_org TEXT NOT NULL DEFAULT <install-did>` column in `m0002`. Set on every `propose()` to the install's DID. Set on ingest from team sync to the upstream KU's `owner_org` (preserved, not rewritten).

Add a `TRUSTED_ORGS` env var (comma-separated DIDs; default: `*` meaning trust-all, which is current behavior). `query()` implicitly filters: include rows where `owner_org == <local-did>` OR `owner_org in TRUSTED_ORGS` OR `TRUSTED_ORGS == '*'`.

**Why foundation-only in Phase 1:** enforcing org boundaries requires a Phase 2 permissions model (per-org read/propose/graduate rights, inheritance, UI). But adding the column now is a cheap migration; retrofitting later means rewriting every existing KU's visibility. Default-trust preserves behavior for solo-operator use.

### 11. `status()` default output scope (review MCP-3 fix)

**Chosen:** Default `status()` returns: `total`, `by_status`, `confidence_distribution`, `staleness`, `tool_gap_signals` (grandfathered vs emergent). Debug-gated behind `status(debug=True)`: `schema_version`, `proposer_did`, migration history, hook state-file summary, `query_misses` rolling-window stats. Default keeps tokens tight; ops visibility is one flag away.

### 12. CQ conformance test via vendored schema

**Chosen:** Vendor `mozilla-ai/cq`'s `knowledge-unit.schema.json` at a pinned SHA under `tests/fixtures/cq/`, with `CQ_SCHEMA_REF.md` recording the SHA + source URL. `jsonschema` dev dep asserts every `to_cq_json()` validates. `make sync-cq-schema` updates the pin with a conscious catch-up moment.

### 13. Dual-shape serialization escape hatch

**Chosen:** `to_cq_json()` → v1. `to_cq_v0()` → legacy. Opt-in per consumer (`CQ_SIYUAN_SCHEMA_VERSION=0`). Default v1. Escape hatch is explicitly temporary — removed when Siyuan sync is updated in a follow-up change.

## Risks / Trade-offs

- **[Migration on production DB corrupts rows]** → `.bak-pre-v<N>` snapshot every breaking migration + refuse-to-overwrite; integration test full chain against `tests/fixtures/migration_v0.db`.
- **[`stolperstein.key` gets copied into Docker volume backups]** → document explicit exclusion in deploy notes; Komodo deploy step lists it as a sensitive file; key loss = new DID on next boot (provenance chain breaks, but data intact).
- **[Hook latency adds perceptible delay]** → fire-and-forget + 500ms budget; handler terminates before tool response returns; measured on CI fixture.
- **[Rate-limit state file corrupts under concurrent writes]** → `fcntl.flock` + tmp-file-then-rename; schema validation on read; fall back to no-injection on contention.
- **[Emergent-signal aggregation false-positives into noise]** → conservative thresholds (≥5 misses, ≥2 sessions, cosine ≥0.8); `flag()` a bad emergent KU archives it; emergent count visible in `status()` for operator to eyeball.
- **[Default-trust `TRUSTED_ORGS='*'` becomes dangerous at multi-tenant scale]** → Phase 2 required before any multi-org deployment; Phase 1 single-install default is correct; document as known-limitation in deploy notes.
- **[CQ upstream drifts again before we archive]** → pinned schema fixture + scripted sync makes next realignment mechanical.
- **[Action-field sanitization strips legitimate HTML examples from KUs]** → accepted: KUs are agent-to-agent communication; HTML examples belong in `detail`, not `action`. Document in SKILL.md that `action` must be plain imperative text.
- **[Users bypass hook rate-limit via manual `query()` calls and flood]** → accepted: manual is intentional, rate limit is only for auto-fired handlers.
- **[CDiT positioning (CDI-999) doesn't validate in 30 days and this work becomes tech orphaned]** → accepted risk: the technical foundation work (CQ v1, migrations, hooks, security) is load-bearing regardless of positioning outcome.

## Migration Plan

1. **Pre-deploy**: tag current prod commit; snapshot `stolperstein-data` volume to `stolperstein-data-pre-v1`.
2. **Deploy**: Komodo re-deploys container. On first boot:
   - runner checks `schema_version` (NULL = v0);
   - copies `stolperstein.db` → `stolperstein.db.bak-pre-v1`;
   - applies `m0001_cq_v1_layout` (flat context, severity, last_confirmed_at, superseded_by top-level);
   - applies `m0002_provenance_and_org` (install_identity with public key only, `/data/stolperstein.key` with private key, adds `proposer_did`/`graduation_history`/`provenance_emergent`/`owner_org`, backfills);
   - applies `m0003_gap_signal_rename` (`gap-signal` → `tool-gap-signal` with `emergent=false`);
   - applies `m0004_emergent_scaffolding` (adds `query_misses` rolling table);
   - updates `schema_version=4`.
3. **Post-deploy verify**:
   - `mcp-stolperstein status --debug` shows `schema_version=4`, KU total unchanged, no rows with `proposer_did IS NULL`, no rows with `owner_org IS NULL`, `tool_gap_signals.grandfathered` equals the pre-migration `gap-signal` count.
   - Manual end-to-end: connect Claude Code, trigger a real error, observe temporal-qualified hook injection; run `/stolperstein:reflect` at session end.
4. **Post-migration cleanup**: operator runs `mcp-stolperstein prune-backups --confirm` after 48 hours of clean operation to remove `.bak-pre-v1`.
5. **Rollback**: stop container, restore from `stolperstein.db.bak-pre-v1` + previous `stolperstein.key` backup, redeploy previous image tag. If the key is lost, a new keypair is generated on re-migration — all subsequent KUs get a different DID, but existing KU content is intact. The audit chain breaks at the rollback point.

## Open Questions

- **Emergent aggregation cadence**: every 10th query() is a rough default. Should it be time-based (hourly) or event-based (query-miss count threshold)? Current draft: event-based with `EMERGENT_DETECT_EVERY_N=10` env override.
- **`graduation_history` on team-sync import**: when we ingest a team KU, do we append an entry reflecting the import? Current draft: no — imports are passive and the upstream history is preserved as-is.
- **Hook handler packaging**: ship Python handlers (requires `python3` on PATH) or pre-built shell scripts calling `curl`? Current draft: Python, `#!/usr/bin/env python3`, stdlib-only imports, documented PATH requirement.
- **Phase 2 permissions model**: ACL-per-org, role-based, capability-based? Deferred to the follow-up change; this change only lays the `owner_org` field + `TRUSTED_ORGS` default-trust so Phase 2 has a column to attach to.
- **CDiT consulting engagement shape** (tracked in CDI-999): 6-week vs 12-week, fixed-price vs T&M, first-client profile. Not a technical design question for this change, but the answer shapes what "good" looks like for the Phase 2 scope.
