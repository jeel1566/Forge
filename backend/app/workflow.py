from typing import TypedDict
from langgraph.graph import END, START, StateGraph


class ExtractionState(TypedDict):
    workspace_id: str
    statement: str
    category: str
    evidence_quote: str
    candidate: dict


def make_candidate(state: ExtractionState):
    return {"candidate": {key: state[key] for key in ("workspace_id", "statement", "category", "evidence_quote")}}


graph = StateGraph(ExtractionState)
graph.add_node("make_candidate", make_candidate)
graph.add_edge(START, "make_candidate")
graph.add_edge("make_candidate", END)
extraction_workflow = graph.compile()
