# Backend schema guidance

The live schema is defined by forward-only migrations in `backend/app/store.py`. Do not edit old migrations or claim tables exist before a new migration lands.

## V1 lifecycle enums

```text
rule_policy: approval | autonomous
rule_state: observed | candidate | active | verified | contradicted | retracted | archived
verification_result: supported | contradicted | insufficient_data
sync_health: healthy | partial | unreachable | authentication_failed |
             authorization_failed | rate_limited | malformed_response
```

## V1 key constraints

- One active rule policy per workspace.
- One active rule version per stable rule key and scope.
- Every rule version references a decision record and one or more evidence spans.
- Every autonomous activation records its evaluation, projection hash, prior version, and rollback path.
- Session outcomes are idempotent per agent/session/worktree outcome key.
- GitHub sync events remain bounded; sensitive request/response data is excluded.
