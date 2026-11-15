"""Exercise the merged notebook startup without launching or signalling processes."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest


@pytest.mark.parametrize("previous", [None, "", "invalid", "stale", "running", "stuck"])
def test_log_uploader_restart_keeps_app_root_paths(tmp_path, monkeypatch, previous):
    notebook = json.loads(
        (Path(__file__).resolve().parents[1] / "0_home.ipynb").read_text()
    )
    cells = [
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    ]
    for source in cells:
        compile(source, "0_home.ipynb", "exec")
    startup = next(source for source in cells if "subprocess.Popen(" in source)

    app_root = tmp_path / "app"
    app_root.mkdir()
    log_dir = app_root / "logs"
    pid_file = log_dir / "upload_logs.pid"
    if previous is not None:
        log_dir.mkdir()
        pid_file.write_text(previous if previous in ("", "invalid") else "12345")
    unrelated_cwd = tmp_path / "notebooks"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)

    kill = Mock()
    if previous == "stale":
        kill.side_effect = ProcessLookupError
    elif previous == "running":
        kill.side_effect = [None, ProcessLookupError]
    popen = Mock(return_value=SimpleNamespace(pid=54321))
    namespace = {
        "utils": SimpleNamespace(APP_ROOT=app_root, LOG_DIR=log_dir),
        "os": SimpleNamespace(path=os.path, kill=kill),
        "signal": signal,
        "time": SimpleNamespace(sleep=Mock()),
        "sys": sys,
        "subprocess": SimpleNamespace(Popen=popen, DEVNULL=subprocess.DEVNULL),
    }

    exec(compile(startup, "0_home.ipynb:log-uploader", "exec"), namespace)

    popen.assert_called_once_with(
        [sys.executable, app_root / "src" / "upload_logs_to_afs.py"],
        cwd=app_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    assert pid_file.read_text() == "54321"
    assert not (unrelated_cwd / "logs").exists()
    assert not (tmp_path / "logs").exists()
    if previous == "stale":
        assert kill.call_args_list == [call(12345, signal.SIGTERM)]
    elif previous == "running":
        assert kill.call_args_list == [call(12345, signal.SIGTERM), call(12345, 0)]
    elif previous == "stuck":
        assert kill.call_args_list == (
            [call(12345, signal.SIGTERM)]
            + [call(12345, 0)] * 10
            + [call(12345, signal.SIGKILL)]
        )
    else:
        kill.assert_not_called()
