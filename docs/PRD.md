# Product requirements

## Outcome

Forge helps a single developer retain engineering rationale and improve one repeated behaviour at a time. Before work, an agent gets compact, cited context. The developer can review every proposed memory item and every coaching claim.

## Scope

GitHub supplies push, pull-request, review, and review-comment events. Agents voluntarily submit explicit decisions or observations through MCP; Forge never scrapes conversations. The data model supports multiple repositories, while the hackathon demo uses one developer and one repository.

| ID | Requirement |
|---|---|
| FR-1 | Receive supported GitHub events idempotently. |
| FR-2 | Preserve immutable evidence and exact quote, line, or diff spans. |
| FR-3 | Extract zero to three cited pending decisions from eligible evidence. |
| FR-4 | Promote a decision to current memory only after explicit confirmation. |
| FR-5 | Check decisions against later relevant evidence without treating silence as proof. |
| FR-6 | Detect fixed, observable patterns from repeated evidence. |
| FR-7 | Map qualifying patterns to a fixed principle catalogue. |
| FR-8 | Maintain at most one active coaching cycle per workspace. |
| FR-9 | Expose cited reads and pending-only writes through MCP. |

## Acceptance metrics

- Every displayed decision, verification result, pattern, and coaching claim has citations.
- No unconfirmed decision appears in current project memory.
- A repeated delivery creates neither duplicate evidence nor duplicate work.
- Demo data produces a reviewable decision and one evidence-backed pattern.
- Weak evidence is shown as `insufficient_data`.

## Out of scope

Multi-user permissions, GitHub App OAuth, passive chat collection, vector search, automatic rules-file edits, and developer scoring are not MVP features.
