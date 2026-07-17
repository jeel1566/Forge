import os
from pathlib import Path
from typing import Callable, TypeVar

from mcp.server.fastmcp import FastMCP

from .store import Store

mcp = FastMCP("Forge")
Result = TypeVar("Result")


def current_store() -> Store:
    database = Path(os.environ.get("FORGE_DB_PATH", ".forge/forge.sqlite3")).expanduser()
    if not database.exists():
        raise RuntimeError(f"Forge is offline: no local database exists at {database}. Start Forge first with `forge start`.")
    return Store(database)


def with_store(operation: Callable[[Store], Result]) -> Result:
    store = current_store()
    try:
        return operation(store)
    finally:
        store.close()


@mcp.tool()
def forge_get_project_context(workspace_id: str = "default") -> dict:
    """Return confirmed, cited memory and the one active developer intention."""
    return with_store(lambda store: store.context(workspace_id))


@mcp.tool()
def forge_record_decision(statement: str, evidence_quote: str, category: str = "process", workspace_id: str = "default") -> dict:
    """Create a pending evidence-backed decision. The developer must review it in Forge."""
    return with_store(lambda store: store.create_pending(workspace_id, statement, category, evidence_quote))


@mcp.tool()
def forge_record_reflection(reflection: str, evidence_quote: str, workspace_id: str = "default") -> dict:
    """Record a pending reflection without accessing chat transcripts."""
    return with_store(lambda store: store.create_reflection(workspace_id, reflection, evidence_quote))


@mcp.tool()
def forge_get_active_intention(workspace_id: str = "default") -> dict:
    """Return the single developer-chosen active intention or insufficient data."""
    return with_store(lambda store: store.active_intention(workspace_id))


@mcp.tool()
def forge_get_agents_guardrail_candidates(workspace_id: str = "default") -> dict:
    """Return repeated confirmed guardrails with citations; present any AGENTS.md diff for developer approval before editing."""
    return with_store(lambda store: store.guardrail_candidates(workspace_id))


@mcp.tool()
def forge_propose_agents_guardrail(statement: str, current_agents_content: str = "", workspace_id: str = "default") -> dict:
    """Create an exact AGENTS.md diff from a cited guardrail. Show it in chat and wait for explicit developer approval before editing the file."""
    return with_store(lambda store: store.propose_agents_guardrail(workspace_id, statement, current_agents_content))


@mcp.tool()
def forge_record_agents_guardrail_approval(statement: str, proposed_diff: str, workspace_id: str = "default") -> dict:
    """Record an AGENTS.md handoff only after the developer explicitly approved the shown diff and the active agent applied it."""
    return with_store(lambda store: store.record_guardrail_approval(workspace_id, statement, proposed_diff))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
