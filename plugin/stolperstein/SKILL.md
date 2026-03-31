---
name: stolperstein
description: Query and contribute to the Stolperstein knowledge base — experiential knowledge for AI coding agents
metadata:
  filePattern: []
  bashPattern: ["error", "failed", "Error:", "FAILED", "fatal", "panic", "traceback", "Exception", "denied", "refused", "timeout", "not found"]
  priority: 50
---

# Stolperstein — Experiential Knowledge for AI Agents

You have access to a knowledge base of problem-solution pairs (Knowledge Units) captured from past coding sessions. Use it to avoid rediscovering known issues.

## When to Query

- **Before tackling unfamiliar technology** — check if there are known pitfalls
- **When you hit an error** — search for matching error signatures
- **When switching context** — query for domain-specific gotchas

```
query(text="Swift concurrency strict checking", domain=["swift", "xcode"])
```

## When to Propose

After solving a novel problem that would help a future agent:

```
propose(
  summary="Xcode 16 requires explicit Swift 6 concurrency opt-in",
  detail="When targeting Swift 6 language mode, all sendable violations become errors...",
  action="Add -strict-concurrency=complete to build settings.",
  domain=["swift", "xcode"],
  kind="pitfall"
)
```

**Kind options:** `pitfall`, `workaround`, `tool-recommendation`, `gap-signal`

## When to Confirm

When you encounter a KU that helped and was accurate:

```
confirm(ku_id="ku_abc123")
```

## When to Flag

When a KU is outdated, incorrect, or superseded:

```
flag(ku_id="ku_abc123", reason="incorrect", detail="No longer applies after HA 2025.4")
```

## When to Reflect

At the end of a significant debugging or development session, run `/stolperstein:reflect` to extract generalizable learnings.

## Status

Check store health anytime:

```
status()
```
