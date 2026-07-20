# API and MCP reference

Forge has two local transports:

- **stdio MCP** (`forge-mcp`) for Codex and Antigravity. It includes the explicit, developer-reviewed write workflow.
- **loopback HTTP MCP** (`forge mcp-http`) for optional ChatGPT use. It is read-only and serves `http://127.0.0.1:<port>/mcp`.

The dashboard uses the loopback FastAPI endpoints under `/v1` and never exposes secrets or raw payloads.

## Session and memory tools

| Tool | Purpose |
|---|---|
| `forge_initialize_workspace` | Set `approval` or `autonomous` policy once for a workspace. |
| `forge_get_session_start_context` | Read active/project-reusable rules, alerts, decisions, and latest handoff. |
| `forge_get_latest_session_handoff`, `forge_get_session_handoff` | Read persisted handoffs. |
| `forge_record_session_handoff` | Save one structured, cited handoff; idempotent by outcome key. |
| `forge_complete_session` | Save a handoff and mark the exact runtime lease ready for release. |
| `forge_heartbeat_session` | Refresh a lease during long work. |
| `forge_record_session_feedback` | Save explicit usefulness/relevance/rule feedback. |
| `forge_search_vault`, `forge_export_vault` | Search persisted project facts or create a deterministic local vault export. |

## Work and evidence tools

| Tool | Purpose |
|---|---|
| `forge_start_work_item`, `forge_finish_work_item`, `forge_list_work_items`, `forge_get_work_item` | Track bounded work with cited evidence. |
| `forge_capture_incident`, `forge_list_incidents` | Record facts, hypotheses, counterexamples, and next actions separately. |
| `forge_list_learning_cases`, `forge_get_learning_case` | Read grouped repeated observations. |
| `forge_get_recent_evidence` | List existing safe evidence spans for citations. |
| `forge_run_configured_validation` | Run one checked-in trusted validation ID. |
| `forge_run_validation` | Run one manual/untrusted validation command; never activation proof. |
| `forge_record_decision`, `forge_retrieve_decisions` | Persist and retrieve durable non-rule decisions. |

## Learning and rule tools

| Tool | Purpose |
|---|---|
| `forge_list_learning_cards`, `forge_get_learning_card` | Read card identity, observations, rules, and lifecycle state. |
| `forge_get_learning_alerts`, `forge_review_learning_alert` | Read and developer-review duplicate/conflict/projection/review alerts. |
| `forge_get_rule_history`, `forge_get_rule_proposal`, `forge_approve_rule` | Inspect rules, view approval diff, and approve an eligible approval-mode rule. |
| `forge_verify_rule` | Apply trusted configured-validation support, contradiction, or insufficient data. |
| `forge_record_verification_input`, `forge_record_local_failure`, `forge_confirm_verification_input` | Capture later Git/GitHub/local-failure inputs; non-validation findings require developer confirmation before changing a rule. |
| `forge_request_reusable_rule`, `forge_list_reusable_rules`, `forge_list_reusable_rule_requests`, `forge_approve_reusable_rule`, `forge_override_reusable_rule` | Promote a rule across two local repositories only after explicit approval; apply project override. |
| `forge_get_legacy_history` | Read bounded preserved legacy rows. It cannot create or activate learning. |

## Runtime and GitHub tools

| Tool | Purpose |
|---|---|
| `forge_start_dashboard` | Start/reuse an MCP-owned loopback dashboard. |
| `forge_start_work_session`, `forge_get_worktree_delta`, `forge_get_coordination_status` | Read local multi-worktree coordination facts. |
| `forge_get_github_sync_status` | Read safe connector health, rate-limit, retry, cursor, and partial-sync metadata. |

## HTTP API groups

| Group | Endpoints |
|---|---|
| Health/repository | `/health`, `/v1/repositories`, `/v1/workspaces/{id}/repository` |
| Handoffs/evidence/decisions | `/v1/workspaces/{id}/handoffs`, `/v1/evidence/{id}`, `/v1/workspaces/{id}/evidence`, `/v1/workspaces/{id}/decisions` |
| Learning/rules | `/v1/workspaces/{id}/learning-cards`, `/learning-alerts`, `/rules`, `/projection-status`, reusable-rule routes |
| GitHub | `/v1/connectors/github`, `/v1/workspaces/{id}/github/status`, `/github/poll` |
| Coordination | `/v1/workspaces/{id}/coordination`, `/v1/workspaces/{id}/repository` |

Use the local dashboard/API for configuration; do not treat it as a public internet API.

## Trust and privacy contract

- All writes return persisted IDs, state, timestamps, citations, and deterministic reasons.
- Raw transcripts, secrets, tokens, authorization headers, raw command output, and raw GitHub response bodies are rejected or excluded.
- ChatGPT HTTP exposes only these read operations: context, handoffs, work/learning history, vault search, cards, rule history, reusable rules, evidence metadata, decisions, coordination, alerts, and GitHub status.
- GitHub polling is read-only, disabled by default, bounded, idempotent, and safe when offline.
