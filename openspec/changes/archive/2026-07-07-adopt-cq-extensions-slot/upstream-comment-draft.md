# Draft: adopter comment for mozilla-ai/cq#286 (or #406)

> Status: DRAFT — for Casey's review. Do not post without approval.
> Target: follow-up comment on discussion #286, referencing #406/#453.

---

Closing the loop on the extensions slot from my side: Stolperstein now emits it in production.

Since #453 merged, our strict serializer carries every local extension inside `extensions` under `stolperstein:*` keys instead of stripping them — `stolperstein:severity`, `stolperstein:kind`, `stolperstein:status`, `stolperstein:staleness_policy`, `stolperstein:owner_org`, plus `stolperstein:contributing_orgs` / `stolperstein:environment` / `stolperstein:related` / `stolperstein:emergent` when populated. Full mapping is in our [extensions registry](https://github.com/CaseyRo/mcp-stolperstein/blob/main/docs/cq-extensions.md); output validates against the schema pinned at `cb1f81f`.

Two implementation notes that may be useful data points:

1. **`maxProperties: 20` is comfortable but not roomy.** We use 9 keys for one implementation. Two or three implementations annotating the same unit (the working-group scenario) would hit the cap fast. Not a problem today — just flagging it before it becomes load-bearing.
2. **Omit-when-empty wants a spec sentence.** We emit no key for null/empty values so consumers can treat key-presence as meaningful. If the schema docs recommended that convention, implementations would converge on it instead of half of them shipping `"ns:field": null`.

As before: this implementation is AI-built under my direction — the serializer change, tests, and this comment draft included. Happy to share the conformance test corpus if useful for the standard work.

---

> Posting notes (not part of the comment): keep the AI disclosure line — it's
> established voice in this thread. If #406 gets reopened for follow-ups,
> post the two notes there instead and keep #286 to the adoption announcement.
