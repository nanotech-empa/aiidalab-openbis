import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import ipyfilechooser
import ipywidgets as ipw
from pybis import AfsClient
from src import sync_registry, utils


class SetupSyncWidget(ipw.VBox):
    def __init__(
        self,
        openbis_session,
        registry_path: Path = sync_registry.DEFAULT_REGISTRY_PATH,
        on_job_started: Optional[Callable[[str], None]] = None,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.registry_path = Path(registry_path)
        self.on_job_started = on_job_started
        self.current_owner = None
        self.current_object_id = None

        self._build_ui()

    def _get_available_eln_instances(self):
        try:
            config = utils.read_json(utils.ELN_CONFIG)
            instances = [
                k
                for k in config.keys()
                if k != "default"
                and isinstance(config[k], dict)
                and "token" in config[k]
            ]
            return instances, config.get("default")
        except Exception:
            return [], None

    def _build_ui(self):
        # Explanation box
        info_html = ipw.HTML(
            """
            <div style="background: #eef2ff; border-left: 4px solid #6366f1; padding: 12px; margin-bottom: 15px; font-size: 13px; border-radius: 4px;">
                <strong>📘 AFS Folder Synchronisation</strong><br>
                Establish an automated, one-way background synchronisation from openBIS AFS to local AiiDAlab storage.
                Deletions, modifications, and new files on openBIS are mirrored locally. Unchanged files are not re-downloaded.
            </div>
            """
        )

        # 0. openBIS Instance Selector
        eln_instances, default_eln = self._get_available_eln_instances()
        current_url = getattr(self.openbis_session, "url", default_eln or "")

        current_matched = None
        for inst in eln_instances:
            if inst.rstrip("/") == current_url.rstrip("/"):
                current_matched = inst
                break
        if not current_matched and eln_instances:
            current_matched = eln_instances[0]

        if len(eln_instances) > 1:
            self.instance_dropdown = ipw.Dropdown(
                options=eln_instances,
                value=current_matched,
                description="openBIS URL:",
                style={"description_width": "initial"},
                layout=ipw.Layout(width="450px"),
            )
            self.instance_dropdown.observe(self._on_instance_change, names="value")
            instance_widget = self.instance_dropdown
        else:
            instance_widget = ipw.HTML(
                f"<div style='font-size: 12px; color: #4b5563; margin-bottom: 6px;'>"
                f"<strong>Connected openBIS Instance:</strong> <code>{current_url}</code>"
                f"</div>"
            )

        instance_box = ipw.VBox(
            [
                ipw.HTML("<strong>0. Connected openBIS Instance</strong>"),
                instance_widget,
            ],
            layout=ipw.Layout(margin="0 0 15px 0"),
        )

        # 1. Object Search
        self.object_input = ipw.Text(
            placeholder="Enter Sample / Object Identifier or PermId (e.g. /DEFAULT/RAW_EXP/SAMPLE_1)",
            layout=ipw.Layout(flex="1 1 auto"),
        )
        self.search_btn = ipw.Button(
            description="Search & Browse AFS",
            button_style="info",
            icon="search",
            layout=ipw.Layout(width="180px"),
        )
        self.search_btn.on_click(self._on_search)
        self.search_status = ipw.HTML(value="")

        search_box = ipw.VBox(
            [
                ipw.HTML("<strong>1. Select openBIS Object</strong>"),
                ipw.HBox([self.object_input, self.search_btn]),
                self.search_status,
            ],
            layout=ipw.Layout(margin="0 0 15px 0"),
        )

        # 2. AFS Folder Selector
        self.afs_dropdown = ipw.Dropdown(
            description="AFS Folder:",
            options=["/"],
            value="/",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="95%"),
        )
        self.afs_dropdown.observe(self._on_folder_change, names="value")

        afs_box = ipw.VBox(
            [
                ipw.HTML("<strong>2. Source Folder in AFS</strong>"),
                self.afs_dropdown,
            ],
            layout=ipw.Layout(margin="0 0 15px 0"),
        )

        # 3. Local Target
        self.local_input = ipw.Text(
            description="Local Path:",
            placeholder="/home/jovyan/data/...",
            style={"description_width": "initial"},
            layout=ipw.Layout(flex="1 1 auto"),
        )
        self.local_input.observe(self._on_folder_change, names="value")

        self.browse_btn = ipw.Button(
            description="Browse Folder",
            button_style="info",
            icon="folder-open",
            layout=ipw.Layout(width="150px"),
        )
        self.browse_btn.on_click(self._on_toggle_file_chooser)

        self.file_chooser = ipyfilechooser.FileChooser(
            path="/home/jovyan",
            show_only_dirs=True,
            select_default=False,
            title="Select Destination Directory:",
        )
        self.file_chooser.use_dir_icons = True
        self.file_chooser.register_callback(self._on_local_folder_selected)

        self.file_chooser_box = ipw.VBox(
            [self.file_chooser],
            layout=ipw.Layout(
                display="none",
                margin="6px 0",
                padding="8px",
                border="1px dashed #cbd5e1",
            ),
        )

        local_row = ipw.HBox([self.local_input, self.browse_btn])
        local_box = ipw.VBox(
            [
                ipw.HTML("<strong>3. Destination Folder in AiiDAlab</strong>"),
                local_row,
                self.file_chooser_box,
            ],
            layout=ipw.Layout(margin="0 0 15px 0"),
        )

        # 4. Poll Interval Dropdown
        self.poll_interval = ipw.Dropdown(
            options=[
                ("5 seconds", 5),
                ("10 seconds", 10),
                ("30 seconds", 30),
                ("1 minute", 60),
                ("5 minutes", 300),
                ("15 minutes", 900),
                ("30 minutes", 1800),
                ("1 hour", 3600),
            ],
            value=60,
            description="Poll Interval:",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="280px"),
        )

        interval_box = ipw.VBox(
            [
                ipw.HTML("<strong>4. Synchronisation Frequency</strong>"),
                self.poll_interval,
            ],
            layout=ipw.Layout(margin="0 0 15px 0"),
        )

        # Conflict Banner
        self.conflict_html = ipw.HTML(value="")

        # Start Button
        self.start_button = ipw.Button(
            description="Start Background Synchronisation",
            button_style="success",
            icon="play",
            layout=ipw.Layout(width="300px", height="40px"),
        )
        self.start_button.on_click(self._on_start)

        self.launch_status = ipw.HTML(value="")

        self.children = [
            info_html,
            instance_box,
            search_box,
            afs_box,
            local_box,
            interval_box,
            self.conflict_html,
            self.start_button,
            self.launch_status,
        ]

    def _on_instance_change(self, change):
        new_url = change["new"]
        try:
            sess, _ = utils.connect_openbis_aiida(new_url)
            if sess and sess.is_session_active():
                self.openbis_session = sess
                self.search_status.value = (
                    f"<span style='color: green;'>✓ Connected to {new_url}</span>"
                )
                self.afs_dropdown.options = ["/"]
                self.current_owner = None
                self.current_object_id = None
            else:
                self.search_status.value = f"<span style='color: red;'>Failed to establish active session with {new_url}.</span>"
        except Exception as e:
            self.search_status.value = (
                f"<span style='color: red;'>Error connecting to {new_url}: {e}</span>"
            )

    def _on_toggle_file_chooser(self, b):
        if self.file_chooser_box.layout.display == "none":
            self.file_chooser_box.layout.display = "block"
            self.browse_btn.description = "Close Browser"
            self.browse_btn.icon = "times"
            current_path = Path(self.local_input.value.strip() or "/home/jovyan")
            target = current_path if current_path.is_dir() else current_path.parent
            if target.is_dir():
                try:
                    self.file_chooser.reset(path=str(target))
                except Exception:
                    pass
        else:
            self.file_chooser_box.layout.display = "none"
            self.browse_btn.description = "Browse Folder"
            self.browse_btn.icon = "folder-open"

    def _on_local_folder_selected(self, chooser):
        chosen = chooser.selected_path or chooser.selected
        if chosen:
            self.local_input.value = str(chosen)
            self.file_chooser_box.layout.display = "none"
            self.browse_btn.description = "Browse Folder"
            self.browse_btn.icon = "folder-open"

    def check_conflict(
        self, owner: str, afs_path: str, local_path: str
    ) -> Optional[dict]:
        if not owner or not afs_path or not local_path:
            self.conflict_html.value = ""
            self.start_button.disabled = False
            return None

        conflict = sync_registry.find_conflict(
            owner, afs_path, local_path, self.registry_path
        )
        if conflict:
            pid = conflict.get("pid", "unknown")
            conf_afs = conflict.get("afs_path")
            conf_local = conflict.get("local_path")
            self.conflict_html.value = f"""
            <div style="background: #fef2f2; border: 1px solid #f87171; border-left: 4px solid #ef4444; padding: 10px; border-radius: 4px; margin-bottom: 12px; color: #991b1b; font-size: 12px;">
                <strong>⚠️ Synchronisation Conflict Detected</strong><br>
                This folder is already being synchronized to <code>{conf_local}</code> (AFS source: <code>{conf_afs}</code>, PID: {pid}).<br>
                Duplicate active synchronisations are not permitted. Manage or stop the running sync in the <em>Active Synchronisations</em> tab.
            </div>
            """
            self.start_button.disabled = True
        else:
            self.conflict_html.value = ""
            self.start_button.disabled = False

        return conflict

    def _on_folder_change(self, change):
        if self.current_owner:
            self.check_conflict(
                self.current_owner, self.afs_dropdown.value, self.local_input.value
            )

    def _on_search(self, b):
        query = self.object_input.value.strip()
        if not query:
            self.search_status.value = "<span style='color: red;'>Please enter an object code or identifier.</span>"
            return

        self.search_status.value = "Searching openBIS..."
        try:
            sample = None
            if hasattr(self.openbis_session, "get_sample"):
                try:
                    sample = self.openbis_session.get_sample(query)
                except Exception:
                    pass

            if not sample and hasattr(self.openbis_session, "get_experiment"):
                try:
                    sample = self.openbis_session.get_experiment(query)
                except Exception:
                    pass

            if not sample:
                self.search_status.value = (
                    f"<span style='color: red;'>Object '{query}' not found.</span>"
                )
                return

            self.current_owner = str(
                getattr(sample, "permId", getattr(sample, "code", query))
            )
            self.current_object_id = str(getattr(sample, "identifier", query))

            # Query AFS folders
            afs_url = (
                getattr(self.openbis_session, "url", "").rstrip("/") + "/afs-server"
            )
            token = getattr(self.openbis_session, "token", "")
            afs_client = AfsClient(afs_url, token, verify=False)

            folders = ["/"]
            flist = []
            try:
                flist = afs_client.list(self.current_owner, "/", recursively=True)
            except Exception as afs_err:
                self.search_status.value = f"<span style='color: orange;'>Found object '{self.current_object_id}', but could not load AFS files: {afs_err}</span>"
                return

            folders_set = set(["/"])
            for f in flist or []:
                p = "/" + f.path.strip("/")
                if getattr(f, "directory", False):
                    folders_set.add(p)
                else:
                    parts = p.strip("/").split("/")
                    for i in range(1, len(parts)):
                        folders_set.add("/" + "/".join(parts[:i]))
            folders = sorted(list(folders_set))

            self.afs_dropdown.options = folders
            self.afs_dropdown.value = folders[0]

            code_clean = str(getattr(sample, "code", "data")).lower()
            self.local_input.value = f"/home/jovyan/data/openbis_raw_scans/{code_clean}"

            if not flist:
                self.search_status.value = (
                    f"<span style='color: orange;'>⚠️ Found {self.current_object_id} "
                    f"(PermID: {self.current_owner}), but no files or folders were found in AFS for this object.</span>"
                )
            else:
                self.search_status.value = (
                    f"<span style='color: green;'>✓ Found {self.current_object_id} "
                    f"(PermID: {self.current_owner}). Loaded {len(folders)} AFS folder(s).</span>"
                )
            self.check_conflict(
                self.current_owner, self.afs_dropdown.value, self.local_input.value
            )

        except Exception as e:
            self.search_status.value = (
                f"<span style='color: red;'>Error querying openBIS: {e}</span>"
            )

    def _on_start(self, b):
        if not self.current_owner:
            self.launch_status.value = "<span style='color: red;'>Please search and select an openBIS object first.</span>"
            return

        afs_path = self.afs_dropdown.value
        local_path = self.local_input.value.strip()
        interval = max(5, int(self.poll_interval.value))

        if not local_path:
            self.launch_status.value = "<span style='color: red;'>Please specify a valid local destination folder.</span>"
            return

        if self.check_conflict(self.current_owner, afs_path, local_path):
            return

        job_id = f"sync-{int(time.time())}"
        config_dir = Path("logs/configs")
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / f"{job_id}.json"

        job_config = {
            "job_id": job_id,
            "owner": self.current_owner,
            "object_identifier": self.current_object_id or self.current_owner,
            "openbis_url": getattr(self.openbis_session, "url", "").rstrip("/"),
            "afs_path": afs_path,
            "local_path": local_path,
            "poll_interval": interval,
            "log_file": f"logs/sync_{job_id}.log",
            "status": "RUNNING",
            "started_at": datetime.datetime.now().isoformat(),
            "last_synced": None,
            "files_synced": 0,
        }

        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(job_config, f, indent=2)

        # Launch detached worker process
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.sync_afs_worker", "--config", str(config_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        job_config["pid"] = proc.pid
        sync_registry.register_job(job_config, self.registry_path)

        self.launch_status.value = f"<span style='color: green;'>✓ Background synchronisation started (PID: {proc.pid})!</span>"
        if self.on_job_started:
            self.on_job_started(job_id)


