# Technical requirements

## Runtime boundaries

Forge remains a local Python application: FastAPI dashboard/API on `127.0.0.1`, SQLite as system of record, local stdio MCP for active agents, local Git as primary evidence, and opt-in read-only GitHub polling.

## V1 requirements

- Additive, forward-only SQLite migrations only; never edit an applied migration.
- All learning writes are idempotent and have stable IDs or idempotency keys.
- Rule evaluation is deterministic from persisted evidence and workspace policy, not a model confidence claim.
- `AGENTS.md` projections are bounded to a managed section, hash-bound, versioned, and reversible.
- SQLite WAL, bounded retries, clean shutdown, and no concurrent GitHub poll per workspace.
- No secret, raw transcript, raw GitHub response body, or authorization header enters logs, MCP output, or exports.
- Every dashboard/MCP response remains useful when GitHub is offline or rate limited.

## Model boundary

Forge has no LLM dependency. A model selected in Codex or Antigravity may produce a self-summary, but Forge validates the submitted structure and evidence without calling that model itself.
