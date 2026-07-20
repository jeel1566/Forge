# Forge product requirements

## Product outcome

Forge helps coding agents share trusted decisions—not overwhelming context—and turn each completed session into better rules for the next one. It reduces repeated mistakes by preserving the decision, failed approach, fix, validation, and bounded rule lifecycle as cited local records without collecting private chats.

## Shipped requirements

| Area | Requirement |
|---|---|
| Decision ledger | Persist project handoffs, decisions, work items, incidents, evidence, and vault search in SQLite. |
| Agent lifecycle | Install Codex or Antigravity separately; create/reuse per-repository leases; end with a cited handoff. |
| Learning | Use Learning Cards with deterministic identity, duplicate/conflict alerts, trusted validation gates, review due dates, verification, and retraction. |
| Rules | Support approval/autonomous policy, journaled managed-block projection, rollback, and reusable-rule approval across two repositories. |
| Validation | Execute only checked-in argv allowlist entries as trusted proof; retain manual validation as untrusted context. |
| GitHub | Optional read-only polling of PRs/reviews/comments with pagination, checkpoints, limits, retries, and safe telemetry. |
| Product surface | Local dashboard, FastAPI API, stdio MCP writes, and ChatGPT-compatible read-only HTTP MCP. |

## Non-goals

- Chat transcript extraction, hidden model training, or mandatory hosted AI.
- Cloud storage, background SaaS infrastructure, or a permanent daemon.
- Auto-merging, conflict resolution, GitHub write operations, automatic duplicate resolution, or automatic reusable-rule promotion.
- Treating a model claim, Git commit, arbitrary shell command, or silence as activation proof.

## Acceptance signals

- A new agent can retrieve the last cited handoff and active scoped rules without exploring generated files.
- An active rule is traceable to citations, validation configuration, and a projection record.
- A conflicting observation is visible as an alert and cannot silently alter a rule.
- Offline GitHub leaves local agent sessions, SQLite, dashboard, and MCP usable.
