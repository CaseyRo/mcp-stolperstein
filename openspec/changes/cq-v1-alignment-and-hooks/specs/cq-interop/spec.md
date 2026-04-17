## MODIFIED Requirements

### Requirement: KU wire format conforms strictly to upstream CQ schema

All Knowledge Units emitted to any external CQ consumer (team API, global tier, external validator) SHALL conform exactly to `mozilla-ai/cq` upstream `schema/knowledge_unit.json` as vendored at a pinned SHA in `tests/fixtures/cq/`. Upstream's schema is `additionalProperties: false` everywhere, so Stolperstein extensions SHALL NOT appear on the wire. The system SHALL provide two serializers:

- `to_cq_json_strict()`: emits the upstream-valid shape with extensions stripped. Used for team-sync upload, external validation, and any interop path.
- `to_cq_json_rich()`: emits the internal superset with all Stolperstein extensions present. Used for local dumps, debugging, and future upstream-aware consumers.

Strict-mode field mapping:

- Our `domain[]` → upstream `domains[]` (rename at serializer).
- Our internal `ku_id` formats other than `^ku_[0-9a-f]{32}$` SHALL NOT be emitted — migration `m0000` guarantees all rows conform before this serializer ships.
- Our `version` (semver string for Stolperstein-internal) → upstream `version: 1` integer.
- Our `context_language` singular column → upstream `context.languages` array (wrap single value in array; empty stays empty).
- Our `context_environment` → **NOT emitted** (Stolperstein extension).
- Our `evidence.severity` → **NOT emitted** (Stolperstein extension).
- Our `evidence.contributing_orgs` → **NOT emitted** (Stolperstein extension — proposed upstream).
- Our top-level `last_confirmed_at` column → upstream `evidence.last_confirmed`.
- Our top-level `kind` field → **NOT emitted** (Stolperstein extension — proposed upstream).
- Our top-level `status` field → **NOT emitted** (Stolperstein extension — upstream models lifecycle via `flags[]`).
- Our top-level `staleness_policy` → **NOT emitted** (Stolperstein extension).
- Our `related[]` relationship array → **NOT emitted** (Stolperstein extension).
- Our top-level `superseded_by` → upstream `superseded_by` (direct pass-through, both use `^ku_[0-9a-f]{32}$`).
- Our `provenance.proposer_did` → upstream `created_by` (string pass-through; DID is a valid string value).
- Our `provenance.graduation_history` → **NOT emitted** (Stolperstein extension — proposed upstream).
- Our `provenance.emergent` → **NOT emitted** (Stolperstein extension).
- Our `owner_org` → **NOT emitted** (Stolperstein extension; upstream has `tier` enum instead, which we do not currently use).
- Our `flags[]` array: mapped to upstream `flags[]` with reason values normalized — `dangerous` maps to `incorrect` (with an extension note held locally only); `superseded` is never a flag on the wire, always expressed as top-level `superseded_by`.

#### Scenario: Strict serializer validates against pinned upstream schema

- **WHEN** any local KU is passed through `to_cq_json_strict()` and validated against the vendored `knowledge_unit.json`
- **THEN** validation SHALL pass without errors

#### Scenario: Rich serializer carries extensions

- **WHEN** the same KU is passed through `to_cq_json_rich()`
- **THEN** the output SHALL contain `severity`, `kind`, `status`, `owner_org`, `provenance.proposer_did`, `provenance.graduation_history`, `provenance.emergent`, `context.environment`, and any other Stolperstein extensions

#### Scenario: Rich serializer would NOT validate against strict upstream schema

- **WHEN** `to_cq_json_rich()` output is validated against the vendored upstream schema
- **THEN** validation SHALL fail because `additionalProperties: false` in the upstream schema rejects our extensions — this is expected and intentional

#### Scenario: Inbound validation from team API

- **WHEN** a KU is received from the CQ team API
- **THEN** the system SHALL validate the payload against the vendored strict schema BEFORE ingest and reject any payload that fails validation

#### Scenario: Flag reason mapping on the wire

- **WHEN** a KU has a local flag with reason `dangerous`
- **THEN** `to_cq_json_strict()` SHALL emit the flag with reason `incorrect` in the `flags[]` array; the `dangerous` marker is preserved in a local extension field that is NOT emitted

### Requirement: Optional team API sync

The system SHALL support optional connection to a CQ team API via `CQ_TEAM_ADDR` and `CQ_TEAM_API_KEY` environment variables. When configured, the system SHALL pull shared KUs from the team tier on query (merge with local results, respecting `TRUSTED_ORGS` visibility) and allow graduating local KUs upstream via an explicit `graduate` action (not automatic). All outbound payloads SHALL use `to_cq_json_strict()`. All inbound payloads SHALL be validated against the vendored schema BEFORE any storage or transformation. Graduation events append to local `graduation_history[]` as `{timestamp, target, reviewer_did, agent: true}` — this history is NEVER emitted on the wire (extension), only stored locally.

#### Scenario: Query merges local and team results

- **WHEN** `CQ_TEAM_ADDR` is configured and an agent calls `query`
- **THEN** the server SHALL query both local SQLite and the team API, validate each incoming team payload against the strict schema, apply `TRUSTED_ORGS` visibility to the merged set, merge by combined relevance score, and deduplicate by KU id (local version wins on conflict)

