---
topic: knowledge-lifecycle
last_compiled: 2026-07-07
---

# Knowledge Lifecycle

## Summary [coverage: high — 6 sources]

The Knowledge Unit (KU) lifecycle is the spine of mcp-stolperstein: how experiential knowledge is **captured** (`propose`, `reflect`), **retrieved** (`query`), and **matured or retired** through confirm/flag transitions and a confidence score that rises with corroboration and decays with time. Six MCP tools drive it — `query`, `propose`, `confirm`, `flag`, `reflect`, `status` — over a SQLite store combining an FTS5 keyword index and a sqlite-vec vector index for hybrid search.

Every KU carries a `status` (`draft` → `active` → `stale` → `archived`, plus `disputed` off any live state) and a `confidence` float in [0.0, 1.0] that starts at 0.5, moves up with organizationally-diverse confirmations, decays linearly past a staleness threshold, and is capped at 0.5 when disputed. Duplicate proposals (>0.9 cosine to an existing active KU) collapse into a `duplicate_of` reference rather than creating a new entry.

The specs come in two generations. The **stolperstein-mvp-scaffold** specs are the v0 baseline. The **cq-v1-alignment-and-hooks** specs modify that baseline to align the wire shape with Mozilla AI's upstream `cq` v1 schema and to add multi-tenant primitives: flat `context_*` params, an upstream-named `domains` field, severity-as-tiebreaker on query, per-KU `owner_org` provenance, `TRUSTED_ORGS` visibility filtering, emergent-only gap signals, and a top-level `superseded_by` field. This article reflects that evolution: where v0 and v1 differ, v1 is the current behavior.

## Rationale & Context [coverage: medium — 5 sources]

The lifecycle model exists to make agent-captured knowledge **trustworthy over time without human curation**. A raw note from one agent on one project is a weak signal; the same insight confirmed by agents at multiple organizations is a strong one. Three design choices follow from that:

- **Confidence over binary trust.** Instead of "verified / unverified," a KU carries a continuous score so retrieval can rank and callers can gate (`confidence_min`). The score deliberately **weights diversity of confirming sources over raw confirmation count** — three confirmations from three distinct `owner_org` values move confidence more than three from one, so a single loud installation can't inflate its own knowledge.
- **Decay, so stale knowledge fades.** Knowledge about tooling rots (a workaround stops applying after a framework release). Confidence decays linearly after a staleness threshold, and staleness itself is a state transition, so old KUs sink in ranking rather than misleading. The exception is severity: `critical` KUs get a higher decay floor (0.2 vs 0.1) because ignoring a critical pitfall is disproportionately costly even when the KU is old and unconfirmed.
- **Gaps are detected, not proposed.** In v0, `gap-signal` was a proposable `kind`. v1 removes it: tool gaps are emergent aggregate signals mined automatically from query-miss patterns, not something an agent asserts by hand. Proposing `gap-signal` now returns an actionable error pointing the caller to `workaround`/`pitfall`.

The v1 alignment adds the multi-tenant foundation (`owner_org`, `TRUSTED_ORGS`) as **read-filter visibility only, defaulting to trust-all** — the diversity-weighted confidence and cross-org sharing are the payoff, but enforceable write-side org permissions are explicitly out of scope here.

## Requirements & Behavior [coverage: high — 6 sources]

### Capture — `propose`

The `propose` tool SHALL accept required `summary` (≤280 chars), `detail`, `action`, `domains` (array, min 1 element — upstream-conformant name, with `domain` accepted as a silently-promoted alias), and `kind`. In v1 the `kind` enum is `pitfall | workaround | tool-recommendation` (v0 also allowed `gap-signal`). Optional **flat** params: `context_languages`, `context_frameworks`, `context_environment`, `context_pattern`, `severity` (`low|medium|high|critical`, default `medium`), and `staleness_policy`. It returns the created KU with a generated id matching `^ku_[0-9a-f]{32}$`, initial confidence 0.5, status `draft`, `provenance.proposer_did` set to the install DID, `owner_org` set to the same DID, and empty `graduation_history`.

- **WHEN** an agent proposes with `context_languages=["swift"]`, `context_environment="xcode-16"`, `severity="high"` **THEN** the flat params are assembled into a nested `context` object in the response, confidence 0.5, status `draft`, provenance and owner stamped, severity stored.
- **WHEN** an agent proposes with only required fields **THEN** context fields are `null`, severity defaults to `medium`, and provenance/owner are still stamped.
- **WHEN** `kind="gap-signal"` **THEN** the server SHALL raise `McpError(InvalidParams, ...)` naming `gap-signal` as deprecated in CQ v1 and directing the caller to `kind='workaround'` or `kind='pitfall'`.
- **WHEN** a proposed summary has >0.9 cosine similarity to an existing active KU **THEN** the server returns the existing KU's id plus a `duplicate_of` field instead of creating a new entry.

### Capture — `reflect`

