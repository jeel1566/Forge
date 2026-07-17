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
    return current_store().create_pending(workspace_id, reflection, "reflection", evidence_quote, "agent_reflection")


@mcp.tool()
def forge_get_active_intention(workspace_id: str = "default") -> dict:
    """Return the single developer-chosen active intention or insufficient data."""
    return current_store().active_intention(workspace_id)


@mcp.tool()
def forge_get_agents_guardrail_candidates(workspace_id: str = "default") -> dict:
    """Return repeated confirmed guardrails with citations; present any AGENTS.md diff for developer approval before editing."""
    return {"candidates": current_store().guardrail_candidates(workspace_id)}


if __name__ == "__main__":
    mcp.run()
