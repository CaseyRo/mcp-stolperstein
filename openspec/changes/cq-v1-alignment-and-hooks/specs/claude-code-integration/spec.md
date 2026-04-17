## MODIFIED Requirements

### Requirement: SKILL.md provides agent behavioral guidance

The plugin SHALL include a `SKILL.md` file that instructs Claude Code agents to: query Stolperstein when structured error signals appear, propose KUs after solving novel problems, and run reflect at end of substantive sessions. The SKILL.md SHALL describe all 6 tools with v1-shaped usage examples (flat `context_*` params + `severity` on `propose`, no `gap-signal` as a proposable kind) and SHALL document which hooks are active and what they do, including the `STOLPERSTEIN_HOOKS_DISABLED` escape hatch, so agents and humans understand the proactive behavior they will experience.

#### Scenario: Agent auto-discovers Stolperstein capabilities

- **WHEN** a Claude Code session starts in a project with the Stolperstein plugin configured
- **THEN** the agent SHALL have access to SKILL.md instructions describing when and how to use each tool, plus a "Hooks active in this project" section listing the installed hooks and a "Disabling hooks" section listing the env var

#### Scenario: SKILL.md reflects v1 tool shapes

- **WHEN** an agent reads SKILL.md
- **THEN** the `propose` example SHALL use flat `context_languages`, `context_frameworks`, `context_environment`, `context_pattern`, and `severity` parameters (and `domains` not `domain`), and SHALL NOT reference `gap-signal` as a proposable kind

#### Scenario: SKILL.md documents hook-vs-tool dual-channel behavior

- **WHEN** an agent reads SKILL.md
- **THEN** a note SHALL clarify that hook injections are rate-limited nudges (one field only, 30s cooldown) while explicit `query()` calls return the full KU shape, and recommend calling `query()` directly when more detail is needed

### Requirement: /stolperstein:reflect skill for session-end extraction

The plugin SHALL provide a `/stolperstein:reflect` slash command that triggers the `reflect` tool with a session summary. The skill SHALL prompt the agent to summarize problems solved, then present candidate KUs for the agent to propose or discard. Candidate previews SHALL include the inferred flat `context_*` and `severity` fields so the agent can edit before proposing, and the approve-and-propose step SHALL pass them through to `propose()` unchanged.

#### Scenario: User triggers reflect at end of session

- **WHEN** the user runs `/stolperstein:reflect`
- **THEN** the skill SHALL prompt the agent to summarize the session's key learnings, call `reflect`, and present each candidate KU (including flat context + severity) for approval

#### Scenario: Reflect produces candidates that agent proposes

- **WHEN** reflect returns 3 candidates and the agent approves 2
- **THEN** the skill SHALL call `propose` for each approved candidate with the full v1 payload (flat context + severity) and report the created KU ids

### Requirement: MCP server configuration in Claude Code settings

The plugin SHALL be installable by adding the MCP server to Claude Code's settings (either project-level `.claude/settings.json` or user-level `~/.claude/settings.json`). The server SHALL be reachable via stdio (local) or HTTP/SSE (remote via Tailscale or Cloudflare Access).

#### Scenario: Local stdio configuration

- **WHEN** the MCP server is configured with `"command": "mcp-stolperstein"` (stdio transport)
- **THEN** Claude Code SHALL connect to the server via stdio and discover all 6 tools

#### Scenario: Remote HTTP configuration via Cloudflare Access

- **WHEN** the MCP server is configured with a public URL endpoint and bearer token
- **THEN** Claude Code SHALL connect via HTTP/SSE transport with the token and discover all 6 tools

## REMOVED Requirements

### Requirement: PostToolUse hook auto-queries on errors

**Reason**: Relocated to the new `claude-hooks` capability, which owns the full hook surface (UserPromptSubmit, PostToolUse Bash, Stop), structured-signal matching, action sanitization, temporal qualification, rate limiting, and handler scripts. Keeping the hook requirement split between `claude-code-integration` (plugin packaging + SKILL.md) and `claude-hooks` (hook behavior) separates concerns cleanly.

**Migration**: Implementers refer to `specs/claude-hooks/spec.md` for authoritative hook behavior. The plugin still ships the hooks; they're specified elsewhere.
