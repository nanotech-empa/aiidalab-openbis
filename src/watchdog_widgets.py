import os
import ipywidgets as ipw
import signal
from IPython.display import display, Javascript
from . import utils, widgets
import ipyfilechooser
import atexit
import subprocess
import logging

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

    def stop_watchdog(self, b):
        selected_pids = self.running_watchdogs_widget.value

        if selected_pids:
            for pid in selected_pids:
                os.kill(pid, signal.SIGTERM)
                logging.info(f"Terminating watchdog process with PID: {pid}")
                display(Javascript(data="alert('Watchdog stopped.')"))

            self.running_watchdogs_widget.options = [
                (directory, pid)
                for directory, pid in self.running_watchdogs_widget.options
                if pid not in selected_pids
            ]

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

        # Ensure process is killed on notebook shutdown / kernel restart
        atexit.register(self.cleanup_watchdog)

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

        if most_recent_parent:
            experiment_id = self.select_experiment_widget.experiment_dropdown.value
            if most_recent_parent.experiment.permId != experiment_id:
                self.select_experiment_widget.experiment_dropdown.value = (
                    most_recent_parent.experiment.permId
                )
                self.measurement_session_name_text.value = (
                    f"Meas_{sample_object.props['name']}"
                )
                display(
                    Javascript(
                        data="alert('Experiment was auto-updated based on the sample!');"
                    )
                )
                logging.info("Experiment was changed.")

    def _validate_inputs(self):
        """Checks all UI components before allowing a save. Returns True if valid."""
        if self.select_experiment_widget.experiment_dropdown.value == "-1":
            display(Javascript(data="alert('Please select an experiment.');"))
            return False
        if self.select_sample_widget.sample_dropdown.value == "-1":
            display(Javascript(data="alert('Please select a sample.');"))
            return False
        if self.select_instrument_widget.instrument_dropdown.value == "-1":
            display(Javascript(data="alert('Please select an instrument.');"))
            return False

        try:
            is_selecting = (
                self.select_measurements_folder_widget._cancel.layout.display is None
            )
        except AttributeError:
            is_selecting = (
                False  # Fallback if ipyfilechooser updates its internal variables later
            )

        if is_selecting:
            display(
                Javascript(
                    data="alert('You are still editing the directory! Please confirm it by clicking \"Change\" in the folder chooser.');"
                )
            )
            return False

        if not self.select_measurements_folder_widget.selected_path:
            display(Javascript(data="alert('Please select a valid directory.');"))
            return False

        return True

    def _get_or_create_measurement_session(
        self, sample_id, sample_name, instrument_id, experiment_id, data_folder
    ):
        """Creates an openBIS session object or retrieves an existing one from logging.json."""
        logging_filepath = os.path.join(data_folder, "logging.json")

        if os.path.exists(logging_filepath):
            logging_data = utils.read_json(logging_filepath)
            session_id = logging_data.get("measurement_session_id", "")
            measurement_session = utils.get_openbis_object(
                self.openbis_session, sample_ident=session_id
            )
            logging.info(
                f"Uploading data into existing Measurement Session {measurement_session.permId}."
            )
            return measurement_session

        measurement_session_name = self.measurement_session_name_text.value

        measurement_session = utils.create_openbis_object(
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Measurement Session"],
            collection=experiment_id,
            parents=[sample_id, instrument_id],
            props={
                "name": measurement_session_name,
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
        sample_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=sample_id
        )
        experiment_id = self.select_experiment_widget.experiment_dropdown.value
        instrument_id = self.select_instrument_widget.instrument_dropdown.value
        data_folder = self.select_measurements_folder_widget.selected_path

        # 3. Handle openBIS connection
        measurement_session = self._get_or_create_measurement_session(
            sample_id,
            sample_object.props["name"],
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
            ]
        )

        display(Javascript(data="alert('Watchdog process started!');"))
        logging.info(f"Watchdog process started with PID: {watchdog_process.pid}")

        # 5. Update UI Watchdog List
        self.watchdog_processes.append(watchdog_process)
        running_list = list(
            self.running_watchdogs_widget.running_watchdogs_widget.options
        )
        running_list.append((data_folder, watchdog_process.pid))
        self.running_watchdogs_widget.running_watchdogs_widget.options = tuple(
            running_list
        )

    def cleanup_watchdog(self):
        if self.watchdog_processes:
            for process in self.watchdog_processes:
                logging.info(f"Terminating watchdog process with PID: {process.pid}")
                process.terminate()
            self.watchdog_processes = []