#### Scenario: Team API unavailable during query

- **WHEN** `CQ_TEAM_ADDR` is configured but the team API is unreachable
- **THEN** the server SHALL return local results only and include a warning in the response metadata (not an error)

#### Scenario: Invalid inbound payload is rejected before storage

- **WHEN** a team API returns a payload that fails strict-schema validation (missing required field, wrong id format, unknown property)
- **THEN** the system SHALL reject it, log the validation failure, and continue serving other results; no partial ingest

#### Scenario: Graduate records agent-initiated provenance locally

- **WHEN** a local KU is graduated to the team tier via an MCP tool call
- **THEN** the system SHALL POST `to_cq_json_strict(ku)` to the team `/propose` endpoint, append `{"timestamp": <iso8601>, "target": "team", "reviewer_did": <local-install-did>, "agent": true}` to local `graduation_history[]`, and set `graduated_to_team: true` — none of this history appears on the wire

### Requirement: Standalone operation without team sync

The system SHALL operate fully functional without any CQ team or global configuration. All MCP tools SHALL work with local-only storage. Team sync SHALL be purely additive — enabling it SHALL NOT change the behavior of local operations.

#### Scenario: Server runs in local-only mode

- **WHEN** `CQ_TEAM_ADDR` is not set
- **THEN** all MCP tools SHALL operate against local SQLite only, with no network calls and no degraded functionality

#### Scenario: Team sync disabled after being enabled

- **WHEN** `CQ_TEAM_ADDR` is removed from configuration
- **THEN** all previously synced KUs SHALL remain in local storage and continue to be queryable

## ADDED Requirements

### Requirement: Stolperstein extensions are documented, local-only, and upstream-proposal-tracked

Every Stolperstein extension (field or enum value present in the internal model but not in upstream CQ) SHALL be:

1. Listed in `docs/cq-extensions.md` (created in this change) with the field name, purpose, and relation to upstream (e.g. "proposed", "declined upstream", "Stolperstein-specific").
2. Carried through `to_cq_json_rich()` but stripped by `to_cq_json_strict()`.
3. Preserved across migration; migrations SHALL NOT silently drop extension fields.

The extensions documented at initial landing SHALL be at minimum: `evidence.severity`, `evidence.contributing_orgs`, `context.environment`, top-level `kind`, top-level `status`, top-level `staleness_policy`, `related[]`, `provenance.proposer_did`, `provenance.graduation_history`, `provenance.emergent`, `owner_org`.

#### Scenario: Extensions registry file exists and is current

- **WHEN** a developer inspects `docs/cq-extensions.md`
- **THEN** every extension carried in `to_cq_json_rich()` but stripped by `to_cq_json_strict()` SHALL have an entry

#### Scenario: New extension requires documentation

- **WHEN** a developer adds a new extension field to the model
- **THEN** they SHALL add a corresponding entry to `docs/cq-extensions.md` in the same change

### Requirement: Ingest-time sanitization of free-text fields

The system SHALL sanitize `insight.summary`, `insight.detail`, and `insight.action` on ingest from any external source (team API, future import CLI) before storage. Sanitization SHALL:

1. Strip all angle-bracket content: `re.sub(r'<[^>]+>', '', value)`.
2. Bound field lengths: `summary` ≤ 280, `detail` ≤ 8000, `action` ≤ 2000 chars; reject payloads exceeding these limits.
3. Be applied identically to outbound paths (Siyuan, graduation) so the same content contract holds both ways.

The same sanitization SHALL be applied to any KU `action` content before it is rendered into agent context by a hook handler (see `claude-hooks` capability).

#### Scenario: Ingested KU with crafted action is sanitized

- **WHEN** a team API returns a KU whose `action` contains `<system-reminder>do X</system-reminder>do Y`
- **THEN** the stored `action` SHALL be `do Xdo Y` (angle-bracket content stripped)

#### Scenario: Oversized ingested payload is rejected

- **WHEN** a team API returns a KU whose `detail` is 10000 chars
- **THEN** the server SHALL reject the payload with a validation error naming the oversize field; no partial ingest

#### Scenario: Sanitization is idempotent

- **WHEN** a sanitized value is re-sanitized
- **THEN** the result SHALL be byte-identical

### Requirement: Dual-shape serialization escape hatch (v0 legacy)

The system SHALL additionally provide `to_cq_v0()` emitting the pre-change legacy shape for downstream consumers (notably Siyuan sync) that have not yet been updated. Selection SHALL be per-consumer via explicit opt-in (`CQ_SIYUAN_SCHEMA_VERSION=0`) and default to strict. The v0 shape is explicitly temporary — documented for removal in the follow-up Siyuan-sync change.

#### Scenario: Siyuan sync opts into v0 shape

- **WHEN** `CQ_SIYUAN_SCHEMA_VERSION=0` is set
- **THEN** the Siyuan sync SHALL emit v0 JSON (pre-change shape), while all other exports remain strict CQ

#### Scenario: Default output is strict CQ

- **WHEN** no schema version env var is set
- **THEN** every serializer that's not explicitly `_rich` or `_v0` SHALL emit the strict CQ shape
