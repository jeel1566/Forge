# Data Model

## Entity map

```text
workspace -> repositories -> ingestion_events -> evidence_items -> evidence_spans
decisions <-> decision_citations -> evidence_spans
patterns -> pattern_observations -> decisions or evidence_items
coaching_cycles -> metric_snapshots
verification_runs <-> verification_citations -> evidence_spans
project_memory_entries -> confirmed decisions
```

## Entity responsibilities

| Entity | Purpose |
|---|---|
| `evidence_items` | Immutable source facts: commit, PR, review, agent observation, or error log. |
| `evidence_spans` | Exact quote, line range, or diff hunk supporting an interpretation. |
| `decisions` | Extracted engineering rationale with status and confidence. |
| `verification_runs` | A dated check of a decision or coaching goal against later evidence. |
| `patterns` | Repeated observable behaviour; never an unsupported personality trait. |
| `coaching_cycles` | One recommendation, one metric, one target, one follow-up date. |
| `project_memory_entries` | Versioned current-state projections from confirmed decisions. |

## Data rules

- Raw source payload goes in `raw_payload JSONB`; searchable core columns stay relational.
- Citations use join tables, not arrays of IDs.
- `project_memory_entries` allows only one current row for a workspace/key pair.
- `coaching_cycles` allows only one active row per workspace.
