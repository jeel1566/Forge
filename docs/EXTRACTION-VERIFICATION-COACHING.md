# Extraction, Verification, and Coaching Pipeline

## The Forge feedback loop

```text
Evidence
  -> Git commits, PR reviews, AI conversations, errors
  -> Pattern detection
  -> Repeated large commits, AI-first debugging, repeated review comments
  -> Engineering principle
  -> Incremental development, hypothesis-driven debugging, root cause analysis
  -> Intervention
  -> One recommendation, one measurable goal, check next week
```

This is Forge's central technique. The stages have different responsibilities and cannot be collapsed into one unconstrained LLM call.

## Extraction

The extractor receives source spans and returns zero to three pending decisions. It must cite every claim, avoid unstated rationale, assign low confidence to inference, and return no decision for mere brainstorming.

## Verification

The verifier receives a decision plus later relevant evidence. It returns `consistent`, `contradicted`, or `insufficient_data`. Silence never counts as consistent. Coaching goals are evaluated deterministically from their metrics as `met`, `missed`, or `insufficient_data`.

## Pattern scoring

Initial patterns are fixed and measurable:

- `large_commits`: three or more commits above a configured changed-lines threshold.
- `repeated_review_theme`: the same classified review theme across three PRs.
- `unverified_hotfixes`: two or more error/fix/revert or reopened-change sequences.

A pattern is coachable only with at least three observations, sufficient citations, recent evidence, and an outcome/review-cost signal. Its priority is frequency × impact × confidence × recency.

## Principle mapping and intervention

| Pattern | Principle | Initial intervention | Example measurable goal |
|---|---|---|---|
| Large commits | Incremental development | Split work into reviewable commits. | Reduce median changed lines per commit below 250. |
| Repeated review theme | Feedback-driven development | Add a pre-PR check for the repeated issue. | Reduce matching review comments by 50%. |
| Unverified hotfixes | Hypothesis-driven debugging | Record a hypothesis and verification before editing. | Increase fixes with a linked test/reproduction to 80%. |

After two missed cycles, Forge escalates the pattern for developer review instead of repeating the same recommendation.
