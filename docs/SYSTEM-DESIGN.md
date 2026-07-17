# System design

## Lifecycle

```text
input -> ingestion event + job -> immutable evidence + spans -> pending decision
      -> developer confirms/rejects -> current-memory projection
      -> later-evidence verification -> qualifying pattern -> one coaching cycle
```

Each arrow is an explicit state transition, not an unconstrained model action. Evidence stays immutable; interpretations are versioned; the current-memory table is only a projection of confirmed decisions.

## State rules

| State | Created by | Exit condition |
|---|---|---|
| `ingestion_event` | API after validation | A worker normalizes it exactly once. |
| `evidence_item` | Worker | Immutable after creation; supports multiple spans. |
| Pending decision | Extractor or MCP pending write | Developer confirms or rejects it. |
| Current memory entry | Review action | Superseded by another confirmed decision for its key. |
| Verification run | Scheduled/later-evidence job | Returns a cited result or `insufficient_data`. |
| Coaching cycle | Deterministic pattern selection | Becomes met, missed, dismissed, or escalated. |

## Invariants

1. A decision has at least one exact evidence span.
2. Only an explicit, confirmed decision creates current memory.
3. Missing later evidence produces `insufficient_data`; silence is never confirmation.
4. A coachable pattern needs three independent observations, citations, recent evidence, and a measurable outcome or review-cost signal.
5. One workspace has at most one active coaching cycle; two misses escalate for developer review.

## Failure and recovery

Invalid GitHub signatures are rejected. Duplicate deliveries are accepted but become no-ops through unique keys. Invalid model output records a failed attempt and retries with backoff; after the third failure, the job becomes a visible dead letter and writes no partial derived state. Operators can retry a dead-letter job after fixing configuration or provider availability because every step is idempotent.
