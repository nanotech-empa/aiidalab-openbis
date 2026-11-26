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
