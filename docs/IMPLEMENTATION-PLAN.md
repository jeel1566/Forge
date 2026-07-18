# New Forge implementation plan

## Principle

Keep the existing local-first stack: Python, FastAPI, MCP, SQLite, Git, and optional read-only GitHub polling. Do not add cloud storage, background infrastructure, vector search, LangChain, or a model API. Codex and Antigravity provide the reasoning and self-summary; Forge provides the durable evidence-backed loop.

## Phase 1 — Policy and schema

Add forward-only migrations for workspace rule policy, structured outcomes, decision records, versioned rules, evaluations, verifications, and projections. During workspace initialization ask once for `approval` or `autonomous`; persist the choice and change history.

## Phase 2 — Structured self-summary

Add one MCP write accepting a bounded, idempotent session outcome: scope, problem, prior approach, failure reason, alternatives, fix, verification, risk, citations, and agent identity. Add a compact context read that returns relevant rules and a capture worksheet.

## Phase 3 — Deterministic rule lifecycle

Implement evidence thresholds, duplicate detection, candidate states, exact rule scopes, version history, expiration/review points, and rollback. In approval mode, produce a hash-bound diff. In autonomous mode, allow only safe managed-block projection after the same deterministic gate passes.

## Phase 4 — Verification and pattern loop

Connect later Git/test/review/error evidence to rules. Mark support, contradiction, or `insufficient_data`; retract contradicted rules. Require independently cited repeated observations before strengthening a reusable rule.

## Phase 5 — Product surface and migration

Show policy, active/candidate/retracted rules, evidence, history, recovery, and GitHub health in the dashboard. Keep legacy review-first handoffs readable and migrate only through additive schema changes. Update the repository skill only after target MCP tools exist.

## Definition of done

- A Codex session and an Antigravity session share the same local, cited context.
- A verified repeated failure can create a scoped rule according to the selected policy.
- Every autonomous activation can be explained and rolled back from local history.
- No raw transcript, secret, auto-merge, or GitHub write enters the loop.
- Focused tests cover policy persistence, duplicate outcomes, evidence gates, rollback, restart, and offline behavior.