# class GenerateMeasurementsWatchdogWidget(ipw.VBox):
#     def __init__(self, openbis_session, session_data, running_watchdogs_widget):
#         super().__init__()
#         self.openbis_session = openbis_session
#         self.session_data = session_data
#         self.running_watchdogs_widget = running_watchdogs_widget

#         self.notes = ipw.HTML(
#             value="""
#             <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
#                 <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
#                     💡 Understanding the Measurement Uploader
#                 </summary>

#                 <div style="margin-top: 12px; cursor: default;">
#                     <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
#                         <li><span style="color: #2980b9; font-weight: bold;">Watchdogs</span> run in the background to automatically detect and upload new measurement files.</li>
#                         <li><span style="color: #27ae60; font-weight: bold;">Measurements</span> are securely linked to the specific experiment, sample, and instrument you configure.</li>
#                     </ul>

#                     <div style="font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 8px;">
#                         Start directory monitoring (Setup):
#                     </div>

#                     <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
#                         <li style="margin-bottom: 6px;">
#                             <b>Select experiment:</b> Determines where the measurement data will be saved in openBIS.
#                             <i>(Note: If the experiment does not exist, you can create one by clicking the <b>+</b> button, selecting a project, and giving it a name).</i>
#                         </li>
#                         <li style="margin-bottom: 6px;"><b>Select sample:</b> Choose the specific sample that is being measured.</li>
#                         <li style="margin-bottom: 6px;"><b>Select instrument:</b> Specify the device used to acquire the data.</li>
#                         <li style="margin-bottom: 6px;"><b>Select measurements directory:</b> Define the local folder where the instrument saves its files.</li>
#                         <li><b>Save (💾):</b> Locks in your configuration and starts a watchdog to monitor the selected directory.</li>
#                     </ul>
#                 </div>
#             </details>
#             """
#         )

#         header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

#         self.select_experiment_title = ipw.HTML(
#             value=f"<div style='{header_style}'>Select experiment</div>"
#         )

#         self.select_experiment_widget = widgets.SelectExperimentWidget(
#             self.openbis_session
#         )

#         self.select_sample_title = ipw.HTML(
#             value=f"<div style='{header_style}'>Select sample</div>"
#         )

#         self.select_sample_widget = widgets.SelectSampleWidget(self.openbis_session)

#         self.select_instrument_title = ipw.HTML(
#             value=f"<div style='{header_style}'>Select instrument</div>"
#         )

#         self.select_instrument_widget = widgets.SelectInstrumentWidget(
#             self.openbis_session
#         )

#         self.select_measurements_folder_title = ipw.HTML(
#             value=f"<div style='{header_style}'>Select measurements directory</div>"
#         )

#         self.select_measurements_folder_widget = ipyfilechooser.FileChooser(
#             path="/home/jovyan/", select_default=True, use_dir_icons=True, show_only_dirs=True
#         )

#         self.generate_watchdog_button = ipw.Button(
#             description="",
#             disabled=False,
#             button_style="",
#             tooltip="Save",
#             icon="save",
#             layout=ipw.Layout(width="100px", height="50px"),
#         )

#         self.select_sample_widget.sample_dropdown.observe(
#             self.load_sample_data, names="value"
#         )
#         self.generate_watchdog_button.on_click(self.generate_watchdog)

#         self.watchdog_processes = []

#         # Ensure process is killed on notebook shutdown / kernel restart
#         atexit.register(self.cleanup_watchdog)

#         self.children = [
#             self.notes,
#             self.select_experiment_title,
#             self.select_experiment_widget,
#             self.select_sample_title,
#             self.select_sample_widget,
#             self.select_instrument_title,
#             self.select_instrument_widget,
#             self.select_measurements_folder_title,
#             self.select_measurements_folder_widget,
#             self.generate_watchdog_button,
#         ]

#     def load_sample_data(self, change):
#         sample_id = self.select_sample_widget.sample_dropdown.value
#         if sample_id == "-1":
#             logging.info("No sample selected.")
#             return

