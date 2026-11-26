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
    by_pid = {entry["pid"]: entry for entry in stored}
    assert by_pid[1111]["status"] == "RUNNING"
    assert by_pid[3333]["status"] == "RUNNING"
    assert by_pid[2222]["status"] == "EXITED"
    assert by_pid[2222]["user_stopped"] is False


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
    assert len(stored) == 1
    assert stored[0]["pid"] == 5678
    assert stored[0]["monitored_folder"] == run2
    assert stored[0]["measurement_session_id"] == "SESS-2"
    assert stored[0]["status"] == "RUNNING"


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
    assert len(stored) == 1
    assert stored[0]["pid"] == 4321
    assert stored[0]["monitored_folder"] == os.path.normpath(run1)
    assert stored[0]["measurement_session_id"] == "SESS-9"
    assert stored[0]["status"] == "RUNNING"
    assert stored[0]["user_stopped"] is False
    assert stored[0]["started_at"]


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
    session.parents = []
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


def _make_full_generator_widget(
    watchdog_module, tmp_path, data_folder, session_name="MEAS_New"
):
    logs_dir = tmp_path / "logs"
    meas_logs_dir = logs_dir / "measurements"
    meas_logs_dir.mkdir(parents=True, exist_ok=True)
    running_widget = _make_running_widget(watchdog_module, logs_dir)

    fake_project = ipw.VBox()
    fake_project.project_dropdown = ipw.Dropdown(
        options=[("Select project...", "-1"), ("P1", "PROJ-1")], value="PROJ-1"
    )
    fake_experiment = ipw.VBox()
    fake_experiment.experiment_dropdown = ipw.Dropdown(
        options=[("Select experiment...", "-1"), ("E1", "EXP-1")], value="EXP-1"
    )
    fake_experiment.create_experiment_button = ipw.Button()
    fake_experiment.load_experiments = MagicMock()
    fake_sample = ipw.VBox()
    fake_sample.sample_dropdown = ipw.Dropdown(
        options=[("Select sample...", "-1"), ("S1", "SMP-1")], value="SMP-1"
    )
    fake_instrument = ipw.VBox()
    fake_instrument.instrument_dropdown = ipw.Dropdown(
        options=[("Select instrument...", "-1"), ("I1", "INST-1")], value="INST-1"
    )

    with (
        patch.object(
            watchdog_module.widgets, "SelectProjectWidget", return_value=fake_project
        ),
        patch.object(
            watchdog_module.widgets,
            "SelectExperimentWidget",
            return_value=fake_experiment,
        ),
        patch.object(
            watchdog_module.widgets, "SelectSampleWidget", return_value=fake_sample
        ),
        patch.object(
            watchdog_module.widgets,
            "SelectInstrumentWidget",
            return_value=fake_instrument,
        ),
    ):
        widget = watchdog_module.GenerateMeasurementsWatchdogWidget(
            MagicMock(),
            {"url": "https://openbis.local", "token": "tok-new"},
            running_widget,
        )

    widget.measurement_logs_folder = meas_logs_dir
    widget.measurement_session_name_text.value = session_name
    widget.select_measurements_folder_widget.reset(path=str(data_folder))
    return widget


def _extract_prompt_widgets(conflict_box):
    assert len(conflict_box.children) >= 2
    message_html = conflict_box.children[0]
    buttons_row = conflict_box.children[1]
    buttons = {btn.description: btn for btn in buttons_row.children}
    return message_html, buttons


def test_generate_watchdog_untracked_folder_starts_immediately_without_prompt(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "fresh_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
    new_session = _fake_session("SESS-NEW-1", "MEAS_New")
    fake_proc = MagicMock(pid=7001)

    with (
        patch("src.utils.create_openbis_object", return_value=new_session) as mock_create,
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget.generate_watchdog(None)

    assert mock_create.call_count == 1
    assert mock_popen.call_count == 1
    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False
    log_data = json.loads(
        (widget.measurement_logs_folder / "SESS-NEW-1.json").read_text()
    )
    assert log_data["processed_files"] == []
    assert log_data["data_folder"] == os.path.normpath(str(data_folder))


def test_generate_watchdog_running_folder_shows_prompt_and_continue_leaves_running(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "running_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 4444,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-RUN",
                }
            ]
        )
    )
    run_session = _fake_session("SESS-RUN", "MEAS_Running")

    with (
        patch("os.kill"),
        patch("src.utils.get_openbis_object", return_value=run_session),
        patch("src.utils.create_openbis_object") as mock_create,
        patch("subprocess.Popen") as mock_popen,
        patch.object(watchdog_module, "display") as mock_display,
    ):
        widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
        widget.generate_watchdog(None)

        assert widget.folder_conflict_box.layout.display != "none"
        assert widget.generate_watchdog_button.disabled is True
        message_html, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        assert "MEAS_Running" in message_html.value
        assert "SESS-RUN" in message_html.value
        assert "4444" in message_html.value
        assert buttons["Continue existing session"].button_style == "success"
        assert buttons["Continue existing session"].disabled is False
        assert buttons["Switch to new session"].button_style == "danger"
        assert "Cancel" in buttons

        buttons["Continue existing session"].click()

    assert mock_create.call_count == 0
    assert mock_popen.call_count == 0
    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False
    assert mock_display.call_count >= 1


