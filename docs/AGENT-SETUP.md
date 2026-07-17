# Agent setup

Forge MCP is a local stdio process. It opens the same SQLite database used by `forge start`; it does not connect to ChatGPT, Codex, or Antigravity transcripts.

## Prerequisite

Install Forge, then start it once for the repository database:

```powershell
pipx install forge
forge start --path C:\path\to\repository
```

Set the database path to that repository's `.forge\forge.sqlite3` when configuring the MCP process. Do not put GitHub tokens in MCP configuration.

## Codex

Add the local MCP server with Codex:

```powershell
codex mcp add forge --env FORGE_DB_PATH="C:\path\to\repository\.forge\forge.sqlite3" -- forge-mcp
```

The repository-local skill is at `.agents\skills\forge`. It retrieves confirmed cited context at session start and may create one pending, evidence-backed item at session end.

## Antigravity

Open **Manage MCP Servers** → **View raw config**, then add this entry to `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "forge": {
      "command": "forge-mcp",
      "env": {
        "FORGE_DB_PATH": "C:\\path\\to\\repository\\.forge\\forge.sqlite3"
      }
    }
  }
}
```

Restart or refresh the MCP connection after saving. Antigravity uses the same local stdio MCP server and receives only tool inputs and outputs; Forge never reads Antigravity transcripts.

## Offline behavior

If the database does not exist, every MCP call reports that Forge is offline and asks the agent to continue without Forge context. It never creates an empty database from an incorrect configuration.
