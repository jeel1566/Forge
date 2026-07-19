import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
                mcp_server.forge_get_session_start_context()
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
            context = mcp_server.forge_get_session_start_context()
        self.assertEqual("pending", decision["review_status"])
        self.assertEqual([], context["decisions"])
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

    def test_complete_session_rejects_an_unknown_agent_before_writing(self):
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            with self.assertRaisesRegex(ValueError, "handoff.agent"):
                mcp_server.forge_complete_session("session-1", {"agent": "unknown"})

    def test_complete_session_accepts_unresolved_work_alias_and_normalizes_agent(self):
        store = Store(self.database)
        store.register_repository("default", str(Path(self.temporary_directory.name)))
        span_id = store.create_evidence("default", "git_commit", "Completion", "safe", "Focused test passed", "completion-alias")
        store.close()
        handoff = {
            "agent": "Antigravity", "worktree_path": ".", "branch": "main", "outcome_key": "completion-alias",
            "scope": ["repository"], "category": "testing", "goal": "Validate the handoff.",
            "problem": "The old key name was rejected.", "prior_approach": "Used unresolved_work.",
            "why_prior_approach_failed": "The persisted field is unresolved.", "alternatives": [],
            "chosen_fix": "Use the compatibility mapping.", "rationale": "Existing agent skills use this wording.",
            "validation": "Focused test.", "risk": "None.", "unresolved_work": "None.",
            "proposed_rule": "none", "evidence_span_ids": [span_id],
        }
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}), patch("backend.app.mcp_server.ForgeRuntime") as runtime_class:
            runtime_class.return_value.mark_handoff.return_value = {"lease_ready_to_end": True}
            result = mcp_server.forge_complete_session("session-1", handoff)
        self.assertEqual("antigravity", result["outcome"]["agent"])
        self.assertEqual("None.", result["outcome"]["unresolved"])

    def test_complete_session_lists_missing_handoff_fields(self):
        with self.assertRaisesRegex(ValueError, "worktree_path"):
            mcp_server.forge_complete_session("session-1", {"agent": "codex"})

    def test_start_dashboard_uses_the_registered_workspace(self):
        store = Store(self.database)
        store.register_repository("default", str(Path(self.temporary_directory.name)))
        store.close()
        runtime = MagicMock()
        runtime.start_dashboard.return_value = {"status": "ready", "url": "http://127.0.0.1:43123"}
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}), patch("backend.app.mcp_server.ForgeRuntime", return_value=runtime):
            result = mcp_server.forge_start_dashboard()
        self.assertEqual("http://127.0.0.1:43123", result["url"])
        runtime.start_dashboard.assert_called_once_with(self.database, "default")

    def test_complete_session_saves_handoff_and_marks_runtime_lease(self):
        store = Store(self.database)
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Validation", "safe", "Validation passed", "commit-1")
        store.close()
        handoff = {
            "agent": "codex", "worktree_path": ".", "branch": "main", "outcome_key": "complete-session",
            "scope": ["repository"], "category": "testing", "goal": "Validate completion", "problem": "No end gate",
            "prior_approach": "Released directly", "why_prior_approach_failed": "It lost the handoff boundary",
            "alternatives": [], "chosen_fix": "Mark the lease", "rationale": "The runtime can verify completion",
            "validation": "Configured validation passed", "risk": "Agent may abandon", "unresolved": "none",
            "proposed_rule": "none", "evidence_span_ids": [span_id],
        }
        runtime = MagicMock()
        runtime.mark_handoff.return_value = {"handoff_id": "recorded", "lease_ready_to_end": True}
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}), patch("backend.app.mcp_server.ForgeRuntime", return_value=runtime):
            result = mcp_server.forge_complete_session("session-1", handoff)
        self.assertEqual("complete-session", result["outcome"]["outcome_key"])
        runtime.mark_handoff.assert_called_once_with("session-1", "codex", result["outcome"]["id"])


if __name__ == "__main__":
    unittest.main()
