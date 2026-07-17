from mcp.server.fastmcp import FastMCP
from .store import store

mcp = FastMCP("Forge")


@mcp.tool()
def forge_get_project_context(workspace_id: str = "default") -> dict:
    """Return only confirmed, cited project memory and active coaching."""
    return store.context(workspace_id)


@mcp.tool()
def forge_record_decision(statement: str, evidence_quote: str, category: str = "process", workspace_id: str = "default") -> dict:
    """Create pending evidence-backed memory; browser review remains required."""
    return store.create_pending(workspace_id, statement, category, evidence_quote)


if __name__ == "__main__":
    mcp.run()
