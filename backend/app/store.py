import json
import sqlite3
from difflib import unified_diff
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .secrets import protect, unprotect


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or ".forge/forge.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
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
            """)]
        for version, migration in migrations:
            if version not in applied:
                self.db.executescript(migration)
                self.db.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, now()))
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
        tables = ("repositories", "evidence_items", "evidence_spans", "decisions", "decision_citations", "intentions", "project_memory_entries", "connector_state")
        data = {table: [dict(row) for row in self.db.execute(f"SELECT * FROM {table}")] for table in tables}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(target.resolve())

    def register_repository(self, workspace_id: str, path: str, remote_url: str | None = None, branch: str | None = None):
        self.db.execute(
            "INSERT INTO repositories (workspace_id, path, created_at, remote_url, branch) VALUES (?, ?, ?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET path=excluded.path, remote_url=excluded.remote_url, branch=excluded.branch",
            (workspace_id, str(Path(path).resolve()), now(), remote_url, branch),
        )
        self.db.commit()

    def repository(self, workspace_id: str):
        row = self.db.execute("SELECT * FROM repositories WHERE workspace_id=?", (workspace_id,)).fetchone()
        return dict(row) if row else None

    def repositories(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM repositories ORDER BY created_at ASC").fetchall()]

    def update_repository_head(self, workspace_id: str, commit: str):
        self.db.execute("UPDATE repositories SET last_ingested_commit=? WHERE workspace_id=?", (commit, workspace_id))
        self.db.commit()

    def create_evidence(self, workspace_id: str, kind: str, title: str, content: str, quote: str, external_id: str | None = None, metadata: dict | None = None, spans: list[str] | None = None):
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

    def has_evidence(self, workspace_id: str, kind: str, external_id: str) -> bool:
        return bool(self.db.execute("SELECT 1 FROM evidence_items WHERE workspace_id=? AND kind=? AND external_id=?", (workspace_id, kind, external_id)).fetchone())

    def list_evidence(self, workspace_id: str, kind: str = "git_commit", limit: int = 20):
        rows = self.db.execute(
            "SELECT id, kind, external_id, title, metadata, created_at FROM evidence_items WHERE workspace_id=? AND kind=? ORDER BY created_at DESC LIMIT ?",
            (workspace_id, kind, limit),
        ).fetchall()
        return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in rows]

    def evidence_count(self, workspace_id: str, kind: str) -> int:
        return self.db.execute("SELECT COUNT(*) AS count FROM evidence_items WHERE workspace_id=? AND kind=?", (workspace_id, kind)).fetchone()["count"]

    def get_evidence(self, evidence_id: str):
        row = self.db.execute("SELECT * FROM evidence_items WHERE id=?", (evidence_id,)).fetchone()
        if not row:
            return None
        evidence = dict(row)
        evidence["metadata"] = json.loads(evidence["metadata"])
        evidence["spans"] = [dict(span) for span in self.db.execute("SELECT id, quote, created_at FROM evidence_spans WHERE evidence_id=?", (evidence_id,)).fetchall()]
        return evidence

    def create_pending(self, workspace_id: str, statement: str, category: str, evidence_quote: str, source: str = "agent_decision"):
        span_id = self.create_evidence(workspace_id, source, "Agent supplied evidence", evidence_quote, evidence_quote)
        decision_id = str(uuid4())
        self.db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?, 'pending', ?, NULL)", (decision_id, workspace_id, statement, category, now()))
        self.db.execute("INSERT INTO decision_citations VALUES (?, ?)", (decision_id, span_id))
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
        return {"decisions": self.list_decisions(workspace_id), "reflections": self.list_reflections(workspace_id)}

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
        self.db.commit()
        return {"decision": self.get_decision(decision_id), "memory_created": status == "confirmed"}

    def set_intention(self, workspace_id: str, statement: str):
        self.db.execute("INSERT INTO intentions VALUES (?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET statement=excluded.statement, created_at=excluded.created_at", (workspace_id, statement, now()))
        self.db.commit()

    def active_intention(self, workspace_id: str):
        row = self.db.execute("SELECT statement, created_at FROM intentions WHERE workspace_id=?", (workspace_id,)).fetchone()
        return dict(row) if row else {"status": "insufficient_data", "reason": "No active intention selected."}

    def context(self, workspace_id: str):
        rows = self.db.execute("SELECT id, decision_id FROM project_memory_entries WHERE workspace_id=? AND superseded_at IS NULL ORDER BY created_at DESC LIMIT 12", (workspace_id,)).fetchall()
        memory = [{**self.get_decision(row["decision_id"]), "memory_entry_id": row["id"]} for row in rows]
        return {"workspace_id": workspace_id, "memory": memory, "active_intention": self.active_intention(workspace_id)}

    def archive_memory(self, entry_id: str):
        result = self.db.execute("UPDATE project_memory_entries SET superseded_at=? WHERE id=? AND superseded_at IS NULL", (now(), entry_id))
        self.db.commit()
        return result.rowcount == 1

    def today(self, workspace_id: str):
        pending = next((item for item in self.list_decisions(workspace_id) if item["review_status"] == "pending"), None)
        return {"workspace_id": workspace_id, "intention": self.active_intention(workspace_id), "memory": self.context(workspace_id)["memory"][:1], "pending_decision": pending, "pending_reflection": self.pending_reflection(workspace_id)}

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

    def record_guardrail_approval(self, workspace_id: str, statement: str, proposed_diff: str):
        self.db.execute("INSERT INTO approved_guardrails VALUES (?, ?, ?, ?, ?)", (str(uuid4()), workspace_id, statement, proposed_diff, now()))
        self.db.commit()
        return {"recorded": True}

    def approved_guardrails(self, workspace_id: str):
        return [dict(row) for row in self.db.execute("SELECT * FROM approved_guardrails WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,)).fetchall()]

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
