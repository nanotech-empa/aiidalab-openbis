"""Observability, registry, and atomic log helpers for measurement watchdogs."""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import subprocess
import threading
import uuid
from collections import deque

from . import sync_registry, utils

IGNORED_SUFFIXES = (".json", ".ini", ".part", ".openbis-drive-part", ".tmp")
_LOG_LOCKS_GUARD = threading.Lock()
_LOG_LOCKS: dict[str, threading.Lock] = {}


def _get_log_lock(filepath: str | pathlib.Path) -> threading.Lock:
    key = os.path.abspath(str(filepath))
    with _LOG_LOCKS_GUARD:
        lock = _LOG_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOG_LOCKS[key] = lock
        return lock


def is_session_token_expired(openbis_session) -> bool:
    if openbis_session is None:
        return True
    check_active = getattr(openbis_session, "is_session_active", None)
    if callable(check_active):
        try:
            active = check_active()
            if active is False:
                return True
        except Exception:
            return False
    return False


def redact_secrets(
    text: str, secrets: list[str | None] | tuple[str | None, ...] | None
) -> str:
    if not text or not secrets:
        return text
    redacted = str(text)
    for secret in secrets:
        if isinstance(secret, str) and secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def utc_now_iso(now: datetime.datetime | None = None) -> str:
    return (now or utc_now()).isoformat()


def default_is_ignored_file(file_path: str) -> bool:
    filename = os.path.basename(file_path)
    return filename.startswith(".") or filename.endswith(IGNORED_SUFFIXES)


def atomic_write_json(data, filepath: str | pathlib.Path) -> None:
    path = pathlib.Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}"
    )
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_json_safe(filepath: str | pathlib.Path, default=None):
    path = pathlib.Path(filepath)
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def update_measurement_log(logging_filepath: str | pathlib.Path, updater) -> dict:
    lock = _get_log_lock(logging_filepath)
    with lock:
        current = read_json_safe(logging_filepath, default={})
        if not isinstance(current, dict):
            current = {}
        result = updater(current)
        updated = result if isinstance(result, dict) else current
        atomic_write_json(updated, logging_filepath)
        return updated


def _touch_heartbeat(logging_data: dict, ts: str) -> None:
    existing = _parse_iso_datetime(logging_data.get("last_heartbeat_at"))
    incoming = _parse_iso_datetime(ts)
    if existing is None or incoming is None or incoming >= existing:
        logging_data["last_heartbeat_at"] = ts


def append_upload_event(
    logging_data: dict,
    file_path: str,
    upload_type: str,
    uploaded_at: str | None = None,
    max_events: int = 200,
) -> dict:
    ts = uploaded_at or utc_now_iso()
    filename = os.path.basename(file_path)
    history = logging_data.get("upload_history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "file": file_path,
            "filename": filename,
            "type": upload_type,
            "uploaded_at": ts,
        }
    )
    if len(history) > max_events:
        history = history[-max_events:]
    logging_data["upload_history"] = history
    logging_data["last_upload_at"] = ts
    logging_data["last_uploaded_file"] = filename
    _touch_heartbeat(logging_data, ts)
    return logging_data


def append_error_event(
    logging_data: dict,
    message: str,
    stage: str = "watcher",
    file_path: str | None = None,
    timestamp: str | None = None,
    max_errors: int = 50,
) -> dict:
    ts = timestamp or utc_now_iso()
    errors = logging_data.get("recent_errors")
    if not isinstance(errors, list):
        errors = []
    event = {
        "timestamp": ts,
        "file": os.path.basename(file_path) if file_path else None,
        "stage": stage,
        "message": str(message),
    }
    errors.append(event)
    if len(errors) > max_errors:
        errors = errors[-max_errors:]
    logging_data["recent_errors"] = errors
    logging_data["last_error"] = event
    _touch_heartbeat(logging_data, ts)
    return logging_data


def get_measurement_process_log_path(
    measurement_session_id: str, logs_dir: str | pathlib.Path
) -> pathlib.Path:
    logs_path = pathlib.Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)
    return logs_path / f"{measurement_session_id}.log"


