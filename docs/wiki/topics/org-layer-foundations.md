---
topic: org-layer-foundations
last_compiled: 2026-07-07
---

# Org-Layer Foundations

## Summary [coverage: high — 2 sources]

Stolperfalle is framed as Phase 1 of a "machine-readable org layer." Two capabilities lay that foundation without yet building the whole product: **multi-tenant primitives** (an `owner_org` on every Knowledge Unit plus a `TRUSTED_ORGS` visibility filter) and **emergent-signal detection** (capturing zero-result queries and clustering them into `tool-gap-signal` KUs).

Both are deliberately foundation-only. `owner_org` is stamped on every KU and `query()` applies a read-side visibility filter, but the default is **trust-all** (`TRUSTED_ORGS="*"`) and there are **no write-side org permission checks** — `propose`/`confirm`/`flag`/ingest run without them. Enforceable per-org write/graduate permissions, per-org UI, and selective graduation are explicitly Phase 2. Emergent detection ships as a real module with a simple count-based clustering heuristic (cosine ≥0.8, ≥5 misses across ≥2 distinct hour-buckets, 7-day dedupe) so the algorithm can be swapped later without schema or tool churn. Adding the field and the module now is cheap; retrofitting either onto an existing install is expensive.

## Rationale & Context [coverage: medium — 2 sources]

The project was reframed from a "personal knowledge base" into the "atomic data layer for the machine-readable org layer that replaces status meetings." This change (`cq-v1-alignment-and-hooks`) is Phase 1 of that larger ambition, not a personal-tool polish pass. Two decisions in this change carry that thesis into the data model: `owner_org`/`TRUSTED_ORGS` and the emergent-signal module.

**Why `owner_org` is foundation.** Enforcing org boundaries requires a Phase 2 permissions model (per-org read/propose/graduate rights, inheritance, UI). But adding the column now is a cheap migration, whereas retrofitting later means rewriting every existing KU's visibility. The design's stated principle: "Adding the field to the data model now is cheap; retrofitting later is expensive." Default-trust preserves current single-install behavior so a solo operator sees no change.

**Why emergent signals are first-class now.** The strategic framing makes emergent signals *the* feature that justifies the org-layer thesis — surfacing the things nobody asked about but the agents keep hitting. Leaving it as an open question would signal it is deprioritizable; it is not. So it ships as a real `emergent.py` module (Decision 9) rather than a TODO. The heuristic is intentionally simple — the point is that the capability *exists* so later changes can improve the algorithm without a structural refactor.

Stakeholders named for this foundation work include the solo operator, downstream Siyuan sync, future CQ team/global-tier consumers, and "future org-scale deployments where KUs cross department boundaries" — the case the org layer is being built toward.

## Requirements & Behavior [coverage: high — 2 sources]

### owner_org stamping and preservation

- Every KU SHALL have a non-null `owner_org` (TEXT, typically a `did:key:...`).
- `propose()` SHALL set `owner_org` automatically to the local install's DID (its `proposer_did`).
- Ingested team-sync KUs SHALL **preserve** their upstream `owner_org` — it SHALL NOT be rewritten to the local DID.
- Migration `m0002_provenance_and_org` SHALL backfill existing v0 rows with the newly generated local install DID.

Scenarios: `propose()` stamps the install DID; a CQ-v1 KU ingested with `owner_org="did:key:zUpstreamOrg"` keeps that value; running `m0002` against a v0 DB sets `owner_org` on every existing row to the local DID.

### TRUSTED_ORGS visibility filter

`query` SHALL apply an implicit visibility filter **BEFORE** confidence/severity ranking:

- Include rows where `owner_org == <local-install-did>` (own KUs, always visible).
- Include rows where `owner_org IN TRUSTED_ORGS` (explicit trust).
- Include **all** rows when `TRUSTED_ORGS == "*"` (trust-all, the default).

`TRUSTED_ORGS` is a comma-separated env var (or `.claude/settings.json` key). The default `"*"` preserves current single-install behavior; operators running multi-org must narrow the list. The filter SHALL apply identically to local and team-API result sets.

Scenarios: unset/`"*"` returns any KU regardless of `owner_org`; `TRUSTED_ORGS="did:key:zA,did:key:zB"` in install `did:key:zLocal` returns only KUs owned by `zLocal`, `zA`, or `zB`; with `CQ_TEAM_ADDR` configured, the merged local+team result set includes only local KUs plus team KUs matching a trusted org.

### Phase 1 does NOT enforce write permissions

The org-boundaries capability is **READ-FILTER ONLY**. `propose()`, `confirm()`, `flag()`, and ingestion SHALL continue without per-org write permission checks. A restrictive `TRUSTED_ORGS` does not block local writes: with `TRUSTED_ORGS="did:key:zNotUs"`, a local `propose()` still creates the KU with `owner_org` = local DID. Documentation (SKILL.md, deploy notes) SHALL explicitly state that write-side permissions are not enforced in Phase 1 and land in a follow-up change.

### Confidence diversity counts distinct owner_orgs

