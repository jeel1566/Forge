import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .git import ingest_repository
from .store import Store
from .workflow import create_candidate

store = Store(os.environ.get("FORGE_DB_PATH"))
app = FastAPI(title="Forge", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class PendingDecision(BaseModel):
    statement: str = Field(min_length=1)
    category: str = "process"
    evidence_quote: str = Field(min_length=1)


class Review(BaseModel):
    status: str
    statement: str | None = Field(default=None, min_length=1)


class Intention(BaseModel):
    statement: str = Field(min_length=1)


class GitImport(BaseModel):
    path: str = "."


class GitHubCredentials(BaseModel):
    token: str | None = Field(default=None, min_length=1)
    webhook_secret: str | None = Field(default=None, min_length=1)


@app.get("/health")
def health():
    return {"status": "ok", "service": "forge", "database": str(store.path)}


@app.get("/v1/workspaces/{workspace_id}/today")
def today(workspace_id: str):
    return store.today(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/decisions")
def decisions(workspace_id: str):
    return store.list_decisions(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/context")
def context(workspace_id: str):
    return store.context(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/evidence")
def evidence(workspace_id: str, limit: int = 20):
    return store.list_evidence(workspace_id, limit=max(1, min(limit, 100)))


@app.get("/v1/evidence/{evidence_id}")
def evidence_detail(evidence_id: str):
    result = store.get_evidence(evidence_id)
    if not result:
        raise HTTPException(404, "evidence not found")
    return result


@app.get("/v1/workspaces/{workspace_id}/agents-guardrails")
def agents_guardrails(workspace_id: str):
    """Cited candidates only; Forge never reads or writes AGENTS.md."""
    return {"candidates": store.guardrail_candidates(workspace_id)}


@app.get("/v1/connectors/github")
def github_credentials():
    return store.github_credentials()


@app.put("/v1/connectors/github")
def save_github_credentials(body: GitHubCredentials):
    if not body.token and not body.webhook_secret:
        raise HTTPException(422, "provide a token or webhook secret")
    try:
        return store.save_github_credentials(body.token, body.webhook_secret)
    except (OSError, RuntimeError) as error:
        raise HTTPException(500, str(error)) from error


@app.delete("/v1/connectors/github")
def delete_github_credentials():
    return store.delete_github_credentials()


@app.post("/v1/workspaces/{workspace_id}/imports", status_code=201)
def record_decision(workspace_id: str, body: PendingDecision):
    return store.create_pending(**create_candidate(workspace_id, **body.model_dump()))


@app.post("/v1/workspaces/{workspace_id}/git/imports")
def import_git(workspace_id: str, body: GitImport):
    try:
        return ingest_repository(store, workspace_id, body.path)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/workspaces/{workspace_id}/intention", status_code=201)
def set_intention(workspace_id: str, body: Intention):
    store.set_intention(workspace_id, body.statement)
    return store.active_intention(workspace_id)


@app.post("/v1/decisions/{decision_id}/review")
def review(decision_id: str, body: Review):
    if body.status not in {"confirmed", "rejected"}:
        raise HTTPException(422, "status must be confirmed or rejected")
    result = store.review(decision_id, body.status, body.statement)
    if not result:
        raise HTTPException(404, "decision not found")
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


dashboard = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "index.html"
assets = dashboard.parent / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/")
def dashboard_root():
    if dashboard.exists():
        return FileResponse(dashboard)
    return {"message": "Build the dashboard with pnpm --dir frontend build."}
