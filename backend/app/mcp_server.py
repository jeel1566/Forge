import os
from pathlib import Path
from typing import Callable, TypeVar

from mcp.server.fastmcp import FastMCP

from .coordination import coordination_status
from .store import Store
from .worktree import git_common_dir, inspect_worktree

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
    """Return confirmed decision memory, approved session handoffs, and the active intention."""
    return with_store(lambda store: store.context(workspace_id))


@mcp.tool()
def forge_get_github_sync_status(workspace_id: str = "default") -> dict:
    """Return compact, local-only GitHub sync health and safe telemetry; never returns credentials or API payloads."""
    def status(store: Store) -> dict:
        value = store.github_poll_status(workspace_id)
        keys = ("workspace_id", "enabled", "health", "partial", "in_progress", "pull_cursor", "last_success_at", "next_poll_at", "retry_after_at", "consecutive_failures", "last_error", "last_error_kind", "last_http_status", "last_request_ms", "rate_limit_remaining", "rate_limit_limit", "rate_limit_reset_at")
        return {key: value.get(key) for key in keys}
    return with_store(status)


@mcp.tool()
def forge_get_session_capture_guidance() -> dict:
    """Return the deterministic, privacy-preserving checklist for an end-of-session handoff."""
    return {
        "status": "ready",
        "rules": [
            "Review only the current agent context; never send a raw chat transcript to Forge.",
            "Describe what changed, why, decisions, problems, fixes, validation, and unresolved work.",
            "Cite at least one existing local Git, PR, or review evidence span.",
            "Create a session context as pending; it never becomes decision memory automatically.",
            "Propose durable decisions separately and only when they are reusable across future work.",
        ],
    }


@mcp.tool()
def forge_get_recent_evidence(workspace_id: str = "default", limit: int = 20) -> list[dict]:
    """Return recent immutable evidence spans for the active project so an agent can cite a handoff."""
    return with_store(lambda store: store.recent_evidence_spans(workspace_id, max(1, min(limit, 50))))


@mcp.tool()
def forge_start_work_session(agent: str, worktree_path: str, workspace_id: str = "default") -> dict:
    """Record a local Git work boundary at session start. It stores no chat content and creates no memory."""
    snapshot = inspect_worktree(worktree_path)
    return with_store(lambda store: store.start_work_session(workspace_id, agent, snapshot["worktree_path"], snapshot["branch"], snapshot["head_commit"]))


@mcp.tool()
def forge_get_worktree_delta(worktree_path: str, base_commit: str | None = None) -> dict:
    """Read the current local Git worktree delta so an agent can split multiple completed changes into separate cited handoffs."""
    return inspect_worktree(worktree_path, base_commit)


@mcp.tool()
def forge_get_coordination_status(workspace_id: str = "default") -> dict:
    """Return local-Git worktree coordination facts, exact overlap warnings, and branch/conflict states without changing files."""
    return with_store(lambda store: coordination_status(store, workspace_id))


@mcp.tool()
def forge_get_worktree_status(worktree_path: str, workspace_id: str | None = None) -> dict:
    """Return one worktree's local Git status. Forge is offline when its local database is unavailable."""
    def read(store: Store) -> dict:
        try:
            resolved_workspace = workspace_id or store.workspace_for_git_common_dir(git_common_dir(worktree_path)) or store.workspace_for_path(worktree_path)
        except ValueError as error:
            return {"status": "unavailable", "reason": str(error), "worktree_path": str(Path(worktree_path).resolve())}
        if not resolved_workspace:
            return {"status": "unavailable", "reason": "Worktree is not associated with a registered Forge repository.", "worktree_path": str(Path(worktree_path).resolve())}
        result = coordination_status(store, resolved_workspace)
        for worktree in result["worktrees"]:
            if worktree["worktree_path"].lower() == str(Path(worktree_path).resolve()).lower():
                return {"status": result["status"], "workspace_id": resolved_workspace, "worktree": worktree, "overlaps": [overlap for overlap in result["overlaps"] if worktree["worktree_path"] in overlap["worktree_paths"]]}
        return {"status": "unavailable", "reason": "Worktree was not returned by local Git discovery.", "worktree_path": str(Path(worktree_path).resolve())}
    return with_store(read)


@mcp.tool()
def forge_finish_work_session(session_id: str) -> dict:
    """Close a recorded local Git work boundary using its current HEAD. It stores no chat content."""
    def finish(store: Store) -> dict:
        session = store.get_work_session(session_id)
        if not session:
            raise ValueError("Work session not found.")
        snapshot = inspect_worktree(session["worktree_path"], session["base_commit"])
        return {"session": store.finish_work_session(session_id, snapshot["head_commit"]), "delta": snapshot}
    return with_store(finish)


@mcp.tool()
def forge_record_decision(statement: str, evidence_quote: str, category: str = "process", workspace_id: str = "default", evidence_span_ids: list[str] | None = None) -> dict:
    """Create a pending evidence-backed decision. The developer must review it in Forge."""
    return with_store(lambda store: store.create_pending(workspace_id, statement, category, evidence_quote, evidence_span_ids=evidence_span_ids))


