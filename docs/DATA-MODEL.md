# Data model

## Current store

The existing local SQLite store contains repositories, immutable evidence/spans, decisions/citations, session handoffs/citations, work sessions, coordination state, GitHub polling state/events, reflections, intentions, and guardrail handoffs. It is migrated forward-only.

## Canonical learning records

```text
workspaces
workspace_rule_policies
session_outcomes (public name: Session Handoff) -> evidence_spans
validation_runs -> evidence_spans
learning_cards -> session_outcomes + validation_runs
rule_versions -> learning_cards
rule_verifications -> rule_versions + validation_runs
rule_projections -> rule_versions
```

| Entity | Purpose | Constraint |
|---|---|---|
| `workspace_rule_policies` | One persisted `approval` or `autonomous` choice per workspace. | Exactly one active policy and auditable change history. |
| `session_outcomes` | Canonical agent-authored Session Handoff. | Bounded structured fields; never raw transcript. |
| `validation_runs` | Safe result of a configured or manual validation. | Only trusted configured runs can support cards. |
| `learning_cards` | Canonical observed problem and lifecycle. | Identity is normalized scope, area, trigger, and action. |
| `decision_records` | Why a change was made, changed, removed, or fixed. | Cites source outcome and evidence. |
| `rule_versions` | Immutable scoped rule text and projection history. | Linked to one Learning Card; cards own lifecycle. |
| `rule_evaluations` | Deterministic activation checks. | Stores threshold inputs and reason. |
| `rule_verifications` | Later support, contradiction, or insufficient data. | Cites later evidence; silence is not stored as support. |
| `rule_projections` | Hash-bound managed `AGENTS.md` projection history. | Records generated/applied content hash and rollback predecessor. |

## Privacy and retention

Legacy `session_contexts`, old guardrail records, and existing candidate rules remain read-only history. No table stores GitHub tokens in telemetry, authorization headers, raw sensitive response bodies, command output, or raw chat transcripts. Referenced validation evidence is retained; only unreferenced validation runs older than 90 days are cleaned up.
