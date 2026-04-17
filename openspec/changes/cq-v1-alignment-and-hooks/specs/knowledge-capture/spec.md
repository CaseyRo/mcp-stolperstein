## MODIFIED Requirements

### Requirement: MCP server exposes 6 tools via FastMCP

The system SHALL expose exactly 6 MCP tools via a FastMCP server: `query`, `propose`, `confirm`, `flag`, `reflect`, and `status`. The server SHALL communicate via stdio transport for Claude Code and HTTP/SSE for remote clients. Tool signatures SHALL be v1 CQ-shaped with flat parameters (no nested objects on the MCP surface). Tool annotations SHALL be honest: `confirm` and `flag` SHALL be annotated `idempotentHint=False` because they mutate counters and history on each call.

#### Scenario: Agent discovers all tools on connection

- **WHEN** a Claude Code session connects to the MCP server
- **THEN** the server SHALL advertise all 6 tools with typed input schemas reflecting the v1 shape (flat `context_*` params on `propose`, no `severity_min` on `query`)

#### Scenario: Server starts successfully

- **WHEN** the server process starts with a valid `CQ_LOCAL_DB_PATH`
- **THEN** it SHALL run pending migrations, initialize the SQLite database, load the install's DID from `install_identity` (or generate one via m0002), and begin accepting MCP requests within 5 seconds

#### Scenario: confirm and flag are annotated non-idempotent

- **WHEN** the tool catalogue is introspected
- **THEN** `confirm` and `flag` SHALL carry `idempotentHint=False`

### Requirement: propose tool captures new Knowledge Units

The `propose` tool SHALL accept required fields `summary` (string, max 280 chars), `detail` (string), `action` (string), `domains` (array of tags, min 1 element — upstream-conformant name), and `kind` (enum: `pitfall`, `workaround`, `tool-recommendation` — Stolperstein extension). It SHALL accept optional `context_languages` (array), `context_frameworks` (array), `context_environment` (string — extension), `context_pattern` (string), and `severity` (enum: `low`, `medium`, `high`, `critical`, default `medium` — extension) as FLAT parameters (not a nested object). For backward-compatibility, `domain` SHALL be accepted as an alias for `domains` and silently promoted. The tool SHALL return the created KU with a generated `id` matching `^ku_[0-9a-f]{32}$`, initial confidence 0.5, `provenance.proposer_did` set to the install's DID, `owner_org` set to the install's DID, and empty `graduation_history`. Docstring SHALL include inline examples, mark which fields are strict CQ vs Stolperstein extension, and list valid `kind` values (no `gap-signal`).

#### Scenario: Agent proposes a valid KU with context and severity

- **WHEN** an agent calls `propose` with all required fields plus `context_languages=["swift"]`, `context_frameworks=["swiftui"]`, `context_environment="xcode-16"`, `context_pattern="concurrency"`, `severity="high"`
- **THEN** the server SHALL create a KU with the flat params assembled into a nested `context` object in the response, confidence 0.5, status `draft`, `provenance.proposer_did` set, `owner_org` set, and severity stored

#### Scenario: Agent proposes a minimal KU without optional fields

- **WHEN** an agent calls `propose` with only required fields
- **THEN** the server SHALL accept the KU with context fields `null`, severity defaulted to `medium`, and still stamp `provenance.proposer_did` and `owner_org`

#### Scenario: Propose rejects deprecated gap-signal with recovery hint

- **WHEN** an agent calls `propose` with `kind="gap-signal"`
- **THEN** the server SHALL raise `McpError(InvalidParams, "kind 'gap-signal' is no longer proposable in CQ v1. Tool gaps are detected automatically from query-miss patterns. To capture this insight, use kind='workaround' or kind='pitfall' and describe the gap in the detail field.")`

#### Scenario: Duplicate detection on propose

- **WHEN** an agent proposes a KU whose summary has >0.9 cosine similarity to an existing active KU
- **THEN** the server SHALL return the existing KU's id and a `duplicate_of` field instead of creating a new entry

