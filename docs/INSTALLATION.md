# Forge installation guide

This guide installs Forge for Codex or Antigravity and, optionally, connects its **read-only** project memory to ChatGPT. Forge stays local-first: every project keeps its own SQLite database in `.forge\forge.sqlite3`; Forge never reads chat transcripts.

## Choose your setup

| Where you use Forge | Install once | Start when working | Optional dashboard |
|---|---|---|---|
| Codex | `forge install codex` | Agent instruction starts a local Forge session | MCP tool starts it when requested |
| Antigravity | `forge install antigravity --path .` | Agent instruction starts a local Forge session | Antigravity sidecar |
| ChatGPT web | Secure MCP Tunnel setup | Forge HTTP server and tunnel client | No dashboard required |

Codex and Antigravity use Forge directly on the same computer. They do not need a tunnel, OpenAI Platform key, or public server. ChatGPT web is optional and uses a separate read-only connection.

## 1. Install Forge

Install the published package once:

```powershell
pipx install forge
forge doctor --path .
```

For a source checkout during development, run its commands from the repository with `python -m backend.app.cli ...` if your installed `forge` command has not yet been upgraded.

## 2. Install one coding agent

Install only the agent you use. Re-running either command is safe.

```powershell
forge install codex
forge install antigravity --path .
```

The Codex installer changes only `~/.codex`. The Antigravity installer changes only `~/.gemini` and, with `--path .`, creates that repository's dashboard sidecar. Both add a marked Forge instruction block and a Forge End skill. They preserve unrelated MCP servers and agent instructions.

Restart the selected agent once after installation so it discovers the MCP configuration.

## 3. Normal local session

At the start of meaningful work, Forge's managed agent instruction runs:

```powershell
forge session-start --path . --agent codex
```

It creates or reuses the current project's `.forge\forge.sqlite3` and returns a session ID. The agent then reads compact context through Forge MCP. At `/forge_end`, the agent runs configured checks, saves one transcript-free cited handoff, and releases that same session ID.

The dashboard is optional. Codex starts it through `forge_start_dashboard`; Antigravity uses its project sidecar. Local MCP and SQLite do not require a dashboard server.

## 4. Optional ChatGPT web connector

### What this adds

ChatGPT web cannot launch Forge's local `forge-mcp` command. Forge therefore provides a separate loopback-only HTTP endpoint that exposes **read tools only**. OpenAI's Secure MCP Tunnel connects ChatGPT to that endpoint without exposing Forge publicly.

This is optional. Do not set it up if you do not want to use an OpenAI Platform tunnel. It does not add ChatGPT write tools, validation execution, rule approval, dashboard access, tokens, transcripts, raw command output, or raw GitHub payloads.

### Requirements

- ChatGPT Developer Mode and Tunnel access for your workspace.
- A tunnel created in [OpenAI Platform Tunnels](https://platform.openai.com/settings/organization/tunnels), scoped to the same ChatGPT workspace.
- A restricted Platform runtime key with **Tunnels: Read + Use**. This is not a model key; never share it in chat, source control, Forge, or logs.
- OpenAI's `tunnel-client` installed on the computer. Get it from Platform Tunnels or the [official releases](https://github.com/openai/tunnel-client/releases/latest).

### First-time connector setup

1. Create the tunnel in Platform Tunnels and copy its `tunnel_...` ID.
2. Create the restricted runtime key in [Platform Runtime API Keys](https://platform.openai.com/settings/organization/api-keys). Keep it private.
3. Start Forge's read-only HTTP endpoint in one PowerShell window:

   ```powershell
   forge session-start --path . --agent codex
   forge mcp-http --path . --port 8765
   ```

4. Start the tunnel client in a second PowerShell window. Let it choose a free health port so a reserved `8080` port cannot block startup:

   ```powershell
   $env:CONTROL_PLANE_API_KEY = "<runtime-key>"
   $healthFile = Join-Path $env:TEMP "forge-tunnel-health.url"

   tunnel-client run --control-plane.tunnel-id "tunnel_..." --control-plane.api-key "env:CONTROL_PLANE_API_KEY" --mcp.server-url "http://127.0.0.1:8765/mcp" --health.listen-addr "127.0.0.1:0" --health.url-file "$healthFile"
   ```

5. In another window, confirm the tunnel is ready:

   ```powershell
   $healthUrl = Get-Content $env:TEMP\forge-tunnel-health.url
   Invoke-WebRequest "$healthUrl/readyz"
   ```

   A successful response has status code `200`.

6. In ChatGPT web, go to **Settings → Apps/Connectors → Create**, choose **Tunnel**, paste the same `tunnel_...` ID, choose **No Auth**, acknowledge the warning, then create the connector and scan tools.

The form expects the tunnel ID, **not** `http://127.0.0.1:8765/mcp` and not the local health URL. After creation, Forge appears under ChatGPT Apps/Connectors or MCP with a development label; it is not an old-style Plugin entry.

### Daily use and restart behavior

Create the tunnel and ChatGPT connector once. For each computer restart or whenever the processes are closed, start both of these again while using ChatGPT:

```powershell
forge mcp-http --path . --port 8765
tunnel-client run ...
```

Keep both windows open. The connector remains saved in ChatGPT, but it cannot retrieve Forge data while either local process is stopped. A later managed-runtime setup can supervise `tunnel-client`; this guide intentionally uses the visible foreground setup first.

## Verify and repair

```powershell
forge doctor --path .
forge doctor --path . --agent codex
forge repair codex
forge uninstall codex
```

`doctor` is read-only. `repair` restores only Forge-managed agent configuration. `uninstall` removes only Forge's MCP entry, managed instructions, and Forge End skill; it never deletes a project's `.forge` data.

## Troubleshooting

| Problem | What to do |
|---|---|
| `forge` is not recognized | Open a new PowerShell after installation, or use `python -m backend.app.cli` from the source checkout. |
| ChatGPT does not list Forge | Confirm the connector exists under Apps/Connectors, start a new chat, then enable Forge from the Apps/Tools picker. |
| ChatGPT connector creation fails | Confirm the tunnel exists, its ID is correct, and it is scoped to the same ChatGPT workspace. |
| `listen tcp 127.0.0.1:8080` fails | Use `--health.listen-addr "127.0.0.1:0"` and `--health.url-file` exactly as shown above. |
| Tunnel is not ready | Keep Forge HTTP running, check `$healthUrl/readyz`, then inspect the tunnel-client terminal for its safe error message. |
| A runtime key was pasted into chat or committed | Revoke it immediately, create a new restricted runtime key, and never paste the replacement key anywhere except your local PowerShell environment. |

## Security boundaries

- Forge's SQLite data remains on the developer machine.
- The HTTP endpoint binds only to `127.0.0.1`.
- Secure MCP Tunnel is outbound from the developer machine; Forge does not open a public listener.
- ChatGPT receives only the requested compact read-tool result.
- Forge never persists or returns tokens, authorization headers, raw transcripts, raw command output, or raw GitHub response bodies.
- Use Codex or Antigravity for developer-reviewed Forge writes; the ChatGPT transport is deliberately read-only.

For OpenAI-side availability and permissions, see the [Developer Mode and MCP apps guide](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta) and the [Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
