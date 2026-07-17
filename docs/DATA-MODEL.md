# Data model

## Entity map

```text
workspace -> repositories -> ingestion_events -> evidence_items -> evidence_spans
decisions <-> decision_citations -> evidence_spans
verification_runs <-> verification_citations -> evidence_spans
patterns -> pattern_observations -> decisions or evidence_items
coaching_cycles -> metric_snapshots
project_memory_entries -> confirmed decisions
jobs -> ingestion_events or derived-work idempotency keys
```

## Entities

| Entity | Responsibility | Important rule |
|---|---|---|
| `workspaces` / `repositories` | Ownership and external repository identity. | The hackathon uses one workspace; the model remains repository-aware. |
| `ingestion_events` | Immutable record of an accepted external delivery. | Unique provider delivery identity makes replay a no-op. |
| `evidence_items` | Immutable source facts: commits, PRs, reviews, agent observations, or errors. | Raw provider content may live in `raw_payload JSONB`. |
| `evidence_spans` | Exact quote, line range, or diff hunk. | Every displayed derived claim links to one or more spans. |
| `decisions` | Extracted rationale with pending/confirmed/rejected review state. | Pending is the default; confirmation is explicit. |
| `verification_runs` | Dated comparison against later evidence. | Absence of evidence returns `insufficient_data`. |
| `patterns` / `pattern_observations` | Repeated observable behaviour and its cited backing. | A pattern observation references exactly one decision or evidence item. |
| `coaching_cycles` / `metric_snapshots` | One goal, target, follow-up, and measured result. | One active cycle per workspace. |
| `project_memory_entries` | Versioned current projection of confirmed decisions. | One current key per workspace. |
| `jobs` | Durable, retryable background work. | Unique `(type, idempotency_key)` prevents repeated effects. |

## Relationship rules

Use citation join tables (`decision_citations` and `verification_citations`), never arrays of foreign keys. Keep searchable and constrained fields relational even when retaining provider payloads in JSONB. Confirming a decision creates or supersedes a current project-memory projection; it does not mutate evidence or the original decision record.
