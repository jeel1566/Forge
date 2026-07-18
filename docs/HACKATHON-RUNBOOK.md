# Demo runbook

## Demonstrate the current build

1. Install and run Forge locally.
2. Import local Git evidence and optionally poll a GitHub repository.
3. Use MCP to retrieve context and submit one cited session handoff or pending decision.
4. Show the dashboard evidence, decision status, and GitHub health.

## Demonstrate the new Forge design

Use the architecture diagram to explain the planned loop: Codex and Antigravity each summarise their own session, Forge evaluates cited local evidence, and a per-workspace policy controls whether a rule waits for approval or can be autonomously projected with rollback.

Do not present autonomous projection or GPT-5.6 integration as shipped functionality until the target MCP tools and migrations are implemented.
