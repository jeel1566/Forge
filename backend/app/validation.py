from __future__ import annotations

import subprocess
import shutil
import os
import json
from hashlib import sha256
from pathlib import Path
from time import monotonic

from .store import Store


def configured_validation(store: Store, workspace_id: str, validation_id: str) -> dict:
    repository = store.repository(workspace_id)
    if not repository:
        raise ValueError("Repository is not registered.")
    path = Path(repository["path"]) / "forge.validation.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("forge.validation.json is required for trusted validation.") from error
    except json.JSONDecodeError as error:
        raise ValueError("forge.validation.json is not valid JSON.") from error
    entries = config.get("validations") if isinstance(config, dict) else None
    if not isinstance(entries, list):
        raise ValueError("forge.validation.json must contain a validations array.")
    entry = next((item for item in entries if isinstance(item, dict) and item.get("id") == validation_id), None)
    if not entry or not isinstance(entry.get("argv"), list) or not all(isinstance(part, str) and part for part in entry["argv"]):
        raise ValueError("Configured validation is missing a safe argv array.")
    digest = sha256(path.read_bytes()).hexdigest()
    return {"label": validation_id, "command": entry["argv"], "timeout_seconds": int(entry.get("timeout_seconds", 900)), "config_hash": digest, "scopes": entry.get("scopes", []), "categories": entry.get("categories", [])}


def run_validation(store: Store, workspace_id: str, label: str, command: list[str], timeout_seconds: int = 900, trusted: bool = False, config_hash: str | None = None, scopes: list[str] | None = None, categories: list[str] | None = None) -> dict:
    """Run one explicit local validation command and persist safe result metadata only."""
    repository = store.repository(workspace_id)
    if not repository:
        raise ValueError("Repository is not registered.")
    if not command or not all(isinstance(part, str) and part for part in command):
        raise ValueError("Validation command must contain one or more non-empty arguments.")
    if timeout_seconds < 1 or timeout_seconds > 3_600:
        raise ValueError("Validation timeout must be between 1 and 3600 seconds.")
    executable = command[0]
    repository_executable = Path(repository["path"]) / executable
    if not Path(executable).is_absolute() and repository_executable.is_file():
        command = [str(repository_executable), *command[1:]]
    elif os.name == "nt" and not executable.lower().endswith((".exe", ".bat", ".cmd")):
        resolved = shutil.which(executable)
        if resolved:
            command = [resolved, *command[1:]]
    started = monotonic()
    try:
        completed = subprocess.run(command, cwd=repository["path"], shell=False, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        status, exit_code = ("passed", completed.returncode) if completed.returncode == 0 else ("failed", completed.returncode)
    except subprocess.TimeoutExpired:
        status, exit_code = "timed_out", None
    except OSError:
        status, exit_code = "unavailable", None
    duration_ms = round((monotonic() - started) * 1_000)
    command_digest = sha256("\0".join(command).encode("utf-8")).hexdigest()
    return store.record_validation_result(workspace_id, label, status, exit_code, duration_ms, command[0], command_digest, trusted, config_hash, scopes, categories)


def run_configured_validation(store: Store, workspace_id: str, validation_id: str) -> dict:
    configured = configured_validation(store, workspace_id, validation_id)
    return run_validation(store, workspace_id, configured["label"], configured["command"], configured["timeout_seconds"], True, configured["config_hash"], configured["scopes"], configured["categories"])
