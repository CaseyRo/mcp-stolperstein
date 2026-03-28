## Why

AI coding agents rediscover the same failures independently across sessions. Hard-won solutions to obscure gotchas — dependency quirks, platform restrictions, config traps — evaporate when a session ends. For a solo dev running a broad stack, the same agent hits the same wall weeks later. There is no mechanism for agents to learn from past experience across session boundaries.

Mozilla AI released **cq** (March 2026) — an open standard for shared agent learning with tiered storage (local/team/global commons), confidence scoring, and a defined KU interchange format (JSON schema). Rather than building a parallel system, we should build Stolperstein as a **CQ-compatible local node** that can both consume from and contribute to the CQ ecosystem while adding our own value (Siyuan sync, CDIT-specific hooks, richer local UX).

## What Changes

- New **MCP server** (Python/FastMCP) providing structured knowledge capture and retrieval via 6 tools — aligned with CQ's tool surface (query, propose, confirm, flag, reflect, status)
- **CQ-compatible KU schema** as the canonical data format — our SQLite store uses the same JSON interchange format so KUs can graduate upstream to CQ team/global tiers without transformation
- **SQLite storage layer** with full-text search (FTS5) and vector similarity search (sqlite-vec) for hybrid retrieval
- **Knowledge Unit (KU) lifecycle** — propose, confirm, flag, decay — with confidence scoring compatible with CQ's algorithm (diversity-weighted, temporal decay, dispute handling)
- **CQ team sync** — optional upstream connection to a CQ team API for pulling shared knowledge and graduating local KUs
- **Claude Code plugin** (SKILL.md + hooks.json) enabling auto-query on errors and a `/stolperstein:reflect` skill for end-of-session knowledge extraction
- **Siyuan sync** — one-way push rendering active KUs as structured documents for human review (our differentiator over stock CQ)
- **Docker deployment** on Zentralwerk (Komodo-managed, Tailscale-accessible)

## Capabilities

### New Capabilities

- `knowledge-capture`: MCP tools for proposing, confirming, and flagging Knowledge Units — the write path of the system (6 tools aligned with CQ: query, propose, confirm, flag, reflect, status)
- `knowledge-retrieval`: Hybrid search (FTS5 + sqlite-vec cosine similarity) for querying KUs by natural language, error signatures, or technology tags — the read path
- `ku-lifecycle`: Confidence scoring, staleness decay, state machine (draft -> active -> stale -> archived), and validation tracking — compatible with CQ's confidence algorithm
- `cq-interop`: CQ-compatible KU JSON schema, optional team API sync (pull shared KUs, graduate local KUs upstream), and future path to global commons contribution
- `claude-code-integration`: SKILL.md, hooks.json (PostToolUse auto-query on errors), and /stolperstein:reflect session skill
- `siyuan-sync`: One-way push of active KUs to a Siyuan notebook as structured documents

### Modified Capabilities

_None — greenfield project._

## Impact

- **New repo**: `mcp-stolperstein` (Python, FastMCP, SQLite)
- **New Docker service**: Komodo stack on Zentralwerk, Tailscale-exposed
- **Claude Code config**: New MCP server entry in settings, new plugin in `.claude/` for consuming projects (starting with Hauswart)
- **Dependencies**: FastMCP, sqlite-vec, sentence-transformers (or API-based embeddings), httpx (Siyuan API, CQ team API)
- **CQ ecosystem**: Compatible local node — can operate standalone or connect to CQ team/global tiers. KU schema follows `knowledge-unit.schema.json` interchange format. Future contribution path to mozilla-ai/cq upstream.
- **MVP test case**: Hauswart (SwiftUI HA client) — Swift/SwiftUI quirks, HA WebSocket/REST gotchas, Apple ecosystem restrictions, Xcode/build issues