#         sample_object = utils.get_openbis_object(
#             self.openbis_session, sample_ident=sample_id
#         )

#         sample_object_parents = sample_object.parents
#         most_recent_parent = None

#         for parent_id in sample_object_parents:
#             parent_object = utils.get_openbis_object(
#                 self.openbis_session, sample_ident=parent_id
#             )

#             parent_type = parent_object.type
#             if parent_type == OPENBIS_OBJECT_TYPES["Process Step"]:
#                 if most_recent_parent:
#                     if (
#                         parent_object.registrationDate
#                         > most_recent_parent.registrationDate
#                     ):
#                         most_recent_parent = parent_object
#                 else:
#                     most_recent_parent = parent_object

#         if most_recent_parent:
#             experiment_id = self.select_experiment_widget.experiment_dropdown.value
#             if most_recent_parent.experiment.permId != experiment_id:
#                 self.select_experiment_widget.experiment_dropdown.value = (
#                     most_recent_parent.experiment.permId
#                 )
#                 display(Javascript(data="alert('Experiment was changed!')"))
#                 logging.info("Experiment was changed.")

#     def generate_watchdog(self, b):
#         experiment_id = self.select_experiment_widget.experiment_dropdown.value
#         if experiment_id == "-1":
#             logging.info("No experiment selected.")
#             return

#         sample_id = self.select_sample_widget.sample_dropdown.value
#         if sample_id == "-1":
#             logging.info("No sample selected.")
#             return

#         sample_object = utils.get_openbis_object(
#             self.openbis_session, sample_ident=sample_id
#         )
#         sample_name = sample_object.props["name"]

#         instrument_id = self.select_instrument_widget.instrument_dropdown.value
#         if instrument_id == "-1":
#             logging.info("No instrument selected.")
#             return

#         data_folder = self.select_measurements_folder_widget.selected_path
#         logging_filepath = f"{data_folder}/logging.json"
#         if os.path.exists(logging_filepath):
#             logging_data = utils.read_json(logging_filepath)
#             measurement_session_object = utils.get_openbis_object(
#                 self.openbis_session,
#                 sample_ident=logging_data.get("measurement_session_id", ""),
#             )
#             logging.info(
#                 f"Uploading data into Measurement Session {measurement_session_object.permId}."
#             )
#         else:
#             measurement_session_object = utils.create_openbis_object(
#                 self.openbis_session,
#                 type=OPENBIS_OBJECT_TYPES["Measurement Session"],
#                 collection=experiment_id,
#                 parents=[sample_id, instrument_id],
#                 props={
#                     "name": f"Measurement Session on Sample {sample_name}",
#                     "default_object_view": "IMAGING_GALLERY_VIEW",
#                     "measurement_folder_path": self.select_measurements_folder_widget.selected_path,
#                 },
#             )
#             logging.info(
#                 f"Measurement Session {measurement_session_object.permId} created."
#             )

#         measurement_session_id = measurement_session_object.permId
#         measurements_directory = self.select_measurements_folder_widget.selected_path

#         watchdog_process = subprocess.Popen(
#             [
#                 "python",
#                 "src/measurements_uploader.py",
#                 "--openbis_url",
#                 self.session_data["url"],
#                 "--openbis_token",
#                 self.session_data["token"],
#                 "--measurement_session_id",
#                 measurement_session_id,
#                 "--data_folder",
#                 measurements_directory,
#             ]
#         )

#         display(Javascript(data="alert('Watchdog process started!')"))
#         logging.info(f"Watchdog process started with PID: {watchdog_process.pid}")

#         self.watchdog_processes.append(watchdog_process)
#         running_watchdogs = (
#             self.running_watchdogs_widget.running_watchdogs_widget.options
#         )
#         running_watchdogs = list(running_watchdogs)
#         running_watchdogs.append((measurements_directory, watchdog_process.pid))
#         self.running_watchdogs_widget.running_watchdogs_widget.options = (
#             running_watchdogs
#         )

#     def cleanup_watchdog(self):
#         if self.watchdog_processes:
#             for process in self.watchdog_processes:
#                 logging.info(f"Terminating watchdog process with PID: {process.pid}")
#                 process.terminate()
#                 self.watchdog_processes = []
