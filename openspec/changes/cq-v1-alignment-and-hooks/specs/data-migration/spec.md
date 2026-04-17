## ADDED Requirements

### Requirement: Versioned migration framework

The system SHALL maintain a `schema_version` single-row table recording the highest applied migration id. The system SHALL register migrations as Python modules under `src/stolperstein/migrations/` named `mNNNN_<slug>.py`, each exposing a `version: int` constant, a `breaking: bool` constant, and an `up(conn: sqlite3.Connection) -> None` function. The migration runner SHALL apply all registered migrations whose version is greater than the stored `schema_version`, in ascending order, in a single transaction per migration, updating `schema_version` at the end of each.

#### Scenario: Fresh database bootstraps to the latest version

- **WHEN** the server starts against a non-existent DB file
- **THEN** the runner SHALL create the DB, apply every registered migration in order, and leave `schema_version` equal to the highest registered version

#### Scenario: Existing v0 database migrates forward

- **WHEN** the server starts against a DB whose `schema_version` is absent (treated as 0)
- **THEN** the runner SHALL apply every registered migration in order, each in its own transaction, stamping `schema_version` after each success

#### Scenario: Migration fails mid-application

- **WHEN** a migration raises during `up()`
- **THEN** the transaction SHALL be rolled back, `schema_version` SHALL remain at its pre-migration value, and the server SHALL refuse to start with a clear error

#### Scenario: Re-applying an already-applied migration is a no-op

- **WHEN** the server starts against a DB whose `schema_version` already equals or exceeds a migration's version
- **THEN** that migration SHALL be skipped silently

### Requirement: Pre-migration snapshot for breaking changes

The migration runner SHALL take a file-copy snapshot of the database at `<db_path>.bak-pre-v<target>` before applying any migration marked `breaking=True` (renames, removes, retypes). Snapshots SHALL NOT be taken for purely additive migrations. Snapshot files SHALL be preserved until an operator deletes them via the `prune-backups` CLI — the system SHALL never auto-clean. The runner SHALL refuse to overwrite an existing snapshot.

#### Scenario: Breaking migration takes a backup

- **WHEN** `m0001_cq_v1_layout` (breaking=True) runs
- **THEN** the runner SHALL copy the DB to `<db_path>.bak-pre-v1` before opening the migration transaction

#### Scenario: Additive migration skips backup

- **WHEN** a future migration marked `breaking=False` runs
- **THEN** no snapshot SHALL be taken

#### Scenario: Backup exists from a prior aborted attempt

- **WHEN** a `.bak-pre-v<N>` file already exists at migration time
- **THEN** the runner SHALL refuse to overwrite it, raise an error naming the file, and require operator intervention

### Requirement: Private-key material SHALL NOT be stored in the SQLite DB

The `install_identity` table SHALL hold only `did TEXT PRIMARY KEY`, `public_key BLOB NOT NULL`, and `created_at TEXT NOT NULL`. The Ed25519 private key SHALL be stored at `/data/stolperstein.key` as raw bytes with filesystem permissions `0o600` owned by the `mcp` user, OR provided at boot via the `MCP_STOLPERSTEIN_SIGNING_KEY` environment variable (base64-encoded). Pre-migration `.bak-pre-v*` files SHALL NOT contain the private key (since the key lives outside the DB). Documentation SHALL list `stolperstein.key` as a sensitive file to exclude from volume backups and `docker cp`.

#### Scenario: install_identity has no private_key column

- **WHEN** the schema is introspected after `m0002_provenance_and_org` runs
- **THEN** the `install_identity` table SHALL have columns `did`, `public_key`, `created_at` only

#### Scenario: Private key file is created with restrictive permissions

- **WHEN** `m0002_provenance_and_org` generates a keypair
- **THEN** `/data/stolperstein.key` SHALL exist with mode `0o600` and be owned by the process user (`mcp` in production)

#### Scenario: Env var overrides file-based key

