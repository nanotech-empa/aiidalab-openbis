import datetime
import json
import os
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest


def test_atomic_write_and_update_measurement_log_preserves_unknown_keys(tmp_path):
    from src import measurement_monitor

    log_file = tmp_path / "SESS-1.json"
    measurement_monitor.atomic_write_json(
        {
            "measurement_session_id": "SESS-1",
            "custom_meta": "keep-me",
            "processed_files": ["/data/a.sxm"],
        },
        log_file,
    )

    assert list(tmp_path.glob("*.tmp.*")) == []

    def _updater(data):
        data["current_action"] = "Watching for new files"

    updated = measurement_monitor.update_measurement_log(log_file, _updater)

    assert updated["custom_meta"] == "keep-me"
    assert updated["processed_files"] == ["/data/a.sxm"]
    assert updated["current_action"] == "Watching for new files"
    assert json.loads(log_file.read_text(encoding="utf-8")) == updated
    assert list(tmp_path.glob("*.tmp.*")) == []


def test_append_upload_and_error_events_cap_history_and_update_latest():
    from src import measurement_monitor

    data = {"processed_files": []}
    for i in range(205):
        measurement_monitor.append_upload_event(
            data,
            f"/data/scan_{i:03d}.sxm",
            "SXM",
            uploaded_at=f"2026-11-26T10:00:{i % 60:02d}+00:00",
        )

    assert len(data["upload_history"]) == 200
    assert data["upload_history"][0]["filename"] == "scan_005.sxm"
    assert data["upload_history"][-1]["filename"] == "scan_204.sxm"
    assert data["upload_history"][-1]["type"] == "SXM"
    assert data["last_uploaded_file"] == "scan_204.sxm"
    assert data["last_upload_at"] == "2026-11-26T10:00:24+00:00"

    for i in range(55):
        measurement_monitor.append_error_event(
            data,
            f"err-{i}",
            stage="dat",
            file_path=f"/data/spec_{i:02d}.dat",
            timestamp=f"2026-11-26T11:00:{i % 60:02d}+00:00",
        )

    assert len(data["recent_errors"]) == 50
    assert data["recent_errors"][0]["message"] == "err-5"
    assert data["recent_errors"][-1]["message"] == "err-54"
    assert data["recent_errors"][-1]["file"] == "spec_54.dat"
    assert data["recent_errors"][-1]["stage"] == "dat"
    assert data["last_error"] == data["recent_errors"][-1]


def test_start_watchdog_subprocess_redirects_output_without_leaking_token_or_fd(
    tmp_path,
):
    from src import measurement_monitor

    logs_dir = tmp_path / "logs" / "measurements"
    opened_handles = []

    def fake_popen(cmd, **kwargs):
        stdout_handle = kwargs["stdout"]
        opened_handles.append(stdout_handle)
        assert not stdout_handle.closed
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["start_new_session"] is True
        return MagicMock(pid=4242)

    with patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
        proc, log_path = measurement_monitor.start_watchdog_subprocess(
            app_folder=tmp_path / "app",
            openbis_url="https://openbis.local",
            openbis_token="SECRET-TOKEN-XYZ",
            measurement_session_id="SESS-42",
            data_folder=str(tmp_path / "data"),
            logs_dir=logs_dir,
        )

    assert proc.pid == 4242
    assert log_path == logs_dir / "SESS-42.log"
    assert opened_handles[0].closed is True
    cmd = mock_popen.call_args.args[0]
    assert cmd[:3] == ["python", "-u", f"{tmp_path / 'app'}/src/measurements_uploader.py"]
    assert "SESS-42" in cmd
    log_text = log_path.read_text(encoding="utf-8")
    assert "SESS-42" in log_text
    assert "SECRET-TOKEN-XYZ" not in log_text

    # Also verify log FD closes even if Popen raises OSError
    opened_handles.clear()

    def failing_popen(cmd, **kwargs):
        opened_handles.append(kwargs["stdout"])
        raise OSError("spawn failed")

    with (
        patch("subprocess.Popen", side_effect=failing_popen),
        pytest.raises(OSError, match="spawn failed"),
    ):
        measurement_monitor.start_watchdog_subprocess(
            app_folder=tmp_path / "app",
            openbis_url="https://openbis.local",
            openbis_token="SECRET-TOKEN-XYZ",
            measurement_session_id="SESS-43",
            data_folder=str(tmp_path / "data"),
            logs_dir=logs_dir,
        )

    assert len(opened_handles) == 1
    assert opened_handles[0].closed is True


def test_sync_watchdog_liveness_transitions_dead_running_to_exited_and_reaps_zombie(
    tmp_path,
):
    from src import measurement_monitor

    registry = tmp_path / "active_watchdogs.json"
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.monotonic() + 5.0
        proc_stat = f"/proc/{proc.pid}/stat"
        while time.monotonic() < deadline:
            if os.path.exists(proc_stat):
                with open(proc_stat, "r", encoding="utf-8") as fh:
                    if ") Z " in fh.read():
                        break
            time.sleep(0.05)

        registry.write_text(
            json.dumps(
                [
                    {
                        "pid": proc.pid,
                        "monitored_folder": "/data/zombie",
                        "measurement_session_id": "SESS-ZOMBIE",
                    },
                    {
                        "pid": 999999,
                        "monitored_folder": "/data/stopped",
                        "measurement_session_id": "SESS-STOPPED",
                        "status": "STOPPED",
                        "user_stopped": True,
                        "stopped_at": "2026-11-26T09:00:00+00:00",
                    },
                ]
            ),
            encoding="utf-8",
        )

        entries = measurement_monitor.sync_watchdog_liveness(registry)
        by_id = {e["measurement_session_id"]: e for e in entries}
        assert by_id["SESS-ZOMBIE"]["status"] == "EXITED"
        assert by_id["SESS-ZOMBIE"]["user_stopped"] is False
        assert by_id["SESS-ZOMBIE"]["stopped_at"]
        assert by_id["SESS-STOPPED"]["status"] == "STOPPED"
        assert by_id["SESS-STOPPED"]["user_stopped"] is True
        assert by_id["SESS-STOPPED"]["stopped_at"] == "2026-11-26T09:00:00+00:00"
    finally:
        proc.wait(timeout=5)


