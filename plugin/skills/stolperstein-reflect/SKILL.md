---
name: stolperstein:reflect
description: Extract generalizable learnings from the current session and propose them as Knowledge Units
---

# /stolperstein:reflect — Session Knowledge Extraction

Run this at the end of a significant coding or debugging session to capture reusable learnings.

## Steps

1. **Summarize the session**: What problems did you encounter? What workarounds did you apply? What was surprising or non-obvious?

2. **Call reflect** with the summary:
   ```
   reflect(session_summary="<your summary>")
   ```

3. **Review candidates**: For each returned candidate, decide whether to propose it:
   - Is this generalizable? (Would it help a different agent on a different project?)
   - Is the summary clear and the action prescriptive?
   - If yes: call `propose()` with the candidate fields
   - If no: skip it

4. **Report**: Tell the user how many KUs were proposed and their IDs.

## Good candidates

- Error patterns that took multiple attempts to diagnose
- Platform-specific gotchas (Swift, Docker, HA, etc.)
- Workarounds for known framework bugs
- Tool configuration that isn't well-documented

## Bad candidates (skip these)

- Project-specific business logic decisions
- One-time setup steps unlikely to recur
- Obvious things documented in official docs
