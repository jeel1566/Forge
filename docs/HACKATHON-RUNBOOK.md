# Hackathon demo runbook

This tutorial validates Forge's central promise: a cited source becomes a pending decision, and a developer—not a model—decides whether it becomes memory.

## Prerequisites

Install Node.js, pnpm, Docker (optional), and the Supabase CLI. Create a Supabase project and copy the required placeholders into `.env`:

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GITHUB_WEBHOOK_SECRET=
GITHUB_TOKEN=
LLM_API_KEY=
FORGE_BASE_URL=http://localhost:3000
```

## Run the deterministic demo

1. Install dependencies and prepare the database.

   ```bash
   pnpm install
   pnpm supabase:push
   ```

2. Start the HTTP application and worker in separate terminals.

   ```bash
   pnpm dev
   pnpm worker
   ```

3. Open `http://localhost:3000`, load seeded evidence, and open its generated pending decision. Confirm it and verify that the Project Memory view shows its evidence citation.

You should be able to inspect the original evidence, the exact supporting span, the decision status, and the resulting current-memory entry. If no decision is generated, inspect the dead-letter view first; invalid provider output must never create a partial decision.

## Connect GitHub

Configure a webhook for `POST /v1/webhooks/github` using `GITHUB_WEBHOOK_SECRET`. Forge verifies the raw request body, returns `202`, and processes it asynchronously. Replay the same delivery to verify idempotency: it must create no second evidence item or job.

## Verify the coaching loop

Use seed data that contains the required observations for one fixed detector. Forge should show a cited pattern, one mapped principle, one active measurable goal, and a follow-up state. An absent or weak evidence set must be displayed as `insufficient_data`, not advice.
