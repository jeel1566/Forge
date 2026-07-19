from __future__ import annotations

import json
import os
import re
import socket
from hashlib import sha256
from pathlib import Path


MANAGED_START = "<!-- forge:agent-instructions:start -->"
MANAGED_END = "<!-- forge:agent-instructions:end -->"
SKILL_MARKER = "<!-- forge:managed-skill -->"
SIDECAR_PREFIX = "forge-dashboard-"


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def _replace_block(current: str, block: str | None) -> str:
    start = current.find(MANAGED_START)
    end = current.find(MANAGED_END)
    if (start == -1) != (end == -1):
        raise ValueError("Forge managed instruction markers are incomplete; repair them before installing.")
    if start != -1:
        end += len(MANAGED_END)
        current = current[:start].rstrip() + current[end:].lstrip()
    if not block:
        return current.rstrip() + ("\n" if current.strip() else "")
    return current.rstrip() + ("\n\n" if current.strip() else "") + block + "\n"


def _instructions(agent: str) -> str:
    return "\n".join((
        MANAGED_START,
        "## Forge local project memory",
        f"At the start of meaningful work, run `forge session-start --path . --agent {agent}`, then call `forge_get_session_start_context` through Forge MCP.",
        f"At session start, retain the `session_id` returned by Forge. When the developer types `/forge_end`, use the installed Forge End skill. It runs configured checks, calls `forge_complete_session` with that session ID, reports alerts, then releases that exact lease.",
        "Never send raw chat transcripts, secrets, command output, or GitHub credentials to Forge. If Forge is offline, continue normally and say shared context is unavailable.",
        f"This block is managed only by `forge install {agent}` and `forge uninstall {agent}`.",
        MANAGED_END,
    ))


def _write(path: Path, content: str, dry_run: bool):
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".forge.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _remove_toml_section(content: str, section: str) -> str:
    pattern = rf"(?ms)^\[{re.escape(section)}\]\r?\n.*?(?=^\[|\Z)"
    return re.sub(pattern, "", content).strip() + ("\n" if content.strip() else "")


def _codex_config(with_forge: bool) -> tuple[Path, str]:
    path = _home() / ".codex" / "config.toml"
    content = _read(path)
    content = _remove_toml_section(content, "mcp_servers.forge.env")
    content = _remove_toml_section(content, "mcp_servers.forge")
    if with_forge:
        content = content.rstrip() + "\n\n# forge:managed\n[mcp_servers.forge]\ncommand = \"forge-mcp\"\n"
    return path, content


def _antigravity_config(with_forge: bool) -> tuple[Path, str]:
    path = _home() / ".gemini" / "config" / "mcp_config.json"
    current = _read(path)
    try:
        document = json.loads(current) if current.strip() else {}
    except json.JSONDecodeError as error:
        raise ValueError(f"Antigravity MCP configuration is not valid JSON: {path}") from error
    servers = document.setdefault("mcpServers", {})
    if with_forge:
        servers["forge"] = {"command": "forge-mcp"}
    else:
        servers.pop("forge", None)
    return path, json.dumps(document, indent=2) + "\n"


def _instruction_path(agent: str) -> Path:
    return _home() / (".codex/AGENTS.md" if agent == "codex" else ".gemini/GEMINI.md")


def _skill_path(agent: str) -> Path:
    return _home() / (".codex/skills/forge-end/SKILL.md" if agent == "codex" else ".gemini/skills/forge-end/SKILL.md")


def _config_path(agent: str) -> Path:
    return _home() / (".codex/config.toml" if agent == "codex" else ".gemini/config/mcp_config.json")


def _antigravity_settings_path() -> Path:
    return _home() / ".gemini/config/config.json"


def _sidecar_id(repository: Path) -> str:
    return SIDECAR_PREFIX + sha256(str(repository.resolve()).encode("utf-8")).hexdigest()[:12]


