# System Design

## Lifecycle

```text
GitHub or MCP input
  -> ingestion event
  -> immutable evidence item and evidence spans
  -> extraction or normalization job
  -> pending decision
  -> developer confirm/reject
  -> current project-memory projection
  -> later evidence verification
  -> pattern aggregation
  -> one coaching cycle
  -> metric follow-up and escalation if needed
```

## Core invariants

1. A decision has at least one cited evidence span.
2. Only a confirmed, sufficiently explicit decision can create current project memory.
3. Verification uses later evidence and returns `insufficient_data` when no conclusion is justified.
4. A pattern requires at least three independent observations and a measurable outcome/review-cost signal.
5. A workspace has at most one active coaching cycle.
6. Two missed attempts on the same pattern escalate instead of repeating the same advice.

## Failure handling

Invalid webhook signatures are rejected. Duplicate deliveries are accepted but ignored after deduplication. Invalid model JSON fails the job and retries. A third failure creates a dead-letter job and dashboard alert; it never writes partial derived state.
