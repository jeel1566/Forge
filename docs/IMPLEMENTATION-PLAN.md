# Historical implementation record

> This page records the earlier implementation plan. The described vertical slice and product surface are now shipped; use the README and architecture documents for current behavior.

## Principle

Keep the existing local-first stack: Python, FastAPI, MCP, SQLite, Git, and optional read-only GitHub polling. Do not add cloud storage, background infrastructure, vector search, LangChain, or a model API. Codex and Antigravity provide the reasoning and self-summary; Forge provides the durable evidence-backed loop.

## Completed vertical slice

Forge now has forward-only migrations for workspace policy, structured outcomes, versioned rules, citations, and verification. A workspace can select approval or autonomous mode.

Agents now submit bounded, idempotent, cited self-summaries. Two independently cited outcomes with validation make a scoped rule eligible. Approval mode shows an exact diff; autonomous mode writes only Forge’s managed `AGENTS.md` block. Contradicted evidence retracts the rule and rewrites that block.

## Next — Richer verification and pattern loop

Add review/expiry times, richer independent-pattern classification, and a dashboard timeline that joins outcomes, versions, and verification evidence.

## Phase 5 — Product surface and migration

Show policy, active/candidate/retracted rules, evidence, history, recovery, and GitHub health in the dashboard. Keep legacy review-first handoffs readable and migrate only through additive schema changes. Update the repository skill only after target MCP tools exist.

## Definition of done

- A Codex session and an Antigravity session share the same local, cited context.
- A verified repeated failure can create a scoped rule according to the selected policy.
- Every autonomous activation can be explained and rolled back from local history.
- No raw transcript, secret, auto-merge, or GitHub write enters the loop.
- Focused tests cover policy persistence, duplicate outcomes, evidence gates, rollback, restart, and offline behavior.
