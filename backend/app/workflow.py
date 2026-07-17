def create_candidate(workspace_id: str, statement: str, category: str, evidence_quote: str) -> dict:
    """Keep agent proposals explicit; Forge never performs model extraction."""
    return {"workspace_id": workspace_id, "statement": statement, "category": category, "evidence_quote": evidence_quote}
