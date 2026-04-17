# Upstream issue draft — mozilla-ai/cq

**Target repo:** `mozilla-ai/cq`
**Type:** Discussion / issue (not yet a PR — proposing direction)
**Title:** Proposed schema extensions from an independent implementation (Stolperstein)

---

## Body

Hi cq maintainers — thanks for publishing the protocol. I'm building [Stolperstein](https://github.com/CaseyRo/stolpersteine), an independent cq-compatible local node focused on single-operator and small-team deployments (German KMU / Mittelstand). Running the implementation against `schema/knowledge_unit.json` at `main` (as of commit `92b35de`), I've hit a few places where the current schema is tighter than I need for our use case. Rather than fork silently I wanted to surface them early, as proposed extensions or discussion points.

Happy to submit PRs for any of these that land with community support — or to rework my end if the current boundaries are intentional.

### Summary of proposed additions

| Field | Where | What | Why |
|---|---|---|---|
| `evidence.severity` | `evidence` | enum `low \| medium \| high \| critical` | Lets retrieving agents rank safety-critical pitfalls above cosmetic ones when confidence is tied. Very useful in multi-agent environments where one bad `action` can break production. |
| `context.environment` | `context` | string | Captures build/runtime environment (e.g. `xcode-16`, `node-22`, `postgres-16.4`). Different from `languages` / `frameworks` / `pattern` — environment-version-specific pitfalls are common. |
| `kind` | top-level | enum `pitfall \| workaround \| tool-recommendation` | We find agents benefit from coarse-grained typing on a KU — "is this a trap to avoid or a tool to try?" Currently we'd stuff it in `domains` or the insight text, which feels lossy. |
| `flags[].reason = "superseded"` | `FlagReason` | add `superseded` variant | Distinct from `duplicate` — supersedence means "the newer KU replaces this one in a causal sense" (e.g. a workaround obsoleted by a tool fix). `duplicate` implies equivalence. |
| `evidence.contributing_orgs` | `evidence` | `array[string]` | Diversity of confirming sources is a better signal than raw `confirmations` count. Enables confidence weighting by source diversity rather than volume. |
| `provenance.graduation_history` | optional top-level | `array[{timestamp, target, reviewer}]` | Audit trail for tier-graduation events. Would help with EU AI Act / high-risk system audit requirements if cq is deployed in regulated contexts. |

### On provenance / DIDs

The current schema has `created_by` as a free-form string. I'm experimenting with per-install `did:key` identifiers for provenance. I don't need this in the schema as a constraint, but documenting that `created_by` is recommended to be a resolvable identifier (URI, DID, email) would help interop between installs that care about attribution. Would a non-binding description note be acceptable?

### On `additionalProperties: false`

This is the tightest blocker for experimentation. Could we consider one of:

- Relax to `true` under a dedicated extensions namespace (e.g. any property prefixed `x-`)
- Keep `false` but add an explicit `extensions: object` slot for implementation-specific fields

This would let downstream implementations iterate without forking the schema. Happy to take either shape.

### What's in it for cq

Stolperstein is part of a positioning thrust we're building at [CDiT](https://cdit-works.de) around "the machine-readable org layer" — the shorthand being: *if every department's agents share state the way cq lets them, half of status meetings compress to nothing.* Adoption of cq in the KMU / Mittelstand segment is ~zero right now; a working reference implementation and real deployment experience feeding back to the protocol is one concrete path to getting there.

I'll open separate issues for any of the above that want discussion on their own thread. Let me know which would be welcome as PRs and which are "interesting but out of scope for now."

— Casey, CDiT
