## ADDED Requirements

### Requirement: SKILL.md provides agent behavioral guidance

The plugin SHALL include a `SKILL.md` file that instructs Claude Code agents to: query Stolperstein before tackling unfamiliar technology, propose KUs after solving novel problems, and run reflect at end of significant sessions. The SKILL.md SHALL describe all 6 tools with usage examples.

#### Scenario: Agent auto-discovers Stolperstein capabilities

- **WHEN** a Claude Code session starts in a project with the Stolperstein plugin configured
- **THEN** the agent SHALL have access to SKILL.md instructions describing when and how to use each tool

### Requirement: PostToolUse hook auto-queries on errors

The plugin SHALL include a `hooks.json` configuration with a `PostToolUse` hook that triggers `query` automatically when a tool call results in an error. The hook SHALL extract relevant error context (error message, tool name, file path) and query Stolperstein for matching KUs.

#### Scenario: Build error triggers auto-query

- **WHEN** a `Bash` tool call fails with an error containing "Swift" or a compiler error
- **THEN** the hook SHALL call `query` with the error message text and domain tags extracted from the project context (e.g., `["swift", "xcode"]`)

#### Scenario: Auto-query finds a matching KU

- **WHEN** the auto-query returns one or more KUs with confidence >= 0.5
- **THEN** the hook SHALL inject the top KU's `action` field into the agent's context as a suggested fix

#### Scenario: Auto-query finds no results

- **WHEN** the auto-query returns no matching KUs
- **THEN** the hook SHALL not inject any context (silent no-op)

### Requirement: /stolperstein:reflect skill for session-end extraction

The plugin SHALL provide a `/stolperstein:reflect` slash command that triggers the `reflect` tool with a session summary. The skill SHALL prompt the agent to summarize problems solved, then present candidate KUs for the agent to propose or discard.

#### Scenario: User triggers reflect at end of session

- **WHEN** the user runs `/stolperstein:reflect`
- **THEN** the skill SHALL prompt the agent to summarize the session's key learnings, call `reflect`, and present each candidate KU for approval before calling `propose`

#### Scenario: Reflect produces candidates that agent proposes

- **WHEN** reflect returns 3 candidate KUs and the agent approves 2
- **THEN** the skill SHALL call `propose` for each approved candidate and report the created KU ids

### Requirement: MCP server configuration in Claude Code settings

The plugin SHALL be installable by adding the MCP server to Claude Code's settings (either project-level `.claude/settings.json` or user-level `~/.claude/settings.json`). The server SHALL be reachable via stdio (local) or HTTP/SSE (remote via Tailscale).

#### Scenario: Local stdio configuration

- **WHEN** the MCP server is configured with `"command": "python", "args": ["-m", "stolperstein"]`
- **THEN** Claude Code SHALL connect to the server via stdio and discover all 6 tools

#### Scenario: Remote HTTP configuration via Tailscale

- **WHEN** the MCP server is configured with a Tailscale URL endpoint
- **THEN** Claude Code SHALL connect via HTTP/SSE transport and discover all 6 tools
