# Technical requirements

## Runtime

Use one TypeScript codebase: a web/API process, a worker process, Supabase PostgreSQL, and a model-provider adapter. Both processes use the same service layer; only server-side code holds the Supabase service-role key.

| Boundary | Responsibility |
|---|---|
| HTTP API | Validate input, create durable work, return responses. |
| Worker | Claim jobs, normalize evidence, call models, and run deterministic checks. |
| PostgreSQL | System of record, idempotency boundary, and durable queue. |
| Provider adapter | Schema-validated extraction and verification requests. |

## Constraints

- Webhooks verify the raw-body HMAC, transactionally record the delivery and job, then return `202` without model work.
- All write paths are idempotent; model JSON validates before any derived write.
- Jobs retry three times with backoff, then remain visible as `dead_letter`.
- Webhook acknowledgement is under one second; cited-context reads are under two seconds excluding model work.
- JSONB holds source payloads only; queryable relationships stay relational.

## Configuration

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GITHUB_WEBHOOK_SECRET=
GITHUB_TOKEN=
LLM_API_KEY=
FORGE_BASE_URL=http://localhost:3000
```

`GITHUB_TOKEN` is limited to the demo repository. A GitHub App is a later replacement, not an MVP dependency.
