import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

from nanonis_importer import nanonis_importer


def test_process_measurement_files_uses_tmp_for_dat_files_staging(tmp_path):
    data_folder = tmp_path / "measurement_folder"
    data_folder.mkdir()
    dat_file = data_folder / "spec_001.dat"
    dat_file.write_text("dummy dat content")

    logging_file = tmp_path / "logging.json"
    logging_file.write_text('{"processed_files": []}')

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    mock_spm_instance = MagicMock()
    mock_spm_instance.record_datetime = datetime(2026, 1, 1, 12, 0, 0)
    mock_spm_instance.signals = ["bias", "current"]
    mock_spm_instance.measurement_type = "bias_spec"

    captured_staging_dir = []

    def fake_demo_dat_flow(session, directory, sample, experiment):
        captured_staging_dir.append(directory)
        # Check that dat file was copied to directory
        assert os.path.exists(os.path.join(directory, "spec_001.dat"))

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", return_value=mock_spm_instance),
        patch(
            "nanonis_importer.nanonis_importer.demo_dat_flow",
            side_effect=fake_demo_dat_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="http://mock.openbis",
            token="dummy_token",
            data_folder=str(data_folder),
            measurements_id="SMP-123",
            logging_filepath=str(logging_file),
        )

    # Ensure demo_dat_flow was called
    assert len(captured_staging_dir) == 1
    staging_dir = captured_staging_dir[0]

    # Staging directory must NOT be inside data_folder
    assert str(data_folder) not in staging_dir
    # Staging directory must be in temp directory
    assert staging_dir.startswith(tempfile.gettempdir())
    # Staging directory must have been cleaned up
    assert not os.path.exists(staging_dir)
    # data_folder must not have dat_files
    assert not os.path.exists(os.path.join(str(data_folder), "dat_files"))


def test_process_measurement_files_cleans_up_staging_on_error(tmp_path):
    data_folder = tmp_path / "measurement_folder"
    data_folder.mkdir()
    dat_file = data_folder / "spec_002.dat"
    dat_file.write_text("dummy dat content")

    logging_file = tmp_path / "logging.json"
    logging_file.write_text('{"processed_files": []}')

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    mock_spm_instance = MagicMock()
    mock_spm_instance.record_datetime = datetime(2026, 1, 1, 12, 0, 0)
    mock_spm_instance.signals = ["bias", "current"]
    mock_spm_instance.measurement_type = "bias_spec"

    staged_dirs = []

    def failing_demo_dat_flow(session, directory, sample, experiment):
        staged_dirs.append(directory)
        raise RuntimeError("Upload failure")

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", return_value=mock_spm_instance),
        patch(
            "nanonis_importer.nanonis_importer.demo_dat_flow",
            side_effect=failing_demo_dat_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="http://mock.openbis",
            token="dummy_token",
            data_folder=str(data_folder),
            measurements_id="SMP-123",
            logging_filepath=str(logging_file),
        )

    assert len(staged_dirs) == 1
    staging_dir = staged_dirs[0]
    # Verify staging directory was in temp and NOT in data_folder
    assert str(data_folder) not in staging_dir
    assert staging_dir.startswith(tempfile.gettempdir())
    # Verify staging directory was cleaned up even after exception
    assert not os.path.exists(staging_dir)
    assert not os.path.exists(os.path.join(str(data_folder), "dat_files"))


def test_init_or_load_measurement_log_saves_in_logs_folder(tmp_path):
    from src import measurements_uploader, utils

    data_folder = tmp_path / "meas_folder"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"

    log_path, log_data = measurements_uploader.init_or_load_measurement_log(
        openbis_url="https://openbis.local",
        openbis_token="token-1",
        measurement_session_id="20261027-99999",
        data_folder=str(data_folder),
        logs_dir=logs_dir,
    )

    assert log_path == str(logs_dir / "20261027-99999.json")
    assert os.path.exists(log_path)
    assert not (data_folder / "logging.json").exists()
    assert log_data["measurement_session_id"] == "20261027-99999"
    assert log_data["data_folder"] == os.path.normpath(str(data_folder))
    assert log_data["processed_files"] == []

    # Simulate uploading a file and saving to log
    uploaded_file = str(data_folder / "scan_001.sxm")
    log_data["processed_files"].append(uploaded_file)
    utils.write_json(log_data, log_path)

    # Simulate resuming with a new token: processed_files must be preserved
    log_path2, log_data2 = measurements_uploader.init_or_load_measurement_log(
        openbis_url="https://openbis.local",
        openbis_token="token-2-refreshed",
        measurement_session_id="20261027-99999",
        data_folder=str(data_folder),
        logs_dir=logs_dir,
    )
    assert log_path2 == log_path
    assert log_data2["eln_token"] == "token-2-refreshed"
    assert log_data2["processed_files"] == [uploaded_file]


