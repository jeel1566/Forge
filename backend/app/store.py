import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .secrets import protect


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or ".forge/forge.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self):
        self.db.executescript(
            """
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
            """
        )
        self.db.commit()

    def close(self):
        self.db.close()

    def register_repository(self, workspace_id: str, path: str):
        self.db.execute(
            "INSERT INTO repositories VALUES (?, ?, ?) ON CONFLICT(workspace_id) DO UPDATE SET path=excluded.path",
            (workspace_id, str(Path(path).resolve()), now()),
        )
        self.db.commit()

    def repository_path(self, workspace_id: str) -> str | None:
        row = self.db.execute("SELECT path FROM repositories WHERE workspace_id=?", (workspace_id,)).fetchone()
        return row["path"] if row else None

    def create_evidence(self, workspace_id: str, kind: str, title: str, content: str, quote: str, external_id: str | None = None, metadata: dict | None = None):
        existing = None
        if external_id:
            existing = self.db.execute("SELECT id FROM evidence_items WHERE workspace_id=? AND kind=? AND external_id=?", (workspace_id, kind, external_id)).fetchone()
        if existing:
            return self.db.execute("SELECT id FROM evidence_spans WHERE evidence_id=?", (existing["id"],)).fetchone()["id"]
        evidence_id, span_id = str(uuid4()), str(uuid4())
        self.db.execute("INSERT INTO evidence_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (evidence_id, workspace_id, kind, external_id, title, content, json.dumps(metadata or {}), now()))
        self.db.execute("INSERT INTO evidence_spans VALUES (?, ?, ?, ?)", (span_id, evidence_id, quote, now()))
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
        rows = self.db.execute("SELECT decision_id FROM project_memory_entries WHERE workspace_id=? AND superseded_at IS NULL ORDER BY created_at DESC LIMIT 12", (workspace_id,)).fetchall()
        memory = [self.get_decision(row["decision_id"]) for row in rows]
        return {"workspace_id": workspace_id, "memory": memory, "active_intention": self.active_intention(workspace_id)}

    def today(self, workspace_id: str):
        pending = next((item for item in self.list_decisions(workspace_id) if item["review_status"] == "pending"), None)
        return {"workspace_id": workspace_id, "intention": self.active_intention(workspace_id), "memory": self.context(workspace_id)["memory"][:1], "pending_decision": pending}

    def guardrail_candidates(self, workspace_id: str):
        rows = self.db.execute(
            "SELECT statement, COUNT(*) AS count FROM decisions WHERE workspace_id=? AND review_status='confirmed' GROUP BY statement HAVING count >= 2",
            (workspace_id,),
        ).fetchall()
        return [{"statement": row["statement"], "citations": [item for item in self.list_decisions(workspace_id) if item["review_status"] == "confirmed" and item["statement"] == row["statement"]]} for row in rows]

    def github_credentials(self):
        names = {row["name"] for row in self.db.execute("SELECT name FROM connector_secrets WHERE name IN ('github_token', 'github_webhook_secret')")}
        return {"token_saved": "github_token" in names, "webhook_secret_saved": "github_webhook_secret" in names}

    def save_github_credentials(self, token: str | None, webhook_secret: str | None):
        for name, value in (("github_token", token), ("github_webhook_secret", webhook_secret)):
            if value:
                self.db.execute("INSERT INTO connector_secrets VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at", (name, protect(value), now()))
        state = "configured" if all(self.github_credentials().values()) else "partial"
        self.db.execute("INSERT INTO connector_state VALUES ('github', ?, ?) ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at", (state, now()))
        self.db.commit()
        return {"state": state, **self.github_credentials()}

    def delete_github_credentials(self):
        self.db.execute("DELETE FROM connector_secrets WHERE name IN ('github_token', 'github_webhook_secret')")
        self.db.execute("INSERT INTO connector_state VALUES ('github', 'disconnected', ?) ON CONFLICT(name) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at", (now(),))
        self.db.commit()
        return {"state": "disconnected", **self.github_credentials()}