The `reflect` tool SHALL accept a free-text session summary and return a ranked list of candidate KUs scored by generalizability ("would this help a different agent on a different project?"). Each candidate carries `generalizability_score`, pre-filled `summary`/`detail`/`action`/`domain`/`kind`, and (v1) best-effort flat `context_*` and `severity`, so the caller passes them straight to `propose()`. `kind` is never `gap-signal`. A summary of only project-specific decisions returns an empty candidates list.

### Retrieval — `query`

The `query` tool SHALL accept `text` (required), optional `domain` filter, optional `confidence_min` (default 0.3), and optional `limit` (default 10). It returns KUs ranked by a weighted combination of FTS5 relevance and sqlite-vec cosine similarity. In v1, `evidence.severity` is a **tiebreaker** at equal combined rank (critical > high > medium > low), and there is **no `severity_min` parameter** — severity gating is client-side. Results carry the full v1 CQ shape (`insight`, `context`, `evidence`, `provenance`, top-level `superseded_by`, `owner_org`).

- **WHEN** two KUs have identical combined rank but differing severity **THEN** the higher-severity KU appears first.
- **WHEN** a domain filter is passed **THEN** only KUs whose `domain` array contains the tag are returned.
- **WHEN** a query matches nothing above `confidence_min` **THEN** the server returns an empty array (not an error) AND records the miss (text, timestamp, embedding) in the `query_misses` rolling table for emergent detection.
- **(v1 visibility)** A KU is visible IF `owner_org == local-install-did` OR `owner_org IN TRUSTED_ORGS` OR `TRUSTED_ORGS == "*"`. `TRUSTED_ORGS` defaults to `"*"` (trust-all). The visibility filter SHALL be applied **before** confidence/severity filtering, so filtered-out KUs never enter the result set.

### Confirm / Flag transitions

`confirm(ku_id)` SHALL increment `confirmations`, update `last_confirmed_at` (v0: `last_confirmed`), recalculate and persist confidence, and (v1) SHALL NOT modify `graduation_history`. On lookup miss it raises `McpError(InvalidParams, "KU not found: {ku_id}. Call query() first to obtain a valid ku_id.")`.

`flag(ku_id, reason, detail?, superseded_by?)` reason enum is `stale | incorrect | superseded | dangerous`:
- **`incorrect` / `dangerous`** → status `disputed`, confidence capped at 0.5, flag reason recorded.
- **`superseded`** → status `archived`; v1 writes the superseding id to the **top-level `superseded_by` column** (v0 instead added a `related` entry of type `superseded_by`).
- On lookup miss, same `McpError(InvalidParams, ...)` recovery hint as confirm.

### State transitions

Each KU has a `status` following `draft → active → stale → archived`, with any non-archived KU able to transition to `disputed`. Transitions: draft→active on first confirmation; active→stale on staleness-threshold breach; stale→active on re-confirmation; active→disputed on flag; disputed→active on sufficient re-confirmations; any→archived on flag `superseded` or manual archive. (v1) Status transitions SHALL NOT change `owner_org`.

### Confidence & staleness

Confidence is a float in [0.0, 1.0]: base 0.5 on creation, adjusted by confirmations **weighted by organizational diversity** (v1: distinct `owner_org` values among contributors; v0: distinct agents/projects), linear temporal decay of 0.01/day past the staleness threshold, and a dispute cap of 0.5. Default decay floor is 0.1; (v1) `evidence.severity=critical` raises the floor to 0.2. Each KU has a `staleness_policy` (default `confirm_or_decay_after_90d`) settable at propose time; a `query` or `status` call evaluates staleness against `last_confirmed_at + threshold` and transitions any newly-stale KUs before returning.

### Status & provenance (v1)

`status(debug=False)` default response is token-frugal: `total`, `by_status`, `confidence_distribution`, `staleness`, and `tool_gap_signals` partitioned into `grandfathered` / `emergent`. `debug=True` additionally surfaces `schema_version`, `proposer_did`, applied migrations, hook state, and `query_misses` stats. Every `propose`/`confirm`/`flag`/graduation event updates provenance; graduation appends `{timestamp, target, reviewer_did, agent: true}` to `graduation_history[]`; `confirm` does not.

## Design & Architecture [coverage: high — 4 sources]

**Hybrid rank.** Retrieval runs two indexes in parallel and combines them: `ku_fts` (FTS5 virtual table over `summary + detail + action`) for keyword relevance, and `ku_embeddings` (sqlite-vec) for cosine similarity. The two scores are combined into a single weighted rank; `evidence.severity` breaks ties. Embeddings are generated at propose time from `summary + " " + detail + " " + action + " " + (context.pattern if present else "")` — other `context_*` fields are deliberately excluded as too sparse to help and likely to dilute the signal. The embedding model is configurable via `CQ_EMBEDDING_MODEL`; if it's unavailable the KU is still created and FTS5-indexed (with a warning) so keyword search keeps working.

**Visibility before ranking.** The `owner_org`/`TRUSTED_ORGS` filter is applied first, so confidence/severity ranking only ever sees visible KUs. This ordering matters for correctness: it prevents a filtered-out org's KU from occupying a result slot or a query miss from being suppressed by an invisible match.

