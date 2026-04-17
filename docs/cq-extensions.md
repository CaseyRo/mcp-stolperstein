# Stolperstein extensions to the CQ schema

Stolperstein conforms strictly to the upstream `mozilla-ai/cq` schema on the wire (see `tests/fixtures/cq/CQ_SCHEMA_REF.md` for the pin). It also carries **extensions** — fields we need for our use case that upstream doesn't (yet) define. Extensions are stored locally, exposed by `to_cq_json_rich()` and the MCP tool surface, and **stripped** by `to_cq_json_strict()` before any wire transmission.

This document is the canonical registry. Every extension field carried in `rich` but dropped in `strict` **must** appear here.

Upstream discussion proposing these extensions: [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286).

## Status legend

- **proposed** — filed upstream, awaiting response.
- **accepted** — upstream has merged the extension; we can unblock by re-vendoring the schema and moving the field out of this registry.
- **declined** — upstream decided against; field stays local-only indefinitely.
- **stolperstein-specific** — never intended for upstream (implementation detail or org-layer concern outside the protocol's scope).

## Extensions

| Field | Location | Type | Status | Purpose |
|---|---|---|---|---|
| `evidence.severity` | evidence | `low \| medium \| high \| critical` | proposed | Ranking tiebreaker + decay-floor modifier. Safety-critical pitfalls stay visible longer and outrank cosmetic ones at equal confidence. |
| `evidence.contributing_orgs` | evidence | `array[string]` (DIDs) | proposed | Diversity-weighted confidence: 3 orgs confirming > 3 agents from 1 org. |
| `context.environment` | context | string | proposed | Build/runtime version scope (e.g. `xcode-16`, `node-22`) — version-specific pitfalls are common and orthogonal to language/framework/pattern. |
| `kind` | top-level | `pitfall \| workaround \| tool-recommendation` | proposed | Coarse-grained KU typing so agents know the shape before reading. Upstream has nothing equivalent. |
| `status` | top-level | `draft \| active \| stale \| disputed \| archived` | stolperstein-specific | Lifecycle state machine. Upstream models lifecycle only via `flags[]` — our richer model is internal. |
| `staleness_policy` | top-level | string | stolperstein-specific | Per-KU decay policy override. |
| `related[]` | top-level | `[{type, target_id}]` | stolperstein-specific | Relationship graph beyond `superseded_by`. |
| `owner_org` | top-level | string (DID) | stolperstein-specific | Multi-tenant read filter via `TRUSTED_ORGS`. Phase 1 foundation — enforceable write permissions in Phase 2. Upstream has `tier: local \| private \| public` instead, which addresses a different slice. |
| `provenance.proposer_did` | top-level `provenance` object | string (DID) | proposed as `created_by` semantics | Rich provenance. On the wire, strict mode emits `proposer_did` as upstream's `created_by`. |
| `provenance.graduation_history` | top-level `provenance` object | `array[{timestamp, target, reviewer_did, agent}]` | proposed | Audit trail for tier graduations — EU AI Act relevance. |
| `provenance.emergent` | top-level `provenance` object | boolean | stolperstein-specific | Distinguishes emergent-aggregation-produced `tool-gap-signal` KUs from grandfathered migration artifacts. |

## Rules

1. Adding a new extension requires adding a row here in the same change that adds the field.
2. When upstream accepts an extension, move the row to the "accepted" table (not yet created — first acceptance will create it).
3. Extensions must never leak through `to_cq_json_strict()`. `tests/test_cq_schema.py` validates this on every commit.
4. Extensions do NOT need to appear in `to_cq_v0()` — v0 is a legacy-transition hatch, not an extension surface.
