---
name: forge
description: Use Forge's local shared project memory at the start and end of a coding session. Retrieve persisted context, then submit a compact self-written evidence-backed session outcome without sending a raw chat transcript.
---

# Forge shared memory

Forge is the shared local notebook for this repository. Codex summarises Codex work; Antigravity summarises Antigravity work. Do not ask one agent to summarise the other and do not read, scrape, or upload a raw chat transcript.

## Session start

1. When the global Forge installation is active, run `forge session-start --path . --agent codex` or `--agent antigravity` and retain the returned `session_id`.
2. Call `forge_get_session_start_context` for the active workspace.
3. Treat returned cited decisions, active rules, alerts, and latest Session Handoff as project context; do not invent missing memory.
4. For meaningful work, call `forge_start_work_session` with the active worktree and heartbeat the retained session around longer work.
5. If Forge is offline, say so briefly and continue normal work without shared context.

## Session end

1. Run `forge_run_configured_validation` for each applicable checked-in validation ID, then call `forge_get_recent_evidence`.
2. Write a concise self-summary: goal, problem, prior approach, why it failed, alternatives, fix, validation, risk, and unresolved work.
3. Submit it with `forge_complete_session` and the retained session ID. A proposed rule requires structured `scope`, `learning_area`, `learning_trigger`, and `learning_action`.
4. Report persisted alerts, then run `forge session-end --path . --session-id <session_id>`.
5. Use `forge_record_decision` only for a reusable non-rule decision.

Only configured validation results can move a Learning Card forward. Arbitrary `forge_run_validation` results are untrusted manual context. Use `forge_list_learning_cards`, `forge_get_learning_card`, and `forge_get_learning_alerts` for persisted facts. Two separately cited, applicable configured validations make a card ready. In autonomous mode Forge projects only its managed `AGENTS.md` block; in approval mode call `forge_get_rule_proposal`, show the exact diff, and call `forge_approve_rule` only after an explicit yes.

## Rule safety

Never auto-merge, resolve conflicts, create context files, expose secrets, or treat a chat claim as evidence. Present duplicate/conflict alerts to the developer and call `forge_review_learning_alert` only after their decision. When later configured validation evidence contradicts an active rule, call `forge_verify_rule`; Forge retracts it and rolls back only its managed rule block.

Later Git changes, GitHub review findings, and bounded local failures may be recorded with `forge_record_verification_input` or `forge_record_local_failure`. Cite the persisted local evidence, present non-validation findings to the developer, and call `forge_confirm_verification_input` only after an explicit confirmation. They never activate a Learning Card.

## Current vertical slice

Workspace policy, Learning Cards, Forge-recorded validation evidence, the two-outcome gate, approval/autonomous projection, and contradiction rollback are available. Advanced repetition analysis and richer rule review screens remain future work.
