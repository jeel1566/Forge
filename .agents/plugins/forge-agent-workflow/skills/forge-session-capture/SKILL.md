---
name: forge-session-capture
description: Capture multiple completed local Git work units as developer-reviewed Forge handoffs without sending raw transcripts.
---

# Forge Session Capture

At meaningful session start, call `forge_start_work_session`. At meaningful session end, call `forge_finish_work_session` and `forge_get_worktree_delta`, then create one cited pending handoff for each completed work unit with `forge_record_session_contexts`.

Do not send a chat transcript, do not automatically create durable decision memory, and do not write `AGENTS.md`. The developer reviews every handoff in Forge.
