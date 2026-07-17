import unittest

from backend.app.git import workspace_id_for_repository
from backend.app.github import GitHubError, repository_slug


class GitHubRepositoryTests(unittest.TestCase):
    def test_parses_https_and_ssh_origins(self):
        self.assertEqual("openai/forge", repository_slug("https://github.com/openai/forge.git"))
        self.assertEqual("openai/forge", repository_slug("git@github.com:openai/forge.git"))

    def test_rejects_non_github_origin(self):
        with self.assertRaises(GitHubError):
            repository_slug("https://example.com/openai/forge.git")

    def test_workspace_id_is_stable_for_a_path(self):
        self.assertEqual(workspace_id_for_repository("."), workspace_id_for_repository("."))
