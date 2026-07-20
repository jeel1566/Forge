from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4


RUNTIME_FILE = "runtime.json"
LOCK_FILE = "runtime.lock"
LEASE_SECONDS = 60 * 60 * 4
START_TIMEOUT_SECONDS = 12
LOCK_STALE_SECONDS = 60


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_at() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)).isoformat()


def _is_expired(timestamp: str | None) -> bool:
    if not timestamp:
        return True
    try:
        return datetime.fromisoformat(timestamp) <= datetime.now(timezone.utc)
    except ValueError:
        return True


def _process_is_alive(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value == 259)
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


class ForgeRuntime:
    """Owns the optional local Forge process for one repository."""

    def __init__(self, repository: str | Path):
        self.repository = Path(repository).resolve()
        self.directory = self.repository / ".forge"
        self.path = self.directory / RUNTIME_FILE
        self.lock_path = self.directory / LOCK_FILE

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def status(self, database: str | Path) -> dict:
        runtime = self._read()
        if not runtime:
            return {"state": "absent"}
        if runtime.get("mode") == "lease_only":
            return {"state": "lease_only", "lease_count": len(runtime.get("leases", {}))}
        database_path = Path(database).resolve()
        port, instance_id = runtime.get("port"), runtime.get("instance_id")
        healthy = bool(port and instance_id and self._healthy(int(port), database_path, instance_id))
        return {"state": "healthy" if healthy else "stale", "pid": runtime.get("pid"), "port": port, "lease_count": len(runtime.get("leases", {}))}

    def repair_stale_metadata(self, database: str | Path) -> dict:
        self._remove_stale_lock()
        status = self.status(database)
        if status["state"] != "stale":
            return {"runtime": status["state"], "metadata_removed": False}
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return {"runtime": "stale", "metadata_removed": True}

    def _write(self, runtime: dict):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(runtime, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @contextmanager
    def _lock(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        descriptor = None
        while descriptor is None:
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(descriptor, json.dumps({"pid": os.getpid(), "created_at": _timestamp()}).encode("utf-8"))
            except FileExistsError:
                self._remove_stale_lock()
                if time.monotonic() >= deadline:
                    raise RuntimeError("Forge startup is already in progress for this repository.")
                time.sleep(0.1)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def _remove_stale_lock(self):
        try:
            lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
            created_at = lock.get("created_at")
            age_seconds = (datetime.now(timezone.utc) - datetime.fromisoformat(created_at)).total_seconds() if created_at else LOCK_STALE_SECONDS + 1
            stale = not _process_is_alive(lock.get("pid")) or (not lock.get("pid") and age_seconds > LOCK_STALE_SECONDS)
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            stale = True
        if stale:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _available_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _healthy(port: int, database: Path, instance_id: str | None = None) -> bool:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as response:
                body = json.loads(response.read().decode("utf-8"))
            return (
                body.get("status") == "ok"
                and Path(body.get("database", "")).resolve() == database.resolve()
                and (instance_id is None or body.get("instance_id") == instance_id)
            )
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return False

    def _wait_for_health(self, port: int, database: Path, instance_id: str) -> bool:
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._healthy(port, database, instance_id):
                return True
            time.sleep(0.15)
        return False

    @staticmethod
    def _prune_leases(runtime: dict):
        runtime["leases"] = {
            session_id: lease for session_id, lease in runtime.get("leases", {}).items()
            if not _is_expired(lease.get("expires_at"))
        }

    def start_lease(self, database: str | Path, agent: str) -> dict:
        database_path = Path(database).resolve()
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            if runtime.get("database") != str(database_path):
                runtime = {"version": 3, "mode": "lease_only", "database": str(database_path), "leases": {}}
            reused = bool(runtime.get("leases"))
            session_id = str(uuid4())
            runtime["leases"][session_id] = {"agent": agent, "started_at": _timestamp(), "last_heartbeat_at": _timestamp(), "expires_at": _expires_at()}
            self._write(runtime)
            return {"status": "ready", "reused": reused, "server": "managed" if runtime.get("port") else "not_required", "session_id": session_id, "lease_expires_at": runtime["leases"][session_id]["expires_at"]}

    def _ensure_server(self, runtime: dict, database_path: Path, workspace_id: str) -> tuple[dict, bool]:
        reused = bool(runtime.get("port") and runtime.get("instance_id") and self._healthy(int(runtime["port"]), database_path, runtime["instance_id"]))
        if reused:
            return runtime, True
        if runtime.get("port") and runtime.get("pid") and _process_is_alive(int(runtime["pid"])) and self._healthy(int(runtime["port"]), database_path):
            self._stop_process(int(runtime["pid"]))
        port = self._available_port()
        instance_id = str(uuid4())
        environment = os.environ.copy()
        environment["FORGE_DB_PATH"] = str(database_path)
        environment["FORGE_RUNTIME_INSTANCE_ID"] = instance_id
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.app.cli", "start", "--path", str(self.repository), "--port", str(port), "--workspace", workspace_id],
            cwd=self.repository,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if not self._wait_for_health(port, database_path, instance_id):
            process.terminate()
            raise RuntimeError("Forge dashboard did not become healthy; continue without it.")
        return {"version": 2, "instance_id": instance_id, "pid": process.pid, "port": port, "database": str(database_path), "started_at": _timestamp(), "leases": runtime.get("leases", {})}, False

    def start_dashboard(self, database: str | Path, workspace_id: str) -> dict:
        database_path = Path(database).resolve()
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            if runtime.get("database") != str(database_path):
                runtime = {"version": 3, "mode": "lease_only", "database": str(database_path), "leases": {}}
            runtime, reused = self._ensure_server(runtime, database_path, workspace_id)
            runtime["last_health_at"] = _timestamp()
            self._write(runtime)
            return {"status": "ready", "reused": reused, "pid": runtime["pid"], "port": runtime["port"], "url": f"http://127.0.0.1:{runtime['port']}"}

    def start_or_reuse(self, database: str | Path, workspace_id: str, agent: str) -> dict:
        database_path = Path(database).resolve()
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            runtime, reused = self._ensure_server(runtime, database_path, workspace_id)
            runtime["last_health_at"] = _timestamp()
            session_id = str(uuid4())
            runtime.setdefault("leases", {})[session_id] = {"agent": agent, "started_at": _timestamp(), "last_heartbeat_at": _timestamp(), "expires_at": _expires_at()}
            self._write(runtime)
            return {"status": "ready", "reused": reused, "instance_id": runtime["instance_id"], "port": runtime["port"], "pid": runtime["pid"], "session_id": session_id, "lease_expires_at": runtime["leases"][session_id]["expires_at"]}

    def heartbeat(self, session_id: str) -> dict:
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            lease = runtime.get("leases", {}).get(session_id)
            if not lease:
                raise ValueError("Forge session is no longer active. Start a new session before continuing.")
            lease["last_heartbeat_at"] = _timestamp()
            lease["expires_at"] = _expires_at()
            self._write(runtime)
            return {"session_id": session_id, "agent": lease["agent"], "lease_expires_at": lease["expires_at"]}

    def mark_handoff(self, session_id: str, agent: str, handoff_id: str) -> dict:
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            lease = runtime.get("leases", {}).get(session_id)
            if not lease or lease.get("agent") != agent:
                raise ValueError("No matching active Forge session exists for this handoff.")
            lease["handoff_id"] = handoff_id
            lease["completed_at"] = _timestamp()
            lease["last_heartbeat_at"] = _timestamp()
            lease["expires_at"] = _expires_at()
            self._write(runtime)
            return {"session_id": session_id, "handoff_id": handoff_id, "lease_ready_to_end": True}

    def end_session(self, session_id: str, abandon: bool = False, abandon_reason: str | None = None) -> dict:
        with self._lock():
            runtime = self._read()
            self._prune_leases(runtime)
            lease = runtime.get("leases", {}).get(session_id)
            if not lease:
                raise ValueError("Forge session is no longer active. Start a new session before ending it.")
            if lease and not lease.get("handoff_id") and not abandon:
                raise ValueError("Record a Session Handoff with forge_complete_session before ending this lease, or explicitly abandon it.")
            if abandon and abandon_reason not in {"validation_unavailable", "handoff_incomplete", "developer_cancelled", "agent_error"}:
                raise ValueError("abandon_reason must be validation_unavailable, handoff_incomplete, developer_cancelled, or agent_error.")
            removed = runtime.get("leases", {}).pop(session_id, None) is not None
            if runtime.get("leases"):
                self._write(runtime)
                return {"released": removed, "stopped": False, "active_sessions": sorted(runtime["leases"]), "active_agents": sorted({item["agent"] for item in runtime["leases"].values()}), "agent": lease.get("agent") if lease else None, "handoff_id": lease.get("handoff_id") if lease else None, "abandoned": bool(lease and abandon)}
            port = runtime.get("port")
            pid = runtime.get("pid")
            stopped = False
            if port and pid and _process_is_alive(int(pid)) and self._healthy(int(port), Path(runtime.get("database", "")), runtime.get("instance_id")):
                self._stop_process(int(pid))
                stopped = True
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return {"released": removed, "stopped": stopped, "active_sessions": [], "active_agents": [], "agent": lease.get("agent") if lease else None, "handoff_id": lease.get("handoff_id") if lease else None, "abandoned": bool(lease and abandon)}

    @staticmethod
    def _stop_process(pid: int):
        if os.name == "nt":
            try:
                os.kill(pid, signal.CTRL_BREAK_EVENT)
                return
            except (OSError, ValueError):
                pass
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
