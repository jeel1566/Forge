import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.runtime import ForgeRuntime


class ForgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name)
        self.database = self.repository / ".forge" / "forge.sqlite3"
        self.database.parent.mkdir()
        self.database.touch()
        self.runtime = ForgeRuntime(self.repository)

    def tearDown(self):
        self.temporary_directory.cleanup()

    @patch("backend.app.runtime.subprocess.Popen")
    def test_starts_process_and_records_safe_runtime_metadata(self, process):
        process.return_value = MagicMock(pid=1234)
        with patch.object(self.runtime, "_available_port", return_value=43123), patch.object(self.runtime, "_wait_for_health", return_value=True):
            result = self.runtime.start_or_reuse(self.database, "workspace", "codex")
        metadata = json.loads(self.runtime.path.read_text(encoding="utf-8"))
        self.assertFalse(result["reused"])
        self.assertEqual(43123, metadata["port"])
        self.assertEqual(1234, metadata["pid"])
        self.assertIn(result["session_id"], metadata["leases"])
        self.assertEqual("codex", metadata["leases"][result["session_id"]]["agent"])
        self.assertIn("instance_id", metadata)
        self.assertNotIn("token", self.runtime.path.read_text(encoding="utf-8").lower())
        self.assertIn("--port", process.call_args.args[0])

    @patch("backend.app.runtime.subprocess.Popen")
    def test_reuses_healthy_process_without_launching_another(self, process):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {}})
        with patch.object(self.runtime, "_healthy", return_value=True):
            result = self.runtime.start_or_reuse(self.database, "workspace", "antigravity")
        self.assertTrue(result["reused"])
        process.assert_not_called()

    @patch("backend.app.runtime.subprocess.Popen")
    def test_lease_only_session_never_launches_a_dashboard_process(self, process):
        first = self.runtime.start_lease(self.database, "codex")
        second = self.runtime.start_lease(self.database, "antigravity")
        metadata = self.runtime._read()
        self.assertEqual("not_required", first["server"])
        self.assertTrue(second["reused"])
        self.assertEqual("lease_only", self.runtime.status(self.database)["state"])
        self.assertEqual({"codex", "antigravity"}, {lease["agent"] for lease in metadata["leases"].values()})
        process.assert_not_called()

    @patch("backend.app.runtime.subprocess.Popen")
    def test_managed_dashboard_preserves_existing_leases(self, process):
        self.runtime._write({"version": 3, "mode": "lease_only", "database": str(self.database.resolve()), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00"}}})
        process.return_value = MagicMock(pid=1234)
        with patch.object(self.runtime, "_available_port", return_value=43123), patch.object(self.runtime, "_wait_for_health", return_value=True):
            dashboard = self.runtime.start_dashboard(self.database, "workspace")
        self.assertEqual("http://127.0.0.1:43123", dashboard["url"])
        self.assertIn("session-1", self.runtime._read()["leases"])

    def test_last_lease_stops_process_and_removes_metadata(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00", "handoff_id": "handoff-1"}}})
        with patch.object(self.runtime, "_healthy", return_value=True), patch("backend.app.runtime._process_is_alive", return_value=True), patch.object(self.runtime, "_stop_process") as stop:
            result = self.runtime.end_session("session-1")
        self.assertTrue(result["released"])
        self.assertTrue(result["stopped"])
        stop.assert_called_once_with(1234)
        self.assertFalse(self.runtime.path.exists())

    def test_lease_keeps_process_running_for_other_agent(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00", "handoff_id": "handoff-1"}, "session-2": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00", "handoff_id": "handoff-2"}, "session-3": {"agent": "antigravity", "expires_at": "2999-01-01T00:00:00+00:00", "handoff_id": "handoff-3"}}})
        with patch.object(self.runtime, "_stop_process") as stop:
            result = self.runtime.end_session("session-1")
        self.assertFalse(result["stopped"])
        self.assertEqual(["antigravity", "codex"], result["active_agents"])
        self.assertEqual(["session-2", "session-3"], result["active_sessions"])
        stop.assert_not_called()

    def test_session_end_requires_completed_handoff_or_explicit_abandon(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00"}}})
        with self.assertRaisesRegex(ValueError, "forge_complete_session"):
            self.runtime.end_session("session-1")
        with patch.object(self.runtime, "_healthy", return_value=False):
            result = self.runtime.end_session("session-1", abandon=True, abandon_reason="developer_cancelled")
        self.assertTrue(result["abandoned"])

    def test_mark_handoff_makes_lease_ready_to_end(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00"}}})
        result = self.runtime.mark_handoff("session-1", "codex", "handoff-1")
        self.assertTrue(result["lease_ready_to_end"])
        self.assertEqual("handoff-1", self.runtime._read()["leases"]["session-1"]["handoff_id"])

    def test_heartbeat_refreshes_one_session_and_expired_sessions_are_pruned(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"expired": {"agent": "codex", "expires_at": "2000-01-01T00:00:00+00:00"}, "active": {"agent": "antigravity", "expires_at": "2999-01-01T00:00:00+00:00"}}})
        result = self.runtime.heartbeat("active")
        metadata = self.runtime._read()
        self.assertEqual("antigravity", result["agent"])
        self.assertNotIn("expired", metadata["leases"])
        self.assertIn("last_heartbeat_at", metadata["leases"]["active"])

    def test_stale_startup_lock_is_recovered(self):
        self.runtime.lock_path.write_text('{"pid": 999999, "created_at": "2000-01-01T00:00:00+00:00"}', encoding="utf-8")
        with patch("backend.app.runtime._process_is_alive", return_value=False):
            with self.runtime._lock():
                self.assertTrue(self.runtime.lock_path.exists())
        self.assertFalse(self.runtime.lock_path.exists())

    def test_instance_mismatch_never_reports_an_unrelated_process_stopped(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {"session-1": {"agent": "codex", "expires_at": "2999-01-01T00:00:00+00:00", "handoff_id": "handoff-1"}}})
        with patch("backend.app.runtime._process_is_alive", return_value=True), patch.object(self.runtime, "_healthy", return_value=False), patch.object(self.runtime, "_stop_process") as stop:
            result = self.runtime.end_session("session-1")
        self.assertFalse(result["stopped"])
        stop.assert_not_called()

    def test_repair_removes_only_stale_runtime_metadata(self):
        self.runtime._write({"version": 2, "instance_id": "instance-1", "pid": 1234, "port": 43123, "database": str(self.database), "leases": {}})
        with patch.object(self.runtime, "_healthy", return_value=False):
            result = self.runtime.repair_stale_metadata(self.database)
        self.assertTrue(result["metadata_removed"])
        self.assertFalse(self.runtime.path.exists())


if __name__ == "__main__":
    unittest.main()
