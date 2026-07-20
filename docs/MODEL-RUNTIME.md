# Model runtime boundaries

## What Forge knows

Forge knows the submitting agent identifier, a structured outcome, cited local evidence, and persisted rule/decision metadata. It does not know or store the raw Codex, Antigravity, ChatGPT, or other-agent conversation.

## GPT-5.6 in Codex

This repository has no direct GPT-5.6 SDK/API integration and no LangChain or LlamaIndex dependency. If a Codex session is configured to use GPT-5.6, that model is the reasoning agent: it reads repository instructions, retrieves Forge context through MCP, writes its own compact session summary, and submits it through MCP. Forge does not select, call, evaluate, or train the model.

No separate Forge chat archive was available in this repository to make claims about prior GPT-5.6 sessions. This document therefore describes the architectural role, not a measured model-performance report.

## ChatGPT Apps

ChatGPT Apps use MCP through the Apps SDK, but ChatGPT connects to remote MCP servers rather than Forge's local stdio process. Forge provides `forge mcp-http --path .`, a separate loopback-only Streamable HTTP MCP server with safe read tools only. OpenAI's separately installed Secure MCP Tunnel client supplies the remote connection without publicly exposing Forge. The regular Codex and Antigravity stdio MCP server retains the developer-reviewed write workflow. See the [installation guide](INSTALLATION.md#4-optional-chatgpt-web-connector) for the real tunnel lifecycle and security boundaries.

Useful official references: [Build with the Apps SDK](https://help.openai.com/en/articles/12515353-build-with-the-apps-sdk) and [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta).
