No capability spec deltas for this change.

`proposal.md`'s Capabilities section lists no new or modified capabilities:
this is a pure rename of public-facing identifiers (repo, package, CLI, env
vars, Docker volumes, Komodo stack, DNS/Cloudflare Access, the Claude Code
plugin, MCP tool name prefixes). None of it changes the requirements of any
existing capability in `openspec/specs/` — the wire protocol, the KU schema,
and all six MCP tools' behavior are unaffected; see `design.md` for what
does change and how it's sequenced.
