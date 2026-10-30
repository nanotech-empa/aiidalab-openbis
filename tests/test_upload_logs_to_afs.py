from unittest.mock import MagicMock, mock_open, patch
from src import upload_logs_to_afs


def test_get_ram_usage_str_with_psutil():
    mock_vm = MagicMock()
    # 8 GB used out of 16 GB total = 50.0%
    mock_vm.total = 16 * (1024**3)
    mock_vm.used = 8 * (1024**3)
    mock_vm.percent = 50.0

    with patch("psutil.virtual_memory", return_value=mock_vm):
        ram_str = upload_logs_to_afs.get_ram_usage_str()
        assert ram_str == "8.0 / 16.0 GB [50.0%]"


def test_get_ram_usage_from_proc_meminfo():
    mock_meminfo = (
        "MemTotal:       16777216 kB\n"
        "MemFree:         4194304 kB\n"
        "MemAvailable:    8388608 kB\n"
        "Buffers:          524288 kB\n"
        "Cached:          3670016 kB\n"
    )

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=mock_meminfo)),
    ):
        ram_str = upload_logs_to_afs.get_ram_usage_from_proc_meminfo()
        assert ram_str == "8.0 / 16.0 GB [50.0%]"


def test_get_ram_usage_str_falls_back_when_psutil_fails():
    with (
        patch("psutil.virtual_memory", side_effect=Exception("psutil error")),
        patch(
            "src.upload_logs_to_afs.get_ram_usage_from_proc_meminfo",
            return_value="8.0 / 16.0 GB [50.0%]",
        ),
    ):
        ram_str = upload_logs_to_afs.get_ram_usage_str()
        assert ram_str == "8.0 / 16.0 GB [50.0%]"


def test_log_ram_usage_if_due():
    mock_logger = MagicMock()

    # Case 1: First run (last_logged_time = 0), should log and update timestamp
    new_time = upload_logs_to_afs.log_ram_usage_if_due(
        logger=mock_logger,
        last_logged_time=0.0,
        current_time=1000.0,
        interval_seconds=3600.0,
    )
    assert new_time == 1000.0
    mock_logger.info.assert_called_once()
    assert "RAM usage:" in mock_logger.info.call_args[0][0]

    # Case 2: 1800s later (less than 3600s), should NOT log again
    mock_logger.reset_mock()
    same_time = upload_logs_to_afs.log_ram_usage_if_due(
        logger=mock_logger,
        last_logged_time=1000.0,
        current_time=2800.0,
        interval_seconds=3600.0,
    )
    assert same_time == 1000.0
    mock_logger.info.assert_not_called()

    # Case 3: 3601s later, should log again and update timestamp
    mock_logger.reset_mock()
    later_time = upload_logs_to_afs.log_ram_usage_if_due(
        logger=mock_logger,
        last_logged_time=1000.0,
        current_time=4601.0,
        interval_seconds=3600.0,
    )
    assert later_time == 4601.0
    mock_logger.info.assert_called_once()
    assert "RAM usage:" in mock_logger.info.call_args[0][0]