**State machine + confidence recompute.** State transitions and confidence are recomputed on the mutating tool calls (`confirm`, `flag`) and lazily on read (`query`/`status` runs the staleness sweep before returning). Confidence math: start 0.5, add diversity-weighted confirmation lift (count distinct `owner_org` among contributors, not raw count), subtract linear decay of 0.01/day past the staleness threshold clamped to the floor (0.1 default, 0.2 for critical severity), and hard-cap at 0.5 while disputed.

**Dedup.** On propose, the new summary's embedding is compared against active KUs; >0.9 cosine short-circuits creation and returns `duplicate_of`.

**Atomicity & concurrency.** All writes (KU row + FTS + embedding) are atomic within a single transaction. The DB runs in WAL mode so a concurrent `query` sees a consistent snapshot and does not block on a write. Schema changes happen only through registered migrations — the store never edits columns in place.

## Schema & Interop [coverage: high — 4 sources]

Lifecycle state lives across flat columns and JSON columns on `knowledge_units`, plus dedicated tables:

- **Core lifecycle columns:** `status`, `confidence`, `confirmations`, `last_confirmed_at`, `superseded_by` (top-level, set on supersedence — not stored in `related[]`), `evidence_severity`, `context_environment`, `context_pattern`, `owner_org`, `proposer_did`, `provenance_emergent`.
- **JSON columns:** `domains`, `context_languages`, `context_frameworks`, `contributing_orgs`, `related`, `graduation_history`.
- **Supporting tables:** `ku_fts` (FTS5 on summary+detail+action), `ku_embeddings` (sqlite-vec), `schema_version` (single-row), `install_identity` (single-row — DID + public key **only**, never the private key), and `query_misses` (rolling, feeds emergent detection).

Mapping lifecycle fields onto the KU/CQ shape: `severity` sits under `evidence.severity` (a Stolperfalle extension used for the query tiebreaker and the critical decay floor); `confirmations`/`confidence` are evidence-side signals; `status`, `kind`, `staleness_policy`, `owner_org`, top-level `superseded_by`, and `related[]` are top-level; provenance carries `proposer_did`, `graduation_history[]`, and the `emergent` flag. On the wire, `propose` accepts flat `context_*` params but the response nests them into a `context` object, and `domains` is the upstream-conformant name (with `domain` as a promoted alias).

**gap-signal interop:** `kind="gap-signal"` is rejected on propose; the emergent aggregation job emits `kind="tool-gap-signal"` with `provenance.emergent=true`. Pre-v1 rows with `gap-signal` are rewritten by the v0→v1 migration to `tool-gap-signal` with `provenance.emergent=false` (grandfathered), preserving every other field. `status` reports the two populations separately.

## Status & Open Questions [coverage: medium — 6 sources]

**v0 baseline (stolperstein-mvp-scaffold) → v1 (cq-v1-alignment-and-hooks) deltas:**

| Concern | v0 baseline | v1 modification |
|---|---|---|
| KU id format | `ku_[alphanumeric]` | `^ku_[0-9a-f]{32}$` |
| Capture field name | `domain` | `domains` (min 1), `domain` alias promoted |
| `kind` enum | includes `gap-signal` | `gap-signal` removed; emergent `tool-gap-signal` only |
| Context on propose | (not specified) | flat `context_*` params + `severity`, nested in response |
| Query severity | — | severity tiebreaker; no `severity_min` param |
| Diversity weighting | distinct agents/projects | distinct `owner_org` values |
| Decay floor | 0.1 | 0.1 default, 0.2 for `critical` |
| Supersedence target | `related[]` entry | top-level `superseded_by` column |
| confirm error | "KU not found" string | `McpError(InvalidParams, ...)` with `query()` hint |
| Provenance | (not specified) | `proposer_did` + `owner_org` stamped; graduation history; confirm doesn't mutate it |
| `status` | no args, four fields | `debug` flag; token-frugal default + `tool_gap_signals` partition |
| Storage | 3 tables | + `schema_version`, `install_identity`, `query_misses`, many columns |

**Deferred / out of scope here.**
- Multi-tenant `owner_org` + `TRUSTED_ORGS` land as **foundation only**: read-filter visibility with default trust-all. Enforceable write-side org permissions and selective graduation are later scope.
- `staleness_policy` is settable at propose but is "modifiable via a **future** admin tool" — no admin mutation path is specified yet.
- v0 said an unreachable embedding model should mark the embedding "pending for retry"; v1 restates create-anyway-and-warn but does not carry the retry-queue language, leaving the retry mechanism unspecified.
- disputed→active requires "sufficient re-confirmations," but the exact threshold is not quantified in these specs.
- The precise weighting between FTS5 relevance and vector cosine in the combined rank is described as "weighted combination" without fixed coefficients.

## Sources [coverage: high — 6 sources]

- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/knowledge-capture/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/knowledge-retrieval/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/ku-lifecycle/spec]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/knowledge-capture/spec]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/knowledge-retrieval/spec]]
- [[../../../openspec/changes/stolperstein-mvp-scaffold/specs/ku-lifecycle/spec]]
