## ADDED Requirements

### Requirement: One-way push of active KUs to Siyuan

The system SHALL push active KUs to a configurable Siyuan notebook as structured documents via the Siyuan API. Sync SHALL be one-way (Stolperstein -> Siyuan) and triggered on KU state changes (propose, confirm, flag). Each KU SHALL be rendered as a single Siyuan document with structured blocks.

#### Scenario: New KU syncs to Siyuan on creation

- **WHEN** a KU is proposed and reaches `active` status (after first confirmation)
- **THEN** the system SHALL create a Siyuan document in the configured notebook with the KU's summary as title and structured blocks for detail, action, domain tags, confidence, and metadata

#### Scenario: KU update syncs to Siyuan

- **WHEN** an active KU's confidence changes (via confirm or flag)
- **THEN** the system SHALL update the existing Siyuan document to reflect the new confidence and status

#### Scenario: Archived KU removed from Siyuan

- **WHEN** a KU transitions to `archived` status
- **THEN** the system SHALL move the Siyuan document to a "Archived" sub-section or delete it (configurable via `CQ_SIYUAN_ARCHIVE_MODE`)

### Requirement: Siyuan sync is optional and non-blocking

Siyuan sync SHALL be enabled only when `CQ_SIYUAN_URL` and `CQ_SIYUAN_NOTEBOOK` environment variables are set. Sync failures SHALL be logged but SHALL NOT block or fail the MCP tool response. Sync SHALL run asynchronously after the tool response is sent.

#### Scenario: Siyuan not configured

- **WHEN** `CQ_SIYUAN_URL` is not set
- **THEN** all MCP tools SHALL operate normally with no Siyuan-related behavior or errors

#### Scenario: Siyuan API unreachable

- **WHEN** `CQ_SIYUAN_URL` is configured but the Siyuan instance is unreachable
- **THEN** the MCP tool response SHALL succeed normally and the system SHALL log the sync failure for retry

### Requirement: Siyuan document structure

Each synced KU document SHALL follow a consistent structure: title (summary), domain tags as Siyuan tags, a "Problem" section (detail), an "Action" section (action), a metadata block (confidence, confirmations, kind, status, timestamps), and links to related KUs if any.

#### Scenario: KU renders with full structure

- **WHEN** a KU with domain `["swift", "xcode"]`, kind `pitfall`, confidence 0.75, and 3 confirmations syncs to Siyuan
- **THEN** the Siyuan document SHALL contain: title from summary, `#swift` and `#xcode` tags, Problem heading with detail text, Action heading with action text, and a metadata block showing confidence 0.75, 3 confirmations, kind pitfall