def test_upsert_mark_stopped_and_dismiss_registry_lifecycle(tmp_path):
    from src import measurement_monitor

    registry = tmp_path / "active_watchdogs.json"
    entry1 = measurement_monitor.upsert_running_watchdog(
        registry,
        pid=1001,
        data_folder="/data/run1/",
        measurement_session_id="SESS-1",
        metadata={"session_name": "MEAS_1", "sample_name": "S1"},
        log_file=tmp_path / "SESS-1.log",
    )
    assert entry1["status"] == "RUNNING"
    assert entry1["monitored_folder"] == "/data/run1"
    assert entry1["session_name"] == "MEAS_1"

    # Cannot dismiss a running entry
    assert (
        measurement_monitor.dismiss_watchdog_entry(
            registry, measurement_session_id="SESS-1"
        )
        is False
    )

    # Stop preserving card (remove_entries=False)
    measurement_monitor.mark_watchdogs_stopped(registry, [1001], remove_entries=False)
    entries = measurement_monitor.load_watchdog_entries(registry)
    assert len(entries) == 1
    assert entries[0]["status"] == "STOPPED"
    assert entries[0]["user_stopped"] is True
    assert entries[0]["stopped_at"]

    # Upsert on resume updates in place instead of creating a duplicate
    measurement_monitor.upsert_running_watchdog(
        registry,
        pid=1002,
        data_folder="/data/run1",
        measurement_session_id="SESS-1",
    )
    entries = measurement_monitor.load_watchdog_entries(registry)
    assert len(entries) == 1
    assert entries[0]["pid"] == 1002
    assert entries[0]["status"] == "RUNNING"
    assert entries[0]["user_stopped"] is False
    assert entries[0]["stopped_at"] is None
    assert entries[0]["session_name"] == "MEAS_1"

    # Stop removing entry (switch flow)
    measurement_monitor.mark_watchdogs_stopped(registry, [1002], remove_entries=True)
    assert measurement_monitor.load_watchdog_entries(registry) == []

    # Add stopped entry and dismiss it
    measurement_monitor.save_watchdog_entries(
        [
            {
                "pid": 1003,
                "monitored_folder": "/data/run2",
                "measurement_session_id": "SESS-2",
                "status": "EXITED",
                "user_stopped": False,
            }
        ],
        registry,
    )
    assert (
        measurement_monitor.dismiss_watchdog_entry(
            registry, measurement_session_id="SESS-2"
        )
        is True
    )
    assert measurement_monitor.load_watchdog_entries(registry) == []


def test_build_watchdog_card_snapshot_handles_legacy_logs_disk_counts_health_and_afs_sync(
    tmp_path,
):
    from src import measurement_monitor

    now = datetime.datetime(2026, 11, 26, 12, 0, 0, tzinfo=datetime.timezone.utc)
    meas_dir = tmp_path / "logs" / "measurements"
    meas_dir.mkdir(parents=True)
    data_folder = tmp_path / "meas_day1"
    data_folder.mkdir()
    sxm1 = data_folder / "scan1.sxm"
    dat1 = data_folder / "spec1.dat"
    txt1 = data_folder / "notes.txt"
    pending_sxm = data_folder / "scan2.sxm"
    ignored = data_folder / "temp.part"
    for p in (sxm1, dat1, txt1, pending_sxm, ignored):
        p.write_text("x", encoding="utf-8")

    # (a) Running watchdog with enriched log, process log tail, and live AFS sync job
    (meas_dir / "SESS-1.json").write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local/openbis/webapp/eln-lims/",
                "eln_token": "DO-NOT-EXPOSE",
                "measurement_session_id": "SESS-1",
                "data_folder": str(data_folder),
                "session_name": "MEAS_SampleA",
                "sample_name": "SampleA",
                "experiment_name": "Exp1",
                "instrument_name": "STM-1",
                "started_at": "2026-11-26T11:50:00+00:00",
                "last_heartbeat_at": "2026-11-26T11:59:50+00:00",
                "last_upload_at": "2026-11-26T11:58:00+00:00",
                "last_uploaded_file": "notes.txt",
                "current_action": "Watching for new files",
                "processed_files": [str(sxm1), str(dat1), str(txt1)],
                "upload_history": [
                    {"file": str(sxm1), "filename": "scan1.sxm", "type": "SXM", "uploaded_at": "2026-11-26T11:55:00+00:00"},
                    {"file": str(dat1), "filename": "spec1.dat", "type": "DAT", "uploaded_at": "2026-11-26T11:56:00+00:00"},
                    {"file": str(txt1), "filename": "notes.txt", "type": "ATTACHMENT", "uploaded_at": "2026-11-26T11:58:00+00:00"},
                ],
                "recent_errors": [],
                "last_error": None,
            }
        ),
        encoding="utf-8",
    )
    (meas_dir / "SESS-1.log").write_text(
        "\n".join(f"line-{i}" for i in range(40)) + "\n", encoding="utf-8"
    )
    sync_reg = tmp_path / "logs" / "active_synchronisations.json"
    sync_payload = {
        "jobs": {
            "job1": {
                "job_id": "job1",
                "status": "RUNNING",
                "pid": os.getpid(),
                "local_path": f"{data_folder}/",
            }
        }
    }
    sync_reg.write_text(json.dumps(sync_payload), encoding="utf-8")
    sync_before = sync_reg.read_text(encoding="utf-8")

    snap = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": 1234,
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-1",
            "status": "RUNNING",
            "log_file": str(meas_dir / "SESS-1.log"),
        },
        measurement_logs_dir=meas_dir,
        sync_registry_path=sync_reg,
        now=now,
    )
    assert snap["status"] == "RUNNING"
    assert snap["folder_exists"] is True
    assert snap["heartbeat_stale"] is False
    assert snap["session_name"] == "MEAS_SampleA"
    assert snap["sample_name"] == "SampleA"
    assert snap["experiment_name"] == "Exp1"
    assert snap["instrument_name"] == "STM-1"
    assert "SESS-1" in snap["session_url"]
    assert snap["uploaded_count"] == 3
    assert snap["total_disk_files"] == 4
    assert snap["pending_files"] == ["scan2.sxm"]
    assert snap["type_counts"] == {"SXM": 1, "DAT": 1, "ATTACHMENT": 1}
    assert len(snap["log_tail"]) == 30
    assert snap["log_tail"][0] == "line-10"
    assert snap["log_tail"][-1] == "line-39"
    assert snap["afs_sync_status"] == "RUNNING"
    assert sync_reg.read_text(encoding="utf-8") == sync_before

    # (b) Legacy log without upload_history infers counts by extension
    (meas_dir / "SESS-LEGACY.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-LEGACY",
                "data_folder": str(data_folder),
                "processed_files": [str(sxm1), str(dat1), str(txt1)],
            }
        ),
        encoding="utf-8",
    )
    snap_legacy = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": 2222,
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-LEGACY",
            "status": "STOPPED",
            "user_stopped": True,
        },
        measurement_logs_dir=meas_dir,
        now=now,
    )
    assert snap_legacy["status"] == "STOPPED"
    assert snap_legacy["type_counts"] == {"SXM": 1, "DAT": 1, "ATTACHMENT": 1}

    # (c) Exited with token_expired -> status TOKEN_EXPIRED
    (meas_dir / "SESS-TOK.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-TOK",
                "data_folder": str(data_folder),
                "processed_files": [],
                "token_expired": True,
                "last_error": {"stage": "auth", "message": "Token expired"},
            }
        ),
        encoding="utf-8",
    )
    snap_tok = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": 3333,
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-TOK",
            "status": "EXITED",
            "user_stopped": False,
        },
        measurement_logs_dir=meas_dir,
        now=now,
    )
    assert snap_tok["status"] == "TOKEN_EXPIRED"

    # (d) Stale heartbeat + missing folder
    (meas_dir / "SESS-STALE.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-STALE",
                "data_folder": str(tmp_path / "missing_dir"),
                "processed_files": [],
                "last_heartbeat_at": "2026-11-26T11:55:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    snap_stale = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": 4444,
            "monitored_folder": str(tmp_path / "missing_dir"),
            "measurement_session_id": "SESS-STALE",
            "status": "RUNNING",
        },
        measurement_logs_dir=meas_dir,
        now=now,
    )
    assert snap_stale["folder_exists"] is False
    assert snap_stale["heartbeat_stale"] is True

    # (e) Corrupt JSON log does not crash
    (meas_dir / "SESS-BAD.json").write_text("{corrupt", encoding="utf-8")
    snap_bad = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": 5555,
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-BAD",
            "status": "EXITED",
        },
        measurement_logs_dir=meas_dir,
        sync_registry_path=tmp_path / "logs" / "nonexistent_sync.json",
        now=now,
    )
    assert snap_bad["status"] == "EXITED"
    assert snap_bad["uploaded_count"] == 0
    assert snap_bad["afs_sync_status"] is None


