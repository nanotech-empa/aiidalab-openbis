"""Exercise real pyBIS chunking with a fake HTTP transport; never contact a server."""

import base64
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from types import MethodType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from pybis.dataset import DataSet, DataSetUploadQueueNew

from src import upload_diagnostics as diag
from src import utils
from src.export_recovery import ExportCheck, ExportReport, ensure_upload, report_html

SECRET = "secret-session-value-do-not-log"


def response(status=200, size=0):
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps({"size": size, "secret": SECRET}).encode()
    return value


def dataset(client):
    obj = SimpleNamespace(openbis=client, files_in_wsp=[])
    obj.upload_files_v3 = MethodType(DataSet.upload_files_v3, obj)
    return obj


def test_real_pybis_chunk_ranges_bytes_and_no_global_patch(monkeypatch, tmp_path):
    path = tmp_path / "file.aiida"
    content = b"a" * (10 * 1024 * 1024 + 97)
    path.write_bytes(content)
    calls = []

    def transport(self, method, url, **kwargs):
        query = parse_qs(urlsplit(url).query)
        body = kwargs["data"]
        calls.append((int(query["startByte"][0]), body, kwargs["verify"]))
        return response(size=len(body))

    monkeypatch.setattr(requests.Session, "request", transport)
    client = SimpleNamespace(token=SECRET, verify_certificates=True)
    obj = dataset(client)
    original = obj.upload_files_v3
    with diag.attempt() as trace:
        diag.record_files([path])
        with diag.observe_dataset(obj):
            obj.upload_files_v3(
                [str(path)],
                datastore_url="https://test.invalid",
                wait_until_finished=True,
            )
    assert obj.upload_files_v3 is original
    assert obj.openbis is client
    assert (
        DataSet.upload_files_v3.__globals__["DataSetUploadQueueNew"]
        is DataSetUploadQueueNew
    )
    assert b"".join(body for _, body, _ in sorted(calls)) == content
    assert all(verify is True for _, _, verify in calls)
    assert trace.confirmed_bytes == len(content)
    assert trace.completed_requests == 2
    assert trace.failed_requests == 0
    assert not trace.pending
    events = [json.loads(line) for line in trace.path.read_text().splitlines()]
    assert any(
        event["event"] == "local_file" and event["size_bytes"] == len(content)
        for event in events
    )
    assert len([event for event in events if event["event"] == "chunk_started"]) == 2
    assert trace.path.stat().st_mode & 0o777 == 0o600
    assert SECRET not in trace.path.read_text()
    assert "sessionID" not in trace.path.read_text()
    assert str(path) not in trace.path.read_text()


def test_broken_pipe_identifies_transfer_and_restores_dataset(monkeypatch, tmp_path):
    path = tmp_path / "archive.aiida"
    path.write_bytes(b"a" * (10 * 1024 * 1024 + 1))
    failure = requests.ConnectionError(SECRET, BrokenPipeError(32, SECRET))

    def transport(*args, **kwargs):
        raise failure

    monkeypatch.setattr(requests.Session, "request", transport)
    obj = dataset(SimpleNamespace(token=SECRET, verify_certificates=True))
    original = obj.upload_files_v3
    with (
        diag.attempt() as trace,
        pytest.raises(requests.ConnectionError) as caught,
        diag.observe_dataset(obj),
    ):
        obj.upload_files_v3(
            [str(path)],
            datastore_url="https://test.invalid",
            wait_until_finished=True,
        )
    assert caught.value is failure
    assert obj.upload_files_v3 is original
    failures = [event for event in trace.events if event["event"] == "phase_failed"]
    assert failures[0]["phase"] == "chunk_transfer"
    assert any(error.get("errno") == 32 for error in failures[0]["errors"])
    assert trace.failed_requests >= 1 and trace.completed_requests == 0
    assert not trace.pending
    assert SECRET not in json.dumps(trace.report())
    html = trace.render()
    download = re.search(r"base64,([^\"]+)", html).group(1)
    assert SECRET not in base64.b64decode(download).decode()
    assert "chunk_transfer" in html


@pytest.mark.parametrize(
    "failed_phase", ["dataset_registration", "dataset_readback", None]
)
def test_registration_and_readback_distinguished(failed_phase):
    error = RuntimeError(SECRET)

    class Client:
        def _post_request_full_url(self, url, request):
            if failed_phase == "dataset_registration":
                raise error
            return {"permId": "dataset"}

        def get_dataset(self, permid, **kwargs):
            if failed_phase == "dataset_readback":
                raise error
            return {"permId": permid}

    client = Client()
    obj = SimpleNamespace(openbis=client)
    with diag.attempt() as trace:
        try:
            with diag.observe_dataset(obj):
                obj.openbis._post_request_full_url(
                    "https://test.invalid/rpc?sessionID=" + SECRET,
                    {"method": "createUploadedDataSet", "params": [SECRET]},
                )
                obj.openbis.get_dataset("dataset", only_data=True)
        except RuntimeError as caught:
            assert caught is error
    failures = [event for event in trace.events if event["event"] == "phase_failed"]
    assert [event["phase"] for event in failures] == (
        [failed_phase] if failed_phase else []
    )
    assert obj.openbis is client
    assert SECRET not in json.dumps(trace.report())


def test_http_failure_is_not_counted_as_accepted_bytes():
    with diag.attempt() as trace:
        send = diag._observed_request(lambda *args, **kwargs: response(502), trace)
        result = send(
            "POST",
            "https://test.invalid/upload?id=2&startByte=10&endByte=19&sessionID="
            + SECRET,
            data=b"0123456789",
        )
    assert result.status_code == 502
    assert trace.confirmed_bytes == trace.completed_requests == 0
    assert trace.failed_requests == 1
    assert any(event.get("http_status") == 502 for event in trace.events)