- **WHEN** `MCP_STOLPERSTEIN_SIGNING_KEY` is set and the server starts
- **THEN** the server SHALL decode the base64 value as the signing key and SHALL NOT read `/data/stolperstein.key`

#### Scenario: Backup files exclude the private key

- **WHEN** a pre-migration snapshot is taken
- **THEN** the `.bak-pre-v<N>` file SHALL contain only the SQLite DB, not the `stolperstein.key` file

### Requirement: v0-to-v1 data transformation

The migration chain `m0000` → `m0005` SHALL transform an existing v0 database without data loss. Specific responsibilities:

**`m0000_ku_id_format_fix` (breaking=True):**

1. For every row whose `id` matches `^ku_[0-9a-f]{1,31}$` (legacy shorter hex), compute `new_id = "ku_" + old_id[3:].zfill(32)` — pad with leading zeros to reach 32 hex chars.
2. Rewrite `id` on the row, then rewrite every reference: scan `related` JSON for any `target_id` matching an old id and rewrite to the padded form; rewrite `superseded_by` references if present in any existing column.
3. Rewrite FTS5 and `ku_embeddings` rows (or rebuild them) to point at the new ids.
4. Leave rows that already match `^ku_[0-9a-f]{32}$` untouched.

**`m0001_cq_conformance_rename` (breaking=True):**

1. Rename column `domain` → `domains` (keeps JSON-array content; wire format needs the plural name).
2. Add columns: `last_confirmed_at TEXT`, `superseded_by TEXT NULL`, `context_languages TEXT NOT NULL DEFAULT '[]'`, `context_frameworks TEXT NOT NULL DEFAULT '[]'`, `context_pattern TEXT NULL`.
3. Copy `last_confirmed` values into `last_confirmed_at` for every row.
4. For every row whose `related` JSON contains an entry with `type="superseded_by"`, move the `target_id` of the most recent such entry into the new `superseded_by` column and remove all such entries from the array.
5. Drop the `last_confirmed` column via temp-table swap (preserves FTS5 content linkage).

**`m0002_stolperstein_extensions` (breaking=True):**

1. Add extension columns that are NOT in upstream CQ: `evidence_severity TEXT NOT NULL DEFAULT 'medium'`, `context_environment TEXT NULL`.
2. `kind`, `status`, `staleness_policy`, `related` already exist from v0 — no-op for those (they become Stolperstein extensions in the new framing).

**`m0003_provenance_and_org` (breaking=True):**

1. Create `install_identity` (cols: `did TEXT PRIMARY KEY`, `public_key BLOB NOT NULL`, `created_at TEXT NOT NULL` — NO private_key column).
2. Generate a new Ed25519 keypair, derive `did:key:...`, persist `did` + `public_key` in `install_identity`, write the private key to `/data/stolperstein.key` (mode 0o600) OR read it from `MCP_STOLPERSTEIN_SIGNING_KEY` env var.
3. Add columns: `proposer_did TEXT`, `graduation_history TEXT NOT NULL DEFAULT '[]'`, `provenance_emergent INTEGER NULL`, `owner_org TEXT`.
4. Backfill `proposer_did` AND `owner_org` for every existing row with the install's DID.

**`m0004_gap_signal_rename` (breaking=False):**

1. UPDATE every row with `kind='gap-signal'` to `kind='tool-gap-signal'` and set `provenance_emergent=0` (grandfathered).

**`m0005_emergent_scaffolding` (breaking=False):**

1. Create `query_misses` table (cols: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `text TEXT NOT NULL`, `embedding BLOB`, `created_at TEXT NOT NULL`).
2. Create index on `created_at` for TTL-based cleanup.

#### Scenario: Existing 24-hex id is padded to 32

- **WHEN** a row in v0 had `id='ku_a1b2c3d4e5f6a1b2c3d4e5f6'` (24 hex)
- **THEN** after m0000, the row SHALL have `id='ku_00000000a1b2c3d4e5f6a1b2c3d4e5f6'` (32 hex, leading zeros), and any other row referencing that id in `related[].target_id` SHALL be rewritten to the new form in the same transaction