def test_generate_watchdog_stopped_folder_continue_resumes_existing_session(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "stopped_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
    log_path = widget.measurement_logs_folder / "SESS-OLD.json"
    log_path.write_text(
        json.dumps(
            {
                "eln_url": "https://old.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "existing.sxm")],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    fake_proc = MagicMock(pid=8001)

    with (
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object") as mock_create,
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget.generate_watchdog(None)
        assert widget.folder_conflict_box.layout.display != "none"
        message_html, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        assert "MEAS_Old" in message_html.value
        assert "SESS-OLD" in message_html.value
        assert "not currently running" in message_html.value.lower()

        buttons["Continue existing session"].click()

    assert mock_create.call_count == 0
    assert mock_popen.call_count == 1
    popen_cmd = mock_popen.call_args.args[0]
    assert "SESS-OLD" in popen_cmd
    updated_log = json.loads(log_path.read_text())
    assert updated_log["eln_token"] == "tok-new"
    assert updated_log["processed_files"] == [str(data_folder / "existing.sxm")]
    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False


def test_generate_watchdog_running_folder_switch_stops_old_detaches_logs_and_starts_new_fresh(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "running_switch_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 4444,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-OLD-1",
                }
            ]
        )
    )
    old_session = _fake_session("SESS-OLD-1", "MEAS_Wrong")
    new_session = _fake_session("SESS-NEW-2", "MEAS_Correct")
    fake_old_proc = MagicMock(pid=4444)
    fake_new_proc = MagicMock(pid=9002)
    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))

    with (
        patch("os.kill", side_effect=fake_kill),
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object", return_value=new_session) as mock_create,
        patch("subprocess.Popen", return_value=fake_new_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget = _make_full_generator_widget(
            watchdog_module, tmp_path, data_folder, session_name="MEAS_Correct"
        )
        widget.watchdog_processes.append(fake_old_proc)
        log_old_1 = widget.measurement_logs_folder / "SESS-OLD-1.json"
        log_old_2 = widget.measurement_logs_folder / "SESS-OLD-0.json"
        log_old_1.write_text(
            json.dumps(
                {
                    "measurement_session_id": "SESS-OLD-1",
                    "data_folder": str(data_folder),
                    "processed_files": [str(data_folder / "scan1.sxm")],
                }
            )
        )
        log_old_2.write_text(
            json.dumps(
                {
                    "measurement_session_id": "SESS-OLD-0",
                    "data_folder": f"{data_folder}/",
                    "processed_files": [str(data_folder / "scan0.sxm")],
                }
            )
        )

        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        assert buttons["Switch to new session"].button_style == "danger"
        buttons["Switch to new session"].click()

    assert mock_create.call_count == 1
    assert (4444, signal.SIGTERM) in kill_calls
    assert mock_popen.call_count == 1
    assert "SESS-NEW-2" in mock_popen.call_args.args[0]
    assert [p.pid for p in widget.watchdog_processes] == [9002]
    assert list(widget.running_watchdogs_widget.running_watchdogs_widget.options) == [
        (os.path.normpath(str(data_folder)), 9002)
    ]

    stored_active = json.loads((logs_dir / "active_watchdogs.json").read_text())
    assert len(stored_active) == 1
    assert stored_active[0]["pid"] == 9002
    assert stored_active[0]["monitored_folder"] == os.path.normpath(str(data_folder))
    assert stored_active[0]["measurement_session_id"] == "SESS-NEW-2"
    assert stored_active[0]["status"] == "RUNNING"
    assert stored_active[0]["session_name"] == "MEAS_Correct"
    assert stored_active[0]["log_file"].endswith("SESS-NEW-2.log")

    old1_data = json.loads(log_old_1.read_text())
    old2_data = json.loads(log_old_2.read_text())
    assert old1_data["data_folder"] is None
    assert old1_data["replaced_by_session_id"] == "SESS-NEW-2"
    assert old2_data["data_folder"] is None
    assert old2_data["replaced_by_session_id"] == "SESS-NEW-2"

    new_log_path = widget.measurement_logs_folder / "SESS-NEW-2.json"
    new_log_data = json.loads(new_log_path.read_text())
    assert new_log_data["data_folder"] == os.path.normpath(str(data_folder))
    assert new_log_data["processed_files"] == []
    active_logs = watchdog_module.find_measurement_logs_for_folder(
        str(data_folder), logs_dir=widget.measurement_logs_folder
    )
    assert [p for p, _ in active_logs] == [new_log_path]


def test_generate_watchdog_stopped_folder_switch_detaches_old_log_and_uploads_all_files(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "stopped_switch_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(
        watchdog_module, tmp_path, data_folder, session_name="MEAS_Fresh"
    )
    old_log = widget.measurement_logs_folder / "SESS-OLD.json"
    old_log.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "scan1.sxm")],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    new_session = _fake_session("SESS-FRESH", "MEAS_Fresh")
    fake_proc = MagicMock(pid=9111)

    with (
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object", return_value=new_session) as mock_create,
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        buttons["Switch to new session"].click()

    assert mock_create.call_count == 1
    assert mock_popen.call_count == 1
    assert "SESS-FRESH" in mock_popen.call_args.args[0]
    assert json.loads(old_log.read_text())["data_folder"] is None
    new_log = json.loads(
        (widget.measurement_logs_folder / "SESS-FRESH.json").read_text()
    )
    assert new_log["processed_files"] == []
    assert new_log["data_folder"] == os.path.normpath(str(data_folder))


def test_generate_watchdog_switch_failure_preserves_old_watchdog_and_log(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "switch_fail_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 4444,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-OLD",
                }
            ]
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))

    with (
        patch("os.kill", side_effect=fake_kill),
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch(
            "src.utils.create_openbis_object", side_effect=RuntimeError("openBIS down")
        ),
        patch("subprocess.Popen") as mock_popen,
        patch.object(watchdog_module, "display") as mock_display,
    ):
        widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
        old_log = widget.measurement_logs_folder / "SESS-OLD.json"
        old_log.write_text(
            json.dumps(
                {
                    "measurement_session_id": "SESS-OLD",
                    "data_folder": str(data_folder),
                    "processed_files": [str(data_folder / "scan1.sxm")],
                }
            )
        )
        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        buttons["Switch to new session"].click()

    assert (4444, signal.SIGTERM) not in kill_calls
    assert mock_popen.call_count == 0
    assert json.loads(old_log.read_text())["data_folder"] == str(data_folder)
    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False
    assert mock_display.call_count >= 1


