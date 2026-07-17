---
name: forge
description: Use Forge's local MCP memory when starting or ending a coding session in a Forge-enabled repository. Retrieve cited confirmed context, optionally propose one evidence-backed pending decision or reflection, and handle developer-approved AGENTS.md guardrails without reading chat transcripts.
---

# Forge Memory

Use Forge as a local, developer-reviewed memory layer. Treat it as optional: if Forge is offline, say so and continue normal coding work without inventing context.

## Session start

1. Call `forge_get_project_context` for the active repository workspace.
2. Use only returned confirmed memory and citations as Forge context.
3. Do not infer memory from a prior chat, scrape transcripts, or treat pending decisions as memory.

## Session end

When a developer has expressed a reusable decision or reflection and there is a short, concrete supporting quote, voluntarily call exactly one of:

- `forge_record_decision` for a candidate engineering guardrail or decision.
- `forge_record_reflection` for a reviewed observation that should not become memory.

Supply only the explicit statement and supporting quote. Explain that the item is pending developer review. Do not create a draft when the evidence is weak or absent.

## Guardrails

1. Call `forge_get_agents_guardrail_candidates` only for repeated confirmed patterns.
2. Read `AGENTS.md` through normal repository access, then call `forge_propose_agents_guardrail` with its current content.
3. Show the exact returned diff in chat and wait for an explicit developer yes.
4. Only then edit `AGENTS.md` and call `forge_record_agents_guardrail_approval`.

Never let Forge write `AGENTS.md`, confirm memory, read raw chats, score a developer, or automate their decisions.
