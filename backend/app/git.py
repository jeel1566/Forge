import subprocess
from hashlib import sha256
from pathlib import Path

from .store import Store
from .worktree import git_common_dir


def git_output(repository: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout.strip()


def optional_git_output(repository: Path, *arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(repository), *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else ""


def workspace_id_for_repository(path: str | Path) -> str:
    repository = Path(path).resolve()
    remote_url = optional_git_output(repository, "config", "--get", "remote.origin.url")
    try:
        local_identity = git_common_dir(repository)
    except ValueError:
        local_identity = str(repository)
    identity = remote_url.rstrip("/").removesuffix(".git").lower() or local_identity.lower()
    return f"repo-{sha256(identity.encode()).hexdigest()[:12]}"


def ingest_repository(store: Store, workspace_id: str, path: str | Path) -> dict:
    repository = Path(path).resolve()
    try:
        head = git_output(repository, "rev-parse", "HEAD")
        branch = git_output(repository, "branch", "--show-current") or "detached"
        remote_url = optional_git_output(repository, "config", "--get", "remote.origin.url")
        common_dir = git_common_dir(repository)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Could not read Git history from {repository}") from error
    previous = store.repository(workspace_id)
    start = previous["last_ingested_commit"] if previous else None
    if start:
        try:
            subprocess.run(["git", "-C", str(repository), "merge-base", "--is-ancestor", start, head], capture_output=True, check=True)
            revision_range = f"{start}..{head}"
        except subprocess.CalledProcessError:
            revision_range = head
    else:
        revision_range = head
    commits = git_output(repository, "log", "--reverse", "--format=%H%x1f%an%x1f%aI%x1f%s%x1e", revision_range)
    store.register_repository(workspace_id, str(repository), remote_url or None, branch, common_dir)
    imported = 0
    for record in commits.split("\x1e"):
        if not record.strip():
            continue
        commit, author, occurred_at, subject = record.strip().split("\x1f", 3)
        if store.has_evidence(workspace_id, "git_commit", commit):
            continue
        files = [item for item in git_output(repository, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines() if item]
        summary = f"Commit {commit[:12]} changed {len(files)} file(s)."
        store.create_evidence(workspace_id, "git_commit", subject, summary, subject, commit, {"commit": commit, "repository": str(repository), "author": author, "occurred_at": occurred_at, "branch": branch, "files": files})
        imported += 1
    store.update_repository_head(workspace_id, head)
    return {"workspace_id": workspace_id, "repository": str(repository), "branch": branch, "commits_seen": len([item for item in commits.split("\x1e") if item.strip()]), "commits_imported": imported}
