# Technical Requirements Document

## Chosen stack

| Area | Decision |
|---|---|
| Database | Supabase-hosted PostgreSQL |
| API/dashboard | TypeScript web application and server API |
| Background processing | A separate TypeScript worker using a Postgres-backed jobs table |
| Ingestion | GitHub webhooks plus MCP-controlled agent writes |
| Database access | Server-side Supabase service-role client only |
| Model calls | Provider adapter behind extraction and verification jobs |

## Constraints

- The webhook route must return `202` without waiting for an LLM.
- All state-changing work must be idempotent.
- The browser must not access tables with a service-role key.
- Raw source payloads may use JSONB; source-of-truth relationships must remain relational.
- Every model output must validate against a JSON schema before persistence.

## Non-functional requirements

| Concern | Requirement |
|---|---|
| Auditability | Every claim has evidence spans and model/version metadata. |
| Reliability | Jobs retry three times with backoff, then become visible dead-letter failures. |
| Performance | Webhook acknowledgement under one second; context response under two seconds excluding model work. |
| Privacy | No passive agent-chat collection; submitted evidence remains workspace-scoped. |
| Operability | Local development, hosted Supabase, migrations, seed data, and a health check are documented. |

## Required configuration

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GITHUB_WEBHOOK_SECRET=
GITHUB_TOKEN=
LLM_API_KEY=
FORGE_BASE_URL=http://localhost:3000
```

`GITHUB_TOKEN` is limited to the demo repository in the MVP. A GitHub App replaces it in a later release.
