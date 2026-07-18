# Decision, verification, and rule evolution

Forge does not use a hidden extractor. The working agent produces a structured reflection from its own session, then Forge applies deterministic validation and lifecycle rules.

## Structured reflection prompt

```text
Retrieve relevant active rules and similar past failures.
Report: goal/scope; observed failure with evidence; prior approach; root cause;
options rejected; chosen fix and why; verification command/result; unresolved risk;
and a proposed rule in condition → required action → exception form.
```

The prompt is research-oriented: retrieve local context first, distinguish observation from inference, cite proof, and label unknown facts instead of inventing them.

## Rule evolution

| Signal | Effect |
|---|---|
| One cited failure/fix | Observation or candidate only. |
| Repeated independently cited category | Candidate may become eligible for activation. |
| Passing verification after applying a rule | Supporting evidence, not permanent proof. |
| Revert, failing test, or contradicted review | Mark rule contradicted and require rollback/review. |
| No relevant later evidence | `insufficient_data`; no confidence increase. |

Autonomous mode uses this same evidence gate; it does not trust a model's confidence score by itself.
