# Global agent installation and Forge lifecycle

## Decision

Forge is installed once for an individual coding agent, not once for Forge itself and not for every other agent. Installing into Codex changes only Codex's global Forge setup. Installing into Antigravity changes only Antigravity's global Forge setup.

The installation makes Forge available in every project that agent opens. Each project retains separate local Forge data in its own `.forge` directory.

## Intended everyday flow

### Agent start

1. A developer opens a project with Codex or Antigravity.
2. That agent's installed Forge instruction runs first.
3. It finds the project root and runs `forge session-start --path <project-root>`.
4. The command creates or refreshes a unique local `session_id` lease for that agent task. MCP accesses the repository SQLite database directly, so agent work never depends on a browser process.
5. The agent reads active rules, recent outcomes, decisions, and unresolved risks before changing code.

The launcher must use a project lock and health check. It must not use a raw `forge start --path .` instruction because that command blocks the agent and could create duplicate servers.

### Agent end

1. The developer invokes `/forge_end`, supplied by the selected agent's globally installed Forge End skill.
2. The same agent reviews its own work and current conversation context.
3. It produces a clean, bounded handover: goal, problem, prior approach, why it failed, chosen fix, rationale, alternatives, validation, risks, unresolved work, scope, and an optional proposed rule.
4. The agent records real local proof of the validation before submitting the handover.
5. The skill calls `forge_complete_session`; Forge verifies the submitted evidence references, saves the handover as searchable shared context, evaluates any proposed rule, and marks the lease complete.
6. The skill heartbeats that exact session around longer work. Only then does it release the matching local Forge session lease. Normal release is rejected without that completion marker.
7. Forge shuts down only after the final active session for that project ends. A bounded stale-session timeout handles an agent crash without leaving Forge alive forever.

Forge never reads or stores raw chat transcripts. The agent creates the handover from its own available context and submits only the clean structured result.

## Runtime model

Each project has an independent local Forge database. Multiple Codex and Antigravity tasks have separate session-ID leases while safely sharing that database. The dashboard is optional: an Antigravity project sidecar owns a repository's loopback dashboard process and restart behavior; it is not a child of an agent shell command.

Install that sidecar with `forge install antigravity --path .`, then restart Antigravity so it discovers it. The sidecar receives a dedicated port generated during installation. Codex calls `forge_start_dashboard` through its persistent Forge MCP process after starting a lease; that MCP process owns the loopback dashboard until the final Forge lease ends. The MCP server and database remain local-only.

## Safety requirements

- Never overwrite an agent's existing instructions. Installation updates only that agent's clearly marked Forge-managed block.
- Never alter the other agent's configuration during a single-agent installation.
- Never launch two Forge processes for the same project.
- Never stop Forge while another active Codex or Antigravity session has a lease.
- Never expose a dashboard beyond loopback or store secrets/raw chats in runtime metadata.
- If Forge cannot start, the agent continues normally and reports that shared context is unavailable.

## Current state versus target

| Capability | Current state | Target state |
|---|---|---|
| Shared local database | Working | Keep |
| MCP context and outcome submission | Working when configured | Invoke automatically at agent start/end |
| Project dashboard at `127.0.0.1:8000` | Manual foreground command | Started safely by an agent session when needed |
| Codex/Antigravity installation | Manual MCP configuration | Agent-specific global installer and managed instructions |
| Detailed end handover | Agent can submit one | `/forge_end` guides and verifies it |
| Test/build proof | Outcome text and existing evidence citations | Persisted, sanitized validation-result evidence |
| Multi-agent process ownership | Working | Project lock, local health checks, one lease per installed agent, last-user shutdown, stale cleanup |

## Non-goals

- A permanent cloud service or 24/7 daemon.
- Reading an agent's transcript database or sending chat content to Forge.
- Automatically merging code, resolving conflicts, or changing GitHub data.
# Foundation consolidation note

Forge now uses one canonical **Session Handoff** record for new agent work. Legacy session-context and AGENTS guardrail records are retained as read-only history only. A rule-supporting handoff must cite applicable configured validation runs; arbitrary command results remain manual context and cannot advance a Learning Card. If Forge detects a manual edit inside its managed `AGENTS.md` block, it blocks projection and records a repair alert instead of overwriting developer content.