def test_generate_watchdog_running_with_deleted_openbis_session_disables_continue_allows_switch(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "running_deleted_session_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 6666,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-DELETED",
                }
            ]
        )
    )
    new_session = _fake_session("SESS-NEW-3", "MEAS_Recovered")
    fake_proc = MagicMock(pid=9333)
    kill_calls = []

    with (
        patch("os.kill", side_effect=lambda pid, sig: kill_calls.append((pid, sig))),
        patch("src.utils.get_openbis_object", side_effect=ValueError("Deleted")),
        patch("src.utils.create_openbis_object", return_value=new_session),
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        assert buttons["Continue existing session"].disabled is True
        assert buttons["Switch to new session"].disabled is False
        buttons["Switch to new session"].click()

    assert (6666, signal.SIGTERM) in kill_calls
    assert mock_popen.call_count == 1
    assert "SESS-NEW-3" in mock_popen.call_args.args[0]


def test_generate_watchdog_cancel_dismisses_prompt_without_changes(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "cancel_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
    old_log = widget.measurement_logs_folder / "SESS-OLD.json"
    old_log.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")

    with (
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object") as mock_create,
        patch("subprocess.Popen") as mock_popen,
    ):
        widget.generate_watchdog(None)
        assert widget.folder_conflict_box.layout.display != "none"
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        buttons["Cancel"].click()

    assert mock_create.call_count == 0
    assert mock_popen.call_count == 0
    assert json.loads(old_log.read_text())["data_folder"] == str(data_folder)
    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False


def test_changing_folder_clears_open_confirmation_prompt_and_html_escapes_names(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "escape_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
    old_log = widget.measurement_logs_folder / "SESS-XSS.json"
    old_log.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-XSS",
                "data_folder": str(data_folder),
                "processed_files": [],
            }
        )
    )
    old_session = _fake_session("SESS-XSS", "<script>alert(1)</script>")

    with patch("src.utils.get_openbis_object", return_value=old_session):
        widget.generate_watchdog(None)

    message_html, _ = _extract_prompt_widgets(widget.folder_conflict_box)
    assert "<script>" not in message_html.value
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in message_html.value

    chooser = widget.select_measurements_folder_widget
    assert chooser._callback is not None
    chooser._callback(chooser)

    assert widget.folder_conflict_box.layout.display == "none"
    assert widget.generate_watchdog_button.disabled is False


def test_double_click_switch_and_continue_only_executes_once(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "reentrancy_switch_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 4444,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-OLD",
                }
            ]
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    new_session = _fake_session("SESS-NEW", "MEAS_New")
    fake_proc = MagicMock(pid=9501)
    switch_btn_ref = []
    reentered = {"switch": False}

    def slow_create(*args, **kwargs):
        # Simulate a second click arriving while create_openbis_object is in flight
        if not reentered["switch"]:
            reentered["switch"] = True
            switch_btn_ref[0].click()
        return new_session

    with (
        patch("os.kill"),
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object", side_effect=slow_create) as mock_create,
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)
        switch_btn_ref.append(buttons["Switch to new session"])
        buttons["Switch to new session"].click()

    assert mock_create.call_count == 1
    assert mock_popen.call_count == 1

    # Also verify double-click on Continue for a stopped folder only starts once
    stopped_folder = tmp_path / "reentrancy_continue_run"
    stopped_folder.mkdir()
    widget2 = _make_full_generator_widget(watchdog_module, tmp_path, stopped_folder)
    (widget2.measurement_logs_folder / "SESS-STOP.json").write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-STOP",
                "data_folder": str(stopped_folder),
                "processed_files": [],
            }
        )
    )
    stopped_session = _fake_session("SESS-STOP", "MEAS_Stopped")
    continue_btn_ref = []
    reentered_continue = {"done": False}

    def slow_popen(*args, **kwargs):
        if not reentered_continue["done"]:
            reentered_continue["done"] = True
            continue_btn_ref[0].click()
        return MagicMock(pid=9502)

    with (
        patch("src.utils.get_openbis_object", return_value=stopped_session),
        patch("subprocess.Popen", side_effect=slow_popen) as mock_popen2,
        patch.object(watchdog_module, "display"),
    ):
        widget2.generate_watchdog(None)
        _, buttons2 = _extract_prompt_widgets(widget2.folder_conflict_box)
        continue_btn_ref.append(buttons2["Continue existing session"])
        buttons2["Continue existing session"].click()

    assert mock_popen2.call_count == 1


