# Open-Source Setup and Distribution

## Release goal

An evaluator must be able to clone Forge, configure a Supabase project and GitHub repository, run the app locally, and see evidence flow to a pending decision without modifying source code.

## Required repository artifacts

```text
.env.example
docker-compose.yml
Dockerfile
package.json
pnpm-lock.yaml
apps/web/
apps/worker/
packages/core/
packages/mcp-server/
supabase/migrations/
supabase/seed.sql
docs/
LICENSE
CONTRIBUTING.md
```

## Required setup path

1. Create a Supabase project and copy its URL and service-role key into `.env`.
2. Add a GitHub webhook pointing to `/v1/webhooks/github`, configured with `GITHUB_WEBHOOK_SECRET`.
3. Apply migrations and seed the `default` workspace and fixed principles.
4. Start the web/API app and worker.
5. Push a commit or submit an MCP observation.
6. Open the dashboard and confirm/reject the generated pending decision.

## Required commands to deliver

```bash
pnpm install
pnpm supabase:push
pnpm dev
pnpm worker
pnpm test
docker compose up --build
```

## Environment template

```text
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GITHUB_WEBHOOK_SECRET=
GITHUB_TOKEN=
LLM_API_KEY=
FORGE_BASE_URL=http://localhost:3000
```

Never commit a populated `.env` file. Use placeholder values only in `.env.example`.

## Open-source defaults

- License: MIT for the hackathon repository unless a different contributor policy is required.
- No hosted account is required for local app use, but Supabase remains the managed database dependency.
- Provide a demo fixture repository or seeded sample evidence so judges can evaluate the feedback loop without connecting personal data.
