import os
import asyncio
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

    def test_work_item_mcp_is_cited_and_idempotent(self):
        store = Store(self.database)
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Work Item", "safe", "Focused validation passed", "work-item-mcp")
        store.close()
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            first = mcp_server.forge_start_work_item("mcp-work", "codex", ".", "main", "Verify MCP Work Items.", ["backend"], "session-1", "testing")
            retried = mcp_server.forge_start_work_item("mcp-work", "codex", ".", "main", "Verify MCP Work Items.", ["backend"], "session-1", "testing")
            finished = mcp_server.forge_finish_work_item(first["work_item"]["id"], "completed", "MCP stored the item.", "The same key is retry-safe.", "Focused validation passed.", "None.", "None.", [span_id])
            listed = mcp_server.forge_list_work_items(session_id="session-1")
        self.assertTrue(retried["idempotent"])
        self.assertEqual("completed", finished["work_item"]["status"])
        self.assertEqual([first["work_item"]["id"]], [item["id"] for item in listed])

    def test_incident_mcp_requires_a_work_item_and_returns_citations(self):
        store = Store(self.database)
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Route", "safe", "Route exists", "incident-mcp")
        item = store.start_work_item("default", "session-1", "incident-work", "codex", ".", "main", "Inspect a route.", ["backend"])["work_item"]
        store.close()
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            incident = mcp_server.forge_capture_incident(item["id"], "incident-mcp", "technical_error", ["backend"], "API", "Route call", "The request returned 404.", "The client used an invalid route.", "The server may be stale.", "Read the local route definition.", "medium", [span_id])
            listed = mcp_server.forge_list_incidents(work_item_id=item["id"])
        self.assertEqual("technical_error", incident["observation"]["kind"])
        self.assertEqual("Route", incident["observation"]["citations"][0]["title"])
        self.assertEqual([incident["observation"]["id"]], [entry["id"] for entry in listed])

    def test_vault_mcp_searches_persisted_records_and_exports_generated_files(self):
        store = Store(self.database)
        store.register_repository("default", self.temporary_directory.name)
        span_id = store.create_evidence("default", "git_commit", "Vault MCP", "safe", "Focused vault test passed", "vault-mcp")
        item = store.start_work_item("default", "session-1", "vault-mcp", "codex", ".", "main", "Build vault search.", ["backend"], "memory")["work_item"]
        store.finish_work_item("default", item["id"], "completed", "Added searchable records.", "SQLite remains authoritative.", "Focused test passed.", "None.", "None.", [span_id])
        store.close()
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}):
            found = mcp_server.forge_search_vault("searchable records", scope="backend")
            exported = mcp_server.forge_export_vault()
        self.assertEqual([item["id"]], [entry["record_id"] for entry in found])
        self.assertTrue((Path(exported["path"]) / "PROJECT_CONTEXT.md").exists())

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

    def test_chatgpt_http_transport_exposes_only_safe_read_tools(self):
        server = mcp_server.chatgpt_http_server(9123)
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        self.assertEqual(set(mcp_server.CHATGPT_READ_ONLY_TOOLS), names)
        self.assertEqual("127.0.0.1", server.settings.host)
        self.assertEqual(9123, server.settings.port)
        self.assertEqual("/mcp", server.settings.streamable_http_path)
        self.assertTrue(server.settings.stateless_http)
        self.assertNotIn("forge_record_session_handoff", names)
        self.assertNotIn("forge_run_validation", names)
        self.assertNotIn("forge_approve_rule", names)

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

    def test_complete_session_saves_every_handoff_before_marking_the_lease(self):
        store = Store(self.database)
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Validation", "safe", "Validation passed", "batch-commit")
        store.close()
        handoff = {
            "agent": "codex", "worktree_path": ".", "branch": "main", "scope": ["repository"], "category": "testing",
            "problem": "One handoff hid separate work.", "prior_approach": "Recorded a single session result.",
            "why_prior_approach_failed": "Distinct changes need their own context.", "alternatives": [],
            "chosen_fix": "Record a batch.", "rationale": "Each work unit remains legible.",
            "validation": "Configured validation passed", "risk": "A failed item keeps the lease open.", "unresolved": "none",
            "proposed_rule": "none", "evidence_span_ids": [span_id],
        }
        runtime = MagicMock()
        runtime.mark_handoff.return_value = {"handoff_id": "recorded", "lease_ready_to_end": True}
        with patch.dict(os.environ, {"FORGE_DB_PATH": str(self.database)}), patch("backend.app.mcp_server.ForgeRuntime", return_value=runtime):
            result = mcp_server.forge_complete_session("session-1", handoffs=[{**handoff, "outcome_key": "batch-one", "goal": "First work unit"}, {**handoff, "outcome_key": "batch-two", "goal": "Second work unit"}])
        self.assertEqual(["batch-one", "batch-two"], [outcome["outcome_key"] for outcome in result["outcomes"]])
        runtime.mark_handoff.assert_called_once_with("session-1", "codex", result["outcomes"][-1]["id"])


if __name__ == "__main__":
    unittest.main()
