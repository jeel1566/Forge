import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.store import Store
from backend.app.validation import run_configured_validation, run_validation


class LearningLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "forge.validation.json").write_text(json.dumps({"validations": [{
            "id": "backend-check", "argv": [sys.executable, "-c", "pass"], "scopes": ["backend"],
            "categories": ["testing"], "timeout_seconds": 30,
        }, {"id": "repository-check", "argv": [sys.executable, "-c", "pass"], "scopes": ["repository"], "categories": ["testing"], "timeout_seconds": 30}]}), encoding="utf-8")
        self.store = Store(self.repository / ".forge" / "forge.sqlite3")
        self.store.register_repository("default", str(self.repository))

    def tearDown(self):
        self.store.close()
        self.temporary_directory.cleanup()

    def evidence(self, validation_id: str = "backend-check"):
        return run_configured_validation(self.store, "default", validation_id)["span_id"]

    def handoff(self, key: str, span_id: str, rule: str = "Run the migration test before finishing.", **card):
        card = {"learning_area": "database", "learning_trigger": "schema migration changed", "learning_action": "run the migration test", **card}
        return self.store.record_session_handoff(
            "default", "codex", str(self.repository), "feature/rules", key, ["backend/schema"], "testing",
            "Fix schema migration", "Migration test failed", "Edited SQL without a focused test",
            "The migration was invalid", [{"option": "Retry blindly", "reason": "It hides the cause"}],
            "Add migration test", "The test proves the schema change", "Configured validation passed",
            "Future migrations may differ", "none", rule, [span_id], **card,
        )

    def ready_rule(self, mode: str = "autonomous"):
        self.store.configure_rule_policy("default", mode)
        self.handoff("outcome-1", self.evidence())
        return self.handoff("outcome-2", self.evidence())["rule"]

    def test_configured_validations_make_a_card_ready(self):
        candidate = self.ready_rule()
        self.assertTrue(candidate["eligible"])
        card = self.store.learning_cards("default")[0]
        self.assertEqual("ready", card["state"])
        self.assertEqual(2, len(card["observations"]))
        self.assertEqual("codex", card["observations"][0]["agent"])
        self.assertIn("Configured validation passed", card["observations"][0]["validation"])
        self.assertTrue(card["observations"][0]["citation_quote"])

    def test_manual_validation_never_advances_a_card(self):
        manual = run_validation(self.store, "default", "manual", [sys.executable, "-c", "pass"])["span_id"]
        result = self.handoff("manual-outcome", manual)
        self.assertFalse(result["rule"]["eligible"])
        self.assertEqual("observed", self.store.learning_cards("default")[0]["state"])

    def test_card_identity_matches_differently_worded_rules(self):
        first = self.handoff("outcome-1", self.evidence(), "Run migration tests before finishing.")
        second = self.handoff("outcome-2", self.evidence(), "Check migrations after changing schema.")
        self.assertEqual(first["rule"]["id"], second["rule"]["id"])
        self.assertTrue(second["rule"]["eligible"])

    def test_same_validation_span_is_not_independent_evidence(self):
        span_id = self.evidence()
        self.handoff("outcome-1", span_id)
        repeated = self.handoff("outcome-2", span_id)
        self.assertEqual(1, repeated["rule"]["evidence_count"])
        self.assertFalse(repeated["rule"]["eligible"])

    def test_handoff_links_to_its_work_item(self):
        span_id = self.evidence()
        item = self.store.start_work_item(
            "default", "session-1", "migration-work", "codex", str(self.repository), "feature/rules",
            "Fix a migration.", ["backend/schema"], "database",
        )["work_item"]
        result = self.handoff("work-item-outcome", span_id, "none", work_item_id=item["id"])
        self.assertEqual(item["id"], result["outcome"]["work_item_id"])

    def test_approval_mode_writes_only_after_explicit_approval(self):
        candidate = self.ready_rule("approval")
        proposal = self.store.rule_proposal(candidate["id"])
        self.assertIn(candidate["statement"], proposal["diff"])
        active = self.store.approve_rule(candidate["id"], True)
        self.assertEqual("active", active["state"])
        self.assertIn(candidate["statement"], (self.repository / "AGENTS.md").read_text(encoding="utf-8"))

    def test_manual_edit_inside_managed_block_blocks_projection(self):
        first = self.ready_rule()
        self.store.activate_rule(first["id"])
        agents = self.repository / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8").replace("Forge Active Rules", "Manual edit"), encoding="utf-8")
        second_rule = self.handoff("new-1", self.evidence(), "A second rule", learning_area="api", learning_trigger="route changed", learning_action="run backend check")["rule"]
        second_rule = self.handoff("new-2", self.evidence(), "A second rule", learning_area="api", learning_trigger="route changed", learning_action="run backend check")["rule"]
        with self.assertRaisesRegex(ValueError, "repair"):
            self.store.activate_rule(second_rule["id"])
        self.assertTrue(any(alert["kind"] == "projection_repair" for alert in self.store.learning_alerts("default")))
        status = self.store.projection_status("default")
        self.assertTrue(status["repair_alerts"])
        self.assertIn("repair", status["repair_alerts"][0]["detail"])

    def test_conflict_blocks_both_cards_until_developer_decides(self):
        first = self.handoff("first", self.evidence(), learning_area="database", learning_trigger="schema changed", learning_action="run migration test")
        second = self.handoff("second", self.evidence(), "Use schema check", learning_area="database", learning_trigger="schema changed", learning_action="run schema lint")
        alerts = self.store.learning_alerts("default")
        self.assertEqual("possible_conflict", alerts[0]["kind"])
        self.store.review_learning_alert(alerts[0]["id"], "marked_conflict")
        self.assertEqual("marked_conflict", self.store.db.execute("SELECT status FROM learning_card_alerts WHERE id=?", (alerts[0]["id"],)).fetchone()["status"])
        self.assertNotEqual(first["rule"]["id"], second["rule"]["id"])

    def test_contradiction_requires_configured_validation_and_rolls_back(self):
        active = self.store.activate_rule(self.ready_rule()["id"])
        manual = run_validation(self.store, "default", "manual", [sys.executable, "-c", "pass"])["span_id"]
        with self.assertRaises(ValueError):
            self.store.verify_rule(active["id"], "contradicted", manual, "manual evidence")
        retracted = self.store.verify_rule(active["id"], "contradicted", self.evidence(), "The rule blocked a valid hotfix.")
        self.assertEqual("retracted", retracted["state"])
        self.assertNotIn(active["statement"], (self.repository / "AGENTS.md").read_text(encoding="utf-8"))

    def test_git_verification_requires_developer_confirmation_before_retraction(self):
        active = self.store.activate_rule(self.ready_rule()["id"])
        span_id = self.store.create_evidence("default", "git_commit", "Regression fix", "safe git summary", "Regression fix", "later-commit")
        pending = self.store.record_verification_input(active["id"], "git_change", "contradicted", span_id, "Later Git evidence shows the rule missed this regression.")
        self.assertEqual("active", pending["rule"]["state"])
        self.assertFalse(pending["input"]["developer_confirmed"])
        confirmed = self.store.confirm_verification_input(pending["input"]["id"])
        self.assertEqual("retracted", confirmed["rule"]["state"])
        card = self.store.learning_cards("default")[0]
        self.assertEqual("git_change", card["verification_inputs"][0]["source_kind"])
        self.assertTrue(card["verification_inputs"][0]["citation_quote"])

    def test_local_failure_is_bounded_pending_evidence(self):
        active = self.store.activate_rule(self.ready_rule()["id"])
        pending = self.store.record_local_failure(active["id"], "test_failure", "Focused migration check failed at the changed boundary.")
        self.assertEqual("local_failure", pending["input"]["source_kind"])
        self.assertFalse(pending["input"]["developer_confirmed"])
        self.assertNotIn("command_output", pending["input"])

    def test_restart_preserves_card_and_validation_history(self):
        self.handoff("outcome-1", self.evidence())
        self.store.close()
        self.store = Store(self.repository / ".forge" / "forge.sqlite3")
        self.assertEqual(1, len(self.store.learning_cards("default")))
        self.assertEqual(1, self.store.db.execute("SELECT COUNT(*) AS count FROM validation_runs").fetchone()["count"])


