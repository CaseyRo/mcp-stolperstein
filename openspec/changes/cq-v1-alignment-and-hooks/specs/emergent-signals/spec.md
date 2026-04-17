## ADDED Requirements

### Requirement: Query misses are captured for emergent-signal detection

Every `query()` call that returns zero visible results above `confidence_min=0.3` SHALL be recorded as a row in the `query_misses` rolling table. Each row SHALL store the query text (truncated to 512 chars), the generated embedding (384-dim float vector, serialized per `sqlite_vec`), and the creation timestamp. Rows older than 30 days SHALL be pruned on each `detect-emergent` run. The capture SHALL NOT be exposed as a user-visible side effect — the response shape of `query()` is unchanged.

#### Scenario: Empty-result query records a miss

- **WHEN** `query(text="obscure thing", confidence_min=0.3)` returns zero visible KUs
- **THEN** a new row SHALL be inserted into `query_misses` with the text, the query's embedding, and the current timestamp

#### Scenario: Successful query does NOT record a miss

- **WHEN** `query(text="swift concurrency")` returns at least one visible KU above confidence_min
- **THEN** no row SHALL be inserted into `query_misses`

#### Scenario: Old misses are pruned

- **WHEN** the emergent-signal job runs and finds `query_misses` rows older than 30 days
- **THEN** those rows SHALL be deleted before aggregation begins

### Requirement: Emergent-signal aggregation produces tool-gap-signal KUs

The system SHALL provide an `emergent` module that aggregates recent `query_misses` into emergent `tool-gap-signal` KUs. The aggregation SHALL:

1. Cluster misses by embedding cosine similarity (threshold ≥ 0.8).
2. For any cluster with at least `EMERGENT_MIN_MISSES` misses (default 5) from at least `EMERGENT_MIN_SESSIONS` distinct sessions (default 2, where "session" is approximated by distinct 1-hour time buckets): emit a new KU.
3. Emitted KUs SHALL have: `kind="tool-gap-signal"`, `provenance.emergent=true`, `status="draft"`, `confidence=0.5`, `owner_org` = local install DID, `summary` synthesized from a representative miss, `detail` summarizing the cluster (e.g., "Agents searched for this topic {N} times over {T} days without a matching KU"), `action` = imperative to investigate or propose a covering KU.
4. An emitted KU SHALL NOT be re-emitted from the same cluster within 7 days (dedupe by embedding proximity to existing emergent KUs).

Cadence: the aggregation SHALL run on every `EMERGENT_DETECT_EVERY_N`-th `query()` call (default 10) OR on explicit `mcp-stolperstein detect-emergent` invocation. The trigger SHALL be a fire-and-forget background task that does not block the triggering `query()` call's response.

#### Scenario: Sufficient clustered misses produce an emergent KU

- **WHEN** 6 misses with ≥0.8 cosine similarity occur across 3 distinct hour-buckets in the past 30 days
- **THEN** the next aggregation run SHALL emit a new KU with `kind="tool-gap-signal"` and `provenance.emergent=true`

#### Scenario: Insufficient misses do not produce a KU

- **WHEN** only 2 similar misses exist in the window
- **THEN** the aggregation SHALL emit nothing

#### Scenario: Recent emergent KU prevents duplicate

- **WHEN** a cluster would produce a KU but an existing emergent KU with cosine similarity ≥0.8 was emitted within the past 7 days
- **THEN** no new KU SHALL be emitted

#### Scenario: Aggregation does not block query response

- **WHEN** a `query()` call triggers aggregation (the N-th call)
- **THEN** the `query()` response SHALL return on the normal latency budget; aggregation runs in background

### Requirement: Emergent KUs are distinguishable in status reporting

The `status()` tool SHALL report `tool_gap_signals` as an object with two fields: `grandfathered` (count of KUs where `kind="tool-gap-signal"` AND `provenance.emergent=false`) and `emergent` (count where `provenance.emergent=true`). Operators SHALL be able to inspect the latest emergent KUs via `status(debug=True)` which SHALL additionally include up to 10 most recent emergent KUs by `first_observed`.

#### Scenario: Status partitions tool-gap-signals

- **WHEN** the store contains 3 grandfathered (migrated) and 7 emergent tool-gap-signals
- **THEN** `status()` SHALL return `tool_gap_signals: {grandfathered: 3, emergent: 7}`

#### Scenario: Debug status lists recent emergent KUs

- **WHEN** an operator calls `status(debug=True)`
- **THEN** the response SHALL include a `recent_emergent` array with up to 10 most-recently-observed emergent KUs

### Requirement: Emergent aggregation is disableable

Operators SHALL be able to disable emergent aggregation by setting `STOLPERSTEIN_EMERGENT_DISABLED=true` or setting `EMERGENT_DETECT_EVERY_N=0`. When disabled, `query_misses` MAY still be captured (for future enablement) but no aggregation SHALL run.

#### Scenario: Disabled aggregation skips emission

- **WHEN** `STOLPERSTEIN_EMERGENT_DISABLED=true` is set
- **THEN** no emergent KU SHALL be emitted regardless of miss volume

#### Scenario: Manual detect-emergent still works when env is set to disable

- **WHEN** `STOLPERSTEIN_EMERGENT_DISABLED=true` AND the operator runs `mcp-stolperstein detect-emergent`
- **THEN** the CLI SHALL print "emergent detection is disabled; set STOLPERSTEIN_EMERGENT_DISABLED=false to run" and exit 0 without aggregating
