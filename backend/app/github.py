import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .store import Store

API_ROOT = "https://api.github.com"


class GitHubError(RuntimeError):
    kind = "unreachable"
    retry_after_seconds: int | None = None
    rate_limit_reset_at: str | None = None


class GitHubAuthenticationError(GitHubError):
    kind = "authentication_failed"


class GitHubAuthorizationError(GitHubError):
    kind = "authorization_failed"


class GitHubRateLimitError(GitHubError):
    kind = "rate_limited"


class GitHubMalformedResponseError(GitHubError):
    kind = "malformed_response"


class GitHubConcurrentPollError(GitHubError):
    kind = "poll_in_progress"


@dataclass
class GitHubResponse:
    data: list
    metadata: dict
    next_path: str | None


def repository_slug(remote_url: str) -> str:
    match = re.search(r"github\.com[/:]([^/]+)/(.+?)(?:\.git)?$", remote_url)
    if not match:
        raise GitHubError("The registered Git remote is not a GitHub repository.")
    return f"{match.group(1)}/{match.group(2)}"


def _integer_header(headers, name: str) -> int | None:
    try:
        value = headers.get(name)
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _reset_time(headers) -> str | None:
    seconds = _integer_header(headers, "X-RateLimit-Reset")
    return datetime.fromtimestamp(seconds, UTC).isoformat() if seconds else None


def _retry_after(headers) -> int | None:
    return _integer_header(headers, "Retry-After")


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for link in link_header.split(","):
        if 'rel="next"' in link:
            url = link[link.find("<") + 1:link.find(">")]
            parsed = urlsplit(url)
            return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    return None


def _metadata(headers, status: int, request_ms: int) -> dict:
    return {
        "http_status": status,
        "request_ms": request_ms,
        "rate_limit_remaining": _integer_header(headers, "X-RateLimit-Remaining"),
        "rate_limit_limit": _integer_header(headers, "X-RateLimit-Limit"),
        "rate_limit_reset_at": _reset_time(headers),
        "retry_after_at": None,
        "etag": headers.get("ETag"),
    }


def request_json(path: str, token: str, etag: str | None = None) -> GitHubResponse:
    headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "Forge-local-memory"}
    if etag:
        headers["If-None-Match"] = etag
    request = Request(f"{API_ROOT}{path}", headers=headers)
    started = time.monotonic()
    try:
        with urlopen(request, timeout=15) as response:
            request_ms = int((time.monotonic() - started) * 1000)
            metadata = _metadata(response.headers, response.status, request_ms)
            try:
                data = json.loads(response.read())
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise GitHubMalformedResponseError("GitHub returned a malformed response.") from error
            if not isinstance(data, list):
                raise GitHubMalformedResponseError("GitHub returned an unexpected collection response.")
            return GitHubResponse(data, metadata, _next_link(response.headers.get("Link")))
    except HTTPError as error:
        request_ms = int((time.monotonic() - started) * 1000)
        metadata = _metadata(error.headers, error.code, request_ms)
        retry = _retry_after(error.headers)
        if error.code == 304:
            return GitHubResponse([], metadata, None)
        if error.code == 401:
            failure = GitHubAuthenticationError("GitHub authentication failed. Update the local token.")
        elif error.code in (403, 404) and metadata["rate_limit_remaining"] == 0:
            failure = GitHubRateLimitError("GitHub rate limit reached.")
        elif error.code in (403, 404):
            failure = GitHubAuthorizationError("GitHub authorization failed. Check repository access and token permissions.")
        elif error.code in (429, 503):
            failure = GitHubRateLimitError("GitHub requested a retry later.")
        else:
            failure = GitHubError(f"GitHub returned HTTP {error.code}.")
        failure.retry_after_seconds = retry
        failure.rate_limit_reset_at = metadata["rate_limit_reset_at"]
        raise failure from error
    except URLError as error:
        raise GitHubError("GitHub is unreachable. Local Git evidence remains available.") from error


def _response(value) -> GitHubResponse:
    """Accept legacy test fakes while production callers use GitHubResponse."""
    if isinstance(value, GitHubResponse):
        return value
    if isinstance(value, list):
        return GitHubResponse(value, {}, None)
    raise GitHubMalformedResponseError("GitHub returned an unexpected collection response.")


def _limits() -> tuple[int, int, float]:
    return (max(1, int(os.getenv("FORGE_GITHUB_MAX_PAGES", "10"))), max(1, int(os.getenv("FORGE_GITHUB_MAX_ITEMS", "1000"))), max(1.0, float(os.getenv("FORGE_GITHUB_MAX_SECONDS", "45"))))


