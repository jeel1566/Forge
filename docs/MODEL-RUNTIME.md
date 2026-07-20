# Model and agent boundary

## Forge is not an AI model

Forge has no model provider SDK, no OpenAI API integration, no LangChain, no LlamaIndex, no vector database, and no hidden transcript reader. It does not choose a model, ask a model to summarise work, judge a model's reasoning, or train on Forge data.

Forge's role is deliberately smaller: a durable local decision ledger, deterministic evidence checks, rule lifecycle control, and retrieval of only relevant guidance through MCP. It does not try to retain or recreate an agent's entire working context.

## Codex and GPT-5.6

When Codex is configured with GPT-5.6, GPT-5.6 is the reasoning layer outside Forge. It can:

1. Read the project's own instructions and active Forge rules.
2. Retrieve compact persisted context through `forge_get_session_start_context`.
3. Inspect code, change it, and run validations.
4. Write a clean structured handoff from its own working context.
5. Submit cited facts to Forge through MCP.

Forge accepts the submitted structure and referenced local evidence; it does not receive the full Codex chat. The same boundary applies to Antigravity and any model it uses.

## What “Forge is the memory, not the brain” means

| Responsibility | Agent/model | Forge |
|---|---|---|
| Understand a task and plan code | Yes | No |
| Read private conversation context | Yes, inside its host | No |
| Make code changes | Yes | No |
| Run an approved local validation | Requests it | Records safe result and may execute configured argv |
| Explain a decision or failure | Writes the handoff | Stores structured fields and citations |
| Decide if a rule meets the evidence gate | Proposes evidence | Deterministic checks and developer policy |
| Persist reusable local context | Reads/writes through MCP | Yes |

The repository contains no raw-chat record that could establish a measured claim about how GPT-5.6 performed while Forge was built. Documentation therefore describes the implemented boundary, not an invented benchmark or transcript summary.

## ChatGPT web

ChatGPT web uses a separate read-only Streamable HTTP MCP endpoint at loopback. An OpenAI Secure MCP Tunnel can forward that endpoint when the developer explicitly starts it. ChatGPT receives only requested persisted facts and cannot call Forge write, approval, validation, or projection tools.

See [Installation](INSTALLATION.md#chatgpt-web-connector-optional-read-only) and [API/MCP reference](API-MCP-SPEC.md).