def test_process_measurement_files_records_sxm_dat_upload_history_and_preserves_keys(
    tmp_path,
):
    from nanonis_importer import nanonis_importer

    data_folder = tmp_path / "run_importer"
    data_folder.mkdir()
    sxm_path = data_folder / "scan_01.sxm"
    dat_path = data_folder / "spec_01.dat"
    sxm_path.write_text("sxm", encoding="utf-8")
    dat_path.write_text("dat", encoding="utf-8")

    log_file = tmp_path / "logs" / "SESS-IMP.json"
    log_file.parent.mkdir(parents=True)
    log_file.write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local",
                "eln_token": "tok-1",
                "measurement_session_id": "SESS-IMP",
                "data_folder": str(data_folder),
                "session_name": "MEAS_Importer",
                "started_at": "2026-11-26T10:00:00+00:00",
                "processed_files": [],
            }
        ),
        encoding="utf-8",
    )

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    def fake_spm(path):
        obj = MagicMock()
        if path.endswith(".sxm"):
            obj.record_datetime = datetime.datetime(2026, 11, 26, 10, 0, 1)
        else:
            obj.record_datetime = datetime.datetime(2026, 11, 26, 10, 0, 2)
            obj.signals = {"I": {}}
            obj.measurement_type = "bias"
        return obj

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch("nanonis_importer.nanonis_importer.demo_sxm_flow"),
        patch("nanonis_importer.nanonis_importer.demo_dat_flow"),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="https://openbis.local",
            token="tok-1",
            data_folder=str(data_folder),
            measurements_id="SESS-IMP",
            logging_filepath=str(log_file),
        )

    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["session_name"] == "MEAS_Importer"
    assert data["started_at"] == "2026-11-26T10:00:00+00:00"
    assert set(data["processed_files"]) == {str(sxm_path), str(dat_path)}
    types = {(ev["filename"], ev["type"]) for ev in data["upload_history"]}
    assert types == {("scan_01.sxm", "SXM"), ("spec_01.dat", "DAT")}
    assert data["last_uploaded_file"] == "spec_01.dat"
    assert data["last_upload_at"]


def test_process_measurement_files_records_per_file_errors_without_crashing(tmp_path):
    from nanonis_importer import nanonis_importer

    data_folder = tmp_path / "run_importer_err"
    data_folder.mkdir()
    (data_folder / "bad.sxm").write_text("sxm", encoding="utf-8")
    (data_folder / "bad.dat").write_text("dat", encoding="utf-8")
    log_file = tmp_path / "SESS-ERR.json"

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    def fake_spm(path):
        obj = MagicMock()
        obj.record_datetime = datetime.datetime(
            2026, 11, 26, 10, 0, 1 if path.endswith(".sxm") else 2
        )
        obj.signals = {"I": {}}
        obj.measurement_type = "bias"
        return obj

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=RuntimeError("bad sxm"),
        ),
        patch(
            "nanonis_importer.nanonis_importer.demo_dat_flow",
            side_effect=ValueError("bad dat"),
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="https://openbis.local",
            token="tok-1",
            data_folder=str(data_folder),
            measurements_id="SESS-ERR",
            logging_filepath=str(log_file),
        )

    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["processed_files"] == []
    stages = {(e["stage"], e["file"], e["message"]) for e in data["recent_errors"]}
    assert ("sxm", "bad.sxm", "bad sxm") in stages
    assert ("dat", "bad.dat", "bad dat") in stages
    assert data["last_error"]["stage"] == "dat"
    assert data["last_error"]["message"] == "bad dat"


