# Codex and Antigravity setup reference

The [installation guide](INSTALLATION.md) is the primary step-by-step setup document. This page remains the concise reference for agent-specific installation, repair, and local lifecycle behavior.

## Install Forge once

```powershell
pipx install forge-local-memory
forge install codex
# or, from each dashboard-enabled project:
forge install antigravity --path .
```

`pipx` places `forge` and `forge-mcp` on the user PATH. Installing Codex changes only `~/.codex`; installing Antigravity changes only `~/.gemini`. Each installer preserves unrelated MCP servers and writes only a marked Forge instruction block.

The installer also adds a Forge-owned global `forge-end` skill for that selected agent only. Typing `/forge_end` asks the agent to review its own work, run configured validation, save one cited transcript-free handoff with `forge_complete_session`, show persisted alerts, and then release its lease. It never lets Forge read chat transcripts.

`forge install codex --dry-run` shows the intended Forge-owned changes without writing files. Re-running `forge install codex` is safe and reports whether setup is healthy; use `forge install codex --repair` or `forge repair codex` only to restore missing Forge-owned MCP entries, managed instructions, and the Forge End skill. Forge refuses to overwrite incomplete managed markers or a non-Forge skill.

For a pinned pre-release from this repository:

```powershell
pipx install "git+https://github.com/jeel1566/Forge.git@v0.1.0"
```

## Start a project session

When an installed agent opens a repository, its managed Forge instruction runs:

```powershell
forge session-start --path . --agent codex
```

This creates or opens that repository's `.forge\forge.sqlite3`, registers the repository, and creates or refreshes a session lease. MCP reads and writes this local database directly; it does not require a dashboard server.

For a dashboard that survives Antigravity command completion, install the project sidecar once from that repository:

```powershell
forge install antigravity --path .
```

The command creates one Forge-owned Antigravity sidecar configuration, enables only that sidecar, and prints its loopback URL. Fully restart Antigravity once so it discovers the new sidecar. The sidecar owns and restarts the dashboard process; Forge never uses a detached child of an agent shell command for this purpose.

For Codex, the installed start instruction calls `forge_start_dashboard` through Forge MCP after the session lease is created. The persistent MCP process owns the loopback dashboard, so it survives the one-shot agent shell command and is released after the final Forge lease ends.

Keep the returned `session_id`. At the end of the agent session, the Forge End skill completes and releases that exact lease:

```powershell
forge session-end --path . --session-id <session_id>
```

Forge stops after the final active agent lease is released. `forge_heartbeat_session` refreshes a live session; expired leases and stale startup locks are cleaned safely on the next Forge operation.

## Check and repair

```powershell
forge doctor --path .
forge doctor --path . --agent codex
forge repair --path .
forge repair codex
```

`doctor` is read-only: it checks database integrity when a database exists, `forge.validation.json`, safe runtime metadata, and agent installation state. It never creates a database, prints tokens, or shows raw MCP configuration. `repair --path .` removes only stale Forge runtime metadata; it never removes project history or stops an unverified process.

Remove an agent-specific installation safely with:

```powershell
forge uninstall codex
# or, for a project sidecar: forge uninstall antigravity --path .
```

Uninstall removes only that agent’s Forge MCP entry, Forge-managed instruction block, and Forge End skill. With `--path .`, Antigravity uninstall also removes only that repository's Forge-owned sidecar and enablement. It never deletes any repository’s `.forge` database or local shared history.

## Upgrade

```powershell
pipx upgrade forge-local-memory
forge doctor --path .
```

Install Forge once per agent, then use it in every project. Each project keeps separate local data in its own `.forge` directory.

## ChatGPT custom app (read-only)

Follow the complete [ChatGPT web connector instructions](INSTALLATION.md#4-optional-chatgpt-web-connector). The summary below is intentionally brief.

ChatGPT does not launch the local `forge-mcp` stdio command used by Codex and Antigravity. Start Forge's dedicated Streamable HTTP endpoint instead:

```powershell
forge session-start --path . --agent codex
forge mcp-http --path . --port 8765
```

This prints the local endpoint `http://127.0.0.1:8765/mcp` and keeps it running on loopback only. It requires an already initialized local Forge database and never creates one by itself.

Create an OpenAI Secure MCP Tunnel in Platform Tunnels with the same ChatGPT workspace scope, then copy its `tunnel_...` ID and obtain its runtime API key. Install the separate OpenAI `tunnel-client` binary and run it in another PowerShell window while Forge is running:

```powershell
$env:CONTROL_PLANE_API_KEY = "<runtime API key>"
tunnel-client run --control-plane.tunnel-id "tunnel_..." --control-plane.api-key "env:CONTROL_PLANE_API_KEY" --mcp.server-url "http://127.0.0.1:8765/mcp" --health.listen-addr "127.0.0.1:0" --health.url-file "$env:TEMP\forge-tunnel-health.url"
```

In ChatGPT web, enable Developer Mode, create a custom app, choose **Tunnel**, enter that same `tunnel_...` ID, select **No Auth**, then use **Scan Tools** and create the app. The ChatGPT form does not accept Forge's `127.0.0.1` address. ChatGPT plan and workspace-admin availability vary; use the current [OpenAI Developer Mode and MCP apps guide](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta) and [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) for the exact Platform permissions and client installation flow.

Forge deliberately exposes only read tools through this transport: compact session context, handoffs, local evidence metadata, rule/card state, alerts, vault search, coordination, and GitHub sync status. It never exposes writes, validation execution, credentials, tokens, raw command output, raw GitHub payloads, or transcripts. Use Codex or Antigravity for the explicit developer-reviewed Forge write workflow.

## How agents use Forge

1. At session start, the agent runs `forge session-start --path . --agent <agent>`, then calls `forge_get_session_start_context`.
2. The agent works normally; Forge never watches or extracts the private chat.
3. At session end, **the same agent** summarises its own decisions, failures, prior approach, fix, validation, and unresolved work.
4. The agent submits the compact structured outcome through MCP with evidence references.
5. The next Codex or Antigravity session retrieves that shared memory.

Codex does not summarise Antigravity. Antigravity does not summarise Codex. Both contribute to and read the same local Forge memory.

## Reusable rules and feedback

An active project rule can be submitted through `forge_request_reusable_rule`. Forge records only its safe local rule metadata and evidence count in the local reusable-rule registry. A reusable rule stays pending until two distinct local repositories have evidence-gated active versions of the same rule. It reaches another project only after the developer explicitly approves it with `forge_approve_reusable_rule`.

At the beginning of later sessions, `forge_get_session_start_context` returns approved reusable rules alongside the project's own active rules. A project can replace or ignore an approved reusable rule locally with `forge_override_reusable_rule`; that project-specific choice wins without changing the reusable source rule.

After a real session, Forge asks only three questions: whether the retrieved context was useful, what was irrelevant or missing, and whether the proposed rule should be approved, revised, coaching-only, or rejected. `forge_record_session_feedback` stores those explicit answers as cited local review data. It never reads chats or uses the feedback for hidden model training.

## Policy modes: v1 target

During `forge_initialize_workspace`, Forge asks once whether this workspace uses `approval` or `autonomous` rules. In approval mode, the agent shows the exact managed `AGENTS.md` diff before activation. In autonomous mode, Forge may update only its managed rule section after its evidence gate succeeds; every update is versioned and reversible.

The installed MCP command never hard-codes a particular repository database. It discovers the active repository's local `.forge` database and reports offline safely if session initialization has not run.

## Offline behavior

If the local database is missing or Forge is stopped, MCP reports that it is offline. The agent continues without Forge context; it does not create a database in an unintended path or send data anywhere.
