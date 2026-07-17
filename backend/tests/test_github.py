import unittest

from backend.app.github import GitHubError, repository_slug


class GitHubRepositoryTests(unittest.TestCase):
    def test_parses_https_and_ssh_origins(self):
        self.assertEqual("openai/forge", repository_slug("https://github.com/openai/forge.git"))
        self.assertEqual("openai/forge", repository_slug("git@github.com:openai/forge.git"))

    def test_rejects_non_github_origin(self):
        with self.assertRaises(GitHubError):
            repository_slug("https://example.com/openai/forge.git")
