import os
import ipywidgets as ipw
import signal
from IPython.display import display, Javascript
from . import utils, widgets
import ipyfilechooser
import atexit
import shutil
import subprocess
import logging

OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")

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

        self.running_watchdogs_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Running watchdogs</span>"
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

        self.select_experiment_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select experiment</span>"
        )

        self.select_experiment_widget = widgets.SelectExperimentWidget(
            self.openbis_session
        )

        self.select_sample_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select sample</span>"
        )

        self.select_sample_widget = widgets.SelectSampleWidget(self.openbis_session)

        self.select_instrument_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select instrument</span>"
        )

        self.select_instrument_widget = widgets.SelectInstrumentWidget(
            self.openbis_session
        )

        self.select_measurements_folder_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select measurements directory</span>"
        )

        self.select_measurements_folder_widget = ipyfilechooser.FileChooser(
            path=".", select_default=True, use_dir_icons=True, show_only_dirs=True
        )

        self.generate_watchdog_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.select_sample_widget.sample_dropdown.observe(
            self.load_sample_data, names="value"
        )
        self.generate_watchdog_button.on_click(self.generate_watchdog)

        self.watchdog_processes = []

        # Ensure process is killed on notebook shutdown / kernel restart
        atexit.register(self.cleanup_watchdog)

        self.children = [
            self.select_experiment_title,
            self.select_experiment_widget,
            self.select_sample_title,
            self.select_sample_widget,
            self.select_instrument_title,
            self.select_instrument_widget,
            self.select_measurements_folder_title,
            self.select_measurements_folder_widget,
            self.generate_watchdog_button,
        ]

    def load_sample_data(self, change):
        sample_id = self.select_sample_widget.sample_dropdown.value
        if sample_id == "-1":
            logging.info("No sample selected.")
            return

        sample_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=sample_id
        )

        sample_object_parents = sample_object.parents
        most_recent_parent = None

        for parent_id in sample_object_parents:
            parent_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=parent_id
            )

            parent_type = parent_object.type
            if parent_type == OPENBIS_OBJECT_TYPES["Process Step"]:
                if most_recent_parent:
                    if (
                        parent_object.registrationDate
                        > most_recent_parent.registrationDate
                    ):
                        most_recent_parent = parent_object
                else:
                    most_recent_parent = parent_object

        if most_recent_parent:
            experiment_id = self.select_experiment_widget.experiment_dropdown.value
            if most_recent_parent.experiment.permId != experiment_id:
                self.select_experiment_widget.experiment_dropdown.value = (
                    most_recent_parent.experiment.permId
                )
                display(Javascript(data="alert('Experiment was changed!')"))
                logging.info("Experiment was changed.")

    def generate_watchdog(self, b):
        experiment_id = self.select_experiment_widget.experiment_dropdown.value
        if experiment_id == "-1":
            logging.info("No experiment selected.")
            return

        sample_id = self.select_sample_widget.sample_dropdown.value
        if sample_id == "-1":
            logging.info("No sample selected.")
            return

        sample_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=sample_id
        )
        sample_name = sample_object.props["name"]

        instrument_id = self.select_instrument_widget.instrument_dropdown.value
        if instrument_id == "-1":
            logging.info("No instrument selected.")
            return

        measurement_session_object = utils.create_openbis_object(
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Measurement Session"],
            collection=experiment_id,
            parents=[sample_id, instrument_id],
            props={
                "name": f"Measurement Session on Sample {sample_name}",
                "default_object_view": "IMAGING_GALLERY_VIEW",
                "measurement_folder_path": self.select_measurements_folder_widget.selected_path,
            },
        )
        logging.info(
            f"Measurement Session {measurement_session_object.permId} created."
        )

        measurement_session_id = measurement_session_object.permId
        measurements_directory = self.select_measurements_folder_widget.selected_path
        watchdog_file = "src/measurements_uploader.py"
        shutil.copy(watchdog_file, measurements_directory)

        watchdog_process = subprocess.Popen(
            [
                "python",
                f"{measurements_directory}/measurements_uploader.py",
                "--openbis_url",
                self.session_data["url"],
                "--openbis_token",
                self.session_data["token"],
                "--measurement_session_id",
                measurement_session_id,
                "--data_folder",
                measurements_directory,
            ]
        )

        display(Javascript(data="alert('Watchdog process started!')"))
        logging.info(f"Watchdog process started with PID: {watchdog_process.pid}")

        self.watchdog_processes.append(watchdog_process)
        running_watchdogs = (
            self.running_watchdogs_widget.running_watchdogs_widget.options
        )
        running_watchdogs = list(running_watchdogs)
        running_watchdogs.append((measurements_directory, watchdog_process.pid))
        self.running_watchdogs_widget.running_watchdogs_widget.options = (
            running_watchdogs
        )

    def cleanup_watchdog(self):
        if self.watchdog_processes:
            for process in self.watchdog_processes:
                logging.info(f"Terminating watchdog process with PID: {process.pid}")
                process.terminate()
                self.watchdog_processes = []