def test_get_or_create_measurement_session_reuses_existing_session_on_resume(tmp_path):
    with patch(
        "src.utils.get_interface_config_info",
        return_value={
            "object_types": {"Measurement Session": "MEASUREMENT_SESSION"},
            "object_types_codes": {"Measurement Session": "MS"},
            "actions_types": {},
            "actions_types_codes": {},
            "actions_types_icons": {},
            "actions_use_instrument": {},
            "slabs_types": {},
            "slabs_types_codes": {},
            "slabs_concepts_types": {},
            "slabs_concepts_codes": {},
            "instruments_types": {},
            "components_types": {},
        },
    ):
        from src import watchdog_widgets

    watchdog_widgets.OPENBIS_OBJECT_TYPES["Measurement Session"] = "MEASUREMENT_SESSION"

    data_folder = tmp_path / "experiment_run_1"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"

    mock_openbis = MagicMock()
    session_data = {"url": "https://openbis.local", "token": "tok-1"}

    widget = watchdog_widgets.GenerateMeasurementsWatchdogWidget.__new__(
        watchdog_widgets.GenerateMeasurementsWatchdogWidget
    )
    widget.openbis_session = mock_openbis
    widget.session_data = session_data
    widget.measurement_logs_folder = logs_dir
    widget.measurement_session_name_text = MagicMock()
    widget.measurement_session_name_text.value = "MEAS_Sample1"

    created_session = MagicMock()
    created_session.permId = "20261027-11111"

    with (
        patch(
            "src.utils.create_openbis_object", return_value=created_session
        ) as mock_create,
        patch("src.utils.get_openbis_object", return_value=created_session) as mock_get,
    ):
        # 1. First time: creates new Measurement Session in openBIS and writes log in logs_dir
        res1 = widget._get_or_create_measurement_session(
            sample_id="SMP-1",
            instrument_id="INST-1",
            experiment_id="EXP-1",
            data_folder=str(data_folder),
        )
        assert res1.permId == "20261027-11111"
        assert mock_create.call_count == 1
        assert mock_get.call_count == 0
        assert (logs_dir / "20261027-11111.json").exists()
        assert not (data_folder / "logging.json").exists()

        # 2. Stop and resume on the same folder (even with trailing slash): reuses existing session
        res2 = widget._get_or_create_measurement_session(
            sample_id="SMP-1",
            instrument_id="INST-1",
            experiment_id="EXP-1",
            data_folder=f"{data_folder}/",
        )
        assert res2.permId == "20261027-11111"
        assert mock_create.call_count == 1  # Not called again!
        assert mock_get.call_count == 1

        # 3. If the session was deleted in openBIS (raises ValueError), creates a new one and cleans up stale log
        new_session = MagicMock()
        new_session.permId = "20261027-22222"
        mock_create.return_value = new_session
        mock_get.side_effect = ValueError("No such object")

        res3 = widget._get_or_create_measurement_session(
            sample_id="SMP-1",
            instrument_id="INST-1",
            experiment_id="EXP-1",
            data_folder=str(data_folder),
        )
        assert res3.permId == "20261027-22222"
        assert mock_create.call_count == 2
        assert not (logs_dir / "20261027-11111.json").exists()
        assert (logs_dir / "20261027-22222.json").exists()


def test_stop_and_resume_uploads_only_new_files_to_same_session(tmp_path):
    from src import measurements_uploader

    data_folder = tmp_path / "measurement_folder"
    data_folder.mkdir()
    logs_dir = tmp_path / "logs" / "measurements"

    sxm_1 = data_folder / "scan_001.sxm"
    sxm_1.write_text("sxm1")

    mock_session = MagicMock()
    mock_sample = MagicMock()
    mock_sample.experiment = "/SPACE/PROJ/EXP"
    mock_session.get_sample.return_value = mock_sample

    mock_spm_instance = MagicMock()
    mock_spm_instance.record_datetime = datetime(2026, 1, 1, 12, 0, 0)

    uploaded_sxm_files = []

    def fake_demo_sxm_flow(session, file_path, sample, experiment):
        uploaded_sxm_files.append((file_path, sample))

    # Run 1: Initialize log in logs_dir and process scan_001.sxm
    log_filepath, _ = measurements_uploader.init_or_load_measurement_log(
        openbis_url="http://mock.openbis",
        openbis_token="tok-1",
        measurement_session_id="SESS-500",
        data_folder=str(data_folder),
        logs_dir=logs_dir,
    )

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", return_value=mock_spm_instance),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=fake_demo_sxm_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="http://mock.openbis",
            token="tok-1",
            data_folder=str(data_folder),
            measurements_id="SESS-500",
            logging_filepath=log_filepath,
        )

    assert uploaded_sxm_files == [(str(sxm_1), "SESS-500")]
    assert not (data_folder / "logging.json").exists()

    # Run 2 (Resume): Add scan_002.sxm, re-initialize log for SESS-500, and process
    sxm_2 = data_folder / "scan_002.sxm"
    sxm_2.write_text("sxm2")

    log_filepath_2, _ = measurements_uploader.init_or_load_measurement_log(
        openbis_url="http://mock.openbis",
        openbis_token="tok-2",
        measurement_session_id="SESS-500",
        data_folder=str(data_folder),
        logs_dir=logs_dir,
    )

    with (
        patch("src.utils.connect_openbis", return_value=(mock_session, None)),
        patch("nanonis_importer.nanonis_importer.spm", return_value=mock_spm_instance),
        patch(
            "nanonis_importer.nanonis_importer.demo_sxm_flow",
            side_effect=fake_demo_sxm_flow,
        ),
    ):
        nanonis_importer.process_measurement_files(
            openbis_url="http://mock.openbis",
            token="tok-2",
            data_folder=str(data_folder),
            measurements_id="SESS-500",
            logging_filepath=log_filepath_2,
        )

    # scan_001.sxm was NOT uploaded again; only scan_002.sxm was uploaded to SESS-500
    assert len(uploaded_sxm_files) == 2
    assert uploaded_sxm_files[1] == (str(sxm_2), "SESS-500")
