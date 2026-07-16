# API and MCP Specification

## REST surface

| Method | Route | Purpose |
|---|---|---|
| POST | `/v1/webhooks/github` | Receive and validate a GitHub delivery. |
| POST | `/v1/workspaces/:id/imports` | Import manual agent/chat/error evidence. |
| GET | `/v1/workspaces/:id/context` | Return compact cited project context. |
| GET | `/v1/workspaces/:id/decisions` | List/filter decisions. |
| POST | `/v1/decisions/:id/review` | Confirm or reject a decision. |
| GET | `/v1/workspaces/:id/patterns` | List patterns and observations. |
| GET | `/v1/workspaces/:id/coaching/active` | Return the active goal or insufficient-data state. |

## MCP tools

| Tool | Access | Contract |
|---|---|---|
| `forge_get_project_context` | Read | Returns up to 12 relevant, cited confirmed memory items and active coaching. |
| `forge_search_decisions` | Read | Searches decision history with citations and review status. |
| `forge_record_decision` | Pending write | Stores agent evidence plus a pending decision; never updates memory. |
| `forge_get_active_coaching` | Read | Returns one goal or an honest insufficient-data response. |
| `forge_record_observation` | Pending write | Stores error, review, or debugging evidence for later analysis. |

## `forge_record_decision` input

```json
{
  "workspace_id": "uuid",
  "statement": "Defer OAuth until the ingestion demo works.",
  "category": "scope",
  "evidence_quote": "Let's skip OAuth until the core ingestion demo works.",
  "explicitness": "explicit"
}
```

The server creates an `agent_conversation` evidence item, its evidence span, and a pending decision. A browser confirmation is still required for project-memory promotion.
