import json
import os
import random
import sqlite3
from threading import RLock
from hashlib import sha256
from difflib import unified_diff
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .secrets import protect, unprotect
from .templates import decision_fields, handoff_fields


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    _reconciled_paths: set[Path] = set()

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or ".forge/forge.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        self._connection_lock = RLock()
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self._migrate()

    def _migrate(self):
        self.db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied = {row["version"] for row in self.db.execute("SELECT version FROM schema_migrations")}
        migrations = [(1, """
            CREATE TABLE IF NOT EXISTS repositories (
                workspace_id TEXT PRIMARY KEY, path TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_items (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
                external_id TEXT, title TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(workspace_id, kind, external_id)
            );
            CREATE TABLE IF NOT EXISTS evidence_spans (
                id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES evidence_items(id),
                quote TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, statement TEXT NOT NULL,
                category TEXT NOT NULL, review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'confirmed', 'rejected')),
                created_at TEXT NOT NULL, reviewed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS decision_citations (
                decision_id TEXT NOT NULL REFERENCES decisions(id), span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(decision_id, span_id)
            );
            CREATE TABLE IF NOT EXISTS intentions (
                workspace_id TEXT PRIMARY KEY, statement TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_memory_entries (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id), statement TEXT NOT NULL,
                created_at TEXT NOT NULL, superseded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS connector_state (
                name TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS connector_secrets (
                name TEXT PRIMARY KEY, value BLOB NOT NULL, updated_at TEXT NOT NULL
            );
            """), (2, """
            ALTER TABLE repositories ADD COLUMN remote_url TEXT;
            ALTER TABLE repositories ADD COLUMN branch TEXT;
            ALTER TABLE repositories ADD COLUMN last_ingested_commit TEXT;
            """), (3, """
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, statement TEXT NOT NULL,
                review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'confirmed', 'dismissed')),
                evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(id), created_at TEXT NOT NULL, reviewed_at TEXT
            );
            """), (4, """
            CREATE TABLE IF NOT EXISTS approved_guardrails (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, statement TEXT NOT NULL,
                proposed_diff TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """), (5, """
            ALTER TABLE connector_state ADD COLUMN detail TEXT;
            """), (6, """
            CREATE TABLE IF NOT EXISTS session_contexts (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, agent TEXT NOT NULL,
                worktree_path TEXT NOT NULL, branch TEXT NOT NULL, base_commit TEXT,
                head_commit TEXT, what_changed TEXT NOT NULL, why TEXT NOT NULL,
                decisions TEXT NOT NULL, problems TEXT NOT NULL, fixes TEXT NOT NULL,
                validation TEXT NOT NULL, unresolved TEXT NOT NULL,
                review_status TEXT NOT NULL CHECK(review_status IN ('pending', 'approved', 'dismissed')),
                created_at TEXT NOT NULL, reviewed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS session_context_citations (
                session_context_id TEXT NOT NULL REFERENCES session_contexts(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(session_context_id, span_id)
            );
            """), (7, """
            ALTER TABLE session_contexts ADD COLUMN archived_at TEXT;
            """), (8, """
            CREATE TABLE IF NOT EXISTS agent_session_metadata (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, agent TEXT NOT NULL,
                conversation_id TEXT NOT NULL, workspace_path TEXT NOT NULL,
                execution_num INTEGER, termination_reason TEXT, fully_idle INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS portable_guardrail_adoptions (
                id TEXT PRIMARY KEY, source_guardrail_id TEXT NOT NULL REFERENCES approved_guardrails(id),
                source_workspace_id TEXT NOT NULL, target_workspace_id TEXT NOT NULL,
                statement TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(source_guardrail_id, target_workspace_id)
            );
            """), (9, """
            CREATE TABLE IF NOT EXISTS agent_work_sessions (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, agent TEXT NOT NULL,
                worktree_path TEXT NOT NULL, branch TEXT NOT NULL, base_commit TEXT NOT NULL,
                head_commit TEXT, started_at TEXT NOT NULL, ended_at TEXT
            );
            ALTER TABLE decisions ADD COLUMN source_session_context_id TEXT REFERENCES session_contexts(id);
            """), (10, """
            ALTER TABLE repositories ADD COLUMN git_common_dir TEXT;
            ALTER TABLE repositories ADD COLUMN coordination_base_ref TEXT;
            """), (11, """
            CREATE TABLE IF NOT EXISTS worktrees (
                workspace_id TEXT NOT NULL, worktree_path TEXT NOT NULL,
                git_common_dir TEXT NOT NULL, branch TEXT NOT NULL, head_commit TEXT,
                is_detached INTEGER NOT NULL, is_bare INTEGER NOT NULL,
                is_locked INTEGER NOT NULL, lock_reason TEXT,
                is_prunable INTEGER NOT NULL, prunable_reason TEXT,
                active_session_id TEXT REFERENCES agent_work_sessions(id),
                last_seen_at TEXT NOT NULL, status_checked_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, worktree_path)
            );
            CREATE INDEX IF NOT EXISTS worktrees_common_dir_index ON worktrees(git_common_dir);
            """), (12, """
            ALTER TABLE session_contexts ADD COLUMN template_version INTEGER;
            ALTER TABLE session_contexts ADD COLUMN scope_json TEXT;
            ALTER TABLE session_contexts ADD COLUMN changed_json TEXT;
            ALTER TABLE session_contexts ADD COLUMN summary TEXT;
            ALTER TABLE session_contexts ADD COLUMN risks_constraints TEXT;
            ALTER TABLE decisions ADD COLUMN template_version INTEGER;
            ALTER TABLE decisions ADD COLUMN scope_json TEXT;
            ALTER TABLE decisions ADD COLUMN decision_context TEXT;
            ALTER TABLE decisions ADD COLUMN chosen_approach TEXT;
            ALTER TABLE decisions ADD COLUMN alternatives_json TEXT;
            ALTER TABLE decisions ADD COLUMN benefits TEXT;
            ALTER TABLE decisions ADD COLUMN costs TEXT;
            ALTER TABLE decisions ADD COLUMN follow_up TEXT;
            ALTER TABLE decisions ADD COLUMN applicability TEXT;
            ALTER TABLE decisions ADD COLUMN supersedes_decision_id TEXT REFERENCES decisions(id);
            """), (13, """
            CREATE TABLE IF NOT EXISTS session_context_files (
                session_context_id TEXT NOT NULL REFERENCES session_contexts(id),
                path TEXT NOT NULL, summary TEXT NOT NULL,
                PRIMARY KEY(session_context_id, path)
            );
            CREATE TABLE IF NOT EXISTS decision_scopes (
                decision_id TEXT NOT NULL REFERENCES decisions(id),
                scope TEXT NOT NULL,
                PRIMARY KEY(decision_id, scope)
            );
            CREATE INDEX IF NOT EXISTS session_context_files_path_index ON session_context_files(path);
            CREATE INDEX IF NOT EXISTS decision_scopes_scope_index ON decision_scopes(scope);
            CREATE INDEX IF NOT EXISTS decisions_lookup_index ON decisions(workspace_id, category, review_status, created_at);
            """), (14, """
            CREATE TABLE IF NOT EXISTS session_context_scopes (
                session_context_id TEXT NOT NULL REFERENCES session_contexts(id),
                scope TEXT NOT NULL,
                PRIMARY KEY(session_context_id, scope)
            );
            CREATE INDEX IF NOT EXISTS session_context_scopes_scope_index ON session_context_scopes(scope);
            CREATE INDEX IF NOT EXISTS session_contexts_history_index ON session_contexts(workspace_id, review_status, archived_at, created_at);
            """), (15, """
            CREATE TABLE IF NOT EXISTS github_poll_settings (
                workspace_id TEXT PRIMARY KEY REFERENCES repositories(workspace_id),
                enabled INTEGER NOT NULL DEFAULT 0,
                interval_seconds INTEGER NOT NULL DEFAULT 900,
                next_poll_at TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS github_poll_due_index ON github_poll_settings(enabled, next_poll_at);
            """), (16, """
            CREATE TABLE IF NOT EXISTS agents_guardrail_handoffs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                source_guardrail_id TEXT REFERENCES approved_guardrails(id),
                statement TEXT NOT NULL, target_agents_path TEXT NOT NULL,
                base_content_hash TEXT NOT NULL, target_content_hash TEXT NOT NULL,
                proposed_diff TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending_developer_approval', 'applied')),
                created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS agents_guardrail_handoffs_workspace_index ON agents_guardrail_handoffs(workspace_id, status, created_at);
            """), (17, """
            CREATE TABLE IF NOT EXISTS github_sync_state (
                workspace_id TEXT PRIMARY KEY REFERENCES repositories(workspace_id),
                pull_cursor TEXT, etags TEXT NOT NULL DEFAULT '{}', in_progress INTEGER NOT NULL DEFAULT 0,
                poll_started_at TEXT, last_poll_finished_at TEXT, last_http_status INTEGER,
                last_request_ms INTEGER, rate_limit_remaining INTEGER, rate_limit_limit INTEGER,
                rate_limit_reset_at TEXT, retry_after_at TEXT, last_partial INTEGER NOT NULL DEFAULT 0,
                last_error_kind TEXT, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS github_sync_events (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                occurred_at TEXT NOT NULL, event_type TEXT NOT NULL, health TEXT NOT NULL,
                http_status INTEGER, request_ms INTEGER, detail TEXT, partial INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS github_sync_events_retention_index ON github_sync_events(occurred_at);
            CREATE INDEX IF NOT EXISTS github_sync_events_workspace_index ON github_sync_events(workspace_id, occurred_at DESC);
            """), (18, """
            CREATE TABLE IF NOT EXISTS workspace_rule_policies (
                workspace_id TEXT PRIMARY KEY REFERENCES repositories(workspace_id),
                mode TEXT NOT NULL CHECK(mode IN ('approval', 'autonomous')),
                configured_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_outcomes (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                agent TEXT NOT NULL, worktree_path TEXT NOT NULL, branch TEXT NOT NULL,
                outcome_key TEXT NOT NULL, scope_json TEXT NOT NULL, category TEXT NOT NULL,
                goal TEXT NOT NULL, problem TEXT NOT NULL, prior_approach TEXT NOT NULL,
                why_prior_approach_failed TEXT NOT NULL, alternatives_json TEXT NOT NULL,
                chosen_fix TEXT NOT NULL, rationale TEXT NOT NULL, validation TEXT NOT NULL,
                risk TEXT NOT NULL, unresolved TEXT NOT NULL, proposed_rule TEXT NOT NULL,
                created_at TEXT NOT NULL, UNIQUE(workspace_id, outcome_key)
            );
            CREATE TABLE IF NOT EXISTS session_outcome_citations (
                session_outcome_id TEXT NOT NULL REFERENCES session_outcomes(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(session_outcome_id, span_id)
            );
            CREATE TABLE IF NOT EXISTS rule_versions (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                rule_key TEXT NOT NULL, version INTEGER NOT NULL, statement TEXT NOT NULL,
                scope_json TEXT NOT NULL, category TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('candidate', 'active', 'retracted')),
                activation_mode TEXT NOT NULL CHECK(activation_mode IN ('approval', 'autonomous')),
                source_outcome_id TEXT NOT NULL REFERENCES session_outcomes(id),
                previous_version_id TEXT REFERENCES rule_versions(id),
                evaluation_reason TEXT NOT NULL, created_at TEXT NOT NULL,
                activated_at TEXT, retracted_at TEXT, projection_hash TEXT,
                UNIQUE(workspace_id, rule_key, version)
            );
            CREATE TABLE IF NOT EXISTS rule_version_citations (
                rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(rule_version_id, span_id)
            );
            CREATE TABLE IF NOT EXISTS rule_verifications (
                id TEXT PRIMARY KEY, rule_version_id TEXT NOT NULL REFERENCES rule_versions(id),
                result TEXT NOT NULL CHECK(result IN ('supported', 'contradicted', 'insufficient_data')),
                evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                note TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rule_versions_workspace_index ON rule_versions(workspace_id, state, created_at DESC);
            CREATE INDEX IF NOT EXISTS session_outcomes_workspace_index ON session_outcomes(workspace_id, created_at DESC);
            """), (19, """
            ALTER TABLE session_outcomes ADD COLUMN learning_area TEXT;
            ALTER TABLE session_outcomes ADD COLUMN learning_trigger TEXT;
            ALTER TABLE session_outcomes ADD COLUMN learning_action TEXT;
            ALTER TABLE rule_versions ADD COLUMN learning_area TEXT;
            ALTER TABLE rule_versions ADD COLUMN learning_trigger TEXT;
            ALTER TABLE rule_versions ADD COLUMN learning_action TEXT;
            CREATE INDEX IF NOT EXISTS rule_versions_learning_index ON rule_versions(workspace_id, learning_area, learning_trigger, learning_action, state);
            """), (20, """
            CREATE TABLE IF NOT EXISTS learning_cards (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                rule_key TEXT NOT NULL, scope_json TEXT NOT NULL, area TEXT, trigger TEXT, action TEXT,
                state TEXT NOT NULL CHECK(state IN ('observed', 'watching', 'supported', 'ready', 'active', 'verified', 'contradicted', 'retracted', 'archived')),
                rule_version_id TEXT REFERENCES rule_versions(id), review_due_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, rule_key)
            );
            CREATE TABLE IF NOT EXISTS learning_card_observations (
                card_id TEXT NOT NULL REFERENCES learning_cards(id), outcome_id TEXT NOT NULL REFERENCES session_outcomes(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id), created_at TEXT NOT NULL,
                PRIMARY KEY(card_id, outcome_id, span_id)
            );
            CREATE TABLE IF NOT EXISTS learning_card_alerts (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                card_id TEXT NOT NULL REFERENCES learning_cards(id), related_card_id TEXT REFERENCES learning_cards(id),
                kind TEXT NOT NULL CHECK(kind IN ('possible_duplicate', 'possible_conflict', 'review_due')),
                status TEXT NOT NULL CHECK(status IN ('pending', 'merged', 'kept_separate', 'marked_conflict', 'dismissed')),
                created_at TEXT NOT NULL, resolved_at TEXT, UNIQUE(card_id, related_card_id, kind)
            );
            CREATE INDEX IF NOT EXISTS learning_cards_workspace_index ON learning_cards(workspace_id, state, review_due_at);
            """), (21, """
            CREATE TABLE IF NOT EXISTS validation_runs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                evidence_span_id TEXT NOT NULL UNIQUE REFERENCES evidence_spans(id), validation_id TEXT NOT NULL,
                trusted INTEGER NOT NULL, config_hash TEXT, command_digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('passed', 'failed', 'timed_out', 'unavailable')),
                duration_ms INTEGER NOT NULL, scopes_json TEXT NOT NULL, categories_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS validation_runs_workspace_index ON validation_runs(workspace_id, trusted, status, created_at DESC);
            CREATE TABLE IF NOT EXISTS learning_card_reviews (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                card_id TEXT NOT NULL REFERENCES learning_cards(id), related_card_id TEXT REFERENCES learning_cards(id),
                decision TEXT NOT NULL CHECK(decision IN ('merged', 'kept_separate', 'marked_conflict')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rule_projections (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                rule_version_id TEXT REFERENCES rule_versions(id), operation TEXT NOT NULL CHECK(operation IN ('activate', 'retract')),
                status TEXT NOT NULL CHECK(status IN ('prepared', 'applied', 'failed', 'reverted')),
                target_path TEXT NOT NULL, expected_block_hash TEXT, resulting_block_hash TEXT,
                detail TEXT, created_at TEXT NOT NULL, completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS projection_alerts (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                rule_version_id TEXT REFERENCES rule_versions(id), status TEXT NOT NULL CHECK(status IN ('pending', 'resolved')),
                detail TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT
            );
            ALTER TABLE rule_versions ADD COLUMN learning_card_id TEXT REFERENCES learning_cards(id);
            ALTER TABLE rule_versions ADD COLUMN legacy INTEGER NOT NULL DEFAULT 0;
            CREATE INDEX IF NOT EXISTS rule_versions_card_index ON rule_versions(learning_card_id, created_at DESC);
            """), (22, """
            CREATE TABLE IF NOT EXISTS session_end_events (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                agent TEXT NOT NULL, event_type TEXT NOT NULL CHECK(event_type IN ('completed', 'abandoned')),
                handoff_id TEXT REFERENCES session_outcomes(id), abandon_reason TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS session_end_events_workspace_index ON session_end_events(workspace_id, agent, created_at DESC);
            """), (23, """
            CREATE TABLE IF NOT EXISTS verification_inputs (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                rule_version_id TEXT NOT NULL REFERENCES rule_versions(id), source_kind TEXT NOT NULL CHECK(source_kind IN ('configured_validation', 'git_change', 'github_review', 'local_failure')),
                evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(id), result TEXT NOT NULL CHECK(result IN ('supported', 'contradicted', 'insufficient_data')),
                summary TEXT NOT NULL, developer_confirmed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, applied_at TEXT,
                UNIQUE(rule_version_id, source_kind, evidence_span_id, result)
            );
            CREATE INDEX IF NOT EXISTS verification_inputs_rule_index ON verification_inputs(rule_version_id, created_at DESC);
            """), (24, """
            CREATE TABLE IF NOT EXISTS work_items (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                session_id TEXT, work_item_key TEXT NOT NULL, agent TEXT NOT NULL,
                worktree_path TEXT NOT NULL, branch TEXT NOT NULL, goal TEXT NOT NULL,
                scope_json TEXT NOT NULL, area TEXT,
                status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'abandoned')),
                summary TEXT, rationale TEXT, validation TEXT, risk TEXT, unresolved TEXT,
                started_at TEXT NOT NULL, ended_at TEXT, updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, work_item_key)
            );
            CREATE TABLE IF NOT EXISTS work_item_citations (
                work_item_id TEXT NOT NULL REFERENCES work_items(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(work_item_id, span_id)
            );
            ALTER TABLE session_outcomes ADD COLUMN work_item_id TEXT REFERENCES work_items(id);
            CREATE INDEX IF NOT EXISTS work_items_workspace_index ON work_items(workspace_id, status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS work_items_session_index ON work_items(workspace_id, session_id, updated_at DESC);
            """), (25, """
            CREATE TABLE IF NOT EXISTS learning_observations (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                work_item_id TEXT NOT NULL REFERENCES work_items(id), observation_key TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('technical_error', 'work_behavior', 'decision_pattern')),
                scope_json TEXT NOT NULL, area TEXT NOT NULL, trigger TEXT NOT NULL,
                observed_fact TEXT NOT NULL, hypothesis TEXT NOT NULL, counterexample TEXT NOT NULL,
                next_action TEXT NOT NULL, confidence TEXT NOT NULL CHECK(confidence IN ('low', 'medium', 'high')),
                state TEXT NOT NULL CHECK(state IN ('observed', 'corroborated', 'proposed', 'approved', 'rejected')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, observation_key)
            );
            CREATE TABLE IF NOT EXISTS learning_observation_citations (
                observation_id TEXT NOT NULL REFERENCES learning_observations(id),
                span_id TEXT NOT NULL REFERENCES evidence_spans(id),
                PRIMARY KEY(observation_id, span_id)
            );
            CREATE INDEX IF NOT EXISTS learning_observations_workspace_index ON learning_observations(workspace_id, kind, state, created_at DESC);
            CREATE INDEX IF NOT EXISTS learning_observations_work_item_index ON learning_observations(work_item_id, created_at DESC);
            """), (26, """
            CREATE TABLE IF NOT EXISTS learning_cases (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES repositories(workspace_id),
                case_key TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('technical_error', 'work_behavior', 'decision_pattern')),
                scope_json TEXT NOT NULL, area TEXT NOT NULL, trigger TEXT NOT NULL, next_action TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('observed', 'corroborated', 'proposed', 'approved', 'rejected')),
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id, case_key)
            );
            CREATE TABLE IF NOT EXISTS learning_case_observations (
                case_id TEXT NOT NULL REFERENCES learning_cases(id), observation_id TEXT NOT NULL REFERENCES learning_observations(id),
                created_at TEXT NOT NULL, PRIMARY KEY(case_id, observation_id)
            );
            CREATE INDEX IF NOT EXISTS learning_cases_workspace_index ON learning_cases(workspace_id, state, updated_at DESC);
            """), (27, """
            CREATE VIRTUAL TABLE IF NOT EXISTS vault_search USING fts5(
                record_id UNINDEXED, workspace_id UNINDEXED, record_type UNINDEXED,
                scope UNINDEXED, content
            );
            """), (28, """
            CREATE TABLE IF NOT EXISTS reusable_rules (
                id TEXT PRIMARY KEY, rule_key TEXT NOT NULL UNIQUE, statement TEXT NOT NULL,
                category TEXT NOT NULL, scope_json TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending', 'active', 'retracted')),
                created_at TEXT NOT NULL, requested_at TEXT NOT NULL, approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reusable_rule_sources (
                reusable_rule_id TEXT NOT NULL REFERENCES reusable_rules(id),
                repository_key TEXT NOT NULL, repository_path TEXT NOT NULL,
                workspace_id TEXT NOT NULL, rule_version_id TEXT NOT NULL,
                evidence_count INTEGER NOT NULL, recorded_at TEXT NOT NULL,
                PRIMARY KEY(reusable_rule_id, repository_key)
            );
            CREATE TABLE IF NOT EXISTS project_reusable_rule_overrides (
                workspace_id TEXT NOT NULL, reusable_rule_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('ignore', 'replace')),
                statement TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(workspace_id, reusable_rule_id)
            );
            CREATE TABLE IF NOT EXISTS session_feedback (
                id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, handoff_id TEXT NOT NULL REFERENCES session_outcomes(id),
                context_useful TEXT NOT NULL CHECK(context_useful IN ('yes', 'no', 'partly')),
                irrelevant_or_missing TEXT NOT NULL, rule_assessment TEXT NOT NULL CHECK(rule_assessment IN ('approve', 'revise', 'coaching_only', 'reject')),
                evidence_span_id TEXT NOT NULL REFERENCES evidence_spans(id), created_at TEXT NOT NULL,
                UNIQUE(workspace_id, handoff_id)
            );
            """), (29, """
            ALTER TABLE github_sync_state ADD COLUMN checkpoints TEXT NOT NULL DEFAULT '{}';
            """), (30, """
            CREATE TABLE IF NOT EXISTS vault_search_state (
                workspace_id TEXT PRIMARY KEY,
                source_hash TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            """)]
        migrated = False
        for version, migration in migrations:
            if version not in applied:
                self.db.executescript(migration)
                self.db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))
                migrated = True
        if 29 not in applied:
            self.db.execute("UPDATE evidence_items SET content=title WHERE kind IN ('git_commit', 'github_pull_request', 'github_review', 'github_review_comment')")
            self.db.execute("UPDATE evidence_spans SET quote='[redacted legacy Git diff hunk]' WHERE quote LIKE '@@%'")
        self.db.commit()
        if migrated:
            self._backfill_learning_cards()
            self._backfill_learning_card_links()
        if self.path.resolve() not in self._reconciled_paths:
            self._reconcile_projections()
            self._reconciled_paths.add(self.path.resolve())

    def _backfill_learning_cards(self):
        rows = self.db.execute("SELECT id, workspace_id, rule_key, scope_json, learning_area, learning_trigger, learning_action, state, created_at, activated_at FROM rule_versions").fetchall()
        for row in rows:
            card_state = {"candidate": "watching", "active": "active", "retracted": "retracted"}[row["state"]]
            due = (datetime.fromisoformat(row["activated_at"]) + timedelta(days=90)).isoformat() if row["activated_at"] else None
            self.db.execute("INSERT OR IGNORE INTO learning_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid4()), row["workspace_id"], row["rule_key"], row["scope_json"], row["learning_area"], row["learning_trigger"], row["learning_action"], card_state, row["id"], due, row["created_at"], now()))
        self.db.commit()

    def _backfill_learning_card_links(self):
        rows = self.db.execute("SELECT id, workspace_id, rule_key FROM rule_versions WHERE learning_card_id IS NULL").fetchall()
        for row in rows:
            card = self.db.execute("SELECT id FROM learning_cards WHERE workspace_id=? AND rule_key=?", (row["workspace_id"], row["rule_key"])).fetchone()
            if card:
                self.db.execute("UPDATE rule_versions SET learning_card_id=?, legacy=1 WHERE id=?", (card["id"], row["id"]))
        self.db.commit()

    def _reconcile_projections(self):
        rows = self.db.execute("SELECT * FROM rule_projections WHERE status='prepared'").fetchall()
        for row in rows:
            path = Path(row["target_path"])
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            block_hash = self._managed_block_hash(current)
            if block_hash == row["resulting_block_hash"]:
                self.db.execute("UPDATE rule_projections SET status='applied', completed_at=? WHERE id=?", (now(), row["id"]))
            else:
                self.db.execute("UPDATE rule_projections SET status='failed', detail=?, completed_at=? WHERE id=?", ("Projection recovery could not verify the managed block.", now(), row["id"]))
        self.db.commit()

    def close(self):
        self.db.close()

    def integrity_check(self):
        result = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        return {"database": str(self.path.resolve()), "integrity": result, "ok": result == "ok"}

    def backup(self, path: str | Path):
        target = Path(path)
        if target.exists():
            raise FileExistsError(f"Backup already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(target)
        try:
            self.db.backup(destination)
        finally:
            destination.close()
        return str(target.resolve())

    def export(self, path: str | Path):
        target = Path(path)
        if target.exists():
            raise FileExistsError(f"Export already exists: {target}")
        tables = ("repositories", "evidence_items", "evidence_spans", "decisions", "decision_citations", "decision_scopes", "reflections", "intentions", "project_memory_entries", "session_contexts", "session_context_citations", "session_context_files", "session_context_scopes", "agent_work_sessions", "worktrees", "connector_state", "github_poll_settings", "agents_guardrail_handoffs", "workspace_rule_policies", "session_outcomes", "session_outcome_citations", "session_end_events", "validation_runs", "learning_cards", "learning_card_observations", "learning_card_alerts", "learning_card_reviews", "rule_versions", "rule_version_citations", "rule_verifications", "verification_inputs", "rule_projections", "projection_alerts", "reusable_rules", "reusable_rule_sources", "project_reusable_rule_overrides", "session_feedback")
        data = {table: [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")] for table in tables}
        for evidence in data["evidence_items"]:
            evidence.pop("content", None)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(target.resolve())

    def register_repository(self, workspace_id: str, path: str, remote_url: str | None = None, branch: str | None = None, git_common_dir: str | None = None):
        self.db.execute(
            "INSERT INTO repositories (workspace_id, path, created_at, remote_url, branch, git_common_dir) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET path=excluded.path, remote_url=excluded.remote_url, branch=excluded.branch, git_common_dir=COALESCE(excluded.git_common_dir, repositories.git_common_dir)",
            (workspace_id, str(Path(path).resolve()), now(), remote_url, branch, str(Path(git_common_dir).resolve()) if git_common_dir else None),
        )
        self.db.commit()

    def repository(self, workspace_id: str):
        row = self.db.execute("SELECT * FROM repositories WHERE workspace_id=?", (workspace_id,)).fetchone()
        return dict(row) if row else None

    def repositories(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM repositories ORDER BY created_at ASC").fetchall()]

    def workspace_for_path(self, path: str | Path):
        resolved = str(Path(path).resolve()).lower()
        row = self.db.execute("SELECT workspace_id FROM repositories WHERE lower(path)=?", (resolved,)).fetchone()
        return row["workspace_id"] if row else None

    def workspace_for_git_common_dir(self, git_common_dir: str | Path):
        resolved = str(Path(git_common_dir).resolve()).lower()
        row = self.db.execute("SELECT workspace_id FROM repositories WHERE lower(git_common_dir)=?", (resolved,)).fetchone()
        return row["workspace_id"] if row else None

    def set_coordination_base_ref(self, workspace_id: str, base_ref: str | None):
        self.db.execute("UPDATE repositories SET coordination_base_ref=? WHERE workspace_id=?", (base_ref or None, workspace_id))
        self.db.commit()
        return self.repository(workspace_id)

    def active_or_recent_work_sessions(self, workspace_id: str, recent_since: str):
        rows = self.db.execute(
            "SELECT * FROM agent_work_sessions WHERE workspace_id=? AND (ended_at IS NULL OR ended_at>=?) "
            "ORDER BY ended_at IS NULL DESC, started_at DESC",
            (workspace_id, recent_since),
        ).fetchall()
        sessions = {}
        for row in rows:
            session = dict(row)
            sessions.setdefault(session["worktree_path"].lower(), session)
        return list(sessions.values())

    def sync_worktrees(self, workspace_id: str, git_common_dir: str, worktrees: list[dict]):
        timestamp = now()
        self.db.executemany(
            "INSERT INTO worktrees (workspace_id, worktree_path, git_common_dir, branch, head_commit, is_detached, is_bare, is_locked, lock_reason, is_prunable, prunable_reason, active_session_id, last_seen_at, status_checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(workspace_id, worktree_path) DO UPDATE SET git_common_dir=excluded.git_common_dir, branch=excluded.branch, head_commit=excluded.head_commit, is_detached=excluded.is_detached, is_bare=excluded.is_bare, is_locked=excluded.is_locked, lock_reason=excluded.lock_reason, is_prunable=excluded.is_prunable, prunable_reason=excluded.prunable_reason, active_session_id=excluded.active_session_id, last_seen_at=excluded.last_seen_at, status_checked_at=excluded.status_checked_at",
            [
                (workspace_id, item["worktree_path"], git_common_dir, item["branch"], item["head_commit"], int(item["is_detached"]), int(item["is_bare"]), int(item["is_locked"]), item["lock_reason"], int(item["is_prunable"]), item["prunable_reason"], item["active_session_id"], timestamp, item["checked_at"])
                for item in worktrees
            ],
        )
        self.db.commit()

    def update_repository_head(self, workspace_id: str, commit: str):
        self.db.execute("UPDATE repositories SET last_ingested_commit=? WHERE workspace_id=?", (commit, workspace_id))
        self.db.commit()

    def create_evidence(self, workspace_id: str, kind: str, title: str, content: str, quote: str, external_id: str | None = None, metadata: dict | None = None, spans: list[str] | None = None):
        with self._connection_lock:
            existing = None
            if external_id:
                existing = self.db.execute("SELECT id FROM evidence_items WHERE workspace_id=? AND kind=? AND external_id=?", (workspace_id, kind, external_id)).fetchone()
            if existing:
                return self.db.execute("SELECT id FROM evidence_spans WHERE evidence_id=?", (existing["id"],)).fetchone()["id"]
            evidence_id, span_id = str(uuid4()), str(uuid4())
            self.db.execute("INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (evidence_id, workspace_id, kind, external_id, title, content, json.dumps(metadata or {}), now()))
            for span in dict.fromkeys([quote, *(spans or [])]):
                self.db.execute("INSERT INTO evidence_spans VALUES (?, ?, ?, ?)", (span_id if span == quote else str(uuid4()), evidence_id, span, now()))
            self.db.commit()
            return span_id

    def record_validation_result(self, workspace_id: str, label: str, status: str, exit_code: int | None, duration_ms: int, command_name: str, command_digest: str, trusted: bool = False, config_hash: str | None = None, scopes: list[str] | None = None, categories: list[str] | None = None):
        if status not in {"passed", "failed", "timed_out", "unavailable"}:
            raise ValueError("Unsupported validation status.")
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        label = self._outcome_text(label, "validation label", 200)
        command_name = self._outcome_text(command_name, "validation command", 200)
        if duration_ms < 0:
            raise ValueError("Validation duration cannot be negative.")
        run_id = str(uuid4())
        title = f"Validation {status}: {label}"
        quote = f"{label}: {status}" + (f" (exit {exit_code})" if exit_code is not None else "")
        span_id = self.create_evidence(
            workspace_id, "local_validation", title, quote, quote, run_id,
            {"captured_by": "forge", "trusted": trusted, "config_hash": config_hash, "status": status, "exit_code": exit_code, "duration_ms": duration_ms, "command_name": command_name, "command_digest": command_digest},
        )
        self.db.execute(
            "INSERT INTO validation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, workspace_id, span_id, label, int(trusted), config_hash, command_digest, status, duration_ms, json.dumps(sorted(set(scopes or []))), json.dumps(sorted(set(categories or []))), now()),
        )
        self.db.commit()
        return {"span_id": span_id, "validation_run_id": run_id, "label": label, "status": status, "exit_code": exit_code, "duration_ms": duration_ms, "trusted": trusted}

    def has_evidence(self, workspace_id: str, kind: str, external_id: str) -> bool:
        return bool(self.db.execute("SELECT 1 FROM evidence_items WHERE workspace_id=? AND kind=? AND external_id=?", (workspace_id, kind, external_id)).fetchone())

    def list_evidence(self, workspace_id: str, kind: str = "git_commit", limit: int = 20):
        with self._connection_lock:
            rows = self.db.execute(
                "SELECT id, kind, external_id, title, metadata, created_at FROM evidence_items WHERE workspace_id=? AND kind=? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, kind, limit),
            ).fetchall()
            return [{**dict(row), "metadata": json.loads(row["metadata"] or "{}")} for row in rows]

    def evidence_count(self, workspace_id: str, kind: str) -> int:
        return self.db.execute("SELECT COUNT(*) AS count FROM evidence_items WHERE workspace_id=? AND kind=?", (workspace_id, kind)).fetchone()["count"]

    def get_evidence(self, evidence_id: str):
        with self._connection_lock:
            row = self.db.execute("SELECT * FROM evidence_items WHERE id=?", (evidence_id,)).fetchone()
            if not row:
                return None
            evidence = dict(row)
            evidence["metadata"] = json.loads(evidence["metadata"] or "{}")
            evidence["spans"] = [dict(span) for span in self.db.execute("SELECT id, quote, created_at FROM evidence_spans WHERE evidence_id=?", (evidence_id,)).fetchall()]
            return evidence

    def recent_evidence_spans(self, workspace_id: str, limit: int = 20):
        rows = self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote, e.created_at "
            "FROM evidence_spans s JOIN evidence_items e ON e.id=s.evidence_id "
            "WHERE e.workspace_id=? ORDER BY e.created_at DESC LIMIT ?",
            (workspace_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _workspace_span_ids(self, workspace_id: str, span_ids: list[str]) -> list[str]:
        unique_ids = list(dict.fromkeys(span_ids))
        if not unique_ids:
            raise ValueError("At least one existing evidence span is required.")
        placeholders = ",".join("?" for _ in unique_ids)
        rows = self.db.execute(
            f"SELECT s.id FROM evidence_spans s JOIN evidence_items e ON e.id=s.evidence_id WHERE e.workspace_id=? AND s.id IN ({placeholders})",
            (workspace_id, *unique_ids),
        ).fetchall()
        if {row["id"] for row in rows} != set(unique_ids):
            raise ValueError("Every citation must be an existing evidence span from this project.")
        return unique_ids

    def create_pending(self, workspace_id: str, statement: str, category: str, evidence_quote: str, source: str = "agent_decision", evidence_span_ids: list[str] | None = None, source_session_context_id: str | None = None):
        if source_session_context_id:
            session = self.get_session_context(source_session_context_id)
            if not session or session["workspace_id"] != workspace_id or session["review_status"] != "approved":
                raise ValueError("A decision can only be proposed from an approved session context in this project.")
        span_ids = self._workspace_span_ids(workspace_id, evidence_span_ids) if evidence_span_ids else [self.create_evidence(workspace_id, source, "Agent supplied evidence", evidence_quote, evidence_quote)]
        decision_id = str(uuid4())
        self.db.execute("INSERT INTO decisions (id, workspace_id, statement, category, review_status, created_at, reviewed_at, source_session_context_id) VALUES (?, ?, ?, ?, 'pending', ?, NULL, ?)", (decision_id, workspace_id, statement, category, now(), source_session_context_id))
        self.db.executemany("INSERT INTO decision_citations VALUES (?, ?)", [(decision_id, span_id) for span_id in span_ids])
        self.db.commit()
        return self.get_decision(decision_id)

    def create_reflection(self, workspace_id: str, statement: str, evidence_quote: str):
        span_id = self.create_evidence(workspace_id, "agent_reflection", "Agent supplied reflection", evidence_quote, evidence_quote)
        reflection_id = str(uuid4())
        self.db.execute("INSERT INTO reflections VALUES (?, ?, ?, 'pending', ?, ?, NULL)", (reflection_id, workspace_id, statement, span_id, now()))
        self.db.commit()
        return self.get_reflection(reflection_id)

    def get_reflection(self, reflection_id: str):
        row = self.db.execute("SELECT r.*, s.quote AS evidence_quote FROM reflections r JOIN evidence_spans s ON s.id=r.evidence_span_id WHERE r.id=?", (reflection_id,)).fetchone()
        return dict(row) if row else None

    def pending_reflection(self, workspace_id: str):
        row = self.db.execute("SELECT id FROM reflections WHERE workspace_id=? AND review_status='pending' ORDER BY created_at ASC LIMIT 1", (workspace_id,)).fetchone()
        return self.get_reflection(row["id"]) if row else None

    def list_reflections(self, workspace_id: str):
        rows = self.db.execute("SELECT id FROM reflections WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [self.get_reflection(row["id"]) for row in rows]

    def history(self, workspace_id: str):
        return {"decisions": self.list_decisions(workspace_id), "reflections": self.list_reflections(workspace_id), "session_contexts": self.list_session_contexts(workspace_id)}

    def review_reflection(self, reflection_id: str, status: str):
        reflection = self.get_reflection(reflection_id)
        if not reflection:
            return None
        if reflection["review_status"] != "pending":
            return {"error": "already_reviewed", "reflection": reflection}
        self.db.execute("UPDATE reflections SET review_status=?, reviewed_at=? WHERE id=?", (status, now(), reflection_id))
        self.db.commit()
        return {"reflection": self.get_reflection(reflection_id)}

    def get_decision(self, decision_id: str):
        row = self.db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["evidence_quote"] = self.db.execute(
            "SELECT s.quote FROM evidence_spans s JOIN decision_citations c ON c.span_id=s.id WHERE c.decision_id=? LIMIT 1", (decision_id,)
        ).fetchone()["quote"]
        result["scope"] = json.loads(result.pop("scope_json")) if result.get("scope_json") else []
        result["alternatives"] = json.loads(result.pop("alternatives_json")) if result.get("alternatives_json") else []
        result["evidence"] = [dict(row) for row in self.db.execute(
            "SELECT s.id AS span_id, e.external_id, e.kind, s.quote FROM decision_citations c "
            "JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.decision_id=?",
            (decision_id,),
        ).fetchall()]
        return result

    def list_decisions(self, workspace_id: str):
        rows = self.db.execute("SELECT id FROM decisions WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)).fetchall()
        return [self.get_decision(row["id"]) for row in rows]

    def review(self, decision_id: str, status: str, statement: str | None = None):
        decision = self.get_decision(decision_id)
        if not decision:
            return None
        if decision["review_status"] != "pending":
            return {"error": "already_reviewed", "decision": decision}
        self.db.execute("UPDATE decisions SET statement=COALESCE(?, statement), review_status=?, reviewed_at=? WHERE id=?", (statement, status, now(), decision_id))
        if status == "confirmed":
            confirmed = self.get_decision(decision_id)
            self.db.execute("INSERT INTO project_memory_entries VALUES (?, ?, ?, ?, ?, NULL)", (str(uuid4()), confirmed["workspace_id"], decision_id, confirmed["statement"], now()))
            if confirmed.get("supersedes_decision_id"):
                self.db.execute(
                    "UPDATE project_memory_entries SET superseded_at=? WHERE decision_id=? AND workspace_id=? AND superseded_at IS NULL",
                    (now(), confirmed["supersedes_decision_id"], confirmed["workspace_id"]),
                )
        self.db.commit()
        return {"decision": self.get_decision(decision_id), "memory_created": status == "confirmed"}

    def set_intention(self, workspace_id: str, statement: str):
        self.db.execute("INSERT INTO intentions VALUES (?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET statement=excluded.statement, created_at=excluded.created_at", (workspace_id, statement, now()))
        self.db.commit()

    def active_intention(self, workspace_id: str):
        row = self.db.execute("SELECT statement, created_at FROM intentions WHERE workspace_id=?", (workspace_id,)).fetchone()
        return dict(row) if row else {"status": "insufficient_data", "reason": "No active intention selected."}

    def create_session_context(self, workspace_id: str, agent: str, worktree_path: str, branch: str, what_changed: str, why: str, decisions: str, problems: str, fixes: str, validation: str, unresolved: str, evidence_span_ids: list[str], base_commit: str | None = None, head_commit: str | None = None):
        span_ids = self._workspace_span_ids(workspace_id, evidence_span_ids)
        session_id = str(uuid4())
        self.db.execute(
            "INSERT INTO session_contexts (id, workspace_id, agent, worktree_path, branch, base_commit, head_commit, what_changed, why, decisions, problems, fixes, validation, unresolved, review_status, created_at, reviewed_at, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)",
            (session_id, workspace_id, agent, str(Path(worktree_path).resolve()), branch, base_commit, head_commit, what_changed, why, decisions, problems, fixes, validation, unresolved, now()),
        )
        self.db.executemany("INSERT INTO session_context_citations VALUES (?, ?)", [(session_id, span_id) for span_id in span_ids])
        self.db.commit()
        return self.get_session_context(session_id)

    def create_structured_session_context(self, workspace_id: str, agent: str, worktree_path: str, branch: str, evidence_span_ids: list[str], template: dict, base_commit: str | None = None, head_commit: str | None = None):
        fields = handoff_fields(template)
        context = self.create_session_context(
            workspace_id, agent, worktree_path, branch, fields["summary"], fields["why"], fields["decisions"],
            fields["risks_constraints"], "unknown", fields["validation"], fields["unresolved"], evidence_span_ids,
            base_commit, head_commit,
        )
        self.db.execute(
            "UPDATE session_contexts SET template_version=?, scope_json=?, changed_json=?, summary=?, risks_constraints=? WHERE id=?",
            (fields["template_version"], json.dumps(fields["scope"]), json.dumps(fields["changed"]), fields["summary"], fields["risks_constraints"], context["id"]),
        )
        self.db.executemany(
            "INSERT INTO session_context_files VALUES (?, ?, ?)",
            [(context["id"], item["path"], item["summary"]) for item in fields["changed"]],
        )
        self.db.executemany("INSERT INTO session_context_scopes VALUES (?, ?)", [(context["id"], scope) for scope in fields["scope"]])
        self.db.commit()
        return self.get_session_context(context["id"])

    def create_structured_decision(self, workspace_id: str, source_session_context_id: str, evidence_span_ids: list[str], template: dict):
        fields = decision_fields(template)
        source = self.get_session_context(source_session_context_id)
        if not source or source["workspace_id"] != workspace_id or source["review_status"] != "approved":
            raise ValueError("A structured decision requires an approved handoff from this workspace.")
        if fields["supersedes_decision_id"]:
            superseded = self.get_decision(fields["supersedes_decision_id"])
            if not superseded or superseded["workspace_id"] != workspace_id:
                raise ValueError("supersedes_decision_id must refer to a decision in this workspace.")
        decision = self.create_pending(
            workspace_id, fields["decision"], fields["category"], fields["chosen_approach"],
            evidence_span_ids=evidence_span_ids, source_session_context_id=source_session_context_id,
        )
        self.db.execute(
            "UPDATE decisions SET template_version=?, scope_json=?, decision_context=?, chosen_approach=?, alternatives_json=?, benefits=?, costs=?, follow_up=?, applicability=?, supersedes_decision_id=? WHERE id=?",
            (fields["template_version"], json.dumps(fields["scope"]), fields["context"], fields["chosen_approach"], json.dumps(fields["alternatives"]), fields["benefits"], fields["costs"], fields["follow_up"], fields["applicability"], fields["supersedes_decision_id"], decision["id"]),
        )
        self.db.executemany("INSERT INTO decision_scopes VALUES (?, ?)", [(decision["id"], scope) for scope in fields["scope"]])
        self.db.commit()
        return self.get_decision(decision["id"])

    def create_session_contexts(self, workspace_id: str, handoffs: list[dict]):
        if not handoffs:
            raise ValueError("At least one handoff is required.")
        return [self.create_session_context(workspace_id=workspace_id, **handoff) for handoff in handoffs]

    def start_work_session(self, workspace_id: str, agent: str, worktree_path: str, branch: str, base_commit: str):
        session_id = str(uuid4())
        self.db.execute("INSERT INTO agent_work_sessions VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL)", (session_id, workspace_id, agent, str(Path(worktree_path).resolve()), branch, base_commit, now()))
        self.db.commit()
        return self.get_work_session(session_id)

    def get_work_session(self, session_id: str):
        row = self.db.execute("SELECT * FROM agent_work_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def finish_work_session(self, session_id: str, head_commit: str):
        result = self.db.execute("UPDATE agent_work_sessions SET head_commit=?, ended_at=? WHERE id=? AND ended_at IS NULL", (head_commit, now(), session_id))
        if not result.rowcount:
            raise ValueError("Open work session not found.")
        self.db.commit()
        return self.get_work_session(session_id)

    def get_session_context(self, session_id: str):
        row = self.db.execute("SELECT * FROM session_contexts WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        context = dict(row)
        context["citations"] = [dict(citation) for citation in self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote FROM session_context_citations c "
            "JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id "
            "WHERE c.session_context_id=?", (session_id,)
        ).fetchall()]
        context["scope"] = json.loads(context.pop("scope_json")) if context.get("scope_json") else []
        context["changed"] = json.loads(context.pop("changed_json")) if context.get("changed_json") else []
        return context

    def list_session_contexts(self, workspace_id: str, status: str | None = None, limit: int = 20, query_text: str | None = None, scope: str | None = None, file_path: str | None = None, include_archived: bool = False):
        query = "SELECT DISTINCT sc.id FROM session_contexts sc"
        conditions, arguments = ["sc.workspace_id=?"], [workspace_id]
        if scope:
            query += " JOIN session_context_scopes scs ON scs.session_context_id=sc.id"
            conditions.append("scs.scope=?")
            arguments.append(scope)
        if file_path:
            query += " JOIN session_context_files scf ON scf.session_context_id=sc.id"
            conditions.append("scf.path=?")
            arguments.append(file_path)
        if not include_archived:
            conditions.append("sc.archived_at IS NULL")
        if status:
            conditions.append("sc.review_status=?")
            arguments.append(status)
        if query_text and query_text.strip():
            conditions.append("LOWER(COALESCE(sc.summary, sc.what_changed) || ' ' || sc.why || ' ' || sc.decisions || ' ' || sc.validation || ' ' || sc.unresolved || ' ' || COALESCE(sc.risks_constraints, sc.problems)) LIKE ?")
            arguments.append(f"%{query_text.strip().lower()}%")
        query += " WHERE " + " AND ".join(conditions) + " ORDER BY sc.created_at DESC LIMIT ?"
        arguments.append(limit)
        return [self.get_session_context(row["id"]) for row in self.db.execute(query, arguments).fetchall()]

    def retrieve_decisions(self, workspace_id: str, file_path: str | None = None, scope: str | None = None, category: str | None = None, status: str | None = "confirmed", limit: int = 20):
        query = "SELECT DISTINCT d.id FROM decisions d"
        conditions, arguments = ["d.workspace_id=?"], [workspace_id]
        if scope:
            query += " JOIN decision_scopes ds ON ds.decision_id=d.id"
            conditions.append("ds.scope=?")
            arguments.append(scope)
        if file_path:
            query += " JOIN session_context_files scf ON scf.session_context_id=d.source_session_context_id"
            conditions.append("scf.path=?")
            arguments.append(file_path)
        if category:
            conditions.append("d.category=?")
            arguments.append(category)
        if status:
            conditions.append("d.review_status=?")
            arguments.append(status)
        query += " WHERE " + " AND ".join(conditions) + " ORDER BY d.created_at DESC LIMIT ?"
        arguments.append(max(1, min(limit, 100)))
        return [self.get_decision(row["id"]) for row in self.db.execute(query, arguments).fetchall()]

    def pending_session_context(self, workspace_id: str):
        row = self.db.execute("SELECT id FROM session_contexts WHERE workspace_id=? AND review_status='pending' ORDER BY created_at ASC LIMIT 1", (workspace_id,)).fetchone()
        return self.get_session_context(row["id"]) if row else None

    def review_session_context(self, session_id: str, status: str):
        session = self.get_session_context(session_id)
        if not session:
            return None
        if session["review_status"] != "pending":
            return {"error": "already_reviewed", "session_context": session}
        self.db.execute("UPDATE session_contexts SET review_status=?, reviewed_at=? WHERE id=?", (status, now(), session_id))
        self.db.commit()
        return {"session_context": self.get_session_context(session_id)}

    def archive_session_context(self, session_id: str):
        result = self.db.execute("UPDATE session_contexts SET archived_at=? WHERE id=? AND review_status='approved' AND archived_at IS NULL", (now(), session_id))
        self.db.commit()
        return result.rowcount == 1

    def context(self, workspace_id: str):
        rows = self.db.execute("SELECT id, decision_id FROM project_memory_entries WHERE workspace_id=? AND superseded_at IS NULL ORDER BY created_at DESC LIMIT 12", (workspace_id,)).fetchall()
        memory = [{**self.get_decision(row["decision_id"]), "memory_entry_id": row["id"]} for row in rows]
        return {
            "workspace_id": workspace_id,
            "memory": memory,
            "active_intention": self.active_intention(workspace_id),
            "recent_session_outcomes": self.list_session_outcomes(workspace_id, limit=3),
            "recent_session_context": self.list_session_contexts(workspace_id, "approved", limit=3),
            "pending_rule_candidates": self.list_rule_versions(workspace_id, "candidate"),
        }

    def archive_memory(self, entry_id: str):
        result = self.db.execute("UPDATE project_memory_entries SET superseded_at=? WHERE id=? AND superseded_at IS NULL", (now(), entry_id))
        self.db.commit()
        return result.rowcount == 1

    def today(self, workspace_id: str):
        pending = next((item for item in self.list_decisions(workspace_id) if item["review_status"] == "pending"), None)
        context = self.context(workspace_id)
        pending_contexts = self.list_session_contexts(workspace_id, "pending", limit=20)
        return {"workspace_id": workspace_id, "intention": self.active_intention(workspace_id), "memory": context["memory"][:1], "recent_session_outcomes": context["recent_session_outcomes"], "recent_session_context": context["recent_session_context"], "pending_rule_candidates": context["pending_rule_candidates"], "pending_decision": pending, "pending_reflection": self.pending_reflection(workspace_id), "pending_session_context": pending_contexts[0] if pending_contexts else None, "pending_session_contexts": pending_contexts}

    def guardrail_candidates(self, workspace_id: str):
        rows = self.db.execute(
            "SELECT statement, COUNT(*) AS count FROM decisions WHERE workspace_id=? AND review_status='confirmed' GROUP BY statement HAVING count >= 2",
            (workspace_id,),
        ).fetchall()
        candidates = [{"statement": row["statement"], "citations": [item for item in self.list_decisions(workspace_id) if item["review_status"] == "confirmed" and item["statement"] == row["statement"]]} for row in rows]
        if not candidates:
            return {"status": "insufficient_data", "minimum_confirmations": 2, "reason": "A guardrail needs two matching developer-confirmed decisions.", "candidates": []}
        return {"status": "ready", "minimum_confirmations": 2, "candidates": candidates}

    def propose_agents_guardrail(self, workspace_id: str, statement: str, current_agents_content: str):
        eligible = {candidate["statement"] for candidate in self.guardrail_candidates(workspace_id)["candidates"]}
        if statement not in eligible:
            return {"status": "insufficient_data", "reason": "This guardrail does not yet have two matching confirmed decisions."}
        before = current_agents_content.rstrip() + ("\n" if current_agents_content else "")
        if statement in current_agents_content:
            return {"status": "already_present", "diff": "", "statement": statement}
        after = before + ("\n" if before else "") + "## Confirmed Guardrails\n\n" + f"- {statement}\n"
        diff = "".join(unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="AGENTS.md", tofile="AGENTS.md"))
        return {"status": "pending_developer_approval", "statement": statement, "diff": diff}

    @staticmethod
    def _content_hash(content: str) -> str:
        return sha256(content.encode("utf-8")).hexdigest()

    def _guardrail_target_content(self, statement: str, current_agents_content: str) -> str | None:
        if statement in current_agents_content:
            return None
        before = current_agents_content.rstrip() + ("\n" if current_agents_content else "")
        heading = "" if "## Confirmed Guardrails" in before else "\n## Confirmed Guardrails\n"
        return before + heading + f"\n- {statement}\n"

    def prepare_agents_guardrail_handoff(self, workspace_id: str, statement: str, current_agents_content: str, target_agents_path: str = "AGENTS.md", source_guardrail_id: str | None = None):
        if Path(target_agents_path).name != "AGENTS.md":
            raise ValueError("target_agents_path must name an AGENTS.md file.")
        if source_guardrail_id:
            source = self.db.execute("SELECT * FROM approved_guardrails WHERE id=?", (source_guardrail_id,)).fetchone()
            if not source or source["workspace_id"] == workspace_id:
                raise ValueError("Select an approved guardrail from another project.")
            statement = source["statement"]
        elif statement not in {candidate["statement"] for candidate in self.guardrail_candidates(workspace_id)["candidates"]}:
            return {"status": "insufficient_data", "reason": "This guardrail does not yet have two matching confirmed decisions."}
        target_content = self._guardrail_target_content(statement, current_agents_content)
        if target_content is None:
            return {"status": "already_present", "statement": statement, "target_agents_path": target_agents_path}
        proposal_id = str(uuid4())
        diff = "".join(unified_diff(current_agents_content.splitlines(keepends=True), target_content.splitlines(keepends=True), fromfile=target_agents_path, tofile=target_agents_path))
        self.db.execute(
            "INSERT INTO agents_guardrail_handoffs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (proposal_id, workspace_id, source_guardrail_id, statement, target_agents_path, self._content_hash(current_agents_content), self._content_hash(target_content), diff, "pending_developer_approval", now()),
        )
        self.db.commit()
        return self.get_agents_guardrail_handoff(proposal_id)

    def get_agents_guardrail_handoff(self, handoff_id: str):
        row = self.db.execute("SELECT * FROM agents_guardrail_handoffs WHERE id=?", (handoff_id,)).fetchone()
        return dict(row) if row else None

    def list_agents_guardrail_handoffs(self, workspace_id: str, limit: int = 20):
        rows = self.db.execute("SELECT * FROM agents_guardrail_handoffs WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(limit, 100)))).fetchall()
        return [dict(row) for row in rows]

    def complete_agents_guardrail_handoff(self, handoff_id: str, developer_approved: bool, resulting_agents_content: str):
        if not developer_approved:
            raise ValueError("Complete a handoff only after the developer explicitly approved the shown diff.")
        handoff = self.get_agents_guardrail_handoff(handoff_id)
        if not handoff or handoff["status"] != "pending_developer_approval":
            raise ValueError("Pending AGENTS.md handoff not found.")
        if self._content_hash(resulting_agents_content) != handoff["target_content_hash"]:
            raise ValueError("The resulting AGENTS.md content does not match the developer-approved proposal.")
        self.db.execute("UPDATE agents_guardrail_handoffs SET status='applied', completed_at=? WHERE id=?", (now(), handoff_id))
        if handoff["source_guardrail_id"]:
            source = self.db.execute("SELECT * FROM approved_guardrails WHERE id=?", (handoff["source_guardrail_id"],)).fetchone()
            self.db.execute(
                "INSERT OR IGNORE INTO portable_guardrail_adoptions VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), handoff["source_guardrail_id"], source["workspace_id"], handoff["workspace_id"], handoff["statement"], now()),
            )
        else:
            self.db.execute("INSERT INTO approved_guardrails VALUES (?, ?, ?, ?, ?)", (str(uuid4()), handoff["workspace_id"], handoff["statement"], handoff["proposed_diff"], now()))
        self.db.commit()
        return self.get_agents_guardrail_handoff(handoff_id)

    def record_guardrail_approval(self, workspace_id: str, statement: str, proposed_diff: str):
        self.db.execute("INSERT INTO approved_guardrails VALUES (?, ?, ?, ?, ?)", (str(uuid4()), workspace_id, statement, proposed_diff, now()))
        self.db.commit()
        return {"recorded": True}

    def approved_guardrails(self, workspace_id: str):
        return [dict(row) for row in self.db.execute("SELECT * FROM approved_guardrails WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)).fetchall()]

    def portable_guardrails(self, workspace_id: str):
        return [dict(row) for row in self.db.execute(
            "SELECT id, workspace_id, statement, proposed_diff, created_at FROM approved_guardrails WHERE workspace_id<>? ORDER BY created_at DESC", (workspace_id,)
        ).fetchall()]

    def adopt_portable_guardrail(self, target_workspace_id: str, source_guardrail_id: str, developer_approved: bool):
        if not developer_approved:
            raise ValueError("A portable guardrail requires explicit developer approval.")
        source = self.db.execute("SELECT * FROM approved_guardrails WHERE id=?", (source_guardrail_id,)).fetchone()
        if not source or source["workspace_id"] == target_workspace_id:
            raise ValueError("Select an approved guardrail from another project.")
        self.db.execute(
            "INSERT OR IGNORE INTO portable_guardrail_adoptions VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), source_guardrail_id, source["workspace_id"], target_workspace_id, source["statement"], now()),
        )
        self.db.commit()
        return {"recorded": True, "statement": source["statement"]}

    def record_agent_stop(self, workspace_id: str, conversation_id: str, workspace_path: str, execution_num: int | None, termination_reason: str | None, fully_idle: bool):
        self.db.execute(
            "INSERT INTO agent_session_metadata VALUES (?, ?, 'antigravity', ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), workspace_id, conversation_id, str(Path(workspace_path).resolve()), execution_num, termination_reason, int(fully_idle), now()),
        )
        self.db.commit()

    def github_credentials(self):
        token_saved = bool(self.db.execute("SELECT 1 FROM connector_secrets WHERE name='github_token'").fetchone())
        status = self.connector_status("github")
        return {"token_saved": token_saved, "state": status["state"] if status else ("configured" if token_saved else "disconnected"), "detail": status["detail"] if status else None}

    def connector_status(self, name: str):
        row = self.db.execute("SELECT state, detail, updated_at FROM connector_state WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def set_connector_state(self, name: str, state: str, detail: str | None = None):
        self.db.execute("INSERT INTO connector_state (name, state, updated_at, detail) VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at, detail=excluded.detail", (name, state, now(), detail))
        self.db.commit()

    def save_github_token(self, token: str):
        self.db.execute("INSERT INTO connector_secrets VALUES ('github_token', ?, ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (protect(token), now()))
        self.set_connector_state("github", "configured")
        return self.github_credentials()

    def github_token(self):
        row = self.db.execute("SELECT value FROM connector_secrets WHERE name='github_token'").fetchone()
        return unprotect(row["value"]) if row else None

    def delete_github_credentials(self):
        self.db.execute("DELETE FROM connector_secrets WHERE name IN ('github_token', 'github_webhook_secret')")
        self.set_connector_state("github", "disconnected")
        return self.github_credentials()

    def github_poll_status(self, workspace_id: str):
        row = self.db.execute("SELECT * FROM github_poll_settings WHERE workspace_id=?", (workspace_id,)).fetchone()
        sync = self.db.execute("SELECT * FROM github_sync_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        status = self.connector_status("github")
        setting = dict(row) if row else {"workspace_id": workspace_id, "enabled": 0, "interval_seconds": 900, "next_poll_at": None, "consecutive_failures": 0, "last_success_at": None, "last_error": None}
        state = dict(sync) if sync else {"pull_cursor": None, "in_progress": 0, "poll_started_at": None, "last_poll_finished_at": None, "last_http_status": None, "last_request_ms": None, "rate_limit_remaining": None, "rate_limit_limit": None, "rate_limit_reset_at": None, "retry_after_at": None, "last_partial": 0, "last_error_kind": None}
        health = state["last_error_kind"] or ("healthy" if setting["last_success_at"] else (status["state"] if status else "disconnected"))
        return {**setting, **state, "enabled": bool(setting["enabled"]), "in_progress": bool(state["in_progress"]), "partial": bool(state["last_partial"]), "health": health, "connector_state": status["state"] if status else "disconnected", "connector_detail": status["detail"] if status else None}

    def _github_sync_state(self, workspace_id: str):
        self.db.execute("INSERT OR IGNORE INTO github_sync_state (workspace_id, updated_at) VALUES (?, ?)", (workspace_id, now()))

    def github_etag(self, workspace_id: str, key: str):
        self._github_sync_state(workspace_id)
        row = self.db.execute("SELECT etags FROM github_sync_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        return json.loads(row["etags"]).get(key)

    def github_checkpoint(self, workspace_id: str, key: str) -> str | None:
        self._github_sync_state(workspace_id)
        row = self.db.execute("SELECT checkpoints FROM github_sync_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        return json.loads(row["checkpoints"] or "{}").get(key)

    def set_github_checkpoint(self, workspace_id: str, key: str, path: str | None):
        self._github_sync_state(workspace_id)
        row = self.db.execute("SELECT checkpoints FROM github_sync_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        checkpoints = json.loads(row["checkpoints"] or "{}")
        if path:
            checkpoints[key] = path
        else:
            checkpoints.pop(key, None)
        self.db.execute("UPDATE github_sync_state SET checkpoints=?, updated_at=? WHERE workspace_id=?", (json.dumps(checkpoints, sort_keys=True), now(), workspace_id))
        self.db.commit()

    def record_github_response(self, workspace_id: str, key: str, metadata: dict):
        self._github_sync_state(workspace_id)
        row = self.db.execute("SELECT etags FROM github_sync_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        etags = json.loads(row["etags"])
        if metadata.get("etag"):
            etags[key] = metadata["etag"]
        self.db.execute(
            "UPDATE github_sync_state SET etags=?, last_http_status=?, last_request_ms=?, rate_limit_remaining=?, rate_limit_limit=?, rate_limit_reset_at=?, retry_after_at=?, updated_at=? WHERE workspace_id=?",
            (json.dumps(etags, sort_keys=True), metadata.get("http_status"), metadata.get("request_ms"), metadata.get("rate_limit_remaining"), metadata.get("rate_limit_limit"), metadata.get("rate_limit_reset_at"), metadata.get("retry_after_at"), now(), workspace_id),
        )
        self.db.commit()

    def begin_github_poll(self, workspace_id: str) -> bool:
        self._github_sync_state(workspace_id)
        stale_before = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
        result = self.db.execute("UPDATE github_sync_state SET in_progress=1, poll_started_at=?, updated_at=? WHERE workspace_id=? AND (in_progress=0 OR poll_started_at<?)", (now(), now(), workspace_id, stale_before))
        self.db.commit()
        return result.rowcount == 1

    def finish_github_poll(self, workspace_id: str):
        self._github_sync_state(workspace_id)
        self.db.execute("UPDATE github_sync_state SET in_progress=0, last_poll_finished_at=?, updated_at=? WHERE workspace_id=?", (now(), now(), workspace_id))
        self.db.commit()

    def record_github_event(self, workspace_id: str, event_type: str, health: str, metadata: dict | None = None, detail: str | None = None, partial: bool = False):
        metadata = metadata or {}
        self.db.execute("INSERT INTO github_sync_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid4()), workspace_id, now(), event_type, health, metadata.get("http_status"), metadata.get("request_ms"), detail, int(partial)))
        self.db.execute("DELETE FROM github_sync_events WHERE id IN (SELECT id FROM github_sync_events WHERE occurred_at < ? OR id NOT IN (SELECT id FROM github_sync_events ORDER BY occurred_at DESC LIMIT 500))", ((datetime.now(UTC) - timedelta(days=30)).isoformat(),))
        self.db.commit()

    def configure_github_polling(self, workspace_id: str, enabled: bool, interval_seconds: int = 900):
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        if interval_seconds < 60 or interval_seconds > 86_400:
            raise ValueError("Polling interval must be between 60 seconds and 24 hours.")
        self.db.execute(
            "INSERT INTO github_poll_settings (workspace_id, enabled, interval_seconds, next_poll_at, consecutive_failures, last_success_at, last_error, updated_at) VALUES (?, ?, ?, ?, 0, NULL, NULL, ?) "
            "ON CONFLICT(workspace_id) DO UPDATE SET enabled=excluded.enabled, interval_seconds=excluded.interval_seconds, next_poll_at=excluded.next_poll_at, consecutive_failures=CASE WHEN excluded.enabled=1 THEN 0 ELSE github_poll_settings.consecutive_failures END, last_error=CASE WHEN excluded.enabled=1 THEN NULL ELSE github_poll_settings.last_error END, updated_at=excluded.updated_at",
            (workspace_id, int(enabled), interval_seconds, now() if enabled else None, now()),
        )
        self.db.commit()
        return self.github_poll_status(workspace_id)

    def due_github_polls(self, current_time: str):
        rows = self.db.execute("SELECT workspace_id FROM github_poll_settings WHERE enabled=1 AND (next_poll_at IS NULL OR next_poll_at<=?) ORDER BY next_poll_at", (current_time,)).fetchall()
        return [row["workspace_id"] for row in rows]

    def record_github_poll_success(self, workspace_id: str, result: dict | None = None):
        setting = self.github_poll_status(workspace_id)
        next_poll_at = (datetime.now(UTC) + timedelta(seconds=setting["interval_seconds"])).isoformat()
        self._github_sync_state(workspace_id)
        self.db.execute("UPDATE github_poll_settings SET next_poll_at=?, consecutive_failures=0, last_success_at=?, last_error=NULL, updated_at=? WHERE workspace_id=?", (next_poll_at, now(), now(), workspace_id))
        self.db.execute("UPDATE github_sync_state SET pull_cursor=COALESCE(?, pull_cursor), last_partial=?, last_error_kind=NULL, retry_after_at=NULL, updated_at=? WHERE workspace_id=?", ((result or {}).get("pull_cursor"), int(bool((result or {}).get("partial"))), now(), workspace_id))
        self.record_github_event(workspace_id, "poll", "partial" if (result or {}).get("partial") else "healthy", detail="Bounded sync completed.", partial=bool((result or {}).get("partial")))
        self.set_connector_state("github", "connected", "GitHub polling is healthy." if not (result or {}).get("partial") else "GitHub sync reached a configured limit; it will resume next poll.")
        self.db.commit()
        return self.github_poll_status(workspace_id)

    def record_github_poll_failure(self, workspace_id: str, error: str, kind: str = "unreachable", retry_after_seconds: int | None = None, rate_limit_reset_at: str | None = None):
        setting = self.github_poll_status(workspace_id)
        failures = setting["consecutive_failures"] + 1
        delay = min(setting["interval_seconds"] * (2 ** min(failures - 1, 6)), 3600)
        delay = int(delay * random.uniform(0.8, 1.2))
        if retry_after_seconds is not None:
            delay = max(delay, retry_after_seconds)
        if rate_limit_reset_at:
            try:
                delay = max(delay, max(0, int((datetime.fromisoformat(rate_limit_reset_at) - datetime.now(UTC)).total_seconds())))
            except ValueError:
                pass
        next_poll_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        self.db.execute("UPDATE github_poll_settings SET next_poll_at=?, consecutive_failures=?, last_error=?, updated_at=? WHERE workspace_id=?", (next_poll_at, failures, error, now(), workspace_id))
        self._github_sync_state(workspace_id)
        self.db.execute("UPDATE github_sync_state SET last_error_kind=?, retry_after_at=?, updated_at=? WHERE workspace_id=?", (kind, next_poll_at, now(), workspace_id))
        self.record_github_event(workspace_id, "failure", kind, detail=error)
        self.set_connector_state("github", kind, error)
        self.db.commit()
        return self.github_poll_status(workspace_id)

    def rule_policy(self, workspace_id: str):
        row = self.db.execute("SELECT * FROM workspace_rule_policies WHERE workspace_id=?", (workspace_id,)).fetchone()
        return {**dict(row), "configured": True} if row else {"workspace_id": workspace_id, "mode": None, "configured": False}

    def configure_rule_policy(self, workspace_id: str, mode: str):
        if mode not in {"approval", "autonomous"}:
            raise ValueError("Rule policy must be approval or autonomous.")
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        timestamp = now()
        self.db.execute(
            "INSERT INTO workspace_rule_policies VALUES (?, ?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET mode=excluded.mode, updated_at=excluded.updated_at",
            (workspace_id, mode, timestamp, timestamp),
        )
        self.db.commit()
        return self.rule_policy(workspace_id)

    @staticmethod
    def reusable_database_path() -> Path:
        configured = os.environ.get("FORGE_REUSABLE_RULES_DB")
        return Path(configured).expanduser() if configured else Path.home() / ".forge" / "reusable-rules.sqlite3"

    @staticmethod
    def _reusable_key(rule: dict) -> str:
        statement = " ".join(rule["statement"].split()).lower()
        return sha256(json.dumps([rule["category"].strip().lower(), statement], separators=(",", ":")).encode("utf-8")).hexdigest()

    def _open_reusable_store(self) -> "Store":
        path = self.reusable_database_path().resolve()
        if path == self.path.resolve():
            raise ValueError("Reusable rules must use a separate local registry database.")
        return Store(path)

    @staticmethod
    def _reusable_rule(row: sqlite3.Row, sources: list[dict] | None = None) -> dict:
        rule = dict(row)
        rule["scope"] = json.loads(rule.pop("scope_json"))
        if sources is not None:
            rule["sources"] = sources
        return rule

    def _global_reusable_rules(self, state: str | None = None) -> list[dict]:
        reusable = self._open_reusable_store()
        try:
            query = "SELECT * FROM reusable_rules"
            params: list[object] = []
            if state:
                query += " WHERE state=?"
                params.append(state)
            query += " ORDER BY requested_at DESC"
            results = []
            for row in reusable.db.execute(query, params).fetchall():
                sources = [dict(source) for source in reusable.db.execute(
                    "SELECT repository_path, workspace_id, rule_version_id, evidence_count, recorded_at FROM reusable_rule_sources WHERE reusable_rule_id=? ORDER BY repository_key",
                    (row["id"],),
                ).fetchall()]
                results.append(self._reusable_rule(row, sources))
            return results
        finally:
            reusable.close()

    def request_reusable_rule(self, rule_version_id: str) -> dict:
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "active":
            raise ValueError("Only an active, evidence-gated project rule can support reusable promotion.")
        rule = self._rule_progress(rule)
        if not rule["eligible"]:
            raise ValueError("Reusable promotion requires the local rule's configured validation evidence gate.")
        repository = self.repository(rule["workspace_id"])
        if not repository:
            raise ValueError("Rule workspace repository is not registered.")
        reusable = self._open_reusable_store()
        try:
            key = self._reusable_key(rule)
            row = reusable.db.execute("SELECT * FROM reusable_rules WHERE rule_key=?", (key,)).fetchone()
            timestamp = now()
            if not row:
                rule_id = str(uuid4())
                reusable.db.execute(
                    "INSERT INTO reusable_rules VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, NULL)",
                    (rule_id, key, rule["statement"], rule["category"], json.dumps(self._normalized_scope(rule["scope"])), timestamp, timestamp),
                )
            else:
                rule_id = row["id"]
            repository_path = str(Path(repository["path"]).resolve())
            repository_key = sha256((repository.get("remote_url") or repository_path).encode("utf-8")).hexdigest()
            reusable.db.execute(
                "INSERT OR IGNORE INTO reusable_rule_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule_id, repository_key, repository_path, rule["workspace_id"], rule["id"], rule["evidence_count"], timestamp),
            )
            source_count = reusable.db.execute("SELECT COUNT(*) AS count FROM reusable_rule_sources WHERE reusable_rule_id=?", (rule_id,)).fetchone()["count"]
            reusable.db.commit()
            reusable_rule = reusable.db.execute("SELECT * FROM reusable_rules WHERE id=?", (rule_id,)).fetchone()
            return {**self._reusable_rule(reusable_rule), "source_count": source_count, "minimum_sources": 2, "ready_for_approval": reusable_rule["state"] == "pending" and source_count >= 2}
        finally:
            reusable.close()

    def approve_reusable_rule(self, reusable_rule_id: str, developer_approved: bool) -> dict:
        reusable = self._open_reusable_store()
        try:
            rule = reusable.db.execute("SELECT * FROM reusable_rules WHERE id=?", (reusable_rule_id,)).fetchone()
            if not rule:
                raise ValueError("Reusable rule not found.")
            source_count = reusable.db.execute("SELECT COUNT(*) AS count FROM reusable_rule_sources WHERE reusable_rule_id=?", (reusable_rule_id,)).fetchone()["count"]
            if source_count < 2:
                raise ValueError("Reusable rule requires evidence-gated rules from two distinct repositories.")
            if not developer_approved:
                return {**self._reusable_rule(rule), "source_count": source_count, "status": "pending_developer_approval"}
            if rule["state"] != "pending":
                raise ValueError("Only a pending reusable rule can be approved.")
            reusable.db.execute("UPDATE reusable_rules SET state='active', approved_at=? WHERE id=?", (now(), reusable_rule_id))
            reusable.db.commit()
            approved = reusable.db.execute("SELECT * FROM reusable_rules WHERE id=?", (reusable_rule_id,)).fetchone()
            return {**self._reusable_rule(approved), "source_count": source_count, "status": "active"}
        finally:
            reusable.close()

    def reusable_rules(self, workspace_id: str, scope: str | None = None) -> list[dict]:
        overrides = {row["reusable_rule_id"]: dict(row) for row in self.db.execute("SELECT * FROM project_reusable_rule_overrides WHERE workspace_id=?", (workspace_id,)).fetchall()}
        results = []
        for rule in self._global_reusable_rules("active"):
            if scope and not any(self._scope_is_covered(scope, [item]) for item in rule["scope"]):
                continue
            override = overrides.get(rule["id"])
            if override and override["action"] == "ignore":
                continue
            results.append({
                **rule,
                "statement": override["statement"] if override and override["action"] == "replace" else rule["statement"],
                "origin": "project_override" if override else "reusable_rule",
                "reusable_rule_id": rule["id"],
            })
        return results

    def reusable_rule_requests(self, state: str = "pending") -> list[dict]:
        if state not in {"pending", "active", "retracted"}:
            raise ValueError("Reusable rule state must be pending, active, or retracted.")
        return self._global_reusable_rules(state)

    def set_reusable_rule_override(self, workspace_id: str, reusable_rule_id: str, action: str, statement: str | None = None) -> dict:
        if action not in {"ignore", "replace"}:
            raise ValueError("Reusable rule override action must be ignore or replace.")
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        active = next((rule for rule in self._global_reusable_rules("active") if rule["id"] == reusable_rule_id), None)
        if not active:
            raise ValueError("Only an active reusable rule can be overridden.")
        replacement = self._outcome_text(statement or "", "override statement") if action == "replace" else None
        timestamp = now()
        self.db.execute(
            "INSERT INTO project_reusable_rule_overrides VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(workspace_id, reusable_rule_id) DO UPDATE SET action=excluded.action, statement=excluded.statement, updated_at=excluded.updated_at",
            (workspace_id, reusable_rule_id, action, replacement, timestamp, timestamp),
        )
        self.db.commit()
        if action == "ignore":
            return {**active, "origin": "project_override", "override_action": "ignore"}
        return next(rule for rule in self.reusable_rules(workspace_id) if rule["id"] == reusable_rule_id)

    def record_session_feedback(self, workspace_id: str, handoff_id: str, context_useful: str, irrelevant_or_missing: str, rule_assessment: str) -> dict:
        if context_useful not in {"yes", "no", "partly"}:
            raise ValueError("context_useful must be yes, no, or partly.")
        if rule_assessment not in {"approve", "revise", "coaching_only", "reject"}:
            raise ValueError("rule_assessment must be approve, revise, coaching_only, or reject.")
        handoff = self.get_session_handoff(handoff_id)
        if not handoff or handoff["workspace_id"] != workspace_id:
            raise ValueError("Session Handoff is not available in this workspace.")
        notes = self._outcome_text(irrelevant_or_missing, "irrelevant_or_missing")
        existing = self.db.execute("SELECT * FROM session_feedback WHERE workspace_id=? AND handoff_id=?", (workspace_id, handoff_id)).fetchone()
        if existing:
            return {**dict(existing), "idempotent": True}
        summary = f"Context useful: {context_useful}. Rule review: {rule_assessment}. Notes: {notes}"
        span_id = self.create_evidence(workspace_id, "developer_feedback", "Developer session feedback", summary, summary, external_id=f"session-feedback:{handoff_id}")
        feedback_id = str(uuid4())
        self.db.execute("INSERT INTO session_feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (feedback_id, workspace_id, handoff_id, context_useful, notes, rule_assessment, span_id, now()))
        self.db.commit()
        return {**dict(self.db.execute("SELECT * FROM session_feedback WHERE id=?", (feedback_id,)).fetchone()), "idempotent": False}

    @staticmethod
    def _outcome_text(value: str, field: str, maximum: int = 4000) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} is required.")
        if len(normalized) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters.")
        return normalized

    def _normalized_scope(self, scope: list[str]) -> list[str]:
        return sorted({item.strip().replace("\\", "/").strip("/").lower() for item in scope if item and item.strip()})

    def _rule_key(self, scope: list[str], category: str, statement: str, learning_area: str | None = None, learning_trigger: str | None = None, learning_action: str | None = None) -> str:
        normalized_scope = self._normalized_scope(scope)
        if learning_area and learning_trigger and learning_action:
            value = ["learning-card", normalized_scope, learning_area.strip().lower(), learning_trigger.strip().lower(), learning_action.strip().lower()]
        else:
            value = ["legacy-rule", normalized_scope, category.strip().lower(), statement.strip().lower()]
        return sha256(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _current_validation_config_hash(self, workspace_id: str) -> str | None:
        repository = self.repository(workspace_id)
        if not repository:
            return None
        path = Path(repository["path"]) / "forge.validation.json"
        return sha256(path.read_bytes()).hexdigest() if path.exists() else None

    @staticmethod
    def _scope_is_covered(scope: str, allowed_scopes: list[str]) -> bool:
        normalized = scope.strip().replace("\\", "/").strip("/").lower()
        return "repository" in allowed_scopes or any(normalized == allowed or normalized.startswith(f"{allowed}/") for allowed in allowed_scopes)

    def _applicable_validation_runs(self, outcome_id: str, scope: list[str], category: str) -> list[dict]:
        config_hash = self._current_validation_config_hash(self.db.execute("SELECT workspace_id FROM session_outcomes WHERE id=?", (outcome_id,)).fetchone()["workspace_id"])
        rows = self.db.execute(
            "SELECT v.* FROM validation_runs v JOIN learning_card_observations o ON o.span_id=v.evidence_span_id WHERE o.outcome_id=?",
            (outcome_id,),
        ).fetchall()
        trusted = [dict(row) for row in rows if row["trusted"] and row["status"] == "passed" and row["config_hash"] and row["config_hash"] == config_hash and category.strip().lower() in json.loads(row["categories_json"])]
        return trusted if trusted and all(any(self._scope_is_covered(item, json.loads(run["scopes_json"])) for run in trusted) for item in self._normalized_scope(scope)) else []

    def _outcome_has_applicable_validation(self, outcome_id: str, scope: list[str], category: str) -> bool:
        return bool(self._applicable_validation_runs(outcome_id, scope, category))

    def _rule_outcome_count(self, workspace_id: str, rule_key: str) -> int:
        card = self.db.execute("SELECT * FROM learning_cards WHERE workspace_id=? AND rule_key=?", (workspace_id, rule_key)).fetchone()
        if not card:
            return 0
        rows = self.db.execute("SELECT DISTINCT o.outcome_id, s.created_at FROM learning_card_observations o JOIN session_outcomes s ON s.id=o.outcome_id WHERE o.card_id=? ORDER BY s.created_at", (card["id"],)).fetchall()
        scope = json.loads(card["scope_json"])
        category = self.db.execute("SELECT category FROM rule_versions WHERE learning_card_id=? ORDER BY created_at DESC LIMIT 1", (card["id"],)).fetchone()
        if not category:
            return 0
        used_spans: set[str] = set()
        count = 0
        for row in rows:
            runs = self._applicable_validation_runs(row["outcome_id"], scope, category["category"])
            spans = {run["evidence_span_id"] for run in runs}
            if spans - used_spans:
                count += 1
                used_spans.update(spans)
        return count

    def _rule_version(self, rule_version_id: str):
        row = self.db.execute("SELECT * FROM rule_versions WHERE id=?", (rule_version_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["scope"] = json.loads(value.pop("scope_json"))
        value["citations"] = [dict(item) for item in self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote FROM rule_version_citations c JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.rule_version_id=?",
            (rule_version_id,),
        ).fetchall()]
        value["verifications"] = [dict(item) for item in self.db.execute("SELECT * FROM rule_verifications WHERE rule_version_id=? ORDER BY created_at DESC", (rule_version_id,)).fetchall()]
        return value

    def _rule_progress(self, rule: dict | None):
        if not rule:
            return None
        evidence_count = self._rule_outcome_count(rule["workspace_id"], rule["rule_key"])
        rule["evidence_count"] = evidence_count
        rule["required_evidence_count"] = 2
        rule["eligible"] = evidence_count >= rule["required_evidence_count"]
        if rule["state"] == "candidate":
            rule["next_action"] = "Ready for activation." if rule["eligible"] else "Waiting for another outcome with a different cited local validation result."
        elif rule["state"] == "active":
            rule["next_action"] = "Active in Forge's managed AGENTS.md block; later evidence can verify or retract it."
        else:
            rule["next_action"] = "Retracted rules are not served as active context."
        return rule

    def _card_for_rule(self, rule_version_id: str):
        row = self.db.execute("SELECT c.* FROM learning_cards c JOIN rule_versions r ON r.learning_card_id=c.id WHERE r.id=?", (rule_version_id,)).fetchone()
        return dict(row) if row else None

    def _ensure_learning_card(self, rule: dict, outcome_id: str, span_ids: list[str]):
        card = self._card_for_rule(rule["id"])
        if not card:
            card_id = str(uuid4())
            card_state = {"candidate": "watching", "active": "active", "retracted": "retracted"}[rule["state"]]
            self.db.execute("INSERT INTO learning_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (card_id, rule["workspace_id"], rule["rule_key"], json.dumps(self._normalized_scope(rule["scope"])), rule.get("learning_area"), rule.get("learning_trigger"), rule.get("learning_action"), "observed", rule["id"], None, now(), now()))
            self.db.execute("UPDATE rule_versions SET learning_card_id=? WHERE id=?", (card_id, rule["id"]))
            card = dict(self.db.execute("SELECT * FROM learning_cards WHERE id=?", (card_id,)).fetchone())
            others = self.db.execute("SELECT * FROM learning_cards WHERE workspace_id=? AND id<>?", (rule["workspace_id"], card_id)).fetchall()
            for other in others:
                if other["scope_json"] != card["scope_json"] or not card["area"] or card["area"] != other["area"]:
                    continue
                kind = "possible_conflict" if card["trigger"] == other["trigger"] and card["action"] != other["action"] else "possible_duplicate" if card["action"] == other["action"] else None
                if kind:
                    self.db.execute("INSERT OR IGNORE INTO learning_card_alerts VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)", (str(uuid4()), rule["workspace_id"], card_id, other["id"], kind, now()))
        self.db.executemany("INSERT OR IGNORE INTO learning_card_observations VALUES (?, ?, ?, ?)", [(card["id"], outcome_id, span_id, now()) for span_id in span_ids])
        supported = self._rule_outcome_count(rule["workspace_id"], rule["rule_key"])
        state = "ready" if supported >= 2 else "watching" if supported else "observed"
        self.db.execute("UPDATE learning_cards SET state=?, updated_at=? WHERE id=?", (state, now(), card["id"]))
        return card

    def learning_cards(self, workspace_id: str, state: str | None = None):
        query, params = "SELECT * FROM learning_cards WHERE workspace_id=?", [workspace_id]
        if state:
            query += " AND state=?"
            params.append(state)
        cards = []
        for row in self.db.execute(query + " ORDER BY updated_at DESC", params).fetchall():
            card = dict(row)
            card["scope"] = json.loads(card.pop("scope_json"))
            card["alerts"] = [dict(alert) for alert in self.db.execute("SELECT * FROM learning_card_alerts WHERE (card_id=? OR related_card_id=?) AND status='pending'", (card["id"], card["id"])).fetchall()]
            card["observations"] = [dict(item) for item in self.db.execute(
                "SELECT o.outcome_id, o.span_id, o.created_at, h.agent, h.goal, h.validation, s.quote AS citation_quote "
                "FROM learning_card_observations o JOIN session_outcomes h ON h.id=o.outcome_id "
                "JOIN evidence_spans s ON s.id=o.span_id WHERE o.card_id=? ORDER BY o.created_at",
                (card["id"],),
            ).fetchall()]
            card["rule_versions"] = [dict(item) for item in self.db.execute("SELECT id, statement, state, created_at, activated_at, retracted_at FROM rule_versions WHERE learning_card_id=? ORDER BY created_at", (card["id"],)).fetchall()]
            card["verification_inputs"] = [self._verification_input(item["id"]) for item in self.db.execute(
                "SELECT id FROM verification_inputs WHERE rule_version_id IN (SELECT id FROM rule_versions WHERE learning_card_id=?) ORDER BY created_at",
                (card["id"],),
            ).fetchall()]
            cards.append(card)
        return cards

    def learning_cards_for_id(self, card_id: str):
        row = self.db.execute("SELECT workspace_id FROM learning_cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            return []
        return [card for card in self.learning_cards(row["workspace_id"]) if card["id"] == card_id]

    def learning_alerts(self, workspace_id: str):
        alerts = [dict(row) for row in self.db.execute("SELECT * FROM learning_card_alerts WHERE workspace_id=? AND status='pending' ORDER BY created_at", (workspace_id,)).fetchall()]
        for card in self.db.execute("SELECT id, review_due_at FROM learning_cards WHERE workspace_id=? AND state IN ('active', 'verified') AND review_due_at IS NOT NULL AND review_due_at<?", (workspace_id, now())).fetchall():
            alerts.append({"id": f"review_due:{card['id']}", "card_id": card["id"], "related_card_id": None, "kind": "review_due", "status": "pending", "created_at": card["review_due_at"]})
        alerts.extend({"id": row["id"], "card_id": None, "related_card_id": None, "kind": "projection_repair", "status": row["status"], "created_at": row["created_at"], "detail": row["detail"]} for row in self.db.execute("SELECT * FROM projection_alerts WHERE workspace_id=? AND status='pending' ORDER BY created_at", (workspace_id,)).fetchall())
        return alerts

    def projection_status(self, workspace_id: str):
        projections = [dict(row) for row in self.db.execute(
            "SELECT id, rule_version_id, operation, status, target_path, detail, created_at, completed_at FROM rule_projections WHERE workspace_id=? ORDER BY created_at DESC LIMIT 20",
            (workspace_id,),
        ).fetchall()]
        repairs = [dict(row) for row in self.db.execute(
            "SELECT id, rule_version_id, status, detail, created_at FROM projection_alerts WHERE workspace_id=? AND status='pending' ORDER BY created_at DESC",
            (workspace_id,),
        ).fetchall()]
        return {"workspace_id": workspace_id, "projections": projections, "repair_alerts": repairs}

    def legacy_history(self, workspace_id: str, limit: int = 20):
        contexts = self.db.execute("SELECT id, agent, worktree_path, branch, what_changed, validation, unresolved, created_at FROM session_contexts WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(limit, 100)))).fetchall()
        rules = self.db.execute("SELECT id, statement, state, created_at FROM rule_versions WHERE workspace_id=? AND legacy=1 ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(limit, 100)))).fetchall()
        return {"workspace_id": workspace_id, "read_only": True, "session_contexts": [dict(row) for row in contexts], "rule_versions": [dict(row) for row in rules]}

    def cleanup_unreferenced_validation_evidence(self, workspace_id: str, older_than_days: int = 90):
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        rows = self.db.execute("SELECT e.id FROM evidence_items e WHERE e.workspace_id=? AND e.kind='local_validation' AND e.created_at<? AND NOT EXISTS (SELECT 1 FROM session_outcome_citations c JOIN evidence_spans s ON s.id=c.span_id WHERE s.evidence_id=e.id) AND NOT EXISTS (SELECT 1 FROM rule_verifications v JOIN evidence_spans s ON s.id=v.evidence_span_id WHERE s.evidence_id=e.id)", (workspace_id, cutoff)).fetchall()
        evidence_ids = [(row["id"],) for row in rows]
        if evidence_ids:
            self.db.executemany("DELETE FROM validation_runs WHERE evidence_span_id IN (SELECT id FROM evidence_spans WHERE evidence_id=?)", evidence_ids)
            self.db.executemany("DELETE FROM evidence_spans WHERE evidence_id=?", evidence_ids)
            self.db.executemany("DELETE FROM evidence_items WHERE id=?", evidence_ids)
        self.db.commit()
        return {"deleted": len(rows)}

    def review_learning_alert(self, alert_id: str, decision: str):
        if decision not in {"merged", "kept_separate", "marked_conflict"}:
            raise ValueError("Unsupported Learning Card review decision.")
        alert = self.db.execute("SELECT * FROM learning_card_alerts WHERE id=? AND status='pending'", (alert_id,)).fetchone()
        if not alert:
            raise ValueError("Pending Learning Card alert not found.")
        if decision == "merged" and alert["related_card_id"]:
            states = self.db.execute("SELECT id, state FROM learning_cards WHERE id IN (?, ?)", (alert["card_id"], alert["related_card_id"])).fetchall()
            if any(row["state"] in {"active", "verified", "contradicted", "retracted"} for row in states):
                raise ValueError("Only inactive Learning Cards can be merged.")
            self.db.execute("INSERT OR IGNORE INTO learning_card_observations SELECT ?, outcome_id, span_id, created_at FROM learning_card_observations WHERE card_id=?", (alert["card_id"], alert["related_card_id"]))
            self.db.execute("UPDATE learning_cards SET state='archived', updated_at=? WHERE id=?", (now(), alert["related_card_id"]))
        self.db.execute("INSERT INTO learning_card_reviews VALUES (?, ?, ?, ?, ?, ?)", (str(uuid4()), alert["workspace_id"], alert["card_id"], alert["related_card_id"], decision, now()))
        self.db.execute("UPDATE learning_card_alerts SET status=?, resolved_at=? WHERE id=?", (decision, now(), alert_id))
        self.db.commit()
        return {"id": alert_id, "decision": decision}

    def list_rule_versions(self, workspace_id: str, state: str | None = None):
        query = "SELECT id FROM rule_versions WHERE workspace_id=?"
        params: list[str] = [workspace_id]
        if state:
            query += " AND state=?"
            params.append(state)
        query += " ORDER BY created_at DESC"
        return [self._rule_progress(self._rule_version(row["id"])) for row in self.db.execute(query, params).fetchall()]

    def start_work_item(self, workspace_id: str, session_id: str | None, work_item_key: str, agent: str, worktree_path: str, branch: str, goal: str, scope: list[str], area: str | None = None):
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        if not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            raise ValueError("scope must contain at least one non-empty item.")
        fields = {
            "work_item_key": self._outcome_text(work_item_key, "work_item_key", 255),
            "agent": self._outcome_text(agent, "agent", 100),
            "worktree_path": self._outcome_text(worktree_path, "worktree_path", 1000),
            "branch": self._outcome_text(branch, "branch", 255),
            "goal": self._outcome_text(goal, "goal"),
            "area": self._outcome_text(area, "area", 200) if area else None,
        }
        existing = self.db.execute(
            "SELECT id FROM work_items WHERE workspace_id=? AND work_item_key=?",
            (workspace_id, fields["work_item_key"]),
        ).fetchone()
        if existing:
            return {"work_item": self.get_work_item(existing["id"]), "idempotent": True}
        item_id = str(uuid4())
        timestamp = now()
        self.db.execute(
            "INSERT INTO work_items (id, workspace_id, session_id, work_item_key, agent, worktree_path, branch, goal, scope_json, area, status, summary, rationale, validation, risk, unresolved, started_at, ended_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, NULL, NULL, NULL, NULL, ?, NULL, ?)",
            (item_id, workspace_id, session_id, fields["work_item_key"], fields["agent"], fields["worktree_path"], fields["branch"], fields["goal"], json.dumps(self._normalized_scope(scope)), fields["area"], timestamp, timestamp),
        )
        self.db.commit()
        return {"work_item": self.get_work_item(item_id), "idempotent": False}

    def finish_work_item(self, workspace_id: str, work_item_id: str, status: str, summary: str, rationale: str, validation: str, risk: str, unresolved: str, evidence_span_ids: list[str]):
        if status not in {"completed", "abandoned"}:
            raise ValueError("work item status must be completed or abandoned.")
        item = self.db.execute("SELECT * FROM work_items WHERE id=? AND workspace_id=?", (work_item_id, workspace_id)).fetchone()
        if not item:
            raise ValueError("Work Item is not available in this workspace.")
        if item["status"] != "active":
            return {"work_item": self.get_work_item(work_item_id), "idempotent": True}
        span_ids = self._workspace_span_ids(workspace_id, evidence_span_ids)
        fields = {
            "summary": self._outcome_text(summary, "summary"),
            "rationale": self._outcome_text(rationale, "rationale"),
            "validation": self._outcome_text(validation, "validation"),
            "risk": self._outcome_text(risk, "risk"),
            "unresolved": self._outcome_text(unresolved, "unresolved"),
        }
        timestamp = now()
        self.db.execute(
            "UPDATE work_items SET status=?, summary=?, rationale=?, validation=?, risk=?, unresolved=?, ended_at=?, updated_at=? WHERE id=?",
            (status, fields["summary"], fields["rationale"], fields["validation"], fields["risk"], fields["unresolved"], timestamp, timestamp, work_item_id),
        )
        self.db.executemany("INSERT OR IGNORE INTO work_item_citations VALUES (?, ?)", [(work_item_id, span_id) for span_id in span_ids])
        self.db.commit()
        return {"work_item": self.get_work_item(work_item_id), "idempotent": False}

    def get_work_item(self, work_item_id: str):
        row = self.db.execute("SELECT * FROM work_items WHERE id=?", (work_item_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["scope"] = json.loads(item.pop("scope_json"))
        item["citations"] = [dict(citation) for citation in self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote FROM work_item_citations c JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.work_item_id=? ORDER BY s.created_at",
            (work_item_id,),
        ).fetchall()]
        return item

    def list_work_items(self, workspace_id: str, session_id: str | None = None, status: str | None = None, limit: int = 50):
        query = "SELECT id FROM work_items WHERE workspace_id=?"
        params: list[object] = [workspace_id]
        if session_id is not None:
            query += " AND session_id=?"
            params.append(session_id)
        if status is not None:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))
        return [self.get_work_item(row["id"]) for row in self.db.execute(query, params).fetchall()]

    def capture_learning_observation(self, workspace_id: str, work_item_id: str, observation_key: str, kind: str, scope: list[str], area: str, trigger: str, observed_fact: str, hypothesis: str, counterexample: str, next_action: str, confidence: str, evidence_span_ids: list[str]):
        if kind not in {"technical_error", "work_behavior", "decision_pattern"}:
            raise ValueError("observation kind is invalid.")
        if confidence not in {"low", "medium", "high"}:
            raise ValueError("observation confidence is invalid.")
        if not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            raise ValueError("scope must contain at least one non-empty item.")
        work_item = self.db.execute("SELECT id FROM work_items WHERE id=? AND workspace_id=?", (work_item_id, workspace_id)).fetchone()
        if not work_item:
            raise ValueError("Work Item is not available in this workspace.")
        fields = {
            "observation_key": self._outcome_text(observation_key, "observation_key", 255),
            "area": self._outcome_text(area, "area", 200),
            "trigger": self._outcome_text(trigger, "trigger", 400),
            "observed_fact": self._outcome_text(observed_fact, "observed_fact"),
            "hypothesis": self._outcome_text(hypothesis, "hypothesis"),
            "counterexample": self._outcome_text(counterexample, "counterexample"),
            "next_action": self._outcome_text(next_action, "next_action", 400),
        }
        span_ids = self._workspace_span_ids(workspace_id, evidence_span_ids)
        existing = self.db.execute("SELECT id FROM learning_observations WHERE workspace_id=? AND observation_key=?", (workspace_id, fields["observation_key"])).fetchone()
        if existing:
            case = self.db.execute("SELECT case_id FROM learning_case_observations WHERE observation_id=?", (existing["id"],)).fetchone()
            return {"observation": self.get_learning_observation(existing["id"]), "case": self.get_learning_case(case["case_id"]) if case else None, "idempotent": True}
        observation_id = str(uuid4())
        timestamp = now()
        self.db.execute(
            "INSERT INTO learning_observations (id, workspace_id, work_item_id, observation_key, kind, scope_json, area, trigger, observed_fact, hypothesis, counterexample, next_action, confidence, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'observed', ?, ?)",
            (observation_id, workspace_id, work_item_id, fields["observation_key"], kind, json.dumps(self._normalized_scope(scope)), fields["area"], fields["trigger"], fields["observed_fact"], fields["hypothesis"], fields["counterexample"], fields["next_action"], confidence, timestamp, timestamp),
        )
        self.db.executemany("INSERT INTO learning_observation_citations VALUES (?, ?)", [(observation_id, span_id) for span_id in span_ids])
        self.db.commit()
        observation = self.get_learning_observation(observation_id)
        return {"observation": observation, "case": self._upsert_learning_case(observation), "idempotent": False}

    def _learning_case_key(self, observation: dict) -> str:
        value = ["learning-case", observation["kind"], self._normalized_scope(observation["scope"]), observation["area"].strip().lower(), observation["trigger"].strip().lower(), observation["next_action"].strip().lower()]
        return sha256(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _upsert_learning_case(self, observation: dict):
        case_key = self._learning_case_key(observation)
        row = self.db.execute("SELECT id FROM learning_cases WHERE workspace_id=? AND case_key=?", (observation["workspace_id"], case_key)).fetchone()
        timestamp = now()
        if row:
            case_id = row["id"]
        else:
            case_id = str(uuid4())
            self.db.execute(
                "INSERT INTO learning_cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'observed', ?, ?)",
                (case_id, observation["workspace_id"], case_key, observation["kind"], json.dumps(self._normalized_scope(observation["scope"])), observation["area"], observation["trigger"], observation["next_action"], timestamp, timestamp),
            )
        self.db.execute("INSERT OR IGNORE INTO learning_case_observations VALUES (?, ?, ?)", (case_id, observation["id"], timestamp))
        count = self.db.execute("SELECT COUNT(DISTINCT o.work_item_id) AS count FROM learning_case_observations c JOIN learning_observations o ON o.id=c.observation_id WHERE c.case_id=?", (case_id,)).fetchone()["count"]
        state = "proposed" if count >= 2 else "observed"
        self.db.execute("UPDATE learning_cases SET state=?, updated_at=? WHERE id=?", (state, timestamp, case_id))
        self.db.commit()
        return self.get_learning_case(case_id)

    def get_learning_case(self, case_id: str):
        row = self.db.execute("SELECT * FROM learning_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            return None
        case = dict(row)
        case["scope"] = json.loads(case.pop("scope_json"))
        case["observations"] = [self.get_learning_observation(item["observation_id"]) for item in self.db.execute("SELECT observation_id FROM learning_case_observations WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall()]
        case["independent_work_item_count"] = len({item["work_item_id"] for item in case["observations"]})
        return case

    def list_learning_cases(self, workspace_id: str, state: str | None = None, limit: int = 50):
        query = "SELECT id FROM learning_cases WHERE workspace_id=?"
        params: list[object] = [workspace_id]
        if state is not None:
            query += " AND state=?"
            params.append(state)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))
        return [self.get_learning_case(row["id"]) for row in self.db.execute(query, params).fetchall()]

    def _vault_search_entries(self, workspace_id: str) -> list[tuple[str, str, str, str, str]]:
        entries: list[tuple[str, str, str, str, str]] = []
        for item in self.list_work_items(workspace_id, limit=100):
            entries.append((
                item["id"],
                workspace_id,
                "work_item",
                " ".join(item["scope"]),
                "\n".join(filter(None, [item["goal"], item.get("summary"), item.get("rationale"), item.get("validation"), item.get("unresolved")])),
            ))
        for handoff in self.list_session_outcomes(workspace_id, limit=100):
            entries.append((
                handoff["id"],
                workspace_id,
                "handoff",
                " ".join(handoff["scope"]),
                "\n".join([handoff["goal"], handoff["problem"], handoff["chosen_fix"], handoff["rationale"], handoff["unresolved"]]),
            ))
        for decision in self.list_decisions(workspace_id):
            source = self.get_session_context(decision["source_session_context_id"]) if decision.get("source_session_context_id") else None
            files = [change["path"] for change in source.get("changed", [])] if source else []
            entries.append((
                decision["id"],
                workspace_id,
                "decision",
                " ".join([*decision.get("scope", []), *files]),
                "\n".join(filter(None, [decision["statement"], decision.get("decision_context"), decision.get("chosen_approach"), *files])),
            ))
        for case in self.list_learning_cases(workspace_id, limit=100):
            entries.append((
                case["id"],
                workspace_id,
                "learning_case",
                " ".join(case["scope"]),
                "\n".join([case["area"], case["trigger"], case["next_action"], case["state"]]),
            ))
        for rule in self.list_rule_versions(workspace_id):
            entries.append((
                rule["id"],
                workspace_id,
                "rule",
                " ".join(rule["scope"]),
                "\n".join([rule["statement"], rule["state"]]),
            ))
        return entries

    @staticmethod
    def _vault_search_hash(entries: list[tuple[str, str, str, str, str]]) -> str:
        return sha256(json.dumps(entries, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

    def _rebuild_vault_search(self, workspace_id: str, entries: list[tuple[str, str, str, str, str]] | None = None):
        entries = entries if entries is not None else self._vault_search_entries(workspace_id)
        self.db.execute("DELETE FROM vault_search WHERE workspace_id=?", (workspace_id,))
        self.db.executemany("INSERT INTO vault_search (record_id, workspace_id, record_type, scope, content) VALUES (?, ?, ?, ?, ?)", entries)
        self.db.execute(
            "INSERT INTO vault_search_state VALUES (?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET source_hash=excluded.source_hash, indexed_at=excluded.indexed_at",
            (workspace_id, self._vault_search_hash(entries), now()),
        )
        self.db.commit()

    def search_vault(self, workspace_id: str, query: str, scope: str | None = None, file_path: str | None = None, limit: int = 20):
        tokens = ["".join(character for character in token if character.isalnum() or character in "_-/.") for token in query.split()]
        tokens = [token for token in tokens if token]
        if not tokens:
            raise ValueError("query must contain searchable text.")
        entries = self._vault_search_entries(workspace_id)
        source_hash = self._vault_search_hash(entries)
        state = self.db.execute("SELECT source_hash FROM vault_search_state WHERE workspace_id=?", (workspace_id,)).fetchone()
        if not state or state["source_hash"] != source_hash:
            self._rebuild_vault_search(workspace_id, entries)
        match = " AND ".join(f'"{token}"' for token in tokens)
        rows = self.db.execute("SELECT record_id, record_type, scope, snippet(vault_search, 4, '[', ']', '…', 14) AS excerpt FROM vault_search WHERE vault_search MATCH ? AND workspace_id=? ORDER BY rank LIMIT ?", (match, workspace_id, max(1, min(limit, 50)))).fetchall()
        required = (file_path or scope or "").replace("\\", "/").strip("/").lower()
        return [dict(row) for row in rows if not required or required in row["scope"].lower() or required in row["excerpt"].lower()]

    @staticmethod
    def _write_vault_file(path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    def export_vault(self, workspace_id: str, output: str | Path | None = None):
        repository = self.repository(workspace_id)
        if not repository:
            raise ValueError("Repository is not registered.")
        root = Path(output) if output else self.path.parent / "vault"
        root = root.resolve()
        work_items = self.list_work_items(workspace_id, limit=100)
        cases = self.list_learning_cases(workspace_id, limit=100)
        rules = self.list_rule_versions(workspace_id)
        decisions = self.list_decisions(workspace_id)
        active_rules = [rule for rule in rules if rule["state"] == "active"]
        context = ["# Forge Project Context", "", "This file is generated from Forge's local SQLite vault. Do not edit it as evidence.", "", "## Active Rules", ""]
        context.extend([f"- {rule['statement']}" for rule in active_rules] or ["- None."])
        context.extend(["", "## Open Learning Cases", ""])
        context.extend([f"- [{case['state']}] {case['area']}: {case['next_action']} (`{case['id']}`)" for case in cases if case["state"] != "approved"] or ["- None."])
        context.extend(["", "## Latest Work Items", ""])
        context.extend([f"- [{item['status']}] {item['goal']} (`{item['id']}`)" for item in work_items] or ["- None."])
        self._write_vault_file(root / "PROJECT_CONTEXT.md", "\n".join(context) + "\n")
        self._write_vault_file(root / "active-rules.md", "# Active Rules\n\n" + "\n".join(f"- [{', '.join(rule['scope'])}] {rule['statement']}" for rule in active_rules) + "\n")
        self._write_vault_file(root / "rule-history.md", "# Rule History\n\n" + "\n".join(f"- [{rule['state']}] [{', '.join(rule['scope'])}] {rule['statement']} (`{rule['id']}`)" for rule in rules) + "\n")
        self._write_vault_file(root / "decisions.md", "# Confirmed Decisions\n\n" + "\n".join(f"- {item['statement']} (`{item['id']}`)" for item in decisions if item["review_status"] == "confirmed") + "\n")
        self._write_vault_file(root / "open-cases.md", "# Learning Cases\n\n" + "\n".join(f"- [{case['state']}] {case['area']} — {case['next_action']} (`{case['id']}`)" for case in cases) + "\n")
        sessions = root / "sessions"
        expected = set()
        for item in work_items:
            path = sessions / f"{item['id']}.md"
            expected.add(path.name)
            citation_lines = [f"- {citation['title']}: {citation['quote']}" for citation in item["citations"]]
            lines = [f"# {item['goal']}", "", f"- Status: {item['status']}", f"- Scope: {', '.join(item['scope'])}", f"- Area: {item['area'] or 'none'}", "", "## Summary", item["summary"] or "Not finished.", "", "## Rationale", item["rationale"] or "Not finished.", "", "## Validation", item["validation"] or "Not finished.", "", "## Citations", *(citation_lines or ["- None."]), ""]
            self._write_vault_file(path, "\n".join(lines))
        if sessions.exists():
            for path in sessions.glob("*.md"):
                if path.name not in expected:
                    path.unlink()
        return {"workspace_id": workspace_id, "path": str(root), "work_items": len(work_items), "learning_cases": len(cases), "active_rules": len(active_rules)}

    def get_learning_observation(self, observation_id: str):
        row = self.db.execute("SELECT * FROM learning_observations WHERE id=?", (observation_id,)).fetchone()
        if not row:
            return None
        observation = dict(row)
        observation["scope"] = json.loads(observation.pop("scope_json"))
        observation["citations"] = [dict(citation) for citation in self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote FROM learning_observation_citations c JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.observation_id=? ORDER BY s.created_at",
            (observation_id,),
        ).fetchall()]
        return observation

    def list_learning_observations(self, workspace_id: str, work_item_id: str | None = None, kind: str | None = None, limit: int = 50):
        query = "SELECT id FROM learning_observations WHERE workspace_id=?"
        params: list[object] = [workspace_id]
        if work_item_id is not None:
            query += " AND work_item_id=?"
            params.append(work_item_id)
        if kind is not None:
            query += " AND kind=?"
            params.append(kind)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 100)))
        return [self.get_learning_observation(row["id"]) for row in self.db.execute(query, params).fetchall()]

    def record_session_outcome(self, workspace_id: str, agent: str, worktree_path: str, branch: str, outcome_key: str, scope: list[str], category: str, goal: str, problem: str, prior_approach: str, why_prior_approach_failed: str, alternatives: list[dict], chosen_fix: str, rationale: str, validation: str, risk: str, unresolved: str, proposed_rule: str, evidence_span_ids: list[str], learning_card_id: str | None = None, learning_area: str | None = None, learning_trigger: str | None = None, learning_action: str | None = None, work_item_id: str | None = None):
        if not self.repository(workspace_id):
            raise ValueError("Repository is not registered.")
        if not scope or not all(isinstance(item, str) and item.strip() for item in scope):
            raise ValueError("scope must contain at least one non-empty item.")
        span_ids = self._workspace_span_ids(workspace_id, evidence_span_ids)
        fields = {
            "agent": self._outcome_text(agent, "agent", 100), "worktree_path": self._outcome_text(worktree_path, "worktree_path", 1000),
            "branch": self._outcome_text(branch, "branch", 255), "outcome_key": self._outcome_text(outcome_key, "outcome_key", 255),
            "category": self._outcome_text(category, "category", 100), "goal": self._outcome_text(goal, "goal"),
            "problem": self._outcome_text(problem, "problem"), "prior_approach": self._outcome_text(prior_approach, "prior_approach"),
            "why_prior_approach_failed": self._outcome_text(why_prior_approach_failed, "why_prior_approach_failed"),
            "chosen_fix": self._outcome_text(chosen_fix, "chosen_fix"), "rationale": self._outcome_text(rationale, "rationale"),
            "validation": self._outcome_text(validation, "validation"), "risk": self._outcome_text(risk, "risk"),
            "unresolved": self._outcome_text(unresolved, "unresolved"), "proposed_rule": self._outcome_text(proposed_rule, "proposed_rule"),
        }
        card_fields = {
            "learning_area": self._outcome_text(learning_area, "learning_area", 200) if learning_area else None,
            "learning_trigger": self._outcome_text(learning_trigger, "learning_trigger", 400) if learning_trigger else None,
            "learning_action": self._outcome_text(learning_action, "learning_action", 400) if learning_action else None,
        }
        if any(card_fields.values()) and not all(card_fields.values()):
            raise ValueError("learning_area, learning_trigger, and learning_action are required together.")
        if learning_card_id:
            existing_card = self.db.execute("SELECT * FROM learning_cards WHERE id=? AND workspace_id=?", (learning_card_id, workspace_id)).fetchone()
            if not existing_card or existing_card["state"] in {"archived", "retracted"}:
                raise ValueError("Learning Card is not available in this workspace.")
            existing_card = dict(existing_card)
            rule_key = existing_card["rule_key"]
            card_fields = {"learning_area": existing_card["area"], "learning_trigger": existing_card["trigger"], "learning_action": existing_card["action"]}
        else:
            rule_key = self._rule_key(scope, fields["category"], fields["proposed_rule"], **card_fields)
        if work_item_id:
            work_item = self.db.execute("SELECT id FROM work_items WHERE id=? AND workspace_id=?", (work_item_id, workspace_id)).fetchone()
            if not work_item:
                raise ValueError("Work Item is not available in this workspace.")
        existing = self.db.execute("SELECT id FROM session_outcomes WHERE workspace_id=? AND outcome_key=?", (workspace_id, fields["outcome_key"])).fetchone()
        if existing:
            return {"outcome": self.get_session_outcome(existing["id"]), "idempotent": True, "rule": None}
        outcome_id = str(uuid4())
        self.db.execute(
            "INSERT INTO session_outcomes (id, workspace_id, agent, worktree_path, branch, outcome_key, scope_json, category, goal, problem, prior_approach, why_prior_approach_failed, alternatives_json, chosen_fix, rationale, validation, risk, unresolved, proposed_rule, created_at, learning_area, learning_trigger, learning_action, work_item_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (outcome_id, workspace_id, fields["agent"], fields["worktree_path"], fields["branch"], fields["outcome_key"], json.dumps(sorted(set(scope))), fields["category"], fields["goal"], fields["problem"], fields["prior_approach"], fields["why_prior_approach_failed"], json.dumps(alternatives), fields["chosen_fix"], fields["rationale"], fields["validation"], fields["risk"], fields["unresolved"], fields["proposed_rule"], now(), card_fields["learning_area"], card_fields["learning_trigger"], card_fields["learning_action"], work_item_id),
        )
        self.db.executemany("INSERT INTO session_outcome_citations VALUES (?, ?)", [(outcome_id, span_id) for span_id in span_ids])
        rule = None
        if fields["proposed_rule"].lower() != "none":
            existing_rule = self.db.execute("SELECT id FROM rule_versions WHERE workspace_id=? AND rule_key=? AND state IN ('candidate', 'active') ORDER BY version DESC LIMIT 1", (workspace_id, rule_key)).fetchone()
            if existing_rule:
                self.db.executemany("INSERT OR IGNORE INTO rule_version_citations VALUES (?, ?)", [(existing_rule["id"], span_id) for span_id in span_ids])
                rule = self._rule_version(existing_rule["id"])
            else:
                rule_id = str(uuid4())
                policy = self.rule_policy(workspace_id)["mode"] or "approval"
                self.db.execute("INSERT INTO rule_versions (id, workspace_id, rule_key, version, statement, scope_json, category, state, activation_mode, source_outcome_id, previous_version_id, evaluation_reason, created_at, activated_at, retracted_at, projection_hash, learning_area, learning_trigger, learning_action) VALUES (?, ?, ?, 1, ?, ?, ?, 'candidate', ?, ?, NULL, ?, ?, NULL, NULL, NULL, ?, ?, ?)", (rule_id, workspace_id, rule_key, fields["proposed_rule"], json.dumps(self._normalized_scope(scope)), fields["category"], policy, outcome_id, "Waiting for two independently cited configured validation-backed handoffs.", now(), card_fields["learning_area"], card_fields["learning_trigger"], card_fields["learning_action"]))
                self.db.executemany("INSERT INTO rule_version_citations VALUES (?, ?)", [(rule_id, span_id) for span_id in span_ids])
                rule = self._rule_version(rule_id)
        self.db.commit()
        if rule:
            card = self._ensure_learning_card(rule, outcome_id, span_ids)
            self.db.commit()
            rule = self._rule_progress(rule)
            rule["learning_card_id"] = card["id"]
        return {"outcome": self.get_session_outcome(outcome_id), "idempotent": False, "rule": rule}

    def get_session_outcome(self, outcome_id: str):
        row = self.db.execute("SELECT * FROM session_outcomes WHERE id=?", (outcome_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["scope"] = json.loads(value.pop("scope_json"))
        value["alternatives"] = json.loads(value.pop("alternatives_json"))
        value["citations"] = [dict(item) for item in self.db.execute(
            "SELECT s.id AS span_id, e.id AS evidence_id, e.kind, e.title, s.quote FROM session_outcome_citations c JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.session_outcome_id=?",
            (outcome_id,),
        ).fetchall()]
        return value

    def list_session_outcomes(self, workspace_id: str, limit: int = 20):
        rows = self.db.execute("SELECT id FROM session_outcomes WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?", (workspace_id, max(1, min(limit, 100)))).fetchall()
        return [self.get_session_outcome(row["id"]) for row in rows]

    def record_session_handoff(self, workspace_id: str, *args, **kwargs):
        proposed_rule = kwargs.get("proposed_rule", args[16] if len(args) > 16 else "none")
        learning_card_id = kwargs.get("learning_card_id", args[18] if len(args) > 18 else None)
        fields = (
            kwargs.get("learning_area", args[19] if len(args) > 19 else None),
            kwargs.get("learning_trigger", args[20] if len(args) > 20 else None),
            kwargs.get("learning_action", args[21] if len(args) > 21 else None),
        )
        if proposed_rule.strip().lower() != "none" and not learning_card_id:
            if not all(fields):
                raise ValueError("Rule-supporting Session Handoffs require scope, learning_area, learning_trigger, and learning_action.")
        return self.record_session_outcome(workspace_id, *args, **kwargs)

    def record_session_end_event(self, workspace_id: str, agent: str, event_type: str, handoff_id: str | None = None, abandon_reason: str | None = None):
        if event_type not in {"completed", "abandoned"}:
            raise ValueError("session end event type is invalid.")
        if event_type == "completed" and not handoff_id:
            raise ValueError("completed sessions require a Session Handoff.")
        self.db.execute(
            "INSERT INTO session_end_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid4()), workspace_id, self._outcome_text(agent, "agent", 100), event_type, handoff_id, abandon_reason, now()),
        )
        self.db.commit()

    def get_session_handoff(self, handoff_id: str):
        return self.get_session_outcome(handoff_id)

    def get_latest_session_handoff(self, workspace_id: str):
        rows = self.list_session_outcomes(workspace_id, 1)
        return rows[0] if rows else {"workspace_id": workspace_id, "status": "no_handoff"}

    def session_start_context(self, workspace_id: str, scope: str | None = None):
        learning = self.learning_context(workspace_id, scope)
        return {
            "workspace_id": workspace_id,
            "policy": learning["policy"],
            "active_rules": learning["active_rules"],
            "reusable_rules": self.reusable_rules(workspace_id, scope),
            "learning_alerts": learning["learning_alerts"],
            "latest_handoff": self.get_latest_session_handoff(workspace_id),
            "decisions": self.retrieve_decisions(workspace_id, scope=scope, limit=10),
            "session_feedback_prompt": {
                "context_useful": "Was the retrieved context useful? (yes, partly, or no)",
                "irrelevant_or_missing": "Was anything irrelevant or missing?",
                "rule_assessment": "Did the proposed rule describe the real issue? (approve, revise, coaching_only, or reject)",
            },
        }

    def _workspace_agents_path(self, workspace_id: str) -> Path:
        repository = self.repository(workspace_id)
        if not repository:
            raise ValueError("Repository is not registered.")
        return Path(repository["path"]).resolve() / "AGENTS.md"

    def _render_managed_rules(self, rules: list[dict]) -> str:
        lines = ["<!-- forge:rules:start -->", "## Forge Active Rules", ""]
        lines.extend(f"- [{', '.join(rule['scope'])}] {rule['statement']}" for rule in rules)
        lines.extend(["", "<!-- forge:rules:end -->", ""])
        return "\n".join(lines)

    @staticmethod
    def _managed_block_hash(content: str) -> str | None:
        start, end = "<!-- forge:rules:start -->", "<!-- forge:rules:end -->"
        if (start in content) != (end in content):
            return None
        if start not in content:
            return ""
        block = start + content.split(start, 1)[1].split(end, 1)[0] + end
        return sha256(block.encode("utf-8")).hexdigest()

    def _replace_managed_rules(self, current: str, block: str) -> str:
        start, end = "<!-- forge:rules:start -->", "<!-- forge:rules:end -->"
        has_start, has_end = start in current, end in current
        if has_start != has_end:
            raise ValueError("AGENTS.md has an incomplete Forge managed rule block.")
        if has_start:
            before = current.split(start, 1)[0]
            after = current.split(end, 1)[1]
            return before.rstrip() + "\n\n" + block + after.lstrip()
        return current.rstrip() + ("\n\n" if current.strip() else "") + block

    def _project_active_rules(self, workspace_id: str, active_rules: list[dict] | None = None, rule_version_id: str | None = None, operation: str = "activate") -> str:
        target = self._workspace_agents_path(workspace_id)
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        current_hash = self._managed_block_hash(current)
        if current_hash is None:
            self._record_projection_alert(workspace_id, rule_version_id, "AGENTS.md has incomplete Forge managed rule markers.")
            raise ValueError("AGENTS.md has an incomplete Forge managed rule block.")
        previous = self.db.execute("SELECT resulting_block_hash FROM rule_projections WHERE workspace_id=? AND status='applied' ORDER BY completed_at DESC LIMIT 1", (workspace_id,)).fetchone()
        if previous and current_hash != previous["resulting_block_hash"]:
            self._record_projection_alert(workspace_id, rule_version_id, "Forge managed rule block was edited manually; repair it before projection.")
            raise ValueError("Forge managed AGENTS.md block changed outside Forge; repair is required.")
        active = active_rules if active_rules is not None else self.list_rule_versions(workspace_id, "active")
        target_content = self._replace_managed_rules(current, self._render_managed_rules(active))
        target_hash = self._managed_block_hash(target_content)
        projection_id = str(uuid4())
        self.db.execute("INSERT INTO rule_projections VALUES (?, ?, ?, ?, 'prepared', ?, ?, ?, NULL, ?, NULL)", (projection_id, workspace_id, rule_version_id, operation, str(target), current_hash, target_hash, now()))
        self.db.commit()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_text(target_content, encoding="utf-8")
            temporary.replace(target)
        except OSError as error:
            self.db.execute("UPDATE rule_projections SET status='failed', detail=?, completed_at=? WHERE id=?", (str(error), now(), projection_id))
            self.db.commit()
            raise ValueError(f"Could not update the managed AGENTS.md block: {error}") from error
        self.db.execute("UPDATE rule_projections SET status='applied', completed_at=? WHERE id=?", (now(), projection_id))
        self.db.commit()
        return target_hash

    def _record_projection_alert(self, workspace_id: str, rule_version_id: str | None, detail: str):
        self.db.execute("INSERT INTO projection_alerts VALUES (?, ?, ?, 'pending', ?, ?, NULL)", (str(uuid4()), workspace_id, rule_version_id, detail, now()))
        self.db.commit()

    def activate_rule(self, rule_version_id: str):
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "candidate":
            raise ValueError("Candidate rule not found.")
        policy = self.rule_policy(rule["workspace_id"])
        if policy["mode"] != "autonomous":
            raise ValueError("Only autonomous workspaces can activate a rule without approval.")
        card = self._card_for_rule(rule_version_id)
        if not card or card["state"] != "ready":
            raise ValueError("A rule needs two independently cited, verified outcomes before activation.")
        if self.db.execute("SELECT 1 FROM learning_card_alerts WHERE (card_id=? OR related_card_id=?) AND kind IN ('possible_duplicate', 'possible_conflict') AND status='pending'", (card["id"], card["id"])).fetchone():
            raise ValueError("Resolve pending Learning Card duplicate/conflict alerts before activation.")
        projection_hash = self._project_active_rules(rule["workspace_id"], [*self.list_rule_versions(rule["workspace_id"], "active"), rule], rule_version_id)
        self.db.execute("UPDATE rule_versions SET state='active', activated_at=?, evaluation_reason=? WHERE id=?", (now(), "Two independently cited outcomes with validation met the autonomous activation gate.", rule_version_id))
        self.db.execute("UPDATE learning_cards SET state='active', review_due_at=?, updated_at=? WHERE id=?", ((datetime.now(UTC) + timedelta(days=90)).isoformat(), now(), card["id"]))
        self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
        self.db.commit()
        return self._rule_version(rule_version_id)

    def rule_proposal(self, rule_version_id: str):
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "candidate":
            raise ValueError("Candidate rule not found.")
        if self.rule_policy(rule["workspace_id"])["mode"] != "approval":
            raise ValueError("Rule proposals are only used in approval workspaces.")
        card = self._card_for_rule(rule_version_id)
        if not card or card["state"] != "ready":
            raise ValueError("A rule needs two independently cited, verified outcomes before approval.")
        target = self._workspace_agents_path(rule["workspace_id"])
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        proposed = self._replace_managed_rules(current, self._render_managed_rules([*self.list_rule_versions(rule["workspace_id"], "active"), rule]))
        return {
            "rule_version_id": rule_version_id, "target_agents_path": str(target), "diff": "".join(unified_diff(current.splitlines(keepends=True), proposed.splitlines(keepends=True), fromfile="AGENTS.md", tofile="AGENTS.md")),
            "status": "pending_developer_approval",
        }

    def approve_rule(self, rule_version_id: str, developer_approved: bool):
        if not developer_approved:
            raise ValueError("Developer approval is required to activate a rule in approval mode.")
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "candidate":
            raise ValueError("Candidate rule not found.")
        if self.rule_policy(rule["workspace_id"])["mode"] != "approval":
            raise ValueError("Use autonomous activation for this workspace.")
        card = self._card_for_rule(rule_version_id)
        if not card or card["state"] != "ready":
            raise ValueError("A rule needs two independently cited, verified outcomes before approval.")
        if self.db.execute("SELECT 1 FROM learning_card_alerts WHERE (card_id=? OR related_card_id=?) AND kind IN ('possible_duplicate', 'possible_conflict') AND status='pending'", (card["id"], card["id"])).fetchone():
            raise ValueError("Resolve pending Learning Card duplicate/conflict alerts before approval.")
        projection_hash = self._project_active_rules(rule["workspace_id"], [*self.list_rule_versions(rule["workspace_id"], "active"), rule], rule_version_id)
        self.db.execute("UPDATE rule_versions SET state='active', activated_at=?, evaluation_reason=? WHERE id=?", (now(), "Developer approved the exact managed AGENTS.md projection after the evidence gate passed.", rule_version_id))
        self.db.execute("UPDATE learning_cards SET state='active', review_due_at=?, updated_at=? WHERE id=?", ((datetime.now(UTC) + timedelta(days=90)).isoformat(), now(), card["id"]))
        self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
        self.db.commit()
        return self._rule_version(rule_version_id)

    def _verification_input(self, input_id: str):
        row = self.db.execute(
            "SELECT i.*, e.kind AS evidence_kind, e.title AS evidence_title, s.quote AS citation_quote FROM verification_inputs i "
            "JOIN evidence_spans s ON s.id=i.evidence_span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE i.id=?",
            (input_id,),
        ).fetchone()
        return dict(row) if row else None

    def verification_inputs(self, rule_version_id: str):
        return [self._verification_input(row["id"]) for row in self.db.execute("SELECT id FROM verification_inputs WHERE rule_version_id=? ORDER BY created_at", (rule_version_id,)).fetchall()]

    def _validate_verification_source(self, rule: dict, source_kind: str, evidence_span_id: str, result: str):
        if source_kind not in {"configured_validation", "git_change", "github_review", "local_failure"}:
            raise ValueError("Verification source kind is invalid.")
        evidence = self.db.execute("SELECT e.kind, e.created_at FROM evidence_spans s JOIN evidence_items e ON e.id=s.evidence_id WHERE s.id=?", (evidence_span_id,)).fetchone()
        if not evidence:
            raise ValueError("Verification evidence citation was not found.")
        self._workspace_span_ids(rule["workspace_id"], [evidence_span_id])
        baseline = rule["activated_at"] or rule["created_at"]
        if evidence["created_at"] <= baseline:
            raise ValueError("Verification evidence must come from later work than the rule.")
        expected_kinds = {
            "git_change": {"git_commit"},
            "github_review": {"github_review", "github_review_comment"},
            "local_failure": {"local_failure"},
        }
        if source_kind in expected_kinds and evidence["kind"] not in expected_kinds[source_kind]:
            raise ValueError(f"{source_kind} requires matching cited local evidence.")
        if source_kind == "configured_validation" and result != "insufficient_data":
            run = self.db.execute("SELECT * FROM validation_runs WHERE evidence_span_id=?", (evidence_span_id,)).fetchone()
            config_hash = self._current_validation_config_hash(rule["workspace_id"])
            if not run or not run["trusted"] or run["config_hash"] != config_hash:
                raise ValueError("Configured verification requires a trusted current Forge validation.")
            allowed_scopes = json.loads(run["scopes_json"])
            allowed_categories = json.loads(run["categories_json"])
            if rule["category"].strip().lower() not in allowed_categories or not all(self._scope_is_covered(scope, allowed_scopes) for scope in rule["scope"]):
                raise ValueError("Verification validation does not apply to this Learning Card.")

    def _apply_verification(self, rule: dict, result: str, evidence_span_id: str, note: str):
        rule_version_id = rule["id"]
        card = self._card_for_rule(rule_version_id)
        if card and result == "supported":
            self.db.execute("UPDATE learning_cards SET state='verified', updated_at=? WHERE id=?", (now(), card["id"]))
        if result == "contradicted" and rule["state"] == "active":
            self.db.execute("UPDATE learning_cards SET state='contradicted', updated_at=? WHERE id=?", (now(), card["id"]))
            self.db.commit()
            projection_hash = self._project_active_rules(rule["workspace_id"], [item for item in self.list_rule_versions(rule["workspace_id"], "active") if item["id"] != rule_version_id], rule_version_id, "retract")
            self.db.execute("UPDATE rule_versions SET state='retracted', retracted_at=? WHERE id=?", (now(), rule_version_id))
            self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
            if card:
                self.db.execute("UPDATE learning_cards SET state='retracted', updated_at=? WHERE id=?", (now(), card["id"]))
        self.db.commit()
        return self._rule_version(rule_version_id)

    def record_verification_input(self, rule_version_id: str, source_kind: str, result: str, evidence_span_id: str, summary: str, developer_confirmed: bool = False):
        if result not in {"supported", "contradicted", "insufficient_data"}:
            raise ValueError("Verification result is invalid.")
        rule = self._rule_version(rule_version_id)
        if not rule:
            raise ValueError("Rule not found.")
        summary = self._outcome_text(summary, "verification summary")
        self._validate_verification_source(rule, source_kind, evidence_span_id, result)
        existing = self.db.execute("SELECT id FROM verification_inputs WHERE rule_version_id=? AND source_kind=? AND evidence_span_id=? AND result=?", (rule_version_id, source_kind, evidence_span_id, result)).fetchone()
        if existing:
            return {"input": self._verification_input(existing["id"]), "rule": self._rule_version(rule_version_id), "idempotent": True}
        input_id = str(uuid4())
        self.db.execute("INSERT INTO verification_inputs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (input_id, rule["workspace_id"], rule_version_id, source_kind, evidence_span_id, result, summary, int(developer_confirmed), now(), None))
        self.db.execute("INSERT INTO rule_verifications VALUES (?, ?, ?, ?, ?, ?)", (str(uuid4()), rule_version_id, result, evidence_span_id, summary, now()))
        self.db.commit()
        should_apply = result != "insufficient_data" and (source_kind == "configured_validation" or developer_confirmed)
        if should_apply:
            updated = self._apply_verification(rule, result, evidence_span_id, summary)
            self.db.execute("UPDATE verification_inputs SET applied_at=? WHERE id=?", (now(), input_id))
            self.db.commit()
        else:
            updated = self._rule_version(rule_version_id)
        return {"input": self._verification_input(input_id), "rule": updated, "idempotent": False}

    def confirm_verification_input(self, input_id: str):
        input_record = self._verification_input(input_id)
        if not input_record:
            raise ValueError("Verification input not found.")
        if input_record["developer_confirmed"]:
            return {"input": input_record, "rule": self._rule_version(input_record["rule_version_id"]), "idempotent": True}
        self.db.execute("UPDATE verification_inputs SET developer_confirmed=1 WHERE id=?", (input_id,))
        self.db.commit()
        rule = self._rule_version(input_record["rule_version_id"])
        if input_record["result"] != "insufficient_data":
            rule = self._apply_verification(rule, input_record["result"], input_record["evidence_span_id"], input_record["summary"])
            self.db.execute("UPDATE verification_inputs SET applied_at=? WHERE id=?", (now(), input_id))
            self.db.commit()
        return {"input": self._verification_input(input_id), "rule": rule, "idempotent": False}

    def record_local_failure(self, rule_version_id: str, failure_class: str, summary: str, result: str = "contradicted", developer_confirmed: bool = False):
        rule = self._rule_version(rule_version_id)
        if not rule:
            raise ValueError("Rule not found.")
        failure_class = self._outcome_text(failure_class, "failure class", 100).lower().replace(" ", "_")
        if failure_class not in {"test_failure", "build_failure", "runtime_failure", "review_regression"}:
            raise ValueError("failure_class must be test_failure, build_failure, runtime_failure, or review_regression.")
        summary = self._outcome_text(summary, "failure summary")
        span_id = self.create_evidence(rule["workspace_id"], "local_failure", f"Local failure: {failure_class}", summary, summary, metadata={"failure_class": failure_class})
        return self.record_verification_input(rule_version_id, "local_failure", result, span_id, summary, developer_confirmed)

    def verify_rule(self, rule_version_id: str, result: str, evidence_span_id: str, note: str):
        """Backward-compatible configured-validation verification entry point."""
        return self.record_verification_input(rule_version_id, "configured_validation", result, evidence_span_id, note, developer_confirmed=True)["rule"]

    def learning_context(self, workspace_id: str, scope: str | None = None):
        rules = self.list_rule_versions(workspace_id, "active")
        candidates = self.list_rule_versions(workspace_id, "candidate")
        if scope:
            rules = [rule for rule in rules if scope in rule["scope"]]
            candidates = [rule for rule in candidates if scope in rule["scope"]]
        return {
            "workspace_id": workspace_id, "policy": self.rule_policy(workspace_id), "active_rules": rules, "pending_rule_candidates": candidates, "learning_cards": self.learning_cards(workspace_id), "learning_alerts": self.learning_alerts(workspace_id),
            "capture_prompt": "Summarize your own session: goal, problem with citation, prior approach, why it failed, alternatives, chosen fix, validation, risk, unresolved work, and one scoped proposed rule or none.",
        }
