# Backend Schema

## Required enums

```text
source_type: github_commit | github_pull_request | github_review |
             agent_conversation | error_log | manual_import
decision_category: scope | architecture | tooling | process | debugging
review_status: pending | confirmed | rejected
pattern_classification: positive | needs_attention | insufficient_data
coaching_status: active | met | missed | escalated | dismissed
verification_kind: decision | coaching_goal
verification_result: consistent | contradicted | met | missed | insufficient_data
job_status: queued | running | completed | failed | dead_letter
```

## Tables and key constraints

| Table | Primary constraint/index |
|---|---|
| `repositories` | Unique provider and external repository ID. |
| `ingestion_events` | Unique provider and external delivery ID. |
| `evidence_items` | Unique source type and external ID. |
| `decision_citations` | Decision, span, and citation role composite key. |
| `pattern_observations` | Exactly one backing decision or evidence item. |
| `project_memory_entries` | Partial unique index on current workspace/key pair. |
| `coaching_cycles` | Partial unique index for one active workspace cycle. |
| `jobs` | Unique job type and idempotency key. |

## Indexes

```text
evidence_items(workspace_id, occurred_at desc)
evidence_items(repository_id, occurred_at desc)
decisions(workspace_id, created_at desc)
decisions(workspace_id, review_status) WHERE review_status = 'pending'
patterns(workspace_id, classification, last_seen_at desc)
coaching_cycles(check_at) WHERE status = 'active'
jobs(status, run_after, created_at) WHERE status = 'queued'
```

No vector index is included in the MVP. Add one only when measured context retrieval requires semantic recall beyond cited relational records.
