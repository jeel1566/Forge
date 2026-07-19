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

## Implemented rule-loop MCP tools

| Tool | Role |
|---|---|
| `forge_initialize_workspace` | Persists `approval` or `autonomous` rule policy for the workspace. |
| `forge_get_learning_context` | Returns compact active rules, relevant decisions, recent related failures, and capture prompt. |
| `forge_run_validation` | Runs an explicit local command in the registered repository and saves only safe pass/fail metadata; raw output is never stored. |
| `forge_record_session_outcome` | Accepts an agent's structured self-summary, validation citations, idempotency key, and optional Learning Card fields; it evaluates and automatically projects an eligible autonomous rule. |
| `forge_get_rule_proposal` | Returns exact managed `AGENTS.md` diff for approval mode. |
| `forge_approve_rule` | Applies an eligible approval-mode rule after explicit developer approval. |
| `forge_verify_rule` | Records later supporting, contradicting, or insufficient evidence. |
| `forge_get_rule_history` | Returns versioned provenance, state, and verification history. |

All writes return stable IDs, status, timestamps, citations, and a deterministic reason. A Learning Card uses `learning_area`, `learning_trigger`, and `learning_action`, so later outcomes can join the same observed problem despite different rule wording. Rule activation needs two different `local_validation` citations captured by Forge; an agent's written validation claim alone is insufficient. Writes reject secrets, raw transcripts, unsupported evidence references, and unbounded content.

## HTTP API direction

The local API serves repositories, evidence, session handoffs, GitHub status, workspace policy, outcomes, rule lifecycle/history, approval diffs, and managed projection. It stays loopback-only and never becomes a public webhook receiver by default.

## GitHub safety

Polling is disabled by default and reads PRs, reviews, and inline review comments only. Status is compact: health, partial state, cursor, last success, next eligible poll, retry state, rate limits, and safe error kind. Tokens, authorization headers, and raw response bodies are never returned.
