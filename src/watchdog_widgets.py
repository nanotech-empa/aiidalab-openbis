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

from . import utils, widgets

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

        self.notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Monitoring the Measurement Uploader
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <div style="font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 8px;">
                        Directories being monitored (Management):
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5;">
                        <li style="margin-bottom: 6px;"><b>Running watchdogs:</b> Displays a list of all folder directories currently being actively monitored.</li>
                        <li><b>Stop monitoring (🚫):</b> To turn off a watchdog, select the target directory from the list and click this button.</li>
                    </ul>
                </div>
            </details>
            """
        )

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.running_watchdogs_title = ipw.HTML(
            value=f"<div style='{header_style}'>Running watchdogs</div>"
        )

        self.running_watchdogs_widget = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px")
        )
        self.refresh_watchdog_list()

        self.stop_watchdog_button = ipw.Button(
            icon="ban",
            tooltip="Stop watchdog",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.stop_watchdog_button.on_click(self.stop_watchdog)

        self.children = [
            self.notes,
            self.running_watchdogs_title,
            self.running_watchdogs_widget,
            self.stop_watchdog_button,
        ]

    def _active_watchdogs_file(self):
        logs_root = getattr(self, "logs_folder", None) or LOGS_FOLDER
        return pathlib.Path(logs_root) / "active_watchdogs.json"

    def refresh_watchdog_list(self):
        json_file = self._active_watchdogs_file()

        folder_options = []
        valid_entries = []  # We will store only the alive processes here
        file_needs_update = False  # Flag to track if we need to rewrite the JSON

        try:
            with open(json_file, "r") as f:
                data = json.load(f)

            if isinstance(data, list):
                for entry in data:
                    folder = entry.get("monitored_folder", "Unknown Folder")
                    pid = entry.get("pid")

                    if pid is not None:
                        # Check if the process is actually running (reaping any exited child zombies first)
                        is_running = False
                        reaped = False
                        if hasattr(os, "waitpid") and hasattr(os, "WNOHANG"):
                            try:
                                waited_pid, _ = os.waitpid(pid, os.WNOHANG)
                                if waited_pid == pid:
                                    reaped = True
                                    file_needs_update = True
                            except ChildProcessError:
                                pass

                        if not reaped:
                            try:
                                # Sending signal 0 checks for existence without killing it
                                os.kill(pid, 0)
                                is_running = True
                            except ProcessLookupError:
                                # The process is dead
                                is_running = False
                                file_needs_update = True
                            except PermissionError:
                                # The process exists, but is owned by another user (rare here, but means it's alive)
                                is_running = True

                        if is_running:
                            # It's alive! Add it to the widget and our valid list
                            folder_options.append((folder, pid))
                            valid_entries.append(entry)
                        else:
                            logger.info(
                                f"PID {pid} for {folder} is dead. Removing from logs."
                            )

            # If we found any dead processes, rewrite the JSON file to clean it up
            if file_needs_update:
                with open(json_file, "w") as f:
                    json.dump(valid_entries, f, indent=4)

        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Update the widget with only the actively running folders
        self.running_watchdogs_widget.options = folder_options

    def get_active_watchdogs_for_folder(self, data_folder):
        self.refresh_watchdog_list()
        norm_target = os.path.normpath(data_folder)
        json_file = self._active_watchdogs_file()
        matches = []
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

        if isinstance(data, list):
            for entry in data:
                folder = entry.get("monitored_folder")
                pid = entry.get("pid")
                if (
                    folder
                    and pid is not None
                    and os.path.normpath(folder) == norm_target
                ):
                    matches.append(entry)
        return matches

    def stop_watchdog_pids(self, pids, notify=True):
        target_pids = list(pids)
        if not target_pids:
            return []

        pid_set = set(target_pids)
        for pid in target_pids:
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Terminating watchdog process with PID: {pid}")
            except ProcessLookupError:
                logger.warning(
                    f"Process {pid} not found. It may have already exited."
                )

        if notify:
            display(Javascript(data="alert('Watchdog(s) stopped.')"))

        self.running_watchdogs_widget.options = [
            (directory, pid)
            for directory, pid in self.running_watchdogs_widget.options
            if pid not in pid_set
        ]

        json_file = self._active_watchdogs_file()
        try:
            with open(json_file, "r") as f:
                data = json.load(f)

            updated_data = (
                [entry for entry in data if entry.get("pid") not in pid_set]
                if isinstance(data, list)
                else []
            )
            with open(json_file, "w") as f:
                json.dump(updated_data, f, indent=4)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.error(f"Could not read {json_file} to clean up PIDs.")

        return target_pids

    def add_active_watchdog(self, pid, data_folder, measurement_session_id):
        norm_data_folder = os.path.normpath(data_folder)
        json_file = self._active_watchdogs_file()
        json_file.parent.mkdir(parents=True, exist_ok=True)
        data = []
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        data.append(
            {
                "pid": pid,
                "monitored_folder": norm_data_folder,
                "measurement_session_id": measurement_session_id,
            }
        )
        with open(json_file, "w") as f:
            json.dump(data, f, indent=4)

        self.running_watchdogs_widget.options += ((norm_data_folder, pid),)

    def stop_watchdog(self, b):
        selected_pids = self.running_watchdogs_widget.value

        if selected_pids:
            self.stop_watchdog_pids(selected_pids, notify=True)
        else:
            display(Javascript(data="alert('Select at least one directory.')"))
            logger.info("No directory selected.")


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
            "processed_files": [],
        }
        utils.write_json(logging_data, str(log_filepath))
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
        logging_data.setdefault("processed_files", [])
        utils.write_json(logging_data, str(log_filepath))
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

    def _start_watchdog_process(self, measurement_session_id, data_folder):
        norm_data_folder = os.path.normpath(data_folder)
        watchdog_process = subprocess.Popen(
            [
                "python",
                f"{APP_FOLDER}/src/measurements_uploader.py",
                "--openbis_url",
                self.session_data["url"],
                "--openbis_token",
                self.session_data["token"],
                "--measurement_session_id",
                measurement_session_id,
                "--data_folder",
                norm_data_folder,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        display(Javascript(data="alert('Watchdog process started!');"))
        logger.info(
            f"Watchdog process started with PID: {watchdog_process.pid} for {norm_data_folder}"
        )

        self.running_watchdogs_widget.add_active_watchdog(
            watchdog_process.pid, norm_data_folder, measurement_session_id
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
                self._start_watchdog_process(
                    measurement_session.permId, norm_data_folder
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
                    active_pids, notify=False
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

            detach_measurement_logs_for_folder(
                norm_data_folder,
                replaced_by_session_id=new_session.permId,
                logs_dir=logs_dir,
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