if __name__ == "__main__":
    unittest.main()


class ReusableRuleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.registry = self.root / "reusable-rules.sqlite3"
        self.stores: list[Store] = []

    def tearDown(self):
        for store in self.stores:
            store.close()
        self.temporary_directory.cleanup()

    def active_rule(self, name: str):
        repository = self.root / name
        repository.mkdir()
        (repository / "forge.validation.json").write_text(json.dumps({"validations": [{
            "id": "repository-check", "argv": [sys.executable, "-c", "pass"], "scopes": ["repository"],
            "categories": ["testing"], "timeout_seconds": 30,
        }]}), encoding="utf-8")
        store = Store(repository / ".forge" / "forge.sqlite3")
        self.stores.append(store)
        store.register_repository("default", str(repository))
        store.configure_rule_policy("default", "approval")
        def handoff(key: str):
            span_id = run_configured_validation(store, "default", "repository-check")["span_id"]
            return store.record_session_handoff(
                "default", "codex", str(repository), "feature/reusable", key, ["repository"], "testing",
                "Validate a reusable rule.", "A repeated validation omission was found.", "Relied on a final broad test.",
                "The focused check was skipped.", [{"option": "Rely on memory", "reason": "It is not reliable."}],
                "Run the configured repository check.", "The configured check is reproducible.", "Configured validation passed.",
                "None.", "None.", "Run the configured repository check before finishing.", [span_id],
                learning_area="validation", learning_trigger="finishing repository work", learning_action="run the configured repository check",
            )
        handoff(f"{name}-one")
        candidate = handoff(f"{name}-two")["rule"]
        return store, store.approve_rule(candidate["id"], True), candidate

    def test_reusable_rule_requires_two_projects_and_project_override_wins(self):
        with patch.dict("os.environ", {"FORGE_REUSABLE_RULES_DB": str(self.registry)}):
            forge_store, forge_rule, _ = self.active_rule("forge")
            first = forge_store.request_reusable_rule(forge_rule["id"])
            self.assertEqual(1, first["source_count"])
            self.assertFalse(first["ready_for_approval"])
            cortex_store, cortex_rule, _ = self.active_rule("cortex")
            pending = cortex_store.request_reusable_rule(cortex_rule["id"])
            self.assertEqual(2, pending["source_count"])
            self.assertTrue(pending["ready_for_approval"])
            self.assertEqual("pending", pending["state"])
            self.assertEqual("pending_developer_approval", cortex_store.approve_reusable_rule(pending["id"], False)["status"])
            active = cortex_store.approve_reusable_rule(pending["id"], True)
            self.assertEqual("active", active["state"])
            new_repository = self.root / "new-project"
            new_repository.mkdir()
            new_store = Store(new_repository / ".forge" / "forge.sqlite3")
            self.stores.append(new_store)
            new_store.register_repository("default", str(new_repository))
            context = new_store.session_start_context("default")
            self.assertEqual([active["id"]], [rule["id"] for rule in context["reusable_rules"]])
            overridden = new_store.set_reusable_rule_override("default", active["id"], "replace", "This project requires the repository check before release.")
            self.assertEqual("project_override", overridden["origin"])
            self.assertEqual("This project requires the repository check before release.", new_store.session_start_context("default")["reusable_rules"][0]["statement"])
            ignored = new_store.set_reusable_rule_override("default", active["id"], "ignore")
            self.assertEqual("ignore", ignored["override_action"])
            self.assertEqual([], new_store.session_start_context("default")["reusable_rules"])

    def test_feedback_is_cited_local_review_data(self):
        with patch.dict("os.environ", {"FORGE_REUSABLE_RULES_DB": str(self.registry)}):
            store, _, candidate = self.active_rule("forge")
            handoff = store.get_session_handoff(candidate["source_outcome_id"])
            feedback = store.record_session_feedback("default", handoff["id"], "yes", "Nothing missing.", "approve")
            self.assertFalse(feedback["idempotent"])
            evidence = store.get_evidence(store.db.execute("SELECT evidence_id FROM evidence_spans WHERE id=?", (feedback["evidence_span_id"],)).fetchone()["evidence_id"])
            self.assertEqual("developer_feedback", evidence["kind"])
            self.assertNotIn("transcript", str(feedback).lower())
