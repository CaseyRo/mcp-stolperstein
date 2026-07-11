---
topic: cq-interop-and-schema
last_compiled: 2026-07-07
---

# CQ Interop & Schema

## Summary [coverage: high — 5 sources]

Stolperstein's Knowledge Unit (KU) model is a **superset** of Mozilla AI's upstream `mozilla-ai/cq` `schema/knowledge_unit.json`. The interop contract is *conform-plus-extend*: everything upstream defines is emitted exactly as upstream expects, and everything Stolperstein needs beyond that rides along as documented, namespaced **extensions**.

Two serializers implement this split in `src/stolperstein/models.py`:

- **`to_cq_json_strict()`** — emits the upstream-valid wire shape. Stolperstein extension fields are carried inside the upstream **`extensions` slot** under `stolperstein:*` keys (e.g. `evidence.severity` → `extensions["stolperstein:severity"]`). Validated on every commit against a vendored, pinned copy of the upstream schema in `tests/fixtures/cq/knowledge_unit.json`.
- **`to_cq_json_rich()`** — emits the full internal superset with every extension as a first-class field (`evidence.severity`, top-level `kind`, etc.), *no* `extensions` object. Used for local dumps, debugging, and extension-aware consumers.

A third serializer, `to_cq_v0()`, emits the pre-alignment legacy shape for the Siyuan-sync transition, gated by `CQ_SIYUAN_SCHEMA_VERSION=0`.

