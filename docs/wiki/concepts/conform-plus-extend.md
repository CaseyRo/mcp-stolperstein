---
concept: Conform-plus-Extend
last_compiled: 2026-07-07
topics_connected: [project-overview, cq-interop-and-schema, knowledge-lifecycle, org-layer-foundations]
status: active
---

# Conform-plus-Extend

## Pattern

Stolperfalle is deliberately positioned as a **conforming-plus-extending reference implementation** of Mozilla AI's `mozilla-ai/cq`, not a fork. The same move recurs at every layer: emit a wire shape that validates *exactly* against the vendored, pinned upstream schema (`to_cq_json_strict()`), while carrying a richer internal superset (`to_cq_json_rich()`) whose extra fields ride the upstream `extensions` slot as namespaced `stolperstein:*` keys. Extensions that prove useful get proposed back upstream so the protocol grows rather than diverges. The load-bearing invariant is that an extension must **never** leak into a strict core field — it lives in the slot, and every `stolperstein:*` key is registered in `docs/cq-extensions.md`.

## Instances

- **2026-04 (mvp-scaffold)** in [[../topics/cq-interop-and-schema]]: built as a "CQ-compatible local node" using the same JSON interchange format so KUs could graduate to CQ team/global tiers without transformation.
- **2026-06 (cq-v1-alignment)** in [[../topics/project-overview]]: reframed from "catching up to CQ" to "conform to the strict, small base **and** deliberately extend it" — severity, DID provenance, org boundaries, a state machine, emergent signals, a `kind` enum.
- **extensions slot (#453)** in [[../topics/cq-interop-and-schema]]: the `additionalProperties:false` blocker was resolved upstream; extensions now travel as `stolperstein:<field>` keys instead of being stripped.
- **lifecycle** in [[../topics/knowledge-lifecycle]]: `severity`, `status`, and `kind` are extensions layered on the strict `insight`/`evidence` base.
- **org layer** in [[../topics/org-layer-foundations]]: `owner_org`, `contributing_orgs`, and `provenance.emergent` are all extensions, filed upstream as proposals.

## What This Means

The strategy lets Stolperfalle be interoperable **and** ahead of upstream at the same time — a reference implementation whose extensions are the growth path for the protocol itself. The risk it exists to manage is drift: any consumer that validates output against the pinned schema will reject a non-conforming payload, so the strict serializer is a hard contract, not a convenience. The discipline — two explicit serializers, the extensions registry, the pinned vendored schema in tests — is what keeps "extend freely" from quietly becoming "no longer CQ."

## Sources

- [[../topics/project-overview]]
- [[../topics/cq-interop-and-schema]]
- [[../topics/knowledge-lifecycle]]
- [[../topics/org-layer-foundations]]
