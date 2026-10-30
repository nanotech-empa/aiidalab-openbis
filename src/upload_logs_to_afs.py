import logging
import os
import time

try:
    import psutil
except ImportError:
    psutil = None

from pybis import AfsClient
import utils

CONFIG_FILENAME = "/home/jovyan/apps/aiidalab-openbis/config/config.json"
CONFIG = utils.read_json(CONFIG_FILENAME)
OPENBIS_SESSION, SESSION_DATA = utils.connect_openbis_aiida()

OPENBIS_AFS_CONFIG = utils.read_json(
    "/home/jovyan/apps/aiidalab-openbis/config/openbis_config.json"
)["AFS"]
TARGET_SAMPLE_ID = OPENBIS_AFS_CONFIG.get("target_sample_id")
UPLOAD_INTERVAL_SECONDS = OPENBIS_AFS_CONFIG.get(
    "upload_interval_seconds", 300
)  # Upload every 5 minutes
RAM_LOG_INTERVAL_SECONDS = 3600  # Log RAM usage every hour

LOG_FILE_PATH = "/home/jovyan/apps/aiidalab-openbis/logs/aiidalab_openbis_interface.log"

if not os.path.exists("logs"):
    os.mkdir("logs")

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def get_ram_usage_from_proc_meminfo():
    """Fallback to read RAM usage directly from /proc/meminfo if psutil fails."""
    if not os.path.exists("/proc/meminfo"):
        return "N/A"
    try:
        mem_total_kb = None
        mem_avail_kb = None
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_kb = float(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    mem_avail_kb = float(line.split()[1])
                if mem_total_kb is not None and mem_avail_kb is not None:
                    break
        if mem_total_kb is not None and mem_avail_kb is not None and mem_total_kb > 0:
            used_kb = mem_total_kb - mem_avail_kb
            percent = (used_kb / mem_total_kb) * 100.0
            used_gb = used_kb / (1024**2)
            total_gb = mem_total_kb / (1024**2)
            return f"{used_gb:.1f} / {total_gb:.1f} GB [{percent:.1f}%]"
    except Exception as e:
        logger.error("Error reading /proc/meminfo: %s", e)
    return "N/A"


def get_ram_usage_str():
    """Return formatted RAM usage string: 'used / total GB [percent%]'."""
    try:
        if psutil is not None:
            vm = psutil.virtual_memory()
            used_gb = vm.used / (1024**3)
            total_gb = vm.total / (1024**3)
            return f"{used_gb:.1f} / {total_gb:.1f} GB [{vm.percent:.1f}%]"
        raise ImportError("psutil not available")
    except Exception as e:
        logger.warning(
            "psutil failed to get RAM usage: %s. Falling back to /proc/meminfo.", e
        )
        return get_ram_usage_from_proc_meminfo()


def log_ram_usage_if_due(
    logger, last_logged_time, current_time=None, interval_seconds=3600.0
):
    """Log current instance RAM usage if interval_seconds has elapsed since last_logged_time."""
    if current_time is None:
        current_time = time.time()
    if last_logged_time == 0.0 or (current_time - last_logged_time >= interval_seconds):
        ram_str = get_ram_usage_str()
        logger.info("RAM usage: %s", ram_str)
        return current_time
    return last_logged_time


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
    last_ram_log_time = 0.0
    while True:
        last_ram_log_time = log_ram_usage_if_due(
            logger, last_ram_log_time, interval_seconds=RAM_LOG_INTERVAL_SECONDS
        )
        upload_log(OPENBIS_SESSION)
        time.sleep(UPLOAD_INTERVAL_SECONDS)
