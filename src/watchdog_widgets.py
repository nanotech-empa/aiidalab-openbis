import os
import ipywidgets as ipw
import signal
from IPython.display import display, Javascript
from . import utils, widgets
import ipyfilechooser
import subprocess
import logging
import json

INTERFACE_CONFIG_INFO = utils.get_interface_config_info()
OPENBIS_OBJECT_TYPES, _ = (
    INTERFACE_CONFIG_INFO["object_types"],
    INTERFACE_CONFIG_INFO["object_types_codes"],
)

if not os.path.exists("logs"):
    os.mkdir("logs")

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class RunningMeasurementWatchdogsWidget(ipw.VBox):
    def __init__(self, openbis_session, session_data):
        super().__init__()
        self.openbis_session = openbis_session
        self.session_data = session_data

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

    def refresh_watchdog_list(self):
        json_file = "logs/active_watchdogs.json"

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
                        # Check if the process is actually running
                        is_running = False
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
                            logging.info(
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

    def stop_watchdog(self, b):
        selected_pids = self.running_watchdogs_widget.value

        if selected_pids:
            # 1. Kill the actual processes safely
            for pid in selected_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    logging.info(f"Terminating watchdog process with PID: {pid}")
                except ProcessLookupError:
                    # The process might have already died/crashed on its own
                    logging.warning(
                        f"Process {pid} not found. It may have already exited."
                    )

            display(Javascript(data="alert('Watchdog(s) stopped.')"))

            # 2. Remove them from the widget UI
            self.running_watchdogs_widget.options = [
                (directory, pid)
                for directory, pid in self.running_watchdogs_widget.options
                if pid not in selected_pids
            ]

            # 3. Remove them from the JSON log file
            json_file = "logs/active_watchdogs.json"
            try:
                # Read the current file
                with open(json_file, "r") as f:
                    data = json.load(f)

                # Filter out the dictionaries whose 'pid' is in selected_pids
                if isinstance(data, list):
                    updated_data = [
                        entry for entry in data if entry.get("pid") not in selected_pids
                    ]

                # Write the clean list back to the file
                with open(json_file, "w") as f:
                    json.dump(updated_data, f, indent=4)

            except (FileNotFoundError, json.JSONDecodeError):
                logging.error(f"Could not read {json_file} to clean up PIDs.")

        else:
            display(Javascript(data="alert('Select at least one directory.')"))
            logging.info("No directory selected.")


class GenerateMeasurementsWatchdogWidget(ipw.VBox):
    def __init__(self, openbis_session, session_data, running_watchdogs_widget):
        super().__init__()
        self.openbis_session = openbis_session
        self.session_data = session_data
        self.running_watchdogs_widget = running_watchdogs_widget
        self.watchdog_processes = []

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
        self.select_experiment_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select experiment</div>"
        )
        self.select_experiment_widget = widgets.SelectExperimentWidget(
            self.openbis_session
        )

        self.select_sample_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select sample</div>"
        )
        self.select_sample_widget = widgets.SelectSampleWidget(self.openbis_session)
        self.select_sample_widget.sample_dropdown.observe(
            self._on_sample_changed, names="value"
        )

        self.select_instrument_title = ipw.HTML(
            value=f"<div style='{header_style}'>Select instrument</div>"
        )
        self.select_instrument_widget = widgets.SelectInstrumentWidget(
            self.openbis_session
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

        self.children = [
            self.notes,
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
        ]

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

        most_recent_parent = self._get_most_recent_process_step(sample_object)

        # 1. Early exit if no parent is found
        if not most_recent_parent:
            return

        # 2. Check if the experiment actually needs changing
        new_exp_id = most_recent_parent.experiment.permId
        current_exp_id = self.select_experiment_widget.experiment_dropdown.value

        if new_exp_id == current_exp_id:
            return  # Early exit if they are already the same

        # 3. Apply the updates
        self.select_experiment_widget.experiment_dropdown.value = new_exp_id

        sample_name = sample_object.props["name"]
        self.measurement_session_name_text.value = f"Meas_{sample_name}"

        display(
            Javascript(
                data="alert('Experiment was auto-updated based on the sample!');"
            )
        )

        # 4. Better logging: Actually log *what* happened
        logging.info(
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

    def _get_or_create_measurement_session(
        self, sample_id, instrument_id, experiment_id, data_folder
    ):
        """Creates an openBIS session object or retrieves an existing one from logging.json."""
        logging_filepath = os.path.join(data_folder, "logging.json")

        # 1. Try to load an existing session (EAFP Approach)
        try:
            logging_data = utils.read_json(logging_filepath)
            session_id = logging_data.get("measurement_session_id")

            # Verify we actually got a valid ID from the JSON
            if session_id:
                measurement_session = utils.get_openbis_object(
                    self.openbis_session, sample_ident=session_id
                )
                logging.info(
                    f"Uploading data into existing Measurement Session {measurement_session.permId}."
                )
                return measurement_session

        except (FileNotFoundError, ValueError):
            # File doesn't exist, or JSON is invalid. Move on to creation.
            pass

        # 2. Create a new session if no valid existing one was found
        measurement_session = utils.create_openbis_object(
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Measurement Session"],
            collection=experiment_id,
            parents=[sample_id, instrument_id],
            props={
                "name": self.measurement_session_name_text.value,
                "default_object_view": "IMAGING_GALLERY_VIEW",
                "measurement_folder_path": data_folder,
            },
        )

        logging.info(f"New Measurement Session {measurement_session.permId} created.")
        return measurement_session

    def generate_watchdog(self, b):
        # 1. Block saving if inputs (or the folder chooser) aren't ready
        if not self._validate_inputs():
            return

        # 2. Gather verified data
        sample_id = self.select_sample_widget.sample_dropdown.value
        experiment_id = self.select_experiment_widget.experiment_dropdown.value
        instrument_id = self.select_instrument_widget.instrument_dropdown.value
        data_folder = self.select_measurements_folder_widget.selected_path

        # Check if the folder is already being monitored
        current_options = self.running_watchdogs_widget.running_watchdogs_widget.options
        if any(folder == data_folder for folder, pid in current_options):
            display(
                Javascript(data="alert('This directory is already being monitored!');")
            )
            return

        # 3. Handle openBIS connection
        measurement_session = self._get_or_create_measurement_session(
            sample_id,
            instrument_id,
            experiment_id,
            data_folder,
        )

        # 4. Start Subprocess
        watchdog_process = subprocess.Popen(
            [
                "python",
                "src/measurements_uploader.py",
                "--openbis_url",
                self.session_data["url"],
                "--openbis_token",
                self.session_data["token"],
                "--measurement_session_id",
                measurement_session.permId,
                "--data_folder",
                data_folder,
            ],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        display(Javascript(data="alert('Watchdog process started!');"))
        logging.info(
            f"Watchdog process started with PID: {watchdog_process.pid} for {data_folder}"
        )

        # 5. Update the JSON log file
        json_file = "logs/active_watchdogs.json"
        data = []
        try:
            with open(json_file, "r") as f:
                data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        data.append({"pid": watchdog_process.pid, "monitored_folder": data_folder})

        with open(json_file, "w") as f:
            json.dump(data, f, indent=4)

        # 6. Update UI Watchdog List (Pythonic Tuple Concatenation)
        self.watchdog_processes.append(watchdog_process)
        self.running_watchdogs_widget.running_watchdogs_widget.options += (
            (data_folder, watchdog_process.pid),
        )

    def cleanup_watchdog(self):
        if self.watchdog_processes:
            for process in self.watchdog_processes:
                logging.info(f"Terminating watchdog process with PID: {process.pid}")
                process.terminate()
            self.watchdog_processes = []
