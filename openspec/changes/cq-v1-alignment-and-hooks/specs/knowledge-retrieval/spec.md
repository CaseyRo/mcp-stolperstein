## MODIFIED Requirements

### Requirement: query tool performs hybrid search

The `query` tool SHALL accept a `text` query (required), optional `domain` filter (array of tags), optional `confidence_min` (float, default 0.3), and optional `limit` (int, default 10). It SHALL return KUs ranked by a weighted combination of FTS5 relevance and sqlite-vec cosine similarity, with `evidence.severity` used as a tiebreaker (critical > high > medium > low at equal rank). The tool SHALL NOT accept a `severity_min` filter parameter; callers who need severity-gated results filter client-side. Each returned KU SHALL include the full v1 CQ shape (`insight`, `context`, `evidence`, `provenance`, top-level `superseded_by`, `owner_org`). Docstring SHALL explicitly describe the `domain`, `confidence_min`, and `limit` parameters with guidance on when to override defaults.

#### Scenario: Agent queries by natural language

- **WHEN** an agent calls `query` with text "Swift concurrency strict checking Xcode 16"
- **THEN** the server SHALL return KUs matching via both FTS5 keyword relevance and vector similarity, ranked by combined score, excluding KUs below `confidence_min`, with each result including `context`, `evidence.severity`, `provenance`, and `owner_org`

#### Scenario: Agent queries with domain filter

- **WHEN** an agent calls `query` with text "websocket reconnection" and domain `["homeassistant"]`
- **THEN** the server SHALL return only KUs whose `domain` array contains "homeassistant", ranked by relevance with severity as tiebreaker

#### Scenario: Severity tiebreaker at equal rank

- **WHEN** two KUs have identical combined rank scores but differing severity
- **THEN** the KU with higher severity (critical > high > medium > low) SHALL appear first

#### Scenario: Query returns no results

- **WHEN** an agent calls `query` with text that matches no KUs above the confidence threshold
- **THEN** the server SHALL return an empty results array (not an error) AND SHALL record the miss in the `query_misses` rolling table for emergent-signal detection

### Requirement: SQLite storage with FTS5 and sqlite-vec

The system SHALL store KUs in a SQLite database with tables: `knowledge_units` (core fields including `last_confirmed_at`, `superseded_by`, `evidence_severity`, `context_environment`, `context_pattern`, `owner_org`, `proposer_did`, `provenance_emergent`; JSON columns for `domains`, `context_languages`, `context_frameworks`, `contributing_orgs`, `related`, `graduation_history`), `ku_fts` (FTS5 virtual table on summary + detail + action), `ku_embeddings` (sqlite-vec for vector similarity), `schema_version` (single-row table), `install_identity` (single-row, holds DID + public key only — never the private key), and `query_misses` (rolling table feeding emergent-signal detection). All writes SHALL be atomic within a single transaction. Schema changes SHALL only happen via registered migrations.

#### Scenario: Database initialization on first run

- **WHEN** the server starts and `CQ_LOCAL_DB_PATH` points to a non-existent file
- **THEN** the server SHALL create the database file, apply all registered migrations in order, write the public key + DID to `install_identity`, write the private key to the separate `/data/stolperstein.key` file with `chmod 600`, and leave `schema_version` at the highest migration id

#### Scenario: Install identity never co-locates private key

- **WHEN** the installer inspects `install_identity` rows
- **THEN** the row SHALL contain `did` and `public_key` only; there SHALL be no `private_key` column

#### Scenario: Concurrent read during write

- **WHEN** one request writes a new KU while another request queries
- **THEN** the query SHALL see a consistent snapshot (WAL mode) and not block on the write

### Requirement: Embedding generation on propose

The system SHALL generate a vector embedding for each KU at propose time using the concatenation of `summary + " " + detail + " " + action + " " + (context.pattern if present else "")` as input. Other `context_*` fields SHALL NOT be included in embedding input (too sparse, dilutes signal). The embedding model SHALL be configurable via `CQ_EMBEDDING_MODEL` environment variable.

#### Scenario: Embedding generated on propose

- **WHEN** a new KU is proposed with `context_pattern="concurrency"`
- **THEN** the server SHALL generate an embedding from the insight text plus the pattern string and store it in `ku_embeddings` within the same transaction as the KU insert

#### Scenario: Embedding model unavailable

- **WHEN** the configured embedding model is unreachable or errors
- **THEN** the server SHALL still create the KU (with FTS5 indexing) and log a warning

## ADDED Requirements

### Requirement: query visibility filter via owner_org and TRUSTED_ORGS

The `query` tool SHALL apply an implicit visibility filter based on `owner_org`: a KU is visible IF `owner_org == <local-install-did>` OR `owner_org IN TRUSTED_ORGS` OR `TRUSTED_ORGS == "*"`. The `TRUSTED_ORGS` setting SHALL default to `"*"` (trust-all, preserves current single-install behavior). The filter SHALL be applied BEFORE confidence/severity filtering so filtered-out KUs never enter the result set.

#### Scenario: Default trust-all preserves current behavior

- **WHEN** `TRUSTED_ORGS` is unset (or `"*"`) and an agent calls `query`
- **THEN** the server SHALL return results including any KU regardless of `owner_org`

#### Scenario: Restrictive TRUSTED_ORGS filters non-local KUs

- **WHEN** `TRUSTED_ORGS` is set to `"did:key:zTrustedOrgA,did:key:zTrustedOrgB"` and an agent queries
- **THEN** the server SHALL return only KUs whose `owner_org` matches the local install DID OR is in the trusted list

#### Scenario: Miss is recorded for emergent detection

- **WHEN** a query returns zero visible results above `confidence_min=0.3`
- **THEN** the server SHALL insert a row into `query_misses` (text, timestamp, embedding) for later aggregation
