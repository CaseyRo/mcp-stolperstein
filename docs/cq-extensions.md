# Stolperstein extensions to the CQ schema

Stolperstein conforms strictly to the upstream `mozilla-ai/cq` schema on the wire (see `tests/fixtures/cq/CQ_SCHEMA_REF.md` for the pin). It also carries **extensions** — fields we need for our use case that upstream doesn't (yet) define. Extensions are stored locally, exposed by `to_cq_json_rich()` and the MCP tool surface, and **stripped** by `to_cq_json_strict()` before any wire transmission.

This document is the canonical registry. Every extension field carried in `rich` but dropped in `strict` **must** appear here.

Upstream discussion proposing these extensions: [mozilla-ai/cq#286](https://github.com/mozilla-ai/cq/discussions/286). Maintainer response received 2026-04-28 — verdicts reflected in the Status column below.

On the `additionalProperties: false` blocker: upstream's position is "probably, but not yet", with a stated preference for an explicit `extensions: object` slot over `x-` prefixed keys. They invited a scoping issue in advance of committing to a date. Until that lands, every field below stays strip-on-strict.

## Status legend

- **proposed** — filed upstream, awaiting response.
- **accepted** — upstream has merged the extension; we can unblock by re-vendoring the schema and moving the field out of this registry.
- **declined** — upstream decided against on the merits (reason noted per row); field stays local-only unless new evidence reopens it.
- **deferred** — upstream acknowledges the underlying need but wants it resolved in a different shape or thread first.
- **stolperstein-specific** — never intended for upstream (implementation detail or org-layer concern outside the protocol's scope).

## Extensions

| Field | Location | Type | Status | Purpose |
|---|---|---|---|---|
| `evidence.severity` | evidence | `low \| medium \| high \| critical` | declined | Ranking tiebreaker + decay-floor modifier. Upstream: contributor-self-assigned trust signals are cheap to game vs observed confirmations; importance should emerge from usage. |
| `evidence.contributing_orgs` | evidence | `array[string]` (DIDs) | declined | Diversity-weighted confidence: 3 orgs confirming > 3 agents from 1 org. Upstream: per-KU org arrays are a profile-building vector when joined across units; diversity should be computed from confirmation provenance instead. |
| `context.environment` | context | string | deferred | Build/runtime scope (`macos`, `cloudflare-workers`, `node-22`) — observed in practice as platform scope, not just version pins. Upstream: fold into `frameworks` + close the gap with SKILL.md guidance first; revisit via [#170](https://github.com/mozilla-ai/cq/issues/170) if it stays noisy. |
| `kind` | top-level | `pitfall \| workaround \| tool-recommendation` | declined | Coarse-grained KU typing so agents know the shape before reading. Upstream: classification should be derived from observed usage, not contributor-declared; keeping that path open. |
| `status` | top-level | `draft \| active \| stale \| disputed \| archived` | stolperstein-specific | Lifecycle state machine. Upstream models lifecycle only via `flags[]` — our richer model is internal. |
| `staleness_policy` | top-level | string | stolperstein-specific | Per-KU decay policy override. |
| `related[]` | top-level | `[{type, target_id}]` | stolperstein-specific | Relationship graph beyond `superseded_by`. |
| `owner_org` | top-level | string (DID) | stolperstein-specific | Multi-tenant read filter via `TRUSTED_ORGS`. Phase 1 foundation — enforceable write permissions in Phase 2. Upstream has `tier: local \| private \| public` instead, which addresses a different slice. |
| `provenance.proposer_did` | top-level `provenance` object | string (DID) | deferred | Rich provenance. On the wire, strict mode emits `proposer_did` as upstream's `created_by`. Upstream sets `created_by` server-side; the cross-install attribution-portability question was invited as its own thread. |
| `provenance.graduation_history` | top-level `provenance` object | `array[{timestamp, target, reviewer_did, agent}]` | declined | Audit trail for tier graduations. Upstream: governance state, not consumption state — belongs in admin tooling; a dedicated EU AI Act audit-trail thread was invited when we can name concrete compliance requirements. |
| `provenance.emergent` | top-level `provenance` object | boolean | stolperstein-specific | Distinguishes emergent-aggregation-produced `tool-gap-signal` KUs from grandfathered migration artifacts. |

## Rules

1. Adding a new extension requires adding a row here in the same change that adds the field.
2. When upstream accepts an extension, move the row to the "accepted" table (not yet created — first acceptance will create it).
3. Extensions must never leak through `to_cq_json_strict()`. `tests/test_cq_schema.py` validates this on every commit.
4. Extensions do NOT need to appear in `to_cq_v0()` — v0 is a legacy-transition hatch, not an extension surface.
