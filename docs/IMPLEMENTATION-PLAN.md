# Local-first implementation plan

## Product decision

Forge is an installable memory layer for coding agents, not a hosted AI coach. It runs on the developer's computer, stores data locally by default, and lets Codex or Antigravity contribute context through MCP. The developer remains the only authority that promotes a draft into memory.

```text
install Forge -> choose a repository -> connect an agent -> work normally
-> review one optional draft or intention -> receive it as cited context later
```

| Decision | Why | Guardrail |
|---|---|---|
| SQLite is the default store. | No account, cloud cost, or setup required. | Optional sync is separate and opt-in. |
| Local web app on `127.0.0.1`. | A visible, inspectable product surface. | Never expose the server to the network by default. |
| MCP is on-demand. | Agents connect only while they are active. | MCP writes create drafts, never confirmed memory. |
| Local Git evidence first. | Works offline and needs no GitHub token. | Store exact commit, diff, and PR references. |
| GitHub polling is optional. | Adds PR and review context without a public webhook endpoint. | Use a fine-grained token and clear connection status. |
| Agent reasoning is bring-your-own. | Users keep their existing Codex or Antigravity access. | Forge never silently reads chat transcripts. |

## Slice 0 — One loop contract

Define and test the only user loop we will demo:

1. A developer finishes a coding session or commits work.
2. Forge records local Git evidence and, if the user elects, an agent-supplied draft.
3. At the next coding session, the agent asks whether one cited draft should be confirmed or turned into a tiny intention.
4. The developer confirms, edits, dismisses, or reflects. Forge shows the evidence either way.

**Done when:** the team can describe this in one sentence and no feature bypasses explicit developer review.

## Slice 1 — Installable local core

Build a Python package with `forge start`, serving the React dashboard and FastAPI API at `127.0.0.1`. Create the SQLite schema, local repository registration, health/status screen, migrations, backup/export, and one seeded demo repository.

**Done when:** a clean machine can install Forge, open the dashboard, restart it, and retain its data without any cloud credentials.

## Slice 2 — Evidence and reviewed memory

Add local Git commit/diff ingestion, immutable evidence spans, cited pending decisions, confirmation/rejection, and confirmed-memory retrieval. Add an optional GitHub polling connector for pull requests and reviews; do not require webhooks in the default install.

**Tests:** duplicate commit ingestion; no source span; rejected draft; restart persistence; unavailable GitHub network.

**Done when:** one real local commit can become one reviewed, cited memory item.

## Slice 3 — Agent augmentation

Ship `forge_get_project_context`, `forge_record_decision`, `forge_record_reflection`, and `forge_get_active_intention` through the Python MCP server. Add a Codex skill/instruction for voluntary end-of-session capture. Add an optional Antigravity Stop hook that records only session metadata; raw transcript capture stays off by default.

**Tests:** MCP writes remain pending; inactive agent connection does not block Forge; no chat content is captured without explicit opt-in.

**Done when:** either supported agent can retrieve context and save a user-approved candidate.

## Slice 4 — One intention and AGENTS.md handoff

Replace generic coaching with one active, developer-chosen intention per repository. The dashboard has a single Today view: current intention, one cited memory, evidence link, and confirm/dismiss/reflection actions. Include empty, loading, offline, and insufficient-evidence states.

Add an AGENTS.md handoff flow. When cited evidence reveals a repeated, developer-confirmed repository guardrail, the active agent shows the exact proposed AGENTS.md diff in chat. The agent edits the file only after explicit approval. For a new repository, the agent asks whether approved, portable guardrails should be brought in; it never copies an entire prior AGENTS.md blindly.

**Done when:** a developer can complete the loop in under a minute without reading product documentation, and can approve or dismiss an AGENTS.md patch without Forge writing files directly.

## Slice 5 — Open-source and hackathon delivery

Add one-command installation, a local demo fixture/reset, screenshots, a 3-minute demo script, clear privacy copy, architecture diagram, and agent setup instructions. If submitting to Build Week, add a narrowly scoped GPT-5.6 feature only for the submission requirement; normal Forge use remains API-key-free.

**Done when:** a judge can install or open the demo, trace one memory item to evidence, and understand the privacy model immediately.

## Explicitly deferred

Cloud accounts, mandatory Supabase, mandatory GitHub webhooks, automatic transcript ingestion, autonomous coaching, automatic AGENTS.md edits, developer scoring, multi-user permissions, vector search, background start-at-login, and multi-device sync are not MVP features.
