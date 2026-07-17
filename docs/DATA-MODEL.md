# Data model

Forge uses one local SQLite database per selected repository by default: `.forge/forge.sqlite3`.

## Current local schema

```text
repositories
evidence_items -> evidence_spans
decisions <-> decision_citations -> evidence_spans
intentions
connector_state + connector_secrets
```

| Entity | Responsibility | Rule |
|---|---|---|
| `repositories` | Maps a workspace identifier to one local Git path. | Local Git is the default evidence source. |
| `evidence_items` | Immutable commits, agent decisions, and reflections. | A Git commit is unique per workspace and commit hash. |
| `evidence_spans` | Exact quoted commit subject or agent-supplied supporting text. | Derived decisions cite spans, not unstructured IDs. |
| `decisions` | Pending, confirmed, or rejected developer-review items. | Only confirmed decisions are returned as memory. |
| `decision_citations` | Relates decisions to one or more exact evidence spans. | Citations remain after rejection. |
| `intentions` | The one developer-chosen active intention per workspace. | One row per workspace. |
| `connector_state` | Non-secret GitHub connector status. | Status never contains credentials. |
| `connector_secrets` | GitHub token and webhook secret encrypted with Windows DPAPI. | Values are never returned by the API or dashboard. |

Confirmed memory is currently a read projection of confirmed decisions, keeping the first useful implementation small while preserving immutable evidence and review history.

## Deferred schema

`ingestion_events`, GitHub PR/review evidence, verification runs, pattern observations, versioned memory projections, and optional sync remain deferred until the local evidence loop needs them. Cloud accounts, raw chat transcripts, and automatic `AGENTS.md` edits are not part of the schema.