def test_process_measurement_files_handles_failed_openbis_connection_without_logout_crash(
    tmp_path,
):
    from nanonis_importer import nanonis_importer

    data_folder = tmp_path / "run_importer_auth"
    data_folder.mkdir()
    log_file = tmp_path / "SESS-AUTH.json"

    with patch("src.utils.connect_openbis", return_value=(None, {})):
        nanonis_importer.process_measurement_files(
            openbis_url="https://openbis.local",
            token="expired-tok",
            data_folder=str(data_folder),
            measurements_id="SESS-AUTH",
            logging_filepath=str(log_file),
        )

    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["token_expired"] is True
    assert data["last_error"]["stage"] == "auth"
    assert len(data["recent_errors"]) == 1


def test_run_upload_cycle_records_attachment_upload_and_annotates_imaging_fallback(
    tmp_path,
):
    from src import measurement_monitor, measurements_uploader

    data_folder = tmp_path / "fallback_run"
    data_folder.mkdir()
    bad_dat = data_folder / "Z-Spec01.dat"
    bad_dat.write_text("dat", encoding="utf-8")
    logs_dir = tmp_path / "logs" / "measurements"
    log_filepath, _ = measurements_uploader.init_or_load_measurement_log(
        "https://openbis.local", "tok-1", "SESS-FB", str(data_folder), logs_dir=logs_dir
    )

    mock_session = MagicMock()
    mock_session.is_session_active.return_value = True

    def fake_importer(url, tok, folder, sess_id, log_fp):
        def _mark_err(d):
            measurement_monitor.append_error_event(
                d, "Cannot parse Z-Spec", stage="dat", file_path=str(bad_dat)
            )

        measurement_monitor.update_measurement_log(log_fp, _mark_err)

    with (
        patch.object(
            measurements_uploader,
            "process_measurement_files",
            side_effect=fake_importer,
        ),
        patch("src.utils.create_openbis_dataset"),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
    ):
        measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token="tok-1",
            measurement_session_id="SESS-FB",
            logging_filepath=log_filepath,
        )

    data = json.loads(open(log_filepath, encoding="utf-8").read())
    assert str(bad_dat) in data["processed_files"]
    assert data["upload_history"][-1]["type"] == "ATTACHMENT"
    assert data["upload_history"][-1]["filename"] == "Z-Spec01.dat"
    assert data["last_error"] is not None
    assert "ATTACHMENT fallback" in data["last_error"]["message"]
    assert data["current_action"] == "Watching for new files"


def test_run_upload_cycle_transient_attachment_error_logs_without_raising_token_expired(
    tmp_path,
):
    from src import measurements_uploader

    data_folder = tmp_path / "transient_err_run"
    data_folder.mkdir()
    txt_file = data_folder / "notes.txt"
    txt_file.write_text("hello", encoding="utf-8")
    logs_dir = tmp_path / "logs" / "measurements"
    log_filepath, _ = measurements_uploader.init_or_load_measurement_log(
        "https://openbis.local", "tok-1", "SESS-TR", str(data_folder), logs_dir=logs_dir
    )

    mock_session = MagicMock()
    mock_session.is_session_active.return_value = True

    with (
        patch.object(measurements_uploader, "process_measurement_files"),
        patch(
            "src.utils.create_openbis_dataset", side_effect=RuntimeError("network blip")
        ),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
    ):
        measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token="tok-1",
            measurement_session_id="SESS-TR",
            logging_filepath=log_filepath,
        )

    data = json.loads(open(log_filepath, encoding="utf-8").read())
    assert data["processed_files"] == []
    assert data.get("token_expired", False) is False
    assert data["last_error"]["stage"] == "attachment"
    assert data["last_error"]["file"] == "notes.txt"
    assert "network blip" in data["last_error"]["message"]


def test_run_upload_cycle_midrun_expired_token_raises_token_expired_and_marks_log(
    tmp_path,
):
    from src import measurements_uploader

    data_folder = tmp_path / "midrun_expired_run"
    data_folder.mkdir()
    txt_file = data_folder / "notes.txt"
    txt_file.write_text("hello", encoding="utf-8")
    logs_dir = tmp_path / "logs" / "measurements"
    log_filepath, _ = measurements_uploader.init_or_load_measurement_log(
        "https://openbis.local",
        "tok-expired",
        "SESS-MID",
        str(data_folder),
        logs_dir=logs_dir,
    )

    mock_session = MagicMock()
    mock_session.is_session_active.return_value = False

    with (
        patch.object(measurements_uploader, "process_measurement_files"),
        patch("src.utils.create_openbis_dataset", side_effect=ValueError("Expired")),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
        pytest.raises(measurements_uploader.TokenExpiredError),
    ):
        measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token="tok-expired",
            measurement_session_id="SESS-MID",
            logging_filepath=log_filepath,
        )

    data = json.loads(open(log_filepath, encoding="utf-8").read())
    assert data["token_expired"] is True
    assert data["last_error"]["stage"] == "auth"
    assert "token" in data["current_action"].lower()


def test_uploader_main_startup_expired_token_marks_log_and_returns_1(
    tmp_path, monkeypatch
):
    from src import measurements_uploader

    data_folder = tmp_path / "startup_expired"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"
    monkeypatch.setattr(measurements_uploader, "MEASUREMENT_LOGS_FOLDER", logs_dir)

    mock_openbis = MagicMock()
    mock_openbis.set_token.side_effect = ValueError("Session token invalid")

    with patch.object(measurements_uploader, "Openbis", return_value=mock_openbis):
        rc = measurements_uploader.main(
            [
                "--openbis_url",
                "https://openbis.local",
                "--openbis_token",
                "bad-token",
                "--measurement_session_id",
                "SESS-START-EXP",
                "--data_folder",
                str(data_folder),
            ]
        )

    assert rc == 1
    data = json.loads((logs_dir / "SESS-START-EXP.json").read_text(encoding="utf-8"))
    assert data["token_expired"] is True
    assert data["last_error"]["stage"] == "auth"
    assert "token" in data["current_action"].lower()


