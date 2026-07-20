# Decisions, verification, and coaching

Forge has no hidden extractor. The agent that did the work writes the handoff, labels uncertainty, and cites local evidence. Forge keeps observation, hypothesis, counterexample, validation, and developer review separate.

## Good handoff prompt

```text
Read relevant persisted Forge context first. Report goal and bounded scope;
observed facts with citations; prior approach; why it failed; alternatives;
chosen fix and rationale; validation result; risk; unresolved work. Propose a
rule only as a narrow condition → action → exception. Label unknowns. Never
send the raw conversation, tokens, raw output, or payloads.
```

## Verification

| Later signal | Forge behavior |
|---|---|
| Applicable trusted configured validation supports a rule | Mark card verified. |
| Applicable trusted configured validation contradicts active rule | Retract rule and roll back managed block. |
| Git change, GitHub review, or local failure | Save cited input; require developer confirmation before applying it. |
| No relevant evidence | Remain neutral (`insufficient_data`). |

## Feedback and reusable rules

Forge records explicit feedback about context usefulness, missing/irrelevant context, and rule assessment as visible cited review data—not model training. A reusable rule remains local and pending until two distinct repositories have evidence-gated active versions; a developer must approve it, and each project can ignore or replace it locally.
