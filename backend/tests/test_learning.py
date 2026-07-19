import tempfile
import unittest
from pathlib import Path

from backend.app.store import Store


class LearningLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        self.store = Store(self.repository / ".forge" / "forge.sqlite3")
        self.store.register_repository("default", str(self.repository))

    def tearDown(self):
        self.store.close()
        self.temporary_directory.cleanup()

    def outcome(self, key: str, span_id: str, rule: str = "When changing schema, run the migration test before finishing.", **learning_card):
        return self.store.record_session_outcome(
            "default", "codex", str(self.repository), "feature/rules", key, ["backend/schema"], "debugging",
            "Fix schema migration", "Migration test failed", "Edited SQL without a focused test",
            "The migration was invalid", [{"option": "Retry blindly", "reason": "It hides the cause"}],
            "Add migration test", "The test proves the schema change", "Forge-recorded migration validation passed",
            "Future migrations may differ", "none", rule, [span_id], **learning_card,
        )

    def evidence(self, external_id: str):
        return self.store.create_evidence("default", "local_validation", external_id, "passed", external_id, external_id, {"captured_by": "forge", "trusted": True, "status": "passed"})

    def test_autonomous_mode_requires_two_cited_outcomes_then_updates_managed_block(self):
        self.store.configure_rule_policy("default", "autonomous")
        first = self.outcome("outcome-1", self.evidence("commit-1"))
        self.assertEqual("candidate", first["rule"]["state"])
        self.assertFalse(first["rule"]["eligible"])
        second = self.outcome("outcome-2", self.evidence("commit-2"))
        self.assertTrue(second["rule"]["eligible"])
        active = self.store.activate_rule(second["rule"]["id"])
        self.assertEqual("active", active["state"])
        agents = (self.repository / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<!-- forge:rules:start -->", agents)
        self.assertIn(active["statement"], agents)

    def test_outcome_key_is_idempotent(self):
        self.store.configure_rule_policy("default", "autonomous")
        span_id = self.evidence("commit-1")
        first = self.outcome("same-outcome", span_id)
        repeated = self.outcome("same-outcome", span_id)
        self.assertFalse(first["idempotent"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(1, self.store.db.execute("SELECT COUNT(*) AS count FROM session_outcomes").fetchone()["count"])

    def test_session_outcomes_are_listed_with_visible_evidence(self):
        span_id = self.evidence("commit-visible")
        saved = self.outcome("visible-outcome", span_id)
        outcomes = self.store.list_session_outcomes("default")
        self.assertEqual([saved["outcome"]["id"]], [item["id"] for item in outcomes])
        self.assertEqual("commit-visible", outcomes[0]["citations"][0]["quote"])

    def test_session_outcomes_are_in_shared_project_context(self):
        saved = self.outcome("shared-outcome", self.evidence("commit-shared"))
        context = self.store.context("default")
        self.assertEqual([saved["outcome"]["id"]], [item["id"] for item in context["recent_session_outcomes"]])

    def test_pending_rule_progress_is_visible_to_the_next_agent(self):
        self.store.configure_rule_policy("default", "autonomous")
        self.outcome("outcome-1", self.evidence("commit-1"))
        context = self.store.learning_context("default")
        candidate = context["pending_rule_candidates"][0]
        self.assertEqual(1, candidate["evidence_count"])
        self.assertEqual(2, candidate["required_evidence_count"])
        self.assertFalse(candidate["eligible"])
        self.assertIn("Waiting for another outcome", candidate["next_action"])

    def test_repeated_outcomes_with_the_same_citation_do_not_activate_a_rule(self):
        self.store.configure_rule_policy("default", "autonomous")
        span_id = self.evidence("commit-1")
        self.outcome("outcome-1", span_id)
        repeated_evidence = self.outcome("outcome-2", span_id)
        self.assertEqual(1, repeated_evidence["rule"]["evidence_count"])
        self.assertFalse(repeated_evidence["rule"]["eligible"])

    def test_learning_card_matches_different_rule_wording(self):
        self.store.configure_rule_policy("default", "autonomous")
        card = {"learning_area": "database", "learning_trigger": "schema migration changed", "learning_action": "run the migration test"}
        first = self.outcome("outcome-1", self.evidence("validation-1"), "Run migration tests before finishing.", **card)
        second = self.outcome("outcome-2", self.evidence("validation-2"), "Check the migration test after a schema edit.", **card)
        self.assertEqual(first["rule"]["id"], second["rule"]["id"])
        self.assertTrue(second["rule"]["eligible"])
        self.assertEqual("database", second["rule"]["learning_area"])

    def test_approval_mode_returns_exact_diff_then_writes_after_approval(self):
        self.store.configure_rule_policy("default", "approval")
        self.outcome("outcome-1", self.evidence("commit-1"))
        candidate = self.outcome("outcome-2", self.evidence("commit-2"))["rule"]
        proposal = self.store.rule_proposal(candidate["id"])
        self.assertIn(candidate["statement"], proposal["diff"])
        active = self.store.approve_rule(candidate["id"], True)
        self.assertEqual("active", active["state"])
        self.assertIn(candidate["statement"], (self.repository / "AGENTS.md").read_text(encoding="utf-8"))

    def test_contradiction_retracts_rule_and_rolls_back_managed_block(self):
        self.store.configure_rule_policy("default", "autonomous")
        self.outcome("outcome-1", self.evidence("commit-1"))
        candidate = self.outcome("outcome-2", self.evidence("commit-2"))["rule"]
        active = self.store.activate_rule(candidate["id"])
        retracted = self.store.verify_rule(active["id"], "contradicted", self.evidence("commit-3"), "The rule blocked a valid hotfix.")
        self.assertEqual("retracted", retracted["state"])
        self.assertNotIn(active["statement"], (self.repository / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
