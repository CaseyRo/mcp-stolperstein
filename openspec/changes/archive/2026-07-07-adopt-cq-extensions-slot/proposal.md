# Adopt the upstream CQ `extensions` slot

## Why

Upstream merged the `extensions` slot we proposed in [mozilla-ai/cq#406](https://github.com/mozilla-ai/cq/issues/406) (implemented via [#453](https://github.com/mozilla-ai/cq/pull/453), 2026-06-23): `KnowledgeUnit` now carries an optional top-level `extensions` object with namespaced keys (`^[a-z0-9][a-z0-9_-]*:\S+$`). Our entire strict/rich serializer split exists to work around `additionalProperties: false` — that blocker is lifted. Strict wire output can now legally carry every Stolperstein extension under `stolperstein:*` keys instead of stripping them, so downstream CQ consumers stop losing severity, kind, and provenance data on graduation.

## What Changes

- Re-vendor `tests/fixtures/cq/knowledge_unit.json` from upstream main (post-#453, includes the `Extensions` $def) and record the new pin in `tests/fixtures/cq/CQ_SCHEMA_REF.md`.
- `to_cq_json_strict()` emits extension fields in the `extensions` slot as `stolperstein:<field>` keys instead of dropping them: `severity`, `contributing_orgs`, `kind`, `status`, `staleness_policy`, `related`, `owner_org`, `environment`, `emergent`. Omit the slot entirely when a KU has no extension values (upstream field is optional).
- `to_cq_json_rich()` and the internal model are unchanged — rich stays the internal superset shape; only the wire serialization changes.
- Update `docs/cq-extensions.md`: the registry's "stripped by strict" framing becomes "carried in the `extensions` slot"; per-row status stays (declined/deferred verdicts from #286 still apply to *promotion into core schema*, not to slot carriage).
- Update the `cq://extensions` resource fallback text and the `to_cq_json_strict` docstrings to match.
- **Not** breaking for the DB or MCP tool surface: no schema migration, no tool signature change. Wire-shape change is additive (new optional key), so existing strict consumers keep working.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cq-interop`: strict serialization requirement changes from "extensions MUST be stripped before wire transmission" to "extensions MUST be emitted under namespaced `stolperstein:*` keys in the optional `extensions` slot, validating against the re-vendored upstream schema".

## Impact

- `src/stolperstein/models.py` — `to_cq_json_strict()` gains the extensions-slot emission; docstrings updated.
- `tests/fixtures/cq/knowledge_unit.json` + `CQ_SCHEMA_REF.md` — re-vendored pin.
- `tests/test_cq_schema.py` — the "extensions must not leak into strict" tests invert into "extensions appear under `stolperstein:*` keys and the payload still validates"; key-format regex asserted.
- `docs/cq-extensions.md`, `cq://extensions` resource text in `src/stolperstein/server.py`.
- No dependency, migration, deployment, or hook changes.
