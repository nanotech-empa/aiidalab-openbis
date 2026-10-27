import json
import os
import signal
from pathlib import Path
from typing import Optional, Union

DEFAULT_REGISTRY_PATH = Path("logs/active_synchronisations.json")


def normalize_path(p: str) -> str:
    """Normalize POSIX-like paths by removing redundant slashes and ensuring a consistent leading slash."""
    if not p:
        return "/"
    p = str(p).strip().replace("\\", "/")
    parts = [part for part in p.split("/") if part and part != "."]
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def load_registry(registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH) -> dict:
    path = Path(registry_path)
    if not path.exists():
        return {"jobs": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict) or "jobs" not in data:
                return {"jobs": {}}
            return data
    except (json.JSONDecodeError, OSError):
        return {"jobs": {}}


def save_registry(
    data: dict, registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH
) -> None:
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp.{os.getpid()}")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    temp_path.replace(path)


def find_conflict(
    owner: str,
    afs_path: str,
    local_path: str,
    registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH,
) -> Optional[dict]:
    """Check if the given (owner, afs_path) or local_path is already used by an active running job."""
    registry = load_registry(registry_path)
    norm_afs = normalize_path(afs_path)
    norm_local = normalize_path(local_path)

    for job in registry.get("jobs", {}).values():
        if job.get("status") != "RUNNING":
            continue

        job_owner = job.get("owner")
        job_afs = normalize_path(job.get("afs_path", ""))
        job_local = normalize_path(job.get("local_path", ""))

        if job_owner == owner and job_afs == norm_afs:
            return job
        if job_local == norm_local:
            return job

    return None


def register_job(
    job_info: dict, registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH
) -> None:
    registry = load_registry(registry_path)
    job_id = job_info["job_id"]
    job_copy = dict(job_info)
    job_copy.setdefault("user_stopped", False)
    registry.setdefault("jobs", {})[job_id] = job_copy
    save_registry(registry, registry_path)


def update_job(
    job_id: str,
    updates: dict,
    registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH,
) -> None:
    registry = load_registry(registry_path)
    if job_id in registry.get("jobs", {}):
        registry["jobs"][job_id].update(updates)
        save_registry(registry, registry_path)


def stop_job(
    job_id: str, registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH
) -> Optional[dict]:
    registry = load_registry(registry_path)
    job = registry.get("jobs", {}).get(job_id)
    if not job:
        return None

    pid = job.get("pid")
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (OSError, ValueError):
            pass

    job["status"] = "STOPPED"
    job["user_stopped"] = True
    job["current_action"] = "Stopped by user"
    save_registry(registry, registry_path)
    return job


def cleanup_local_data(local_path: str, preserve_metadata: bool = True) -> int:
    """Delete downloaded files and empty directories in local_path.

    If preserve_metadata is True, preserves logging.json, .gitignore, and .ipynb_checkpoints.
    Returns the count of deleted files.
    """
    target_dir = Path(local_path)
    if not target_dir.exists() or not target_dir.is_dir():
        return 0

    deleted_count = 0
    for root, dirs, files in os.walk(target_dir, topdown=False):
        root_path = Path(root)
        for f in files:
            if preserve_metadata and (
                f in ("logging.json", ".gitignore") or f.endswith(".part")
            ):
                continue
            file_path = root_path / f
            try:
                file_path.unlink()
                deleted_count += 1
            except OSError:
                pass

        for d in dirs:
            dir_path = root_path / d
            if preserve_metadata and d in (".ipynb_checkpoints", ".git"):
                continue
            try:
                dir_path.rmdir()
            except OSError:
                pass

    if not preserve_metadata:
        try:
            target_dir.rmdir()
        except OSError:
            pass

    return deleted_count


def dismiss_job(
    job_id: str, registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH
) -> bool:
    registry = load_registry(registry_path)
    if job_id in registry.get("jobs", {}):
        del registry["jobs"][job_id]
        save_registry(registry, registry_path)
        return True
    return False


def is_pid_alive(pid: Union[int, str, None]) -> bool:
    """Check if a process with the given PID is currently alive."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def sync_liveness(registry_path: Union[str, Path] = DEFAULT_REGISTRY_PATH) -> None:
    path = Path(registry_path)
    if not path.exists():
        return
    registry = load_registry(registry_path)
    changed = False

    for job in registry.get("jobs", {}).values():
        if job.get("status") == "RUNNING":
            pid = job.get("pid")
            if not is_pid_alive(pid):
                job["status"] = "STOPPED"
                changed = True

    if changed:
        save_registry(registry, registry_path)
