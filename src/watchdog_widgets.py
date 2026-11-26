import datetime
import html
import json
import logging
import os
import pathlib
import signal
import subprocess

import ipyfilechooser
import ipywidgets as ipw
from IPython.display import Javascript, display

from . import measurement_monitor, utils, widgets

INTERFACE_CONFIG_INFO = utils.get_interface_config_info()
OPENBIS_OBJECT_TYPES, _ = (
    INTERFACE_CONFIG_INFO["object_types"],
    INTERFACE_CONFIG_INFO["object_types_codes"],
)

logger = logging.getLogger(__name__)
APP_FOLDER = utils.APP_ROOT
LOGS_FOLDER = utils.LOG_DIR
MEASUREMENT_LOGS_FOLDER = LOGS_FOLDER / "measurements"
LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
MEASUREMENT_LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=utils.LOG_FILE_PATH,
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def get_measurement_log_filepath(
    measurement_session_id, logs_dir=MEASUREMENT_LOGS_FOLDER
):
    logs_path = pathlib.Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)
    return logs_path / f"{measurement_session_id}.json"


def find_measurement_logs_for_folder(data_folder, logs_dir=MEASUREMENT_LOGS_FOLDER):
    logs_path = pathlib.Path(logs_dir)
    if not logs_path.exists():
        return []
    norm_target = os.path.normpath(data_folder)
    matches = []
    json_files = sorted(
        logs_path.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for log_file in json_files:
        try:
            data = utils.read_json(str(log_file))
            if isinstance(data, dict) and data.get("data_folder"):
                if os.path.normpath(data["data_folder"]) == norm_target:
                    matches.append((log_file, data))
        except (FileNotFoundError, ValueError, OSError):
            continue
    return matches


def detach_measurement_logs_for_folder(
    data_folder, replaced_by_session_id=None, logs_dir=MEASUREMENT_LOGS_FOLDER
):
    detached_paths = []
    detached_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for log_file, data in find_measurement_logs_for_folder(
        data_folder, logs_dir=logs_dir
    ):
        updated = dict(data)
        updated["previous_data_folder"] = updated.get("data_folder")
        updated["data_folder"] = None
        updated["detached_at"] = detached_at
        if replaced_by_session_id is not None:
            updated["replaced_by_session_id"] = replaced_by_session_id
        utils.write_json(updated, str(log_file))
        detached_paths.append(log_file)
    return detached_paths


class RunningMeasurementWatchdogsWidget(ipw.VBox):
    def __init__(self, openbis_session, session_data):
        super().__init__()
        self.openbis_session = openbis_session
        self.session_data = session_data
        self.logs_folder = None
        self.measurement_logs_folder = None
        self.sync_registry_path = None
        self.watchdog_processes = []
        self._resuming_sessions = set()

        self.notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Monitoring the Measurement Uploader
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <div style="font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 8px;">
                        Directories being monitored (Management & Observability):
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5;">
                        <li style="margin-bottom: 6px;"><b>Status cards:</b> Show running, stopped, and unexpectedly exited watchdogs along with openBIS links, upload progress, last activity, errors, and recent logs.</li>
                        <li style="margin-bottom: 6px;"><b>Refresh Status:</b> Click to re-check process liveness, disk file counts, and recent logs (also refreshes automatically when opening this tab).</li>
                        <li><b>Stop / Resume / Dismiss:</b> Stop a running watchdog, resume a stopped or token-expired watchdog with your current openBIS session, or dismiss old cards without touching openBIS records.</li>
                    </ul>
                </div>
            </details>
            """
        )

        # Retained internally for backwards compatibility with callers/tests reading .options
        self.running_watchdogs_widget = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px")
        )

        self.refresh_button = ipw.Button(
            description="Refresh Status",
            icon="refresh",
            button_style="",
            layout=ipw.Layout(width="150px"),
        )
        self.refresh_button.on_click(lambda _b: self.refresh_watchdog_list())

        self.watchdogs_box = ipw.VBox()

        self.children = [
            self.notes,
            ipw.HBox(
                [
                    ipw.HTML(
                        "<div style='font-weight: bold; font-size: 16px; color: #34495e;'>Tracked Measurement Watchdogs</div>"
                    ),
                    self.refresh_button,
                ],
                layout=ipw.Layout(
                    justify_content="space-between",
                    align_items="center",
                    margin="0 0 12px 0",
                ),
            ),
            self.watchdogs_box,
        ]

        self.refresh_watchdog_list()

    def _active_watchdogs_file(self):
        logs_root = getattr(self, "logs_folder", None) or LOGS_FOLDER
        return pathlib.Path(logs_root) / "active_watchdogs.json"

    def _measurement_logs_dir(self):
        explicit = getattr(self, "measurement_logs_folder", None)
        if explicit is not None:
            return pathlib.Path(explicit)
        logs_root = getattr(self, "logs_folder", None)
        if logs_root is not None:
            return pathlib.Path(logs_root) / "measurements"
        return pathlib.Path(MEASUREMENT_LOGS_FOLDER)

    def _sync_registry_file(self):
        explicit = getattr(self, "sync_registry_path", None)
        if explicit is not None:
            return pathlib.Path(explicit)
        logs_root = getattr(self, "logs_folder", None) or LOGS_FOLDER
        return pathlib.Path(logs_root) / "active_synchronisations.json"

    def _reap_watchdog_processes(self):
        alive = []
        for process in getattr(self, "watchdog_processes", []):
            poll = getattr(process, "poll", None)
            if callable(poll):
                try:
                    if poll() is not None:
                        continue
                except OSError:
                    continue
            alive.append(process)
        self.watchdog_processes = alive

    def _sync_select_options(self, entries):
        folder_options = [
            (entry.get("monitored_folder", "Unknown Folder"), entry.get("pid"))
            for entry in entries
            if entry.get("status") == "RUNNING" and entry.get("pid") is not None
        ]
        self.running_watchdogs_widget.options = folder_options

    def refresh_watchdog_list(self, refresh_ui=True):
        self._reap_watchdog_processes()
        entries = measurement_monitor.sync_watchdog_liveness(
            self._active_watchdogs_file()
        )
        self._sync_select_options(entries)
        if refresh_ui and hasattr(self, "watchdogs_box"):
            self.render_watchdogs(entries=entries)

    def get_active_watchdogs_for_folder(self, data_folder, refresh_ui=True):
        self.refresh_watchdog_list(refresh_ui=refresh_ui)
        norm_target = os.path.normpath(data_folder)
        entries = measurement_monitor.load_watchdog_entries(
            self._active_watchdogs_file()
        )
        return [
            entry
            for entry in entries
            if entry.get("status") == "RUNNING"
            and entry.get("monitored_folder")
            and entry.get("pid") is not None
            and os.path.normpath(entry["monitored_folder"]) == norm_target
        ]

    def stop_watchdog_pids(self, pids, notify=True, remove_entries=True):
        target_pids = [
            pid
            for pid in dict.fromkeys(pids)
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
        ]
        if not target_pids:
            return []

        pid_set = set(target_pids)
        for pid in target_pids:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Terminating watchdog process with PID: {pid}")
            except (ProcessLookupError, PermissionError):
                logger.warning(
                    f"Process {pid} not found or inaccessible. It may have already exited."
                )

        remaining_processes = []
        for process in getattr(self, "watchdog_processes", []):
            if getattr(process, "pid", None) in pid_set:
                wait = getattr(process, "wait", None)
                if callable(wait):
                    try:
                        wait(timeout=1)
                    except (subprocess.TimeoutExpired, OSError):
                        pass
            else:
                remaining_processes.append(process)
        self.watchdog_processes = remaining_processes

        if notify:
            display(Javascript(data="alert('Watchdog(s) stopped.')"))

        entries = measurement_monitor.mark_watchdogs_stopped(
            self._active_watchdogs_file(),
            target_pids,
            remove_entries=remove_entries,
        )
        self._sync_select_options(entries)
        if hasattr(self, "watchdogs_box"):
            self.render_watchdogs(entries=entries)

        return target_pids

    def remove_watchdog_entries_for_folder(self, data_folder, session_ids=None):
        entries = measurement_monitor.remove_watchdog_entries(
            self._active_watchdogs_file(),
            data_folder=data_folder,
            session_ids=session_ids,
        )
        self._sync_select_options(entries)
        if hasattr(self, "watchdogs_box"):
            self.render_watchdogs(entries=entries)
        return entries

    def add_active_watchdog(
        self,
        pid,
        data_folder,
        measurement_session_id,
        metadata=None,
        log_file=None,
    ):
        measurement_monitor.upsert_running_watchdog(
            self._active_watchdogs_file(),
            pid=pid,
            data_folder=data_folder,
            measurement_session_id=measurement_session_id,
            metadata=metadata,
            log_file=log_file,
        )
        entries = measurement_monitor.load_watchdog_entries(
            self._active_watchdogs_file()
        )
        self._sync_select_options(entries)
        if hasattr(self, "watchdogs_box"):
            self.render_watchdogs(entries=entries)

    def stop_watchdog(self, b):
        selected_pids = self.running_watchdogs_widget.value

        if selected_pids:
            self.stop_watchdog_pids(selected_pids, notify=True, remove_entries=False)
        else:
            display(Javascript(data="alert('Select at least one directory.')"))
            logger.info("No directory selected.")

    def render_watchdogs(self, entries=None):
        if entries is None:
            entries = measurement_monitor.load_watchdog_entries(
                self._active_watchdogs_file()
            )
        if not entries:
            self.watchdogs_box.children = [
                ipw.HTML(
                    "<div style='color: #6b7280; padding: 16px; font-style: italic;'>"
                    "No measurement watchdogs tracked yet."
                    "</div>"
                )
            ]
            return

        default_url = (
            self.session_data.get("url") if isinstance(self.session_data, dict) else None
        )
        active_token = (
            self.session_data.get("token")
            if isinstance(self.session_data, dict)
            else None
        )
        snapshots = [
            measurement_monitor.build_watchdog_card_snapshot(
                entry,
                measurement_logs_dir=self._measurement_logs_dir(),
                sync_registry_path=self._sync_registry_file(),
                default_eln_url=default_url,
                secret_tokens=[active_token] if active_token else None,
            )
            for entry in entries
        ]

        priority = {"RUNNING": 0, "TOKEN_EXPIRED": 1, "EXITED": 2, "STOPPED": 3}
        snapshots.sort(
            key=lambda s: (
                priority.get(s["status"], 9),
                "" if not s.get("started_at") else s["started_at"],
            )
        )
        # Keep newest started_at first within each status bucket
        snapshots.sort(key=lambda s: s.get("started_at") or "", reverse=True)
        snapshots.sort(key=lambda s: priority.get(s["status"], 9))

        self.watchdogs_box.children = [
            self._create_watchdog_card(snap) for snap in snapshots
        ]

    def _create_watchdog_card(self, snap: dict) -> ipw.Widget:
        status = snap["status"]
        pid = snap.get("pid")
        safe_pid = html.escape(str(pid if pid is not None else "N/A"))
        if status == "RUNNING":
            badge = (
                f"<span style='background: #dcfce7; color: #166534; font-size: 11px; "
                f"font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                f"● RUNNING (PID {safe_pid})</span>"
            )
        elif status == "TOKEN_EXPIRED":
            badge = (
                "<span style='background: #fee2e2; color: #991b1b; font-size: 11px; "
                "font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                "⚠ TOKEN EXPIRED</span>"
            )
        elif status == "EXITED":
            badge = (
                "<span style='background: #fef3c7; color: #92400e; font-size: 11px; "
                "font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                "⚠ EXITED UNEXPECTEDLY</span>"
            )
        else:
            badge = (
                "<span style='background: #f3f4f6; color: #4b5563; font-size: 11px; "
                "font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                "○ STOPPED</span>"
            )

        afs_badge = ""
        if snap.get("afs_sync_status") == "RUNNING":
            afs_badge = (
                "<span style='background: #dbeafe; color: #1e40af; font-size: 11px; "
                "font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                "AFS Sync: ● RUNNING</span>"
            )
        elif snap.get("afs_sync_status") == "STOPPED":
            afs_badge = (
                "<span style='background: #f3f4f6; color: #6b7280; font-size: 11px; "
                "font-weight: bold; padding: 2px 8px; border-radius: 12px;'>"
                "AFS Sync: ○ STOPPED</span>"
            )

        safe_name = html.escape(str(snap.get("session_name") or "Unknown Session"))
        safe_sid = html.escape(str(snap.get("session_id") or "N/A"))
        session_url = snap.get("session_url")
        if (
            isinstance(session_url, str)
            and session_url.lower().startswith(("http://", "https://"))
        ):
            safe_url = html.escape(session_url, quote=True)
            session_title = (
                f"<a href='{safe_url}' target='_blank' rel='noopener noreferrer' "
                f"style='font-weight: bold; color: #1d4ed8; text-decoration: none; margin-left: 8px;'>"
                f"{safe_name} ({safe_sid} ↗)</a>"
            )
        else:
            session_title = (
                f"<strong style='margin-left: 8px;'>{safe_name} ({safe_sid})</strong>"
            )

        header_html = ipw.HTML(
            f"<div style='display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;'>"
            f"<div>{badge}{session_title}</div>"
            f"<div>{afs_badge}</div>"
            f"</div>"
        )

        meta_parts = []
        if snap.get("sample_name"):
            meta_parts.append(
                f"<b>Sample:</b> {html.escape(str(snap['sample_name']))}"
            )
        if snap.get("experiment_name"):
            meta_parts.append(
                f"<b>Experiment:</b> {html.escape(str(snap['experiment_name']))}"
            )
        if snap.get("instrument_name"):
            meta_parts.append(
                f"<b>Instrument:</b> {html.escape(str(snap['instrument_name']))}"
            )
        meta_line = (
            f"<div>{' · '.join(meta_parts)}</div>" if meta_parts else ""
        )

        safe_folder = html.escape(snap.get("monitored_folder") or "")
        safe_action = html.escape(snap.get("current_action") or "Idle")
        last_file = snap.get("last_uploaded_file")
        last_upload_info = html.escape(snap.get("last_upload_relative") or "N/A")
        if last_file:
            last_upload_info += f" (<code>{html.escape(str(last_file))}</code>)"

        tc = snap["type_counts"]
        pending_count = len(snap["pending_files"])
        progress_text = (
            f"{snap['uploaded_count']} / {snap['total_disk_files']} uploaded "
            f"({tc['SXM']} SXM · {tc['DAT']} DAT · {tc['ATTACHMENT']} ATT)"
            f" · {pending_count} pending"
        )

        warnings_html = ""
        if not snap["folder_exists"]:
            warnings_html += (
                "<div style='color: #b91c1c; font-weight: bold; margin-top: 4px;'>"
                "⚠ Folder not found or inaccessible on disk.</div>"
            )
        if snap["heartbeat_stale"]:
            warnings_html += (
                f"<div style='color: #b45309; font-weight: bold; margin-top: 4px;'>"
                f"⚠ Last active {html.escape(snap['heartbeat_relative'])} — worker may be busy on a large upload or hung.</div>"
            )

        error_banner = ""
        if snap.get("token_expired") or snap.get("last_error"):
            err = snap.get("last_error") or {}
            err_stage = html.escape(str(err.get("stage") or "error"))
            err_file = f" ({html.escape(str(err['file']))})" if err.get("file") else ""
            err_msg = html.escape(
                str(
                    err.get("message")
                    or "openBIS session token expired or invalid."
                )
            )
            token_hint = (
                " Click <b>Resume</b> to reconnect with your current openBIS token."
                if snap.get("token_expired")
                else ""
            )
            error_banner = (
                "<div style='background: #fef2f2; border-left: 4px solid #dc2626; "
                "padding: 6px 10px; margin-top: 6px; color: #991b1b; font-size: 12px; border-radius: 3px;'>"
                f"<b>⚠ Upload issue [{err_stage}]{err_file}:</b> {err_msg}{token_hint}"
                "</div>"
            )

        details_html = ipw.HTML(
            f"<div style='font-size: 12px; color: #374151; margin: 8px 0; line-height: 1.5;'>"
            f"<div><b>Folder:</b> <code>{safe_folder}</code></div>"
            f"{meta_line}"
            f"<div><b>Status:</b> {safe_action} · <b>Last active:</b> {html.escape(snap['heartbeat_relative'])} · <b>Last upload:</b> {last_upload_info}</div>"
            f"<div><b>Progress:</b> {progress_text}</div>"
            f"{warnings_html}"
            f"{error_banner}"
            f"</div>"
        )

        card_status = ipw.HTML(value="")
        btn_box = ipw.HBox()

        if status == "RUNNING":
            stop_btn = ipw.Button(
                description="Stop",
                button_style="danger",
                icon="stop",
                layout=ipw.Layout(width="100px"),
            )

            def _on_stop(_b, target_pid=pid):
                if target_pid is not None:
                    self.stop_watchdog_pids(
                        [target_pid], notify=False, remove_entries=False
                    )

            stop_btn.on_click(_on_stop)
            btn_box.children = [stop_btn]
        else:
            resume_btn = ipw.Button(
                description="Resume",
                button_style="success",
                icon="play",
                layout=ipw.Layout(width="110px"),
            )
            dismiss_btn = ipw.Button(
                description="Dismiss",
                button_style="",
                icon="times",
                layout=ipw.Layout(width="100px"),
            )

            def _on_resume(_b, s=snap, rbtn=resume_btn, status_out=card_status):
                session_id = s.get("session_id")
                folder = s.get("monitored_folder") or ""
                resume_key = session_id or folder
                if resume_key in self._resuming_sessions:
                    return
                self._resuming_sessions.add(resume_key)
                rbtn.disabled = True
                try:
                    if not folder or not os.path.isdir(folder):
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            "⚠ Cannot resume: folder not found on disk.</div>"
                        )
                        return

                    if self.get_active_watchdogs_for_folder(folder, refresh_ui=False):
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            "⚠ Cannot resume: this folder is already being monitored by an active watchdog.</div>"
                        )
                        return

                    if not session_id:
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            "⚠ Cannot resume: missing Measurement Session ID.</div>"
                        )
                        return

                    openbis_url = (
                        self.session_data.get("url")
                        if isinstance(self.session_data, dict)
                        else None
                    )
                    openbis_token = (
                        self.session_data.get("token")
                        if isinstance(self.session_data, dict)
                        else None
                    )
                    if not openbis_url or not openbis_token:
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            "⚠ Cannot resume: missing openBIS session credentials (URL or token).</div>"
                        )
                        return

                    try:
                        utils.get_openbis_object(
                            self.openbis_session, sample_ident=session_id
                        )
                    except Exception:
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            "⚠ Cannot resume: Measurement Session no longer exists in openBIS.</div>"
                        )
                        return

                    logs_dir = self._measurement_logs_dir()
                    log_json_path = get_measurement_log_filepath(
                        session_id, logs_dir=logs_dir
                    )
                    prev_state = (
                        measurement_monitor.read_json_safe(log_json_path, default={})
                        or {}
                    )
                    prev_token_expired = prev_state.get("token_expired", False)
                    prev_last_error = prev_state.get("last_error")

                    measurement_monitor.update_measurement_log(
                        log_json_path,
                        lambda d: d.update(
                            {
                                "eln_url": openbis_url,
                                "eln_token": openbis_token,
                                "measurement_session_id": session_id,
                                "data_folder": os.path.normpath(folder),
                                "token_expired": False,
                                "last_error": None,
                                "processed_files": d.get("processed_files", []),
                            }
                        ),
                    )
                    try:
                        proc, proc_log_path = (
                            measurement_monitor.start_watchdog_subprocess(
                                APP_FOLDER,
                                openbis_url,
                                openbis_token,
                                session_id,
                                folder,
                                logs_dir=logs_dir,
                            )
                        )
                    except Exception as exc:
                        measurement_monitor.update_measurement_log(
                            log_json_path,
                            lambda d: d.update(
                                {
                                    "token_expired": prev_token_expired,
                                    "last_error": prev_last_error,
                                }
                            ),
                        )
                        safe_err = html.escape(
                            measurement_monitor.redact_secrets(
                                str(exc), [openbis_token]
                            )
                        )
                        status_out.value = (
                            "<div style='color: #b91c1c; font-size: 12px; margin-top: 4px;'>"
                            f"⚠ Failed to start watchdog: {safe_err}</div>"
                        )
                        return
                    self.watchdog_processes.append(proc)
                    self.add_active_watchdog(
                        proc.pid,
                        folder,
                        session_id,
                        log_file=proc_log_path,
                    )
                finally:
                    self._resuming_sessions.discard(resume_key)
                    rbtn.disabled = False

            def _on_dismiss(_b, s=snap):
                measurement_monitor.dismiss_watchdog_entry(
                    self._active_watchdogs_file(),
                    measurement_session_id=s.get("session_id"),
                    pid=s.get("pid"),
                    data_folder=s.get("monitored_folder"),
                )
                self.render_watchdogs()

            resume_btn.on_click(_on_resume)
            dismiss_btn.on_click(_on_dismiss)
            btn_box.children = [resume_btn, dismiss_btn]

        # Collapsible Uploaded & Pending files drawer
        pending_items = "".join(
            f"<li><code>{html.escape(f)}</code> (pending)</li>"
            for f in snap["pending_files"][:20]
        )
        uploaded_items = "".join(
            f"<li><code>{html.escape(str(ev.get('filename') or ''))}</code> "
            f"[{html.escape(str(ev.get('type') or 'FILE'))}]"
            f"{' — ' + html.escape(str(ev['uploaded_at'])) if ev.get('uploaded_at') else ''}</li>"
            for ev in snap["recent_uploads"][:20]
        )
        files_body = ""
        if pending_items:
            files_body += f"<div><b>Pending ({pending_count}):</b><ul style='margin: 2px 0 6px 18px;'>{pending_items}</ul></div>"
        if uploaded_items:
            files_body += f"<div><b>Recent uploads ({snap['uploaded_count']} total):</b><ul style='margin: 2px 0 0 18px;'>{uploaded_items}</ul></div>"
        if not files_body:
            files_body = "<div style='color: #6b7280; font-style: italic;'>No files recorded yet.</div>"

        files_drawer = ipw.HTML(
            f"<details style='margin-top: 6px; font-size: 12px;'>"
            f"<summary style='cursor: pointer; color: #374151; font-weight: bold;'>"
            f"Uploaded & pending files ({snap['uploaded_count']} uploaded / {pending_count} pending)"
            f"</summary>"
            f"<div style='margin-top: 6px; padding: 6px 8px; background: #f9fafb; border-radius: 4px;'>{files_body}</div>"
            f"</details>"
        )

        # Collapsible Recent logs & errors drawer
        err_items = "".join(
            f"<li><b>[{html.escape(str(e.get('stage') or 'error'))}]</b> "
            f"{html.escape(str(e.get('file') or ''))} "
            f"{html.escape(str(e.get('message') or ''))} "
            f"<span style='color: #6b7280;'>({html.escape(str(e.get('timestamp') or ''))})</span></li>"
            for e in snap["recent_errors"][:20]
        )
        errors_section = (
            f"<div><b>Recorded errors ({snap['error_count']}):</b>"
            f"<ul style='margin: 2px 0 6px 18px; color: #991b1b;'>{err_items}</ul></div>"
            if err_items
            else ""
        )
        log_tail_text = (
            html.escape("\n".join(snap["log_tail"]))
            if snap["log_tail"]
            else "No worker log output yet."
        )
        log_path_label = (
            f" — <code>{html.escape(str(snap['log_file_path']))}</code>"
            if snap.get("log_file_path")
            else ""
        )
        logs_drawer = ipw.HTML(
            f"<details style='margin-top: 4px; font-size: 12px;'>"
            f"<summary style='cursor: pointer; color: #374151; font-weight: bold;'>"
            f"Recent logs & errors ({snap['error_count']} error(s) · {len(snap['log_tail'])} log lines){log_path_label}"
            f"</summary>"
            f"<div style='margin-top: 6px; padding: 6px 8px; background: #f9fafb; border-radius: 4px;'>"
            f"{errors_section}"
            f"<pre style='margin: 0; max-height: 220px; overflow-y: auto; font-size: 11px; white-space: pre-wrap;'>{log_tail_text}</pre>"
            f"</div>"
            f"</details>"
        )

        return ipw.VBox(
            [header_html, details_html, btn_box, card_status, files_drawer, logs_drawer],
            layout=ipw.Layout(
                border="1px solid #e5e7eb",
                padding="12px",
                margin="0 0 10px 0",
            ),
        )


class GenerateMeasurementsWatchdogWidget(ipw.VBox):
    def __init__(self, openbis_session, session_data, running_watchdogs_widget):
        super().__init__()
        self.openbis_session = openbis_session
        self.session_data = session_data
        self.running_watchdogs_widget = running_watchdogs_widget
        self.watchdog_processes = []
        self.measurement_logs_folder = MEASUREMENT_LOGS_FOLDER
        self._pending_folder_conflict = None

        # Keep __init__ clean by delegating UI creation
        self._setup_ui()

    def _setup_ui(self):
        """Handles the creation and layout of all UI elements."""
        self.notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Understanding the Measurement Uploader
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
                        <li><span style="color: #2980b9; font-weight: bold;">Watchdogs</span> run in the background to automatically detect and upload new measurement files.</li>
                        <li><span style="color: #27ae60; font-weight: bold;">Measurements</span> are securely linked to the specific experiment, sample, and instrument you configure.</li>
                    </ul>

                    <div style="font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 8px;">
                        Start directory monitoring (Setup):
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
                        <li style="margin-bottom: 6px;">
                            <b>Select project:</b> Only experiments that belong to the selected project will be available for selection.
                            <i>(Note: This auto-fills when you select a sample. In the case, the project is not available, you have to open openBIS first and register it).</i>
                        </li>
                        <li style="margin-bottom: 6px;">
                            <b>Select experiment:</b> Determines where the measurement data will be saved in openBIS.
                            <i>(Note: If the experiment does not exist, you can create one by clicking the <b>+</b> button, selecting a project, and giving it a name).</i>
                        </li>
                        <li style="margin-bottom: 6px;"><b>Select sample:</b> Choose the specific sample that is being measured.</li>
                        <li style="margin-bottom: 6px;"><b>Select instrument:</b> Specify the device used to acquire the data.</li>
                        <li style="margin-bottom: 6px;"><b>Select measurements directory:</b> Define the local folder where the instrument saves its files.</li>
                        <li><b>Save (💾):</b> Locks in your configuration and starts a watchdog to monitor the selected directory.</li>
                    </ul>
                </div>
            </details>
            """
        )

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.measurement_session_title = ipw.HTML(
            value=f"<div style='{header_style}'>Measurement session details</div>"
        )
        self.measurement_session_name_label = ipw.HTML(value="<b>Name:</b>")
        self.measurement_session_name_text = ipw.Text(layout=ipw.Layout(width="100%"))
        self.measurement_session_name_hbox = ipw.HBox(
            [self.measurement_session_name_label, self.measurement_session_name_text]
        )

        # Dropdowns
        self.select_project_title = ipw.HTML(
            f"<div style='{header_style}'>Select project</div>"
        )
        self.select_project_widget = widgets.SelectProjectWidget(self.openbis_session)
        self.select_project_widget.project_dropdown.observe(
            self.load_experiment_data, names="value"
        )
        self.select_project_widget.project_dropdown.observe(
            self._on_form_input_changed, names="value"
        )

        self.select_experiment_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select experiment</div>"
        )
        self.select_experiment_widget = widgets.SelectExperimentWidget(
            self.openbis_session
        )
        self.select_experiment_widget.experiment_dropdown.observe(
            self._on_form_input_changed, names="value"
        )

        self.select_experiment_widget.create_experiment_button.on_click(
            self.show_create_experiment_ui
        )

        self.select_sample_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select sample</div>"
        )
        self.select_sample_widget = widgets.SelectSampleWidget(self.openbis_session)
        self.select_sample_widget.sample_dropdown.observe(
            self._on_sample_changed, names="value"
        )
        self.select_sample_widget.sample_dropdown.observe(
            self._on_form_input_changed, names="value"
        )

        self.select_instrument_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select instrument</div>"
        )
        self.select_instrument_widget = widgets.SelectInstrumentWidget(
            self.openbis_session
        )
        self.select_instrument_widget.instrument_dropdown.observe(
            self._on_form_input_changed, names="value"
        )

        # Folder Chooser
        self.select_measurements_folder_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select measurements directory</div>"
        )
        self.select_measurements_folder_widget = ipyfilechooser.FileChooser(
            path="/home/jovyan/",
            select_default=True,
            use_dir_icons=True,
            show_only_dirs=True,
        )
        self.select_measurements_folder_widget.register_callback(
            self._on_folder_changed
        )

        # Save Button
        self.generate_watchdog_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )
        self.generate_watchdog_button.on_click(self.generate_watchdog)

        self.folder_conflict_box = ipw.VBox(layout=ipw.Layout(display="none"))

        self.children = [
            self.notes,
            self.select_project_title,
            self.select_project_widget,
            self.select_experiment_title,
            self.select_experiment_widget,
            self.select_sample_title,
            self.select_sample_widget,
            self.select_instrument_title,
            self.select_instrument_widget,
            self.measurement_session_title,
            self.measurement_session_name_hbox,
            self.select_measurements_folder_title,
            self.select_measurements_folder_widget,
            self.generate_watchdog_button,
            self.folder_conflict_box,
        ]

    def load_experiment_data(self, change):
        project_identifier = self.select_project_widget.project_dropdown.value
        self.select_experiment_widget.load_experiments(project_identifier)

        if self.select_project_widget.project_dropdown.value == "-1":
            self.select_experiment_widget.create_experiment_button.disabled = True
            return

        else:
            self.select_experiment_widget.create_experiment_button.disabled = False
            self.select_experiment_widget.create_experiment_button.on_click(
                self.show_create_experiment_ui
            )

    def show_create_experiment_ui(self, b):
        self.select_experiment_widget.show_create_panel()
        self.select_project_widget.project_dropdown.disabled = True
        self.select_project_widget.filter_my_projects_cb.disabled = True
        self.select_project_widget.sort_date_cb.disabled = True
        self.select_project_widget.sort_name_cb.disabled = True
        self.select_experiment_widget.save_btn.on_click(self.save_new_experiment)
        self.select_experiment_widget.cancel_btn.on_click(self.cancel_new_experiment)

    def save_new_experiment(self, b):
        project_identifier = self.select_project_widget.project_dropdown.value
        new_experiment_name = (
            self.select_experiment_widget.new_exp_name_textbox.value.strip()
        )
        new_experiment_description = (
            self.select_experiment_widget.new_exp_description_textbox.value.strip()
        )

        if project_identifier == "-1":
            display(Javascript(data="alert('Select a project.')"))
            return
        if not new_experiment_name:
            display(Javascript(data="alert('Experiment name cannot be empty.')"))
            return

        try:
            new_experiment = utils.create_openbis_collection(
                self.openbis_session,
                type="EXPERIMENT",
                project=project_identifier,
                props={
                    "name": new_experiment_name,
                    "description": new_experiment_description,
                    "default_collection_view": "IMAGING_GALLERY_VIEW",
                },
            )
            self.select_experiment_widget.hide_create_panel()
            project_identifier = self.select_project_widget.project_dropdown.value
            self.select_experiment_widget.load_experiments(
                project_identifier
            )  # Reload the main DataFrame
            self.select_experiment_widget.experiment_dropdown.value = (
                new_experiment.permId
            )
            display(Javascript(data="alert('Experiment successfully created!')"))

        except ValueError:
            display(
                Javascript(data="alert('Error! Check if experiment already exists.')")
            )
        finally:
            self.select_project_widget.project_dropdown.disabled = False
            self.select_project_widget.filter_my_projects_cb.disabled = False
            self.select_project_widget.sort_date_cb.disabled = False
            self.select_project_widget.sort_name_cb.disabled = False

    def cancel_new_experiment(self, b):
        self.select_experiment_widget.hide_create_panel()
        project_identifier = self.select_project_widget.project_dropdown.value
        self.select_experiment_widget.load_experiments(
            project_identifier
        )  # Reload the main DataFrame
        self.select_project_widget.project_dropdown.disabled = False
        self.select_project_widget.filter_my_projects_cb.disabled = False
        self.select_project_widget.sort_date_cb.disabled = False
        self.select_project_widget.sort_name_cb.disabled = False

    def _get_most_recent_process_step(self, sample_object):
        """Helper to extract the most recent 'Process Step' parent from a sample."""
        most_recent_parent = None
        for parent_id in sample_object.parents:
            parent_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=parent_id
            )
            if parent_object.type == OPENBIS_OBJECT_TYPES["Process Step"]:
                if not most_recent_parent or (
                    parent_object.registrationDate > most_recent_parent.registrationDate
                ):
                    most_recent_parent = parent_object
        return most_recent_parent

    def _on_sample_changed(self, change):
        """Triggered when the user selects a different sample."""
        sample_id = change.new
        if sample_id == "-1":
            return

        sample_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=sample_id
        )

        sample_name = sample_object.props["name"]
        self.measurement_session_name_text.value = f"MEAS_{sample_name}"
        most_recent_parent = self._get_most_recent_process_step(sample_object)

        # 1. Early exit if no parent is found
        if not most_recent_parent:
            self.select_experiment_widget.experiment_dropdown.value = "-1"
            return

        # 2. Check if the experiment actually needs changing
        new_exp_id = most_recent_parent.experiment.permId
        current_exp_id = self.select_experiment_widget.experiment_dropdown.value

        if new_exp_id == current_exp_id:
            return  # Early exit if they are already the same

        most_recent_parent_experiment = utils.get_openbis_collection(
            self.openbis_session, code=most_recent_parent.experiment.identifier
        )

        self.select_project_widget.project_dropdown.value = (
            most_recent_parent_experiment.project.permId
        )

        self.select_experiment_widget.experiment_dropdown.value = (
            most_recent_parent.experiment.permId
        )

        display(
            Javascript(
                data="alert('Project and Experiment were auto-updated based on the sample!')"
            )
        )

        # 4. Better logging: Actually log *what* happened
        logger.info(
            f"Experiment auto-updated to {new_exp_id} based on sample {sample_name}."
        )

    def _validate_inputs(self):
        """Checks all UI components before allowing a save. Returns True if valid."""

        # 1. Check all dropdowns using a loop (DRY Principle)
        dropdowns_to_check = [
            (
                self.select_experiment_widget.experiment_dropdown,
                "Please select an experiment.",
            ),
            (self.select_sample_widget.sample_dropdown, "Please select a sample."),
            (
                self.select_instrument_widget.instrument_dropdown,
                "Please select an instrument.",
            ),
        ]

        for dropdown, error_msg in dropdowns_to_check:
            if dropdown.value == "-1":
                display(Javascript(data=f"alert('{error_msg}');"))
                return False

        # 2. Check if the folder chooser is still in "edit" mode
        try:
            is_selecting = (
                self.select_measurements_folder_widget._cancel.layout.display is None
            )
        except AttributeError:
            is_selecting = (
                False  # Fallback if ipyfilechooser updates its internal variables
            )

        if is_selecting:
            display(
                Javascript(
                    data="alert('You are still editing the directory! Please confirm it by clicking \"Change\".');"
                )
            )
            return False

        # 3. Check if a valid path is actually selected
        if not self.select_measurements_folder_widget.selected_path:
            display(Javascript(data="alert('Please select a valid directory.');"))
            return False

        return True

    def _get_session_name(self, measurement_session, fallback=None):
        if measurement_session is None:
            return fallback or "Unknown"
        props = getattr(measurement_session, "props", None)
        name = None
        if props is not None:
            try:
                name = props.get("name")
            except AttributeError:
                try:
                    name = props["name"]
                except (KeyError, TypeError):
                    name = None
        return (
            name
            or getattr(measurement_session, "permId", None)
            or fallback
            or "Unknown"
        )

    def _reap_watchdog_processes(self):
        alive_processes = []
        for process in getattr(self, "watchdog_processes", []):
            poll = getattr(process, "poll", None)
            if callable(poll):
                try:
                    if poll() is not None:
                        continue
                except OSError:
                    continue
            alive_processes.append(process)
        self.watchdog_processes = alive_processes

    def _find_existing_folder_tracking(self, data_folder):
        """Inspects active watchdogs and measurement logs for an existing link to data_folder."""
        self._reap_watchdog_processes()
        logs_dir = getattr(self, "measurement_logs_folder", MEASUREMENT_LOGS_FOLDER)
        norm_data_folder = os.path.normpath(data_folder)

        running_widget = getattr(self, "running_watchdogs_widget", None)
        active_entries = (
            running_widget.get_active_watchdogs_for_folder(norm_data_folder)
            if running_widget is not None
            else []
        )

        matched_session = None
        matched_log_filepath = None
        matched_logging_data = None
        for log_filepath, logging_data in find_measurement_logs_for_folder(
            norm_data_folder, logs_dir=logs_dir
        ):
            session_id = logging_data.get("measurement_session_id")
            if not session_id:
                continue
            try:
                matched_session = utils.get_openbis_object(
                    self.openbis_session, sample_ident=session_id
                )
                matched_log_filepath = log_filepath
                matched_logging_data = logging_data
                break
            except ValueError:
                logger.info(
                    f"Previous Measurement Session {session_id} no longer exists in openBIS. Removing stale log."
                )
                try:
                    log_filepath.unlink()
                except OSError:
                    pass

        if active_entries:
            active_pids = [
                entry["pid"] for entry in active_entries if entry.get("pid") is not None
            ]
            active_session_id = next(
                (
                    entry.get("measurement_session_id")
                    for entry in reversed(active_entries)
                    if entry.get("measurement_session_id")
                ),
                None,
            )
            if active_session_id is None and matched_session is not None:
                active_session_id = matched_session.permId

            measurement_session = None
            if (
                matched_session is not None
                and active_session_id == matched_session.permId
            ):
                measurement_session = matched_session
            elif active_session_id:
                try:
                    measurement_session = utils.get_openbis_object(
                        self.openbis_session, sample_ident=active_session_id
                    )
                except ValueError:
                    measurement_session = None

            session_id = (
                measurement_session.permId
                if measurement_session is not None
                else active_session_id
            )
            return {
                "is_running": True,
                "active_pids": active_pids,
                "measurement_session": measurement_session,
                "session_id": session_id,
                "session_name": self._get_session_name(
                    measurement_session, fallback=session_id
                ),
                "log_filepath": matched_log_filepath,
                "logging_data": matched_logging_data,
            }

        if matched_session is not None:
            return {
                "is_running": False,
                "active_pids": [],
                "measurement_session": matched_session,
                "session_id": matched_session.permId,
                "session_name": self._get_session_name(
                    matched_session, fallback=matched_session.permId
                ),
                "log_filepath": matched_log_filepath,
                "logging_data": matched_logging_data,
            }

        return None

    def _create_openbis_measurement_session(
        self, sample_id, instrument_id, experiment_id, data_folder
    ):
        norm_data_folder = os.path.normpath(data_folder)
        measurement_session = utils.create_openbis_object(
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Measurement Session"],
            collection=experiment_id,
            parents=[sample_id, instrument_id],
            props={
                "name": self.measurement_session_name_text.value,
                "default_object_view": "IMAGING_GALLERY_VIEW",
                "measurement_folder_path": norm_data_folder,
            },
        )
        logger.info(f"New Measurement Session {measurement_session.permId} created.")
        return measurement_session

    def _dropdown_selected_label(self, dropdown):
        if dropdown is None:
            return None
        val = getattr(dropdown, "value", None)
        if val in (None, "-1"):
            return None
        for option in getattr(dropdown, "options", ()):
            if isinstance(option, (tuple, list)) and len(option) >= 2:
                if option[1] == val:
                    return str(option[0])
            elif option == val:
                return str(option)
        return str(val)

    def _collect_form_metadata(self):
        metadata = {}
        name_widget = getattr(self, "measurement_session_name_text", None)
        if name_widget is not None and getattr(name_widget, "value", None):
            metadata["session_name"] = str(name_widget.value)
        sample_widget = getattr(self, "select_sample_widget", None)
        if sample_widget is not None:
            sample_label = self._dropdown_selected_label(
                getattr(sample_widget, "sample_dropdown", None)
            )
            if sample_label:
                metadata["sample_name"] = sample_label
        exp_widget = getattr(self, "select_experiment_widget", None)
        if exp_widget is not None:
            exp_label = self._dropdown_selected_label(
                getattr(exp_widget, "experiment_dropdown", None)
            )
            if exp_label:
                metadata["experiment_name"] = exp_label
        inst_widget = getattr(self, "select_instrument_widget", None)
        if inst_widget is not None:
            inst_label = self._dropdown_selected_label(
                getattr(inst_widget, "instrument_dropdown", None)
            )
            if inst_label:
                metadata["instrument_name"] = inst_label
        return metadata

    def _write_fresh_measurement_log(self, measurement_session_id, data_folder):
        logs_dir = getattr(self, "measurement_logs_folder", MEASUREMENT_LOGS_FOLDER)
        norm_data_folder = os.path.normpath(data_folder)
        log_filepath = get_measurement_log_filepath(
            measurement_session_id, logs_dir=logs_dir
        )
        logging_data = {
            "eln_url": self.session_data["url"],
            "eln_token": self.session_data["token"],
            "measurement_session_id": measurement_session_id,
            "data_folder": norm_data_folder,
            "started_at": measurement_monitor.utc_now_iso(),
            "token_expired": False,
            "last_error": None,
            "processed_files": [],
            "upload_history": [],
            "recent_errors": [],
        }
        logging_data.update(self._collect_form_metadata())
        measurement_monitor.atomic_write_json(logging_data, str(log_filepath))
        return log_filepath

    def _resume_existing_measurement_session(self, tracking_info, data_folder):
        logs_dir = getattr(self, "measurement_logs_folder", MEASUREMENT_LOGS_FOLDER)
        norm_data_folder = os.path.normpath(data_folder)
        measurement_session = tracking_info["measurement_session"]
        log_filepath = tracking_info.get("log_filepath") or get_measurement_log_filepath(
            measurement_session.permId, logs_dir=logs_dir
        )
        logging_data = dict(tracking_info.get("logging_data") or {})
        logging_data["eln_url"] = self.session_data["url"]
        logging_data["eln_token"] = self.session_data["token"]
        logging_data["measurement_session_id"] = measurement_session.permId
        logging_data["data_folder"] = norm_data_folder
        logging_data["token_expired"] = False
        logging_data["last_error"] = None
        logging_data.setdefault("processed_files", [])
        if tracking_info.get("session_name"):
            logging_data.setdefault("session_name", tracking_info["session_name"])
        measurement_monitor.atomic_write_json(logging_data, str(log_filepath))
        logger.info(
            f"Uploading data into existing Measurement Session {measurement_session.permId}."
        )
        return measurement_session

    def _get_or_create_measurement_session(
        self, sample_id, instrument_id, experiment_id, data_folder
    ):
        """Creates an openBIS session object or retrieves an existing one from logs/measurements."""
        tracking_info = self._find_existing_folder_tracking(data_folder)
        if tracking_info and tracking_info.get("measurement_session") is not None:
            return self._resume_existing_measurement_session(tracking_info, data_folder)

        measurement_session = self._create_openbis_measurement_session(
            sample_id, instrument_id, experiment_id, data_folder
        )
        self._write_fresh_measurement_log(measurement_session.permId, data_folder)
        return measurement_session

    def _start_watchdog_process(
        self, measurement_session_id, data_folder, metadata=None
    ):
        norm_data_folder = os.path.normpath(data_folder)
        logs_dir = getattr(self, "measurement_logs_folder", MEASUREMENT_LOGS_FOLDER)
        watchdog_process, proc_log_path = measurement_monitor.start_watchdog_subprocess(
            APP_FOLDER,
            self.session_data["url"],
            self.session_data["token"],
            measurement_session_id,
            norm_data_folder,
            logs_dir=logs_dir,
        )

        display(Javascript(data="alert('Watchdog process started!');"))
        logger.info(
            f"Watchdog process started with PID: {watchdog_process.pid} for {norm_data_folder}"
        )

        effective_metadata = (
            metadata if metadata is not None else self._collect_form_metadata()
        )
        self.running_watchdogs_widget.add_active_watchdog(
            watchdog_process.pid,
            norm_data_folder,
            measurement_session_id,
            metadata=effective_metadata,
            log_file=proc_log_path,
        )
        self.watchdog_processes.append(watchdog_process)
        return watchdog_process

    def _on_folder_changed(self, _chooser):
        self._clear_folder_conflict_prompt()

    def _on_form_input_changed(self, _change):
        self._clear_folder_conflict_prompt()

    def _clear_folder_conflict_prompt(self):
        self._pending_folder_conflict = None
        if hasattr(self, "folder_conflict_box"):
            self.folder_conflict_box.children = ()
            self.folder_conflict_box.layout.display = "none"
        if hasattr(self, "generate_watchdog_button"):
            self.generate_watchdog_button.disabled = False

    def _show_folder_conflict_prompt(
        self, tracking_info, sample_id, instrument_id, experiment_id, data_folder
    ):
        norm_data_folder = os.path.normpath(data_folder)
        self._pending_folder_conflict = {
            "tracking_info": tracking_info,
            "sample_id": sample_id,
            "instrument_id": instrument_id,
            "experiment_id": experiment_id,
            "data_folder": norm_data_folder,
        }
        self.generate_watchdog_button.disabled = True

        safe_folder = html.escape(norm_data_folder)
        safe_name = html.escape(str(tracking_info.get("session_name") or "Unknown"))
        safe_session_id = html.escape(
            str(tracking_info.get("session_id") or "Unknown")
        )
        if tracking_info["is_running"]:
            pids_str = ", ".join(
                str(pid) for pid in tracking_info.get("active_pids", [])
            )
            status_text = f"Actively monitored (PID {html.escape(pids_str)})"
        else:
            status_text = "Not currently running (previously linked)"

        deleted_note = ""
        if tracking_info.get("measurement_session") is None:
            deleted_note = (
                "<br><i>The linked Measurement Session could not be found in openBIS, "
                "so continuing it is unavailable.</i>"
            )

        prompt_html = ipw.HTML(
            value=f"""
            <div style="background-color: #fdf2f2; border-left: 5px solid #e74c3c; padding: 12px; margin-top: 10px; border-radius: 4px; font-family: sans-serif; color: #2c3e50;">
                <div style="font-weight: bold; font-size: 14px; color: #991b1b; margin-bottom: 6px;">
                    ⚠️ Folder already linked to an existing Measurement Session
                </div>
                <div style="font-size: 13px; line-height: 1.5; margin-bottom: 8px;">
                    Directory <code>{safe_folder}</code> is already linked to Measurement Session
                    <b>{safe_name}</b> (<code>{safe_session_id}</code>) — <b>{status_text}</b>.{deleted_note}<br>
                    Do you want to continue uploading this folder to the previous measurement session?
                </div>
                <div style="font-size: 12px; color: #991b1b;">
                    <b>Warning:</b> Only switch to a new measurement session if the previous one was created by mistake.
                    Switching stops the connection to the previous session and uploads all existing files in this folder to the new session.
                </div>
            </div>
            """
        )

        continue_btn = ipw.Button(
            description="Continue existing session",
            button_style="success",
            icon="play",
            disabled=tracking_info.get("measurement_session") is None,
            layout=ipw.Layout(width="220px"),
        )
        switch_btn = ipw.Button(
            description="Switch to new session",
            button_style="danger",
            icon="exclamation-triangle",
            tooltip="Use only if the previous measurement session was created by mistake",
            layout=ipw.Layout(width="200px"),
        )
        cancel_btn = ipw.Button(
            description="Cancel",
            button_style="",
            layout=ipw.Layout(width="100px"),
        )

        def _consume_pending():
            if self._pending_folder_conflict is None:
                return False
            self._pending_folder_conflict = None
            continue_btn.disabled = True
            switch_btn.disabled = True
            cancel_btn.disabled = True
            return True

        def _on_continue(_):
            if not _consume_pending():
                return
            live_tracking = self._find_existing_folder_tracking(norm_data_folder)
            self._clear_folder_conflict_prompt()
            if live_tracking is not None and live_tracking["is_running"]:
                logger.info(
                    f"Continuing active watchdog for {norm_data_folder} (session {live_tracking.get('session_id')})."
                )
                display(
                    Javascript(
                        data="alert('Continuing upload to the existing measurement session.');"
                    )
                )
                return

            if (
                live_tracking is not None
                and live_tracking.get("measurement_session") is not None
            ):
                measurement_session = self._resume_existing_measurement_session(
                    live_tracking, norm_data_folder
                )
                resume_meta = {}
                if live_tracking.get("session_name"):
                    resume_meta["session_name"] = live_tracking["session_name"]
                self._start_watchdog_process(
                    measurement_session.permId,
                    norm_data_folder,
                    metadata=resume_meta,
                )
                return

            logger.warning(
                f"Previous Measurement Session for {norm_data_folder} is no longer available in openBIS."
            )
            display(
                Javascript(
                    data="alert('The previous measurement session is no longer available in openBIS.');"
                )
            )

        def _on_switch(_):
            if not _consume_pending():
                return
            if not self._validate_inputs():
                self._clear_folder_conflict_prompt()
                return

            current_sample_id = self.select_sample_widget.sample_dropdown.value
            current_experiment_id = (
                self.select_experiment_widget.experiment_dropdown.value
            )
            current_instrument_id = (
                self.select_instrument_widget.instrument_dropdown.value
            )
            logs_dir = getattr(self, "measurement_logs_folder", MEASUREMENT_LOGS_FOLDER)
            try:
                new_session = self._create_openbis_measurement_session(
                    current_sample_id,
                    current_instrument_id,
                    current_experiment_id,
                    norm_data_folder,
                )
            except Exception as exc:
                logger.exception(
                    f"Failed to create new Measurement Session for {norm_data_folder}: {exc}"
                )
                self._clear_folder_conflict_prompt()
                display(
                    Javascript(
                        data="alert('Failed to create new measurement session. Previous tracking was left unchanged.');"
                    )
                )
                return

            live_active = self.running_watchdogs_widget.get_active_watchdogs_for_folder(
                norm_data_folder
            )
            active_pids = list(
                dict.fromkeys(
                    [
                        *(tracking_info.get("active_pids") or []),
                        *(
                            entry["pid"]
                            for entry in live_active
                            if entry.get("pid") is not None
                        ),
                    ]
                )
            )
            if active_pids:
                self.running_watchdogs_widget.stop_watchdog_pids(
                    active_pids, notify=False, remove_entries=True
                )
                stopped_set = set(active_pids)
                remaining_processes = []
                for process in self.watchdog_processes:
                    if getattr(process, "pid", None) in stopped_set:
                        wait = getattr(process, "wait", None)
                        if callable(wait):
                            try:
                                wait(timeout=1)
                            except (subprocess.TimeoutExpired, OSError):
                                pass
                    else:
                        remaining_processes.append(process)
                self.watchdog_processes = remaining_processes

            detached_paths = detach_measurement_logs_for_folder(
                norm_data_folder,
                replaced_by_session_id=new_session.permId,
                logs_dir=logs_dir,
            )
            detached_session_ids = [p.stem for p in detached_paths]
            self.running_watchdogs_widget.remove_watchdog_entries_for_folder(
                norm_data_folder, session_ids=detached_session_ids
            )
            self._write_fresh_measurement_log(new_session.permId, norm_data_folder)
            self._clear_folder_conflict_prompt()
            self._start_watchdog_process(new_session.permId, norm_data_folder)

        def _on_cancel(_):
            if not _consume_pending():
                return
            self._clear_folder_conflict_prompt()

        continue_btn.on_click(_on_continue)
        switch_btn.on_click(_on_switch)
        cancel_btn.on_click(_on_cancel)

        self.folder_conflict_box.children = [
            prompt_html,
            ipw.HBox(
                [continue_btn, switch_btn, cancel_btn],
                layout=ipw.Layout(margin="8px 0 0 0"),
            ),
        ]
        self.folder_conflict_box.layout.display = ""

    def generate_watchdog(self, b):
        self._clear_folder_conflict_prompt()

        # 1. Block saving if inputs (or the folder chooser) aren't ready
        if not self._validate_inputs():
            return

        # 2. Gather verified data
        sample_id = self.select_sample_widget.sample_dropdown.value
        experiment_id = self.select_experiment_widget.experiment_dropdown.value
        instrument_id = self.select_instrument_widget.instrument_dropdown.value
        data_folder = os.path.normpath(
            self.select_measurements_folder_widget.selected_path
        )

        # 3. Check if folder is already tracked (running watchdog or previous session log)
        tracking_info = self._find_existing_folder_tracking(data_folder)
        if tracking_info is not None:
            self._show_folder_conflict_prompt(
                tracking_info,
                sample_id,
                instrument_id,
                experiment_id,
                data_folder,
            )
            return

        # 4. Create new measurement session, initialize fresh log, and start watchdog
        measurement_session = self._create_openbis_measurement_session(
            sample_id,
            instrument_id,
            experiment_id,
            data_folder,
        )
        self._write_fresh_measurement_log(measurement_session.permId, data_folder)
        self._start_watchdog_process(measurement_session.permId, data_folder)

    def cleanup_watchdog(self):
        if self.watchdog_processes:
            for process in self.watchdog_processes:
                logger.info(f"Terminating watchdog process with PID: {process.pid}")
                process.terminate()
            self.watchdog_processes = []