class ActiveSyncsWidget(ipw.VBox):
    def __init__(
        self,
        registry_path: Path = sync_registry.DEFAULT_REGISTRY_PATH,
        on_change: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.registry_path = Path(registry_path)
        self.on_change = on_change

        self.refresh_btn = ipw.Button(
            description="Refresh Status", icon="refresh", button_style=""
        )
        self.refresh_btn.on_click(lambda b: self.render_jobs())

        self.jobs_box = ipw.VBox()
        self.children = [
            ipw.HBox(
                [
                    ipw.HTML("<strong>Tracked Background Synchronisations</strong>"),
                    self.refresh_btn,
                ],
                layout=ipw.Layout(justify_content="space-between", margin="0 0 15px 0"),
            ),
            self.jobs_box,
        ]

        self.render_jobs()

    def render_jobs(self):
        sync_registry.sync_liveness(self.registry_path)
        registry = sync_registry.load_registry(self.registry_path)
        jobs = registry.get("jobs", {})

        if not jobs:
            self.jobs_box.children = [
                ipw.HTML(
                    "<div style='color: #6b7280; padding: 20px; font-style: italic;'>No synchronisation jobs configured yet.</div>"
                )
            ]
            return

        cards = []
        for job_id, job in sorted(
            jobs.items(), key=lambda kv: kv[1].get("started_at", ""), reverse=True
        ):
            cards.append(self._create_job_card(job_id, job))

        self.jobs_box.children = cards

    def _create_job_card(self, job_id: str, job: dict) -> ipw.Widget:
        status = job.get("status", "STOPPED")
        is_running = status == "RUNNING"
        pid = job.get("pid", "N/A")
        badge = (
            f"<span style='background: #dcfce7; color: #166534; font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 12px;'>● RUNNING (PID {pid})</span>"
            if is_running
            else "<span style='background: #f3f4f6; color: #6b7280; font-size: 11px; font-weight: bold; padding: 2px 8px; border-radius: 12px;'>○ STOPPED</span>"
        )

        header_html = ipw.HTML(f"""
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                {badge}
                <strong style="margin-left: 8px;">{job.get("object_identifier", job.get("owner"))}</strong>
            </div>
        </div>
        """)

        ob_url_line = (
            f"<div><strong>openBIS Instance:</strong> <code>{job.get('openbis_url')}</code></div>"
            if job.get("openbis_url")
            else ""
        )
        details_html = ipw.HTML(f"""
        <div style="font-size: 12px; color: #374151; margin: 8px 0;">
            {ob_url_line}
            <div><strong>AFS Source:</strong> <code>{job.get("afs_path")}</code></div>
            <div><strong>AiiDAlab Target:</strong> <code>{job.get("local_path")}</code></div>
            <div><strong>Poll Interval:</strong> Every {job.get("poll_interval")} seconds</div>
            <div><strong>Last Synced:</strong> {job.get("last_synced") or "Pending initial cycle"} ({job.get("files_synced", 0)} files)</div>
        </div>
        """)

        card_status = ipw.HTML(value="")

        btn_box = ipw.HBox()
        if is_running:
            stop_btn = ipw.Button(
                description="Stop Sync",
                button_style="danger",
                icon="stop",
                layout=ipw.Layout(width="110px"),
            )

            def _on_stop(b, jid=job_id):
                sync_registry.stop_job(jid, self.registry_path)
                self.render_jobs()
                if self.on_change:
                    self.on_change()

            stop_btn.on_click(_on_stop)
            btn_box.children = [stop_btn]
        else:
            resume_btn = ipw.Button(
                description="Resume Sync",
                button_style="success",
                icon="play",
                layout=ipw.Layout(width="120px"),
            )

            def _on_resume(b, j_info=job):
                conflict = sync_registry.find_conflict(
                    j_info["owner"],
                    j_info["afs_path"],
                    j_info["local_path"],
                    self.registry_path,
                )
                if conflict and conflict.get("job_id") != j_info.get("job_id"):
                    card_status.value = (
                        f"<div style='color: red; font-size: 11px; margin-top: 4px;'>"
                        f"⚠️ Cannot resume: folder is already actively being synchronized by job {conflict.get('job_id')} (PID {conflict.get('pid')})."
                        f"</div>"
                    )
                    return

                config_dir = Path("logs/configs")
                config_dir.mkdir(parents=True, exist_ok=True)
                config_file = config_dir / f"{j_info['job_id']}.json"
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(j_info, f, indent=2)

                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "src.sync_afs_worker",
                        "--config",
                        str(config_file),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                sync_registry.update_job(
                    j_info["job_id"],
                    {"status": "RUNNING", "pid": proc.pid},
                    self.registry_path,
                )
                self.render_jobs()
                if self.on_change:
                    self.on_change()

            resume_btn.on_click(_on_resume)

            dismiss_btn = ipw.Button(
                description="Dismiss",
                button_style="",
                icon="times",
                layout=ipw.Layout(width="90px"),
            )

            def _on_dismiss(b, jid=job_id):
                sync_registry.dismiss_job(jid, self.registry_path)
                self.render_jobs()
                if self.on_change:
                    self.on_change()

            dismiss_btn.on_click(_on_dismiss)

            btn_box.children = [resume_btn, dismiss_btn]

        card = ipw.VBox(
            [header_html, details_html, btn_box, card_status],
            layout=ipw.Layout(
                border="1px solid #e5e7eb",
                padding="12px",
                margin="0 0 10px 0",
            ),
        )
        return card


class SynchronisationMainWidget(ipw.VBox):
    def __init__(
        self, openbis_session, registry_path: Path = sync_registry.DEFAULT_REGISTRY_PATH
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.registry_path = Path(registry_path)

        self.setup_widget = SetupSyncWidget(
            openbis_session=self.openbis_session,
            registry_path=self.registry_path,
            on_job_started=self._on_job_started,
        )
        self.active_widget = ActiveSyncsWidget(
            registry_path=self.registry_path,
            on_change=self._on_active_changed,
        )

        self.tabs = ipw.Tab(
            children=[self.setup_widget, self.active_widget],
            layout=ipw.Layout(width="auto"),
        )
        self.tabs.set_title(0, "Setup Synchronisation")
        self.tabs.set_title(1, "Active Synchronisations")

        self.children = [self.tabs]

    def _on_job_started(self, job_id: str):
        self.active_widget.render_jobs()
        self.tabs.selected_index = 1

    def _on_active_changed(self):
        if self.setup_widget.current_owner:
            self.setup_widget.check_conflict(
                self.setup_widget.current_owner,
                self.setup_widget.afs_dropdown.value,
                self.setup_widget.local_input.value,
            )
