# Structured templates

## Session outcome

An agent submits this from its own session, never as a raw transcript:

| Field | Meaning |
|---|---|
| `scope` | Files, module, or bounded task affected. |
| `goal` | What the session attempted. |
| `problem` | Error, failure, or decision point with citation. |
| `prior_approach` | What existed before. |
| `why_prior_approach_failed` | Concrete limitation, error, or trade-off. |
| `alternatives` | Options considered and rejected. |
| `chosen_fix` / `why` | What changed and why that option won. |
| `validation` | Command/result or explicit `not_run`. |
| `risk` / `unresolved` | Remaining uncertainty. |
| `proposed_rule` | Condition → action → exception, or `none`. |

## Rule record

A rule has a stable key, exact scope, version, policy mode, state, citations, activation evaluation, review/expiry time, projection hash, and rollback predecessor. It is never a free-form permanent instruction without provenance.
