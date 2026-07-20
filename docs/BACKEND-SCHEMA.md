# Backend schema guidance

The live schema and all migrations are in `backend/app/store.py`. Migrations are forward-only. Do not edit an applied migration, delete a project table, or make a legacy reader create new learning.

## Important enums

```text
workspace policy: approval | autonomous
learning card: observed | watching | ready | active | verified |
               contradicted | retracted | archived
rule version: candidate | active | retracted
verification result: supported | contradicted | insufficient_data
verification input: configured_validation | git_change | github_review | local_failure
GitHub health: healthy | partial | unreachable | authentication_failed |
               authorization_failed | rate_limited | malformed_response
```

## Constraints enforced by the store

- Handoffs are idempotent by workspace and `outcome_key`.
- Rule-supporting handoffs require structured identity and existing evidence citations.
- Two independent applicable trusted configured-validation-backed observations are required for readiness.
- Pending duplicate/conflict alerts block activation; active cards cannot be merged.
- Only a ready unflagged card may activate; approval policy also needs explicit approval.
- Projection journaling protects the managed `AGENTS.md` block against crashes and manual edits.
- Reusable rules require two distinct evidence-gated source repositories plus developer approval.
