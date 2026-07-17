import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .store import Store

API_ROOT = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def repository_slug(remote_url: str) -> str:
    match = re.search(r"github\.com[/:]([^/]+)/(.+?)(?:\.git)?$", remote_url)
    if not match:
        raise GitHubError("The registered Git remote is not a GitHub repository.")
    return f"{match.group(1)}/{match.group(2)}"


def request_json(path: str, token: str):
    request = Request(f"{API_ROOT}{path}", headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "Forge-local-memory"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise GitHubError(f"GitHub returned HTTP {error.code}.") from error
    except URLError as error:
        raise GitHubError("GitHub is unreachable. Local Git evidence remains available.") from error


def poll_github(store: Store, workspace_id: str):
    repository = store.repository(workspace_id)
    if not repository or not repository["remote_url"]:
        raise GitHubError("Register a repository with a GitHub origin before polling.")
    token = store.github_token()
    if not token:
        raise PermissionError("Save a GitHub fine-grained token before polling.")
    slug = repository_slug(repository["remote_url"])
    try:
        pulls = request_json(f"/repos/{slug}/pulls?state=all&sort=updated&direction=desc&per_page=20", token)
        imported_pulls = imported_reviews = 0
        for pull in pulls:
            pull_number = pull["number"]
            pull_external_id = f"github-pr:{pull_number}:{pull['updated_at']}"
            if not store.has_evidence(workspace_id, "github_pull_request", pull_external_id):
                quote = pull.get("body") or pull["title"]
                store.create_evidence(workspace_id, "github_pull_request", f"PR #{pull_number}: {pull['title']}", json.dumps(pull, indent=2), quote, pull_external_id, {"number": pull_number, "state": pull["state"], "updated_at": pull["updated_at"], "url": pull["html_url"], "author": pull["user"]["login"]})
                imported_pulls += 1
            reviews = request_json(f"/repos/{slug}/pulls/{pull_number}/reviews?per_page=100", token)
            for review in reviews:
                review_external_id = f"github-review:{review['id']}"
                if store.has_evidence(workspace_id, "github_review", review_external_id):
                    continue
                quote = review.get("body") or review["state"]
                store.create_evidence(workspace_id, "github_review", f"PR #{pull_number} review: {review['state']}", json.dumps(review, indent=2), quote, review_external_id, {"pull_number": pull_number, "state": review["state"], "submitted_at": review.get("submitted_at"), "author": review["user"]["login"]})
                imported_reviews += 1
    except GitHubError as error:
        store.set_connector_state("github", "offline", str(error))
        raise
    total_pulls = store.evidence_count(workspace_id, "github_pull_request")
    total_reviews = store.evidence_count(workspace_id, "github_review")
    store.set_connector_state("github", "connected", f"Polled {slug}: {total_pulls} PRs ({imported_pulls} new), {total_reviews} reviews ({imported_reviews} new).")
    return {"repository": slug, "pulls_seen": len(pulls), "pulls_imported": imported_pulls, "reviews_imported": imported_reviews, "pulls_total": total_pulls, "reviews_total": total_reviews}
