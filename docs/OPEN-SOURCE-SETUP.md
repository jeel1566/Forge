# Open-source setup

Forge runs locally with SQLite and no account, token, or model API key.

```bash
pip install -e .
pnpm --dir frontend build
forge start --path .
```

Open `http://127.0.0.1:8000`. The server stores data at `.forge/forge.sqlite3` inside the selected repository and imports local Git commits at startup.

## Agent connection

Run `python -m backend.app.mcp_server` from an active Codex or Antigravity MCP configuration. MCP reads return only confirmed, cited memory and an active intention. MCP writes create pending decisions or reflections; they never confirm memory or access raw chat transcripts.

## Privacy defaults

- Forge binds to `127.0.0.1` only.
- SQLite, Git evidence, and exports remain local.
- GitHub polling is optional future work; public webhooks are not required.
- Forge never writes `AGENTS.md`. An agent must show an exact proposed diff and receive explicit approval before applying it.
