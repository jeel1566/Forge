# Agent lifecycle and local runtime

Forge installs per agent, not per repository. `forge install codex` updates only Codex-owned configuration; `forge install antigravity` updates only Antigravity-owned configuration. Each repository keeps a separate `.forge/forge.sqlite3` database.

## Start

1. An installed agent opens a repository.
2. Its Forge-managed instruction runs `forge session-start --path . --agent <agent>`.
3. Forge creates/reuses a repository runtime lease and returns `session_id`.
4. The agent calls `forge_get_session_start_context` before meaningful changes.

MCP talks directly to SQLite. A dashboard server is not required for this flow.

## End

When the developer types `/forge_end`, the agent's installed Forge End skill reviews only its own work, runs configured validations, writes one bounded cited Session Handoff, calls `forge_complete_session` with the exact session ID, presents persisted alerts, then releases the same lease.

If completion cannot be saved, the lease remains active unless the developer explicitly abandons it with one fixed safe reason.

## Multi-agent runtime

Codex and Antigravity can hold separate leases for the same repository. Forge reuses one local runtime and stops it only after the last lease ends. Stale crashed leases and startup locks are pruned safely. Runtime metadata includes an instance ID so Forge does not stop an unrelated process.

## Dashboard ownership

- Codex asks its persistent MCP process to start the dashboard when wanted.
- Antigravity can own a repository sidecar created by `forge install antigravity --path .`.
- A one-shot agent shell command never owns the dashboard process.

## Safety

Installer updates are atomic and limited to Forge-managed markers. Forge will not overwrite incomplete markers, a non-Forge skill, another agent's configuration, or manual edits inside its managed rule block.
