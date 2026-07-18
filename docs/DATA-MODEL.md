# Data model

## Current store

The existing local SQLite store contains repositories, immutable evidence/spans, decisions/citations, session handoffs/citations, work sessions, coordination state, GitHub polling state/events, reflections, intentions, and guardrail handoffs. It is migrated forward-only.

## V1 target additions

```text
workspaces
workspace_rule_policies
session_outcomes -> evidence_spans
decision_records -> session_outcomes
rule_versions -> decision_records
rule_evaluations -> rule_versions + evidence_spans
rule_verifications -> rule_versions + evidence_spans
rule_projections -> rule_versions
```

| Entity | Purpose | Constraint |
|---|---|---|
| `workspace_rule_policies` | One persisted `approval` or `autonomous` choice per workspace. | Exactly one active policy and auditable change history. |
| `session_outcomes` | Agent-authored summary of its own session. | Bounded structured fields; never raw transcript. |
| `decision_records` | Why a change was made, changed, removed, or fixed. | Cites source outcome and evidence. |
| `rule_versions` | Scoped rule text plus lifecycle state. | Immutable versions; one active version per rule key/scope. |
| `rule_evaluations` | Deterministic activation checks. | Stores threshold inputs and reason. |
| `rule_verifications` | Later support, contradiction, or insufficient data. | Cites later evidence; silence is not stored as support. |
| `rule_projections` | Hash-bound managed `AGENTS.md` projection history. | Records generated/applied content hash and rollback predecessor. |

## Privacy and retention

No table stores GitHub tokens in telemetry, authorization headers, raw sensitive response bodies, or raw chat transcripts. Rule versions and decision provenance are retained for traceability; diagnostic GitHub sync events are bounded to 30 days and 500 records.
