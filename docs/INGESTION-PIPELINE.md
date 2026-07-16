# Ingestion Pipeline

## Sources

| Source | Capture mechanism | Trust note |
|---|---|---|
| Git commits | GitHub `push` webhook plus GitHub API fetch | Passive and durable. |
| PRs/reviews | PR, review, and review-comment webhooks | Review feedback is high-value labelled evidence. |
| Agent conversations | MCP `forge_record_decision` or `forge_record_observation` | Voluntary submission only; no chat scraping. |
| Errors | MCP/manual import | Evidence, not an automatic behavioural judgment. |

## Webhook sequence

1. Read the raw request body and verify GitHub HMAC signature.
2. Deduplicate on GitHub delivery ID.
3. Insert `ingestion_events` and a `normalize_evidence` job transactionally.
4. Return `202 Accepted`.
5. Worker fetches missing commit/PR/review details and creates evidence items/spans.
6. Worker queues extraction, verification, or pattern aggregation as relevant.

## Idempotency

Every downstream job uses a stable key, such as `github:{delivery_id}` or `evidence:{id}:extractor-v1`. Replaying a delivery must not produce duplicate decisions, patterns, or coaching cycles.
