---
name: stolperstein:reflect
description: Extract generalizable learnings from the current session and propose them as Knowledge Units
---

# /stolperstein:reflect — Session Knowledge Extraction

Run this at the end of a substantive coding or debugging session to capture reusable learnings into the Stolperstein knowledge base.

## Steps

1. **Summarize the session** — in plain prose, cover:
   - What problems did you hit? (Error signatures, tool failures, surprising behavior.)
   - What workarounds or fixes did you apply?
   - What was non-obvious — the thing a future agent wouldn't guess from the docs?

2. **Call reflect**:
   ```
   reflect(session_summary="<your summary>")
   ```

   Each candidate comes back pre-filled with `summary`, `detail`, `action`, `domains`, `kind`, and best-effort `context_languages` / `context_frameworks` / `context_environment` / `context_pattern` / `severity`. You can pass them straight through to `propose()` without re-reading the docs.

3. **Review candidates** — for each one:
   - Is it generalizable? (Would it help a DIFFERENT agent on a DIFFERENT project?)
   - Is the `summary` clear and the `action` prescriptive?
   - Does `severity` feel right? (`critical` is for things that break production if ignored.)
   - If yes: propose it.
   - If no: skip.

4. **Propose the keepers**:
   ```
   propose(
     summary=candidate["summary"],
     detail=candidate["detail"],
     action=candidate["action"],
     domains=candidate["domains"],
     kind=candidate["kind"],
     context_languages=candidate.get("context_languages", []),
     context_frameworks=candidate.get("context_frameworks", []),
     context_environment=candidate.get("context_environment"),
     context_pattern=candidate.get("context_pattern"),
     severity=candidate.get("severity", "medium"),
   )
   ```

5. **Report** — tell the user how many KUs were proposed and their IDs.

## Good candidates

- Error patterns that took multiple attempts to diagnose.
- Version-specific pitfalls (`context_environment="xcode-16"`, `context_environment="node-22"`).
- Workarounds for known framework bugs.
- Tool configuration that isn't well-documented.
- Anything an agent would want to know BEFORE starting similar work.

## Bad candidates (skip these)

- Project-specific business logic.
- One-time setup steps unlikely to recur.
- Things well-documented in official docs.
- `gap-signal`-shaped observations — those emerge automatically from query-miss patterns; you don't propose them directly.

## Kind guidance

- `pitfall` — "here's a trap, here's how to avoid it."
- `workaround` — "the real fix is upstream; until then, do X."
- `tool-recommendation` — "for this problem, reach for this tool."
