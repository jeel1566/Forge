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
database_request_lock = asyncio.Lock()


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


@app.middleware("http")
async def serialize_database_requests(request, call_next):
    if request.url.path.startswith("/assets"):
        return await call_next(request)
    async with database_request_lock:
        return await call_next(request)


class PendingDecision(BaseModel):
    statement: str = Field(min_length=1)
    category: str = "process"
    evidence_quote: str = Field(min_length=1)


class Review(BaseModel):
    status: str
    statement: str | None = Field(default=None, min_length=1)


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


class RulePolicy(BaseModel):
    mode: str = Field(pattern="^(approval|autonomous)$")


class SessionOutcome(BaseModel):
    agent: str = Field(min_length=1, max_length=100)
    worktree_path: str = Field(min_length=1, max_length=1000)
    branch: str = Field(min_length=1, max_length=255)
    outcome_key: str = Field(min_length=1, max_length=255)
    scope: list[str] = Field(min_length=1)
    category: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=4000)
    problem: str = Field(min_length=1, max_length=4000)
    prior_approach: str = Field(min_length=1, max_length=4000)
    why_prior_approach_failed: str = Field(min_length=1, max_length=4000)
    alternatives: list[dict] = Field(default_factory=list)
    chosen_fix: str = Field(min_length=1, max_length=4000)
    rationale: str = Field(min_length=1, max_length=4000)
    validation: str = Field(min_length=1, max_length=4000)
    risk: str = Field(min_length=1, max_length=4000)
    unresolved: str = Field(min_length=1, max_length=4000)
    proposed_rule: str = Field(min_length=1, max_length=4000)
    evidence_span_ids: list[str] = Field(min_length=1)
    learning_card_id: str | None = Field(default=None, min_length=1)
    learning_area: str | None = Field(default=None, max_length=200)
    learning_trigger: str | None = Field(default=None, max_length=400)
    learning_action: str | None = Field(default=None, max_length=400)


class RuleApproval(BaseModel):
    developer_approved: bool


class ReusableRuleOverride(BaseModel):
    action: str = Field(pattern="^(ignore|replace)$")
    statement: str | None = Field(default=None, min_length=1, max_length=4000)


class SessionFeedback(BaseModel):
    context_useful: str = Field(pattern="^(yes|partly|no)$")
    irrelevant_or_missing: str = Field(min_length=1, max_length=4000)
    rule_assessment: str = Field(pattern="^(approve|revise|coaching_only|reject)$")


class RuleVerification(BaseModel):
    result: str = Field(pattern="^(supported|contradicted|insufficient_data)$")
    evidence_span_id: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=4000)


class VerificationInput(BaseModel):
    source_kind: str = Field(pattern="^(configured_validation|git_change|github_review|local_failure)$")
    result: str = Field(pattern="^(supported|contradicted|insufficient_data)$")
    evidence_span_id: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=4000)
    developer_confirmed: bool = False


class LocalFailureInput(BaseModel):
    failure_class: str = Field(pattern="^(test_failure|build_failure|runtime_failure|review_regression)$")
    summary: str = Field(min_length=1, max_length=4000)
    result: str = Field(default="contradicted", pattern="^(supported|contradicted|insufficient_data)$")
    developer_confirmed: bool = False


class LearningAlertReview(BaseModel):
    decision: str = Field(pattern="^(merged|kept_separate|marked_conflict|dismissed)$")


@app.get("/health")
def health():
    return {"status": "ok", "service": "forge", "database": str(store.path), "instance_id": os.environ.get("FORGE_RUNTIME_INSTANCE_ID")}


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