def test_monitor_folder_invokes_heartbeat_callback_and_stops_on_interrupt(tmp_path):
    from src import measurements_uploader

    watch_dir = tmp_path / "watched"
    watch_dir.mkdir()
    beats = []

    def fake_heartbeat():
        beats.append(True)

    sleep_calls = {"n": 0}

    def fake_sleep(_sec):
        sleep_calls["n"] += 1
        if sleep_calls["n"] >= 2:
            raise KeyboardInterrupt

    with patch("time.sleep", side_effect=fake_sleep):
        measurements_uploader.monitor_folder(
            str(watch_dir),
            lambda _p: None,
            heartbeat_callback=fake_heartbeat,
            heartbeat_interval=0.0,
        )

    assert len(beats) >= 2


def test_dismiss_watchdog_entry_matches_only_session_id_when_folder_shared(tmp_path):
    from src import measurement_monitor

    registry = tmp_path / "active_watchdogs.json"
    shared_a = str(tmp_path / "shared_a")
    shared_b = str(tmp_path / "shared_b")
    measurement_monitor.save_watchdog_entries(
        [
            {
                "pid": os.getpid(),
                "monitored_folder": shared_a,
                "measurement_session_id": "SESS-LIVE",
                "status": "RUNNING",
            },
            {
                "pid": 2002,
                "monitored_folder": shared_a,
                "measurement_session_id": "SESS-OLD",
                "status": "STOPPED",
                "user_stopped": True,
            },
            {
                "pid": 2003,
                "monitored_folder": shared_b,
                "measurement_session_id": "SESS-STOP-1",
                "status": "STOPPED",
                "user_stopped": True,
            },
            {
                "pid": 2004,
                "monitored_folder": shared_b,
                "measurement_session_id": "SESS-STOP-2",
                "status": "EXITED",
                "user_stopped": False,
            },
        ],
        registry,
    )

    assert (
        measurement_monitor.dismiss_watchdog_entry(
            registry,
            measurement_session_id="SESS-OLD",
            pid=2002,
            data_folder=shared_a,
        )
        is True
    )
    remaining_ids = [
        e["measurement_session_id"]
        for e in measurement_monitor.load_watchdog_entries(registry)
    ]
    assert remaining_ids == ["SESS-LIVE", "SESS-STOP-1", "SESS-STOP-2"]

    assert (
        measurement_monitor.dismiss_watchdog_entry(
            registry,
            measurement_session_id="SESS-STOP-2",
            pid=2004,
            data_folder=shared_b,
        )
        is True
    )
    remaining_ids = [
        e["measurement_session_id"]
        for e in measurement_monitor.load_watchdog_entries(registry)
    ]
    assert remaining_ids == ["SESS-LIVE", "SESS-STOP-1"]


def test_update_measurement_log_and_nanonis_importer_preserve_concurrent_heartbeat(
    tmp_path,
):
    import threading

    from nanonis_importer import nanonis_importer
    from src import measurement_monitor, measurements_uploader

    # 1. Multi-threaded update_measurement_log serialization
    concurrent_log = tmp_path / "concurrent.json"
    measurement_monitor.atomic_write_json({"items": []}, concurrent_log)

    def _worker(idx):
        measurement_monitor.update_measurement_log(
            concurrent_log, lambda d, i=idx: d["items"].append(i)
        )

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(json.loads(concurrent_log.read_text(encoding="utf-8"))["items"]) == list(
        range(25)
    )

    # 2. nanonis_importer must not clobber heartbeat written during upload
    data_folder = tmp_path / "concurrent_importer"
    data_folder.mkdir()
    sxm_path = data_folder / "scan_hb.sxm"
    sxm_path.write_text("sxm", encoding="utf-8")
    log_file = tmp_path / "SESS-CONC.json"
    measurement_monitor.atomic_write_json(
        {
            "eln_url": "https://openbis.local",
            "eln_token": "tok-1",
            "measurement_session_id": "SESS-CONC",
            "data_folder": str(data_folder),
            "processed_files": [],
        },
        log_file,
    )

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    def fake_spm(_path):
        obj = MagicMock()
        obj.record_datetime = datetime.datetime(2026, 11, 26, 10, 0, 1)
        return obj

    def fake_sxm_flow(*_args, **_kwargs):
        # Heartbeat arrives on main thread mid-upload
        measurement_monitor.update_measurement_log(
            log_file,
            lambda d: d.update(
                {
                    "last_heartbeat_at": "2099-01-01T12:34:56+00:00",
                    "concurrent_marker": "from_heartbeat",
                }
            ),
        )

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=fake_sxm_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="https://openbis.local",
            token="tok-1",
            data_folder=str(data_folder),
            measurements_id="SESS-CONC",
            logging_filepath=str(log_file),
        )

    final_data = json.loads(log_file.read_text(encoding="utf-8"))
    assert final_data["last_heartbeat_at"] == "2099-01-01T12:34:56+00:00"
    assert final_data["concurrent_marker"] == "from_heartbeat"
    assert str(sxm_path) in final_data["processed_files"]

    # 3. Heartbeat helper does not clobber active upload action
    upload_in_progress = threading.Event()
    upload_in_progress.set()
    measurement_monitor.update_measurement_log(
        log_file, lambda d: d.update({"current_action": "Uploading big.sxm..."})
    )
    measurements_uploader.write_heartbeat(
        str(log_file),
        str(data_folder),
        upload_in_progress=upload_in_progress,
    )
    hb_data = json.loads(log_file.read_text(encoding="utf-8"))
    assert hb_data["current_action"] == "Uploading big.sxm..."


