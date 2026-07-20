# Data model and retention

Forge uses forward-only SQLite migrations. Existing legacy rows are preserved for read-only history; new learning writes use the canonical records below.

## Storage locations

| Location | Content |
|---|---|
| `<repository>/.forge/forge.sqlite3` | Project repository, evidence, handoffs, validations, cards, rules, polling, work items, feedback, and projection history. |
| `~/.forge/reusable-rules.sqlite3` | Local cross-project reusable-rule registry; configurable with `FORGE_REUSABLE_RULES_DB`. |
| `<repository>/.forge/vault/` | Generated project decision/context export only; edits do not create records or rules. |

## Canonical records

```text
repositories
  └─ evidence_items ─ evidence_spans
       ├─ session_outcomes (Session Handoffs) ─ session_outcome_citations
       ├─ validation_runs
       └─ decisions ─ decision_citations

learning_cards ─ learning_card_observations
  └─ rule_versions ─ rule_version_citations ─ rule_verifications
       ├─ verification_inputs
       └─ rule_projections / projection_alerts
```

| Record | Meaning | Key safeguard |
|---|---|---|
| `session_outcomes` | Canonical Session Handoff. | Structured, bounded, idempotent by workspace/outcome key; never a transcript. |
| `validation_runs` | Sanitized manual or configured validation result. | Trusted only when it comes from current `forge.validation.json`; no output stored. |
| `learning_cards` | Normalized observed issue: scope, area, trigger, action. | Exact match reuses card; duplicate/conflict alerts block activation. |
| `rule_versions` | Immutable scoped rule statement and version history. | A card owns lifecycle; a rule is projection history. |
| `rule_projections` | Journal of managed `AGENTS.md` updates. | Prepared/applied/failed/reverted state plus managed-block hashes. |
| `verification_inputs` | Later Git, GitHub review, local failure, or validation finding. | Non-validation inputs require explicit developer confirmation. |
| `work_items` / incidents / cases | Detailed, cited work and repeated observation history. | Facts, hypotheses, counterexamples, and outcomes remain separate. |
| `reusable_rules` | Local registry of cross-project rules. | Requires evidence-gated active rules from two repositories plus approval. |

## Learning states

Learning Cards use `observed`, `watching`, `ready`, `active`, `verified`, `contradicted`, `retracted`, and `archived`.

- First trusted observation: `observed` or `watching`.
- Two independent applicable trusted observations: `ready`.
- Ready card: `active` only through autonomous evidence gate or approval-mode developer approval.
- Later support: `verified`.
- Confirmed contradiction: `contradicted`, then `retracted` if the linked active rule is rolled back.
- `archived` remains historical and cannot accept new learning.

Rule versions separately retain historical candidate/active/retracted statements. Legacy older records remain exposed only through `forge_get_legacy_history`.

## Privacy and cleanup

- Forge does not persist chat transcripts, GitHub tokens in telemetry, authorization headers, raw response bodies, or raw validation output.
- A GitHub token is stored only in the local protected connector-secret store and is never returned by API/MCP/export.
- Referenced validation evidence is retained with its handoff/card/rule links.
- Only unreferenced local validation evidence older than 90 days is eligible for cleanup.
- GitHub sync events retain at most 30 days and 500 newest events.
- SQLite migrations are additive and forward-only; never edit an applied migration or delete project data during normal upgrade.
