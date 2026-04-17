## ADDED Requirements

### Requirement: Every KU carries an owner_org

Every Knowledge Unit SHALL have a non-null `owner_org` field (TEXT, typically a `did:key:...` identifier). The system SHALL set `owner_org` automatically on `propose()` to the local install's DID. Ingested team-sync KUs SHALL preserve their upstream `owner_org` — it SHALL NOT be rewritten to the local install DID. Migration `m0002_provenance_and_org` SHALL backfill existing rows with the local install DID (they were created pre-multi-tenant on this install).

#### Scenario: Propose stamps owner_org to install DID

- **WHEN** `propose()` creates a new KU
- **THEN** the KU's `owner_org` SHALL equal the install's `proposer_did`

#### Scenario: Ingested KU preserves upstream owner_org

- **WHEN** a CQ-v1 KU is ingested from the team API with `owner_org="did:key:zUpstreamOrg"`
- **THEN** the stored row SHALL have `owner_org="did:key:zUpstreamOrg"` (NOT rewritten to the local DID)

#### Scenario: Migration backfills existing rows

- **WHEN** `m0002_provenance_and_org` runs against a v0 DB
- **THEN** every existing row SHALL have `owner_org` set to the newly generated local install DID

### Requirement: query applies a TRUSTED_ORGS visibility filter

The `query` tool SHALL apply an implicit visibility filter BEFORE confidence/severity ranking:

- Include rows where `owner_org == <local-install-did>` (always visible — own KUs).
- Include rows where `owner_org IN TRUSTED_ORGS` (explicit trust).
- Include all rows when `TRUSTED_ORGS == "*"` (trust-all, default).

`TRUSTED_ORGS` is configured via a comma-separated env var or `.claude/settings.json` key. The default is `"*"` to preserve current single-install behavior — operators running multi-org must narrow the list. The filter SHALL apply to both local and team-API result sets identically.

#### Scenario: Default trust-all preserves current behavior

- **WHEN** `TRUSTED_ORGS` is unset (or `"*"`) and an agent calls `query`
- **THEN** the server SHALL return results including any KU regardless of `owner_org`

#### Scenario: Restrictive TRUSTED_ORGS excludes untrusted orgs

- **WHEN** `TRUSTED_ORGS="did:key:zA,did:key:zB"` and an agent queries in an install with DID `did:key:zLocal`
- **THEN** visible results SHALL include only KUs whose `owner_org` is `did:key:zLocal`, `did:key:zA`, or `did:key:zB`

#### Scenario: Filter applies to team-sync merged results

- **WHEN** `CQ_TEAM_ADDR` is configured and `TRUSTED_ORGS="did:key:zA"` and team API returns KUs with various `owner_org` values
- **THEN** the final merged result set SHALL include only local-install KUs and team KUs with `owner_org="did:key:zA"`

### Requirement: Confidence diversity weighting counts distinct owner_orgs

The confidence scoring algorithm SHALL count distinct `owner_org` values among `contributing_orgs` (not distinct agent sessions, not distinct DIDs per session) when computing the diversity multiplier. Migration SHALL preserve any existing `contributing_orgs` values as-is — these arrays store DIDs.

#### Scenario: Same-org multiple confirmations count as single org

- **WHEN** a KU has `contributing_orgs=["did:key:zA", "did:key:zA", "did:key:zA"]`
- **THEN** the diversity multiplier SHALL treat this as 1 distinct org, not 3

#### Scenario: Distinct orgs boost diversity

- **WHEN** a KU has `contributing_orgs=["did:key:zA", "did:key:zB", "did:key:zC"]`
- **THEN** the diversity multiplier SHALL treat this as 3 distinct orgs

### Requirement: owner_org is exposed in query results and status debug

The `query` tool response SHALL include each KU's `owner_org` as a top-level field (part of the v1 CQ shape). The `status(debug=True)` response SHALL include a `by_owner_org` breakdown: counts of KUs grouped by `owner_org` (capped at top 20 orgs for readability).

#### Scenario: Query result exposes owner_org

- **WHEN** `query()` returns a KU
- **THEN** each returned KU SHALL include its `owner_org` field

#### Scenario: Debug status shows org breakdown

- **WHEN** an operator calls `status(debug=True)` in a multi-org install
- **THEN** the response SHALL include `by_owner_org` mapping each owner_org DID to its KU count (top 20)

### Requirement: Phase 1 does not enforce write permissions

The Phase 1 org-boundaries capability is READ-FILTER ONLY. `propose()`, `confirm()`, `flag()`, and ingestion SHALL continue to operate without per-org write permission checks. Enforceable per-org write/graduate permissions are Phase 2 scope; attempting to add them in this change is out-of-scope. Documentation (SKILL.md, deploy notes) SHALL make this explicit so operators running multi-org deployments understand the current limit.

#### Scenario: Propose succeeds regardless of TRUSTED_ORGS

- **WHEN** `TRUSTED_ORGS="did:key:zNotUs"` (restrictive) and a local agent calls `propose()`
- **THEN** the KU SHALL be created with `owner_org` = local install DID; the restrictive `TRUSTED_ORGS` SHALL NOT prevent local writes

#### Scenario: Documentation flags the Phase 1 limit

- **WHEN** an operator reads the SKILL.md or deploy notes
- **THEN** a note SHALL explicitly state that write-side permissions are not enforced in Phase 1 and will land in a follow-up change
