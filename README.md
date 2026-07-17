# Forge

Forge is an evidence-backed memory and coaching loop for one developer. It turns GitHub events and voluntary agent observations into cited, reviewable decisions; only confirmed decisions become project memory. Repeated, measurable evidence can produce one coaching goal.

Forge is deliberately not a chat archive, personality profiler, or generic RAG store. When the evidence is insufficient, it says so.

## Status

This repository currently contains the implementation specification and runbooks. The commands below are the delivery contract for the first implementation slice; they will work after that slice is scaffolded.

## Hackathon demo

The judge path is: seed or receive one GitHub delivery, inspect its evidence, confirm one pending decision, and view one cited coaching goal. The app must work locally with no source changes after configuration.

```bash
cp .env.example .env
pnpm install
pnpm supabase:push
pnpm dev       # dashboard and HTTP API
pnpm worker    # durable background jobs
```

Open `http://localhost:3000`. Use the seeded demo evidence or configure a GitHub webhook for `POST /v1/webhooks/github`.

## Non-negotiable rules

1. Evidence is immutable and every derived claim links to exact evidence spans.
2. Agent and model output is pending evidence, never current memory by default.
3. No later evidence means `insufficient_data`, not confirmation.
4. Only one coaching cycle may be active in a workspace.

## Documentation

- [Product and scope](docs/PRD.md)
- [Runtime architecture](docs/ARCHITECTURE.md)
- [System invariants and lifecycle](docs/SYSTEM-DESIGN.md)
- [API and MCP contracts](docs/API-MCP-SPEC.md)
- [Data model and database constraints](docs/DATA-MODEL.md)
- [Implementation plan](docs/IMPLEMENTATION-PLAN.md)
- [Local setup](docs/OPEN-SOURCE-SETUP.md)
- [Hackathon demo runbook](docs/HACKATHON-RUNBOOK.md)
