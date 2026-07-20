# Technical requirements

- Python, FastAPI, SQLite, local Git, and MCP are the core runtime; no model SDK or cloud database is required.
- The dashboard/API/ChatGPT HTTP endpoint bind to loopback only.
- SQLite migrations are additive and forward-only; state-changing paths are idempotent where retries are expected.
- Runtime uses project locks, leases, instance identity, stale cleanup, and final-lease shutdown to prevent duplicate or wrongly stopped processes.
- Trusted validation executes configured argument arrays without a shell and stores safe status/duration metadata only.
- GitHub polling is optional, read-only, bounded, paginated, restart-safe, rate-limit-aware, and isolated from local features.
- All persistence, API, MCP, export, and log paths exclude raw chats, secrets, headers, raw command output, and raw GitHub bodies.
- The dashboard is a local product surface, not a requirement for MCP/SQLite operation.
