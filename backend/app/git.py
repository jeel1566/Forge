import subprocess
from pathlib import Path

from .store import Store


def ingest_repository(store: Store, workspace_id: str, path: str | Path, limit: int = 50) -> dict:
    repository = Path(path).resolve()
    try:
        commits = subprocess.run(["git", "-C", str(repository), "log", f"--max-count={limit}", "--format=%H%x1f%s%x1e"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Could not read Git history from {repository}") from error
    store.register_repository(workspace_id, str(repository))
    imported = 0
    for record in commits.split("\x1e"):
        if not record.strip():
            continue
        commit, subject = record.strip().split("\x1f", 1)
        if store.has_evidence(workspace_id, "git_commit", commit):
            continue
        diff = subprocess.run(["git", "-C", str(repository), "show", "--format=fuller", "--no-ext-diff", commit], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout
        store.create_evidence(workspace_id, "git_commit", subject, diff, subject, commit, {"commit": commit, "repository": str(repository)})
        imported += 1
    return {"workspace_id": workspace_id, "repository": str(repository), "commits_seen": len([item for item in commits.split("\x1e") if item.strip()]), "commits_imported": imported}
