# Product Requirements Document

## Product

Forge is a developer memory and coaching system that helps a single developer preserve project decisions and improve recurring engineering behaviour. It combines repository events with voluntarily supplied agent evidence, then makes only evidence-cited claims.

## Problem

Coding agents and developers lose rationale between sessions. Existing code explains what happened but often not why. Generic memory/RAG systems retrieve text but do not distinguish confirmed decisions, later contradictions, and repeated behaviours with measurable outcomes.

## Users and MVP scope

The MVP serves one developer working on one or more GitHub repositories. There is no account system, shared workspace, team analytics, or passive scraping of agent/ChatGPT conversations. An agent can submit an explicit decision or observation through MCP; GitHub contributes commits and review evidence through webhooks.

## User outcomes

1. Before starting work, a coding agent receives compact, cited context instead of rediscovering old decisions.
2. The developer can confirm or reject a proposed decision with one click.
3. The developer can inspect the exact evidence behind any memory or coaching claim.
4. Once enough observations exist, Forge offers one measurable coaching goal and evaluates it in the next window.

## Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Receive GitHub push, PR, review, and review-comment events idempotently. |
| FR-2 | Store raw evidence and precise quoted/diff spans. |
| FR-3 | Extract only cited, pending decisions from evidence. |
| FR-4 | Require explicit user confirmation before writing current project memory. |
| FR-5 | Verify decisions against later relevant evidence. |
| FR-6 | Detect fixed, observable patterns from repeated evidence. |
| FR-7 | Map patterns to a fixed principle catalogue, not invented advice. |
| FR-8 | Maintain at most one active coaching cycle per workspace. |
| FR-9 | Serve cited context and controlled evidence writes through MCP. |

## Success metrics

- 100% of displayed decisions, verification results, and coaching claims expose one or more source citations.
- 0 unconfirmed decisions enter current project memory.
- A duplicate GitHub delivery creates no duplicate evidence or job.
- A demo repository produces one reviewable decision and one evidence-backed pattern.
- The dashboard explains `insufficient_data` rather than generating weak advice.

## Non-goals

- Replacing GitHub, a project-management tool, or a general chat archive.
- Scoring developers as good or bad people.
- Auto-editing or auto-committing `AGENTS.md`.
- Multi-user permissions in the MVP.
