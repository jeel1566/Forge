import json
import os
import ast
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from backend.app.cli import main
from backend.app.installation import agent_status, install_agent, repair_agent, uninstall_agent


class AgentInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary_directory.name) / "home"
        self.home.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def environment(self):
        return patch.dict(os.environ, {"USERPROFILE": str(self.home)}, clear=False)

    def test_codex_install_preserves_other_mcp_servers_and_is_idempotent(self):
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir()
        config.write_text('[mcp_servers.pencil]\ncommand = "pencil-mcp"\n', encoding="utf-8")
        with self.environment():
            first = install_agent("codex")
            second = install_agent("codex")
        saved = config.read_text(encoding="utf-8")
        self.assertEqual(first["mcp_config"], second["mcp_config"])
        self.assertIn('[mcp_servers.pencil]', saved)
        self.assertEqual(1, saved.count('[mcp_servers.forge]'))
        self.assertIn('command = "forge-mcp"', saved)
        self.assertIn("forge_get_session_start_context", (self.home / ".codex" / "AGENTS.md").read_text(encoding="utf-8"))
        skill = self.home / ".codex" / "skills" / "forge-end" / "SKILL.md"
        self.assertIn("forge_complete_session", skill.read_text(encoding="utf-8"))
        self.assertIn("Use `unresolved` (not `unresolved_work`)", skill.read_text(encoding="utf-8"))

    def test_antigravity_install_preserves_other_servers_and_uninstall_only_removes_forge(self):
        config = self.home / ".gemini" / "config" / "mcp_config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"mcpServers": {"pencil": {"command": "pencil-mcp"}}}), encoding="utf-8")
        with self.environment():
            install_agent("antigravity")
            uninstall_agent("antigravity")
        saved = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual({"command": "pencil-mcp"}, saved["mcpServers"]["pencil"])
        self.assertNotIn("forge", saved["mcpServers"])
        self.assertNotIn("forge:agent-instructions:start", (self.home / ".gemini" / "GEMINI.md").read_text(encoding="utf-8"))
        self.assertFalse((self.home / ".gemini" / "skills" / "forge-end" / "SKILL.md").exists())

    def test_antigravity_project_install_enables_only_its_dashboard_sidecar(self):
        repository = Path(self.temporary_directory.name) / "project"
        repository.mkdir()
        settings = self.home / ".gemini" / "config" / "config.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"userSettings": {"themeMode": "dark"}, "sidecars": {"other": {"enabled": True}}}), encoding="utf-8")
        with self.environment():
            installed = install_agent("antigravity", repository=repository)
            sidecar_document = json.loads(Path(installed["dashboard_sidecar"]["config"]).read_text(encoding="utf-8"))
            removed = uninstall_agent("antigravity", repository=repository)
        sidecar = installed["dashboard_sidecar"]
        self.assertEqual("forge", sidecar_document["command"])
        self.assertIn("--path", sidecar_document["args"])
        saved = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual("dark", saved["userSettings"]["themeMode"])
        self.assertEqual({"enabled": True}, saved["sidecars"]["other"])
        self.assertNotIn(sidecar["id"], saved["sidecars"])
        self.assertFalse(Path(sidecar["config"]).exists())

    def test_dry_run_does_not_create_files(self):
        with self.environment():
            result = install_agent("codex", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse((self.home / ".codex" / "config.toml").exists())
        self.assertFalse((self.home / ".codex" / "skills" / "forge-end" / "SKILL.md").exists())

    def test_existing_non_forge_skill_is_preserved(self):
        skill = self.home / ".codex" / "skills" / "forge-end" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("personal skill", encoding="utf-8")
        with self.environment(), self.assertRaisesRegex(ValueError, "non-Forge skill"):
            install_agent("codex")

    def test_incomplete_managed_instruction_markers_are_not_overwritten(self):
        instructions = self.home / ".codex" / "AGENTS.md"
        instructions.parent.mkdir()
        instructions.write_text("<!-- forge:agent-instructions:start -->\n", encoding="utf-8")
        with self.environment(), self.assertRaisesRegex(ValueError, "markers are incomplete"):
            install_agent("codex")

    def test_status_and_repair_report_only_safe_health_states(self):
        with self.environment():
            self.assertFalse(agent_status("codex")["healthy"])
            install_agent("codex")
            repaired = repair_agent("codex")
            self.assertTrue(agent_status("codex")["healthy"])
            self.assertFalse(repaired["repaired"])
            self.assertNotIn("config.toml", str(repaired["status"]))

    def test_doctor_does_not_create_a_missing_project_database(self):
        repository = Path(self.temporary_directory.name) / "new-project"
        repository.mkdir()
        output = io.StringIO()
        with self.environment(), patch.object(sys, "argv", ["forge", "doctor", "--path", str(repository), "--agent", "codex"]), redirect_stdout(output):
            main()
        result = ast.literal_eval(output.getvalue().strip())
        self.assertEqual("missing", result["database"]["state"])
        self.assertFalse((repository / ".forge" / "forge.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
