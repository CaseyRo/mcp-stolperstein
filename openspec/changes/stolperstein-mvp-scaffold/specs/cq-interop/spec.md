## ADDED Requirements

### Requirement: KU schema is CQ-compatible

All Knowledge Units SHALL be stored and transmitted using fields compatible with Mozilla CQ's `knowledge-unit.schema.json` interchange format. Required fields: `id` (ku_* format), `version`, `domain`, `insight.summary`, `insight.detail`, `insight.action`, `confidence`, `confirmations`, `contributing_orgs`, `first_observed`, `last_confirmed`, `last_queried_at`, `kind`, `status`, `staleness_policy`, `related`. The system SHALL be able to serialize any local KU to valid CQ JSON without transformation.

#### Scenario: Local KU serializes to CQ format

- **WHEN** a KU is exported or synced upstream
- **THEN** the serialized JSON SHALL validate against the CQ `knowledge-unit.schema.json` schema without errors

#### Scenario: CQ-format KU imports without loss

- **WHEN** a KU in CQ JSON format is received from a team API
- **THEN** the system SHALL store it in the local SQLite database preserving all fields, generating a local embedding if one is not provided

### Requirement: Optional team API sync

The system SHALL support optional connection to a CQ team API via `CQ_TEAM_ADDR` and `CQ_TEAM_API_KEY` environment variables. When configured, the system SHALL pull shared KUs from the team tier on query (merge with local results) and allow graduating local KUs upstream via an explicit `graduate` action (not automatic).

#### Scenario: Query merges local and team results

- **WHEN** `CQ_TEAM_ADDR` is configured and an agent calls `query`
- **THEN** the server SHALL query both local SQLite and the team API, merge results by combined relevance score, and deduplicate by KU id (local version wins on conflict)

#### Scenario: Team API unavailable during query

- **WHEN** `CQ_TEAM_ADDR` is configured but the team API is unreachable
- **THEN** the server SHALL return local results only and include a warning in the response metadata (not an error)

#### Scenario: Graduate a local KU to team tier

- **WHEN** an agent or human triggers graduation of a local KU (via future admin tool or explicit API call)
- **THEN** the system SHALL serialize the KU to CQ JSON format and POST it to the team API's `/propose` endpoint, marking the local KU with `graduated_to_team: true`

### Requirement: Standalone operation without team sync

The system SHALL operate fully functional without any CQ team or global configuration. All 6 MCP tools SHALL work with local-only storage. Team sync SHALL be purely additive — enabling it SHALL NOT change the behavior of local operations.

#### Scenario: Server runs in local-only mode

- **WHEN** `CQ_TEAM_ADDR` is not set
- **THEN** all MCP tools SHALL operate against local SQLite only, with no network calls and no degraded functionality

#### Scenario: Team sync disabled after being enabled

- **WHEN** `CQ_TEAM_ADDR` is removed from configuration
- **THEN** all previously synced KUs SHALL remain in local storage and continue to be queryable
