from dataclasses import asdict, dataclass
from uuid import uuid4


@dataclass
class Decision:
    id: str
    workspace_id: str
    statement: str
    category: str
    review_status: str
    evidence_quote: str


class Store:
    # ponytail: in-process demo store; replace with Supabase calls after migrations are deployed.
    def __init__(self):
        self.decisions = {"demo-decision-1": Decision("demo-decision-1", "default", "Webhook ingestion stays asynchronous so public requests never wait for extraction.", "architecture", "pending", "Keep webhook ingestion asynchronous.")}

    def list_decisions(self, workspace_id: str):
        return [asdict(d) for d in self.decisions.values() if d.workspace_id == workspace_id]

    def context(self, workspace_id: str):
        return {"workspace_id": workspace_id, "memory": [d for d in self.list_decisions(workspace_id) if d["review_status"] == "confirmed"], "coaching": {"status": "insufficient_data", "reason": "More cited observations are required before coaching."}}

    def create_pending(self, workspace_id: str, statement: str, category: str, evidence_quote: str):
        decision = Decision(str(uuid4()), workspace_id, statement, category, "pending", evidence_quote)
        self.decisions[decision.id] = decision
        return asdict(decision)

    def review(self, decision_id: str, status: str):
        decision = self.decisions.get(decision_id)
        if not decision:
            return None
        if decision.review_status != "pending":
            return {"error": "already_reviewed", "decision": asdict(decision)}
        decision.review_status = status
        return {"decision": asdict(decision), "memory_created": status == "confirmed"}


store = Store()
