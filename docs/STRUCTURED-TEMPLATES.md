# Structured handoff and validation reference

## Session Handoff

The agent writes this from its own completed work. Required fields are `agent`, `worktree_path`, `branch`, `outcome_key`, `scope`, `category`, `goal`, `problem`, `prior_approach`, `why_prior_approach_failed`, `alternatives`, `chosen_fix`, `rationale`, `validation`, `risk`, `unresolved`, `proposed_rule`, and `evidence_span_ids`.

| Field | Requirement |
|---|---|
| `outcome_key` | Stable unique key for idempotent retry. |
| `scope` | Non-empty bounded files/modules/repository scope. |
| `alternatives` | Array of `{option, reason}` entries; use `[]` when none. |
| `validation` | Safe summary, not raw output. |
| `evidence_span_ids` | Existing persisted evidence references. |
| `proposed_rule` | A rule statement or `none`. |
| Learning fields | Supply `learning_area`, `learning_trigger`, and `learning_action` together when proposing a rule. |

Use `unresolved`, not `unresolved_work`.

## `forge.validation.json`

```json
{
  "validations": [
    {
      "id": "diff-check",
      "argv": ["git", "diff", "--check"],
      "scopes": ["repository"],
      "categories": ["testing"],
      "timeout_seconds": 120
    }
  ]
}
```

Forge runs `argv` directly without a shell. A configured run is trusted only when it passes and its current config hash, scope, and category apply to the handoff. `forge_run_validation` accepts an arbitrary command only as untrusted/manual context.

## Rule statement

Keep a proposed rule narrow and observable: condition → required action → exception. It must not request transcript capture, secret disclosure, auto-merge, conflict resolution, GitHub writes, or unrelated file edits.
