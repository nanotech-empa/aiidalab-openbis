import time
import os
import utils
from pybis import AfsClient
import logging

CONFIG_FILENAME = "/home/jovyan/apps/aiidalab-openbis/config/config.json"
CONFIG = utils.read_json(CONFIG_FILENAME)
OPENBIS_SESSION, SESSION_DATA = utils.connect_openbis_aiida()

TARGET_SAMPLE_ID = "20260402094947708-6476"
LOG_FILE_PATH = "/home/jovyan/apps/aiidalab-openbis/logs/aiidalab_openbis_interface.log"
UPLOAD_INTERVAL_SECONDS = 300  # Upload every 5 minutes

if not os.path.exists("logs"):
    os.mkdir("logs")

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def upload_log(openbis_session):
    if not os.path.exists(LOG_FILE_PATH):
        return

    try:
        afs_url = OPENBIS_SESSION.url + "/afs-server"
        token = OPENBIS_SESSION.token
        username = OPENBIS_SESSION._get_username()
        with open(LOG_FILE_PATH, "rb") as log_file:
            log_file_text = log_file.read()
            afs_client = AfsClient(afs_url, token)
            afs_client.write(
                TARGET_SAMPLE_ID,
                f"{username}_aiidalab_openbis_interface.log",
                offset=0,
                limit=len(log_file_text),
                data=log_file_text,
            )

    except Exception as e:
        logger.error("Error uploading log to AFS: %s", e)


if __name__ == "__main__":
    while True:
        upload_log(OPENBIS_SESSION)
        time.sleep(UPLOAD_INTERVAL_SECONDS)