def _sidecar_path(repository: Path) -> Path:
    return _home() / ".gemini/config/sidecars" / _sidecar_id(repository) / "sidecar.json"


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _antigravity_settings() -> tuple[Path, dict]:
    path = _antigravity_settings_path()
    current = _read(path)
    try:
        document = json.loads(current) if current.strip() else {}
    except json.JSONDecodeError as error:
        raise ValueError(f"Antigravity configuration is not valid JSON: {path}") from error
    if not isinstance(document, dict):
        raise ValueError(f"Antigravity configuration must be a JSON object: {path}")
    return path, document


def _install_antigravity_sidecar(repository: Path, dry_run: bool) -> dict:
    sidecar_id = _sidecar_id(repository)
    sidecar_path = _sidecar_path(repository)
    port = _available_port()
    sidecar = {
        "display_name": "Forge dashboard",
        "description": "Local Forge dashboard for this repository.",
        "command": "forge",
        "args": ["start", "--path", str(repository), "--port", str(port)],
        "restart_policy": "on-failure",
    }
    settings_path, settings = _antigravity_settings()
    settings.setdefault("sidecars", {})[sidecar_id] = {"enabled": True}
    _write(sidecar_path, json.dumps(sidecar, indent=2) + "\n", dry_run)
    _write(settings_path, json.dumps(settings, indent=2) + "\n", dry_run)
    return {"id": sidecar_id, "config": str(sidecar_path), "port": port, "url": f"http://127.0.0.1:{port}", "enabled": True}


def _remove_antigravity_sidecar(repository: Path, dry_run: bool) -> dict:
    sidecar_id = _sidecar_id(repository)
    sidecar_path = _sidecar_path(repository)
    settings_path, settings = _antigravity_settings()
    settings.get("sidecars", {}).pop(sidecar_id, None)
    if not dry_run:
        if sidecar_path.exists():
            sidecar_path.unlink()
        try:
            sidecar_path.parent.rmdir()
        except OSError:
            pass
    _write(settings_path, json.dumps(settings, indent=2) + "\n", dry_run)
    return {"id": sidecar_id, "config": str(sidecar_path), "removed": True}


def _end_skill(agent: str) -> str:
    return "\n".join((
        "---",
        "name: forge-end",
        "description: Complete a Forge agent session without sending a raw chat transcript.",
        "---",
        "",
        SKILL_MARKER,
        "# Forge End",
        "Use this when the developer types `/forge_end`.",
        "",
        "1. Review only your own work and current chat. Never read or send raw transcripts, secrets, raw command output, or credentials.",
        "2. Keep the `session_id` returned by `forge session-start`. Call `forge_heartbeat_session` before or after long work so a live session remains active.",
        "3. Run each applicable `forge_run_configured_validation` ID from `forge.validation.json`, then call `forge_get_recent_evidence`.",
        "4. Write one concise structured Session Handoff: goal, problem, prior approach, why it failed, alternatives, chosen fix, rationale, validation, risk, unresolved work, and optional structured rule fields.",
        "5. Call `forge_complete_session` once with the session ID and handoff. Its required keys are: agent, worktree_path, branch, outcome_key, scope, category, goal, problem, prior_approach, why_prior_approach_failed, alternatives, chosen_fix, rationale, validation, risk, unresolved, proposed_rule, and evidence_span_ids. Use `unresolved` (not `unresolved_work`) and set `proposed_rule` to `none` when no rule is proposed.",
        "   Use this shape: `{agent: 'antigravity', worktree_path: '.', branch: '<current branch>', outcome_key: '<unique session key>', scope: ['repository'], category: '<work category>', goal: '<goal>', problem: '<problem>', prior_approach: '<prior approach>', why_prior_approach_failed: '<why>', alternatives: [], chosen_fix: '<fix>', rationale: '<why this fix>', validation: '<result>', risk: '<risk>', unresolved: '<unresolved work or none>', proposed_rule: 'none', evidence_span_ids: ['<persisted evidence span id>']}`. Add learning fields only when proposing a rule.",
        "6. Present persisted completion, Learning Card, and alert results to the developer. Do not invent facts.",
        f"7. Only after successful completion, run `forge session-end --path . --session-id <session_id>`.",
        f"8. If completion cannot succeed, keep the lease active. Only use `forge session-end --path . --session-id <session_id> --abandon --reason <fixed-reason>` after the developer explicitly asks to abandon it.",
        "",
    ))


