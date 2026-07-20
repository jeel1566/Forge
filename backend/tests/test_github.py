import tempfile
import unittest
import json
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from backend.app.git import ingest_repository, workspace_id_for_repository
from backend.app.github import GitHubError, GitHubRateLimitError, GitHubResponse, poll_github, repository_slug, request_json
from backend.app.store import Store
from backend.app.worker import run_due_github_polls


class GitHubRepositoryTests(unittest.TestCase):
    def test_parses_https_and_ssh_origins(self):
        self.assertEqual("openai/forge", repository_slug("https://github.com/openai/forge.git"))
        self.assertEqual("openai/forge", repository_slug("git@github.com:openai/forge.git"))

    def test_rejects_non_github_origin(self):
        with self.assertRaises(GitHubError):
            repository_slug("https://example.com/openai/forge.git")

    def test_workspace_id_is_stable_for_a_path(self):
        self.assertEqual(workspace_id_for_repository("."), workspace_id_for_repository("."))

    def test_git_import_collects_files_from_merge_commits(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Store(Path(temporary_directory) / "forge.sqlite3")
            repository = Path(temporary_directory) / "repository"
            repository.mkdir()
            calls = []

            def output(_repository, *arguments):
                calls.append(arguments)
                if arguments == ("rev-parse", "HEAD"):
                    return "merge-commit"
                if arguments == ("branch", "--show-current"):
                    return "main"
                if arguments[0] == "log":
                    return "merge-commit\x1fauthor\x1f2026-07-20T00:00:00Z\x1fMerge feature\x1e"
                if arguments[0] == "diff-tree":
                    return "backend/app/store.py"
                raise AssertionError(arguments)

            try:
                with patch("backend.app.git.git_output", side_effect=output), patch("backend.app.git.optional_git_output", return_value=""), patch("backend.app.git.git_common_dir", return_value=str(repository / ".git")):
                    ingest_repository(store, "default", repository)
                self.assertIn(("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "merge-commit"), calls)
            finally:
                store.close()


class GitHubPollingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temporary_directory.name) / "forge.sqlite3")
        self.store.register_repository("repo", ".", "https://github.com/openai/forge.git", "main")
        self.store.save_github_token("test-token")

    def tearDown(self):
        self.store.close()
        self.temporary_directory.cleanup()

    def test_poll_imports_inline_review_comments(self):
        def github_response(path, _token):
            if path.startswith("/repos/openai/forge/pulls?"):
                return [{"number": 7, "updated_at": "2026-07-17T00:00:00Z", "body": "PR body", "title": "Improve polling", "state": "open", "html_url": "https://github.com/openai/forge/pull/7", "user": {"login": "octo"}}]
            if path.endswith("/reviews?per_page=100"):
                return [{"id": 3, "body": "Looks good", "state": "APPROVED", "submitted_at": "2026-07-17T00:00:00Z", "user": {"login": "reviewer"}}]
            if path.endswith("/comments?per_page=100"):
                return [{"id": 4, "body": "Handle retries", "path": "backend/app/github.py", "line": 42, "side": "RIGHT", "commit_id": "abc", "updated_at": "2026-07-17T00:00:00Z", "html_url": "https://github.com/openai/forge/pull/7#discussion_r4", "user": {"login": "reviewer"}}]
            raise AssertionError(path)
        with patch("backend.app.github.request_json", side_effect=github_response):
            result = poll_github(self.store, "repo")
        self.assertEqual(1, result["comments_imported"])
        self.assertEqual(1, self.store.evidence_count("repo", "github_review_comment"))

    def test_scheduled_poll_recovers_after_a_failure(self):
        self.store.configure_github_polling("repo", True, 60)
        with patch("backend.app.worker.poll_github", side_effect=GitHubError("GitHub is unreachable.")):
            result = run_due_github_polls(self.store, "9999-01-01T00:00:00+00:00")
        self.assertEqual("unreachable", result[0]["status"])
        failed = self.store.github_poll_status("repo")
        self.assertEqual(1, failed["consecutive_failures"])
        self.assertEqual("GitHub is unreachable.", failed["last_error"])
        self.store.db.execute("UPDATE github_poll_settings SET next_poll_at='1970-01-01T00:00:00+00:00' WHERE workspace_id='repo'")
        self.store.db.commit()
        with patch("backend.app.worker.poll_github", return_value={"pulls_imported": 0}):
            result = run_due_github_polls(self.store, "9999-01-01T00:00:00+00:00")
        self.assertEqual("healthy", result[0]["status"])
        recovered = self.store.github_poll_status("repo")
        self.assertEqual(0, recovered["consecutive_failures"])
        self.assertIsNone(recovered["last_error"])

    def test_scheduler_records_unexpected_failures_without_stopping(self):
        self.store.configure_github_polling("repo", True, 60)
        with patch("backend.app.worker.poll_github", side_effect=RuntimeError("database busy")):
            result = run_due_github_polls(self.store, "9999-01-01T00:00:00+00:00")
        self.assertEqual("internal_error", result[0]["status"])
        self.assertEqual("internal_error", self.store.github_poll_status("repo")["health"])

    def test_multi_page_import_is_idempotent_and_records_cursor(self):
        pull_one = {"number": 1, "updated_at": "2026-07-17T00:00:00Z", "title": "One", "state": "closed", "html_url": "https://example/1", "user": {"login": "octo"}, "head": {"sha": "one"}}
        pull_two = {"number": 2, "updated_at": "2026-07-18T00:00:00Z", "title": "Two", "state": "open", "html_url": "https://example/2", "user": {"login": "octo"}, "head": {"sha": "two"}}
        def response(path, _token, _etag=None):
            if "pulls?" in path:
                return GitHubResponse([pull_one], {"http_status": 200, "etag": "pulls"}, "/repos/openai/forge/pulls?page=2") if "page=2" not in path else GitHubResponse([pull_two], {"http_status": 200}, None)
            return GitHubResponse([], {"http_status": 200}, None)
        with patch("backend.app.github.request_json", side_effect=response):
            first = poll_github(self.store, "repo", max_pages=10)
        with patch("backend.app.github.request_json", side_effect=response):
            second = poll_github(self.store, "repo", max_pages=10)
        self.assertEqual(2, first["pulls_imported"])
        self.assertEqual(0, second["pulls_imported"])
        self.store.record_github_poll_success("repo", first)
        self.assertEqual("2026-07-18T00:00:00Z", self.store.github_poll_status("repo")["pull_cursor"])

    def test_partial_sync_stops_at_configured_boundary(self):
        pull = {"number": 1, "updated_at": "2026-07-17T00:00:00Z", "title": "One", "state": "open", "html_url": "https://example/1", "user": {"login": "octo"}}
        with patch("backend.app.github.request_json", return_value=GitHubResponse([pull], {"http_status": 200}, "/repos/openai/forge/pulls?page=2")):
            result = poll_github(self.store, "repo", max_pages=1)
        self.assertTrue(result["partial"])
        self.assertIsNone(result["pull_cursor"])

    def test_partial_sync_resumes_a_nested_collection_from_its_checkpoint(self):
        pull = {"number": 1, "updated_at": "2026-07-17T00:00:00Z", "title": "One", "state": "open", "html_url": "https://example/1", "user": {"login": "octo"}}
        calls = []

        def response(path, _token, _etag=None):
            calls.append(path)
            if "pulls?" in path:
                return GitHubResponse([pull], {"http_status": 200}, None)
            if "reviews?page=2" in path:
                return GitHubResponse([], {"http_status": 200}, None)
            if path.endswith("/reviews?per_page=100"):
                return GitHubResponse([], {"http_status": 200}, "/repos/openai/forge/pulls/1/reviews?page=2")
            return GitHubResponse([], {"http_status": 200}, None)

        with patch("backend.app.github.request_json", side_effect=response):
            self.assertTrue(poll_github(self.store, "repo", max_pages=2)["partial"])
            calls.clear()
            poll_github(self.store, "repo", max_pages=10)
        self.assertIn("/repos/openai/forge/pulls/1/reviews?page=2", calls)

    def test_github_payloads_and_exports_exclude_raw_response_bodies(self):
        pull = {"number": 1, "updated_at": "2026-07-17T00:00:00Z", "title": "One", "body": "private payload body", "state": "open", "html_url": "https://example/1", "user": {"login": "octo"}}
        def response(path, _token, _etag=None):
            return GitHubResponse([pull], {"http_status": 200}, None) if "pulls?" in path else GitHubResponse([], {"http_status": 200}, None)

        with patch("backend.app.github.request_json", side_effect=response):
            poll_github(self.store, "repo")
        evidence = self.store.get_evidence(self.store.list_evidence("repo", "github_pull_request")[0]["id"])
        self.assertNotIn("private payload body", evidence["content"])
        export_path = Path(self.temporary_directory.name) / "forge.json"
        self.store.export(export_path)
        self.assertNotIn("content", json.loads(export_path.read_text(encoding="utf-8"))["evidence_items"][0])

    def test_rate_limit_headers_and_retry_after_are_classified(self):
        headers = Message()
        headers["X-RateLimit-Remaining"] = "0"
        headers["X-RateLimit-Reset"] = "1780000000"
        headers["Retry-After"] = "12"
        error = HTTPError("https://api.github.com/test", 429, "slow down", headers, None)
        with patch("backend.app.github.urlopen", side_effect=error):
            with self.assertRaises(GitHubRateLimitError) as raised:
                request_json("/test", "secret-token")
        self.assertEqual(12, raised.exception.retry_after_seconds)
        self.assertIsNotNone(raised.exception.rate_limit_reset_at)

    def test_concurrent_poll_is_prevented_and_state_survives_restart(self):
        self.store.configure_github_polling("repo", True, 60)
        self.assertTrue(self.store.begin_github_poll("repo"))
        self.assertFalse(self.store.begin_github_poll("repo"))
        self.store.finish_github_poll("repo")
        self.store.record_github_poll_failure("repo", "offline", "unreachable", retry_after_seconds=30)
        path = self.store.path
        self.store.close()
        self.store = Store(path)
        status = self.store.github_poll_status("repo")
        self.assertEqual("unreachable", status["health"])
        self.assertIsNotNone(status["next_poll_at"])

    def test_telemetry_retention_is_bounded(self):
        for _ in range(505):
            self.store.record_github_event("repo", "poll", "healthy")
        count = self.store.db.execute("SELECT COUNT(*) FROM github_sync_events WHERE workspace_id='repo'").fetchone()[0]
        self.assertLessEqual(count, 500)
