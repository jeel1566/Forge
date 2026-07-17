import os

from mcp.server.fastmcp import FastMCP

from .store import Store

mcp = FastMCP("Forge")


def current_store() -> Store:
    return Store(os.environ.get("FORGE_DB_PATH"))


@mcp.tool()
def forge_get_project_context(workspace_id: str = "default") -> dict:
    """Return confirmed, cited memory and the one active developer intention."""
    return current_store().context(workspace_id)


@mcp.tool()
def forge_record_decision(statement: str, evidence_quote: str, category: str = "process", workspace_id: str = "default") -> dict:
    """Create a pending evidence-backed decision. The developer must review it in Forge."""
    return current_store().create_pending(workspace_id, statement, category, evidence_quote)


@mcp.tool()
def forge_record_reflection(reflection: str, evidence_quote: str, workspace_id: str = "default") -> dict:
    """Record a pending reflection without accessing chat transcripts."""
    return current_store().create_reflection(workspace_id, reflection, evidence_quote)


@mcp.tool()
def forge_get_active_intention(workspace_id: str = "default") -> dict:
    """Return the single developer-chosen active intention or insufficient data."""
    return current_store().active_intention(workspace_id)


@mcp.tool()
def forge_get_agents_guardrail_candidates(workspace_id: str = "default") -> dict:
    """Return repeated confirmed guardrails with citations; present any AGENTS.md diff for developer approval before editing."""
    return current_store().guardrail_candidates(workspace_id)


@mcp.tool()
def forge_propose_agents_guardrail(statement: str, current_agents_content: str = "", workspace_id: str = "default") -> dict:
    """Create an exact AGENTS.md diff from a cited guardrail. Show it in chat and wait for explicit developer approval before editing the file."""
    return current_store().propose_agents_guardrail(workspace_id, statement, current_agents_content)


@mcp.tool()
def forge_record_agents_guardrail_approval(statement: str, proposed_diff: str, workspace_id: str = "default") -> dict:
    """Record an AGENTS.md handoff only after the developer explicitly approved the shown diff and the active agent applied it."""
    return current_store().record_guardrail_approval(workspace_id, statement, proposed_diff)


if __name__ == "__main__":
    mcp.run()
