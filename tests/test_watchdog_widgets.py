import json
import os
import signal
from unittest.mock import MagicMock, patch

import ipywidgets as ipw
import pytest


@pytest.fixture
def watchdog_module(tmp_path, monkeypatch):
    from src import utils

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, {}))
    from src import watchdog_widgets

    logs_dir = tmp_path / "logs"
    meas_logs_dir = logs_dir / "measurements"
    meas_logs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(watchdog_widgets, "LOGS_FOLDER", logs_dir)
    monkeypatch.setattr(watchdog_widgets, "MEASUREMENT_LOGS_FOLDER", meas_logs_dir)
    monkeypatch.setitem(
        watchdog_widgets.OPENBIS_OBJECT_TYPES,
        "Measurement Session",
        "MEASUREMENT_SESSION",
    )
    return watchdog_widgets


def _make_running_widget(watchdog_module, logs_dir):
    widget = watchdog_module.RunningMeasurementWatchdogsWidget.__new__(
        watchdog_module.RunningMeasurementWatchdogsWidget
    )
    ipw.VBox.__init__(widget)
    widget.openbis_session = MagicMock()
    widget.session_data = {"url": "https://openbis.local", "token": "tok-1"}
    widget.logs_folder = logs_dir
    widget.running_watchdogs_widget = ipw.SelectMultiple()
    widget.refresh_watchdog_list()
    return widget


def test_detach_measurement_logs_for_folder_detaches_all_matching_logs_and_preserves_history(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs" / "measurements"
    run1 = str(tmp_path / "run1")
    run2 = str(tmp_path / "run2")

    log_a = logs_dir / "SESS-A.json"
    log_b = logs_dir / "SESS-B.json"
    log_other = logs_dir / "SESS-OTHER.json"

    log_a.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-A",
                "data_folder": f"{run1}/",
                "processed_files": [f"{run1}/scan1.sxm"],
            }
        )
    )
    log_b.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-B",
                "data_folder": run1,
                "processed_files": [f"{run1}/scan2.sxm"],
            }
        )
    )
    log_other.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-OTHER",
                "data_folder": run2,
                "processed_files": [f"{run2}/other.sxm"],
            }
        )
    )

    detached = watchdog_module.detach_measurement_logs_for_folder(
        run1, replaced_by_session_id="SESS-NEW", logs_dir=logs_dir
    )

    assert set(detached) == {log_a, log_b}
    assert (
        watchdog_module.find_measurement_logs_for_folder(run1, logs_dir=logs_dir) == []
    )

    data_a = json.loads(log_a.read_text())
    assert data_a["data_folder"] is None
    assert os.path.normpath(data_a["previous_data_folder"]) == os.path.normpath(run1)
    assert data_a["replaced_by_session_id"] == "SESS-NEW"
    assert data_a["detached_at"]
    assert data_a["processed_files"] == [f"{run1}/scan1.sxm"]

    data_b = json.loads(log_b.read_text())
    assert data_b["data_folder"] is None
    assert data_b["replaced_by_session_id"] == "SESS-NEW"
    assert data_b["processed_files"] == [f"{run1}/scan2.sxm"]

    data_other = json.loads(log_other.read_text())
    assert data_other["data_folder"] == run2


def test_get_active_watchdogs_for_folder_prunes_dead_pids_and_normalizes_paths(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    run1 = str(tmp_path / "run1")
    run2 = str(tmp_path / "run2")
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 1111,
                    "monitored_folder": f"{run1}/",
                    "measurement_session_id": "SESS-LIVE",
                },
                {
                    "pid": 2222,
                    "monitored_folder": run1,
                    "measurement_session_id": "SESS-DEAD",
                },
                {
                    "pid": 3333,
                    "monitored_folder": run2,
                    "measurement_session_id": "SESS-OTHER",
                },
            ]
        )
    )

    def fake_kill(pid, sig):
        if pid == 2222:
            raise ProcessLookupError

    with patch("os.kill", side_effect=fake_kill):
        running_widget = _make_running_widget(watchdog_module, logs_dir)
        matches = running_widget.get_active_watchdogs_for_folder(run1)

    assert len(matches) == 1
    assert matches[0]["pid"] == 1111
    assert matches[0]["measurement_session_id"] == "SESS-LIVE"

    stored = json.loads(active_file.read_text())
    assert [entry["pid"] for entry in stored] == [1111, 3333]