def start_watchdog_subprocess(
    app_folder: str | pathlib.Path,
    openbis_url: str,
    openbis_token: str,
    measurement_session_id: str,
    data_folder: str,
    logs_dir: str | pathlib.Path,
) -> tuple[subprocess.Popen, pathlib.Path]:
    norm_data_folder = os.path.normpath(data_folder)
    log_path = get_measurement_process_log_path(measurement_session_id, logs_dir)
    log_fh = open(log_path, "a", encoding="utf-8")
    try:
        log_fh.write(
            f"\n--- Watchdog started at {utc_now_iso()} for {norm_data_folder} "
            f"(session {measurement_session_id}) ---\n"
        )
        log_fh.flush()
        proc = subprocess.Popen(
            [
                "python",
                "-u",
                f"{app_folder}/src/measurements_uploader.py",
                "--openbis_url",
                openbis_url,
                "--openbis_token",
                openbis_token,
                "--measurement_session_id",
                measurement_session_id,
                "--data_folder",
                norm_data_folder,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_fh.close()
    return proc, log_path


def is_pid_running(pid: int | str | None) -> bool:
    if pid is None:
        return False
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False

    if hasattr(os, "waitpid") and hasattr(os, "WNOHANG"):
        try:
            waited_pid, _ = os.waitpid(pid_int, os.WNOHANG)
            if waited_pid == pid_int:
                return False
        except ChildProcessError:
            pass
        except OSError:
            pass

    try:
        os.kill(pid_int, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def load_watchdog_entries(registry_file: str | pathlib.Path) -> list[dict]:
    raw = read_json_safe(registry_file, default=[])
    if isinstance(raw, dict):
        return [raw]
    if not isinstance(raw, list):
        return []
    return [dict(entry) for entry in raw if isinstance(entry, dict)]


def save_watchdog_entries(
    entries: list[dict], registry_file: str | pathlib.Path
) -> None:
    atomic_write_json(entries, registry_file)


def sync_watchdog_liveness(registry_file: str | pathlib.Path) -> list[dict]:
    entries = load_watchdog_entries(registry_file)
    if not entries:
        return []

    changed = False
    now_iso = utc_now_iso()
    for entry in entries:
        status = entry.get("status")
        pid = entry.get("pid")
        if status in (None, "RUNNING"):
            if is_pid_running(pid):
                if status is None:
                    entry["status"] = "RUNNING"
                    entry.setdefault("user_stopped", False)
                    changed = True
            else:
                entry["status"] = "EXITED"
                entry["user_stopped"] = False
                if not entry.get("stopped_at"):
                    entry["stopped_at"] = now_iso
                changed = True

    if changed:
        save_watchdog_entries(entries, registry_file)
    return entries


def upsert_running_watchdog(
    registry_file: str | pathlib.Path,
    pid: int,
    data_folder: str,
    measurement_session_id: str | None,
    metadata: dict | None = None,
    log_file: str | pathlib.Path | None = None,
) -> dict:
    norm_data_folder = os.path.normpath(data_folder)
    entries = load_watchdog_entries(registry_file)
    now_iso = utc_now_iso()

    target_entry = None
    if measurement_session_id:
        for entry in entries:
            if entry.get("measurement_session_id") == measurement_session_id:
                target_entry = entry
                break

    if target_entry is None:
        target_entry = {}
        entries.append(target_entry)

    target_entry["pid"] = pid
    target_entry["monitored_folder"] = norm_data_folder
    target_entry["measurement_session_id"] = measurement_session_id
    target_entry["status"] = "RUNNING"
    target_entry["user_stopped"] = False
    target_entry["started_at"] = now_iso
    target_entry["stopped_at"] = None
    if log_file is not None:
        target_entry["log_file"] = str(log_file)
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value is not None and value != "":
                target_entry[key] = value

    save_watchdog_entries(entries, registry_file)
    return dict(target_entry)


def mark_watchdogs_stopped(
    registry_file: str | pathlib.Path,
    pids: list[int],
    remove_entries: bool = False,
) -> list[dict]:
    pid_set = set(pids)
    entries = load_watchdog_entries(registry_file)
    now_iso = utc_now_iso()

    if remove_entries:
        updated = [entry for entry in entries if entry.get("pid") not in pid_set]
    else:
        updated = []
        for entry in entries:
            if entry.get("pid") in pid_set:
                entry["status"] = "STOPPED"
                entry["user_stopped"] = True
                entry["stopped_at"] = now_iso
            updated.append(entry)

    save_watchdog_entries(updated, registry_file)
    return updated


def remove_watchdog_entries(
    registry_file: str | pathlib.Path,
    data_folder: str | None = None,
    session_ids: list[str] | set[str] | None = None,
) -> list[dict]:
    entries = load_watchdog_entries(registry_file)
    norm_folder = os.path.normpath(data_folder) if data_folder else None
    target_sessions = {sid for sid in (session_ids or []) if sid}

    remaining = []
    changed = False
    for entry in entries:
        matches_session = (
            bool(target_sessions)
            and entry.get("measurement_session_id") in target_sessions
        )
        matches_folder = (
            norm_folder is not None
            and isinstance(entry.get("monitored_folder"), str)
            and bool(entry.get("monitored_folder"))
            and os.path.normpath(entry["monitored_folder"]) == norm_folder
        )
        if matches_session or matches_folder:
            changed = True
            continue
        remaining.append(entry)

    if changed:
        save_watchdog_entries(remaining, registry_file)
    return remaining


def dismiss_watchdog_entry(
    registry_file: str | pathlib.Path,
    measurement_session_id: str | None = None,
    pid: int | None = None,
    data_folder: str | None = None,
) -> bool:
    entries = load_watchdog_entries(registry_file)
    norm_folder = os.path.normpath(data_folder) if data_folder else None
    remaining = []
    dismissed = False

    for entry in entries:
        matches = False
        if measurement_session_id is not None:
            matches = entry.get("measurement_session_id") == measurement_session_id
        elif pid is not None:
            matches = entry.get("pid") == pid
        elif norm_folder is not None:
            matches = bool(
                entry.get("monitored_folder")
                and os.path.normpath(entry["monitored_folder"]) == norm_folder
            )

        if matches and not dismissed:
            if entry.get("status") in (None, "RUNNING") or is_pid_running(
                entry.get("pid")
            ):
                return False
            dismissed = True
            continue
        remaining.append(entry)

    if dismissed:
        save_watchdog_entries(remaining, registry_file)
    return dismissed


def build_openbis_session_url(
    eln_url: str | None, measurement_session_id: str | None
) -> str | None:
    if not eln_url or not measurement_session_id:
        return None
    base_url = utils.normalize_openbis_eln_url(str(eln_url)).strip()
    if not base_url.lower().startswith(("http://", "https://")):
        return None
    return (
        f"{base_url}?viewName=showViewSamplePageFromPermId"
        f"&viewData=%7B%22permIdOrIdentifier%22:%22{measurement_session_id}%22%7D"
    )


def scan_folder_files(
    data_folder: str,
    processed_files: list[str] | None,
    is_ignored_fn=default_is_ignored_file,
) -> dict:
    processed_list = [p for p in (processed_files or []) if isinstance(p, str)]
    processed_norm = {os.path.normpath(p) for p in processed_list}
    if not data_folder or not os.path.isdir(data_folder):
        return {
            "folder_exists": False,
            "total_disk_files": 0,
            "uploaded_count": len(processed_norm),
            "pending_files": [],
            "disk_files": [],
        }

    disk_files = []
    pending_files = []
    try:
        entries = sorted(os.listdir(data_folder))
    except OSError:
        return {
            "folder_exists": False,
            "total_disk_files": 0,
            "uploaded_count": len(processed_norm),
            "pending_files": [],
            "disk_files": [],
        }

    for name in entries:
        full_path = os.path.normpath(os.path.join(data_folder, name))
        if not os.path.isfile(full_path) or is_ignored_fn(full_path):
            continue
        disk_files.append(name)
        if full_path not in processed_norm:
            pending_files.append(name)

    return {
        "folder_exists": True,
        "total_disk_files": len(disk_files),
        "uploaded_count": len(processed_norm),
        "pending_files": pending_files,
        "disk_files": disk_files,
    }


def compute_type_counts(
    processed_files: list[str] | None, upload_history: list[dict] | None
) -> dict[str, int]:
    counts = {"SXM": 0, "DAT": 0, "ATTACHMENT": 0}
    processed_list = [p for p in (processed_files or []) if isinstance(p, str)]
    type_by_path = {}
    if isinstance(upload_history, list):
        for event in upload_history:
            if not isinstance(event, dict):
                continue
            ev_type = event.get("type")
            ev_file = event.get("file")
            if ev_type in counts and isinstance(ev_file, str):
                type_by_path[os.path.normpath(ev_file)] = ev_type

    seen = set()
    for path_str in processed_list:
        norm = os.path.normpath(path_str)
        if norm in seen:
            continue
        seen.add(norm)
        ev_type = type_by_path.get(norm)
        if ev_type in counts:
            counts[ev_type] += 1
        else:
            lower = norm.lower()
            if lower.endswith(".sxm"):
                counts["SXM"] += 1
            elif lower.endswith(".dat"):
                counts["DAT"] += 1
            else:
                counts["ATTACHMENT"] += 1
    return counts


def tail_log_file(
    log_path: str | pathlib.Path | None, max_lines: int = 30
) -> list[str]:
    if not log_path:
        return []
    path = pathlib.Path(log_path)
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return [line.rstrip("\r\n") for line in deque(fh, maxlen=max_lines)]
    except OSError:
        return []


def get_afs_sync_status(
    data_folder: str | None, sync_registry_path: str | pathlib.Path | None
) -> str | None:
    if not data_folder or not sync_registry_path:
        return None
    path = pathlib.Path(sync_registry_path)
    if not path.is_file():
        return None

    registry = sync_registry.load_registry(path)
    jobs = registry.get("jobs", {})
    if not isinstance(jobs, dict):
        return None

    target = sync_registry.normalize_path(os.path.normpath(data_folder))
    matched_any = False
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        local_path = job.get("local_path")
        if not local_path:
            continue
        if sync_registry.normalize_path(os.path.normpath(local_path)) != target:
            continue
        matched_any = True
        if job.get("status") == "RUNNING" and sync_registry.is_pid_alive(
            job.get("pid")
        ):
            return "RUNNING"

    return "STOPPED" if matched_any else None


def _parse_iso_datetime(iso_ts: str | None) -> datetime.datetime | None:
    if not iso_ts or not isinstance(iso_ts, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    except ValueError:
        return None


def format_relative_time(
    iso_ts: str | None, now: datetime.datetime | None = None
) -> str:
    parsed = _parse_iso_datetime(iso_ts)
    if parsed is None:
        return "N/A"
    ref = now or utc_now()
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=datetime.timezone.utc)
    delta_seconds = max(0, int((ref - parsed).total_seconds()))
    if delta_seconds < 60:
        return f"{delta_seconds}s ago"
    if delta_seconds < 3600:
        return f"{delta_seconds // 60}m ago"
    if delta_seconds < 86400:
        return f"{delta_seconds // 3600}h ago"
    return f"{delta_seconds // 86400}d ago"


def build_watchdog_card_snapshot(
    entry: dict,
    measurement_logs_dir: str | pathlib.Path,
    sync_registry_path: str | pathlib.Path | None = None,
    default_eln_url: str | None = None,
    is_ignored_fn=default_is_ignored_file,
    log_tail_lines: int = 30,
    stale_heartbeat_seconds: float = 120.0,
    now: datetime.datetime | None = None,
    secret_tokens: list[str | None] | None = None,
) -> dict:
    ref_now = now or utc_now()
    session_id = entry.get("measurement_session_id")
    folder = entry.get("monitored_folder") or ""
    norm_folder = os.path.normpath(folder) if folder else ""
    logs_dir = pathlib.Path(measurement_logs_dir)

    session_log_path = logs_dir / f"{session_id}.json" if session_id else None
    session_log = (
        read_json_safe(session_log_path, default={})
        if session_log_path is not None
        else {}
    )
    if not isinstance(session_log, dict):
        session_log = {}

    secrets_to_redact: list[str] = []
    if isinstance(session_log.get("eln_token"), str) and session_log["eln_token"]:
        secrets_to_redact.append(session_log["eln_token"])
    if secret_tokens:
        for tok in secret_tokens:
            if isinstance(tok, str) and tok and tok not in secrets_to_redact:
                secrets_to_redact.append(tok)

    raw_status = entry.get("status") or "RUNNING"
    token_expired = bool(session_log.get("token_expired"))
    if raw_status == "EXITED" and token_expired:
        display_status = "TOKEN_EXPIRED"
    else:
        display_status = raw_status

    processed_files = session_log.get("processed_files")
    if not isinstance(processed_files, list):
        processed_files = []

    upload_history = session_log.get("upload_history")
    if not isinstance(upload_history, list):
        upload_history = []

    recent_errors_raw = session_log.get("recent_errors")
    if not isinstance(recent_errors_raw, list):
        recent_errors_raw = []

    def _redact_error(err: dict) -> dict:
        copied = dict(err)
        if copied.get("message") is not None:
            copied["message"] = redact_secrets(str(copied["message"]), secrets_to_redact)
        return copied

    recent_errors = [
        _redact_error(e) if isinstance(e, dict) else e for e in recent_errors_raw
    ]

    last_error_raw = session_log.get("last_error")
    last_error = (
        _redact_error(last_error_raw) if isinstance(last_error_raw, dict) else None
    )

    scan = scan_folder_files(norm_folder, processed_files, is_ignored_fn=is_ignored_fn)
    type_counts = compute_type_counts(processed_files, upload_history)

    last_heartbeat_at = session_log.get("last_heartbeat_at")
    last_upload_at = session_log.get("last_upload_at")
    parsed_hb = _parse_iso_datetime(last_heartbeat_at)
    parsed_up = _parse_iso_datetime(last_upload_at)
    effective_activity_at = last_heartbeat_at
    effective_dt = parsed_hb
    if parsed_up is not None and (effective_dt is None or parsed_up > effective_dt):
        effective_activity_at = last_upload_at
        effective_dt = parsed_up

    heartbeat_stale = False
    if display_status == "RUNNING" and effective_dt is not None:
        heartbeat_stale = (
            ref_now - effective_dt
        ).total_seconds() > stale_heartbeat_seconds

    log_file_path = entry.get("log_file")
    if not log_file_path and session_id:
        candidate_log = logs_dir / f"{session_id}.log"
        if candidate_log.exists():
            log_file_path = str(candidate_log)

    eln_url = session_log.get("eln_url") or default_eln_url
    session_name = (
        session_log.get("session_name")
        or entry.get("session_name")
        or session_id
        or "Unknown Session"
    )

    recent_uploads = list(reversed(upload_history[-20:]))
    if not recent_uploads and processed_files:
        recent_uploads = [
            {
                "file": p,
                "filename": os.path.basename(p),
                "type": (
                    "SXM"
                    if p.lower().endswith(".sxm")
                    else "DAT"
                    if p.lower().endswith(".dat")
                    else "ATTACHMENT"
                ),
                "uploaded_at": None,
            }
            for p in reversed(processed_files[-20:])
            if isinstance(p, str)
        ]

    raw_tail = tail_log_file(log_file_path, max_lines=log_tail_lines)
    redacted_tail = [redact_secrets(line, secrets_to_redact) for line in raw_tail]
    current_action = redact_secrets(
        str(session_log.get("current_action") or ""), secrets_to_redact
    )

    return {
        "status": display_status,
        "raw_status": raw_status,
        "user_stopped": bool(entry.get("user_stopped", False)),
        "token_expired": token_expired,
        "pid": entry.get("pid"),
        "monitored_folder": norm_folder,
        "folder_exists": scan["folder_exists"],
        "session_id": session_id,
        "session_name": session_name,
        "session_url": build_openbis_session_url(eln_url, session_id),
        "sample_name": session_log.get("sample_name") or entry.get("sample_name"),
        "experiment_name": session_log.get("experiment_name")
        or entry.get("experiment_name"),
        "instrument_name": session_log.get("instrument_name")
        or entry.get("instrument_name"),
        "started_at": entry.get("started_at") or session_log.get("started_at"),
        "stopped_at": entry.get("stopped_at"),
        "last_heartbeat_at": effective_activity_at,
        "heartbeat_relative": format_relative_time(effective_activity_at, now=ref_now),
        "heartbeat_stale": heartbeat_stale,
        "current_action": current_action,
        "last_upload_at": session_log.get("last_upload_at"),
        "last_upload_relative": format_relative_time(
            session_log.get("last_upload_at"), now=ref_now
        ),
        "last_uploaded_file": session_log.get("last_uploaded_file"),
        "uploaded_count": scan["uploaded_count"],
        "total_disk_files": scan["total_disk_files"],
        "pending_files": scan["pending_files"],
        "type_counts": type_counts,
        "recent_uploads": recent_uploads,
        "recent_errors": list(reversed(recent_errors[-20:])),
        "error_count": len(recent_errors),
        "last_error": last_error,
        "log_file_path": log_file_path,
        "log_tail": redacted_tail,
        "afs_sync_status": get_afs_sync_status(norm_folder, sync_registry_path),
    }
