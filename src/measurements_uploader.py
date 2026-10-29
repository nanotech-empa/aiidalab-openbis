from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os
import argparse
from pybis import Openbis
import pathlib

import sys

sys.path.insert(0, "/home/jovyan/apps/aiidalab-openbis/")
from src import utils
from nanonis_importer.nanonis_importer import process_measurement_files

import logging

logger = logging.getLogger(__name__)
app_folder = pathlib.Path(__file__).resolve().parent.parent
MEASUREMENT_LOGS_FOLDER = app_folder / "logs" / "measurements"
(app_folder / "logs").mkdir(parents=True, exist_ok=True)
MEASUREMENT_LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=app_folder / "logs" / "aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def get_measurement_log_filepath(
    measurement_session_id, logs_dir=MEASUREMENT_LOGS_FOLDER
):
    logs_path = pathlib.Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)
    return str(logs_path / f"{measurement_session_id}.json")


def init_or_load_measurement_log(
    openbis_url,
    openbis_token,
    measurement_session_id,
    data_folder,
    logs_dir=MEASUREMENT_LOGS_FOLDER,
):
    logging_filepath = get_measurement_log_filepath(
        measurement_session_id, logs_dir=logs_dir
    )
    norm_data_folder = os.path.normpath(data_folder)
    if os.path.exists(logging_filepath):
        logging_data = utils.read_json(logging_filepath)
        logging_data["eln_url"] = openbis_url
        logging_data["eln_token"] = openbis_token
        logging_data["measurement_session_id"] = measurement_session_id
        logging_data["data_folder"] = norm_data_folder
        logging_data.setdefault("processed_files", [])
        utils.write_json(logging_data, logging_filepath)
    else:
        logging_data = {
            "eln_url": openbis_url,
            "eln_token": openbis_token,
            "measurement_session_id": measurement_session_id,
            "data_folder": norm_data_folder,
            "processed_files": [],
        }
        utils.write_json(logging_data, logging_filepath)
    return logging_filepath, logging_data


IGNORED_SUFFIXES = (".json", ".ini", ".part", ".openbis-drive-part", ".tmp")


def is_ignored_file(file_path):
    filename = os.path.basename(file_path)
    return filename.startswith(".") or filename.endswith(IGNORED_SUFFIXES)


def wait_for_file_ready(file_path, timeout=10.0, poll_interval=0.2):
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        try:
            if not os.path.isfile(file_path):
                return False
            current_size = os.path.getsize(file_path)
        except OSError:
            return False
        if current_size > 0 and current_size == last_size:
            return True
        last_size = current_size
        time.sleep(poll_interval)
    return os.path.isfile(file_path)


