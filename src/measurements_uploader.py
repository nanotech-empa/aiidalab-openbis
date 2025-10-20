from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
import os
import argparse
from pybis import Openbis
import sys

sys.path.append("/home/jovyan/apps/aiida-openbis/")
from src import utils
from nanonis_importer.nanonis_importer import process_measurement_files


class NewFileHandler(FileSystemEventHandler):
    def __init__(self, custom_function):
        self.custom_function = custom_function

    def on_created(self, event):
        if not event.is_directory:
            print(f"New file detected: {event.src_path}")
            self.custom_function(event.src_path)


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
    file_path, openbis_url, openbis_token, measurement_session_id, logging_filepath
):
    data_folder = os.path.dirname(file_path)
    process_measurement_files(
        openbis_url,
        openbis_token,
        data_folder,
        measurement_session_id,
        logging_filepath,
    )


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
    data_folder = args.data_folder

    logging_filepath = f"{data_folder}/logging.json"
    if os.path.exists(logging_filepath):
        logging_data = utils.read_json(logging_filepath)
    else:
        logging_data = {
            "eln_url": openbis_url,
            "eln_token": openbis_token,
            "measurement_session_id": measurement_session_id,
            "processed_files": [],
        }
        utils.write_json(logging_data, logging_filepath)

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
                openbis_url=openbis_url,
                openbis_token=openbis_token,
                measurement_session_id=measurement_session_id,
                logging_filepath=logging_filepath,
            )

        process_measurement_files(
            openbis_url,
            openbis_token,
            data_folder,
            measurement_session_id,
            logging_filepath,
        )

        monitor_folder(data_folder, custom_function)
