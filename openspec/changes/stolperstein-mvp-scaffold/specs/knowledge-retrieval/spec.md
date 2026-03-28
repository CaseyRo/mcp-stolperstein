## ADDED Requirements

### Requirement: query tool performs hybrid search

The `query` tool SHALL accept a `text` query (required), optional `domain` filter (array of tags), optional `confidence_min` (float, default 0.3), and optional `limit` (int, default 10). It SHALL return KUs ranked by a weighted combination of FTS5 relevance and sqlite-vec cosine similarity.

#### Scenario: Agent queries by natural language

- **WHEN** an agent calls `query` with text "Swift concurrency strict checking Xcode 16"
- **THEN** the server SHALL return KUs matching via both FTS5 keyword relevance and vector similarity, ranked by combined score, excluding KUs below `confidence_min`

#### Scenario: Agent queries with domain filter

- **WHEN** an agent calls `query` with text "websocket reconnection" and domain `["homeassistant"]`
- **THEN** the server SHALL return only KUs whose `domain` array contains "homeassistant", ranked by relevance

#### Scenario: Query returns no results

- **WHEN** an agent calls `query` with text that matches no KUs above the confidence threshold
- **THEN** the server SHALL return an empty results array (not an error)

### Requirement: SQLite storage with FTS5 and sqlite-vec

The system SHALL store KUs in a SQLite database with three linked tables: `knowledge_units` (core fields), `ku_fts` (FTS5 virtual table on summary + detail + action), and `ku_embeddings` (sqlite-vec for vector similarity search). All writes SHALL be atomic within a single transaction.

#### Scenario: Database initialization on first run

- **WHEN** the server starts and `CQ_LOCAL_DB_PATH` points to a non-existent file
- **THEN** the server SHALL create the database file and all three tables with correct schemas and indexes

#### Scenario: Concurrent read during write

- **WHEN** one request writes a new KU while another request queries
- **THEN** the query SHALL see a consistent snapshot (WAL mode) and not block on the write

### Requirement: Embedding generation on propose

The system SHALL generate a vector embedding for each KU at propose time, using the concatenation of `summary + detail + action` as input. The embedding model SHALL be configurable via `CQ_EMBEDDING_MODEL` environment variable.

#### Scenario: Embedding generated on propose

- **WHEN** a new KU is proposed
- **THEN** the server SHALL generate an embedding vector and store it in `ku_embeddings` within the same transaction as the KU insert

#### Scenario: Embedding model unavailable

- **WHEN** the configured embedding model is unreachable or errors
- **THEN** the server SHALL still create the KU (with FTS5 indexing) and log a warning, marking the embedding as pending for retry
