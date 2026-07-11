---
generated: 2026-07-07
name: mcp-stolperfalle
---

# Wiki Schema

Source of truth for this wiki's structure. Edit between compiles to rename, merge,
or re-scope topics/concepts; the compiler reads this before classifying and respects
your changes. Topic/concept slugs are `lowercase-kebab-case`; link style is `obsidian`.

## Topics

- **project-overview** — strategic + operational overview: the "machine-readable org layer" thesis (CDiT Phase 1), the two change proposals + designs, and the day-to-day runbook.
- **cq-interop-and-schema** — CQ conformance, the strict/rich serializers, the `stolperstein:*` extension registry, the upstream discussion (#286/#406/#453), and schema migrations.
- **knowledge-lifecycle** — the KU lifecycle: capture (propose/reflect), retrieval (hybrid FTS5 + vector), transitions (confirm/flag/decay), states, and confidence scoring.
- **org-layer-foundations** — `owner_org` + `TRUSTED_ORGS` visibility (Phase 1: read-filter, trust-all) and emergent-signal detection from query misses.
- **claude-code-integration** — the Claude Code plugin (SKILL + hooks), the three hook handlers, the reflect flow, and optional SiYuan sync.

## Concepts

- **conform-plus-extend** — strictly conform on the wire, extend locally in the extensions slot, propose extensions upstream. Connects: project-overview, cq-interop-and-schema, knowledge-lifecycle, org-layer-foundations.
- **provenance-and-did-identity** — one `did:key` per install reused as proposer / owner_org / contributing_org / signer, with the private key kept out of the DB. Connects: cq-interop-and-schema, knowledge-lifecycle, org-layer-foundations.

## Evolution Log

- 2026-07-07: Initial schema generated from 5 topics, 2 concepts (32 sources).
