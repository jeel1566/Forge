import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.app.coordination import coordination_status
from backend.app.store import Store
from backend.app.worktree import branch_state, discover_worktrees, parse_worktree_porcelain, unresolved_conflicts


def git(path: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(path), *arguments], text=True, capture_output=True, check=check)


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-b", "main")
        git(self.root, "config", "user.email", "forge@example.test")
        git(self.root, "config", "user.name", "Forge Test")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        git(self.root, "add", "README.md")
        git(self.root, "commit", "-m", "base")
        self.base = git(self.root, "rev-parse", "HEAD").stdout.strip()
        self.first = Path(self.temporary_directory.name) / "first"
        self.second = Path(self.temporary_directory.name) / "second"
        git(self.root, "worktree", "add", "-b", "feature/first", str(self.first), self.base)
        git(self.root, "worktree", "add", "-b", "feature/second", str(self.second), self.base)
        self.store = Store(Path(self.temporary_directory.name) / "forge.sqlite3")
        self.store.register_repository("repo", str(self.root), branch="main")

    def tearDown(self):
        self.store.close()
        self.temporary_directory.cleanup()

    def commit(self, worktree: Path, filename: str, content: str):
        (worktree / filename).write_text(content, encoding="utf-8")
        git(worktree, "add", filename)
        git(worktree, "commit", "-m", f"change {filename}")

    def start_sessions(self):
        self.store.start_work_session("repo", "codex", str(self.first), "feature/first", self.base)
        self.store.start_work_session("repo", "codex", str(self.second), "feature/second", self.base)

    def test_parses_porcelain_worktrees_and_detached_head(self):
        parsed = parse_worktree_porcelain("worktree C:/repo\nHEAD abc\nbranch refs/heads/main\n\nworktree C:/detached\nHEAD def\ndetached\n")
        self.assertEqual("main", parsed[0]["branch"])
        self.assertTrue(parsed[1]["is_detached"])
        git(self.second, "checkout", "--detach")
        discovered = discover_worktrees(self.root)["worktrees"]
        self.assertTrue(next(item for item in discovered if item["worktree_path"] == str(self.second.resolve()))["is_detached"])

    def test_detects_possible_overlap_and_no_overlap_from_real_worktrees(self):
        self.commit(self.first, "shared.py", "first\n")
        self.commit(self.second, "shared.py", "second\n")
        self.start_sessions()
        result = coordination_status(self.store, "repo")
        self.assertEqual("possible_overlap", result["overlaps"][0]["status"])
        self.assertEqual(["shared.py"], result["overlaps"][0]["files"])
        self.assertTrue(result["worktrees"])

    def test_reports_no_overlap_for_distinct_files(self):
        self.commit(self.first, "first.py", "first\n")
        self.commit(self.second, "second.py", "second\n")
        self.start_sessions()
        self.assertEqual([], coordination_status(self.store, "repo")["overlaps"])

    def test_missing_directory_is_unavailable(self):
        self.store.register_repository("missing", str(Path(self.temporary_directory.name) / "missing"))
        result = coordination_status(self.store, "missing")
        self.assertEqual("unavailable", result["status"])

    def test_non_git_directory_is_unavailable(self):
        directory = Path(self.temporary_directory.name) / "not-a-repository"
        directory.mkdir()
        self.store.register_repository("non-git", str(directory))
        result = coordination_status(self.store, "non-git")
        self.assertEqual("unavailable", result["status"])

    def test_detects_unresolved_merge_conflict(self):
        self.commit(self.first, "conflict.txt", "first\n")
        git(self.root, "checkout", "-b", "conflict-source", self.base)
        (self.root / "conflict.txt").write_text("source\n", encoding="utf-8")
        git(self.root, "add", "conflict.txt")
        git(self.root, "commit", "-m", "source conflict")
        merged = git(self.first, "merge", "conflict-source", check=False)
        self.assertNotEqual(0, merged.returncode)
        self.assertEqual("conflicts_present", unresolved_conflicts(self.first)["status"])

    def test_calculates_ahead_behind_and_diverged(self):
        self.commit(self.first, "first.py", "first\n")
        self.assertEqual("ahead", branch_state(self.first, "main")["status"])
        (self.root / "main.py").write_text("main\n", encoding="utf-8")
        git(self.root, "add", "main.py")
        git(self.root, "commit", "-m", "main change")
        self.assertEqual("diverged", branch_state(self.first, "main")["status"])
        self.assertEqual("behind", branch_state(self.second, "main")["status"])


if __name__ == "__main__":
    unittest.main()
