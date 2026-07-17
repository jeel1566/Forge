# Technical requirements

## Runtime

Forge is a Python local core: FastAPI serves the dashboard and API on `127.0.0.1`, SQLite is the system of record, and the MCP process starts only when an agent is active.

| Boundary | Responsibility |
|---|---|
| Local API | Validates developer-facing writes and serves context. |
| SQLite | Stores immutable evidence, spans, pending decisions, confirmed memory, and one intention. |
| Git importer | Idempotently records local commits and diffs by commit hash. |
| MCP | Offers cited reads and pending-only agent writes. |

## Constraints

- No cloud account, model API key, or public webhook is required.
- Git evidence is local and immutable; derived decisions cite exact spans.
- Agent writes default to pending and developer review is required for confirmation.
- Forge never reads raw chat transcripts or writes `AGENTS.md`.
- Optional GitHub polling and cloud sync are later opt-in integrations.

## Configuration

`FORGE_DB_PATH` optionally overrides the default `.forge/forge.sqlite3` database path. The default `forge start` server is always loopback-only.
