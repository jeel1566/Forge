# Global agent installation and Forge lifecycle

## Decision

Forge is installed once for an individual coding agent, not once for Forge itself and not for every other agent. Installing into Codex changes only Codex's global Forge setup. Installing into Antigravity changes only Antigravity's global Forge setup.

The installation makes Forge available in every project that agent opens. Each project retains separate local Forge data in its own `.forge` directory.

## Intended everyday flow

### Agent start

1. A developer opens a project with Codex or Antigravity.
2. That agent's installed Forge instruction runs first.
3. It finds the project root and runs `forge session-start --path <project-root>`.
4. The command safely reuses a running Forge instance for that project or launches one in the background, waits for local readiness, and records that the agent session is using it.
5. The agent reads active rules, recent outcomes, decisions, and unresolved risks before changing code.

The launcher must use a project lock and health check. It must not use a raw `forge start --path .` instruction because that command blocks the agent and could create duplicate servers.

### Agent end

1. The developer invokes the agent's end command: `/forge_end` (implemented as the agent host's supported reusable command or skill).
2. The same agent reviews its own work and current conversation context.
3. It produces a clean, bounded handover: goal, problem, prior approach, why it failed, chosen fix, rationale, alternatives, validation, risks, unresolved work, scope, and an optional proposed rule.
4. The agent records real local proof of the validation before submitting the handover.
5. Forge verifies the submitted evidence references, saves the handover as searchable shared context, and evaluates any proposed rule.
6. The end command releases the agent's local Forge session lease.
7. Forge shuts down only after the final active session for that project ends. A bounded stale-session timeout handles an agent crash without leaving Forge alive forever.

Forge never reads or stores raw chat transcripts. The agent creates the handover from its own available context and submits only the clean structured result.

## Runtime model

Each project has an independent local Forge process and database. A project process should use an available loopback port recorded in that project's `.forge` runtime metadata; multiple projects must not all assume port `8000`.

`forge start --path .` remains the explicit foreground command for developers who want to view the dashboard or run optional scheduled GitHub polling. `forge session-start` is the future non-blocking agent launcher. The MCP server and database remain local-only.

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
| Multi-agent process ownership | Not implemented | Project lock, session leases, last-user shutdown, stale cleanup |

## Non-goals

- A permanent cloud service or 24/7 daemon.
- Reading an agent's transcript database or sending chat content to Forge.
- Automatically merging code, resolving conflicts, or changing GitHub data.