def get_candidate_files(data_folder, uploaded_files=None):
    uploaded_set = set(uploaded_files or [])
    candidates = []
    for f in os.listdir(data_folder):
        full_path = os.path.join(data_folder, f)
        if not os.path.isfile(full_path) or is_ignored_file(full_path):
            continue
        if full_path in uploaded_set or wait_for_file_ready(full_path):
            candidates.append(full_path)
    return candidates


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, custom_function):
        self.custom_function = custom_function

    def on_created(self, event):
        if not event.is_directory and not is_ignored_file(event.src_path):
            if wait_for_file_ready(event.src_path):
                print(f"New file detected: {event.src_path}")
                self.custom_function(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and not is_ignored_file(event.dest_path):
            if wait_for_file_ready(event.dest_path):
                print(f"New file detected: {event.dest_path}")
                self.custom_function(event.dest_path)


def monitor_folder(path_to_watch, custom_function):
    event_handler = NewFileHandler(custom_function)
    observer = Observer()
    observer.schedule(event_handler, path=path_to_watch, recursive=False)
    observer.start()
    print(f"Started monitoring {path_to_watch}...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


# Example of a custom function
def process_new_file(
    file_path,
    openbis_session,
    openbis_url,
    openbis_token,
    measurement_session_id,
    logging_filepath,
):
    if is_ignored_file(file_path) or not wait_for_file_ready(file_path):
        return

    data_folder = os.path.dirname(file_path)
    initial_logging_data = (
        utils.read_json(logging_filepath) if os.path.exists(logging_filepath) else {}
    )
    candidate_files = get_candidate_files(
        data_folder, initial_logging_data.get("processed_files", [])
    )

    process_measurement_files(
        openbis_url,
        openbis_token,
        data_folder,
        measurement_session_id,
        logging_filepath,
    )

    logging_data = utils.read_json(logging_filepath)

    uploaded_files = logging_data.get("processed_files", [])

    # Determine which files from the pre-processing snapshot still need uploading
    missing_files = [
        f
        for f in candidate_files
        if f not in uploaded_files and os.path.isfile(f) and not is_ignored_file(f)
    ]

    # Upload missing files as attachments (At the moment the gallery view cannot handle ATTACHEMENTs. So lets not upload them.)
    for file_path in missing_files:
        measurement_session_obj = openbis_session.get_object(measurement_session_id)

        utils.create_openbis_dataset(
            openbis_session,
            type="ATTACHMENT",
            sample=measurement_session_obj,
            files=[file_path],
        )

        logging_data["processed_files"].append(file_path)
        utils.write_json(logging_data, logging_filepath)
        logger.info(f"Uploaded file: {file_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Setup the openBIS database (create objects types, collections, etc.)."
    )

    # Define the arguments with flags
    parser.add_argument(
        "-url", "--openbis_url", type=str, help="OpenBIS URL", default=""
    )
    parser.add_argument(
        "-token", "--openbis_token", type=str, help="OpenBIS Token", default=""
    )
    parser.add_argument(
        "-meas_sess",
        "--measurement_session_id",
        type=str,
        help="Measurement Session ID",
        default="",
    )
    parser.add_argument(
        "-data",
        "--data_folder",
        type=str,
        help="Folder with measurement data to be processed",
        default="",
    )

    args = parser.parse_args()

    openbis_url = args.openbis_url
    openbis_token = args.openbis_token
    measurement_session_id = args.measurement_session_id
    data_folder = os.path.normpath(args.data_folder)

    logging_filepath, logging_data = init_or_load_measurement_log(
        openbis_url, openbis_token, measurement_session_id, data_folder
    )

    try:
        openbis_session = Openbis(openbis_url, verify_certificates=False)
        openbis_session.set_token(openbis_token)
    except ValueError:
        print("Session is no longer valid. Please check if the token is still valid.")
        openbis_session = None
        session_data = {}

    if openbis_session:

        def custom_function(file_path):
            return process_new_file(
                file_path,
                openbis_session=openbis_session,
                openbis_url=openbis_url,
                openbis_token=openbis_token,
                measurement_session_id=measurement_session_id,
                logging_filepath=logging_filepath,
            )

        candidate_files = get_candidate_files(
            data_folder, logging_data.get("processed_files", [])
        )

        process_measurement_files(
            openbis_url,
            openbis_token,
            data_folder,
            measurement_session_id,
            logging_filepath,
        )

        logging_data = utils.read_json(logging_filepath)

        uploaded_files = logging_data.get("processed_files", [])

        # Determine which files from the pre-processing snapshot still need uploading
        missing_files = [
            f
            for f in candidate_files
            if f not in uploaded_files and os.path.isfile(f) and not is_ignored_file(f)
        ]

        # Upload missing files as attachments (At the moment the gallery view cannot handle ATTACHEMENTs. So lets not upload them.)
        for file_path in missing_files:
            measurement_session_obj = openbis_session.get_object(measurement_session_id)

            utils.create_openbis_dataset(
                openbis_session,
                type="ATTACHMENT",
                sample=measurement_session_obj,
                files=[file_path],
            )

            logging_data["processed_files"].append(file_path)
            utils.write_json(logging_data, logging_filepath)
            logger.info(f"Uploaded file: {file_path}")

        monitor_folder(data_folder, custom_function)
