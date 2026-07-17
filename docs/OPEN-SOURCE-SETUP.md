# Open-source setup

Forge runs locally with SQLite and no account, token, or model API key.

```bash
pip install -e .
pnpm --dir frontend build
forge start --path .
```

Open `http://127.0.0.1:8000`. The server stores data at `.forge/forge.sqlite3` inside the selected repository and imports local Git commits at startup.

Use `forge backup --path . --output forge-backup.sqlite3` for a local SQLite copy, or `forge export --path . --output forge-export.json` for a non-secret JSON export.
Run `forge doctor --path .` to verify the local SQLite database integrity.

## Agent connection

Run `python -m backend.app.mcp_server` from an active Codex or Antigravity MCP configuration. MCP reads return only confirmed, cited memory and an active intention. MCP writes create pending decisions or reflections; they never confirm memory or access raw chat transcripts.

## Optional GitHub polling

Save a fine-grained, read-only GitHub token with `Pull requests: Read` access in the dashboard, then select **Poll GitHub**. Forge derives the GitHub repository from the local `origin`, records PR and review evidence locally, and remains fully functional with polling disabled.

## Privacy defaults

- Forge binds to `127.0.0.1` only.
- Forge rejects non-loopback requests and mutating browser requests from non-local origins.
- SQLite, Git evidence, and exports remain local.
- GitHub polling is optional future work; public webhooks are not required.
- Forge never writes `AGENTS.md`. An agent must show an exact proposed diff and receive explicit approval before applying it.
