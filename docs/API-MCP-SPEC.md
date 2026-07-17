# API and MCP contract

## HTTP API

| Method | Route | Result |
|---|---|---|
| POST | `/v1/webhooks/github` | Validates HMAC, records an idempotent delivery and durable job, returns `202`. |
| POST | `/v1/workspaces/:id/imports` | Records manual or agent evidence. |
| GET | `/v1/workspaces/:id/context` | Returns compact, cited confirmed memory and active coaching. |
| GET | `/v1/workspaces/:id/decisions` | Lists decisions with status and citations. |
| POST | `/v1/decisions/:id/review` | Confirms or rejects a pending decision. |
| GET | `/v1/workspaces/:id/patterns` | Lists cited patterns and observations. |
| GET | `/v1/workspaces/:id/coaching/active` | Returns the single goal or `insufficient_data`. |

## MCP tools

| Tool | Access | Guarantee |
|---|---|---|
| `forge_get_project_context` | Read | At most 12 relevant, cited confirmed items plus active coaching. |
| `forge_search_decisions` | Read | Searchable decision history with citations and status. |
| `forge_record_decision` | Pending write | Creates evidence, span, and a pending decision only. |
| `forge_get_active_coaching` | Read | One goal or an honest insufficient-data response. |
| `forge_record_observation` | Pending write | Stores cited error, review, or debugging evidence for later analysis. |

`forge_record_decision` accepts `workspace_id`, `statement`, `category`, `evidence_quote`, and `explicitness`. The server records an `agent_conversation` evidence item and span; browser review remains required for promotion.
