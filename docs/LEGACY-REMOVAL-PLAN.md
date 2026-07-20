# Legacy removal plan

Forge has one canonical learning path: Session Handoffs, evidence spans, configured validation runs, Learning Cards, rule versions, verification inputs, and managed-rule projections. Earlier session-context and guardrail features remain in the database only as historical records. This plan removes superseded behavior without deleting local history or editing old SQLite migrations.

## Removal technique

This follows the production **characterization-test and deprecation** method:

1. Establish a passing baseline and record every public route, MCP tool, dashboard call, store method, test, and persisted table.
2. Separate data retention from active behavior. Forward-only migrations and legacy rows remain; new writes and duplicate workflows are removed.
3. Remove one complete vertical slice at a time: server models, routes, store mutators, UI calls, tests, and docs together.
4. Preserve one compact read-only legacy-history surface until a documented removal release; never silently discard old project data.
5. Run the full backend suite, frontend build, and `git diff --check` after each slice. The branch is merged only after developer approval.

## Compatibility matrix

| Area | Decision | Reason | Migration/data rule |
|---|---|---|---|
| Session Handoffs, evidence, validations, cards, rules, verification, projections | Keep | Canonical Forge learning loop | Active and supported |
| Local Git/GitHub sync, work sessions, incidents/cases, vault, reusable rules | Keep | Current local evidence and retrieval features | Active and supported |
| `session_contexts` writes, reviews, archives, search API, structured-context decision creation | Remove | Replaced by canonical Session Handoffs and vault search | Preserve rows as read-only legacy history |
| Old AGENTS guardrail candidates, handoffs, portable adoptions | Remove | Replaced by Learning Cards and journaled managed-rule projection | Preserve rows as read-only legacy history |
| Reflections | Remove | No current MCP or dashboard workflow; overlaps with a cited handoff | Preserve rows for export/history only |
| Project memory entries and archive-memory route | Remove | Decisions, handoffs, and vault are the canonical retrieval surfaces | Preserve rows for export/history only |
| Active intention panel and API | Remove | It is a standalone dashboard note, not evidence-backed shared context | Preserve the old table; no new writes |
| Durable non-rule decisions | Keep | `forge_record_decision` is explicitly retained for cited non-rule decisions | Remove only the dependency on legacy session contexts |
| `forge_get_legacy_history` | Keep temporarily | Required to read preserved old records without reviving old workflows | Read-only and bounded |

## Removal slices

### Slice 1 — obsolete public behavior

Remove legacy HTTP models and routes for session contexts, old guardrails, reflections, memory archive, and active intentions. Remove the dashboard's active-intention panel. Keep the canonical dashboard and MCP tools unchanged. Add API tests that prove the deleted routes are unavailable and canonical routes still work.

### Slice 2 — obsolete store mutators

Delete store methods that create, review, archive, or adopt legacy session contexts, guardrails, reflections, intentions, and project memory. Retain narrow legacy readers used by `forge_get_legacy_history` and export. Update `history`, `today`, and decision retrieval so they do not depend on legacy context tables.

### Slice 3 — one legacy read model

Make `forge_get_legacy_history` and its HTTP equivalent the only legacy surface. It returns a bounded, explicit `read_only: true` record list for old contexts, guardrails, reflections, intentions, and project memory. It never creates, advances, activates, or projects a rule.

### Slice 4 — tests, docs, and package surface

Delete tests that prove retired behavior; replace them with preservation/read-only tests. Remove retired API/MCP documentation and stale product claims. Regenerate the dashboard build asset and verify no retired names remain outside migration/export/legacy-reader code.

## Safety gates

- Never modify an already-applied SQLite migration or delete a local database table in this branch.
- Never use `git add -A`; unrelated untracked files remain excluded.
- No route is removed until the repository search shows no current frontend or MCP consumer.
- If an external consumer needs a retired API, stop that slice and add an explicit migration note instead of silently breaking it.
- Do not merge this branch into `main` until the developer explicitly asks.