#### Scenario: Already-conformant id is untouched

- **WHEN** a row has `id='ku_' + <32 hex>`
- **THEN** m0000 SHALL NOT modify that row

#### Scenario: Existing row gains last_confirmed_at

- **WHEN** a row in v0 had `last_confirmed='2026-03-10T12:00:00+00:00'`
- **THEN** after m0001, the row SHALL have `last_confirmed_at='2026-03-10T12:00:00+00:00'` and no `last_confirmed` column

#### Scenario: domain is renamed to domains

- **WHEN** a row in v0 had column `domain='["swift","xcode"]'`
- **THEN** after m0001, the row SHALL have column `domains='["swift","xcode"]'` (same content, new column name)

#### Scenario: Existing supersedence edge migrates

- **WHEN** a row in v0 had `related=[{"type":"superseded_by","target_id":"ku_abc..."}]`
- **THEN** after m0001, `superseded_by='ku_abc...'` and the `superseded_by`-typed entry is removed from `related`

#### Scenario: Install DID is generated exactly once

- **WHEN** m0003 runs against a DB with no `install_identity` row
- **THEN** a new Ed25519 keypair SHALL be generated, `install_identity` SHALL contain exactly one row with `did` and `public_key` (no `private_key`), and `/data/stolperstein.key` SHALL contain the private key with mode 0o600

#### Scenario: owner_org backfills to install DID

- **WHEN** m0003 runs against a DB with existing KUs
- **THEN** every KU's `owner_org` SHALL equal the newly generated install DID

#### Scenario: gap-signal rows survive as grandfathered

- **WHEN** m0004 runs against a DB containing a `kind='gap-signal'` row
- **THEN** the row SHALL have `kind='tool-gap-signal'` and `provenance_emergent=0`, with every other field preserved

#### Scenario: query_misses scaffolding

- **WHEN** m0005 runs
- **THEN** a `query_misses` table with cols `id, text, embedding, created_at` and an index on `created_at` SHALL exist

### Requirement: CLI entrypoints for manual migration operations

The project SHALL provide two CLI subcommands:

1. `mcp-stolperstein migrate` — runs the migration runner against `CQ_LOCAL_DB_PATH` without starting the server; prints `from → to` version transition and each migration as it applies; exits non-zero on failure. Honors `CQ_LOCAL_DB_PATH` env but SHALL NOT accept an arbitrary `--db-path` override pointing outside `/data/` (security boundary).
2. `mcp-stolperstein prune-backups --confirm` — lists `.bak-pre-v*` files in the DB directory, prompts (or accepts `--confirm`), and deletes them. Without `--confirm`, operates in dry-run mode listing what would be deleted.

#### Scenario: Operator runs migrate against production DB

- **WHEN** an operator runs `mcp-stolperstein migrate` on a DB at schema_version 0
- **THEN** the command SHALL print a summary, leave the DB at `schema_version=5`, and exit 0

#### Scenario: Migrate is idempotent

- **WHEN** the operator runs `mcp-stolperstein migrate` a second time
- **THEN** the command SHALL print `already at version 5` and exit 0 without touching the DB

#### Scenario: Prune-backups dry-run

- **WHEN** the operator runs `mcp-stolperstein prune-backups` without `--confirm`
- **THEN** the command SHALL list `.bak-pre-v*` files and exit 0 without deleting anything

#### Scenario: Prune-backups deletes with confirmation

- **WHEN** the operator runs `mcp-stolperstein prune-backups --confirm`
- **THEN** the command SHALL delete all `.bak-pre-v*` files and print what was removed

### Requirement: Migration runs on server boot

The MCP server SHALL run the migration runner as the first action inside `_get_db()` (before any other DDL), so that a single deploy brings the DB forward without requiring the operator to run `migrate` separately.

#### Scenario: Container restart applies pending migrations

- **WHEN** a new container image is deployed against a volume holding a pre-migration DB
- **THEN** the server SHALL run pending migrations before accepting any MCP request, and `status(debug=True)` SHALL report the new `schema_version`