def _write_skill(path: Path, content: str | None, dry_run: bool):
    current = _read(path)
    if current and SKILL_MARKER not in current:
        raise ValueError(f"Forge will not overwrite an existing non-Forge skill: {path}")
    if dry_run:
        return
    if content is None:
        if path.exists():
            path.unlink()
        return
    _write(path, content, False)


def agent_status(agent: str) -> dict:
    if agent not in {"codex", "antigravity"}:
        raise ValueError("agent must be codex or antigravity")
    config_path = _config_path(agent)
    config = _read(config_path)
    if agent == "codex":
        config_state = "healthy" if '[mcp_servers.forge]' in config and 'command = "forge-mcp"' in config else "missing"
    else:
        try:
            document = json.loads(config) if config.strip() else {}
            config_state = "healthy" if document.get("mcpServers", {}).get("forge", {}).get("command") == "forge-mcp" else "missing"
        except json.JSONDecodeError:
            config_state = "invalid"
    instruction = _read(_instruction_path(agent))
    start, end = instruction.find(MANAGED_START), instruction.find(MANAGED_END)
    instruction_state = "healthy" if start != -1 and end != -1 and start < end else "incomplete" if (start == -1) != (end == -1) else "missing"
    skill = _read(_skill_path(agent))
    skill_state = "healthy" if SKILL_MARKER in skill else "foreign" if skill else "missing"
    healthy = config_state == instruction_state == skill_state == "healthy"
    return {"agent": agent, "healthy": healthy, "mcp": config_state, "instructions": instruction_state, "skill": skill_state}


def install_agent(agent: str, dry_run: bool = False, repository: Path | None = None) -> dict:
    if agent not in {"codex", "antigravity"}:
        raise ValueError("agent must be codex or antigravity")
    config_path, config = _codex_config(True) if agent == "codex" else _antigravity_config(True)
    instruction_path = _instruction_path(agent)
    instructions = _replace_block(_read(instruction_path), _instructions(agent))
    skill_path = _skill_path(agent)
    _write(config_path, config, dry_run)
    _write(instruction_path, instructions, dry_run)
    _write_skill(skill_path, _end_skill(agent), dry_run)
    sidecar = _install_antigravity_sidecar(repository, dry_run) if agent == "antigravity" and repository else None
    return {"agent": agent, "dry_run": dry_run, "mcp_config": str(config_path), "instructions": str(instruction_path), "skill": str(skill_path), "command": "forge-mcp", "dashboard_sidecar": sidecar, "status": agent_status(agent) if not dry_run else "would_install"}


def repair_agent(agent: str, dry_run: bool = False, repository: Path | None = None) -> dict:
    before = agent_status(agent)
    result = install_agent(agent, dry_run, repository)
    return {**result, "repaired": not before["healthy"], "before": before}


def uninstall_agent(agent: str, dry_run: bool = False, repository: Path | None = None) -> dict:
    if agent not in {"codex", "antigravity"}:
        raise ValueError("agent must be codex or antigravity")
    config_path, config = _codex_config(False) if agent == "codex" else _antigravity_config(False)
    instruction_path = _instruction_path(agent)
    instructions = _replace_block(_read(instruction_path), None)
    skill_path = _skill_path(agent)
    _write(config_path, config, dry_run)
    _write(instruction_path, instructions, dry_run)
    _write_skill(skill_path, None, dry_run)
    sidecar = _remove_antigravity_sidecar(repository, dry_run) if agent == "antigravity" and repository else None
    return {"agent": agent, "dry_run": dry_run, "mcp_config": str(config_path), "instructions": str(instruction_path), "skill": str(skill_path), "dashboard_sidecar": sidecar, "removed": True}
