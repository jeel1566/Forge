---
name: forge
description: Use Forge's local shared project memory at the start and end of a coding session. Retrieve persisted context, then submit a compact self-written evidence-backed session outcome without sending a raw chat transcript.
---

# Forge shared memory

Forge is the shared local notebook for this repository. Codex summarises Codex work; Antigravity summarises Antigravity work. Do not ask one agent to summarise the other and do not read, scrape, or upload a raw chat transcript.

## Session start

1. Call `forge_get_project_context` for the active workspace.
2. Treat returned cited decisions and approved handoffs as project context; do not invent missing memory.
3. For meaningful work, call `forge_start_work_session` with the active worktree.
4. If Forge is offline, say so briefly and continue normal work without shared context.

## Session end: current tools

1. Call `forge_finish_work_session`, `forge_get_worktree_delta`, `forge_get_session_capture_guidance`, and `forge_get_recent_evidence`.
2. Write a concise self-summary: goal, what changed, why, prior approach, failure/problem, fix, alternatives rejected, validation, and unresolved risk.
3. Split unrelated completed changes into separate cited handoffs and submit them with `forge_record_session_contexts`.
4. Use `forge_record_decision` only for a reusable evidence-backed decision; use `forge_record_reflection` for a non-durable observation.

For the new rule loop, call `forge_get_learning_context` first. At session end, call `forge_run_validation` for the real test/build command, then use its returned span with `forge_record_session_outcome`. Submit a Learning Card (`learning_area`, `learning_trigger`, and `learning_action`) or reuse a pending `learning_card_id`; do not rely on matching sentence wording. Two independently cited Forge-recorded validation results make a scoped rule eligible. In autonomous mode, Forge updates only its managed `AGENTS.md` block; in approval mode, call `forge_get_rule_proposal`, show the exact diff, and only then call `forge_approve_rule` after an explicit yes.

## Rule safety

Never auto-merge, resolve conflicts, expose secrets, or treat a chat claim as evidence. When later evidence contradicts an active rule, call `forge_verify_rule`; Forge retracts it and rolls back only its managed rule block.

## Current vertical slice

Workspace policy, Learning Cards, Forge-recorded validation evidence, the two-outcome gate, approval/autonomous projection, and contradiction rollback are available. Advanced repetition analysis and richer rule review screens remain future work.
