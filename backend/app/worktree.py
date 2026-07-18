import subprocess
from pathlib import Path


def _git(path: str | Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(Path(path).resolve()), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "Not a local Git worktree.")
    return result.stdout.strip()


def parse_worktree_porcelain(output: str) -> list[dict]:
    """Parse `git worktree list --porcelain` without reading worktree files."""
    worktrees = []
    for block in output.strip().split("\n\n"):
        fields = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key:
                fields[key] = value
        if "worktree" not in fields:
            continue
        branch_ref = fields.get("branch")
        worktrees.append({
            "worktree_path": str(Path(fields["worktree"]).resolve()),
            "head_commit": fields.get("HEAD"),
            "branch": branch_ref.removeprefix("refs/heads/") if branch_ref else "(detached)",
            "is_detached": "detached" in fields or not branch_ref,
            "is_bare": "bare" in fields,
            "is_locked": "locked" in fields,
            "lock_reason": fields.get("locked") or None,
            "is_prunable": "prunable" in fields,
            "prunable_reason": fields.get("prunable") or None,
        })
    return worktrees


def git_common_dir(path: str | Path) -> str:
    root = Path(_git(path, "rev-parse", "--show-toplevel"))
    common_dir = Path(_git(root, "rev-parse", "--git-common-dir"))
    return str((root / common_dir).resolve() if not common_dir.is_absolute() else common_dir.resolve())


def discover_worktrees(path: str | Path) -> dict:
    root = _git(path, "rev-parse", "--show-toplevel")
    return {
        "repository_path": str(Path(root).resolve()),
        "git_common_dir": git_common_dir(root),
        "worktrees": parse_worktree_porcelain(_git(root, "worktree", "list", "--porcelain")),
    }


def _git_result(path: str | Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(Path(path).resolve()), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def resolve_base_ref(path: str | Path, configured_base_ref: str | None = None) -> str | None:
    candidates = [configured_base_ref] if configured_base_ref else []
    remote_head = _git_result(path, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote_head.returncode == 0 and remote_head.stdout.strip():
        candidates.append(remote_head.stdout.strip())
    candidates.extend(["main", "master"])
    for candidate in dict.fromkeys(item for item in candidates if item):
        if _git_result(path, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}").returncode == 0:
            return candidate
    return None


def branch_state(path: str | Path, base_ref: str | None) -> dict:
    if not base_ref:
        return {"status": "unavailable", "reason": "No configured base branch is available locally."}
    base = _git_result(path, "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}")
    head = _git_result(path, "rev-parse", "--verify", "HEAD")
    if base.returncode or head.returncode:
        return {"status": "unavailable", "reason": "The base branch or HEAD is unavailable locally."}
    base_commit, head_commit = base.stdout.strip(), head.stdout.strip()
    if base_commit == head_commit:
        status = "up_to_date"
    elif _git_result(path, "merge-base", "--is-ancestor", base_commit, head_commit).returncode == 0:
        status = "ahead"
    elif _git_result(path, "merge-base", "--is-ancestor", head_commit, base_commit).returncode == 0:
        status = "behind"
    else:
        status = "diverged"
    return {"status": status, "base_ref": base_ref, "base_commit": base_commit, "head_commit": head_commit}


def changed_files(path: str | Path, base_commit: str | None, head_commit: str | None) -> dict:
    if not base_commit or not head_commit:
        return {"status": "unavailable", "reason": "A base commit and HEAD commit are required."}
    result = _git_result(path, "diff", "--name-only", f"{base_commit}..{head_commit}")
    if result.returncode:
        return {"status": "unavailable", "reason": result.stderr.strip() or "Git could not compare commits."}
    return {"status": "ready", "files": [line for line in result.stdout.splitlines() if line]}


def unresolved_conflicts(path: str | Path) -> dict:
    result = _git_result(path, "diff", "--name-only", "--diff-filter=U")
    if result.returncode:
        return {"status": "unavailable", "reason": result.stderr.strip() or "Git status is unavailable."}
    files = [line for line in result.stdout.splitlines() if line]
    return {"status": "conflicts_present" if files else "clean", "files": files}


def inspect_worktree(path: str | Path, base_commit: str | None = None) -> dict:
    root = _git(path, "rev-parse", "--show-toplevel")
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current") or "(detached)"
    status = _git(root, "status", "--short")
    commits = []
    if base_commit and base_commit != head:
        lines = _git(root, "log", "--format=%H%x1f%s", f"{base_commit}..{head}")
        commits = [{"commit": line.split("\x1f", 1)[0], "message": line.split("\x1f", 1)[1]} for line in lines.splitlines() if "\x1f" in line]
    return {
        "worktree_path": str(Path(root).resolve()),
        "branch": branch,
        "head_commit": head,
        "base_commit": base_commit or head,
        "commits": commits,
        "changed_files": _git(root, "diff", "--name-only", base_commit or "HEAD", "HEAD").splitlines() if base_commit else [],
        "has_uncommitted_changes": bool(status),
        "uncommitted_files": [line[3:] for line in status.splitlines() if len(line) > 3],
    }