def test_uploader_main_missing_directory_at_startup_logs_error_and_returns_1(
    tmp_path, monkeypatch
):
    from nanonis_importer import nanonis_importer
    from src import measurements_uploader

    missing_dir = tmp_path / "does_not_exist"
    logs_dir = tmp_path / "logs" / "measurements"
    monkeypatch.setattr(measurements_uploader, "MEASUREMENT_LOGS_FOLDER", logs_dir)

    mock_openbis = MagicMock()
    with patch.object(measurements_uploader, "Openbis", return_value=mock_openbis):
        rc = measurements_uploader.main(
            [
                "--openbis_url",
                "https://openbis.local",
                "--openbis_token",
                "tok-ok",
                "--measurement_session_id",
                "SESS-NODIR",
                "--data_folder",
                str(missing_dir),
            ]
        )

    assert rc == 1
    data = json.loads((logs_dir / "SESS-NODIR.json").read_text(encoding="utf-8"))
    assert data["folder_accessible"] is False
    assert data["last_error"]["stage"] == "watcher"
    assert "does not exist" in data["current_action"].lower()

    # nanonis_importer.process_measurement_files must also catch missing folder and still logout
    imp_log = tmp_path / "SESS-IMP-NODIR.json"
    mock_session = MagicMock()
    mock_session.is_session_active.return_value = True
    with patch("src.utils.connect_openbis", return_value=(mock_session, None)):
        nanonis_importer.process_measurement_files(
            "https://openbis.local",
            "tok-ok",
            str(missing_dir),
            "SESS-IMP-NODIR",
            logging_filepath=str(imp_log),
        )
    mock_session.logout.assert_called_once()
    imp_data = json.loads(imp_log.read_text(encoding="utf-8"))
    assert imp_data["last_error"]["stage"] == "importer"


def test_uploader_main_sigterm_sets_stopped_cleanly_without_monitor_overwrite(
    tmp_path, monkeypatch
):
    from src import measurement_monitor, measurements_uploader

    data_folder = tmp_path / "sigterm_folder"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"
    monkeypatch.setattr(measurements_uploader, "MEASUREMENT_LOGS_FOLDER", logs_dir)

    registered = {}
    real_update = measurement_monitor.update_measurement_log
    in_handler = {"active": False}
    io_inside_handler = {"called": False}

    def tracked_update(filepath, updater):
        if in_handler["active"]:
            io_inside_handler["called"] = True
        return real_update(filepath, updater)

    def fake_signal(sig, handler):
        registered[sig] = handler

    def fake_cycle(**_kwargs):
        # Deliver SIGTERM during initial startup scan
        handler = registered[measurements_uploader.signal.SIGTERM]
        in_handler["active"] = True
        try:
            handler(measurements_uploader.signal.SIGTERM, None)
        finally:
            in_handler["active"] = False

    mock_openbis = MagicMock()
    with (
        patch.object(measurements_uploader, "Openbis", return_value=mock_openbis),
        patch.object(measurements_uploader.signal, "signal", side_effect=fake_signal),
        patch.object(
            measurements_uploader, "run_upload_cycle", side_effect=fake_cycle
        ),
        patch.object(
            measurement_monitor, "update_measurement_log", side_effect=tracked_update
        ),
    ):
        rc = measurements_uploader.main(
            [
                "--openbis_url",
                "https://openbis.local",
                "--openbis_token",
                "tok-ok",
                "--measurement_session_id",
                "SESS-TERM",
                "--data_folder",
                str(data_folder),
            ]
        )

    assert rc == 0
    assert io_inside_handler["called"] is False
    data = json.loads((logs_dir / "SESS-TERM.json").read_text(encoding="utf-8"))
    assert data["current_action"] == "Stopped"


def test_process_measurement_files_midrun_expired_token_marks_token_expired_and_stops(
    tmp_path,
):
    from nanonis_importer import nanonis_importer

    data_folder = tmp_path / "midrun_imp_exp"
    data_folder.mkdir()
    (data_folder / "a_first.sxm").write_text("sxm1", encoding="utf-8")
    (data_folder / "b_second.sxm").write_text("sxm2", encoding="utf-8")
    log_file = tmp_path / "SESS-IMP-MIDEXP.json"

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample
    mock_session.is_session_active.return_value = False

    def fake_spm(path):
        obj = MagicMock()
        obj.record_datetime = datetime.datetime(
            2026, 11, 26, 10, 0, 1 if "a_first" in path else 2
        )
        return obj

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=ValueError("Session token expired"),
        ) as mock_sxm_flow,
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="https://openbis.local",
            token="tok-expired",
            data_folder=str(data_folder),
            measurements_id="SESS-IMP-MIDEXP",
            logging_filepath=str(log_file),
        )

    assert mock_sxm_flow.call_count == 1
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["token_expired"] is True
    assert data["last_error"]["stage"] == "auth"


