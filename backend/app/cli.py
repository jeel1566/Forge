import argparse
import os
from pathlib import Path

import uvicorn

from .git import ingest_repository
from .store import Store


def main():
    parser = argparse.ArgumentParser(prog="forge")
    subcommands = parser.add_subparsers(dest="command", required=True)
    start = subcommands.add_parser("start", help="Run Forge locally on 127.0.0.1")
    start.add_argument("--path", default=".", help="Git repository to register")
    start.add_argument("--port", type=int, default=8000)
    start.add_argument("--workspace", default="default")
    args = parser.parse_args()
    if args.command == "start":
        database = os.environ.get("FORGE_DB_PATH", str(Path(args.path).resolve() / ".forge" / "forge.sqlite3"))
        store = Store(database)
        try:
            ingest_repository(store, args.workspace, args.path)
        except ValueError:
            store.register_repository(args.workspace, args.path)
        os.environ["FORGE_DB_PATH"] = database
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