def test_stop_watchdog_pids_terminates_updates_ui_and_json_without_alert_when_silent(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    run1 = str(tmp_path / "run1")
    run2 = str(tmp_path / "run2")
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 1234,
                    "monitored_folder": run1,
                    "measurement_session_id": "SESS-1",
                },
                {
                    "pid": 5678,
                    "monitored_folder": run2,
                    "measurement_session_id": "SESS-2",
                },
            ]
        )
    )

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == signal.SIGTERM and pid == 9999:
            raise ProcessLookupError

    with (
        patch("os.kill", side_effect=fake_kill),
        patch.object(watchdog_module, "display") as mock_display,
    ):
        running_widget = _make_running_widget(watchdog_module, logs_dir)
        stopped = running_widget.stop_watchdog_pids([1234, 9999], notify=False)

    assert (1234, signal.SIGTERM) in kill_calls
    assert (9999, signal.SIGTERM) in kill_calls
    assert stopped == [1234, 9999]
    assert mock_display.call_count == 0
    assert list(running_widget.running_watchdogs_widget.options) == [(run2, 5678)]
    stored = json.loads(active_file.read_text())
    assert stored == [
        {"pid": 5678, "monitored_folder": run2, "measurement_session_id": "SESS-2"}
    ]


def test_add_active_watchdog_appends_entry_and_updates_options(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    run1 = str(tmp_path / "run1")
    running_widget = _make_running_widget(watchdog_module, logs_dir)

    running_widget.add_active_watchdog(4321, f"{run1}/", "SESS-9")

    assert list(running_widget.running_watchdogs_widget.options) == [
        (os.path.normpath(run1), 4321)
    ]
    stored = json.loads((logs_dir / "active_watchdogs.json").read_text())
    assert stored == [
        {
            "pid": 4321,
            "monitored_folder": os.path.normpath(run1),
            "measurement_session_id": "SESS-9",
        }
    ]


def _make_generator_widget(watchdog_module, tmp_path, running_widget=None):
    logs_dir = tmp_path / "logs"
    meas_logs_dir = logs_dir / "measurements"
    meas_logs_dir.mkdir(parents=True, exist_ok=True)
    if running_widget is None:
        running_widget = _make_running_widget(watchdog_module, logs_dir)

    widget = watchdog_module.GenerateMeasurementsWatchdogWidget.__new__(
        watchdog_module.GenerateMeasurementsWatchdogWidget
    )
    ipw.VBox.__init__(widget)
    widget.openbis_session = MagicMock()
    widget.session_data = {"url": "https://openbis.local", "token": "tok-new"}
    widget.running_watchdogs_widget = running_widget
    widget.watchdog_processes = []
    widget.measurement_logs_folder = meas_logs_dir
    widget.measurement_session_name_text = ipw.Text(value="MEAS_New")
    return widget


def _fake_session(perm_id, name):
    session = MagicMock()
    session.permId = perm_id
    session.props = {"name": name}
    return session


def test_find_existing_folder_tracking_returns_none_for_untracked_folder(
    watchdog_module, tmp_path
):
    widget = _make_generator_widget(watchdog_module, tmp_path)
    data_folder = tmp_path / "untracked_run"
    data_folder.mkdir()

    assert widget._find_existing_folder_tracking(str(data_folder)) is None


def test_find_existing_folder_tracking_detects_stopped_previously_linked_session(
    watchdog_module, tmp_path
):
    widget = _make_generator_widget(watchdog_module, tmp_path)
    data_folder = tmp_path / "stopped_run"
    data_folder.mkdir()
    log_path = widget.measurement_logs_folder / "SESS-OLD.json"
    log_path.write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "scan_001.sxm")],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")

    with patch("src.utils.get_openbis_object", return_value=old_session):
        info = widget._find_existing_folder_tracking(f"{data_folder}/")

    assert info is not None
    assert info["is_running"] is False
    assert info["active_pids"] == []
    assert info["session_id"] == "SESS-OLD"
    assert info["session_name"] == "MEAS_Old"
    assert info["measurement_session"] is old_session
    assert info["log_filepath"] == log_path


