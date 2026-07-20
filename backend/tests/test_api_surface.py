import os
import tempfile
import unittest
from pathlib import Path


class ApiSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.previous_database = os.environ.get("FORGE_DB_PATH")
        os.environ["FORGE_DB_PATH"] = str(Path(cls.temporary_directory.name) / "forge.sqlite3")
        from backend.app.main import app, store

        cls.app = app
        cls.store = store

    @classmethod
    def tearDownClass(cls):
        cls.store.close()
        cls.temporary_directory.cleanup()
        if cls.previous_database is None:
            os.environ.pop("FORGE_DB_PATH", None)
        else:
            os.environ["FORGE_DB_PATH"] = cls.previous_database

    def test_only_canonical_learning_routes_remain_public(self):
        paths = {route.path for route in self.app.routes}
        removed_paths = {
            "/v1/workspaces/{workspace_id}/today",
            "/v1/workspaces/{workspace_id}/context",
            "/v1/workspaces/{workspace_id}/history",
            "/v1/workspaces/{workspace_id}/session-contexts",
            "/v1/workspaces/{workspace_id}/agents-guardrails",
            "/v1/workspaces/{workspace_id}/approved-guardrails",
            "/v1/workspaces/{workspace_id}/portable-guardrails",
            "/v1/workspaces/{workspace_id}/agents-guardrail-handoffs",
            "/v1/workspaces/{workspace_id}/imports",
            "/v1/workspaces/{workspace_id}/intention",
            "/v1/reflections/{reflection_id}/review",
            "/v1/memory/{entry_id}/archive",
        }
        self.assertTrue(removed_paths.isdisjoint(paths))
        self.assertIn("/v1/workspaces/{workspace_id}/legacy-history", paths)
        self.assertIn("/v1/workspaces/{workspace_id}/handoffs", paths)
        self.assertIn("/v1/workspaces/{workspace_id}/learning-cards", paths)
        self.assertIn("/v1/workspaces/{workspace_id}/decisions/retrieve", paths)