The confidence scoring's diversity multiplier SHALL count **distinct `owner_org` values** among `contributing_orgs` (not distinct sessions, not distinct DIDs per session). `contributing_orgs=["did:key:zA","did:key:zA","did:key:zA"]` counts as 1 org; three distinct DIDs count as 3. Migration preserves existing `contributing_orgs` arrays as-is (they store DIDs).

### owner_org exposure

`query` responses SHALL include each KU's `owner_org` as a top-level field (part of the v1 CQ shape). `status(debug=True)` SHALL include a `by_owner_org` breakdown — counts of KUs grouped by `owner_org`, capped at the top 20 orgs.

### Query-miss capture

Every `query()` returning zero visible results above `confidence_min=0.3` SHALL record a row in the `query_misses` rolling table, storing: query text (truncated to 512 chars), the 384-dim embedding (serialized per `sqlite_vec`), and a creation timestamp. Rows older than 30 days SHALL be pruned on each `detect-emergent` run. Capture SHALL NOT change the `query()` response shape (no user-visible side effect). A successful query (≥1 visible KU above `confidence_min`) records nothing.

### Emergent-signal aggregation thresholds

The `emergent` module SHALL aggregate recent `query_misses` into `tool-gap-signal` KUs:

1. Cluster misses by embedding cosine similarity (threshold **≥ 0.8**).
2. For any cluster with at least `EMERGENT_MIN_MISSES` misses (default **5**) from at least `EMERGENT_MIN_SESSIONS` distinct sessions (default **2**, where a "session" is approximated by a distinct 1-hour time bucket): emit a KU.
3. Emitted KUs SHALL have: `kind="tool-gap-signal"`, `provenance.emergent=true`, `status="draft"`, `confidence=0.5`, `owner_org` = local install DID, a `summary` synthesized from a representative miss, a `detail` summarizing the cluster (e.g. "Agents searched for this topic {N} times over {T} days without a matching KU"), and an `action` that is an imperative to investigate or propose a covering KU.
4. A cluster SHALL NOT re-emit within **7 days** (dedupe by embedding proximity to existing emergent KUs, cosine ≥0.8).

Cadence: aggregation SHALL run on every `EMERGENT_DETECT_EVERY_N`-th `query()` call (default **10**) OR on explicit `mcp-stolperfalle detect-emergent`. The trigger is a fire-and-forget background task that does not block the triggering `query()` response.

Scenarios: 6 misses at ≥0.8 cosine across 3 distinct hour-buckets in the past 30 days → next run emits a `tool-gap-signal` with `provenance.emergent=true`; only 2 similar misses → nothing emitted; a cluster that would emit but has a ≥0.8-similar emergent KU from the past 7 days → nothing emitted; the N-th `query()` returns on the normal latency budget while aggregation runs in the background.

### Emergent KUs distinguishable in status; disableable

- `status()` SHALL report `tool_gap_signals` as `{grandfathered, emergent}` — grandfathered = `kind="tool-gap-signal"` AND `provenance.emergent=false` (migrated rows); emergent = `provenance.emergent=true`. Example: 3 migrated + 7 emergent → `tool_gap_signals: {grandfathered: 3, emergent: 7}`.
- `status(debug=True)` SHALL additionally include a `recent_emergent` array of up to 10 most-recent emergent KUs by `first_observed`.
- Aggregation SHALL be disableable via `STOLPERFALLE_EMERGENT_DISABLED=true` or `EMERGENT_DETECT_EVERY_N=0`. When disabled, `query_misses` MAY still be captured (for future enablement) but no aggregation runs. Manual `mcp-stolperfalle detect-emergent` under `STOLPERFALLE_EMERGENT_DISABLED=true` SHALL print "emergent detection is disabled; set STOLPERFALLE_EMERGENT_DISABLED=false to run" and exit 0 without aggregating.

## Design & Architecture [coverage: medium — 2 sources]

**Visibility filtering.** `owner_org` is a `TEXT NOT NULL DEFAULT <install-did>` column added in `m0002_provenance_and_org`. Because the filter is applied *before* confidence/severity ranking (rather than as a post-rank pass), untrusted rows never enter the scoring set, and the same predicate covers both the local store and merged team-API results. The predicate is a three-way OR: own DID, membership in `TRUSTED_ORGS`, or the `"*"` trust-all short-circuit. `owner_org` derives from the per-install Ed25519 `did:key` identity (whose private key lives outside the DB), so ownership and provenance share one identifier rather than introducing a separate tenant ID.

**Emergent clustering job.** The capability lives in `src/stolperfalle/emergent.py`. Query misses accumulate in a small `query_misses` rolling table (added by `m0004_emergent_scaffolding`, 30-day TTL). The aggregation is a count-based clustering pass: prune stale misses, group by embedding cosine similarity, and emit a `tool-gap-signal` KU for any bin that clears the miss/session thresholds. "Session" is approximated by distinct 1-hour time buckets rather than tracked session IDs — a deliberate simplification. It is explicitly *not* ML-sophisticated; the design flags richer heuristics (ML clustering, LLM summarization of clusters) as Phase 2. The module boundary is the point: later changes can replace the algorithm without touching the schema or the MCP tool surface.