def test_find_existing_folder_tracking_prunes_stale_stopped_log_when_session_deleted(
    watchdog_module, tmp_path
):
    widget = _make_generator_widget(watchdog_module, tmp_path)
    data_folder = tmp_path / "deleted_session_run"
    data_folder.mkdir()
    log_path = widget.measurement_logs_folder / "SESS-DELETED.json"
    log_path.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-DELETED",
                "data_folder": str(data_folder),
                "processed_files": [],
            }
        )
    )

    with patch("src.utils.get_openbis_object", side_effect=ValueError("Not found")):
        info = widget._find_existing_folder_tracking(str(data_folder))

    assert info is None
    assert not log_path.exists()


def test_find_existing_folder_tracking_detects_running_watchdog_with_session(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "running_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 5555,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-RUN",
                }
            ]
        )
    )
    run_session = _fake_session("SESS-RUN", "MEAS_Run")

    with (
        patch("os.kill"),
        patch("src.utils.get_openbis_object", return_value=run_session),
    ):
        widget = _make_generator_widget(watchdog_module, tmp_path)
        info = widget._find_existing_folder_tracking(str(data_folder))

    assert info is not None
    assert info["is_running"] is True
    assert info["active_pids"] == [5555]
    assert info["session_id"] == "SESS-RUN"
    assert info["session_name"] == "MEAS_Run"
    assert info["measurement_session"] is run_session


def test_find_existing_folder_tracking_detects_running_watchdog_when_openbis_session_deleted(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "running_deleted_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 5555,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-GONE",
                }
            ]
        )
    )

    with (
        patch("os.kill"),
        patch("src.utils.get_openbis_object", side_effect=ValueError("Deleted")),
    ):
        widget = _make_generator_widget(watchdog_module, tmp_path)
        info = widget._find_existing_folder_tracking(str(data_folder))

    assert info is not None
    assert info["is_running"] is True
    assert info["active_pids"] == [5555]
    assert info["session_id"] == "SESS-GONE"
    assert info["measurement_session"] is None


def test_resume_existing_measurement_session_refreshes_token_and_preserves_processed_files(
    watchdog_module, tmp_path
):
    widget = _make_generator_widget(watchdog_module, tmp_path)
    data_folder = tmp_path / "resume_run"
    data_folder.mkdir()
    log_path = widget.measurement_logs_folder / "SESS-OLD.json"
    log_path.write_text(
        json.dumps(
            {
                "eln_url": "https://old.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "a.sxm")],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    tracking_info = {
        "is_running": False,
        "active_pids": [],
        "measurement_session": old_session,
        "session_id": "SESS-OLD",
        "session_name": "MEAS_Old",
        "log_filepath": log_path,
        "logging_data": json.loads(log_path.read_text()),
    }

    resumed = widget._resume_existing_measurement_session(tracking_info, f"{data_folder}/")

    assert resumed is old_session
    updated = json.loads(log_path.read_text())
    assert updated["eln_url"] == "https://openbis.local"
    assert updated["eln_token"] == "tok-new"
    assert updated["data_folder"] == os.path.normpath(str(data_folder))
    assert updated["processed_files"] == [str(data_folder / "a.sxm")]
