import argparse
import datetime
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Optional

from pybis import AfsClient
from src import sync_registry, utils

logger = logging.getLogger(__name__)


def compute_relative_path(file_path: str, source_path: str) -> str:
    """Compute the relative path of an AFS file inside the selected source folder.

    Example:
        compute_relative_path("/raw/run1/scan.dat", "/raw/run1") -> "scan.dat"
        compute_relative_path("/raw/run1/sub/scan.dat", "/raw/run1/") -> "sub/scan.dat"
        compute_relative_path("/scan.dat", "/") -> "scan.dat"
    """
    fp = file_path.replace("\\", "/").strip()
    sp = source_path.replace("\\", "/").strip()

    # Normalize slashes
    fp_parts = [p for p in fp.split("/") if p and p != "."]
    sp_parts = [p for p in sp.split("/") if p and p != "."]

    if not sp_parts:
        return "/".join(fp_parts)

    if fp_parts[: len(sp_parts)] == sp_parts:
        rel_parts = fp_parts[len(sp_parts) :]
        return "/".join(rel_parts)

    return "/".join(fp_parts)


def download_afs_file(
    afs_client: AfsClient,
    owner: str,
    file_path: str,
    local_dest: Path,
    file_size: int,
    chunk_size: int = 10 * 1024 * 1024,
) -> None:
    local_dest.parent.mkdir(parents=True, exist_ok=True)
    temp_file = local_dest.with_suffix(local_dest.suffix + ".part")

    if file_size == 0:
        with open(local_dest, "wb"):
            pass
        return

    offset = 0
    with open(temp_file, "wb") as f_out:
        while offset < file_size:
            limit = min(chunk_size, file_size - offset)
            chunk = afs_client.read(owner, file_path, offset=offset, limit=limit)
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            elif isinstance(chunk, list):
                chunk = bytes(chunk)
            f_out.write(chunk)
            offset += len(chunk)

    if offset < file_size:
        if temp_file.exists():
            temp_file.unlink()
        raise IOError(
            f"Truncated download for {file_path}: received {offset}/{file_size} bytes"
        )

    temp_file.replace(local_dest)


def sync_once(
    afs_client: AfsClient,
    owner: str,
    source_path: str,
    destination_path: str,
) -> dict:
    dest = Path(destination_path)
    dest.mkdir(parents=True, exist_ok=True)

    file_list = afs_client.list(owner, source_path, recursively=True)
    if file_list is None:
        file_list = []

    expected_files = set()
    expected_dirs = {dest.resolve()}
    stats = {"downloaded": 0, "skipped": 0, "deleted": 0}

    for f in file_list:
        rel = compute_relative_path(f.path, source_path)
        if not rel:
            continue
        target = dest / rel

        # Track directory hierarchy
        for parent in target.parents:
            expected_dirs.add(parent.resolve())
            if parent.resolve() == dest.resolve():
                break

        if getattr(f, "directory", False):
            target.mkdir(parents=True, exist_ok=True)
            expected_dirs.add(target.resolve())
        else:
            expected_files.add(target.resolve())
            if target.exists() and target.is_file() and target.stat().st_size == f.size:
                stats["skipped"] += 1
                continue

            download_afs_file(afs_client, owner, f.path, target, f.size)
            stats["downloaded"] += 1

    # Mirror deletions: bottom-up cleanup of untracked files and directories
    for root, dirs, files in os.walk(dest, topdown=False):
        root_path = Path(root).resolve()
        for file in files:
            p = root_path / file
            if p not in expected_files:
                try:
                    p.unlink()
                    stats["deleted"] += 1
                except OSError as e:
                    logger.warning("Could not delete local file %s: %s", p, e)

        for d in dirs:
            p = root_path / d
            if p not in expected_dirs:
                try:
                    p.rmdir()
                    stats["deleted"] += 1
                except OSError as e:
                    logger.debug(
                        "Directory %s not empty or cannot be removed: %s", p, e
                    )

    return stats


def run_worker(config: dict, registry_path: Optional[Path] = None) -> None:
    job_id = config["job_id"]
    owner = config["owner"]
    source_path = config["afs_path"]
    destination_path = config["local_path"]
    interval = max(5, int(config.get("poll_interval", 60)))
    log_file = config.get("log_file")

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
        )

    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logger.info("Received termination signal %s. Shutting down worker...", signum)
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    openbis_session, _ = utils.connect_openbis_aiida()
    if not openbis_session:
        logger.error("Could not establish openBIS session. Worker exiting.")
        sync_registry.update_job(
            job_id,
            {"status": "STOPPED"},
            registry_path or sync_registry.DEFAULT_REGISTRY_PATH,
        )
        return

    afs_url = openbis_session.url.rstrip("/") + "/afs-server"
    afs_client = AfsClient(afs_url, openbis_session.token, verify=False)

    logger.info("Starting sync loop for job %s (interval: %ds)", job_id, interval)

    while running:
        try:
            stats = sync_once(afs_client, owner, source_path, destination_path)
            now_iso = datetime.datetime.now().isoformat()
            sync_registry.update_job(
                job_id,
                {
                    "last_synced": now_iso,
                    "files_synced": stats["downloaded"] + stats["skipped"],
                    "status": "RUNNING",
                },
                registry_path or sync_registry.DEFAULT_REGISTRY_PATH,
            )
            logger.info("Sync completed: %s", stats)
        except Exception as e:
            logger.error("Error during sync cycle: %s", e)

        # Sleep in small increments for prompt signal handling
        for _ in range(interval * 2):
            if not running:
                break
            time.sleep(0.5)

    sync_registry.update_job(
        job_id,
        {"status": "STOPPED"},
        registry_path or sync_registry.DEFAULT_REGISTRY_PATH,
    )
    logger.info("Worker stopped for job %s", job_id)


def main():
    parser = argparse.ArgumentParser(
        description="AFS folder synchronization worker daemon."
    )
    parser.add_argument(
        "--config", required=True, help="Path to JSON configuration file."
    )
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    run_worker(config)


if __name__ == "__main__":
    main()
