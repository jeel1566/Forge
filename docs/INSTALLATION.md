# Install and operate Forge

Forge is local-first. Each repository stores its data in `.forge/forge.sqlite3`; normal Codex and Antigravity use does not need a cloud account, tunnel, dashboard, or GitHub token.

## Prerequisites

- Python 3.11 or newer.
- `pipx` for a global isolated CLI install.
- Git for repository registration and local evidence.
- Node.js plus `pnpm` only when developing Forge from source or running the dashboard build.

## Install the CLI

The public package name is `forge-local-memory`; its command is `forge`.

```powershell
# Before the first PyPI publication
pipx install "git+https://github.com/jeel1566/Forge.git@main"

# After the PyPI release is published
# pipx install forge-local-memory

forge --help
```

For a source checkout, use `python -m backend.app.cli ...` or `pipx install .` from the repository root.

## Install one agent

Choose the agent you use. Each command changes only that agent's Forge-owned MCP entry, instruction block, and Forge End skill.

```powershell
forge install codex

# Run inside a repository when Antigravity should also own a dashboard sidecar.
forge install antigravity --path .
```

Restart the chosen agent once so it discovers the MCP server. Check setup without changing data:

```powershell
forge doctor --path . --agent codex
forge doctor --path . --agent antigravity
```

Re-run the installer safely, or repair only Forge-owned files:

```powershell
forge install codex --dry-run
forge install codex --repair
forge repair codex
forge uninstall codex
```

## Start and finish an agent session

The managed agent instruction performs this automatically at meaningful session start. You can run it manually to diagnose setup:

```powershell
forge session-start --path . --agent codex
```

Keep the returned `session_id`. The agent then calls `forge_get_session_start_context`. When the developer types `/forge_end`, the installed skill runs applicable configured validations, saves a structured Session Handoff with `forge_complete_session`, displays persisted alerts, and releases the same session.

Manual release is intentionally strict:

```powershell
forge session-end --path . --session-id <session-id>
```

Use `--abandon --reason <fixed-reason>` only when the developer explicitly abandons a failed or incomplete session.

## Dashboard

The dashboard is optional. MCP and SQLite work without it.

- **Codex:** call `forge_start_dashboard` through Forge MCP after session start.
- **Antigravity:** `forge install antigravity --path .` creates a local sidecar that owns the dashboard.
- **Manual development:** `forge start --path . --port 8000`, then open `http://127.0.0.1:8000`.

All dashboard/API listeners bind to `127.0.0.1`.

## Trusted validation

Put an allowlist in the repository root. Forge runs these argument arrays without a shell and stores only the validation ID, result, duration, config hash, scopes, and categories—not command output.

```json
{
  "validations": [
    {
      "id": "backend-tests",
      "argv": ["python", "-m", "unittest", "discover", "-s", "backend/tests", "-v"],
      "scopes": ["backend"],
      "categories": ["testing"],
      "timeout_seconds": 900
    }
  ]
}
```

Run a trusted entry by ID:

```powershell
forge validate-configured --path . backend-tests
```

`forge validate --label ... -- <command>` is manual/untrusted context and cannot advance or verify a Learning Card.

## GitHub polling (optional)

Register a repository and configure a fine-grained read-only GitHub token through the local dashboard/API only when PR/review evidence is useful. Polling is disabled by default. It reads pull requests, reviews, and review comments; it never writes GitHub data.

Each poll is paginated, idempotent, bounded by configured page/item/time limits, protected against overlap, and resumes from persisted checkpoints. Safe telemetry includes status, timing, rate-limit state, retry state, partial status, and last success. It excludes tokens, authorization headers, and raw bodies.

## ChatGPT web connector (optional, read-only)

ChatGPT web cannot launch Forge's stdio MCP server. The optional connector uses a separate loopback HTTP endpoint and OpenAI's separately installed `tunnel-client`.

1. Start a local session and HTTP endpoint:

   ```powershell
   forge session-start --path . --agent codex
   forge mcp-http --path . --port 8765
   ```

2. Create an OpenAI Secure MCP Tunnel, then run the tunnel client with a restricted tunnel runtime key in your local shell. Do not paste that key into chat, source, Forge, or logs.
3. In ChatGPT Developer Mode, create a Tunnel app using the `tunnel_...` ID—not the `127.0.0.1` URL—and scan tools.

This transport exposes read tools only: context, handoffs, evidence metadata, cards, rules, alerts, vault search, coordination, decisions, and GitHub status. It never exposes Forge writes, validation execution, approval, secrets, transcripts, raw output, or raw GitHub payloads.

## Maintenance and recovery

```powershell
forge doctor --path .
forge repair --path .
forge backup --path . --output .\forge-backup.sqlite3
forge export --path . --output .\forge-export.json
forge vault export --path .
```

`doctor` is read-only. `repair` removes only stale Forge runtime metadata or restores Forge-owned agent setup. `backup` and `export` never include connector secrets. `vault export` writes generated files under `.forge/vault`; edits to those files never become new Forge memory.

## Upgrade

```powershell
pipx upgrade forge-local-memory
forge doctor --path .
```

For the first source-installed release, reinstall from GitHub with the same `pipx install --force "git+..."` command. See [Releasing Forge](RELEASING.md) for maintainers.