def test_changing_dropdown_while_prompt_open_clears_confirmation_prompt(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "dropdown_change_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
    widget.select_sample_widget.sample_dropdown.options = [
        ("S1", "SMP-1"),
        ("S2", "SMP-2"),
    ]
    widget.select_instrument_widget.instrument_dropdown.options = [
        ("I1", "INST-1"),
        ("I2", "INST-2"),
    ]
    widget.select_experiment_widget.experiment_dropdown.options = [
        ("Select...", "-1"),
        ("E1", "EXP-1"),
        ("E2", "EXP-2"),
    ]
    widget.select_experiment_widget.experiment_dropdown.value = "EXP-1"
    widget.select_project_widget.project_dropdown.options = [
        ("P1", "PROJ-1"),
        ("P2", "PROJ-2"),
    ]
    (widget.measurement_logs_folder / "SESS-OLD.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-OLD",
                "data_folder": str(data_folder),
                "processed_files": [],
            }
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")

    for dropdown, new_value in [
        (widget.select_instrument_widget.instrument_dropdown, "INST-2"),
        (widget.select_experiment_widget.experiment_dropdown, "EXP-2"),
        (widget.select_project_widget.project_dropdown, "PROJ-2"),
        (widget.select_sample_widget.sample_dropdown, "SMP-2"),
    ]:
        with patch("src.utils.get_openbis_object", return_value=old_session):
            widget.generate_watchdog(None)
            assert widget.folder_conflict_box.layout.display != "none"
            assert widget.generate_watchdog_button.disabled is True

            dropdown.value = new_value

            assert widget.folder_conflict_box.layout.display == "none"
            assert widget.generate_watchdog_button.disabled is False
            assert widget._pending_folder_conflict is None


def test_continue_rechecks_live_status_and_resumes_if_watchdog_stopped_while_prompt_open(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    data_folder = tmp_path / "live_recheck_run"
    data_folder.mkdir()
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": 4444,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-OLD",
                }
            ]
        )
    )
    old_session = _fake_session("SESS-OLD", "MEAS_Old")
    pid_alive = {"4444": True}

    def fake_kill(pid, sig):
        if sig == 0 and pid == 4444 and not pid_alive["4444"]:
            raise ProcessLookupError

    fake_proc = MagicMock(pid=9600)
    with (
        patch("os.kill", side_effect=fake_kill),
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget = _make_full_generator_widget(watchdog_module, tmp_path, data_folder)
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

        # Prompt opens while PID 4444 is running
        widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget.folder_conflict_box)

        # Watchdog exits before user clicks Continue
        pid_alive["4444"] = False
        buttons["Continue existing session"].click()

    assert mock_popen.call_count == 1
    assert "SESS-OLD" in mock_popen.call_args.args[0]
    assert json.loads(log_path.read_text())["processed_files"] == [
        str(data_folder / "a.sxm")
    ]

    # Also verify graceful handling if the old session was deleted in openBIS before Continue
    deleted_folder = tmp_path / "deleted_while_open_run"
    deleted_folder.mkdir()
    widget2 = _make_full_generator_widget(watchdog_module, tmp_path, deleted_folder)
    (widget2.measurement_logs_folder / "SESS-VANISH.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-VANISH",
                "data_folder": str(deleted_folder),
                "processed_files": [],
            }
        )
    )
    vanish_session = _fake_session("SESS-VANISH", "MEAS_Vanish")
    get_side_effects = [vanish_session, ValueError("Deleted before click")]

    with (
        patch("src.utils.get_openbis_object", side_effect=get_side_effects),
        patch("subprocess.Popen") as mock_popen2,
        patch.object(watchdog_module, "display") as mock_display2,
    ):
        widget2.generate_watchdog(None)
        _, buttons2 = _extract_prompt_widgets(widget2.folder_conflict_box)
        buttons2["Continue existing session"].click()

    assert mock_popen2.call_count == 0
    assert mock_display2.call_count >= 1


def test_refresh_watchdog_list_reaps_zombie_child_and_marks_not_running(
    watchdog_module, tmp_path
):
    import subprocess
    import sys
    import time

    logs_dir = tmp_path / "logs"
    run_folder = str(tmp_path / "zombie_run")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        # Wait briefly so child exits and becomes a zombie (still unreaped)
        deadline = time.monotonic() + 5.0
        proc_stat = f"/proc/{proc.pid}/stat"
        while time.monotonic() < deadline:
            if os.path.exists(proc_stat):
                with open(proc_stat, "r", encoding="utf-8") as f:
                    if ") Z " in f.read():
                        break
            time.sleep(0.05)

        active_file = logs_dir / "active_watchdogs.json"
        active_file.write_text(
            json.dumps(
                [
                    {
                        "pid": proc.pid,
                        "monitored_folder": run_folder,
                        "measurement_session_id": "SESS-ZOMBIE",
                    }
                ]
            )
        )

        running_widget = _make_running_widget(watchdog_module, logs_dir)
        assert running_widget.get_active_watchdogs_for_folder(run_folder) == []
        assert list(running_widget.running_watchdogs_widget.options) == []
        entries = json.loads(active_file.read_text())
        assert len(entries) == 1
        assert entries[0]["pid"] == proc.pid
        assert entries[0]["status"] == "EXITED"
        assert entries[0]["user_stopped"] is False
    finally:
        proc.wait(timeout=5)


