import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .git import ingest_repository
from .github import GitHubError, poll_github
from .store import Store
from .workflow import create_candidate

store = Store(os.environ.get("FORGE_DB_PATH"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        yield
    finally:
        store.close()


app = FastAPI(title="Forge", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def local_request_guard(request, call_next):
    client_host = request.client.host if request.client else None
    if client_host and client_host not in {"127.0.0.1", "::1", "testclient"}:
        return JSONResponse({"detail": "Forge accepts loopback requests only."}, status_code=403)
    origin = request.headers.get("origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
        return JSONResponse({"detail": "Forge rejected a non-local browser request."}, status_code=403)
    return await call_next(request)


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
    token: str = Field(min_length=1)


class ReflectionReview(BaseModel):
    status: str


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


@app.get("/v1/workspaces/{workspace_id}/repository")
def repository(workspace_id: str):
    result = store.repository(workspace_id)
    if not result:
        raise HTTPException(404, "repository not registered")
    return result


@app.get("/v1/workspaces/{workspace_id}/history")
def history(workspace_id: str):
    return store.history(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/evidence")
def evidence(workspace_id: str, kind: str = "git_commit", limit: int = 20):
    return store.list_evidence(workspace_id, kind=kind, limit=max(1, min(limit, 100)))


@app.get("/v1/evidence/{evidence_id}")
def evidence_detail(evidence_id: str):
    result = store.get_evidence(evidence_id)
    if not result:
        raise HTTPException(404, "evidence not found")
    return result


@app.get("/v1/workspaces/{workspace_id}/agents-guardrails")
def agents_guardrails(workspace_id: str):
    """Cited candidates only; Forge never reads or writes AGENTS.md."""
    return store.guardrail_candidates(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/approved-guardrails")
def approved_guardrails(workspace_id: str):
    return store.approved_guardrails(workspace_id)


@app.get("/v1/connectors/github")
def github_credentials():
    return store.github_credentials()


@app.put("/v1/connectors/github")
def save_github_credentials(body: GitHubCredentials):
    try:
        return store.save_github_token(body.token)
    except (OSError, RuntimeError) as error:
        raise HTTPException(500, str(error)) from error


@app.delete("/v1/connectors/github")
def delete_github_credentials():
    return store.delete_github_credentials()


@app.post("/v1/workspaces/{workspace_id}/github/poll")
def poll_workspace_github(workspace_id: str):
    try:
        return poll_github(store, workspace_id)
    except PermissionError as error:
        raise HTTPException(409, str(error)) from error
    except GitHubError as error:
        raise HTTPException(502, str(error)) from error


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


@app.post("/v1/reflections/{reflection_id}/review")
def review_reflection(reflection_id: str, body: ReflectionReview):
    if body.status not in {"confirmed", "dismissed"}:
        raise HTTPException(422, "status must be confirmed or dismissed")
    result = store.review_reflection(reflection_id, body.status)
    if not result:
        raise HTTPException(404, "reflection not found")
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@app.post("/v1/memory/{entry_id}/archive")
def archive_memory(entry_id: str):
    if not store.archive_memory(entry_id):
        raise HTTPException(404, "active memory entry not found")
    return {"archived": True}


dashboard = Path(__file__).resolve().parent / "static" / "index.html"
assets = dashboard.parent / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/")
def dashboard_root():
    if dashboard.exists():
        return FileResponse(dashboard)
    return {"message": "Build the dashboard with pnpm --dir frontend build."}
