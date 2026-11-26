import argparse
import logging
import os
import pathlib
import signal
import sys
import threading
import time

from pybis import Openbis
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

app_folder = pathlib.Path(__file__).resolve().parent.parent
if str(app_folder) not in sys.path:
    sys.path.insert(0, str(app_folder))

from nanonis_importer.nanonis_importer import process_measurement_files
from src import measurement_monitor, utils

logger = logging.getLogger(__name__)
MEASUREMENT_LOGS_FOLDER = app_folder / "logs" / "measurements"
(app_folder / "logs").mkdir(parents=True, exist_ok=True)
MEASUREMENT_LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=app_folder / "logs" / "aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class TokenExpiredError(RuntimeError):
    """Raised when the openBIS session token is invalid or expired."""


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
    now_iso = measurement_monitor.utc_now_iso()

    def _init(logging_data):
        logging_data["eln_url"] = openbis_url
        logging_data["eln_token"] = openbis_token
        logging_data["measurement_session_id"] = measurement_session_id
        logging_data["data_folder"] = norm_data_folder
        logging_data.setdefault("processed_files", [])
        logging_data.setdefault("upload_history", [])
        logging_data.setdefault("recent_errors", [])
        logging_data.setdefault("started_at", now_iso)
        logging_data["token_expired"] = False
        logging_data["current_action"] = "Starting up"
        return logging_data

    logging_data = measurement_monitor.update_measurement_log(logging_filepath, _init)
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
    if not os.path.isdir(data_folder):
        return candidates
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
                print(f"New file detected: {event.src_path}", flush=True)
                self.custom_function(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and not is_ignored_file(event.dest_path):
            if wait_for_file_ready(event.dest_path):
                print(f"New file detected: {event.dest_path}", flush=True)
                self.custom_function(event.dest_path)


def monitor_folder(
    path_to_watch,
    custom_function,
    heartbeat_callback=None,
    heartbeat_interval=15.0,
    stop_event=None,
):
    event_handler = NewFileHandler(custom_function)
    observer = Observer()
    observer.schedule(event_handler, path=path_to_watch, recursive=False)
    observer.start()
    print(f"Started monitoring {path_to_watch}...", flush=True)
    last_heartbeat = 0.0
    if heartbeat_callback is not None:
        heartbeat_callback()
        last_heartbeat = time.monotonic()

    try:
        while stop_event is None or not stop_event.is_set():
            time.sleep(1)
            if heartbeat_callback is not None:
                now_mono = time.monotonic()
                if now_mono - last_heartbeat >= heartbeat_interval:
                    heartbeat_callback()
                    last_heartbeat = now_mono
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()


def run_upload_cycle(
    data_folder,
    openbis_session,
    openbis_url,
    openbis_token,
    measurement_session_id,
    logging_filepath,
):
    initial_logging_data = (
        measurement_monitor.read_json_safe(logging_filepath, default={}) or {}
    )
    candidate_files = get_candidate_files(
        data_folder, initial_logging_data.get("processed_files", [])
    )

    measurement_monitor.update_measurement_log(
        logging_filepath,
        lambda d: d.update(
            {
                "current_action": "Scanning & uploading files...",
                "last_heartbeat_at": measurement_monitor.utc_now_iso(),
            }
        ),
    )

    process_measurement_files(
        openbis_url,
        openbis_token,
        data_folder,
        measurement_session_id,
        logging_filepath,
    )

    logging_data = (
        measurement_monitor.read_json_safe(logging_filepath, default={}) or {}
    )
    logging_data.setdefault("processed_files", [])

    if logging_data.get("token_expired"):
        msg = "Stopped — openBIS token invalid or expired"
        logging_data["current_action"] = msg
        measurement_monitor.atomic_write_json(logging_data, logging_filepath)
        print(msg, flush=True)
        raise TokenExpiredError(msg)

    uploaded_files = logging_data.get("processed_files", [])

    # Determine which files from the pre-processing snapshot still need uploading
    missing_files = [
        f
        for f in candidate_files
        if f not in uploaded_files and os.path.isfile(f) and not is_ignored_file(f)
    ]

    for file_path in missing_files:
        basename = os.path.basename(file_path)
        measurement_monitor.update_measurement_log(
            logging_filepath,
            lambda d, name=basename: d.update(
                {
                    "current_action": f"Uploading {name}...",
                    "last_heartbeat_at": measurement_monitor.utc_now_iso(),
                }
            ),
        )
        try:
            measurement_session_obj = openbis_session.get_object(measurement_session_id)
            utils.create_openbis_dataset(
                openbis_session,
                type="ATTACHMENT",
                sample=measurement_session_obj,
                files=[file_path],
            )
        except Exception as exc:
            if is_session_token_expired(openbis_session):
                auth_msg = f"openBIS token expired while uploading {basename}: {exc}"
                logger.error(auth_msg)
                print(auth_msg, flush=True)

                def _mark_expired(d):
                    d["token_expired"] = True
                    d["current_action"] = "Stopped — openBIS token invalid or expired"
                    measurement_monitor.append_error_event(
                        d, auth_msg, stage="auth", file_path=file_path
                    )

                measurement_monitor.update_measurement_log(
                    logging_filepath, _mark_expired
                )
                raise TokenExpiredError(auth_msg) from exc

            err_msg = f"Failed to upload attachment {basename}: {exc}"
            logger.error(err_msg)
            print(err_msg, flush=True)
            measurement_monitor.update_measurement_log(
                logging_filepath,
                lambda d, m=str(exc), fp=file_path: measurement_monitor.append_error_event(
                    d, m, stage="attachment", file_path=fp
                ),
            )
            continue

        def _record_attachment(d, fp=file_path, name=basename):
            d.setdefault("processed_files", [])
            if fp not in d["processed_files"]:
                d["processed_files"].append(fp)
            measurement_monitor.append_upload_event(d, fp, "ATTACHMENT")
            last_err = d.get("last_error")
            if (
                isinstance(last_err, dict)
                and last_err.get("file") == name
                and last_err.get("stage") in ("sxm", "dat")
                and "ATTACHMENT fallback" not in str(last_err.get("message", ""))
            ):
                last_err["message"] = (
                    f"{last_err['message']} (uploaded as raw ATTACHMENT fallback)"
                )
                if isinstance(d.get("recent_errors"), list) and d["recent_errors"]:
                    d["recent_errors"][-1]["message"] = last_err["message"]

        measurement_monitor.update_measurement_log(logging_filepath, _record_attachment)
        logger.info(f"Uploaded file: {file_path}")
        print(f"Uploaded file as ATTACHMENT: {basename}", flush=True)

    measurement_monitor.update_measurement_log(
        logging_filepath,
        lambda d: d.update(
            {
                "current_action": "Watching for new files",
                "last_heartbeat_at": measurement_monitor.utc_now_iso(),
            }
        ),
    )


def process_new_file(
    file_path,
    openbis_session,
    openbis_url,
    openbis_token,
    measurement_session_id,
    logging_filepath,
    stop_event=None,
    token_expired_event=None,
):
    if is_ignored_file(file_path) or not wait_for_file_ready(file_path):
        return

    data_folder = os.path.dirname(file_path)
    try:
        run_upload_cycle(
            data_folder=data_folder,
            openbis_session=openbis_session,
            openbis_url=openbis_url,
            openbis_token=openbis_token,
            measurement_session_id=measurement_session_id,
            logging_filepath=logging_filepath,
        )
    except TokenExpiredError:
        if token_expired_event is not None:
            token_expired_event.set()
        if stop_event is not None:
            stop_event.set()
        else:
            raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Monitor a measurement directory and upload new files to openBIS."
    )
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

    args = parser.parse_args(argv)

    openbis_url = args.openbis_url
    openbis_token = args.openbis_token
    measurement_session_id = args.measurement_session_id
    data_folder = os.path.normpath(args.data_folder)

    logging_filepath, _ = init_or_load_measurement_log(
        openbis_url,
        openbis_token,
        measurement_session_id,
        data_folder,
        logs_dir=MEASUREMENT_LOGS_FOLDER,
    )

    try:
        openbis_session = Openbis(openbis_url, verify_certificates=False)
        openbis_session.set_token(openbis_token)
    except ValueError as exc:
        msg = "Session is no longer valid. Please check if the token is still valid."
        print(msg, flush=True)
        logger.error(f"{msg} ({exc})")

        def _mark_startup_expired(d):
            d["token_expired"] = True
            d["current_action"] = "Stopped — openBIS token invalid or expired"
            measurement_monitor.append_error_event(d, msg, stage="auth")

        measurement_monitor.update_measurement_log(
            logging_filepath, _mark_startup_expired
        )
        return 1

    stop_event = threading.Event()
    token_expired_event = threading.Event()

    def _handle_sigterm(_signum, _frame):
        print("Received SIGTERM; stopping watchdog.", flush=True)
        measurement_monitor.update_measurement_log(
            logging_filepath,
            lambda d: d.update({"current_action": "Stopped"}),
        )
        stop_event.set()

    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
    except ValueError:
        pass

    def _heartbeat():
        folder_ok = os.path.isdir(data_folder)
        measurement_monitor.update_measurement_log(
            logging_filepath,
            lambda d: d.update(
                {
                    "last_heartbeat_at": measurement_monitor.utc_now_iso(),
                    "folder_accessible": folder_ok,
                    "current_action": (
                        "Watching for new files"
                        if folder_ok
                        else "Folder inaccessible"
                    ),
                }
            ),
        )

    def custom_function(file_path):
        return process_new_file(
            file_path,
            openbis_session=openbis_session,
            openbis_url=openbis_url,
            openbis_token=openbis_token,
            measurement_session_id=measurement_session_id,
            logging_filepath=logging_filepath,
            stop_event=stop_event,
            token_expired_event=token_expired_event,
        )

    try:
        run_upload_cycle(
            data_folder=data_folder,
            openbis_session=openbis_session,
            openbis_url=openbis_url,
            openbis_token=openbis_token,
            measurement_session_id=measurement_session_id,
            logging_filepath=logging_filepath,
        )
    except TokenExpiredError:
        return 1

    if not os.path.isdir(data_folder):
        msg = f"Monitored directory does not exist: {data_folder}"
        print(msg, flush=True)
        logger.error(msg)
        measurement_monitor.update_measurement_log(
            logging_filepath,
            lambda d: (
                d.update({"folder_accessible": False, "current_action": msg}),
                measurement_monitor.append_error_event(d, msg, stage="watcher"),
            )[0],
        )
        return 1

    monitor_folder(
        data_folder,
        custom_function,
        heartbeat_callback=_heartbeat,
        heartbeat_interval=15.0,
        stop_event=stop_event,
    )
    return 1 if token_expired_event.is_set() else 0


if __name__ == "__main__":
    sys.exit(main())