def _collect_html(widget):
    parts = []
    if isinstance(widget, ipw.HTML):
        parts.append(widget.value)
    for child in getattr(widget, "children", ()):
        parts.extend(_collect_html(child))
    return parts


def _collect_buttons(widget):
    buttons = {}
    if isinstance(widget, ipw.Button):
        buttons[widget.description] = widget
    for child in getattr(widget, "children", ()):
        buttons.update(_collect_buttons(child))
    return buttons


def test_running_watchdogs_widget_renders_cards_with_metadata_progress_afs_and_escaped_logs(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "meas_run"
    data_folder.mkdir()
    sxm1 = data_folder / "scan1.sxm"
    sxm2 = data_folder / "scan2.sxm"
    sxm1.write_text("x", encoding="utf-8")
    sxm2.write_text("x", encoding="utf-8")

    (meas_dir / "SESS-CARD.json").write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local/openbis/webapp/eln-lims/",
                "eln_token": "SUPER-SECRET-TOKEN",
                "measurement_session_id": "SESS-CARD",
                "data_folder": str(data_folder),
                "session_name": "MEAS_<script>xss</script>",
                "sample_name": "SampleA",
                "experiment_name": "Exp1",
                "instrument_name": "STM-1",
                "started_at": "2026-11-26T11:50:00+00:00",
                "last_heartbeat_at": "2026-11-26T11:59:55+00:00",
                "current_action": "Watching for new files",
                "processed_files": [str(sxm1)],
                "upload_history": [
                    {
                        "file": str(sxm1),
                        "filename": "scan1.sxm",
                        "type": "SXM",
                        "uploaded_at": "2026-11-26T11:55:00+00:00",
                    }
                ],
                "recent_errors": [
                    {
                        "timestamp": "2026-11-26T11:56:00+00:00",
                        "file": "bad<file>.dat",
                        "stage": "dat",
                        "message": "parse <boom>",
                    }
                ],
                "last_error": {
                    "timestamp": "2026-11-26T11:56:00+00:00",
                    "file": "bad<file>.dat",
                    "stage": "dat",
                    "message": "parse <boom>",
                },
            }
        ),
        encoding="utf-8",
    )
    (meas_dir / "SESS-CARD.log").write_text(
        "Started ok\n<script>log-xss</script>\n", encoding="utf-8"
    )
    (logs_dir / "active_watchdogs.json").write_text(
        json.dumps(
            [
                {
                    "pid": os.getpid(),
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-CARD",
                    "status": "RUNNING",
                    "log_file": str(meas_dir / "SESS-CARD.log"),
                }
            ]
        ),
        encoding="utf-8",
    )
    (logs_dir / "active_synchronisations.json").write_text(
        json.dumps(
            {
                "jobs": {
                    "sync1": {
                        "job_id": "sync1",
                        "status": "RUNNING",
                        "pid": os.getpid(),
                        "local_path": str(data_folder),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    widget = watchdog_module.RunningMeasurementWatchdogsWidget(
        MagicMock(), {"url": "https://openbis.local", "token": "SUPER-SECRET-TOKEN"}
    )
    assert hasattr(widget, "refresh_button")
    assert hasattr(widget, "watchdogs_box")
    assert isinstance(widget.watchdogs_accordion, ipw.Accordion)
    assert widget.watchdogs_box.children == (widget.watchdogs_accordion,)
    assert len(widget.watchdogs_accordion.children) == 1
    assert len(widget.watchdogs_accordion.titles) == 1
    assert "RUNNING" in widget.watchdogs_accordion.titles[0]
    assert "1/2 uploaded" in widget.watchdogs_accordion.titles[0]
    assert widget.watchdogs_accordion.selected_index == 0

    card = widget.watchdogs_accordion.children[0]
    card_html = "\n".join(_collect_html(card))
    assert "RUNNING" in card_html
    assert "SESS-CARD" in card_html
    assert "<div><b>Sample:</b> SampleA</div>" in card_html
    assert "<div><b>Experiment:</b> Exp1</div>" in card_html
    assert "<div><b>Instrument:</b> STM-1</div>" in card_html
    assert "SampleA · " not in card_html
    assert "1 / 2" in card_html
    assert "AFS Sync" in card_html
    assert "parse &lt;boom&gt;" in card_html
    assert "MEAS_&lt;script&gt;xss&lt;/script&gt;" in card_html
    assert "&lt;script&gt;log-xss&lt;/script&gt;" in card_html
    assert "<script>" not in card_html
    assert "SUPER-SECRET-TOKEN" not in card_html
    buttons = _collect_buttons(card)
    assert "Stop" in buttons
    assert buttons["Stop"].button_style == "danger"


def test_card_stop_transitions_to_stopped_and_dismiss_removes_entry_keeping_log(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "stop_dismiss_run"
    data_folder.mkdir()
    log_json = meas_dir / "SESS-SD.json"
    log_json.write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-SD",
                "data_folder": str(data_folder),
                "processed_files": [],
            }
        ),
        encoding="utf-8",
    )
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 7777,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-SD",
                    "status": "RUNNING",
                }
            ]
        ),
        encoding="utf-8",
    )

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))

    with patch("os.kill", side_effect=fake_kill):
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-1"}
        )
        card = widget.watchdogs_box.children[0]
        _collect_buttons(card)["Stop"].click()

    assert (7777, signal.SIGTERM) in kill_calls
    entries = json.loads(active_file.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["status"] == "STOPPED"
    assert entries[0]["user_stopped"] is True
    assert list(widget.running_watchdogs_widget.options) == []

    stopped_card = widget.watchdogs_box.children[0]
    stopped_buttons = _collect_buttons(stopped_card)
    assert "Resume" in stopped_buttons
    assert "Dismiss" in stopped_buttons

    stopped_buttons["Dismiss"].click()
    assert json.loads(active_file.read_text(encoding="utf-8")) == []
    assert widget.watchdogs_accordion.children == ()
    assert widget.watchdogs_accordion.titles == ()
    assert widget.watchdogs_accordion.selected_index is None
    assert log_json.exists()


def test_card_resume_refreshes_token_clears_error_and_restarts_worker(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "resume_card_run"
    data_folder.mkdir()
    log_json = meas_dir / "SESS-RES.json"
    log_json.write_text(
        json.dumps(
            {
                "eln_url": "https://old.local",
                "eln_token": "tok-expired",
                "measurement_session_id": "SESS-RES",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "old.sxm")],
                "token_expired": True,
                "last_error": {"stage": "auth", "message": "Token expired"},
                "recent_errors": [{"stage": "auth", "message": "Token expired"}],
            }
        ),
        encoding="utf-8",
    )
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 8888,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-RES",
                    "status": "EXITED",
                    "user_stopped": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    session_obj = _fake_session("SESS-RES", "MEAS_Resumed")
    resume_btn_ref = []
    reentered = {"done": False}

    def fake_popen(cmd, **kwargs):
        if not reentered["done"]:
            reentered["done"] = True
            resume_btn_ref[0].click()
        return MagicMock(pid=9901)

    with (
        patch("src.utils.get_openbis_object", return_value=session_obj),
        patch("subprocess.Popen", side_effect=fake_popen) as mock_popen,
        patch("os.kill"),
    ):
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-fresh"}
        )
        card = widget.watchdogs_box.children[0]
        assert "TOKEN EXPIRED" in "\n".join(_collect_html(card))
        resume_btn = _collect_buttons(card)["Resume"]
        resume_btn_ref.append(resume_btn)
        resume_btn.click()

    assert mock_popen.call_count == 1
    assert "SESS-RES" in mock_popen.call_args.args[0]
    assert "tok-fresh" in mock_popen.call_args.args[0]
    updated_log = json.loads(log_json.read_text(encoding="utf-8"))
    assert updated_log["eln_token"] == "tok-fresh"
    assert updated_log["token_expired"] is False
    assert updated_log["last_error"] is None
    assert len(updated_log["recent_errors"]) == 1
    assert updated_log["processed_files"] == [str(data_folder / "old.sxm")]

    entries = json.loads(active_file.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0]["pid"] == 9901
    assert entries[0]["status"] == "RUNNING"


