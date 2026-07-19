import json
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
            """)]
        for version, migration in migrations:
            if version not in applied:
                self.db.executescript(migration)
                self.db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))
        self.db.commit()
        self._backfill_learning_cards()

    def _backfill_learning_cards(self):
        rows = self.db.execute("SELECT id, workspace_id, rule_key, scope_json, learning_area, learning_trigger, learning_action, state, created_at, activated_at FROM rule_versions").fetchall()
        for row in rows:
            card_state = {"candidate": "watching", "active": "active", "retracted": "retracted"}[row["state"]]
            due = (datetime.fromisoformat(row["activated_at"]) + timedelta(days=90)).isoformat() if row["activated_at"] else None
            self.db.execute("INSERT OR IGNORE INTO learning_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid4()), row["workspace_id"], row["rule_key"], row["scope_json"], row["learning_area"], row["learning_trigger"], row["learning_action"], card_state, row["id"], due, row["created_at"], now()))
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
        tables = ("repositories", "evidence_items", "evidence_spans", "decisions", "decision_citations", "decision_scopes", "reflections", "intentions", "project_memory_entries", "session_contexts", "session_context_citations", "session_context_files", "session_context_scopes", "agent_work_sessions", "worktrees", "connector_state", "github_poll_settings", "agents_guardrail_handoffs", "workspace_rule_policies", "session_outcomes", "session_outcome_citations", "rule_versions", "rule_version_citations", "rule_verifications")
        data = {table: [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")] for table in tables}
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

    def record_validation_result(self, workspace_id: str, label: str, status: str, exit_code: int | None, duration_ms: int, command_name: str, command_digest: str, trusted: bool = False, config_hash: str | None = None):
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
        return {"span_id": span_id, "label": label, "status": status, "exit_code": exit_code, "duration_ms": duration_ms}

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
    def _outcome_text(value: str, field: str, maximum: int = 4000) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{field} is required.")
        if len(normalized) > maximum:
            raise ValueError(f"{field} must be at most {maximum} characters.")
        return normalized

    def _rule_key(self, scope: list[str], category: str, statement: str, learning_area: str | None = None, learning_trigger: str | None = None, learning_action: str | None = None) -> str:
        normalized_scope = sorted({item.strip() for item in scope if item.strip()})
        if learning_area and learning_trigger and learning_action:
            value = ["learning-card", normalized_scope, learning_area.strip().lower(), learning_trigger.strip().lower(), learning_action.strip().lower()]
        else:
            value = ["legacy-rule", normalized_scope, category.strip().lower(), statement.strip().lower()]
        return sha256(json.dumps(value, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _rule_outcome_count(self, workspace_id: str, rule_key: str) -> int:
        rows = self.db.execute("SELECT id, scope_json, category, proposed_rule, validation, learning_area, learning_trigger, learning_action FROM session_outcomes WHERE workspace_id=?", (workspace_id,)).fetchall()
        matching_ids = [
            row["id"] for row in rows
            if self._rule_key(json.loads(row["scope_json"]), row["category"], row["proposed_rule"], row["learning_area"], row["learning_trigger"], row["learning_action"]) == rule_key
            and row["proposed_rule"] != "none"
            and row["validation"].strip().lower() not in {"unknown", "not_run"}
        ]
        if not matching_ids:
            return 0
        placeholders = ",".join("?" for _ in matching_ids)
        rows = self.db.execute(
            f"SELECT DISTINCT c.span_id, e.metadata FROM session_outcome_citations c JOIN evidence_spans s ON s.id=c.span_id JOIN evidence_items e ON e.id=s.evidence_id WHERE c.session_outcome_id IN ({placeholders}) AND e.kind='local_validation'",
            matching_ids,
        ).fetchall()
        return sum(1 for row in rows if json.loads(row["metadata"] or "{}").get("trusted") is True)

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
        row = self.db.execute("SELECT * FROM learning_cards WHERE rule_version_id=?", (rule_version_id,)).fetchone()
        return dict(row) if row else None

    def _ensure_learning_card(self, rule: dict, outcome_id: str, span_ids: list[str]):
        card = self._card_for_rule(rule["id"])
        if not card:
            card_id = str(uuid4())
            card_state = {"candidate": "watching", "active": "active", "retracted": "retracted"}[rule["state"]]
            self.db.execute("INSERT INTO learning_cards VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (card_id, rule["workspace_id"], rule["rule_key"], json.dumps(rule["scope"]), rule.get("learning_area"), rule.get("learning_trigger"), rule.get("learning_action"), card_state, rule["id"], None, now(), now()))
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
        self.db.execute("UPDATE learning_cards SET state=?, updated_at=? WHERE id=?", ("ready" if supported >= 2 else "watching", now(), card["id"]))
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
            card["alerts"] = [dict(alert) for alert in self.db.execute("SELECT * FROM learning_card_alerts WHERE card_id=? AND status='pending'", (card["id"],)).fetchall()]
            card["observations"] = [dict(item) for item in self.db.execute("SELECT outcome_id, span_id, created_at FROM learning_card_observations WHERE card_id=? ORDER BY created_at", (card["id"],)).fetchall()]
            cards.append(card)
        return cards

    def learning_alerts(self, workspace_id: str):
        alerts = [dict(row) for row in self.db.execute("SELECT * FROM learning_card_alerts WHERE workspace_id=? AND status='pending' ORDER BY created_at", (workspace_id,)).fetchall()]
        for card in self.db.execute("SELECT id, review_due_at FROM learning_cards WHERE workspace_id=? AND state IN ('active', 'verified') AND review_due_at IS NOT NULL AND review_due_at<?", (workspace_id, now())).fetchall():
            alerts.append({"id": f"review_due:{card['id']}", "card_id": card["id"], "related_card_id": None, "kind": "review_due", "status": "pending", "created_at": card["review_due_at"]})
        return alerts

    def cleanup_unreferenced_validation_evidence(self, workspace_id: str, older_than_days: int = 90):
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        rows = self.db.execute("SELECT e.id FROM evidence_items e WHERE e.workspace_id=? AND e.kind='local_validation' AND e.created_at<? AND NOT EXISTS (SELECT 1 FROM session_outcome_citations c JOIN evidence_spans s ON s.id=c.span_id WHERE s.evidence_id=e.id) AND NOT EXISTS (SELECT 1 FROM rule_verifications v JOIN evidence_spans s ON s.id=v.evidence_span_id WHERE s.evidence_id=e.id)", (workspace_id, cutoff)).fetchall()
        self.db.executemany("DELETE FROM evidence_items WHERE id=?", [(row["id"],) for row in rows])
        self.db.commit()
        return {"deleted": len(rows)}

    def review_learning_alert(self, alert_id: str, decision: str):
        if decision not in {"merged", "kept_separate", "marked_conflict", "dismissed"}:
            raise ValueError("Unsupported Learning Card review decision.")
        alert = self.db.execute("SELECT * FROM learning_card_alerts WHERE id=? AND status='pending'", (alert_id,)).fetchone()
        if not alert:
            raise ValueError("Pending Learning Card alert not found.")
        if decision == "merged" and alert["related_card_id"]:
            self.db.execute("INSERT OR IGNORE INTO learning_card_observations SELECT ?, outcome_id, span_id, created_at FROM learning_card_observations WHERE card_id=?", (alert["card_id"], alert["related_card_id"]))
            self.db.execute("UPDATE learning_cards SET state='archived', updated_at=? WHERE id=?", (now(), alert["related_card_id"]))
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

    def record_session_outcome(self, workspace_id: str, agent: str, worktree_path: str, branch: str, outcome_key: str, scope: list[str], category: str, goal: str, problem: str, prior_approach: str, why_prior_approach_failed: str, alternatives: list[dict], chosen_fix: str, rationale: str, validation: str, risk: str, unresolved: str, proposed_rule: str, evidence_span_ids: list[str], learning_card_id: str | None = None, learning_area: str | None = None, learning_trigger: str | None = None, learning_action: str | None = None):
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
            existing_card = self._rule_version(learning_card_id)
            if not existing_card or existing_card["workspace_id"] != workspace_id or existing_card["state"] not in {"candidate", "active"}:
                raise ValueError("Learning Card is not available in this workspace.")
            rule_key = existing_card["rule_key"]
            card_fields = {key: existing_card[key] for key in card_fields}
        else:
            rule_key = self._rule_key(scope, fields["category"], fields["proposed_rule"], **card_fields)
        existing = self.db.execute("SELECT id FROM session_outcomes WHERE workspace_id=? AND outcome_key=?", (workspace_id, fields["outcome_key"])).fetchone()
        if existing:
            return {"outcome": self.get_session_outcome(existing["id"]), "idempotent": True, "rule": None}
        outcome_id = str(uuid4())
        self.db.execute(
            "INSERT INTO session_outcomes (id, workspace_id, agent, worktree_path, branch, outcome_key, scope_json, category, goal, problem, prior_approach, why_prior_approach_failed, alternatives_json, chosen_fix, rationale, validation, risk, unresolved, proposed_rule, created_at, learning_area, learning_trigger, learning_action) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (outcome_id, workspace_id, fields["agent"], fields["worktree_path"], fields["branch"], fields["outcome_key"], json.dumps(sorted(set(scope))), fields["category"], fields["goal"], fields["problem"], fields["prior_approach"], fields["why_prior_approach_failed"], json.dumps(alternatives), fields["chosen_fix"], fields["rationale"], fields["validation"], fields["risk"], fields["unresolved"], fields["proposed_rule"], now(), card_fields["learning_area"], card_fields["learning_trigger"], card_fields["learning_action"]),
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
                self.db.execute("INSERT INTO rule_versions (id, workspace_id, rule_key, version, statement, scope_json, category, state, activation_mode, source_outcome_id, previous_version_id, evaluation_reason, created_at, activated_at, retracted_at, projection_hash, learning_area, learning_trigger, learning_action) VALUES (?, ?, ?, 1, ?, ?, ?, 'candidate', ?, ?, NULL, ?, ?, NULL, NULL, NULL, ?, ?, ?)", (rule_id, workspace_id, rule_key, fields["proposed_rule"], json.dumps(sorted(set(scope))), fields["category"], policy, outcome_id, "Waiting for two independently cited Forge validation results.", now(), card_fields["learning_area"], card_fields["learning_trigger"], card_fields["learning_action"]))
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

    def _project_active_rules(self, workspace_id: str) -> str:
        target = self._workspace_agents_path(workspace_id)
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        active = self.list_rule_versions(workspace_id, "active")
        target_content = self._replace_managed_rules(current, self._render_managed_rules(active))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(target_content, encoding="utf-8")
        temporary.replace(target)
        return self._content_hash(target_content)

    def activate_rule(self, rule_version_id: str):
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "candidate":
            raise ValueError("Candidate rule not found.")
        policy = self.rule_policy(rule["workspace_id"])
        if policy["mode"] != "autonomous":
            raise ValueError("Only autonomous workspaces can activate a rule without approval.")
        if self._rule_outcome_count(rule["workspace_id"], rule["rule_key"]) < 2:
            raise ValueError("A rule needs two independently cited, verified outcomes before activation.")
        card = self._card_for_rule(rule_version_id)
        if card and self.db.execute("SELECT 1 FROM learning_card_alerts WHERE card_id=? AND kind IN ('possible_duplicate', 'possible_conflict') AND status='pending'", (card["id"],)).fetchone():
            raise ValueError("Resolve pending Learning Card duplicate/conflict alerts before activation.")
        self.db.execute("UPDATE rule_versions SET state='active', activated_at=?, evaluation_reason=? WHERE id=?", (now(), "Two independently cited outcomes with validation met the autonomous activation gate.", rule_version_id))
        if card:
            self.db.execute("UPDATE learning_cards SET state='active', review_due_at=?, updated_at=? WHERE id=?", ((datetime.now(UTC) + timedelta(days=90)).isoformat(), now(), card["id"]))
        self.db.commit()
        try:
            projection_hash = self._project_active_rules(rule["workspace_id"])
        except OSError as error:
            self.db.execute("UPDATE rule_versions SET state='candidate', activated_at=NULL WHERE id=?", (rule_version_id,))
            self.db.commit()
            raise ValueError(f"Could not update the managed AGENTS.md block: {error}") from error
        self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
        self.db.commit()
        return self._rule_version(rule_version_id)

    def rule_proposal(self, rule_version_id: str):
        rule = self._rule_version(rule_version_id)
        if not rule or rule["state"] != "candidate":
            raise ValueError("Candidate rule not found.")
        if self.rule_policy(rule["workspace_id"])["mode"] != "approval":
            raise ValueError("Rule proposals are only used in approval workspaces.")
        if self._rule_outcome_count(rule["workspace_id"], rule["rule_key"]) < 2:
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
        if self._rule_outcome_count(rule["workspace_id"], rule["rule_key"]) < 2:
            raise ValueError("A rule needs two independently cited, verified outcomes before approval.")
        card = self._card_for_rule(rule_version_id)
        if card and self.db.execute("SELECT 1 FROM learning_card_alerts WHERE card_id=? AND kind IN ('possible_duplicate', 'possible_conflict') AND status='pending'", (card["id"],)).fetchone():
            raise ValueError("Resolve pending Learning Card duplicate/conflict alerts before approval.")
        self.db.execute("UPDATE rule_versions SET state='active', activated_at=?, evaluation_reason=? WHERE id=?", (now(), "Developer approved the exact managed AGENTS.md projection after the evidence gate passed.", rule_version_id))
        if card:
            self.db.execute("UPDATE learning_cards SET state='active', review_due_at=?, updated_at=? WHERE id=?", ((datetime.now(UTC) + timedelta(days=90)).isoformat(), now(), card["id"]))
        self.db.commit()
        try:
            projection_hash = self._project_active_rules(rule["workspace_id"])
        except OSError as error:
            self.db.execute("UPDATE rule_versions SET state='candidate', activated_at=NULL WHERE id=?", (rule_version_id,))
            self.db.commit()
            raise ValueError(f"Could not update the managed AGENTS.md block: {error}") from error
        self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
        self.db.commit()
        return self._rule_version(rule_version_id)

    def verify_rule(self, rule_version_id: str, result: str, evidence_span_id: str, note: str):
        if result not in {"supported", "contradicted", "insufficient_data"}:
            raise ValueError("Verification result is invalid.")
        rule = self._rule_version(rule_version_id)
        if not rule:
            raise ValueError("Rule not found.")
        self._workspace_span_ids(rule["workspace_id"], [evidence_span_id])
        self.db.execute("INSERT INTO rule_verifications VALUES (?, ?, ?, ?, ?, ?)", (str(uuid4()), rule_version_id, result, evidence_span_id, self._outcome_text(note, "note"), now()))
        card = self._card_for_rule(rule_version_id)
        if card and result == "supported":
            self.db.execute("UPDATE learning_cards SET state='verified', updated_at=? WHERE id=?", (now(), card["id"]))
        if result == "contradicted" and rule["state"] == "active":
            self.db.execute("UPDATE rule_versions SET state='retracted', retracted_at=? WHERE id=?", (now(), rule_version_id))
            if card:
                self.db.execute("UPDATE learning_cards SET state='contradicted', updated_at=? WHERE id=?", (now(), card["id"]))
            self.db.commit()
            projection_hash = self._project_active_rules(rule["workspace_id"])
            self.db.execute("UPDATE rule_versions SET projection_hash=? WHERE id=?", (projection_hash, rule_version_id))
            if card:
                self.db.execute("UPDATE learning_cards SET state='retracted', updated_at=? WHERE id=?", (now(), card["id"]))
        self.db.commit()
        return self._rule_version(rule_version_id)

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
