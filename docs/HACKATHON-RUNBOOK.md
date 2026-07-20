# Forge demo runbook

## Five-minute demonstration

1. Run `forge session-start --path . --agent codex` in a real Git repository.
2. Show `forge doctor --path .` and open the local dashboard if wanted.
3. Call `forge_get_session_start_context`; explain that it returns persisted local facts, not chat history.
4. Run a configured validation such as `forge validate-configured --path . backend-tests`.
5. Submit a cited Session Handoff through MCP and show it in the dashboard or vault.
6. Show a Learning Card moving from observation to ready after two independent trusted observations.
7. Explain that duplicate/conflict alerts require developer review and that contradiction retracts an active rule.

## Safety demonstration

Show that the handoff contains no transcript or raw output, GitHub status contains no token, and ChatGPT HTTP lists only read tools. The tunnel client is optional and external to Forge.