def test_card_resume_blocks_when_folder_missing_already_running_or_session_deleted(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    existing_folder = tmp_path / "live_folder"
    existing_folder.mkdir()
    missing_folder = tmp_path / "gone_folder"
    deleted_sess_folder = tmp_path / "del_sess_folder"
    deleted_sess_folder.mkdir()

    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": os.getpid(),
                    "monitored_folder": str(existing_folder),
                    "measurement_session_id": "SESS-LIVE",
                    "status": "RUNNING",
                },
                {
                    "pid": 11111,
                    "monitored_folder": str(existing_folder),
                    "measurement_session_id": "SESS-CONFLICT",
                    "status": "STOPPED",
                    "user_stopped": True,
                },
                {
                    "pid": 11112,
                    "monitored_folder": str(missing_folder),
                    "measurement_session_id": "SESS-MISSING",
                    "status": "STOPPED",
                    "user_stopped": True,
                },
                {
                    "pid": 11113,
                    "monitored_folder": str(deleted_sess_folder),
                    "measurement_session_id": "SESS-DEL",
                    "status": "STOPPED",
                    "user_stopped": True,
                },
            ]
        ),
        encoding="utf-8",
    )

    def fake_get_openbis(session, sample_ident=None):
        if sample_ident == "SESS-DEL":
            raise ValueError("Deleted in openBIS")
        return _fake_session(sample_ident, f"MEAS_{sample_ident}")

    def _find_live_card(w, sid):
        assert w.watchdogs_box.children == (w.watchdogs_accordion,)
        for c in w.watchdogs_accordion.children:
            if sid in "\n".join(_collect_html(c)):
                return c
        raise AssertionError(f"Card for {sid} not found in live watchdogs_accordion.children")

    with (
        patch("src.utils.get_openbis_object", side_effect=fake_get_openbis),
        patch("subprocess.Popen") as mock_popen,
    ):
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-fresh"}
        )
        # Multiple watchdogs start collapsed, and refresh preserves selected panel
        assert widget.watchdogs_accordion.selected_index is None
        widget.watchdogs_accordion.selected_index = 2
        selected_title_before = widget.watchdogs_accordion.titles[2]
        widget.refresh_watchdog_list()
        assert widget.watchdogs_accordion.selected_index == 2
        assert widget.watchdogs_accordion.titles[2] == selected_title_before

        _collect_buttons(_find_live_card(widget, "SESS-CONFLICT"))["Resume"].click()
        assert (
            "already"
            in "\n".join(_collect_html(_find_live_card(widget, "SESS-CONFLICT"))).lower()
        )

        _collect_buttons(_find_live_card(widget, "SESS-MISSING"))["Resume"].click()
        assert (
            "not found"
            in "\n".join(_collect_html(_find_live_card(widget, "SESS-MISSING"))).lower()
        )

        _collect_buttons(_find_live_card(widget, "SESS-DEL"))["Resume"].click()
        assert (
            "openbis"
            in "\n".join(_collect_html(_find_live_card(widget, "SESS-DEL"))).lower()
        )

    assert mock_popen.call_count == 0