### Requirement: confirm tool validates existing KUs

The `confirm` tool SHALL accept a `ku_id` and increment the KU's `confirmations` count by 1, update `last_confirmed_at` timestamp, and recalculate confidence score. It SHALL NOT modify `provenance.graduation_history`. On lookup miss, it SHALL raise `McpError(InvalidParams, ...)` with a recovery hint directing the caller to `query()`.

#### Scenario: Agent confirms a KU it previously queried

- **WHEN** an agent calls `confirm` with a valid `ku_id` for an active KU
- **THEN** the server SHALL increment `confirmations`, update `last_confirmed_at` to now, recalculate and persist confidence, and return the updated KU

#### Scenario: Agent confirms a non-existent KU

- **WHEN** an agent calls `confirm` with an id that does not exist
- **THEN** the server SHALL raise `McpError(InvalidParams, "KU not found: {ku_id}. Call query() first to obtain a valid ku_id.")`

### Requirement: flag tool marks KUs as disputed or stale

The `flag` tool SHALL accept a `ku_id`, a `reason` (enum: `stale`, `incorrect`, `superseded`, `dangerous`), an optional `detail` string, and an optional `superseded_by` KU id. When reason is `superseded`, the server SHALL set the top-level `superseded_by` column to the provided id and transition status to `archived`. For `incorrect` or `dangerous`, the server SHALL set status to `disputed` and cap confidence at 0.5. On lookup miss, it SHALL raise `McpError(InvalidParams, ...)` with a recovery hint.

#### Scenario: Agent flags a KU as incorrect

- **WHEN** an agent calls `flag` with reason `incorrect` and a detail string
- **THEN** the server SHALL set status to `disputed`, cap confidence at 0.5, and record the flag reason

#### Scenario: Agent flags a KU as superseded

- **WHEN** an agent calls `flag` with reason `superseded` and a `superseded_by` id
- **THEN** the server SHALL set status to `archived`, write the superseding id to the top-level `superseded_by` column (not to `related[]`)

#### Scenario: Flag on unknown KU returns McpError

- **WHEN** an agent calls `flag` with a non-existent `ku_id`
- **THEN** the server SHALL raise `McpError(InvalidParams, "KU not found: {ku_id}. Call query() first to obtain a valid ku_id.")`

### Requirement: reflect tool extracts session learnings

The `reflect` tool SHALL accept a session summary (free text) and return a ranked list of candidate KUs extracted from the session, scored by generalizability. Each candidate SHALL carry pre-filled flat `context_*` and `severity` fields when inferable from the summary, so the caller can pass them directly to `propose()` without re-reading docs. Docstring SHALL note this round-trip convenience.

#### Scenario: End-of-session reflection

- **WHEN** an agent calls `reflect` with a session summary
- **THEN** the server SHALL return 0-N candidates, each with `generalizability_score`, pre-filled `summary`, `detail`, `action`, `domain`, `kind` (never `gap-signal`), best-effort flat `context_*`, and best-effort `severity`

#### Scenario: Reflection with no generalizable learnings

- **WHEN** an agent calls `reflect` with a summary containing only project-specific decisions
- **THEN** the server SHALL return an empty candidates list

### Requirement: status tool reports store health

The `status` tool SHALL accept an optional `debug: bool = False` parameter and return store statistics. Default response (token-frugal): `total`, `by_status`, `confidence_distribution`, `staleness`, and `tool_gap_signals` partitioned into `grandfathered` (provenance.emergent=false) and `emergent` (true). Debug response additionally SHALL include `schema_version`, `proposer_did`, applied migration list, hook state-file summary, and `query_misses` rolling-window stats.

#### Scenario: Default status call is token-frugal

- **WHEN** an agent calls `status()` with no arguments
- **THEN** the response SHALL NOT include `proposer_did` or `schema_version`

#### Scenario: Debug status surfaces operator detail

- **WHEN** an operator calls `status(debug=True)`
- **THEN** the response SHALL include `schema_version`, `proposer_did`, applied migrations, and hook state summary
