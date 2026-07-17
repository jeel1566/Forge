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

    def test_github_credentials_are_masked_and_deletable(self):
        store = self.store()
        saved = store.save_github_credentials("token-value", "secret-value")
        self.assertTrue(saved["token_saved"])
        self.assertTrue(saved["webhook_secret_saved"])
        self.assertNotIn("token-value", str(saved))
        deleted = store.delete_github_credentials()
        self.assertFalse(deleted["token_saved"])


if __name__ == "__main__":
    unittest.main()
