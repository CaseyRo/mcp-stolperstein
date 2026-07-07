# Tasks: adopt-cq-extensions-slot

## 1. Re-vendor the upstream schema

- [x] 1.1 Fetch `schema/knowledge_unit.json` from `mozilla-ai/cq` main (post-#453) and replace `tests/fixtures/cq/knowledge_unit.json`; confirm it contains the `extensions` property and the `Extensions` $def with the `^[a-z0-9][a-z0-9_-]*:\S+$` key pattern.
- [x] 1.2 Record the new upstream commit SHA and fetch date in `tests/fixtures/cq/CQ_SCHEMA_REF.md`.
- [x] 1.3 Run `uv run pytest tests/test_cq_schema.py` against the new pin BEFORE any serializer change — any failure here is unrelated upstream drift and must be understood first.

## 2. Serializer

- [x] 2.1 Add extensions-slot emission to `KnowledgeUnit.to_cq_json_strict()` in `src/stolperstein/models.py`: map `severity`, `contributing_orgs` (skip empty), `environment` (skip null), `kind`, `status`, `staleness_policy`, `related` (skip empty, serialize as `{type, target_id}` dicts), `owner_org`, `emergent` (skip null) to `stolperstein:<field>` keys; omit the `extensions` object when empty.
- [x] 2.2 Update the `to_cq_json_strict()` docstring and the module docstring (strict no longer "strips" — it relocates into the slot).

## 3. Tests

- [x] 3.1 Invert `test_strict_omits_stolperstein_extensions`: extension fields still absent at top level and inside `context`/`evidence`, present under `extensions["stolperstein:*"]`.
- [x] 3.2 Add test: strict output with populated extensions validates against the re-vendored schema (jsonschema).
- [x] 3.3 Add test: every emitted `extensions` key matches the upstream key regex.
- [x] 3.4 Add test: empty-valued extensions (no environment, no related, no contributing_orgs) produce no keys; assert no null/empty values in the slot.
- [x] 3.5 Confirm `test_rich_output_fails_strict_schema_by_design` still holds (rich has first-class extension fields that remain invalid outside the slot).

## 4. Docs + resources

- [x] 4.1 Update `docs/cq-extensions.md`: reframe from "stripped by strict" to "carried in the `extensions` slot as `stolperstein:*`"; keep #286 verdict column (verdicts govern core-schema promotion); rewrite rule 3 to "extensions appear only inside the `extensions` slot"; note the slot shipped via #406/#453.
- [x] 4.2 Update the `cq://extensions` resource fallback text and `cq://schema/knowledge-unit` description in `src/stolperstein/server.py` to match.
- [x] 4.3 Update the `SERVER_INSTRUCTIONS` line referencing strict/extension behavior if it still says extensions are stripped.

## 5. Verify

- [x] 5.1 Full `uv run pytest` green; `uv run ruff check src tests plugin` clean; mypy no new errors.
- [x] 5.2 Round-trip sanity: serialize a production-shaped KU (all extensions populated) via `to_cq_json_strict()`, validate with jsonschema against the new pin, eyeball the `extensions` object.
- [x] 5.3 Comment on mozilla-ai/cq#286 (or #406) that Stolperstein now emits the slot — real-world adopter data point, per Casey's upstream-engagement approach. Draft for Casey's review first; do not post autonomously.
