import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_github_token_is_protected_and_deletable(self):
        store = self.store()
        saved = store.save_github_token("token-value")
        self.assertTrue(saved["token_saved"])
        self.assertNotIn("token-value", str(saved))
        self.assertEqual("token-value", store.github_token())
        deleted = store.delete_github_credentials()
        self.assertFalse(deleted["token_saved"])

    def test_migrations_and_evidence_spans_are_persistent(self):
        store = self.store()
        store.create_evidence("default", "git_commit", "Add storage", "diff --git", "Add storage", "commit-1", {"files": ["backend/app/store.py"]}, ["@@ -1,1 +1,2 @@"])
        evidence = store.list_evidence("default")[0]
        self.assertEqual(2, len(store.get_evidence(evidence["id"])["spans"]))
        self.assertEqual(1, store.evidence_count("default", "git_commit"))
        self.assertEqual(28, store.db.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()["version"])
        self.assertTrue(store.integrity_check()["ok"])

    def test_one_session_can_hold_multiple_cited_work_items(self):
        store = self.store()
        store.register_repository("default", ".")
        first_span = store.create_evidence("default", "git_commit", "Backend change", "safe", "Backend validation passed", "work-item-one")
        second_span = store.create_evidence("default", "git_commit", "Frontend change", "safe", "Frontend validation passed", "work-item-two")
        first = store.start_work_item("default", "session-1", "backend-change", "codex", ".", "feature/work-items", "Add Work Item storage.", ["backend"], "storage")
        retried = store.start_work_item("default", "session-1", "backend-change", "codex", ".", "feature/work-items", "Add Work Item storage.", ["backend"], "storage")
        second = store.start_work_item("default", "session-1", "frontend-change", "codex", ".", "feature/work-items", "Add Work Item UI.", ["frontend"], "dashboard")
        self.assertTrue(retried["idempotent"])
        self.assertEqual(first["work_item"]["id"], retried["work_item"]["id"])
        store.finish_work_item("default", first["work_item"]["id"], "completed", "Stored Work Items.", "Separate tasks need separate memory.", "Backend validation passed.", "None.", "None.", [first_span])
        store.finish_work_item("default", second["work_item"]["id"], "abandoned", "Paused the UI work.", "The backend API needs review first.", "Frontend validation passed.", "No product risk.", "Resume after API review.", [second_span])
        items = store.list_work_items("default", session_id="session-1")
        self.assertEqual(2, len(items))
        self.assertEqual({"completed", "abandoned"}, {item["status"] for item in items})
        self.assertEqual({"Backend change", "Frontend change"}, {item["citations"][0]["title"] for item in items})

    def test_incident_keeps_facts_hypotheses_and_counterexamples_separate(self):
        store = self.store()
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Route definition", "safe", "POST /v1/repositories is defined locally", "route-definition")
        item = store.start_work_item("default", "session-1", "repository-ui", "codex", ".", "feature/work-items", "Register a repository.", ["frontend"], "dashboard")["work_item"]
        result = store.capture_learning_observation(
            "default", item["id"], "route-assumption-1", "decision_pattern", ["frontend"], "API integration",
            "A repository form calls a local API", "A repository form is added", "The client assumed a route without reading its local definition.",
            "The route may instead be missing or the server may be stale.", "Inspect the matching local route before changing the client.",
            "medium", [span_id],
        )
        retried = store.capture_learning_observation(
            "default", item["id"], "route-assumption-1", "decision_pattern", ["frontend"], "API integration",
            "A repository form calls a local API", "A repository form is added", "The client assumed a route without reading its local definition.",
            "The route may instead be missing or the server may be stale.", "Inspect the matching local route before changing the client.",
            "medium", [span_id],
        )
        observation = result["observation"]
        self.assertTrue(retried["idempotent"])
        self.assertEqual("observed", observation["state"])
        self.assertIn("may instead", observation["counterexample"])
        self.assertEqual("Route definition", observation["citations"][0]["title"])

    def test_independent_work_items_make_one_learning_case_proposed(self):
        store = self.store()
        store.register_repository("default", ".")
        span_id = store.create_evidence("default", "git_commit", "Route evidence", "safe", "Route definition inspected", "case-route")
        first = store.start_work_item("default", "session-1", "case-one", "codex", ".", "main", "Fix route one.", ["frontend"])["work_item"]
        second = store.start_work_item("default", "session-2", "case-two", "codex", ".", "main", "Fix route two.", ["frontend"])["work_item"]
        def capture(item_id, key):
            return store.capture_learning_observation("default", item_id, key, "decision_pattern", ["frontend"], "API", "Calling a local API", "The route was assumed.", "The client did not inspect the route definition.", "The server could be stale.", "Inspect the local route definition before changing a client.", "medium", [span_id])
        first_case = capture(first["id"], "case-observation-one")["case"]
        second_case = capture(second["id"], "case-observation-two")["case"]
        self.assertEqual(first_case["id"], second_case["id"])
        self.assertEqual("proposed", second_case["state"])
        self.assertEqual(2, second_case["independent_work_item_count"])

    def test_concurrent_evidence_reads_are_serialized(self):
        store = self.store()
        store.create_evidence("default", "git_commit", "Concurrent evidence", "diff", "Concurrent evidence", "concurrent-1", {"files": ["backend/app/store.py"]})
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: store.list_evidence("default"), range(40)))
        self.assertTrue(all(result[0]["metadata"]["files"] == ["backend/app/store.py"] for result in results))

    def test_repository_registry_lists_multiple_workspaces(self):
        store = self.store()
        store.register_repository("repo-one", ".", "https://github.com/example/one.git", "main")
        store.register_repository("repo-two", "..", "https://github.com/example/two.git", "main")
        self.assertEqual(["repo-one", "repo-two"], [item["workspace_id"] for item in store.repositories()])

    def test_reflections_are_not_memory_and_memory_can_be_archived(self):
        store = self.store()
        decision = store.create_pending("default", "Keep changes focused.", "process", "The review requested a smaller patch.")
        store.review(decision["id"], "confirmed")
        reflection = store.create_reflection("default", "Review the failing test before editing.", "The error identifies the failing assertion.")
        self.assertEqual([], [item for item in store.context("default")["memory"] if item["statement"] == reflection["statement"]])
        self.assertTrue(store.archive_memory(store.context("default")["memory"][0]["memory_entry_id"]))
        self.assertEqual([], store.context("default")["memory"])
        self.assertEqual(1, len(store.history("default")["reflections"]))

    def test_guardrail_requires_two_confirmations_and_returns_a_diff(self):
        store = self.store()
        self.assertEqual("insufficient_data", store.propose_agents_guardrail("default", "Run focused tests.", "")["status"])
        for _ in range(2):
            decision = store.create_pending("default", "Run focused tests.", "process", "Focused tests caught the regression.")
            store.review(decision["id"], "confirmed")
        proposal = store.propose_agents_guardrail("default", "Run focused tests.", "# Repository instructions\n")
        self.assertEqual("pending_developer_approval", proposal["status"])
        self.assertIn("+## Confirmed Guardrails", proposal["diff"])

    def test_approved_session_context_is_shared_without_becoming_decision_memory(self):
        store = self.store()
        span_id = store.create_evidence("default", "git_commit", "Add session handoffs", "diff --git", "Add session handoffs", "commit-session")
        session = store.create_session_context(
            "default", "codex", ".", "feature/session-handoff", "Added reviewed session handoffs.",
            "Agents need shared worktree context.", "Keep session history separate from durable decisions.",
            "A new agent could not see prior work.", "Store approved handoffs separately.", "Focused tests passed.",
            "Dashboard review UI is pending.", [span_id], "base-commit", "commit-session",
        )
        self.assertEqual("pending", session["review_status"])
        self.assertEqual([], store.context("default")["recent_session_context"])
        store.review_session_context(session["id"], "approved")
        context = store.context("default")
        self.assertEqual(1, len(context["recent_session_context"]))
        self.assertEqual([], context["memory"])
        self.assertEqual("feature/session-handoff", context["recent_session_context"][0]["branch"])
        self.assertTrue(store.archive_session_context(session["id"]))
        self.assertEqual([], store.context("default")["recent_session_context"])

    def test_portable_guardrail_requires_explicit_approval(self):
        store = self.store()
        store.record_guardrail_approval("source", "Run focused tests.", "diff")
        guardrail = store.portable_guardrails("target")[0]
        with self.assertRaises(ValueError):
            store.adopt_portable_guardrail("target", guardrail["id"], False)
        self.assertTrue(store.adopt_portable_guardrail("target", guardrail["id"], True)["recorded"])

    def test_agents_guardrail_handoff_requires_approved_matching_file_edit(self):
        store = self.store()
        statement = "Run focused tests before merging."
        for _ in range(2):
            decision = store.create_pending("default", statement, "process", "Focused tests caught regressions.")
            store.review(decision["id"], "confirmed")
        agents_file = Path(self.temporary_directory.name) / "AGENTS.md"
        original = "# Project instructions\n"
        agents_file.write_text(original, encoding="utf-8")
        handoff = store.prepare_agents_guardrail_handoff("default", statement, agents_file.read_text(encoding="utf-8"), str(agents_file))
        self.assertEqual("pending_developer_approval", handoff["status"])
        with self.assertRaisesRegex(ValueError, "developer explicitly approved"):
            store.complete_agents_guardrail_handoff(handoff["id"], False, original)
        with self.assertRaisesRegex(ValueError, "does not match"):
            store.complete_agents_guardrail_handoff(handoff["id"], True, original)
        applied = "# Project instructions\n\n## Confirmed Guardrails\n\n- Run focused tests before merging.\n"
        agents_file.write_text(applied, encoding="utf-8")
        completed = store.complete_agents_guardrail_handoff(handoff["id"], True, agents_file.read_text(encoding="utf-8"))
        self.assertEqual("applied", completed["status"])
        self.assertEqual(1, len(store.approved_guardrails("default")))

    def test_portable_handoff_generates_target_specific_diff_and_records_adoption(self):
        store = self.store()
        store.record_guardrail_approval("source", "Keep commits focused.", "source diff")
        source = store.portable_guardrails("target")[0]
        handoff = store.prepare_agents_guardrail_handoff("target", "", "# Target instructions\n", "AGENTS.md", source["id"])
        self.assertIn("Keep commits focused.", handoff["proposed_diff"])
        completed = store.complete_agents_guardrail_handoff(handoff["id"], True, "# Target instructions\n\n## Confirmed Guardrails\n\n- Keep commits focused.\n")
        self.assertEqual("applied", completed["status"])
        self.assertTrue(store.adopt_portable_guardrail("target", source["id"], True)["recorded"])

    def test_batch_handoffs_stay_reviewed_context_and_can_propose_a_decision(self):
        store = self.store()
        span_id = store.create_evidence("default", "git_commit", "Implement work sessions", "diff --git", "Implement work sessions", "commit-work")
        handoffs = [{"agent": "codex", "worktree_path": ".", "branch": "feature/work", "what_changed": statement, "why": "Shared work needs a handoff.", "decisions": "Keep context reviewed.", "problems": "None.", "fixes": "None.", "validation": "Focused tests passed.", "unresolved": "None.", "evidence_span_ids": [span_id], "base_commit": "base", "head_commit": "commit-work"} for statement in ("Added boundaries.", "Added batch capture.")]
        contexts = store.create_session_contexts("default", handoffs)
        self.assertEqual(2, len(contexts))
        store.review_session_context(contexts[0]["id"], "approved")
        decision = store.create_pending("default", "Keep reviewed handoffs separate from memory.", "architecture", "Added boundaries.", evidence_span_ids=[span_id], source_session_context_id=contexts[0]["id"])
        self.assertEqual(contexts[0]["id"], decision["source_session_context_id"])
        self.assertEqual([], store.context("default")["memory"])

    def test_structured_templates_require_evidence_and_preserve_decision_traceability(self):
        store = self.store()
        span_id = store.create_evidence("default", "git_commit", "Add worktree status", "diff --git", "Add worktree status", "commit-template")
        handoff = store.create_structured_session_context(
            "default", "codex", ".", "feature/templates", [span_id],
            {
                "scope": ["backend/app"], "summary": "Added structured template storage.", "why": "Review needs consistent, cited handoffs.",
                "changed": [{"path": "backend/app/store.py", "summary": "Stored template fields and indexes."}],
                "decisions": "Use SQLite JSON fields with normalized lookup tables.", "validation": "not_run",
                "risks_constraints": "Existing records remain unstructured.", "unresolved": "None.",
            }, "base", "head",
        )
        self.assertEqual(["backend/app"], handoff["scope"])
        self.assertEqual("backend/app/store.py", handoff["changed"][0]["path"])
        store.review_session_context(handoff["id"], "approved")
        decision = store.create_structured_decision(
            "default", handoff["id"], [span_id],
            {
                "category": "architecture", "scope": ["backend/app"], "decision": "Store template-v1 fields locally.",
                "context": "Reviews need consistent, traceable records.", "chosen_approach": "Use SQLite fields and citation tables.",
                "alternatives": [{"option": "Unstructured notes", "reason": "They cannot be reliably retrieved."}],
                "benefits": "Deterministic retrieval.", "costs": "More explicit proposal input.", "follow_up": "None.",
                "applicability": "Forge handoffs and decisions only.",
            },
        )
        self.assertEqual("pending", decision["review_status"])
        self.assertEqual(handoff["id"], decision["source_session_context_id"])
        store.review(decision["id"], "confirmed")
        retrieved = store.retrieve_decisions("default", file_path="backend/app/store.py", scope="backend/app", category="architecture")
        self.assertEqual([decision["id"]], [item["id"] for item in retrieved])
        self.assertEqual("commit-template", retrieved[0]["evidence"][0]["external_id"])

    def test_vault_search_and_export_use_persisted_facts_not_generated_files(self):
        store = self.store()
        store.register_repository("default", self.temporary_directory.name)
        span_id = store.create_evidence("default", "git_commit", "Vault implementation", "safe", "Vault indexing validation passed", "vault-commit")
        handoff = store.create_structured_session_context(
            "default", "codex", ".", "feature/vault", [span_id],
            {
                "scope": ["backend/app"], "summary": "Added deterministic vault indexing.", "why": "Later work needs project-local retrieval.",
                "changed": [{"path": "backend/app/store.py", "summary": "Indexed persisted decision records."}],
                "decisions": "Export generated project files from SQLite.", "validation": "Focused vault test passed.",
                "risks_constraints": "Generated files are not evidence.", "unresolved": "None.",
            },
        )
        store.review_session_context(handoff["id"], "approved")
        decision = store.create_structured_decision(
            "default", handoff["id"], [span_id],
            {
                "category": "architecture", "scope": ["backend/app"], "decision": "Use deterministic vault retrieval.",
                "context": "Project context must stay local and cited.", "chosen_approach": "Index SQLite facts with FTS5.",
                "alternatives": [{"option": "Search Markdown", "reason": "Generated files are not source facts."}],
                "benefits": "Fast local retrieval.", "costs": "Index rebuild work.", "follow_up": "None.",
                "applicability": "Forge vault only.",
            },
        )
        store.review(decision["id"], "confirmed")
        found = store.search_vault("default", "deterministic vault retrieval", scope="backend/app", file_path="backend/app/store.py")
        self.assertEqual([decision["id"]], [entry["record_id"] for entry in found])
        exported = store.export_vault("default")
        context_path = Path(exported["path"]) / "PROJECT_CONTEXT.md"
        initial = context_path.read_text(encoding="utf-8")
        self.assertIn("Forge Project Context", initial)
        context_path.write_text(initial + "\nMANUAL-FALSE-MEMORY\n", encoding="utf-8")
        self.assertEqual([], store.search_vault("default", "MANUAL-FALSE-MEMORY"))
        store.export_vault("default")
        self.assertEqual(initial, context_path.read_text(encoding="utf-8"))

    def test_structured_templates_reject_missing_required_facts(self):
        store = self.store()
        span_id = store.create_evidence("default", "git_commit", "Commit", "diff", "Commit", "commit-invalid")
        with self.assertRaisesRegex(ValueError, "summary is required"):
            store.create_structured_session_context("default", "codex", ".", "main", [span_id], {"scope": ["backend"], "changed": [{"path": "backend/app/store.py", "summary": "Changed storage."}]})

    def test_session_history_searches_text_scope_files_and_archives(self):
        store = self.store()
        span_id = store.create_evidence("default", "git_commit", "Commit", "diff", "Commit", "commit-history")
        handoff = store.create_structured_session_context(
            "default", "codex", ".", "feature/history", [span_id],
            {"scope": ["backend/history"], "summary": "Added searchable handoff history.", "why": "Past work needs evidence drill-down.", "changed": [{"path": "backend/app/store.py", "summary": "Added history filters."}], "decisions": "Use indexed local SQLite lookups.", "validation": "Focused tests passed.", "risks_constraints": "None.", "unresolved": "None."},
        )
        store.review_session_context(handoff["id"], "approved")
        found = store.list_session_contexts("default", query_text="drill-down", scope="backend/history", file_path="backend/app/store.py")
        self.assertEqual([handoff["id"]], [item["id"] for item in found])
        self.assertTrue(store.archive_session_context(handoff["id"]))
        self.assertEqual([], store.list_session_contexts("default", scope="backend/history"))
        self.assertEqual([handoff["id"]], [item["id"] for item in store.list_session_contexts("default", scope="backend/history", include_archived=True)])


if __name__ == "__main__":
    unittest.main()
