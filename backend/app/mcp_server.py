import os
from pathlib import Path
from typing import Callable, TypeVar

from mcp.server.fastmcp import FastMCP

from .coordination import coordination_status
from .runtime import ForgeRuntime
from .store import Store
from .validation import run_configured_validation, run_validation
from .worktree import inspect_worktree

mcp = FastMCP("Forge")
Result = TypeVar("Result")


def current_store() -> Store:
    configured = os.environ.get("FORGE_DB_PATH")
    if configured:
        database = Path(configured).expanduser()
    else:
        current = Path.cwd().resolve()
        repository = next((path for path in (current, *current.parents) if (path / ".git").exists()), current)
        database = repository / ".forge" / "forge.sqlite3"
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
def forge_initialize_workspace(mode: str, workspace_id: str = "default") -> dict:
    """Persist the workspace rule policy: approval or autonomous."""
    return with_store(lambda store: store.configure_rule_policy(workspace_id, mode))


@mcp.tool()
def forge_get_session_start_context(workspace_id: str = "default", scope: str | None = None) -> dict:
    """Return the compact persisted context needed to begin work: active rules, alerts, decisions, and latest handoff."""
    return with_store(lambda store: store.session_start_context(workspace_id, scope))


@mcp.tool()
def forge_get_latest_session_handoff(workspace_id: str = "default") -> dict:
    """Return the newest persisted Session Handoff only; never infer facts from chat or source files."""
    return with_store(lambda store: store.get_latest_session_handoff(workspace_id))


@mcp.tool()
def forge_get_session_handoff(handoff_id: str) -> dict:
    """Return one persisted cited Session Handoff."""
    return with_store(lambda store: store.get_session_handoff(handoff_id) or {"status": "not_found"})


def _record_handoff(store: Store, workspace_id: str, payload: dict) -> dict:
    result = store.record_session_handoff(workspace_id, **payload)
    rule = result.get("rule")
    if rule and rule.get("eligible") and store.rule_policy(workspace_id)["mode"] == "autonomous" and rule["state"] == "candidate":
        result["rule"] = store.activate_rule(rule["id"])
        result["activation"] = "autonomous"
    elif rule and rule.get("eligible"):
        result["activation"] = "pending_developer_approval"
    return result


