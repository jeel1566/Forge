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


if __name__ == "__main__":
    unittest.main()
