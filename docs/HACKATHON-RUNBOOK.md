# Hackathon demo runbook

This demo proves Forge's central promise: local Git evidence and an agent proposal become a pending decision, and only a developer can promote it to memory.

## Run the demo

```bash
pip install -e .
pnpm --dir frontend build
forge start --path .
```

Open `http://127.0.0.1:8000`. Forge imports the repository's Git commits into the local SQLite file at `.forge/forge.sqlite3`.

## Show the memory loop

1. Through MCP, call `forge_record_decision` with an explicit statement and supporting quote.
2. In Today, inspect the pending decision and its citation.
3. Confirm it. The next `forge_get_project_context` returns it as cited confirmed memory.
4. Set one active intention and show it in the same MCP context response.

No account, webhook, API key, or raw transcript access is required. Rejected proposals remain visible with their immutable evidence and never enter memory.

## Show the AGENTS.md boundary

When `forge_get_agents_guardrail_candidates` returns a repeated confirmed item, the active agent must show an exact `AGENTS.md` diff in chat. Apply it only after the developer explicitly approves. Forge itself does not read or write `AGENTS.md`.
