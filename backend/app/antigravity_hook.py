import argparse
import json
import os
import sys
from pathlib import Path

from .git import workspace_id_for_repository
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    workspaces = payload.get("workspacePaths") or []
    workspace_path = workspaces[0] if workspaces else None
    database = args.database or os.environ.get("FORGE_DB_PATH") or (str(Path(workspace_path) / ".forge" / "forge.sqlite3") if workspace_path else None)
    if database and Path(database).exists() and workspace_path:
        store = Store(database)
        try:
            workspace_id = store.workspace_for_path(workspace_path) or workspace_id_for_repository(workspace_path)
            store.record_agent_stop(workspace_id, payload.get("conversationId", "unknown"), workspace_path, payload.get("executionNum"), payload.get("terminationReason"), bool(payload.get("fullyIdle")))
        finally:
            store.close()
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