def test_generate_watchdog_switch_from_stopped_folder_removes_old_registry_entry(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "stopped_switch_run"
    data_folder.mkdir()

    (meas_dir / "SESS-OLD-STOP.json").write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-OLD-STOP",
                "data_folder": str(data_folder),
                "processed_files": [str(data_folder / "a.sxm")],
            }
        ),
        encoding="utf-8",
    )
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 55555,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-OLD-STOP",
                    "status": "STOPPED",
                    "user_stopped": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    new_session = _fake_session("SESS-NEW-SW", "MEAS_NewSwitch")
    old_session = _fake_session("SESS-OLD-STOP", "MEAS_OldStopped")

    def fake_get_openbis(session, sample_ident=None):
        if sample_ident == "SESS-OLD-STOP":
            return old_session
        return new_session

    with (
        patch("src.utils.get_openbis_object", side_effect=fake_get_openbis),
        patch("src.utils.create_openbis_object", return_value=new_session),
        patch("subprocess.Popen", return_value=MagicMock(pid=77777)),
        patch.object(watchdog_module, "display"),
        patch("os.kill"),
    ):
        gen_widget = _make_full_generator_widget(
            watchdog_module, tmp_path, data_folder, session_name="MEAS_NewSwitch"
        )
        gen_widget.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(gen_widget.folder_conflict_box)
        buttons["Switch to new session"].click()

    entries = json.loads(active_file.read_text(encoding="utf-8"))
    assert [e["measurement_session_id"] for e in entries] == ["SESS-NEW-SW"]
    assert entries[0]["pid"] == 77777


def test_stop_watchdog_pids_ignores_non_positive_pids(watchdog_module, tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with patch("os.kill") as mock_kill:
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-1"}
        )
        widget.stop_watchdog_pids([0, -1, True, "bad"], notify=False)
    mock_kill.assert_not_called()


def test_stop_watchdog_pids_escalates_to_sigkill_and_dismiss_shows_error_if_still_alive(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "stubborn_run"
    data_folder.mkdir()

    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 65663,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-STUBBORN",
                    "status": "RUNNING",
                }
            ]
        ),
        encoding="utf-8",
    )

    kill_calls = []
    killed = {"sigkill": False}

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        if sig == signal.SIGKILL:
            killed["sigkill"] = True

    with (
        patch("os.kill", side_effect=fake_kill),
        patch(
            "src.measurement_monitor.is_pid_running",
            side_effect=lambda _pid: not killed["sigkill"],
        ),
        patch("time.sleep", return_value=None),
    ):
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-1"}
        )
        widget.stop_watchdog_pids([65663], notify=False, remove_entries=False)

    assert (65663, signal.SIGTERM) in kill_calls
    assert (65663, signal.SIGKILL) in kill_calls

    # If a STOPPED card's PID is somehow still alive when Dismiss is clicked,
    # show a visible inline error message instead of silently doing nothing.
    with patch("src.measurement_monitor.is_pid_running", return_value=True):
        widget2 = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-1"}
        )
        card = widget2.watchdogs_accordion.children[0]
        _collect_buttons(card)["Dismiss"].click()
        live_html = "\n".join(_collect_html(widget2.watchdogs_accordion.children[0]))
        assert "still running" in live_html.lower() or "cannot dismiss" in live_html.lower()