The canonical extension registry is `docs/cq-extensions.md`; every `stolperstein:*` key on the wire must appear there. Wire compatibility across schema changes is enforced by the versioned migration framework under `src/stolperstein/migrations/`. Upstream engagement runs through discussion [#286](https://github.com/mozilla-ai/cq/discussions/286), scoping issue [#406](https://github.com/mozilla-ai/cq/issues/406), and the slot-merge PR [#453](https://github.com/mozilla-ai/cq/pull/453).

## Rationale & Context [coverage: high — 6 sources]

**Why conform-plus-extend rather than fork.** Stolperstein is an independent, cq-compatible local node aimed at single-operator and small-team (German KMU / Mittelstand) deployments, part of CDiT's "machine-readable org layer" thrust. Silently forking the schema would break interop with any other cq consumer (team API, global tier, external validators) and forfeit the whole point of a shared protocol. The chosen posture is: stay strictly valid on the wire, surface the gaps upstream rather than diverge quietly.

**The upstream-drift / validation problem.** The strict serializer exists precisely so that the wire shape can be validated against a *pinned* upstream schema rather than a moving `main`. Inbound payloads (from a team API, future import CLI) are validated against the vendored schema **before** any storage or transformation, and rejected on any failure — no partial ingest. This makes upstream drift a controlled, single-commit event (re-vendor the pin, re-run the full conformance corpus) instead of a silent runtime break.

**The `additionalProperties: false` blocker.** The original reason for a strict/rich split was that upstream's schema was `additionalProperties: false` *everywhere*, so any Stolperstein field on the wire would fail validation. Strict mode therefore *stripped* every extension; rich mode kept them but was, by design, invalid against the upstream schema. This was flagged upstream as "the tightest blocker for experimentation." Stolperstein's scoping issue [#406](https://github.com/mozilla-ai/cq/issues/406) proposed an explicit `extensions` object rather than relaxing to `additionalProperties: true`; upstream merged it in [#453](https://github.com/mozilla-ai/cq/pull/453) on 2026-06-23. That lifted the blocker: strict output can now legally *carry* extensions instead of dropping them, so downstream consumers stop losing `severity`, `kind`, and provenance data on graduation.

**Extensions vs. core promotion are orthogonal.** Upstream's per-field verdicts (declined / deferred / etc., from the 2026-04-28 maintainer response to #286) govern whether a field is promoted into the **core** schema. They do *not* govern slot carriage — any documented field may ride the `extensions` slot regardless of its core-promotion verdict.

## Requirements & Behavior [coverage: high — 4 sources]

**Wire format SHALL conform to a pinned upstream schema.** All KUs emitted to any external CQ consumer SHALL conform exactly to `mozilla-ai/cq` `schema/knowledge_unit.json` as vendored at a pinned SHA in `tests/fixtures/cq/`. The pin SHALL be a post-#453 revision defining the optional top-level `extensions` object with keys matching `^[a-z0-9][a-z0-9_-]*:\S+$`.

**Two serializers SHALL exist:**
- `to_cq_json_strict()` — upstream-valid; extensions emitted in the `extensions` slot under `stolperstein:*` keys (no longer stripped).
- `to_cq_json_rich()` — internal superset with extensions as first-class fields; no `extensions` object.

**Strict-mode core field mapping** (unchanged by the slot adoption):
- `domains[]` → upstream `domains[]`
- `version` → upstream `version: 1` (integer)
- top-level `last_confirmed_at` column → upstream `evidence.last_confirmed`
- top-level `superseded_by` → upstream `superseded_by`
- `provenance.proposer_did` → upstream `created_by`

**Strict-mode extension mapping** (all under the top-level `extensions` object):
- `evidence.severity` → `stolperstein:severity` (string; always present)
- `evidence.contributing_orgs` → `stolperstein:contributing_orgs` (array; omitted when empty)
- `context.environment` → `stolperstein:environment` (string; omitted when null)
- top-level `kind` → `stolperstein:kind` (string; always present)
- top-level `status` → `stolperstein:status` (string; always present)
- top-level `staleness_policy` → `stolperstein:staleness_policy` (string; always present)
- top-level `related[]` → `stolperstein:related` (array of `{type, target_id}`; omitted when empty)
- top-level `owner_org` → `stolperstein:owner_org` (string, DID; always present)
- `provenance.emergent` → `stolperstein:emergent` (boolean; omitted when null)

**Extension key format and emptiness rules.** Every emitted key SHALL match `^[a-z0-9][a-z0-9_-]*:\S+$`; the wire key per field is `stolperstein:<field>`. Null/empty values emit no key. The entire `extensions` object SHALL be omitted when no extension value is present (a hypothetical zero-extension KU). In practice `severity`, `kind`, `status`, `staleness_policy`, and `owner_org` always have values, so a real KU always produces at least those five keys. Internal-only fields (`last_queried_at`, `graduated_to_team`) SHALL remain absent from strict output entirely.

**Guaranteed absences.** No extension field name (`severity`, `kind`, `status`, `owner_org`, `staleness_policy`, `related`, `environment`, `contributing_orgs`, `emergent`) SHALL appear at top level or inside `context`/`evidence`/`provenance` sub-objects — only inside `extensions`. This is asserted in `tests/test_cq_schema.py` on every commit.

**Flag-reason mapping (pre-slot behavior, retained for the wire).** A local flag with reason `dangerous` maps to upstream reason `incorrect`, with the `dangerous` marker preserved only in a local extension. `superseded` is never a wire flag — always expressed as top-level `superseded_by`.

**Rich serializer would NOT validate strict.** `to_cq_json_rich()` output validated against the upstream schema fails by design (first-class extension fields are invalid outside the slot) — expected and intentional.

**Ingest sanitization.** `insight.summary` / `insight.detail` / `insight.action` from external sources SHALL be sanitized before storage: strip all angle-bracket content (`re.sub(r'<[^>]+>', '', value)`), bound lengths (`summary` ≤ 280, `detail` ≤ 8000, `action` ≤ 2000; reject oversize), applied identically inbound and outbound, idempotently.

**Migration behavior.** Schema changes SHALL flow through versioned migration modules (`mNNNN_<slug>.py`, each declaring `version: int`, `breaking: bool`, and `up(conn)`), applied in ascending order in one transaction each, updating a single-row `schema_version` table. Before any `breaking=True` migration the runner SHALL snapshot the DB to `<db_path>.bak-pre-v<target>` and SHALL refuse to overwrite an existing snapshot. Migrations SHALL NOT silently drop extension fields.

## Design & Architecture [coverage: high — 5 sources]

**Serialization lives in one place.** All three shapes (`_strict`, `_rich`, `_v0`) are methods on the `KnowledgeUnit` Pydantic model in `src/stolperstein/models.py`. The 2026-07 dead-code cleanup removed the sync clients, `flags`, and `graduation_history` from the live model, leaving the strict serializer small enough that adopting the slot touched essentially one method plus fixtures and docs.

**Extensions-slot design decisions** (from the adopt-cq-extensions-slot design doc):
1. **Namespace `stolperstein`** — not `st` or `cdit`; readable, unambiguous, matches the repo/plugin name, and satisfies the key-format constraint.
2. **Flat keys, JSON-native values** — `stolperstein:severity` → `"high"`, `stolperstein:related` → array of `{type, target_id}` dicts. A single `stolperstein:meta` blob was rejected: per-field keys let a consumer pick fields without parsing a nested contract, and mirror how the registry documents each field.
3. **Omit-when-empty** — null/empty values produce no key; a zero-extension KU omits the object. Keeps payloads minimal and makes "no extensions" indistinguishable from a pre-slot producer.
4. **Re-vendor as a straight copy of upstream `main`** (post-#453 SHA recorded in `tests/fixtures/cq/CQ_SCHEMA_REF.md`), never a hand-edit — the fixture is the oracle; hand-edits drift.
5. **Registry framing** — rows keep their #286 verdicts (which govern *core* promotion) and gain a note that each field now rides the slot on the wire; the old "extensions must never leak through strict" rule was rewritten to "extensions must only appear inside the `extensions` slot."

**No inbound extension handling (yet).** The slot adoption explicitly did *not* add handling for *foreign* `extensions` — no sync path exists post-cleanup — deferred to Phase-2 graduation. It also changed no DB schema, no MCP tool signatures, and no hooks; the wire change is purely additive (a new optional key), so existing strict consumers keep working. Rollback is a single commit revert.

**Migration framework.** `store._init_baseline()` creates v0-shape tables on a fresh install, then the runner applies the ordered `mNNNN_*` modules. Migration runs as the first action inside `_get_db()` on server boot, so a single deploy brings the DB forward. The v0→v1 chain `m0000`→`m0005` transforms an existing DB without loss:
- **`m0000_ku_id_format_fix`** (breaking) — pad legacy short-hex ids to `ku_ + <32 hex>`; rewrite `related[].target_id`, `superseded_by`, FTS5, and `ku_embeddings` references.
- **`m0001_cq_conformance_rename`** (breaking) — rename `domain` → `domains`; add `last_confirmed_at`, `superseded_by`, `context_languages`, `context_frameworks`, `context_pattern`; migrate `superseded_by`-typed `related` edges into the new column; drop `last_confirmed`.
- **`m0002_stolperstein_extensions`** (breaking) — add extension columns not in upstream CQ: `evidence_severity` (default `medium`), `context_environment`; `kind`/`status`/`staleness_policy`/`related` already existed from v0.
- **`m0003_provenance_and_org`** (breaking) — create `install_identity` (`did`, `public_key`, `created_at` — **no** private-key column; the Ed25519 private key lives at `/data/stolperstein.key` mode `0o600` or in `MCP_STOLPERSTEIN_SIGNING_KEY`); add `proposer_did`, `graduation_history`, `provenance_emergent`, `owner_org`; backfill `proposer_did` and `owner_org` to the install DID.
- **`m0004_gap_signal_rename`** (additive) — `kind='gap-signal'` → `'tool-gap-signal'`, set `provenance_emergent=0` (grandfathered).
- **`m0005_emergent_scaffolding`** (additive) — create `query_misses` table + `created_at` index for emergent detection.

Operator entrypoints: `mcp-stolperstein migrate` (runs the runner, prints `from → to`, refuses `--db-path` outside `/data/`) and `mcp-stolperstein prune-backups [--confirm]` (never auto-cleans snapshots).

## Schema & Interop [coverage: high — 4 sources]

**The `extensions` slot (#453).** An optional top-level object on `KnowledgeUnit`; keys must match `^[a-z0-9][a-z0-9_-]*:\S+$`; **max 20 properties**; values carry **no protocol semantics** and are validated in the Go/Python SDKs and CLI. It was deliberately scoped *outside* any signing envelope. Stolperstein uses 9 keys for its single implementation.

**The extension registry** (`docs/cq-extensions.md`) — every `stolperstein:*` key with its upstream verdict:

| Field (internal) | Wire key | Type | Upstream verdict | Purpose |
|---|---|---|---|---|
| `evidence.severity` | `stolperstein:severity` | `low\|medium\|high\|critical` | **declined** | Ranking tiebreaker + decay-floor modifier. Upstream: self-assigned trust is cheap to game; importance should emerge from usage. |
| `evidence.contributing_orgs` | `stolperstein:contributing_orgs` | `array[string]` (DIDs) | **declined** | Diversity-weighted confidence. Upstream: per-KU org arrays are a profile-building vector when joined; compute diversity from confirmation provenance instead. |
| `context.environment` | `stolperstein:environment` | string | **deferred** | Build/runtime scope (`macos`, `cloudflare-workers`, `node-22`). Upstream: fold into `frameworks`; revisit via [#170](https://github.com/mozilla-ai/cq/issues/170) if still noisy. |
| `kind` | `stolperstein:kind` | `pitfall\|workaround\|tool-recommendation` | **declined** | Coarse KU typing. Upstream: derive classification from observed usage, not contributor declaration. |
| `status` | `stolperstein:status` | `draft\|active\|stale\|disputed\|archived` | **stolperstein-specific** | Lifecycle state machine (upstream models lifecycle only via `flags[]`). |
| `staleness_policy` | `stolperstein:staleness_policy` | string | **stolperstein-specific** | Per-KU decay-policy override. |
| `related[]` | `stolperstein:related` | `[{type, target_id}]` | **stolperstein-specific** | Relationship graph beyond `superseded_by`. |
| `owner_org` | `stolperstein:owner_org` | string (DID) | **stolperstein-specific** | Multi-tenant read filter via `TRUSTED_ORGS` (Phase 1 foundation). Upstream has `tier: local\|private\|public` for a different slice. |
| `provenance.proposer_did` | (→ core `created_by`) | string (DID) | **deferred** | Strict mode emits it as upstream `created_by`; cross-install attribution portability invited as its own thread. |
| `provenance.emergent` | `stolperstein:emergent` | boolean | **stolperstein-specific** | Distinguishes emergent-aggregation `tool-gap-signal` KUs from grandfathered migration artifacts. |

**Removed from the live model.** `provenance.graduation_history` (`array[{timestamp, target, reviewer_did, agent}]`, upstream verdict **declined** — governance belongs in admin tooling) was removed in the 2026-07 cleanup because nothing wrote it (graduation is Phase-2). The `graduation_history` DB column from the provenance migration remains; the field returns with Phase-2 graduation.

**Wire-format rules** (registry, rule set):
1. Adding an extension requires adding its registry row in the same change.
2. When upstream promotes an extension into core, move the row to the (not-yet-created) "accepted" table and emit it as a core field instead of a `stolperstein:*` key.
3. Extensions appear in strict output **only** inside `extensions`, never as first-class properties — enforced by `tests/test_cq_schema.py`.

## Status & Open Questions [coverage: medium — 4 sources]

**Verdict legend** (from the 2026-04-28 maintainer response to #286): *proposed* (filed, awaiting), *accepted* (merged upstream — unblock by re-vendoring and moving the row out), *declined* (decided against on the merits — stays local-only unless reopened), *deferred* (need acknowledged but wanted in a different shape/thread), *stolperstein-specific* (never intended for upstream).

**Current standings:**
- **Accepted / shipped:** the `extensions` slot itself (proposed as #406, merged as #453 on 2026-06-23). No individual *field* has yet been promoted into core, so the "accepted" registry table does not exist yet.
- **Declined for core promotion:** `severity`, `contributing_orgs`, `kind` — remain local-only but now ride the slot on the wire.
- **Deferred:** `context.environment` (revisit via #170), `provenance.proposer_did` (attribution-portability thread invited).
- **Stolperstein-specific (never upstream):** `status`, `staleness_policy`, `related[]`, `owner_org`, `provenance.emergent`.
- **Declined + removed from model:** `graduation_history` (EU AI Act audit-trail thread invited when concrete requirements exist).

**Archive state.** The `adopt-cq-extensions-slot` change is **archived** (`openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/`) with all tasks checked off: re-vendored pin, serializer emission, inverted tests (extensions now asserted *present* under `stolperstein:*` and still schema-valid), key-regex assertion, docs/resource updates, and green `pytest`/`ruff`/`mypy`. Its requirement was synced into the live spec `openspec/specs/cq-interop/spec.md`.

**Pending / open questions:**
- **`maxProperties: 20` headroom.** Comfortable at 9 keys for one implementation, but two or three implementations annotating the same unit (the working-group scenario) would approach the cap. Flagged upstream before it becomes load-bearing.
- **Omit-when-empty wants a spec sentence.** Stolperstein treats key-presence as meaningful; without a documented convention, implementations may diverge (half shipping `"ns:field": null`). Raised as a suggested schema-docs recommendation.
- **Privacy allowlist for outbound extensions.** `owner_org` and `contributing_orgs` are org-identifying signals (the #286 privacy concern). They only ship when someone actually transmits strict payloads, and today **no transmit path exists** post-cleanup. A per-field emit allowlist is deferred to Phase-2 graduation design.
- **The adopter comment for #286** (announcing production slot emission, output validating against pin `cb1f81f`) is drafted but held for Casey's review — not posted autonomously.

## Sources

- [[../../../README]]
- [[../../../docs/cq-extensions]]
- [[../../../openspec/specs/cq-interop/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/cq-interop/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/data-migration/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/upstream-issue-draft]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/cq-interop/spec]]
- [[../../../openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/proposal]]
- [[../../../openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/design]]
- [[../../../openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/tasks]]
- [[../../../openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/specs/cq-interop/spec]]
- [[../../../openspec/changes/archive/2026-07-07-adopt-cq-extensions-slot/upstream-comment-draft]]
