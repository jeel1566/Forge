from datetime import UTC, datetime, timedelta

from .worktree import branch_state, changed_files, discover_worktrees, resolve_base_ref, unresolved_conflicts


def _now() -> str:
    return datetime.now(UTC).isoformat()


def coordination_status(store, workspace_id: str, recent_hours: int = 24) -> dict:
    repository = store.repository(workspace_id)
    if not repository:
        return {"status": "unavailable", "reason": "Repository is not registered.", "worktrees": [], "overlaps": []}
    try:
        discovery = discover_worktrees(repository["path"])
    except ValueError as error:
        return {"status": "unavailable", "reason": str(error), "worktrees": [], "overlaps": []}

    base_ref = resolve_base_ref(discovery["repository_path"], repository.get("coordination_base_ref"))
    recent_since = (datetime.now(UTC) - timedelta(hours=recent_hours)).isoformat()
    sessions = store.active_or_recent_work_sessions(workspace_id, recent_since)
    sessions_by_path = {session["worktree_path"].lower(): session for session in sessions}
    entries = []
    for worktree in discovery["worktrees"]:
        session = sessions_by_path.get(worktree["worktree_path"].lower())
        merge_status = branch_state(worktree["worktree_path"], base_ref)
        comparison_base = session["base_commit"] if session else merge_status.get("base_commit")
        files = changed_files(worktree["worktree_path"], comparison_base, worktree["head_commit"])
        conflicts = unresolved_conflicts(worktree["worktree_path"])
        entries.append({
            **worktree,
            "active_session_id": session["id"] if session and session["ended_at"] is None else None,
            "recent_session_id": session["id"] if session else None,
            "session_base_commit": comparison_base,
            "changed_files": files.get("files", []),
            "changed_files_status": files["status"],
            "changed_files_reason": files.get("reason"),
            "merge_status": merge_status,
            "conflict_status": conflicts,
            "checked_at": _now(),
            "sources": [
                "git worktree list --porcelain",
                "git diff --name-only <base>..<head>",
                "git diff --name-only --diff-filter=U",
                "git merge-base --is-ancestor",
            ],
        })

    active_or_recent = [entry for entry in entries if entry["recent_session_id"]]
    overlaps = []
    for index, first in enumerate(active_or_recent):
        first_files = set(first["changed_files"]) if first["changed_files_status"] == "ready" else set()
        for second in active_or_recent[index + 1:]:
            shared_files = sorted(first_files.intersection(second["changed_files"])) if second["changed_files_status"] == "ready" else []
            if shared_files:
                overlaps.append({
                    "status": "possible_overlap",
                    "worktree_paths": [first["worktree_path"], second["worktree_path"]],
                    "files": shared_files,
                    "reason": "Both active or recent sessions changed these paths; review before integrating.",
                })
    store.sync_worktrees(workspace_id, discovery["git_common_dir"], entries)
    return {
        "status": "ready",
        "workspace_id": workspace_id,
        "repository_path": discovery["repository_path"],
        "git_common_dir": discovery["git_common_dir"],
        "base_ref": base_ref,
        "base_ref_status": "ready" if base_ref else "unavailable",
        "worktrees": entries,
        "overlaps": overlaps,
        "sources": ["local Git metadata only"],
    }
