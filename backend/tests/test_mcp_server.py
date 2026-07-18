import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import mcp_server
from backend.app.store import Store


class MCPServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "forge.sqlite3"
        store = Store(self.database)
        store.close()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_offline_database_fails_without_creating_a_new_database(self):
        missing_database = Path(self.temporary_directory.name) / "missing" / "forge.sqlite3"
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(missing_database)}):
            with self.assertRaisesRegex(RuntimeError, "Forge is offline"):
                mcp_server.forge_get_project_context()
        self.assertFalse(missing_database.exists())

    def test_offline_coordination_mcp_fails_without_creating_a_database(self):
        missing_database = Path(self.temporary_directory.name) / "missing-coordination" / "forge.sqlite3"
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(missing_database)}):
            with self.assertRaisesRegex(RuntimeError, "Forge is offline"):
                mcp_server.forge_get_coordination_status()
        self.assertFalse(missing_database.exists())

    def test_pending_mcp_decision_stores_only_explicit_input(self):
        quote = "The focused test failed at the changed boundary."
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            decision = mcp_server.forge_record_decision("Run the focused test before merging.", quote)
            context = mcp_server.forge_get_project_context()
        self.assertEqual("pending", decision["review_status"])
        self.assertEqual([], context["memory"])
        store = Store(self.database)
        try:
            self.assertEqual(quote, store.get_decision(decision["id"])["evidence_quote"])
        finally:
            store.close()

    def test_github_status_is_offline_safe_and_never_exposes_token(self):
        store = Store(self.database)
        store.register_repository("default", ".", "https://github.com/openai/forge.git", "main")
        store.save_github_token("never-return-this-token")
        store.record_github_poll_failure("default", "offline", "unreachable")
        store.close()
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            status = mcp_server.forge_get_github_sync_status()
        self.assertEqual("unreachable", status["health"])
        self.assertNotIn("never-return-this-token", str(status))


if __name__ == "__main__":
    unittest.main()
