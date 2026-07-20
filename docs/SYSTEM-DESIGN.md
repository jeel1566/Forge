# System design and invariants

## Source of truth

Project SQLite is Forge's source of truth. `AGENTS.md` is only a generated projection of active scoped rules inside Forge's marked block. The dashboard, MCP, vault export, and API read persisted local data.

## Invariants

1. Agents submit their own structured handoffs; Forge never reads a transcript store.
2. Evidence links are immutable and every new learning record cites them.
3. Only trusted configured validation can automatically advance, activate, verify, or retract a Learning Card.
4. Duplicate/conflict and reusable-rule decisions remain developer-controlled.
5. A manual edit inside Forge's managed `AGENTS.md` block blocks projection and creates a repair alert; text outside the block is preserved.
6. Rule projection is atomic, journaled, versioned, and reversible.
7. Network loss never blocks local Forge operations.
8. No secret, raw command output, raw GitHub payload, authorization header, or raw chat enters normal persistence or transport output.

## Policy modes

| Mode | Activation path |
|---|---|
| `approval` | Ready, unflagged card → exact projection diff → developer approval → active. |
| `autonomous` | Ready, unflagged card with two independent trusted observations → active. |

Both modes use the same evidence gate, review date, projection journal, verification, and rollback behavior.

## Operational limits

- Trusted validation uses only checked-in argv arrays and per-entry timeouts.
- GitHub polling has page, item, and time limits and reports `partial` when a boundary is reached.
- GitHub retry uses bounded exponential backoff with jitter and respects `Retry-After`/rate-limit resets.
- Sync telemetry is compact and bounded to 30 days or 500 events.
- Reusable rules never leave the developer machine; they are a separate local SQLite registry.