def test_log_failure_keeps_report_and_original_error(tmp_path):
    non_directory = tmp_path / "file"
    non_directory.write_text("not a directory")
    trace = diag.UploadTrace(directory=non_directory / "reports")
    failure = BrokenPipeError(32, SECRET)
    try:
        with (
            pytest.raises(BrokenPipeError) as caught,
            diag.phase("chunk_transfer", trace),
        ):
            raise failure
        assert caught.value is failure
    finally:
        trace.finish()
    assert trace.log_unavailable
    assert "Local log unavailable" in trace.render()
    assert SECRET not in trace.render()


def test_heartbeat_observes_blocked_request(tmp_path):
    trace = diag.UploadTrace(directory=tmp_path, heartbeat_seconds=0.02)
    started, release, observed = threading.Event(), threading.Event(), threading.Event()
    original_event = trace.event

    def record(event, **fields):
        original_event(event, **fields)
        if event == "heartbeat" and fields["active_requests"] == 1:
            observed.set()

    trace.event = record

    def transport(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return response()

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            task = pool.submit(
                diag._observed_request(transport, trace),
                "POST",
                "https://test.invalid",
                data=b"abc",
            )
            try:
                assert started.wait(2)
                assert observed.wait(2)
            finally:
                release.set()
            task.result()
    finally:
        trace.finish()
    assert trace.confirmed_bytes == 3


def test_concurrent_attempts_have_independent_queues(monkeypatch, tmp_path):
    path = tmp_path / "file"
    path.write_bytes(b"data")
    barrier = threading.Barrier(2)

    def transport(self, method, url, **kwargs):
        barrier.wait(timeout=3)
        return response(size=4)

    monkeypatch.setattr(requests.Session, "request", transport)

    def run():
        obj = dataset(SimpleNamespace(token=SECRET, verify_certificates=True))
        with diag.attempt() as trace, diag.observe_dataset(obj):
            obj.upload_files_v3(
                [str(path)],
                datastore_url="https://test.invalid",
                wait_until_finished=True,
            )
        return trace

    with ThreadPoolExecutor(max_workers=2) as pool:
        traces = list(pool.map(lambda _: run(), range(2)))
    assert traces[0].id != traces[1].id
    assert all(
        trace.confirmed_bytes == 4 and trace.completed_requests == 1 for trace in traces
    )
    assert diag.CURRENT.get() is None


def test_unknown_pybis_implementation_falls_back_without_changing_behavior():
    obj = SimpleNamespace(upload_files_v3=lambda: "unchanged")
    with diag.attempt() as trace, diag.observe_dataset(obj):
        assert obj.upload_files_v3() == "unchanged"
    assert any(
        event["event"] == "chunk_instrumentation_unavailable" for event in trace.events
    )


def test_dataset_wrapper_discards_authenticated_stdout(tmp_path, capsys):
    path = tmp_path / "archive.aiida"
    path.write_bytes(b"data")

    def save():
        print(SECRET)
        raise BrokenPipeError(32, SECRET)

    client = SimpleNamespace(new_dataset=lambda **kwargs: SimpleNamespace(save=save))
    with diag.attempt() as trace, pytest.raises(BrokenPipeError):
        utils.create_openbis_dataset(client, files=[path], type="RAW_DATA")
    assert SECRET not in capsys.readouterr().out
    assert not hasattr(utils._discarded_stdout, "getvalue")
    assert any(
        event.get("phase") == "dataset_save" and event["event"] == "phase_failed"
        for event in trace.events
    )


def test_repeated_object_saves_discard_stdout_without_retaining_it(capsys):
    import sys

    original = sys.stdout
    state = vars(utils._discarded_stdout).copy()
    obj = SimpleNamespace(save=lambda: print("x" * 1024))
    for _ in range(100):
        utils.update_openbis_object(obj)
    assert sys.stdout is original
    assert capsys.readouterr().out == ""
    assert vars(utils._discarded_stdout) == state
    assert not hasattr(utils._discarded_stdout, "getvalue")


def test_lost_response_recovery_remains_single_upload_and_records_inventory():
    state = {"present": False, "uploads": 0}

    def upload():
        state["uploads"] += 1
        state["present"] = True
        raise requests.ConnectionError(SECRET)

    with diag.attempt() as trace:
        assert ensure_upload(lambda: state["present"], upload) is True
    assert state["uploads"] == 1
    assert [
        event["present"]
        for event in trace.events
        if event["event"] == "remote_inventory_result"
    ] == [False, True]


def test_technical_details_do_not_include_authenticated_exception_text():
    report = ExportReport([ExportCheck("archive", "AiiDA archive", "missing")])
    markup = report_html(
        report,
        error=requests.ConnectionError("https://host/upload?sessionID=" + SECRET),
    )
    assert "ConnectionError" in markup
    assert SECRET not in markup and "sessionID" not in markup


def test_real_dataset_restores_client_without_setting_server_properties():
    # An uninitialized real entity exercises pyBIS __getattr__/__setattr__;
    # initialization normally queries the server, which this test must not do.
    obj = object.__new__(DataSet)
    client = SimpleNamespace(token=SECRET)
    object.__setattr__(obj, "openbis", client)
    before = dict(obj.__dict__)
    with diag.attempt(), diag.observe_dataset(obj):
        assert obj.openbis is not client
        assert "upload_files_v3" in obj.__dict__
    assert obj.__dict__ == before


def test_report_records_event_truncation_but_local_log_remains_complete():
    with diag.attempt() as trace:
        for index in range(5002):
            trace.event("test_event", index=index)
    assert len(trace.events) == 5000
    assert trace.report()["events_omitted"] == 4
    assert len(trace.path.read_text().splitlines()) == 5004
