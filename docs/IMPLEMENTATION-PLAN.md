# Implementation Plan

## Phase 0 — Repository and local developer experience

Create the monorepo, package scripts, `.env.example`, Docker compose, Supabase migration setup, health endpoint, CI, MIT license, contribution guide, and seeded default workspace/principles.

**Done when:** a clean clone installs dependencies, applies migrations, starts web/API plus worker, and returns a health response.

## Phase 1 — Evidence ledger and GitHub ingestion

Implement tables, migrations, webhook signature validation, delivery deduplication, Postgres jobs, worker job claiming, GitHub normalization, and evidence/span views.

**Done when:** replaying one GitHub delivery creates one evidence record, while a tampered signature is rejected.

## Phase 2 — Decisions and project memory

Implement extraction model adapter, strict JSON validation, pending decisions, citation display, confirm/reject actions, and versioned project-memory projections.

**Done when:** a cited explicit decision appears pending; confirmation creates current memory; rejection does not.

## Phase 3 — MCP server

Implement the five MCP tools: context, search, record decision, active coaching, and record observation. Keep all agent-created decisions pending.

**Done when:** a configured coding agent can retrieve citations and submit a decision without directly changing current memory.

## Phase 4 — Verification, patterns, and coaching

Implement later-evidence selection, deterministic goal evaluation, three initial pattern detectors, fixed principle mapping, priority selection, metric snapshots, and escalation after two misses.

**Done when:** seeded demo evidence produces one cited pattern, one active goal, and a follow-up result.

## Phase 5 — Dashboard and demo polish

Build Evidence, Decisions, Project Memory, Patterns, and Coaching views. Add empty/insufficient-data states, dead-letter visibility, demo seed/reset, tests, and deployment documentation.

**Done when:** a judge can follow the README from clone to an explainable feedback-loop demo.

## Scope cuts if time is short

Keep: commits, PR reviews, one agent observation tool, pending decision review, one large-commit pattern, and one coaching goal.

Defer: multiple repositories, full PR diff interpretation, advanced review-theme classifier, GitHub App OAuth, vector search, automatic rules-file generation, and multi-user access.
