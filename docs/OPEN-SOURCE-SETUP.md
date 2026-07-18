# Local setup

## Run the current build

```powershell
pip install -e .
pnpm --dir frontend build
forge start --path .
```

Open `http://127.0.0.1:8000`. Data stays in `.forge/forge.sqlite3` in the selected repository. Use `forge backup`, `forge export`, and `forge doctor` for local maintenance.

## Connect agents

Use the commands in [agent setup](AGENT-SETUP.md) to point Codex and Antigravity at the same SQLite file. Both agents retrieve local context and submit their own summary through MCP; Forge does not connect to their transcript stores.

## Optional GitHub polling

Configure a fine-grained read-only token in the dashboard only if PR/review evidence is needed. Polling is disabled by default, remains local, and does not affect normal Git/MCP use when unavailable.

## New Forge status

The policy selection and autonomous rule-evolution loop are specified but not fully delivered in the current build. Follow [the implementation plan](IMPLEMENTATION-PLAN.md) before enabling or documenting target-only MCP tools in a production agent configuration.