def _pull_evidence(store: Store, workspace_id: str, pull: dict) -> bool:
    number = pull.get("number")
    updated_at = pull.get("updated_at")
    if not isinstance(number, int) or not updated_at or not pull.get("title"):
        raise GitHubMalformedResponseError("GitHub returned a pull request without required fields.")
    external_id = f"github-pr:{number}:{updated_at}"
    if store.has_evidence(workspace_id, "github_pull_request", external_id):
        return False
    store.create_evidence(workspace_id, "github_pull_request", f"PR #{number}: {pull['title']}", json.dumps(pull, indent=2), pull.get("body") or pull["title"], external_id, {"number": number, "state": pull.get("state"), "updated_at": updated_at, "url": pull.get("html_url"), "author": pull.get("user", {}).get("login"), "merged_at": pull.get("merged_at"), "head_sha": pull.get("head", {}).get("sha")})
    return True


def poll_github(store: Store, workspace_id: str, max_pages: int | None = None, max_items: int | None = None, max_seconds: float | None = None):
    repository = store.repository(workspace_id)
    if not repository or not repository["remote_url"]:
        raise GitHubError("Register a repository with a GitHub origin before polling.")
    token = store.github_token()
    if not token:
        raise GitHubAuthenticationError("Save a GitHub fine-grained token before polling.")
    if not store.begin_github_poll(workspace_id):
        raise GitHubConcurrentPollError("A GitHub poll is already running for this repository.")
    try:
        slug = repository_slug(repository["remote_url"])
        default_pages, default_items, default_seconds = _limits()
        page_limit, item_limit, seconds_limit = max_pages or default_pages, max_items or default_items, max_seconds or default_seconds
        started = time.monotonic()
        pages = items = imported_pulls = imported_reviews = imported_comments = 0
        partial = False
        latest_cursor = None

        def bounded() -> bool:
            return pages >= page_limit or items >= item_limit or time.monotonic() - started >= seconds_limit

        def fetch_pages(path: str, key: str):
            nonlocal pages, items, partial
            next_path = path
            first = True
            while next_path:
                if bounded():
                    partial = True
                    return
                etag = store.github_etag(workspace_id, key) if first else None
                response = _response(request_json(next_path, token, etag) if etag else request_json(next_path, token))
                first = False
                pages += 1
                items += len(response.data)
                store.record_github_response(workspace_id, key, response.metadata)
                yield from response.data
                next_path = response.next_path
                if next_path and bounded():
                    partial = True
                    return

        for pull in fetch_pages(f"/repos/{slug}/pulls?state=all&sort=updated&direction=desc&per_page=100", "pulls"):
            if _pull_evidence(store, workspace_id, pull):
                imported_pulls += 1
            latest_cursor = max(latest_cursor or "", pull.get("updated_at") or "")
            number = pull["number"]
            for review in fetch_pages(f"/repos/{slug}/pulls/{number}/reviews?per_page=100", f"reviews:{number}"):
                review_id = review.get("id")
                if review_id is None:
                    raise GitHubMalformedResponseError("GitHub returned a review without an id.")
                external_id = f"github-review:{review_id}"
                if not store.has_evidence(workspace_id, "github_review", external_id):
                    store.create_evidence(workspace_id, "github_review", f"PR #{number} review: {review.get('state', 'unknown')}", json.dumps(review, indent=2), review.get("body") or review.get("state", "Review with no body."), external_id, {"pull_number": number, "state": review.get("state"), "submitted_at": review.get("submitted_at"), "author": review.get("user", {}).get("login")})
                    imported_reviews += 1
            for comment in fetch_pages(f"/repos/{slug}/pulls/{number}/comments?per_page=100", f"comments:{number}"):
                comment_id = comment.get("id")
                if comment_id is None:
                    raise GitHubMalformedResponseError("GitHub returned a review comment without an id.")
                external_id = f"github-review-comment:{comment_id}:{comment.get('updated_at', '')}"
                if not store.has_evidence(workspace_id, "github_review_comment", external_id):
                    store.create_evidence(workspace_id, "github_review_comment", f"PR #{number} comment on {comment.get('path') or 'unknown file'}", json.dumps(comment, indent=2), comment.get("body") or "Review comment with no body.", external_id, {"pull_number": number, "path": comment.get("path"), "line": comment.get("line"), "side": comment.get("side"), "commit_id": comment.get("commit_id"), "updated_at": comment.get("updated_at"), "url": comment.get("html_url"), "author": comment.get("user", {}).get("login")})
                    imported_comments += 1
            if partial:
                break
        totals = {kind: store.evidence_count(workspace_id, kind) for kind in ("github_pull_request", "github_review", "github_review_comment")}
        return {"repository": slug, "pulls_imported": imported_pulls, "reviews_imported": imported_reviews, "comments_imported": imported_comments, "pulls_total": totals["github_pull_request"], "reviews_total": totals["github_review"], "comments_total": totals["github_review_comment"], "pages": pages, "items": items, "partial": partial, "pull_cursor": None if partial else latest_cursor}
    finally:
        store.finish_github_poll(workspace_id)
