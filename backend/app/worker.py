import asyncio
import os
from datetime import UTC, datetime

from .github import GitHubError, poll_github
from .store import Store


def run_due_github_polls(store: Store, current_time: str | None = None) -> list[dict]:
    results = []
    for workspace_id in store.due_github_polls(current_time or datetime.now(UTC).isoformat()):
        try:
            result = poll_github(store, workspace_id)
            store.record_github_poll_success(workspace_id, result)
            results.append({"workspace_id": workspace_id, "status": "partial" if result.get("partial") else "healthy", "result": result})
        except GitHubError as error:
            store.record_github_poll_failure(workspace_id, str(error), error.kind, error.retry_after_seconds, error.rate_limit_reset_at)
            results.append({"workspace_id": workspace_id, "status": error.kind, "reason": str(error)})
    return results


async def github_poll_scheduler(database_path: str, interval_seconds: int = 15, stop_event: asyncio.Event | None = None):
    while not (stop_event and stop_event.is_set()):
        store = Store(database_path)
        try:
            run_due_github_polls(store)
        finally:
            store.close()
        if stop_event:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(interval_seconds)


def main():
    database = os.environ.get("FORGE_DB_PATH", ".forge/forge.sqlite3")
    asyncio.run(github_poll_scheduler(database))


if __name__ == "__main__":
    main()
