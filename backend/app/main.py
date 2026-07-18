import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .coordination import coordination_status
from .git import ingest_repository, workspace_id_for_repository
from .github import GitHubError, poll_github
from .store import Store
from .worker import github_poll_scheduler
from .worktree import git_common_dir
from .workflow import create_candidate

store = Store(os.environ.get("FORGE_DB_PATH"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    scheduler_stop = asyncio.Event()
    scheduler = asyncio.create_task(github_poll_scheduler(str(store.path), stop_event=scheduler_stop))
    try:
        yield
    finally:
        scheduler_stop.set()
        await scheduler
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


class RepositoryRegistration(BaseModel):
    path: str = Field(min_length=1)


class CoordinationConfig(BaseModel):
    base_ref: str | None = Field(default=None, max_length=255)


class GitHubCredentials(BaseModel):
    token: str = Field(min_length=1)


class GitHubPollingConfig(BaseModel):
    enabled: bool
    interval_seconds: int = Field(default=900, ge=60, le=86_400)


class AgentsGuardrailHandoff(BaseModel):
    statement: str = Field(min_length=1)
    current_agents_content: str = ""
    target_agents_path: str = "AGENTS.md"


class AgentsGuardrailCompletion(BaseModel):
    developer_approved: bool
    resulting_agents_content: str


class ReflectionReview(BaseModel):
    status: str


class SessionContextReview(BaseModel):
    status: str


class StructuredSessionHandoff(BaseModel):
    agent: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    evidence_span_ids: list[str] = Field(min_length=1)
    template: dict
    base_commit: str | None = None
    head_commit: str | None = None


class StructuredDecision(BaseModel):
    source_session_context_id: str = Field(min_length=1)
    evidence_span_ids: list[str] = Field(min_length=1)
    template: dict


@app.get("/health")
def health():
    return {"status": "ok", "service": "forge", "database": str(store.path)}


@app.get("/v1/repositories")
def repositories():
    return store.repositories()


@app.post("/v1/repositories", status_code=201)
def register_repository(body: RepositoryRegistration):
    try:
        workspace_id = workspace_id_for_repository(body.path)
        existing_workspace = store.workspace_for_git_common_dir(git_common_dir(body.path))
        if existing_workspace:
            workspace_id = existing_workspace
        result = ingest_repository(store, workspace_id, body.path)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return {"workspace_id": workspace_id, "repository": store.repository(workspace_id), "import": result}


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


@app.get("/v1/workspaces/{workspace_id}/coordination")
def coordination(workspace_id: str):
    return coordination_status(store, workspace_id)


@app.put("/v1/workspaces/{workspace_id}/coordination")
def configure_coordination(workspace_id: str, body: CoordinationConfig):
    if not store.repository(workspace_id):
        raise HTTPException(404, "repository not registered")
    return store.set_coordination_base_ref(workspace_id, body.base_ref)


@app.get("/v1/workspaces/{workspace_id}/history")
def history(workspace_id: str):
    return store.history(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/session-contexts")
def session_contexts(workspace_id: str, status: str | None = None, query: str | None = None, scope: str | None = None, file_path: str | None = None, include_archived: bool = False, limit: int = 100):
    return store.list_session_contexts(workspace_id, status=status, query_text=query, scope=scope, file_path=file_path, include_archived=include_archived, limit=max(1, min(limit, 100)))


@app.post("/v1/workspaces/{workspace_id}/session-contexts", status_code=201)
def create_structured_session_context(workspace_id: str, body: StructuredSessionHandoff):
    try:
        return store.create_structured_session_context(workspace_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/decisions/retrieve")
def retrieve_decisions(workspace_id: str, file_path: str | None = None, scope: str | None = None, category: str | None = None, status: str | None = "confirmed", limit: int = 20):
    return store.retrieve_decisions(workspace_id, file_path=file_path, scope=scope, category=category, status=status, limit=limit)


@app.post("/v1/workspaces/{workspace_id}/decisions", status_code=201)
def create_structured_decision(workspace_id: str, body: StructuredDecision):
    try:
        return store.create_structured_decision(workspace_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


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


@app.get("/v1/workspaces/{workspace_id}/portable-guardrails")
def portable_guardrails(workspace_id: str):
    return store.portable_guardrails(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/agents-guardrail-handoffs")
def agents_guardrail_handoffs(workspace_id: str):
    return store.list_agents_guardrail_handoffs(workspace_id)


@app.post("/v1/workspaces/{workspace_id}/agents-guardrail-handoffs", status_code=201)
def prepare_agents_guardrail_handoff(workspace_id: str, body: AgentsGuardrailHandoff):
    try:
        return store.prepare_agents_guardrail_handoff(workspace_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/workspaces/{workspace_id}/portable-guardrails/{source_guardrail_id}/handoffs", status_code=201)
def prepare_portable_guardrail_handoff(workspace_id: str, source_guardrail_id: str, body: AgentsGuardrailHandoff):
    try:
        return store.prepare_agents_guardrail_handoff(workspace_id, body.statement, body.current_agents_content, body.target_agents_path, source_guardrail_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/agents-guardrail-handoffs/{handoff_id}/complete")
def complete_agents_guardrail_handoff(handoff_id: str, body: AgentsGuardrailCompletion):
    try:
        return store.complete_agents_guardrail_handoff(handoff_id, body.developer_approved, body.resulting_agents_content)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


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


@app.get("/v1/workspaces/{workspace_id}/github/status")
def github_poll_status(workspace_id: str):
    if not store.repository(workspace_id):
        raise HTTPException(404, "repository not registered")
    return store.github_poll_status(workspace_id)


@app.put("/v1/workspaces/{workspace_id}/github/status")
def configure_github_polling(workspace_id: str, body: GitHubPollingConfig):
    try:
        return store.configure_github_polling(workspace_id, body.enabled, body.interval_seconds)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/workspaces/{workspace_id}/github/poll")
def poll_workspace_github(workspace_id: str):
    try:
        result = poll_github(store, workspace_id)
        store.record_github_poll_success(workspace_id, result)
        return result
    except GitHubError as error:
        store.record_github_poll_failure(workspace_id, str(error), error.kind, error.retry_after_seconds, error.rate_limit_reset_at)
        status = 409 if error.kind == "poll_in_progress" else 401 if error.kind == "authentication_failed" else 403 if error.kind == "authorization_failed" else 429 if error.kind == "rate_limited" else 502
        raise HTTPException(status, {"health": error.kind, "message": str(error)}) from error


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


@app.post("/v1/session-contexts/{session_id}/review")
def review_session_context(session_id: str, body: SessionContextReview):
    if body.status not in {"approved", "dismissed"}:
        raise HTTPException(422, "status must be approved or dismissed")
    result = store.review_session_context(session_id, body.status)
    if not result:
        raise HTTPException(404, "session context not found")
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result


@app.post("/v1/session-contexts/{session_id}/archive")
def archive_session_context(session_id: str):
    if not store.archive_session_context(session_id):
        raise HTTPException(404, "approved session context not found")
    return {"archived": True}


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