def _normalized_completion_handoff(handoff: dict) -> dict:
    if not isinstance(handoff, dict):
        raise ValueError("handoff must be an object.")
    payload = dict(handoff)
    if "unresolved" not in payload and "unresolved_work" in payload:
        payload["unresolved"] = payload.pop("unresolved_work")
    agent = payload.get("agent")
    if isinstance(agent, str):
        payload["agent"] = agent.strip().lower()
    if payload.get("agent") not in {"codex", "antigravity", "agent"}:
        raise ValueError("handoff.agent must be codex, antigravity, or agent.")
    required = (
        "agent", "worktree_path", "branch", "outcome_key", "scope", "category",
        "goal", "problem", "prior_approach", "why_prior_approach_failed",
        "alternatives", "chosen_fix", "rationale", "validation", "risk", "unresolved",
        "proposed_rule", "evidence_span_ids",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        raise ValueError(f"handoff is missing required fields: {', '.join(missing)}.")
    return payload


def _runtime_for(store: Store) -> ForgeRuntime:
    return ForgeRuntime(store.path.parent.parent)


@mcp.tool()
def forge_record_session_handoff(agent: str, worktree_path: str, branch: str, outcome_key: str, scope: list[str], category: str, goal: str, problem: str, prior_approach: str, why_prior_approach_failed: str, alternatives: list[dict], chosen_fix: str, rationale: str, validation: str, risk: str, unresolved: str, proposed_rule: str, evidence_span_ids: list[str], learning_card_id: str | None = None, learning_area: str | None = None, learning_trigger: str | None = None, learning_action: str | None = None, workspace_id: str = "default") -> dict:
    """Record an agent-authored, transcript-free Session Handoff without releasing an agent lease."""
    payload = locals().copy()
    payload.pop("workspace_id")
    return with_store(lambda store: _record_handoff(store, workspace_id, payload))


@mcp.tool()
def forge_complete_session(session_id: str, handoff: dict, workspace_id: str = "default") -> dict:
    """Save one cited transcript-free Session Handoff and mark its lease ready for `forge session-end`.

    `handoff` requires: agent, worktree_path, branch, outcome_key, scope, category, goal,
    problem, prior_approach, why_prior_approach_failed, alternatives, chosen_fix, rationale,
    validation, risk, unresolved, proposed_rule, and evidence_span_ids. Use `unresolved`, not
    `unresolved_work`; the latter is accepted only as a compatibility alias. Set
    `proposed_rule` to `none` when no rule is proposed.
    """
    handoff = _normalized_completion_handoff(handoff)
    agent = handoff["agent"]

    def complete(store: Store) -> dict:
        result = _record_handoff(store, workspace_id, handoff)
        completion = _runtime_for(store).mark_handoff(session_id, agent, result["outcome"]["id"])
        return {**result, "completion": completion, "learning_alerts": store.learning_alerts(workspace_id)}

    return with_store(complete)


@mcp.tool()
def forge_heartbeat_session(session_id: str) -> dict:
    """Refresh one active local Forge session lease. It stores only session timing and agent identity."""
    return with_store(lambda store: _runtime_for(store).heartbeat(session_id))


@mcp.tool()
def forge_start_dashboard(workspace_id: str = "default") -> dict:
    """Start or reuse the local loopback dashboard under the persistent Forge MCP process."""
    def start(store: Store) -> dict:
        repository = store.repository(workspace_id)
        if not repository:
            raise ValueError("Repository is not registered.")
        return ForgeRuntime(repository["path"]).start_dashboard(store.path, workspace_id)
    return with_store(start)


@mcp.tool()
def forge_list_learning_cards(workspace_id: str = "default", state: str | None = None) -> list[dict]:
    """List persisted Learning Cards with observations, linked rule versions, and pending alerts."""
    return with_store(lambda store: store.learning_cards(workspace_id, state))


@mcp.tool()
def forge_get_learning_card(card_id: str) -> dict:
    """Return one persisted Learning Card timeline and its immutable observations."""
    def get(store: Store) -> dict:
        return next((card for card in store.learning_cards_for_id(card_id)), {"status": "not_found"})
    return with_store(get)


@mcp.tool()
def forge_get_learning_alerts(workspace_id: str = "default") -> list[dict]:
    """Return duplicate, conflict, overdue-review, and projection-repair alerts."""
    return with_store(lambda store: store.learning_alerts(workspace_id))


@mcp.tool()
def forge_review_learning_alert(alert_id: str, decision: str) -> dict:
    """Record the developer's explicit duplicate/conflict decision: merged, kept_separate, or marked_conflict."""
    return with_store(lambda store: store.review_learning_alert(alert_id, decision))


@mcp.tool()
def forge_get_rule_history(workspace_id: str = "default", state: str | None = None) -> list[dict]:
    """Return local rule version and verification history."""
    return with_store(lambda store: store.list_rule_versions(workspace_id, state))


@mcp.tool()
def forge_get_rule_proposal(rule_version_id: str) -> dict:
    """Return the exact managed AGENTS.md diff for a ready approval-mode rule."""
    return with_store(lambda store: store.rule_proposal(rule_version_id))


@mcp.tool()
def forge_approve_rule(rule_version_id: str, developer_approved: bool) -> dict:
    """Apply a ready approval-mode rule only after explicit developer approval."""
    return with_store(lambda store: store.approve_rule(rule_version_id, developer_approved))


@mcp.tool()
def forge_verify_rule(rule_version_id: str, result: str, evidence_span_id: str, note: str) -> dict:
    """Record later configured-validation evidence that verifies or contradicts an active rule."""
    return with_store(lambda store: store.verify_rule(rule_version_id, result, evidence_span_id, note))


@mcp.tool()
def forge_record_verification_input(rule_version_id: str, source_kind: str, result: str, evidence_span_id: str, summary: str, developer_confirmed: bool = False) -> dict:
    """Record cited later Git, GitHub review, local failure, or configured-validation evidence. Non-validation inputs require developer confirmation before changing a rule."""
    return with_store(lambda store: store.record_verification_input(rule_version_id, source_kind, result, evidence_span_id, summary, developer_confirmed))


@mcp.tool()
def forge_record_local_failure(rule_version_id: str, failure_class: str, summary: str, result: str = "contradicted", developer_confirmed: bool = False) -> dict:
    """Record a bounded local failure without command output. Developer confirmation is required before it changes a rule."""
    return with_store(lambda store: store.record_local_failure(rule_version_id, failure_class, summary, result, developer_confirmed))


@mcp.tool()
def forge_confirm_verification_input(input_id: str) -> dict:
    """Apply a previously cited non-validation verification input after the developer explicitly confirms it."""
    return with_store(lambda store: store.confirm_verification_input(input_id))


@mcp.tool()
def forge_get_recent_evidence(workspace_id: str = "default", limit: int = 20) -> list[dict]:
    """Return recent safe evidence spans for citation."""
    return with_store(lambda store: store.recent_evidence_spans(workspace_id, max(1, min(limit, 50))))


@mcp.tool()
def forge_run_validation(label: str, command: list[str], timeout_seconds: int = 900, workspace_id: str = "default") -> dict:
    """Run a manual untrusted validation. Its result is context only and can never advance a Learning Card."""
    return with_store(lambda store: run_validation(store, workspace_id, label, command, timeout_seconds))


@mcp.tool()
def forge_run_configured_validation(validation_id: str, workspace_id: str = "default") -> dict:
    """Run one configured Forge validation by ID; only these safe results can support Learning Cards."""
    return with_store(lambda store: run_configured_validation(store, workspace_id, validation_id))


@mcp.tool()
def forge_get_legacy_history(workspace_id: str = "default", limit: int = 20) -> dict:
    """Read preserved legacy session contexts and rules. Legacy data is read-only and cannot affect new learning."""
    return with_store(lambda store: store.legacy_history(workspace_id, limit))


@mcp.tool()
def forge_record_decision(statement: str, evidence_quote: str, category: str = "process", workspace_id: str = "default", evidence_span_ids: list[str] | None = None) -> dict:
    """Create a pending durable decision unrelated to rule activation."""
    return with_store(lambda store: store.create_pending(workspace_id, statement, category, evidence_quote, evidence_span_ids=evidence_span_ids))


@mcp.tool()
def forge_retrieve_decisions(workspace_id: str = "default", file_path: str | None = None, scope: str | None = None, category: str | None = None, status: str | None = "confirmed", limit: int = 20) -> list[dict]:
    """Retrieve cited durable decisions without reading a transcript."""
    return with_store(lambda store: store.retrieve_decisions(workspace_id, file_path=file_path, scope=scope, category=category, status=status, limit=limit))


@mcp.tool()
def forge_get_github_sync_status(workspace_id: str = "default") -> dict:
    """Return local-only GitHub sync health and safe telemetry."""
    return with_store(lambda store: store.github_poll_status(workspace_id))


@mcp.tool()
def forge_start_work_session(agent: str, worktree_path: str, workspace_id: str = "default") -> dict:
    """Record a local Git work boundary; no chat content is captured."""
    snapshot = inspect_worktree(worktree_path)
    return with_store(lambda store: store.start_work_session(workspace_id, agent, snapshot["worktree_path"], snapshot["branch"], snapshot["head_commit"]))


@mcp.tool()
def forge_get_worktree_delta(worktree_path: str, base_commit: str | None = None) -> dict:
    """Return local Git delta facts for the active worktree."""
    return inspect_worktree(worktree_path, base_commit)


@mcp.tool()
def forge_get_coordination_status(workspace_id: str = "default") -> dict:
    """Return local worktree coordination facts and overlap warnings."""
    return with_store(lambda store: coordination_status(store, workspace_id))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
