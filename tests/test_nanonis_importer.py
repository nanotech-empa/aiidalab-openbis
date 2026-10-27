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