def test_build_watchdog_card_snapshot_redacts_eln_token_and_rejects_non_http_url(
    tmp_path,
):
    from src import measurement_monitor, measurements_uploader

    data_folder = tmp_path / "redact_run"
    data_folder.mkdir()
    txt_file = data_folder / "notes.txt"
    txt_file.write_text("hi", encoding="utf-8")
    meas_logs = tmp_path / "logs" / "measurements"
    meas_logs.mkdir(parents=True)

    secret_a = "super-secret-token-xyz"
    secret_b = "extra-active-token-999"
    proc_log = meas_logs / "SESS-SEC.log"
    proc_log.write_text(
        f"debug header token={secret_a}\nother line {secret_b}\n", encoding="utf-8"
    )
    (meas_logs / "SESS-SEC.json").write_text(
        json.dumps(
            {
                "eln_url": "javascript:alert(1)",
                "eln_token": secret_a,
                "measurement_session_id": "SESS-SEC",
                "data_folder": str(data_folder),
                "processed_files": [],
                "current_action": f"Failed with {secret_a}",
                "last_error": {
                    "stage": "attachment",
                    "file": "notes.txt",
                    "message": f"HTTP 401 token={secret_a}",
                    "timestamp": "2026-11-26T10:00:00+00:00",
                },
                "recent_errors": [
                    {
                        "stage": "attachment",
                        "file": "notes.txt",
                        "message": f"HTTP 401 token={secret_a} {secret_b}",
                        "timestamp": "2026-11-26T10:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    snap = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": os.getpid(),
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-SEC",
            "status": "RUNNING",
            "log_file": str(proc_log),
        },
        measurement_logs_dir=meas_logs,
        secret_tokens=[secret_b],
    )

    assert snap["session_url"] is None
    assert measurement_monitor.build_openbis_session_url(
        "javascript:alert(1)", "SESS-SEC"
    ) is None
    combined = "\n".join(
        snap["log_tail"]
        + [
            snap["current_action"],
            snap["last_error"]["message"],
            snap["recent_errors"][0]["message"],
        ]
    )
    assert secret_a not in combined
    assert secret_b not in combined
    assert "[REDACTED]" in combined

    # Exception message containing openbis_token is redacted in run_upload_cycle too
    log_fp, _ = measurements_uploader.init_or_load_measurement_log(
        "https://openbis.local", secret_a, "SESS-REDACT", str(data_folder), logs_dir=meas_logs
    )
    mock_session = MagicMock()
    mock_session.is_session_active.return_value = True
    with (
        patch.object(measurements_uploader, "process_measurement_files"),
        patch(
            "src.utils.create_openbis_dataset",
            side_effect=RuntimeError(f"request failed with {secret_a}"),
        ),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
    ):
        measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token=secret_a,
            measurement_session_id="SESS-REDACT",
            logging_filepath=log_fp,
        )
    redacted_data = json.loads(open(log_fp, encoding="utf-8").read())
    assert secret_a not in redacted_data["last_error"]["message"]
    assert "[REDACTED]" in redacted_data["last_error"]["message"]


def test_active_uploads_keep_heartbeat_fresh_and_update_current_action(tmp_path):
    from nanonis_importer import nanonis_importer
    from src import measurement_monitor

    now = datetime.datetime(2026, 11, 26, 14, 18, 0, tzinfo=datetime.timezone.utc)
    data_folder = tmp_path / "active_upload_run"
    data_folder.mkdir()
    meas_logs = tmp_path / "logs" / "measurements"
    meas_logs.mkdir(parents=True)

    # 1. Exact screenshot bug: last_heartbeat_at is 11m old, last_upload_at is 19s ago
    (meas_logs / "SESS-ACTIVE.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-ACTIVE",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "img0028.sxm")],
                "last_heartbeat_at": (now - datetime.timedelta(minutes=11)).isoformat(),
                "last_upload_at": (now - datetime.timedelta(seconds=19)).isoformat(),
                "last_uploaded_file": "img0028.sxm",
                "current_action": "Scanning & uploading files...",
            }
        ),
        encoding="utf-8",
    )
    snap = measurement_monitor.build_watchdog_card_snapshot(
        {
            "pid": os.getpid(),
            "monitored_folder": str(data_folder),
            "measurement_session_id": "SESS-ACTIVE",
            "status": "RUNNING",
        },
        measurement_logs_dir=meas_logs,
        now=now,
    )
    assert snap["heartbeat_stale"] is False
    assert snap["heartbeat_relative"] == "19s ago"

    # 2. append_upload_event & append_error_event refresh last_heartbeat_at
    log_dict = {}
    measurement_monitor.append_upload_event(
        log_dict, str(data_folder / "a.sxm"), "SXM", uploaded_at="2026-11-26T14:17:00+00:00"
    )
    assert log_dict["last_heartbeat_at"] == "2026-11-26T14:17:00+00:00"
    measurement_monitor.append_error_event(
        log_dict, "oops", stage="sxm", timestamp="2026-11-26T14:17:30+00:00"
    )
    assert log_dict["last_heartbeat_at"] == "2026-11-26T14:17:30+00:00"

    # 3. nanonis_importer updates current_action & last_heartbeat_at during SXM/DAT upload
    sxm_file = data_folder / "img0029.sxm"
    sxm_file.write_text("sxm", encoding="utf-8")
    imp_log = meas_logs / "SESS-IMP-PROG.json"
    imp_log.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-IMP-PROG",
                "data_folder": str(data_folder),
                "processed_files": [],
                "last_heartbeat_at": "2026-11-26T10:00:00+00:00",
                "current_action": "Scanning & uploading files...",
            }
        ),
        encoding="utf-8",
    )

    observed_actions = []
    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    def fake_spm(_p):
        obj = MagicMock()
        obj.record_datetime = datetime.datetime(2026, 11, 26, 10, 0, 1)
        return obj

    def fake_sxm_flow(*_args, **_kwargs):
        snap_during = json.loads(imp_log.read_text(encoding="utf-8"))
        observed_actions.append(
            (snap_during.get("current_action"), snap_during.get("last_heartbeat_at"))
        )

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=fake_sxm_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            "https://openbis.local",
            "tok-1",
            str(data_folder),
            "SESS-IMP-PROG",
            logging_filepath=str(imp_log),
        )

    assert len(observed_actions) == 1
    assert observed_actions[0][0] == "Uploading img0029.sxm..."
    assert observed_actions[0][1] != "2026-11-26T10:00:00+00:00"


