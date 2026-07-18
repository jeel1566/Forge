DECISION_CATEGORIES = {"architecture", "api", "security", "testing", "operations", "process"}
TEMPLATE_VERSION = 1


def _text(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required; use 'unknown' or 'not_run' when the fact is unavailable.")
    return value.strip()


def _scope(value: list[str] | None) -> list[str]:
    if not isinstance(value, list) or not (items := [item.strip() for item in value if isinstance(item, str) and item.strip()]):
        raise ValueError("scope requires at least one module or area.")
    return list(dict.fromkeys(items))


def handoff_fields(payload: dict) -> dict:
    changed = payload.get("changed")
    if not isinstance(changed, list) or not changed:
        raise ValueError("changed requires at least one file path and explanation.")
    normalized_changed = []
    for item in changed:
        if not isinstance(item, dict):
            raise ValueError("changed entries must include path and summary.")
        normalized_changed.append({"path": _text(item.get("path"), "changed.path"), "summary": _text(item.get("summary"), "changed.summary")})
    return {
        "template_version": TEMPLATE_VERSION,
        "scope": _scope(payload.get("scope")),
        "summary": _text(payload.get("summary"), "summary"),
        "why": _text(payload.get("why"), "why"),
        "changed": normalized_changed,
        "decisions": _text(payload.get("decisions"), "decisions"),
        "validation": _text(payload.get("validation"), "validation"),
        "risks_constraints": _text(payload.get("risks_constraints"), "risks_constraints"),
        "unresolved": _text(payload.get("unresolved"), "unresolved"),
    }


def decision_fields(payload: dict) -> dict:
    category = _text(payload.get("category"), "category")
    if category not in DECISION_CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(sorted(DECISION_CATEGORIES))}.")
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list):
        raise ValueError("alternatives must be a list; use [] when none were considered.")
    normalized_alternatives = []
    for item in alternatives:
        if not isinstance(item, dict):
            raise ValueError("alternatives entries must include option and reason.")
        normalized_alternatives.append({"option": _text(item.get("option"), "alternatives.option"), "reason": _text(item.get("reason"), "alternatives.reason")})
    return {
        "template_version": TEMPLATE_VERSION,
        "category": category,
        "scope": _scope(payload.get("scope")),
        "decision": _text(payload.get("decision"), "decision"),
        "context": _text(payload.get("context"), "context"),
        "chosen_approach": _text(payload.get("chosen_approach"), "chosen_approach"),
        "alternatives": normalized_alternatives,
        "benefits": _text(payload.get("benefits"), "benefits"),
        "costs": _text(payload.get("costs"), "costs"),
        "follow_up": _text(payload.get("follow_up"), "follow_up"),
        "applicability": _text(payload.get("applicability"), "applicability"),
        "supersedes_decision_id": payload.get("supersedes_decision_id") or None,
    }
