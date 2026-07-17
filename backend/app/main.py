from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .store import store
from .workflow import extraction_workflow

app = FastAPI(title="Forge", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


class PendingDecision(BaseModel):
    workspace_id: str = "default"
    statement: str = Field(min_length=1)
    category: str = "process"
    evidence_quote: str = Field(min_length=1)


class Review(BaseModel):
    status: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "forge"}


@app.get("/v1/workspaces/{workspace_id}/decisions")
def decisions(workspace_id: str):
    return store.list_decisions(workspace_id)


@app.get("/v1/workspaces/{workspace_id}/context")
def context(workspace_id: str):
    return store.context(workspace_id)


@app.post("/v1/workspaces/{workspace_id}/imports", status_code=201)
def record_decision(workspace_id: str, body: PendingDecision):
    candidate = extraction_workflow.invoke({**body.model_dump(), "workspace_id": workspace_id})["candidate"]
    return store.create_pending(**candidate)


@app.post("/v1/decisions/{decision_id}/review")
def review(decision_id: str, body: Review):
    if body.status not in {"confirmed", "rejected"}:
        raise HTTPException(422, "status must be confirmed or rejected")
    result = store.review(decision_id, body.status)
    if not result:
        raise HTTPException(404, "decision not found")
    if "error" in result:
        raise HTTPException(409, result["error"])
    return result
