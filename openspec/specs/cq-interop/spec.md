# cq-interop Specification

## Purpose
TBD - created by archiving change adopt-cq-extensions-slot. Update Purpose after archive.
## Requirements
### Requirement: KU wire format conforms strictly to upstream CQ schema

All Knowledge Units emitted to any external CQ consumer SHALL conform exactly to `mozilla-ai/cq` upstream `schema/knowledge_unit.json` as vendored at a pinned SHA in `tests/fixtures/cq/`. The vendored pin SHALL be a post-[#453](https://github.com/mozilla-ai/cq/pull/453) revision that defines the optional top-level `extensions` object (namespaced keys matching `^[a-z0-9][a-z0-9_-]*:\S+$`). The system SHALL provide two serializers:

- `to_cq_json_strict()`: emits the upstream-valid shape. Stolperfalle extension fields SHALL be emitted inside the `extensions` slot under `stolperstein:*` keys — no longer stripped. Used for external validation and any interop path.
- `to_cq_json_rich()`: emits the internal superset with all Stolperfalle extensions as first-class fields. Used for local dumps, debugging, and extension-aware consumers. Unchanged by this delta.

Strict-mode core field mapping (unchanged):

- Our `domains[]` → upstream `domains[]`.
- Our `version` → upstream `version: 1` integer.
- Our top-level `last_confirmed_at` column → upstream `evidence.last_confirmed`.
- Our top-level `superseded_by` → upstream `superseded_by`.
- Our `provenance.proposer_did` → upstream `created_by`.

Strict-mode extension mapping (new — all under the top-level `extensions` object):

- `evidence.severity` → `extensions["stolperstein:severity"]` (string).
- `evidence.contributing_orgs` → `extensions["stolperstein:contributing_orgs"]` (array; omitted when empty).
- `context.environment` → `extensions["stolperstein:environment"]` (string; omitted when null).
- top-level `kind` → `extensions["stolperstein:kind"]` (string).
- top-level `status` → `extensions["stolperstein:status"]` (string).
- top-level `staleness_policy` → `extensions["stolperstein:staleness_policy"]` (string).
- top-level `related[]` → `extensions["stolperstein:related"]` (array of `{type, target_id}`; omitted when empty).
- top-level `owner_org` → `extensions["stolperstein:owner_org"]` (string, DID).
- `provenance.emergent` → `extensions["stolperstein:emergent"]` (boolean; omitted when null).

The `extensions` object SHALL be omitted entirely when no extension value is present (upstream field is optional). Internal-only fields (`last_queried_at`, `graduated_to_team`) SHALL remain absent from strict output.

#### Scenario: Strict serializer validates against pinned upstream schema

- **WHEN** any local KU is passed through `to_cq_json_strict()` and validated against the re-vendored `knowledge_unit.json`
- **THEN** validation SHALL pass without errors, including with the `extensions` object present

#### Scenario: Extensions ride the slot under namespaced keys

- **WHEN** a KU with severity `high`, kind `pitfall`, and an `owner_org` DID is passed through `to_cq_json_strict()`
- **THEN** the output SHALL contain `extensions["stolperstein:severity"] == "high"`, `extensions["stolperstein:kind"] == "pitfall"`, and `extensions["stolperstein:owner_org"]` equal to the DID, and every `extensions` key SHALL match `^[a-z0-9][a-z0-9_-]*:\S+$`

#### Scenario: Extensions never appear as top-level or nested extra properties

- **WHEN** `to_cq_json_strict()` output is inspected outside the `extensions` object
- **THEN** no Stolperfalle extension field (`severity`, `kind`, `status`, `owner_org`, `staleness_policy`, `related`, `environment`, `contributing_orgs`, `emergent`) SHALL appear at top level or inside `context`/`evidence`/`provenance` sub-objects

#### Scenario: Extension-free KU omits the slot

- **WHEN** a KU carries only default/empty extension values that serialize to nothing (no environment, no related, no contributing orgs) — noting that `severity`, `kind`, `status`, `staleness_policy`, and `owner_org` always have values and therefore always produce entries
- **THEN** the `extensions` object SHALL contain exactly the always-present keys and no empty/null entries; a hypothetical KU with zero extension values SHALL omit `extensions` entirely

#### Scenario: Rich serializer unchanged

- **WHEN** the same KU is passed through `to_cq_json_rich()`
- **THEN** the output SHALL carry extensions as first-class internal fields (e.g. `evidence.severity`, top-level `kind`) exactly as before this delta, with no `extensions` object

