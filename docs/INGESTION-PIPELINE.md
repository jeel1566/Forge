# Forge learning pipeline

## 1. Start with persisted context

An installed agent starts a local session lease and calls `forge_get_session_start_context`. The compact response contains the persisted decisions, rules, alerts, and latest handoff relevant to continuing work—not a reconstructed chat summary or an overwhelming context dump.

## 2. Work and collect safe evidence

Forge can record local Git facts, configured validation results, optional GitHub review facts, work items, and incidents. GitHub polling is optional and read-only. An agent never uploads its chat transcript.

## 3. Write a Session Handoff

At `/forge_end`, the working agent writes its own structured account: goal, scope, problem, previous approach, why it failed, alternatives, chosen fix, rationale, validation, risk, unresolved work, and optional proposed rule. It cites existing evidence span IDs.

## 4. Gate rule evidence

Only configured validations from the checked-in `forge.validation.json` can move a Learning Card toward activation. The validation must pass, use the current configuration hash, and cover the rule category and all affected scopes. Manual commands, prose, commits, and GitHub findings are useful context but not automatic activation proof.

## 5. Match, alert, and review

Forge normalizes scope, area, trigger, and action. Exact identity reuses a card. Similar identity produces a possible duplicate; same scope/area/trigger with a different action produces a possible conflict. Forge never merges, resolves, or activates either flagged card automatically.

## 6. Activate and project safely

Two independently cited applicable trusted handoffs make a card `ready`. Approval mode shows an exact Forge-managed `AGENTS.md` diff and waits. Autonomous mode can activate a ready unflagged card. Projection uses a durable journal, managed-block hash checks, temporary-file replacement, and startup reconciliation.

## 7. Verify, reuse, or retract

Later trusted validation can verify or contradict a rule. Git changes, GitHub reviews, and local failures are stored as verification inputs and require developer confirmation before they change a rule. Contradiction retracts an active rule and rolls back its managed block. A reusable rule needs two evidence-gated active project rules from different repositories, then explicit approval; local project overrides win.
