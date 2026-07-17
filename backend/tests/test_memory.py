import tempfile
import unittest
from pathlib import Path

from backend.app.store import Store


class MemoryProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "forge.sqlite3"
        self.stores = []

    def store(self):
        instance = Store(self.database)
        self.stores.append(instance)
        return instance

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.temporary_directory.cleanup()

    def test_pending_decisions_do_not_appear_in_memory(self):
        store = self.store()
        decision = store.create_pending("default", "Run focused tests before merging.", "process", "Tests caught the regression.")
        self.assertEqual([], store.context("default")["memory"])
        store.review(decision["id"], "confirmed", "Run the focused regression tests before merging.")
        memory = store.context("default")["memory"]
        self.assertEqual(1, len(memory))
        self.assertEqual("Run the focused regression tests before merging.", memory[0]["statement"])

    def test_decisions_survive_restart_and_rejections_preserve_evidence(self):
        store = self.store()
        decision = store.create_pending("default", "Keep changes focused.", "process", "The review requested a smaller patch.")
        store.review(decision["id"], "rejected")
        restarted = self.store()
        saved = restarted.get_decision(decision["id"])
        self.assertEqual("rejected", saved["review_status"])
        self.assertEqual("The review requested a smaller patch.", saved["evidence_quote"])

    def test_github_token_is_protected_and_deletable(self):
        store = self.store()
        saved = store.save_github_token("token-value")
        self.assertTrue(saved["token_saved"])
        self.assertNotIn("token-value", str(saved))
        self.assertEqual("token-value", store.github_token())
        deleted = store.delete_github_credentials()
        self.assertFalse(deleted["token_saved"])

    def test_migrations_and_evidence_spans_are_persistent(self):
        store = self.store()
        store.create_evidence("default", "git_commit", "Add storage", "diff --git", "Add storage", "commit-1", {"files": ["backend/app/store.py"]}, ["@@ -1,1 +1,2 @@"])
        evidence = store.list_evidence("default")[0]
        self.assertEqual(2, len(store.get_evidence(evidence["id"])["spans"]))
        self.assertEqual(1, store.evidence_count("default", "git_commit"))
        self.assertEqual(5, store.db.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"])
        self.assertTrue(store.integrity_check()["ok"])

    def test_repository_registry_lists_multiple_workspaces(self):
        store = self.store()
        store.register_repository("repo-one", ".", "https://github.com/example/one.git", "main")
        store.register_repository("repo-two", "..", "https://github.com/example/two.git", "main")
        self.assertEqual(["repo-one", "repo-two"], [item["workspace_id"] for item in store.repositories()])

    def test_reflections_are_not_memory_and_memory_can_be_archived(self):
        store = self.store()
        decision = store.create_pending("default", "Keep changes focused.", "process", "The review requested a smaller patch.")
        store.review(decision["id"], "confirmed")
        reflection = store.create_reflection("default", "Review the failing test before editing.", "The error identifies the failing assertion.")
        self.assertEqual([], [item for item in store.context("default")["memory"] if item["statement"] == reflection["statement"]])
        self.assertTrue(store.archive_memory(store.context("default")["memory"][0]["memory_entry_id"]))
        self.assertEqual([], store.context("default")["memory"])
        self.assertEqual(1, len(store.history("default")["reflections"]))

    def test_guardrail_requires_two_confirmations_and_returns_a_diff(self):
        store = self.store()
        self.assertEqual("insufficient_data", store.propose_agents_guardrail("default", "Run focused tests.", "")["status"])
        for _ in range(2):
            decision = store.create_pending("default", "Run focused tests.", "process", "Focused tests caught the regression.")
            store.review(decision["id"], "confirmed")
        proposal = store.propose_agents_guardrail("default", "Run focused tests.", "# Repository instructions\n")
        self.assertEqual("pending_developer_approval", proposal["status"])
        self.assertIn("+## Confirmed Guardrails", proposal["diff"])


if __name__ == "__main__":
    unittest.main()
