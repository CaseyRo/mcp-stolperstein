# Design: adopt the upstream CQ `extensions` slot

## Context

Upstream `mozilla-ai/cq` merged the extensions slot we scoped in #406 (PR #453, 2026-06-23): `KnowledgeUnit` gains an optional top-level `extensions` object; keys must match `^[a-z0-9][a-z0-9_-]*:\S+$`; values carry no protocol semantics and are validated in Go/Python SDKs and the CLI. Our `to_cq_json_strict()` currently strips every Stolperstein extension because the old schema was `additionalProperties: false` with no escape hatch. The 2026-07 dead-code cleanup already removed the sync clients, `flags`, and `graduation_history` — the strict serializer is now small and this delta touches one method plus fixtures/docs.

## Goals / Non-Goals

**Goals**
- Strict output carries all Stolperstein extensions under `stolperstein:*` keys and validates against the re-vendored upstream schema.
- Registry (`docs/cq-extensions.md`) and the `cq://extensions` resource reflect slot carriage.

**Non-Goals**
- No inbound handling of foreign `extensions` (no sync path exists post-cleanup; revisit with Phase-2 graduation).
- No changes to `to_cq_json_rich()`, the DB schema, MCP tools, or hooks.
- No signing/envelope work — #406 explicitly scoped extensions outside any signing envelope.

## Decisions

1. **Namespace: `stolperstein`** (not `st` or `cdit`). Readable, unambiguous, matches the repo/plugin name. Key format constraint allows it.
2. **Flat keys, JSON-native values** — `stolperstein:severity` → `"high"`, `stolperstein:related` → array of `{type, target_id}` dicts. Alternative considered: one `stolperstein:meta` blob holding everything — rejected: per-field keys let a consumer pick fields without parsing a nested contract, and match how the registry documents fields.
3. **Omit-when-empty** — null/empty extension values produce no key; a KU with zero extension values omits the `extensions` object (upstream optional). Keeps payloads minimal and makes "no extensions" indistinguishable from a pre-slot producer.
4. **Re-vendor as a straight copy of upstream main** (post-#453 SHA recorded in `CQ_SCHEMA_REF.md`), not a hand-edit of the current fixture. The fixture is the oracle; hand-edits drift.
5. **Registry framing** — rows keep their #286 verdicts (declined/deferred apply to promotion into *core* schema); a new column/note states each field now rides the slot on the wire. "Extensions must never leak through strict" rule is rewritten to "extensions must only appear inside the `extensions` slot".

## Risks / Trade-offs

- [Upstream schema pin moves under us — other schema changes may ride along with the re-vendor] → validate the full existing test corpus against the new pin in the same commit; any unrelated break surfaces immediately in `test_cq_schema.py`.
- [Downstream consumer chokes on unknown `extensions` keys] → slot is optional and upstream-specified as semantics-free; consumers validating against upstream schema accept it by construction. No known consumers exist yet anyway.
- [`owner_org` DID in wire output is an org-identifying signal (#286 privacy concern was about `contributing_orgs`)] → both ship only when someone actually transmits strict payloads; today no transmit path exists. Flag for review in Phase-2 graduation design, where a per-field emit allowlist can be added if needed.

## Migration Plan

Pure code+fixture change; no data migration, no deploy steps beyond normal auto-deploy. Rollback = revert commit.

## Open Questions

- None blocking. Phase-2 graduation decides whether outbound extension emission needs a privacy allowlist (`owner_org`, `contributing_orgs`).
