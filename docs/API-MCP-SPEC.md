# API and MCP contract

## Contract status

The tools listed as **current** exist in the local implementation. The **v1 target** tools describe the new Forge learning loop and must be implemented before agents are instructed to call them.

## Canonical MCP tools

| Tool | Purpose |
|---|---|
| `forge_get_session_start_context` | Reads active rules, alerts, cited decisions, and the latest handoff. |
| `forge_get_latest_session_handoff` / `forge_get_session_handoff` | Reads persisted cited handoffs only. |
| `forge_get_recent_evidence` | Lists existing local evidence spans for citations. |
| `forge_start_work_session` / `forge_finish_work_session` | Records Git work boundaries only. |
| `forge_get_worktree_delta` / `forge_get_coordination_status` | Returns local Git facts and exact overlap warnings. |
| `forge_record_session_handoff` | Saves one canonical cited agent-supplied handoff without ending a runtime lease. |
| `forge_heartbeat_session` | Refreshes one active session-ID lease without storing chat content. |
| `forge_start_dashboard` | Starts or reuses the loopback dashboard under the persistent Forge MCP process and returns its local URL. |
| `forge_complete_session` | Saves the handoff, marks its exact session-ID lease complete, and returns persisted alerts before `forge session-end`. |
| `forge_record_decision` / `forge_record_reflection` | Saves a pending cited proposal or reflection. |
| `forge_get_github_sync_status` | Returns safe persisted GitHub sync health and telemetry. |

Current MCP never reads a transcript, returns secrets, or silently promotes a record to memory.

## ChatGPT HTTP MCP transport

`forge mcp-http --path . --port 8765` starts a separate Streamable HTTP endpoint at `http://127.0.0.1:8765/mcp`. It binds to loopback only and requires an existing initialized Forge database. It is intentionally read-only: it offers only compact persisted context, handoffs, work/learning history, safe evidence metadata, rules, alerts, vault search, coordination, and GitHub sync status. It excludes every write, validation execution, approval, and projection tool.

ChatGPT connects through OpenAI Secure MCP Tunnel; Forge does not open a public listener or implement its own tunnel. The tunnel provider and ChatGPT Developer Mode control authentication and app authorization. Forge's transport remains safe when GitHub is offline and never returns tokens, transcripts, headers, raw command output, or raw GitHub response bodies.

## Learning-card MCP tools

| Tool | Role |
|---|---|
| `forge_initialize_workspace` | Persists `approval` or `autonomous` rule policy for the workspace. |
| `forge_list_learning_cards` / `forge_get_learning_card` | Returns card state, observations, rules, and alerts. |
| `forge_run_validation` | Runs an explicit manual command; it is always untrusted context. |
| `forge_run_configured_validation` | Runs an approved validation ID; only these results can support a card. |
| `forge_record_session_handoff` | Accepts the structured self-summary and optional Learning Card observation. |
| `forge_complete_session` | Required by the installed `/forge_end` skill before normal lease release. |
| `forge_get_rule_proposal` | Returns exact managed `AGENTS.md` diff for approval mode. |
| `forge_approve_rule` | Applies an eligible approval-mode rule after explicit developer approval. |
| `forge_verify_rule` | Records later supporting, contradicting, or insufficient evidence. |
| `forge_record_verification_input` | Saves cited later Git, GitHub review, local-failure, or configured-validation verification evidence. Non-validation evidence stays pending until developer confirmation. |
| `forge_record_local_failure` / `forge_confirm_verification_input` | Saves a bounded local failure without raw output, then applies a pending finding only after developer confirmation. |
| `forge_get_rule_history` / `forge_get_legacy_history` | Returns current provenance or read-only preserved history. |

All writes return stable IDs, status, timestamps, citations, and a deterministic reason. A Learning Card uses normalized `scope`, `learning_area`, `learning_trigger`, and `learning_action`, so later handoffs join the same observed problem despite different wording. Rule activation needs two different, applicable configured validation citations. Writes reject secrets, raw transcripts, unsupported evidence references, and unbounded content.

`forge session-end --session-id <session_id>` rejects an active lease that has not been marked by `forge_complete_session`. A developer can explicitly abandon a session using one fixed reason (`validation_unavailable`, `handoff_incomplete`, `developer_cancelled`, or `agent_error`); Forge records that safe event without chat content. Runtime health includes a random instance ID, so Forge never stops a process whose identity no longer matches the project metadata.

Configured validations remain the only automatic Learning Card activation evidence. Later Git changes, GitHub reviews, and structured local failures are cited verification inputs: Forge records them, but applies support or contradiction only after explicit developer confirmation. An `insufficient_data` input remains neutral.

## HTTP API direction

The local API serves repositories, evidence, session handoffs, GitHub status, workspace policy, outcomes, rule lifecycle/history, approval diffs, and managed projection. It stays loopback-only and never becomes a public webhook receiver by default.

## GitHub safety

Polling is disabled by default and reads PRs, reviews, and inline review comments only. Status is compact: health, partial state, cursor, last success, next eligible poll, retry state, rate limits, and safe error kind. Tokens, authorization headers, and raw response bodies are never returned.