@mcp.tool()
def forge_record_session_context(agent: str, worktree_path: str, branch: str, what_changed: str, why: str, decisions: str, problems: str, fixes: str, validation: str, unresolved: str, evidence_span_ids: list[str], workspace_id: str = "default", base_commit: str | None = None, head_commit: str | None = None) -> dict:
    """Create a pending multi-agent session handoff cited to existing project evidence; it never creates decision memory."""
    return with_store(lambda store: store.create_session_context(workspace_id, agent, worktree_path, branch, what_changed, why, decisions, problems, fixes, validation, unresolved, evidence_span_ids, base_commit, head_commit))


@mcp.tool()
def forge_record_session_contexts(handoffs: list[dict], workspace_id: str = "default") -> list[dict]:
    """Create multiple pending, cited session handoffs from one agent session. Forge never chooses, approves, or turns them into memory."""
    return with_store(lambda store: store.create_session_contexts(workspace_id, handoffs))


@mcp.tool()
def forge_record_structured_session_handoff(agent: str, worktree_path: str, branch: str, evidence_span_ids: list[str], template: dict, workspace_id: str = "default", base_commit: str | None = None, head_commit: str | None = None) -> dict:
    """Create one pending template-v1 handoff with explicit Git citations; unknown facts must be labeled unknown or not_run."""
    return with_store(lambda store: store.create_structured_session_context(workspace_id, agent, worktree_path, branch, evidence_span_ids, template, base_commit, head_commit))


@mcp.tool()
def forge_propose_decision_from_session_context(session_context_id: str, statement: str, category: str = "process", workspace_id: str = "default") -> dict:
    """Create a pending durable decision from one approved session handoff. The developer must still confirm it separately."""
    def create(store: Store) -> dict:
        session = store.get_session_context(session_context_id)
        if not session:
            raise ValueError("Session context not found.")
        return store.create_pending(workspace_id, statement, category, session["what_changed"], evidence_span_ids=[citation["span_id"] for citation in session["citations"]], source_session_context_id=session_context_id)
    return with_store(create)


@mcp.tool()
def forge_propose_structured_decision(source_session_context_id: str, evidence_span_ids: list[str], template: dict, workspace_id: str = "default") -> dict:
    """Create a pending ADR-lite decision from an approved handoff. Only developer confirmation creates durable memory."""
    return with_store(lambda store: store.create_structured_decision(workspace_id, source_session_context_id, evidence_span_ids, template))


@mcp.tool()
def forge_retrieve_decisions(workspace_id: str = "default", file_path: str | None = None, scope: str | None = None, category: str | None = None, status: str | None = "confirmed", limit: int = 20) -> list[dict]:
    """Retrieve cited decisions by file path, scope, category, and review status without reading any chat transcript."""
    return with_store(lambda store: store.retrieve_decisions(workspace_id, file_path=file_path, scope=scope, category=category, status=status, limit=limit))


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
def forge_get_portable_guardrails(workspace_id: str = "default") -> list[dict]:
    """Return individually approved guardrails from other projects; never copy a whole AGENTS.md file."""
    return with_store(lambda store: store.portable_guardrails(workspace_id))


@mcp.tool()
def forge_propose_agents_guardrail(statement: str, current_agents_content: str = "", workspace_id: str = "default") -> dict:
    """Create an exact AGENTS.md diff from a cited guardrail. Show it in chat and wait for explicit developer approval before editing the file."""
    return with_store(lambda store: store.propose_agents_guardrail(workspace_id, statement, current_agents_content))


@mcp.tool()
def forge_record_agents_guardrail_approval(statement: str, proposed_diff: str, developer_approved: bool, workspace_id: str = "default") -> dict:
    """Record an AGENTS.md handoff only after the developer explicitly approved the shown diff and the active agent applied it."""
    if not developer_approved:
        raise ValueError("Record approval only after the developer explicitly said yes to the shown diff.")
    return with_store(lambda store: store.record_guardrail_approval(workspace_id, statement, proposed_diff))


@mcp.tool()
def forge_prepare_agents_guardrail_handoff(statement: str, current_agents_content: str = "", target_agents_path: str = "AGENTS.md", workspace_id: str = "default") -> dict:
    """Create a persisted exact AGENTS.md proposal. Show its diff, wait for developer approval, then apply it through normal file editing; Forge never edits the file."""
    return with_store(lambda store: store.prepare_agents_guardrail_handoff(workspace_id, statement, current_agents_content, target_agents_path))


@mcp.tool()
def forge_prepare_portable_guardrail_handoff(source_guardrail_id: str, current_agents_content: str = "", target_agents_path: str = "AGENTS.md", workspace_id: str = "default") -> dict:
    """Create one target-project diff for a portable approved rule; never copy another project's entire AGENTS.md file."""
    return with_store(lambda store: store.prepare_agents_guardrail_handoff(workspace_id, "", current_agents_content, target_agents_path, source_guardrail_id))


@mcp.tool()
def forge_complete_agents_guardrail_handoff(handoff_id: str, developer_approved: bool, resulting_agents_content: str) -> dict:
    """Record an already agent-applied AGENTS.md edit only when its resulting content hash matches the developer-approved proposal."""
    return with_store(lambda store: store.complete_agents_guardrail_handoff(handoff_id, developer_approved, resulting_agents_content))


@mcp.tool()
def forge_record_portable_guardrail_adoption(source_guardrail_id: str, developer_approved: bool, workspace_id: str = "default") -> dict:
    """Record one developer-approved portable rule after the active agent applied its shown diff."""
    return with_store(lambda store: store.adopt_portable_guardrail(workspace_id, source_guardrail_id, developer_approved))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
