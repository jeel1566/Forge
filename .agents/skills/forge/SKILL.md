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

Current Forge writes are review-first. Do not claim that a pending handoff or decision is active memory.

## Rule safety

The current implementation requires a developer-approved `AGENTS.md` handoff. Do not write `AGENTS.md` until the exact proposed diff has been shown and approved. Never auto-merge, resolve conflicts, expose secrets, or treat a chat claim as evidence.

## V1 target

The documented new Forge design adds workspace-level `approval` and `autonomous` rule policies, deterministic evidence gates, managed rule projection, verification, and rollback. Do not call target-only tools or assume automatic rule writing until they exist in the installed MCP server.
