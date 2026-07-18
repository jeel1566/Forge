# Codex and Antigravity setup

## Current installation

```powershell
pip install -e .
forge start --path C:\path\to\repository
```

Forge creates or opens `C:\path\to\repository\.forge\forge.sqlite3`. Configure both agents to use this same database.

### Codex

```powershell
codex mcp add forge --env FORGE_DB_PATH="C:\path\to\repository\.forge\forge.sqlite3" -- forge-mcp
```

### Antigravity

Add this to `~/.gemini/config/mcp_config.json`:

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

Restart the MCP connection after saving.

## How agents use Forge

1. At session start, the agent reads repository instructions and calls Forge for relevant local context.
2. The agent works normally; Forge never watches or extracts the private chat.
3. At session end, **the same agent** summarises its own decisions, failures, prior approach, fix, validation, and unresolved work.
4. The agent submits the compact structured outcome through MCP with evidence references.
5. The next Codex or Antigravity session retrieves that shared memory.

Codex does not summarise Antigravity. Antigravity does not summarise Codex. Both contribute to and read the same local Forge memory.

## Policy modes: v1 target

During `forge_initialize_workspace`, Forge asks once whether this workspace uses `approval` or `autonomous` rules. In approval mode, the agent shows the exact managed `AGENTS.md` diff before activation. In autonomous mode, Forge may update only its managed rule section after its evidence gate succeeds; every update is versioned and reversible.

The current build has the review-first guardrail handoff flow. Do not configure agents to call the target tools until they are implemented.

## Offline behavior

If the local database is missing or Forge is stopped, MCP reports that it is offline. The agent continues without Forge context; it does not create a database in an unintended path or send data anywhere.