**Trigger model.** Aggregation is event-based, piggybacking on the `EMERGENT_DETECT_EVERY_N`-th `query()` call as a fire-and-forget background task so it never blocks the query response, with the CLI `detect-emergent` as the explicit escape hatch. (Whether this should instead be time-based is an open question — see below.)

**Conservative thresholds as a noise guard.** The ≥5-misses / ≥2-sessions / cosine-≥0.8 thresholds plus 7-day dedupe are the defense against emergent false-positives flooding the store. A bad emergent KU can be `flag()`-ed to archive it, and the emergent count is visible in `status()` for an operator to eyeball.

## Schema & Interop [coverage: medium — 2 sources]

- **`owner_org`** — top-level KU field, `TEXT NOT NULL`, added in `m0002_provenance_and_org` with `DEFAULT <install-did>`. Part of the v1 CQ shape and returned as a top-level field by `query`. Set to the install DID on `propose()`; preserved from upstream on ingest.
- **`contributing_orgs`** — JSON array of DIDs. Feeds the confidence diversity multiplier by *distinct* value. Migration preserves existing arrays as-is.
- **`provenance.emergent`** — boolean distinguishing machine-emitted signals (`true`) from migrated/human `tool-gap-signal` rows (`false`, "grandfathered"). Migration `m0003_gap_signal_rename` rewrites legacy `kind="gap-signal"` rows to `kind="tool-gap-signal"` with `provenance.emergent=false`; the emergent job sets `true` for its own contributions.
- **`kind="tool-gap-signal"`** — the CQ v1 emergent-only kind. `propose(kind="gap-signal")` is rejected with an actionable `McpError` (tool gaps are detected automatically, not proposed). Emergent KUs additionally carry `status="draft"`, `confidence=0.5`, `owner_org` = install DID, and synthesized `summary`/`detail`/`action`.
- **`query_misses`** — internal rolling table (not on the wire), added by `m0004_emergent_scaffolding`. Stores truncated query text, the 384-dim `sqlite_vec` embedding, and a timestamp; 30-day TTL.
- **`by_owner_org`** (status debug) and **`tool_gap_signals: {grandfathered, emergent}`** / **`recent_emergent`** (status) are reporting projections, not stored columns.

`TRUSTED_ORGS`, `EMERGENT_DETECT_EVERY_N`, `EMERGENT_MIN_MISSES`, `EMERGENT_MIN_SESSIONS`, and `STOLPERFALLE_EMERGENT_DISABLED` are the operator-facing env controls for this layer. On DID identifiers: `did:key:z...` is treated as an opaque identifier — no DID-document resolution, no registry, no resolver (out of scope).

## Status & Open Questions [coverage: medium — 2 sources]

**Shipped as Phase-1 foundation:**

- `owner_org` on every KU (stamped on propose, preserved on ingest, backfilled on migrate).
- `TRUSTED_ORGS` **read-side** visibility filtering, applied before ranking, defaulting to trust-all (`"*"`).
- Confidence diversity weighting by distinct `owner_org`.
- `owner_org` exposure in `query` results and `status(debug=True)`.
- Query-miss capture into `query_misses` and the emergent-signal module (count-based clustering, `tool-gap-signal` emission, 7-day dedupe, status partitioning, disable switches).

**Explicitly Phase 2 (out of scope here):**

- **Write-side org permissions** — enforceable per-org read/propose/graduate rights, inheritance. Phase 1 does not enforce write permissions at all; a restrictive `TRUSTED_ORGS` never blocks local writes. The permissions model (ACL-per-org vs role-based vs capability-based) is a deferred open question; this change only lays the `owner_org` column + default-trust so Phase 2 has something to attach to.
- **Per-org UI** — no per-org views; `by_owner_org` is a debug count only.
- **Selective graduation** — `graduation_history` is recorded passively; there is no human-facing review/graduation UI and no per-org graduation control.
- **Rich emergent heuristics** — ML clustering / LLM summarization of clusters is Phase 2; Phase 1 is count-based miss-clustering.

**Open questions carried forward:**

- **Emergent cadence** — every 10th `query()` is a rough default; should it be time-based (hourly) instead of event-based? Current draft stays event-based with the `EMERGENT_DETECT_EVERY_N` override.
- **`graduation_history` on team-sync import** — whether to append an import entry. Current draft: no; imports are passive and upstream history is preserved.
- **Default-trust risk** — `TRUSTED_ORGS="*"` is correct for single-install but dangerous at multi-tenant scale; Phase 2 (write-side enforcement) is required before any real multi-org deployment. Documented as a known limitation in deploy notes.

## Sources [coverage: high — 2 sources]

- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/org-boundaries/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/specs/emergent-signals/spec]]
- [[../../../openspec/changes/cq-v1-alignment-and-hooks/design]] (context: org-layer thesis, Decisions 9 & 10, Phase 1/2 framing)
