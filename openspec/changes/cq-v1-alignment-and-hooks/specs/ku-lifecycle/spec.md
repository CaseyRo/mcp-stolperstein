## MODIFIED Requirements

### Requirement: KU state machine

Each KU SHALL have a `status` field following this state machine: `draft` -> `active` -> `stale` -> `archived`. Any non-archived KU can transition to `disputed`. Transitions SHALL be: draft->active (on first confirmation), active->stale (on staleness threshold breach), stale->active (on re-confirmation), active->disputed (on flag), disputed->active (on sufficient re-confirmations), any->archived (on flag with reason `superseded` or manual archive). When a KU transitions to `archived` via supersedence, the system SHALL set the top-level `superseded_by` field to the superseding KU's id (not store it in `related[]`). Status transitions SHALL NOT change `owner_org`.

#### Scenario: KU graduates from draft to active

- **WHEN** a KU in `draft` status receives its first `confirm` call
- **THEN** the server SHALL transition the KU to `active` status

#### Scenario: KU decays to stale

- **WHEN** a KU in `active` status has not been confirmed or queried for longer than its `staleness_policy` threshold (default 90 days)
- **THEN** the server SHALL transition the KU to `stale` and begin confidence decay

#### Scenario: Stale KU revived by confirmation

- **WHEN** a KU in `stale` status receives a `confirm` call
- **THEN** the server SHALL transition back to `active`, reset the staleness timer, and recalculate confidence upward

#### Scenario: Supersedence sets top-level field

- **WHEN** a KU is flagged with `reason=superseded` and `superseded_by=ku_xyz`
- **THEN** the server SHALL set `status=archived` and write `superseded_by=ku_xyz` to the top-level column (not `related[]`)

#### Scenario: Status change preserves owner_org

- **WHEN** a KU transitions through any status change
- **THEN** its `owner_org` SHALL remain unchanged

### Requirement: Confidence scoring algorithm

The confidence score SHALL be a float between 0.0 and 1.0, calculated as: base confidence (0.5 on creation) adjusted by confirmations (weighted by organizational diversity — counts distinct `owner_org` values among contributors, not just distinct agents), temporal decay (linear decay after staleness threshold), and dispute penalty (capped at 0.5 when disputed). KUs with `evidence.severity=critical` SHALL have a decay floor of 0.2 instead of the default 0.1 — critical-severity KUs never fully decay because ignoring them is disproportionately costly.

#### Scenario: Confidence increases with diverse confirmations

- **WHEN** a KU receives confirmations from 3 distinct `owner_org` values
- **THEN** the confidence SHALL increase more than if 3 confirmations came from a single `owner_org`

#### Scenario: Confidence decays over time without activity

- **WHEN** a KU has not been confirmed or queried for 90+ days
- **THEN** the confidence SHALL decrease linearly at 0.01 per day past the threshold, clamped to the applicable floor

#### Scenario: Critical severity raises decay floor

- **WHEN** a KU with `evidence.severity=critical` would decay below 0.2
- **THEN** the confidence SHALL clamp at 0.2 instead of the default 0.1 floor

#### Scenario: Disputed KU confidence is capped

- **WHEN** a KU is flagged as `incorrect` or `dangerous`
- **THEN** the confidence SHALL be immediately capped at 0.5 regardless of prior confirmations

### Requirement: Staleness policy is configurable per KU

Each KU SHALL have a `staleness_policy` field (default: `confirm_or_decay_after_90d`) that defines the decay threshold in days. The policy SHALL be settable at propose time and modifiable via a future admin tool.

#### Scenario: KU with custom staleness policy

- **WHEN** a KU is proposed with `staleness_policy: "confirm_or_decay_after_30d"`
- **THEN** the staleness timer SHALL use 30 days instead of the default 90

#### Scenario: Staleness check runs on query

- **WHEN** a `query` or `status` call is made
- **THEN** the server SHALL evaluate staleness based on current time vs. `last_confirmed_at` + policy threshold, transitioning any newly-stale KUs before returning results

## ADDED Requirements

### Requirement: Provenance is recorded on every mutation

Every `propose`, `confirm`, `flag`, and graduation event SHALL update the KU's `provenance` block. Newly proposed KUs SHALL be stamped with the local install's `proposer_did` AND `owner_org`. Graduation events SHALL append entries to `graduation_history[]` with `{timestamp, target, reviewer_did, agent: true}` — the `agent: true` marker distinguishes automated from human graduation. `confirm()` SHALL NOT append to `graduation_history`.

#### Scenario: New KU gets proposer_did and owner_org

- **WHEN** `propose` creates a new KU
- **THEN** the KU's `provenance.proposer_did` SHALL be set to the install's persistent `did:key:...` identifier AND `owner_org` SHALL be set to the same DID

#### Scenario: Graduation appends history entry with agent marker

- **WHEN** a KU is graduated via an MCP tool call
- **THEN** a new entry `{"timestamp": <iso8601>, "target": <tier>, "reviewer_did": <did>, "agent": true}` SHALL be appended to `graduation_history[]`

#### Scenario: Confirm does not mutate graduation_history

- **WHEN** `confirm(ku_id)` is called
- **THEN** `graduation_history` SHALL NOT be modified; only `confirmations`, `last_confirmed_at`, `confidence`, and `status` may change

### Requirement: gap-signal is emergent-only

The `kind="gap-signal"` value SHALL NOT be accepted by `propose`. The system SHALL use `kind="tool-gap-signal"` for emergent aggregate signals. Existing KUs migrated from a pre-v1 schema with `kind="gap-signal"` SHALL be rewritten to `kind="tool-gap-signal"` with `provenance.emergent=false` (grandfathered). KUs produced by the emergent-signal aggregation job SHALL set `provenance.emergent=true`.

#### Scenario: Propose rejects gap-signal

- **WHEN** an agent calls `propose(kind="gap-signal", ...)`
- **THEN** the server SHALL return an `McpError(InvalidParams, ...)` naming `gap-signal` as deprecated and pointing to the emergent alternative

#### Scenario: Migrated rows are marked grandfathered

- **WHEN** the v0→v1 migration runs against a DB containing `gap-signal` rows
- **THEN** each row SHALL be rewritten with `kind="tool-gap-signal"` AND `provenance.emergent=false`, preserving every other field

#### Scenario: Emergent aggregation marks its own output

- **WHEN** the emergent-signal aggregation job produces a new `tool-gap-signal` KU
- **THEN** the new KU SHALL have `provenance.emergent=true`
