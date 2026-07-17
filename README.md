# Forge

Forge is a local-first, evidence-backed memory layer for coding agents. It turns local Git evidence and voluntary agent observations into cited, reviewable decisions; only confirmed decisions become project memory.

Forge is deliberately not a chat archive, personality profiler, or generic RAG store. When the evidence is insufficient, it says so.

## Status

The current slice runs entirely on the developer machine: SQLite is stored in `.forge/forge.sqlite3`, the dashboard binds to `127.0.0.1`, and no cloud account or model API key is required. It imports local Git commits and diffs idempotently, keeps agent proposals pending, and projects only developer-confirmed decisions into memory.

GitHub credentials can be managed from the dashboard and are protected with the current Windows account. GitHub polling and webhook ingestion are not implemented yet.

## Hackathon demo

The demo path is: import local Git evidence, submit a cited pending decision through MCP, edit or confirm it in Today, then retrieve the resulting cited memory in the next agent session.

```bash
pip install -e .
pnpm --dir frontend build
forge start --path .
```

Open `http://127.0.0.1:8000`. Forge imports local Git commits when it starts and exposes recent evidence in Today. MCP can create pending decisions and reflections, but never confirms memory. Forge also never writes `AGENTS.md`: an active agent must present a cited diff and receive approval first.

## Non-negotiable rules

1. Evidence is immutable and every derived claim links to exact evidence spans.
2. Agent and model output is pending evidence, never current memory by default.
3. No later evidence means `insufficient_data`, not confirmation.
4. One active developer intention may exist per workspace.

## Documentation

- [Product and scope](docs/PRD.md)
- [Runtime architecture](docs/ARCHITECTURE.md)
- [System invariants and lifecycle](docs/SYSTEM-DESIGN.md)
- [API and MCP contracts](docs/API-MCP-SPEC.md)
- [Data model and database constraints](docs/DATA-MODEL.md)
- [Implementation plan](docs/IMPLEMENTATION-PLAN.md)
- [Local setup](docs/OPEN-SOURCE-SETUP.md)
- [Hackathon demo runbook](docs/HACKATHON-RUNBOOK.md)
