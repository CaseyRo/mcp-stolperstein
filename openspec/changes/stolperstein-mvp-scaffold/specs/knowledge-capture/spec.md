## ADDED Requirements

### Requirement: MCP server exposes 6 tools via FastMCP

The system SHALL expose exactly 6 MCP tools via a FastMCP server: `query`, `propose`, `confirm`, `flag`, `reflect`, and `status`. The server SHALL communicate via stdio transport for Claude Code and HTTP/SSE for remote clients.

#### Scenario: Agent discovers all tools on connection

- **WHEN** a Claude Code session connects to the MCP server
- **THEN** the server SHALL advertise all 6 tools with typed input schemas and descriptions

#### Scenario: Server starts successfully

- **WHEN** the server process starts with a valid `CQ_LOCAL_DB_PATH`
- **THEN** it SHALL initialize the SQLite database (creating tables if absent) and begin accepting MCP requests within 5 seconds

### Requirement: propose tool captures new Knowledge Units

The `propose` tool SHALL accept a KU with required fields: `summary` (string, max 280 chars), `detail` (string), `action` (string), `domain` (array of tags), and `kind` (enum: pitfall, workaround, tool-recommendation, gap-signal). It SHALL return the created KU with a generated `id` (format: `ku_[alphanumeric]`) and initial confidence of 0.5.

#### Scenario: Agent proposes a valid KU

- **WHEN** an agent calls `propose` with summary "Xcode 16 requires explicit Swift 6 concurrency opt-in", detail text, action text, domain `["swift", "xcode"]`, and kind `pitfall`
- **THEN** the server SHALL create a KU with a unique `ku_*` id, confidence 0.5, status `draft`, `confirmations` 0, and timestamps for `first_observed` and `last_confirmed`

#### Scenario: Agent proposes a KU with missing required fields

- **WHEN** an agent calls `propose` without a `summary` field
- **THEN** the server SHALL return an MCP error with a descriptive message indicating the missing field

#### Scenario: Duplicate detection on propose

- **WHEN** an agent proposes a KU whose summary has >0.9 cosine similarity to an existing active KU
- **THEN** the server SHALL return the existing KU's id and a `duplicate_of` field instead of creating a new entry

### Requirement: confirm tool validates existing KUs

The `confirm` tool SHALL accept a `ku_id` and increment the KU's `confirmations` count by 1, update `last_confirmed` timestamp, and recalculate confidence score.

#### Scenario: Agent confirms a KU it previously queried

- **WHEN** an agent calls `confirm` with a valid `ku_id` for an active KU
- **THEN** the server SHALL increment `confirmations`, update `last_confirmed` to now, and return the updated confidence score

#### Scenario: Agent confirms a non-existent KU

- **WHEN** an agent calls `confirm` with an id that does not exist
- **THEN** the server SHALL return an MCP error with "KU not found"

### Requirement: flag tool marks KUs as disputed or stale

The `flag` tool SHALL accept a `ku_id` and a `reason` (enum: `stale`, `incorrect`, `superseded`, `dangerous`) with an optional `detail` string. It SHALL update the KU's status and cap confidence at 0.5 for disputed entries.

#### Scenario: Agent flags a KU as incorrect

- **WHEN** an agent calls `flag` with a valid `ku_id`, reason `incorrect`, and detail "This workaround no longer applies after HA 2025.4"
- **THEN** the server SHALL set the KU's status to `disputed`, cap confidence at 0.5, and record the flag reason and detail

#### Scenario: Agent flags a KU as superseded

- **WHEN** an agent calls `flag` with reason `superseded` and a `superseded_by` ku_id
- **THEN** the server SHALL set status to `archived`, add a `related` entry of type `superseded_by`, and return the superseding KU

### Requirement: reflect tool extracts session learnings

The `reflect` tool SHALL accept a session summary (free text) and return a ranked list of candidate KUs extracted from the session, scored by generalizability (would this help a different agent on a different project?).

#### Scenario: End-of-session reflection

- **WHEN** an agent calls `reflect` with a summary of problems solved and workarounds applied during a session
- **THEN** the server SHALL return 0-N candidate KUs, each with a `generalizability_score` (0.0-1.0), pre-filled `summary`, `detail`, `action`, `domain`, and `kind` fields ready for the agent to call `propose` on

#### Scenario: Reflection with no generalizable learnings

- **WHEN** an agent calls `reflect` with a session summary containing only project-specific decisions (no reusable patterns)
- **THEN** the server SHALL return an empty candidates list

### Requirement: status tool reports store health

The `status` tool SHALL accept no arguments and return store statistics: total KU count, counts by status (draft, active, stale, disputed, archived), confidence distribution (mean, median, p25, p75), and staleness metrics (count approaching decay threshold, count past threshold).

#### Scenario: Agent queries store status

- **WHEN** an agent calls `status` with no arguments
- **THEN** the server SHALL return a JSON object with `total`, `by_status`, `confidence_distribution`, and `staleness` fields
