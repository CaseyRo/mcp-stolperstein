---
concept: Provenance & DID Identity
last_compiled: 2026-07-07
topics_connected: [cq-interop-and-schema, knowledge-lifecycle, org-layer-foundations]
status: active
---

# Provenance & DID Identity

## Pattern

A single Ed25519 `did:key:z...` per install is the spine of identity, reused across three otherwise-separate concerns. The same DID is the KU's **`proposer_did`** (mapped to upstream `created_by`), its **`owner_org`** (the tenant that owns the row), and an entry in **`contributing_orgs`** when a confirmation arrives. The private key deliberately lives **outside** the SQLite DB (a file at `/data/stolperfalle.key` mode 0600, or a base64 env var); the DB stores only the public key and the derived DID string. That one identity primitive then feeds trust-weighting: confidence scoring is diversity-weighted by the count of *distinct* contributing orgs, so a confirmation from a new org boosts more than another from an already-contributing one.

## Instances

- **provenance mapping** in [[../topics/cq-interop-and-schema]]: `provenance.proposer_did` is emitted as upstream core `created_by`; the rest of provenance (`emergent`, `graduation_history`) rides the extensions slot.
- **ownership** in [[../topics/org-layer-foundations]]: `propose()` stamps `owner_org` to the local install DID; ingested team-sync KUs preserve their upstream `owner_org` rather than being rewritten.
- **trust-weighting** in [[../topics/knowledge-lifecycle]]: diversity-weighted confidence counts distinct `contributing_orgs`; emergent KUs carry `provenance.emergent=true`.

## What This Means

Identity is a single reused primitive, not three parallel ones — which is exactly what makes cross-org trust *meaningful* when Phase 2 adds write-side enforcement. The security posture is the other half: keeping the signing key out of the DB (security-review H1) means a database leak can leak *content* but cannot forge *provenance* — you can read who said what, but you cannot sign as them. That separation is the precondition for treating another org's KUs as trustworthy at all.

## Sources

- [[../topics/cq-interop-and-schema]]
- [[../topics/knowledge-lifecycle]]
- [[../topics/org-layer-foundations]]
