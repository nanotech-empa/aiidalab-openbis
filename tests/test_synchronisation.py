from unittest.mock import MagicMock

from src import sync_registry, synchronisation_widgets
from src.sync_afs_worker import compute_relative_path, sync_once


def test_registry_lifecycle_and_conflict(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"

    # Empty registry
    assert sync_registry.load_registry(reg_file) == {"jobs": {}}

    # Register job 1
    job1 = {
        "job_id": "job-1",
        "pid": 999999,
        "owner": "SAMPLE_1",
        "object_identifier": "/SPACE/EXP/SAMPLE_1",
        "afs_path": "/scans/run1",
        "local_path": "/data/run1",
        "poll_interval": 10,
        "status": "RUNNING",
    }
    sync_registry.register_job(job1, reg_file)

    # Conflict checks: same owner & afs_path with varied slash
    conflict_afs = sync_registry.find_conflict(
        "SAMPLE_1", "/scans/run1/", "/other/dir", reg_file
    )
    assert conflict_afs is not None
    assert conflict_afs["job_id"] == "job-1"

    # Conflict checks: same local path
    conflict_local = sync_registry.find_conflict(
        "SAMPLE_2", "/scans/run2", "/data/run1/", reg_file
    )
    assert conflict_local is not None
    assert conflict_local["job_id"] == "job-1"

    # No conflict for different afs & local
    assert (
        sync_registry.find_conflict("SAMPLE_2", "/scans/run2", "/data/run2", reg_file)
        is None
    )

    # Stop job
    sync_registry.update_job("job-1", {"status": "STOPPED"}, reg_file)
    # Stopped job should no longer cause active conflict
    assert (
        sync_registry.find_conflict("SAMPLE_1", "/scans/run1", "/data/run1", reg_file)
        is None
    )

    # Dismiss job
    assert sync_registry.dismiss_job("job-1", reg_file) is True
    assert "job-1" not in sync_registry.load_registry(reg_file)["jobs"]


def test_sync_liveness_marks_dead_pid_stopped(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"
    job = {
        "job_id": "job-dead",
        "pid": 99999999,  # Definitely non-existent PID
        "owner": "SAMPLE_1",
        "afs_path": "/run1",
        "local_path": "/data/run1",
        "status": "RUNNING",
    }
    sync_registry.register_job(job, reg_file)
    sync_registry.sync_liveness(reg_file)
    data = sync_registry.load_registry(reg_file)
    assert data["jobs"]["job-dead"]["status"] == "STOPPED"


def test_compute_relative_path():
    assert compute_relative_path("/raw/run1/scan.dat", "/raw/run1") == "scan.dat"
    assert (
        compute_relative_path("/raw/run1/sub/scan.dat", "/raw/run1/") == "sub/scan.dat"
    )
    assert compute_relative_path("/scan.dat", "/") == "scan.dat"
    assert compute_relative_path("scan.dat", "") == "scan.dat"


def test_sync_once_incremental_and_deletion(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    # Pre-existing local file that will be deleted because it is not on AFS
    stale_file = dest / "stale.dat"
    stale_file.write_text("old data")

    # Mock remote AFS files
    mock_file1 = MagicMock()
    mock_file1.directory = False
    mock_file1.path = "/scans/run1/scan1.dat"
    mock_file1.size = 12
    mock_file1.name = "scan1.dat"

    mock_client = MagicMock()
    mock_client.list.return_value = [mock_file1]
    mock_client.read.return_value = b"hello remote"

    # First sync: downloads scan1.dat, deletes stale.dat
    stats1 = sync_once(mock_client, "SAMPLE_1", "/scans/run1", str(dest))
    assert stats1["downloaded"] == 1
    assert stats1["deleted"] == 1
    assert not stale_file.exists()
    assert (dest / "scan1.dat").read_bytes() == b"hello remote"

    # Second sync: scan1.dat already exists with matching size -> skipped!
    mock_client.read.reset_mock()
    stats2 = sync_once(mock_client, "SAMPLE_1", "/scans/run1", str(dest))
    assert stats2["downloaded"] == 0
    assert stats2["skipped"] == 1
    assert stats2["deleted"] == 0
    mock_client.read.assert_not_called()


def test_setup_sync_widget_conflict_detection(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"
    job = {
        "job_id": "job-test",
        "pid": 1111,
        "owner": "SMP_1",
        "afs_path": "/run1",
        "local_path": "/local/run1",
        "status": "RUNNING",
    }
    sync_registry.register_job(job, reg_file)

    mock_session = MagicMock()
    widget = synchronisation_widgets.SetupSyncWidget(
        openbis_session=mock_session,
        registry_path=reg_file,
    )

    # Check conflict detection method
    conflict = widget.check_conflict("SMP_1", "/run1", "/other/path")
    assert conflict is not None
    assert "already being synchronized" in widget.conflict_html.value
    assert widget.start_button.disabled is True

    # Check valid path
    widget.check_conflict("SMP_1", "/run2", "/local/run2")
    assert widget.conflict_html.value == ""
    assert widget.start_button.disabled is False


def test_config_json_contains_synchronisation_link():
    import json

    with open("config/config.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    enable_exp = "".join(cfg["home_page"]["enable_links"]["Experiments"])
    assert "6_synchronisation.ipynb" in enable_exp
    assert "Folder synchronisation (AFS)" in enable_exp

    disable_exp = "".join(cfg["home_page"]["disable_links"]["Experiments"])
    assert "6_synchronisation.ipynb" in disable_exp


def test_notebook_valid_json():
    import json

    with open("6_synchronisation.ipynb", "r", encoding="utf-8") as f:
        nb = json.load(f)
    assert nb["nbformat"] == 4
    cell_sources = "".join("".join(c["source"]) for c in nb["cells"])
    assert "SynchronisationMainWidget" in cell_sources
    assert "connect_openbis_aiida" in cell_sources