def test_card_resume_handles_missing_credentials_or_popen_error_without_wiping_error_state(
    watchdog_module, tmp_path
):
    logs_dir = tmp_path / "logs"
    meas_dir = logs_dir / "measurements"
    meas_dir.mkdir(parents=True, exist_ok=True)
    data_folder = tmp_path / "resume_err_run"
    data_folder.mkdir()

    log_json = meas_dir / "SESS-POPEN-ERR.json"
    orig_err = {"stage": "auth", "message": "Token expired"}
    log_json.write_text(
        json.dumps(
            {
                "eln_url": "https://openbis.local",
                "eln_token": "tok-old",
                "measurement_session_id": "SESS-POPEN-ERR",
                "data_folder": str(data_folder),
                "processed_files": [],
                "token_expired": True,
                "last_error": orig_err,
                "recent_errors": [orig_err],
            }
        ),
        encoding="utf-8",
    )
    active_file = logs_dir / "active_watchdogs.json"
    active_file.write_text(
        json.dumps(
            [
                {
                    "pid": 8889,
                    "monitored_folder": str(data_folder),
                    "measurement_session_id": "SESS-POPEN-ERR",
                    "status": "EXITED",
                    "user_stopped": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    session_obj = _fake_session("SESS-POPEN-ERR", "MEAS_Err")

    # Case A: Popen raises OSError -> inline error shown & token_expired/last_error restored
    with (
        patch("src.utils.get_openbis_object", return_value=session_obj),
        patch("subprocess.Popen", side_effect=OSError("spawn failed")),
    ):
        widget = watchdog_module.RunningMeasurementWatchdogsWidget(
            MagicMock(), {"url": "https://openbis.local", "token": "tok-fresh"}
        )
        _collect_buttons(widget.watchdogs_box.children[0])["Resume"].click()
        live_html = "\n".join(_collect_html(widget.watchdogs_box.children[0]))
        assert "spawn failed" in live_html.lower() or "failed to start" in live_html.lower()

    after_err = json.loads(log_json.read_text(encoding="utf-8"))
    assert after_err["token_expired"] is True
    assert after_err["last_error"] == orig_err

    # Case B: Missing url/token in session_data -> inline error & no Popen
    with (
        patch("src.utils.get_openbis_object", return_value=session_obj),
        patch("subprocess.Popen") as mock_popen,
    ):
        widget2 = watchdog_module.RunningMeasurementWatchdogsWidget(MagicMock(), {})
        _collect_buttons(widget2.watchdogs_box.children[0])["Resume"].click()
        live_html2 = "\n".join(_collect_html(widget2.watchdogs_box.children[0]))
        assert "token" in live_html2.lower() or "credentials" in live_html2.lower()
    assert mock_popen.call_count == 0


def test_notebook_tab_switch_triggers_refresh():
    from pathlib import Path

    nb_path = Path(__file__).resolve().parents[1] / "2_sample_measurement.ipynb"
    cells = json.loads(nb_path.read_text(encoding="utf-8"))["cells"]
    code = "\n".join("".join(c.get("source", [])) for c in cells if c["cell_type"] == "code")
    assert "selected_index" in code
    assert "running_watchdogs_vbox.refresh_watchdog_list" in code


def test_generate_watchdog_resets_dropdowns_and_session_name_after_submit(
    watchdog_module, tmp_path
):
    data_folder = tmp_path / "reset_submit_run"
    data_folder.mkdir()
    widget = _make_full_generator_widget(
        watchdog_module, tmp_path, data_folder, session_name="MEAS_Sample1"
    )
    new_session = _fake_session("SESS-RST-1", "MEAS_Sample1")
    fake_proc = MagicMock(pid=8101)

    with (
        patch("src.utils.create_openbis_object", return_value=new_session) as mock_create,
        patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        patch.object(watchdog_module, "display"),
    ):
        widget.generate_watchdog(None)

        # Metadata was captured BEFORE reset
        log_data = json.loads(
            (widget.measurement_logs_folder / "SESS-RST-1.json").read_text(
                encoding="utf-8"
            )
        )
        assert log_data["session_name"] == "MEAS_Sample1"
        assert log_data["sample_name"] == "S1"
        assert log_data["experiment_name"] == "E1"
        assert log_data["instrument_name"] == "I1"

        # All dropdowns and measurement name reset to defaults
        assert widget.select_project_widget.project_dropdown.value == "-1"
        assert widget.select_experiment_widget.experiment_dropdown.value == "-1"
        assert widget.select_sample_widget.sample_dropdown.value == "-1"
        assert widget.select_instrument_widget.instrument_dropdown.value == "-1"
        assert widget.measurement_session_name_text.value == ""

        # Immediately clicking Save again is blocked so no duplicate session is created
        widget.generate_watchdog(None)
        assert mock_create.call_count == 1
        assert mock_popen.call_count == 1

    # On Switch to new session, form also resets; on Cancel or failure, inputs stay intact
    folder_conflict = tmp_path / "reset_switch_run"
    folder_conflict.mkdir()
    old_session = _fake_session("SESS-OLD-RST", "MEAS_Old")
    switched_session = _fake_session("SESS-SW-RST", "MEAS_Switched")
    (widget.measurement_logs_folder / "SESS-OLD-RST.json").write_text(
        json.dumps(
            {
                "measurement_session_id": "SESS-OLD-RST",
                "data_folder": str(folder_conflict),
                "processed_files": [],
            }
        ),
        encoding="utf-8",
    )

    widget2 = _make_full_generator_widget(
        watchdog_module, tmp_path, folder_conflict, session_name="MEAS_Switched"
    )
    with (
        patch("src.utils.get_openbis_object", return_value=old_session),
        patch("src.utils.create_openbis_object", return_value=switched_session),
        patch("subprocess.Popen", return_value=MagicMock(pid=8102)),
        patch.object(watchdog_module, "display"),
    ):
        # Cancel preserves inputs
        widget2.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget2.folder_conflict_box)
        buttons["Cancel"].click()
        assert widget2.select_sample_widget.sample_dropdown.value == "SMP-1"
        assert widget2.measurement_session_name_text.value == "MEAS_Switched"

        # Switch resets inputs
        widget2.generate_watchdog(None)
        _, buttons = _extract_prompt_widgets(widget2.folder_conflict_box)
        buttons["Switch to new session"].click()
        assert widget2.select_project_widget.project_dropdown.value == "-1"
        assert widget2.select_experiment_widget.experiment_dropdown.value == "-1"
        assert widget2.select_sample_widget.sample_dropdown.value == "-1"
        assert widget2.select_instrument_widget.instrument_dropdown.value == "-1"
        assert widget2.measurement_session_name_text.value == ""