def test_run_upload_cycle_returns_pending_count_and_clears_transient_error_on_retry_success(
    tmp_path,
):
    from src import measurements_uploader

    data_folder = tmp_path / "retry_clear_run"
    data_folder.mkdir()
    dat_file = data_folder / "dIdV_00010.dat"
    dat_file.write_text("dat", encoding="utf-8")
    logs_dir = tmp_path / "logs" / "measurements"
    log_fp, _ = measurements_uploader.init_or_load_measurement_log(
        "https://openbis.local", "tok-1", "SESS-RETRY", str(data_folder), logs_dir=logs_dir
    )

    mock_session = MagicMock()
    mock_session.is_session_active.return_value = True

    with (
        patch.object(measurements_uploader, "process_measurement_files"),
        patch(
            "src.utils.create_openbis_dataset",
            side_effect=RuntimeError("502:Proxy Error"),
        ),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
    ):
        pending = measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token="tok-1",
            measurement_session_id="SESS-RETRY",
            logging_filepath=log_fp,
        )

    assert pending == 1
    first_data = json.loads(open(log_fp, encoding="utf-8").read())
    assert first_data["last_error"]["file"] == "dIdV_00010.dat"
    assert "502" in first_data["last_error"]["message"]

    # Retry succeeds -> pending becomes 0, last_error clears, recent_errors history kept
    with (
        patch.object(measurements_uploader, "process_measurement_files"),
        patch("src.utils.create_openbis_dataset"),
        patch.object(measurements_uploader, "wait_for_file_ready", return_value=True),
    ):
        pending_after = measurements_uploader.run_upload_cycle(
            data_folder=str(data_folder),
            openbis_session=mock_session,
            openbis_url="https://openbis.local",
            openbis_token="tok-1",
            measurement_session_id="SESS-RETRY",
            logging_filepath=log_fp,
        )

    assert pending_after == 0
    second_data = json.loads(open(log_fp, encoding="utf-8").read())
    assert str(dat_file) in second_data["processed_files"]
    assert second_data["last_error"] is None
    assert len(second_data["recent_errors"]) == 1


def test_uploader_retry_scheduler_backoff_cap_and_main_integration(tmp_path, monkeypatch):
    from src import measurements_uploader

    # 1. Pure scheduler unit check: exponential backoff, cap at max_attempts, reset on success
    sched = measurements_uploader.RetryScheduler(
        backoff_schedule=(10.0, 20.0), max_attempts=3
    )
    sched.record_result(pending_count=1, now_mono=100.0)
    assert sched.is_due(105.0) is False
    assert sched.is_due(110.0) is True
    assert "retry" in sched.idle_action().lower()

    sched.mark_attempt_started()
    sched.record_result(pending_count=1, now_mono=110.0)
    assert sched.is_due(125.0) is False
    assert sched.is_due(130.0) is True

    sched.mark_attempt_started()
    sched.record_result(pending_count=1, now_mono=130.0)
    assert sched.is_due(150.0) is True

    sched.mark_attempt_started()
    sched.record_result(pending_count=1, now_mono=150.0)
    # 3 attempts exhausted -> no longer due
    assert sched.is_due(9999.0) is False
    assert "3 retries" in sched.idle_action().lower()

    # Reset on success
    sched.record_result(pending_count=0, now_mono=200.0)
    assert sched.idle_action() == "Watching for new files"
    assert sched.is_due(9999.0) is False

    # 2. Integration with main(): transient failure on startup triggers automatic retry in monitor_folder
    data_folder = tmp_path / "auto_retry_main"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"
    monkeypatch.setattr(measurements_uploader, "MEASUREMENT_LOGS_FOLDER", logs_dir)
    monkeypatch.setattr(
        measurements_uploader, "DEFAULT_RETRY_BACKOFF_SECONDS", (0.0,)
    )

    cycle_calls = {"n": 0}

    def fake_cycle(**_kwargs):
        cycle_calls["n"] += 1
        return 1 if cycle_calls["n"] == 1 else 0

    sleep_ticks = {"n": 0}

    def fake_sleep(_sec):
        sleep_ticks["n"] += 1
        if sleep_ticks["n"] >= 3:
            raise KeyboardInterrupt

    mock_openbis = MagicMock()
    with (
        patch.object(measurements_uploader, "Openbis", return_value=mock_openbis),
        patch.object(measurements_uploader, "run_upload_cycle", side_effect=fake_cycle),
        patch("time.sleep", side_effect=fake_sleep),
    ):
        rc = measurements_uploader.main(
            [
                "--openbis_url",
                "https://openbis.local",
                "--openbis_token",
                "tok-ok",
                "--measurement_session_id",
                "SESS-AUTORETRY",
                "--data_folder",
                str(data_folder),
            ]
        )

    assert rc == 0
    assert cycle_calls["n"] == 2
    final_log = json.loads(
        (logs_dir / "SESS-AUTORETRY.json").read_text(encoding="utf-8")
    )
    assert final_log["current_action"] == "Watching for new files"

    # 3. TokenExpiredError during scheduled retry exits cleanly with code 1
    cycle_calls_exp = {"n": 0}

    def fake_cycle_exp(**_kwargs):
        cycle_calls_exp["n"] += 1
        if cycle_calls_exp["n"] == 1:
            return 1
        raise measurements_uploader.TokenExpiredError("expired during retry")

    with (
        patch.object(measurements_uploader, "Openbis", return_value=mock_openbis),
        patch.object(
            measurements_uploader, "run_upload_cycle", side_effect=fake_cycle_exp
        ),
        patch("time.sleep", return_value=None),
    ):
        rc_exp = measurements_uploader.main(
            [
                "--openbis_url",
                "https://openbis.local",
                "--openbis_token",
                "tok-ok",
                "--measurement_session_id",
                "SESS-RETRY-EXP",
                "--data_folder",
                str(data_folder),
            ]
        )

    assert rc_exp == 1
    assert cycle_calls_exp["n"] == 2


def test_process_measurement_files_respects_stop_event_between_files(tmp_path):
    import threading

    from nanonis_importer import nanonis_importer

    data_folder = tmp_path / "stop_mid_cycle"
    data_folder.mkdir()
    (data_folder / "a_01.sxm").write_text("sxm1", encoding="utf-8")
    (data_folder / "b_02.sxm").write_text("sxm2", encoding="utf-8")
    log_file = tmp_path / "SESS-STOP-MID.json"

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    stop_event = threading.Event()
    uploaded = []

    def fake_spm(path):
        obj = MagicMock()
        obj.record_datetime = datetime.datetime(
            2026, 11, 26, 10, 0, 1 if "a_01" in path else 2
        )
        return obj

    def fake_sxm_flow(_session, file_path, **_kwargs):
        uploaded.append(os.path.basename(file_path))
        stop_event.set()  # SIGTERM arrives during upload of first file

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", side_effect=fake_spm),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=fake_sxm_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            "https://openbis.local",
            "tok-1",
            str(data_folder),
            "SESS-STOP-MID",
            logging_filepath=str(log_file),
            stop_event=stop_event,
        )

    assert uploaded == ["a_01.sxm"]
