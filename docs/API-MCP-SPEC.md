# API and MCP contract

## Contract status

The tools listed as **current** exist in the local implementation. The **v1 target** tools describe the new Forge learning loop and must be implemented before agents are instructed to call them.

## Current MCP tools

| Tool | Purpose |
|---|---|
| `forge_get_project_context` | Reads confirmed decisions, approved handoffs, and active intention. |
| `forge_get_session_capture_guidance` | Returns transcript-free end-of-session guidance. |
| `forge_get_recent_evidence` | Lists existing local evidence spans for citations. |
| `forge_start_work_session` / `forge_finish_work_session` | Records Git work boundaries only. |
| `forge_get_worktree_delta` / `forge_get_coordination_status` | Returns local Git facts and exact overlap warnings. |
| `forge_record_session_context(s)` | Saves cited agent-supplied handoffs. |
| `forge_record_decision` / `forge_record_reflection` | Saves a pending cited proposal or reflection. |
| `forge_get_github_sync_status` | Returns safe persisted GitHub sync health and telemetry. |

Current MCP never reads a transcript, returns secrets, or silently promotes a record to memory.

## V1 target MCP tools

| Tool | Role |
|---|---|
| `forge_initialize_workspace` | Creates workspace metadata and asks once for `approval` or `autonomous` rule policy. |
| `forge_get_learning_context` | Returns compact active rules, relevant decisions, recent related failures, and capture prompt. |
| `forge_record_session_outcome` | Accepts an agent's structured self-summary with citations and idempotency key. |
| `forge_evaluate_rule_candidate` | Returns deterministic evidence/scope/duplicate evaluation. |
| `forge_get_rule_proposal` | Returns exact managed `AGENTS.md` diff for approval mode. |
| `forge_apply_rule_projection` | Applies only the managed rule block after policy gate and content-hash verification. |
| `forge_verify_rule` | Records later supporting, contradicting, or insufficient evidence. |
| `forge_get_rule_history` | Returns versioned provenance, state, rollback, and review time. |

All writes return stable IDs, status, timestamps, citations, and a deterministic reason. They reject secrets, raw transcripts, unsupported evidence references, and unbounded content.

## HTTP API direction

The local API continues to serve repositories, evidence, session handoffs, GitHub status, and dashboard state. V1 adds workspace policy, rule lifecycle/history, candidate evaluation, and managed-projection endpoints. The API stays loopback-only and never becomes a public webhook receiver by default.

## GitHub safety

Polling is disabled by default and reads PRs, reviews, and inline review comments only. Status is compact: health, partial state, cursor, last success, next eligible poll, retry state, rate limits, and safe error kind. Tokens, authorization headers, and raw response bodies are never returned.
