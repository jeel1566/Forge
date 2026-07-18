# Product requirements

## Outcome

Forge gives coding agents one durable, local project memory. Codex and Antigravity summarise their own work at the end of a session; Forge preserves the reasoning, failure, fix, and evidence so the next agent can continue without repeating mistakes.

## Product loop

```text
agent retrieves scoped context
→ agent works
→ agent self-summarises decisions and failures
→ Forge cites and evaluates the record
→ a rule is approved or autonomously activated
→ later work verifies, strengthens, or rolls back the rule
```

## Functional requirements

| ID | Requirement |
|---|---|
| FR-1 | Persist one rule policy per workspace: `approval` or `autonomous`; ask once during initialization. |
| FR-2 | Let Codex and Antigravity retrieve compact, scoped context and submit their own structured session summary through MCP. |
| FR-3 | Persist decisions: problem, prior approach, why it failed, options considered, chosen fix, reason, validation, and unresolved risk. |
| FR-4 | Link every learning to local evidence; never treat raw chat or unsupported claims as proof. |
| FR-5 | Maintain versioned rule states: observed, candidate, active, verified, contradicted, retracted, and archived. |
| FR-6 | In approval mode, require an exact visible rule diff before activation. |
| FR-7 | In autonomous mode, activate only evidence-gated scoped rules with a version, expiry/review point, and rollback path. |
| FR-8 | Verify rules against later test, build, review, error, revert, and Git evidence; silence is `insufficient_data`. |
| FR-9 | Detect repeated independently cited failure patterns before increasing a rule's confidence. |
| FR-10 | Keep GitHub polling optional, local, restart-safe, bounded, idempotent, and non-blocking for all local Forge features. |
| FR-11 | Show policy mode, health, evidence, active rules, partial-sync warnings, and recovery guidance in the dashboard. |

## Non-goals

- Reading or uploading raw Codex, Antigravity, or ChatGPT transcripts.
- Treating model output as self-validating evidence.
- Auto-merging, conflict resolution, GitHub write operations, or modifying unrelated files.
- Cloud storage, background services, vector databases, or mandatory model APIs.
- Claiming that every future mistake can be prevented; Forge reduces repeated, evidenced mistakes.

## Acceptance criteria

- Two agents using the same workspace retrieve the same persisted active rules and cited decisions.
- A failed test or review finding can be linked to a structured self-summary without importing the chat.
- Re-running an import or session submission does not create duplicate evidence, decisions, or rule versions.
- Autonomous activation cannot occur without the defined evidence threshold and rollback metadata.
- A contradicted active rule is visible, traceable, and no longer served as active context.