@app.get("/v1/workspaces/{workspace_id}/decisions")
def decisions(workspace_id: str):
    return store.list_decisions(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/learning")
def learning_context(workspace_id: str, scope: str | None = None):
    return store.learning_context(workspace_id, scope)


@app.put("/v1/workspaces/{workspace_id}/rule-policy")
def configure_rule_policy(workspace_id: str, body: RulePolicy):
    try:
        return store.configure_rule_policy(workspace_id, body.mode)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/rules")
def rules(workspace_id: str, state: str | None = None):
    return store.list_rule_versions(workspace_id, state)


@app.post("/v1/rules/{rule_version_id}/reusable-request")
def request_reusable_rule(rule_version_id: str):
    try:
        return store.request_reusable_rule(rule_version_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/reusable-rules")
def reusable_rules(workspace_id: str, scope: str | None = None):
    return store.reusable_rules(workspace_id, scope)


@app.get("/v1/reusable-rules")
def reusable_rule_requests(state: str = "pending"):
    try:
        return store.reusable_rule_requests(state)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/reusable-rules/{reusable_rule_id}/approval")
def approve_reusable_rule(reusable_rule_id: str, body: RuleApproval):
    try:
        return store.approve_reusable_rule(reusable_rule_id, body.developer_approved)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.put("/v1/workspaces/{workspace_id}/reusable-rules/{reusable_rule_id}/override")
def override_reusable_rule(workspace_id: str, reusable_rule_id: str, body: ReusableRuleOverride):
    try:
        return store.set_reusable_rule_override(workspace_id, reusable_rule_id, body.action, body.statement)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/learning-cards")
def learning_cards(workspace_id: str, state: str | None = None):
    return store.learning_cards(workspace_id, state)


@app.get("/v1/workspaces/{workspace_id}/learning-cards/{card_id}")
def learning_card(workspace_id: str, card_id: str):
    card = next((item for item in store.learning_cards_for_id(card_id) if item["workspace_id"] == workspace_id), None)
    if not card:
        raise HTTPException(404, "Learning Card not found")
    return card


@app.get("/v1/workspaces/{workspace_id}/learning-alerts")
def learning_alerts(workspace_id: str):
    return store.learning_alerts(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/projection-status")
def projection_status(workspace_id: str):
    return store.projection_status(workspace_id)


@app.post("/v1/learning-alerts/{alert_id}/review")
def review_learning_alert(alert_id: str, body: LearningAlertReview):
    try:
        return store.review_learning_alert(alert_id, body.decision)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/session-start-context")
def session_start_context(workspace_id: str, scope: str | None = None):
    return store.session_start_context(workspace_id, scope)


@app.post("/v1/workspaces/{workspace_id}/handoffs/{handoff_id}/feedback")
def record_session_feedback(workspace_id: str, handoff_id: str, body: SessionFeedback):
    try:
        return store.record_session_feedback(workspace_id, handoff_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/workspaces/{workspace_id}/handoffs", status_code=201)
def record_session_handoff(workspace_id: str, body: SessionOutcome):
    try:
        result = store.record_session_handoff(workspace_id, **body.model_dump())
        rule = result.get("rule")
        if rule and rule.get("eligible") and store.rule_policy(workspace_id)["mode"] == "autonomous" and rule["state"] == "candidate":
            result["rule"] = store.activate_rule(rule["id"])
            result["activation"] = "autonomous"
        elif rule and rule.get("eligible"):
            result["activation"] = "pending_developer_approval"
        return result
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/workspaces/{workspace_id}/handoffs")
def session_handoffs(workspace_id: str, limit: int = 20):
    return store.list_session_outcomes(workspace_id, limit)


@app.get("/v1/handoffs/{handoff_id}")
def session_handoff(handoff_id: str):
    result = store.get_session_handoff(handoff_id)
    if not result:
        raise HTTPException(404, "Session Handoff not found")
    return result


@app.get("/v1/workspaces/{workspace_id}/legacy-history")
def legacy_history(workspace_id: str, limit: int = 20):
    return store.legacy_history(workspace_id, limit)


@app.get("/v1/rules/{rule_version_id}/proposal")
def rule_proposal(rule_version_id: str):
    try:
        return store.rule_proposal(rule_version_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/rules/{rule_version_id}/approve")
def approve_rule(rule_version_id: str, body: RuleApproval):
    try:
        return store.approve_rule(rule_version_id, body.developer_approved)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/rules/{rule_version_id}/verify")
def verify_rule(rule_version_id: str, body: RuleVerification):
    try:
        return store.verify_rule(rule_version_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/v1/rules/{rule_version_id}/verification-inputs")
def verification_inputs(rule_version_id: str):
    return store.verification_inputs(rule_version_id)


@app.post("/v1/rules/{rule_version_id}/verification-inputs", status_code=201)
def record_verification_input(rule_version_id: str, body: VerificationInput):
    try:
        return store.record_verification_input(rule_version_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/rules/{rule_version_id}/local-failures", status_code=201)
def record_local_failure(rule_version_id: str, body: LocalFailureInput):
    try:
        return store.record_local_failure(rule_version_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.post("/v1/verification-inputs/{input_id}/confirm")
def confirm_verification_input(input_id: str):
    try:
        return store.confirm_verification_input(input_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


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


@app.get("/v1/workspaces/{workspace_id}/decisions/retrieve")
def retrieve_decisions(workspace_id: str, file_path: str | None = None, scope: str | None = None, category: str | None = None, status: str | None = "confirmed", limit: int = 20):
    return store.retrieve_decisions(workspace_id, file_path=file_path, scope=scope, category=category, status=status, limit=limit)


@app.get("/v1/workspaces/{workspace_id}/evidence")
def evidence(workspace_id: str, kind: str = "git_commit", limit: int = 20):
    return store.list_evidence(workspace_id, kind=kind, limit=max(1, min(limit, 100)))


@app.get("/v1/evidence/{evidence_id}")
def evidence_detail(evidence_id: str):
    result = store.get_evidence(evidence_id)
    if not result:
        raise HTTPException(404, "evidence not found")
    return result


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


dashboard = Path(__file__).resolve().parent / "static" / "index.html"
assets = dashboard.parent / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")


@app.get("/")
def dashboard_root():
    if dashboard.exists():
        return FileResponse(dashboard)
    return {"message": "Build the dashboard with pnpm --dir frontend build."}
