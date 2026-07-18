# Seven-stage Forge learning pipeline

## 1. Collect

Forge collects local Git facts, optional GitHub PR/review facts, and a voluntary structured summary from the agent that just completed work. Codex summarises Codex; Antigravity summarises Antigravity. Neither is asked to summarise the other agent's private conversation.

## 2. Cite evidence

The agent cites existing commits, changed paths, tests, errors, PRs, reviews, or review comments. Forge records immutable evidence references rather than raw transcripts or complete API payloads.

## 3. Record the decision

The summary must state: what changed, why, prior approach, why it was wrong or removed, alternatives considered, chosen fix, verification, and unresolved risk. Unknown fields are explicitly `unknown` or `not_run`.

## 4. Evaluate a learning candidate

Forge de-duplicates the candidate and verifies that it has a narrow scope and adequate evidence. Weak records remain observations; they cannot become an active instruction.

## 5. Verify later evidence

Later work can support, contradict, or leave the candidate/rule as `insufficient_data`. Tests, reviews, reverts, recurring errors, and Git history are preferred verification signals.

## 6. Detect repetition

Repeated independently cited observations in the same scope can raise confidence. The baseline target is two separate same-category observations before presenting or autonomously activating a reusable rule; individual high-risk rule classes may require approval regardless of mode.

## 7. Publish, review, or roll back

Forge projects active rules into the managed section of `AGENTS.md`:

- **Approval mode:** shows a precise diff and waits for approval.
- **Autonomous mode:** applies only an evidence-gated rule version and records the prior version for rollback.

The next agent retrieves the active rule and decision context through MCP. A contradicted rule is retracted and excluded from active context.
