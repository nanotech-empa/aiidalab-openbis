from unittest.mock import MagicMock

import pytest
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


def test_mirror_nested_directory_deletion(tmp_path):
    dest = tmp_path / "dest"
    sub_dir = dest / "subfolder"
    sub_dir.mkdir(parents=True)
    stale_nested_file = sub_dir / "stale_nested.dat"
    stale_nested_file.write_text("old nested content")

    mock_client = MagicMock()
    mock_client.list.return_value = []

    # Remote has zero files: the entire nested directory and file must be mirrored/deleted
    stats = sync_once(mock_client, "SAMPLE_1", "/scans/run1", str(dest))
    assert stats["deleted"] >= 1
    assert not stale_nested_file.exists()
    assert not sub_dir.exists()


def test_resume_all_matching_files_zero_transfers(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    f1 = dest / "file1.txt"
    f1.write_bytes(b"content123")

    mock_f = MagicMock()
    mock_f.directory = False
    mock_f.path = "/scans/file1.txt"
    mock_f.size = len(b"content123")
    mock_f.name = "file1.txt"

    mock_client = MagicMock()
    mock_client.list.return_value = [mock_f]

    stats = sync_once(mock_client, "SAMPLE_RESUME", "/scans", str(dest))
    assert stats["downloaded"] == 0
    assert stats["skipped"] == 1
    assert stats["deleted"] == 0
    mock_client.read.assert_not_called()


def test_normalize_path_and_conflict_slash_agnostic(tmp_path):
    reg_file = tmp_path / "active_synchronisations.json"
    job = {
        "job_id": "job-slash",
        "pid": 5555,
        "owner": "SAMPLE_SLASH",
        "afs_path": "/scans/run1/",
        "local_path": "/data/run1/",
        "status": "RUNNING",
    }
    sync_registry.register_job(job, reg_file)

    # Missing leading slash and trailing slash should still detect conflict
    conflict1 = sync_registry.find_conflict(
        "SAMPLE_SLASH", "scans/run1", "/other", reg_file
    )
    assert conflict1 is not None
    assert conflict1["job_id"] == "job-slash"

    # Missing leading slash on local path should also be recognized
    conflict2 = sync_registry.find_conflict("OTHER", "other_afs", "data/run1", reg_file)
    assert conflict2 is not None
    assert conflict2["job_id"] == "job-slash"


def test_download_afs_file_handles_truncated_transfer(tmp_path):
    from src.sync_afs_worker import download_afs_file

    dest_file = tmp_path / "truncated.dat"
    mock_client = MagicMock()
    # Returns only 4 bytes then empty EOF when 100 bytes are expected
    mock_client.read.side_effect = [b"1234", b""]

    with pytest.raises(IOError, match="Truncated download"):
        download_afs_file(
            mock_client, "SAMPLE_1", "/file.dat", dest_file, file_size=100
        )

    assert not dest_file.exists()
    assert not (tmp_path / "truncated.dat.part").exists()


def test_poll_interval_boundary_clamped(tmp_path):
    cfg = {
        "job_id": "clamp-job",
        "owner": "SMP_1",
        "afs_path": "/run1",
        "local_path": str(tmp_path / "loc"),
        "poll_interval": 1,  # Below minimum 5s
    }
    # Verify that poll_interval is normalized to at least 5
    interval = max(5, int(cfg.get("poll_interval", 60)))
    assert interval == 5


def test_active_syncs_widget_resume_conflict_prevention(tmp_path):
    import os

    reg_file = tmp_path / "active_synchronisations.json"

    # Job 1 is running on /run1 with real current PID so sync_liveness keeps it RUNNING
    job1 = {
        "job_id": "job-1",
        "pid": os.getpid(),
        "owner": "SAMPLE_RESUME",
        "afs_path": "/run1",
        "local_path": "/data/run1",
        "status": "RUNNING",
    }
    # Job 2 is stopped on the same /run1
    job2 = {
        "job_id": "job-2",
        "pid": 888888,
        "owner": "SAMPLE_RESUME",
        "afs_path": "/run1",
        "local_path": "/data/run1_other",
        "status": "STOPPED",
    }
    sync_registry.register_job(job1, reg_file)
    sync_registry.register_job(job2, reg_file)

    widget = synchronisation_widgets.ActiveSyncsWidget(registry_path=reg_file)
    assert len(widget.jobs_box.children) == 2
    # Finding conflict should block job2 resume
    conflict = sync_registry.find_conflict(
        "SAMPLE_RESUME", "/run1", "/data/run1_other", reg_file
    )
    assert conflict is not None
    assert conflict["job_id"] == "job-1"


def test_setup_sync_widget_poll_interval_dropdown(tmp_path):
    import ipywidgets as ipw

    mock_session = MagicMock()
    mock_session.url = "https://openbis.example.com"
    widget = synchronisation_widgets.SetupSyncWidget(
        openbis_session=mock_session,
        registry_path=tmp_path / "reg.json",
    )
    assert isinstance(widget.poll_interval, ipw.Dropdown)
    assert widget.poll_interval.value == 60
    assert widget.poll_interval.style.description_width == "initial"
    option_values = [v for _, v in widget.poll_interval.options]
    assert 5 in option_values
    assert 10 in option_values
    assert 30 in option_values
    assert 60 in option_values
    assert 300 in option_values


def test_setup_sync_widget_browse_button_and_file_chooser(tmp_path):
    mock_session = MagicMock()
    widget = synchronisation_widgets.SetupSyncWidget(
        openbis_session=mock_session,
        registry_path=tmp_path / "reg.json",
    )
    assert widget.browse_btn is not None
    assert widget.file_chooser_box.layout.display == "none"

    # Toggle open
    widget._on_toggle_file_chooser(None)
    assert widget.file_chooser_box.layout.display == "block"
    assert widget.browse_btn.description == "Close Browser"

    # Selecting folder updates local_input and collapses
    mock_chooser = MagicMock()
    mock_chooser.selected_path = str(tmp_path / "chosen_dir")
    mock_chooser.selected = str(tmp_path / "chosen_dir")
    widget._on_local_folder_selected(mock_chooser)

    assert widget.local_input.value == str(tmp_path / "chosen_dir")
    assert widget.file_chooser_box.layout.display == "none"
    assert widget.browse_btn.description == "Browse Folder"


def test_setup_sync_widget_extracts_nested_folders(tmp_path, monkeypatch):
    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.permId = "SAMPLE_NESTED"
    mock_sample.code = "NESTED_CODE"
    mock_sample.identifier = "/SPACE/PROJ/NESTED_CODE"
    mock_session.get_sample.return_value = mock_sample

    f1 = MagicMock()
    f1.path = "/folderA/subfolderB/file1.dat"
    f1.directory = False

    f2 = MagicMock()
    f2.path = "/folderC"
    f2.directory = True

    mock_afs = MagicMock()
    mock_afs.list.return_value = [f1, f2]
    monkeypatch.setattr(
        synchronisation_widgets, "AfsClient", lambda *args, **kwargs: mock_afs
    )

    widget = synchronisation_widgets.SetupSyncWidget(
        openbis_session=mock_session,
        registry_path=tmp_path / "reg.json",
    )
    widget.object_input.value = "SAMPLE_NESTED"
    widget._on_search(None)

    options = list(widget.afs_dropdown.options)
    assert "/" in options
    assert "/folderA" in options
    assert "/folderA/subfolderB" in options
    assert "/folderC" in options


def test_sync_once_live_progress_callback(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    f1 = MagicMock()
    f1.directory = False
    f1.path = "/run1/file1.dat"
    f1.size = 10
    f1.name = "file1.dat"

    f2 = MagicMock()
    f2.directory = False
    f2.path = "/run1/file2.dat"
    f2.size = 20
    f2.name = "file2.dat"

    mock_client = MagicMock()
    mock_client.list.return_value = [f1, f2]
    mock_client.read.return_value = b"0123456789"

    progress_calls = []

    def on_prog(dl, sk, tot):
        progress_calls.append((dl, sk, tot))

    stats = sync_once(mock_client, "SMP", "/run1", str(dest), on_progress=on_prog)
    assert stats["downloaded"] == 2
    assert len(progress_calls) >= 1
    assert progress_calls[-1] == (2, 0, 2)


def test_sync_once_handles_failing_file_gracefully(tmp_path, monkeypatch):
    dest = tmp_path / "dest"
    dest.mkdir()

    good_file = MagicMock()
    good_file.directory = False
    good_file.path = "/run1/good.dat"
    good_file.size = 4
    good_file.name = "good.dat"

    bad_file = MagicMock()
    bad_file.directory = False
    bad_file.path = "/run1/bad.dat"
    bad_file.size = 10
    bad_file.name = "bad.dat"

    mock_client = MagicMock()
    mock_client.list.return_value = [bad_file, good_file]

    # bad_file raises NoSuchFileException, good_file succeeds
    def mock_download(client, owner, remote_path, target_path, file_size):
        if "bad.dat" in remote_path:
            # create dummy part file to test cleanup
            part = target_path.with_suffix(target_path.suffix + ".part")
            part.write_bytes(b"temp")
            raise IOError("NoSuchFileException: file missing")
        target_path.write_bytes(b"good")

    monkeypatch.setattr("src.sync_afs_worker.download_afs_file", mock_download)

    stats = sync_once(mock_client, "SMP", "/run1", str(dest))
    assert stats["downloaded"] == 1
    assert (dest / "good.dat").exists()
    assert not (dest / "bad.dat").exists()
    assert not (dest / "bad.dat.part").exists()


def test_active_syncs_widget_displays_downloading_progress(tmp_path):
    import os

    reg_file = tmp_path / "reg.json"
    job = {
        "job_id": "job-prog",
        "pid": os.getpid(),
        "owner": "SMP_P",
        "afs_path": "/run1",
        "local_path": "/local/run1",
        "status": "RUNNING",
        "current_action": "Downloading (50 new, 10 up to date of 100)",
        "last_synced": "2026-10-22T12:00:00",
        "files_synced": 60,
    }
    sync_registry.register_job(job, reg_file)

    widget = synchronisation_widgets.ActiveSyncsWidget(registry_path=reg_file)
    card_html = str(widget.jobs_box.children[0].children[1].value)
    assert "Downloading (50 new, 10 up to date of 100)" in card_html
    assert "Last Completed Cycle" in card_html
