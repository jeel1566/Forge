import argparse
import os
from pathlib import Path

import uvicorn

from .git import ingest_repository
from .store import Store
from .validation import run_configured_validation, run_validation


def main():
    parser = argparse.ArgumentParser(prog="forge")
    subcommands = parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start", help="Run Forge locally on 127.0.0.1")
    start.add_argument("--path", default=".", help="Git repository to register")
    start.add_argument("--port", type=int, default=8000)
    start.add_argument("--workspace", default="default")
    backup = subcommands.add_parser("backup", help="Create a local SQLite backup")
    backup.add_argument("--path", default=".", help="Repository containing the Forge database")
    backup.add_argument("--output", required=True, help="New backup SQLite path")
    export = subcommands.add_parser("export", help="Export non-secret Forge data as JSON")
    export.add_argument("--path", default=".", help="Repository containing the Forge database")
    export.add_argument("--output", required=True, help="New JSON export path")
    doctor = subcommands.add_parser("doctor", help="Check local Forge database integrity")
    doctor.add_argument("--path", default=".", help="Repository containing the Forge database")
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
    database = os.environ.get("FORGE_DB_PATH", str(Path(args.path).resolve() / ".forge" / "forge.sqlite3"))
    store = Store(database)
    try:
        if args.command == "backup":
            print(store.backup(args.output))
            return
        if args.command == "export":
            print(store.export(args.output))
            return
        if args.command == "doctor":
            print(store.integrity_check())
            return
        if args.command == "validate":
            command = args.validation_command[1:] if args.validation_command[:1] == ["--"] else args.validation_command
            print(run_validation(store, args.workspace, args.label, command, args.timeout_seconds))
            return
        if args.command == "validate-configured":
            print(run_configured_validation(store, args.workspace, args.validation_id))
            return
        if args.command == "start":
            try:
                ingest_repository(store, args.workspace, args.path)
            except ValueError:
                store.register_repository(args.workspace, args.path)
            os.environ["FORGE_DB_PATH"] = database
    finally:
        store.close()
    if args.command == "start":
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
