import argparse
import json
import os
import subprocess
from pathlib import Path

import uvicorn

from .git import ingest_repository
from .installation import agent_status, install_agent, repair_agent, uninstall_agent
from .runtime import ForgeRuntime
from .store import Store
from .validation import run_configured_validation, run_validation


def _repository_path(path: str) -> Path:
    resolved = Path(path).resolve()
    result = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 and result.stdout.strip() else resolved


def _validation_config_status(repository: Path) -> str:
    path = repository / "forge.validation.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "missing"
    except json.JSONDecodeError:
        return "invalid"
    entries = document.get("validations") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not all(isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("argv"), list) and all(isinstance(part, str) and part for part in item["argv"]) for item in entries):
        return "invalid"
    return "healthy"


def _doctor(repository: Path, database: Path, agent: str | None) -> dict:
    runtime = ForgeRuntime(repository)
    database_status = {"state": "missing"}
    if database.exists():
        store = Store(database)
        try:
            database_status = {"state": "healthy" if store.integrity_check()["ok"] else "invalid", "integrity": store.integrity_check()["integrity"]}
        finally:
            store.close()
    agents = [agent_status(item) for item in (("codex", "antigravity") if agent in {None, "all"} else (agent,))]
    return {"repository": str(repository), "database": database_status, "validation_config": _validation_config_status(repository), "runtime": runtime.status(database), "agents": agents}


def main():
    parser = argparse.ArgumentParser(prog="forge")
    subcommands = parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start", help="Run Forge locally on 127.0.0.1")
    start.add_argument("--path", default=".", help="Git repository to register")
    start.add_argument("--port", type=int, default=8000)
    start.add_argument("--workspace", default="default")
    session_start = subcommands.add_parser("session-start", help="Start or reuse Forge locally for an agent session")
    session_start.add_argument("--path", default=".")
    session_start.add_argument("--workspace", default="default")
    session_start.add_argument("--agent", default="agent", choices=("agent", "codex", "antigravity"))
    session_end = subcommands.add_parser("session-end", help="Release this agent's local Forge session")
    session_end.add_argument("--path", default=".")
    session_end.add_argument("--session-id", required=True)
    session_end.add_argument("--workspace", default="default")
    session_end.add_argument("--abandon", action="store_true")
    session_end.add_argument("--reason", choices=("validation_unavailable", "handoff_incomplete", "developer_cancelled", "agent_error"))
    install = subcommands.add_parser("install", help="Install Forge for one coding agent only")
    install.add_argument("agent", choices=("codex", "antigravity"))
    install.add_argument("--path", help="Repository to enable the Antigravity dashboard sidecar")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--repair", action="store_true", help="Repair missing Forge-owned files for this agent")
    uninstall = subcommands.add_parser("uninstall", help="Remove Forge from one coding agent only")
    uninstall.add_argument("agent", choices=("codex", "antigravity"))
    uninstall.add_argument("--path", help="Repository whose Antigravity dashboard sidecar should be removed")
    uninstall.add_argument("--dry-run", action="store_true")
    repair = subcommands.add_parser("repair", help="Repair Forge-owned agent setup or stale local runtime metadata")
    repair.add_argument("agent", nargs="?", choices=("codex", "antigravity"))
    repair.add_argument("--path", default=".")
    repair.add_argument("--dry-run", action="store_true")
    backup = subcommands.add_parser("backup", help="Create a local SQLite backup")
    backup.add_argument("--path", default=".", help="Repository containing the Forge database")
    backup.add_argument("--output", required=True, help="New backup SQLite path")
    export = subcommands.add_parser("export", help="Export non-secret Forge data as JSON")
    export.add_argument("--path", default=".", help="Repository containing the Forge database")
    export.add_argument("--output", required=True, help="New JSON export path")
    doctor = subcommands.add_parser("doctor", help="Check local Forge installation and project health without changing data")
    doctor.add_argument("--path", default=".", help="Repository containing the Forge database")
    doctor.add_argument("--agent", choices=("codex", "antigravity", "all"))
    validate = subcommands.add_parser("validate", help="Run one local validation command and save safe evidence")
    validate.add_argument("--path", default=".", help="Repository containing the Forge database")
    validate.add_argument("--workspace", default="default")
    validate.add_argument("--label", required=True, help="Short validation name")
    validate.add_argument("--timeout-seconds", type=int, default=900)
    validate.add_argument("validation_command", nargs=argparse.REMAINDER, help="Command after --")
    configured_validate = subcommands.add_parser("validate-configured", help="Run one configured trusted validation")
    configured_validate.add_argument("--path", default=".")
    configured_validate.add_argument("--workspace", default="default")
    configured_validate.add_argument("validation_id")
    args = parser.parse_args()
    if args.command == "install":
        repository = _repository_path(args.path) if args.path else None
        print(repair_agent(args.agent, args.dry_run, repository) if args.repair else install_agent(args.agent, args.dry_run, repository))
        return
    if args.command == "uninstall":
        repository = _repository_path(args.path) if args.path else None
        print(uninstall_agent(args.agent, args.dry_run, repository))
        return
    repository_path = _repository_path(args.path) if hasattr(args, "path") else None
    database = os.environ.get("FORGE_DB_PATH", str(repository_path / ".forge" / "forge.sqlite3") if repository_path else None)
    if args.command == "doctor":
        print(_doctor(repository_path, Path(database), args.agent))
        return
    if args.command == "repair":
        runtime = ForgeRuntime(repository_path)
        runtime_result = {"runtime": runtime.status(database)["state"], "metadata_removed": False} if args.dry_run else runtime.repair_stale_metadata(database)
        agent_result = repair_agent(args.agent, args.dry_run) if args.agent else None
        print({"repository": str(repository_path), "runtime": runtime_result, "agent": agent_result})
        return
    if args.command == "session-end":
        result = ForgeRuntime(repository_path).end_session(args.session_id, args.abandon, args.reason)
        if Path(database).exists() and result["released"]:
            store = Store(database)
            try:
                store.record_session_end_event(args.workspace, result["agent"], "abandoned" if result["abandoned"] else "completed", result["handoff_id"], args.reason if result["abandoned"] else None)
            finally:
                store.close()
        print(result)
        return
    store = Store(database)
    try:
        if args.command == "backup":
            print(store.backup(args.output))
            return
        if args.command == "export":
            print(store.export(args.output))
            return
        if args.command == "validate":
            command = args.validation_command[1:] if args.validation_command[:1] == ["--"] else args.validation_command
            print(run_validation(store, args.workspace, args.label, command, args.timeout_seconds))
            return
        if args.command == "validate-configured":
            print(run_configured_validation(store, args.workspace, args.validation_id))
            return
        if args.command in {"start", "session-start"}:
            try:
                ingest_repository(store, args.workspace, repository_path)
            except ValueError:
                store.register_repository(args.workspace, str(repository_path))
            if args.command == "session-start":
                runtime = ForgeRuntime(repository_path).start_or_reuse(store.path, args.workspace, args.agent)
                print({"workspace_id": args.workspace, "database": str(store.path), **runtime})
                return
            os.environ["FORGE_DB_PATH"] = database
    finally:
        store.close()
    if args.command == "start":
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
