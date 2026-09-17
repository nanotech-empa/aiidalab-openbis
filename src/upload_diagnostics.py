"""Allowlisted upload telemetry; no payloads, tokens or exception messages.

Instrumentation is local to one export and one dataset. The pyBIS queue uses
its original workers, retry policy and request bodies. No global HTTP or pyBIS
classes are patched, including while other notebook kernels are exporting.
"""

import base64
import html
import json
import os
import platform
import re
import shutil
import threading
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import FunctionType, MethodType
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

CURRENT = ContextVar("openbis_upload_diagnostics", default=None)
LOG_DIR = Path(__file__).resolve().parents[1] / "logs" / "upload_diagnostics"


def exception_info(error):
    """Keep causal exception classes/errno/stack locations, never their text."""
    pending, seen, result = [error], set(), []
    while pending and len(result) < 12:
        item = pending.pop(0)
        if not isinstance(item, BaseException) or id(item) in seen:
            continue
        seen.add(id(item))
        record = {"type": type(item).__name__}
        number = getattr(item, "errno", None)
        if isinstance(number, int):
            record["errno"] = number
        record["frames"] = [
            {
                "file": Path(frame.filename).name,
                "line": frame.lineno,
                "function": frame.name,
            }
            for frame in traceback.extract_tb(item.__traceback__)[-12:]
        ]
        result.append(record)
        pending.extend(
            [item.__cause__, item.__context__, getattr(item, "reason", None)]
        )
        pending.extend(arg for arg in item.args if isinstance(arg, BaseException))
    return result


def error_summary(error):
    return " → ".join(
        item["type"] + (f" (errno {item['errno']})" if "errno" in item else "")
        for item in exception_info(error)
    )


def public_id(value):
    """Identifiers are useful to admins; arbitrary user strings are not logged."""
    text = str(value or "")
    return text if re.fullmatch(r"(?:[0-9a-fA-F-]{36}|\d{17}-\d+)", text) else None


class UploadTrace:
    def __init__(self, directory=None, heartbeat_seconds=15):
        self.id = str(uuid4())
        self.started = time.monotonic()
        self.events = []
        self.events_omitted = 0
        self.pending = {}
        self.confirmed_bytes = 0
        self.completed_requests = 0
        self.failed_requests = 0
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.stream = None
        self.log_unavailable = False
        self.path = (Path(directory) if directory is not None else LOG_DIR) / (
            self.id + ".jsonl"
        )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            self.stream = os.fdopen(fd, "w", encoding="utf-8")
        except OSError:
            self.log_unavailable = True
        packages = {}
        for name in ("pybis", "requests", "urllib3", "aiida-core"):
            try:
                packages[name] = version(name)
            except PackageNotFoundError:
                packages[name] = "not-installed"
        self.event(
            "attempt_started", python=platform.python_version(), packages=packages
        )
        self.thread = threading.Thread(
            target=self._heartbeat, args=(heartbeat_seconds,), daemon=True
        )
        self.thread.start()

    def event(self, event, **fields):
        # Call sites supply only explicit numeric/identifier metadata. Never pass
        # request kwargs, response text, arbitrary properties or str(exception).
        with self.lock:
            record = {
                "event": event,
                "utc": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                **fields,
            }
            if len(self.events) < 5000:
                self.events.append(record)
            else:
                self.events_omitted += 1
            if self.stream is not None:
                try:
                    self.stream.write(json.dumps(record) + "\n")
                    self.stream.flush()
                except OSError:
                    self.log_unavailable = True
                    try:
                        self.stream.close()
                    except OSError:
                        pass
                    self.stream = None

    def _heartbeat(self, seconds):
        while not self.stop.wait(seconds):
            with self.lock:
                self.event(
                    "heartbeat",
                    active_requests=len(self.pending),
                    oldest_request_seconds=round(
                        max(
                            (
                                time.monotonic() - start
                                for start in self.pending.values()
                            ),
                            default=0,
                        ),
                        3,
                    ),
                    confirmed_staging_bytes=self.confirmed_bytes,
                    completed_requests=self.completed_requests,
                )

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=1)
        self.event(
            "attempt_finished",
            confirmed_staging_bytes=self.confirmed_bytes,
            completed_requests=self.completed_requests,
            failed_requests=self.failed_requests,
        )
        if self.stream is not None:
            try:
                self.stream.close()
            except OSError:
                self.log_unavailable = True

    def report(self):
        return {
            "format_version": 1,
            "attempt_id": self.id,
            "local_log_available": not self.log_unavailable,
            "confirmed_staging_bytes": self.confirmed_bytes,
            "completed_requests": self.completed_requests,
            "failed_requests": self.failed_requests,
            "events_omitted": self.events_omitted,
            "note": "HTTP staging success is not dataset registration or archive integrity verification. "
            "Request durations include any retries inside the existing HTTP adapter.",
            "events": self.events,
        }

    def render(self):
        payload = json.dumps(self.report(), indent=2).encode()
        encoded = base64.b64encode(payload).decode("ascii")
        failures = [event for event in self.events if event["event"] == "phase_failed"]
        phase = failures[0]["phase"] if failures else "No instrumented phase failed"
        local = (
            "Local log unavailable; download the report below."
            if self.log_unavailable
            else f"Local log: logs/upload_diagnostics/{self.id}.jsonl"
        )
        return (
            "<details><summary>Upload diagnostic report</summary>"
            f"<p>Attempt: <code>{self.id}</code><br>"
            f"First failed phase: {html.escape(phase)}<br>"
            f"HTTP staging requests completed: {self.completed_requests}; "
            f"failed: {self.failed_requests}; accepted bytes: {self.confirmed_bytes}.</p>"
            "<p>Accepted bytes describe staging only, not a registered dataset. "
            "The report contains timings, identifiers and error types; no credentials or request bodies.</p>"
            f"<p>{html.escape(local)}</p>"
            f'<a download="openbis-upload-{self.id}.json" '
            f'href="data:application/json;base64,{encoded}">Download diagnostic report (JSON)</a>'
            "</details>"
        )


@contextmanager
def attempt():
    trace = UploadTrace()
    token = CURRENT.set(trace)
    try:
        yield trace
    except Exception as error:
        trace.event("unhandled_error", errors=exception_info(error))
        raise
    finally:
        CURRENT.reset(token)
        trace.finish()


@contextmanager
def phase(name, trace=None, **fields):
    trace = trace or CURRENT.get()
    if trace is None:
        yield
        return
    start = time.monotonic()
    trace.event("phase_started", phase=name, **fields)
    try:
        yield
    except Exception as error:
        trace.event(
            "phase_failed",
            phase=name,
            seconds=round(time.monotonic() - start, 3),
            errors=exception_info(error),
            **fields,
        )
        raise
    else:
        trace.event(
            "phase_completed",
            phase=name,
            seconds=round(time.monotonic() - start, 3),
            **fields,
        )


def record_files(files):
    trace = CURRENT.get()
    if trace is None:
        return
    for index, filename in enumerate(files):
        path = Path(filename)
        try:
            trace.event(
                "local_file",
                index=index,
                size_bytes=path.stat().st_size,
                is_archive=path.suffix.lower() == ".aiida",
                free_bytes=shutil.disk_usage(path.parent).free,
            )
        except OSError as error:
            trace.event(
                "local_file_unavailable", index=index, errors=exception_info(error)
            )


def _observed_request(request, trace):
    def send(method, url, **kwargs):
        parts = urlsplit(url)
        # Deliberately exclude the URL/query, filename, sessionID and headers.
        query = parse_qs(parts.query)
        fields = {"host": parts.hostname, "request_id": str(uuid4())}
        for key in ("id", "startByte", "endByte"):
            values = query.get(key, [])
            if len(values) == 1 and values[0].isdigit():
                fields[key] = int(values[0])
        data = kwargs.get("data")
        size = len(data) if isinstance(data, (bytes, bytearray)) else 0
        if hasattr(data, "fileno"):
            try:
                size = max(0, os.fstat(data.fileno()).st_size - data.tell())
            except (OSError, ValueError):
                pass
        fields["body_bytes"] = size
        started = time.monotonic()
        with trace.lock:
            trace.pending[fields["request_id"]] = started
            trace.event("chunk_started", **fields)
        try:
            response = request(method, url, **kwargs)
        except Exception as error:
            with trace.lock:
                trace.failed_requests += 1
                trace.event(
                    "chunk_failed",
                    seconds=round(time.monotonic() - started, 3),
                    errors=exception_info(error),
                    **fields,
                )
            raise
        else:
            with trace.lock:
                status = response.status_code
                if 200 <= status < 300:
                    trace.completed_requests += 1
                    trace.confirmed_bytes += size
                else:
                    trace.failed_requests += 1
                trace.event(
                    "chunk_response",
                    http_status=status,
                    seconds=round(time.monotonic() - started, 3),
                    **fields,
                )
            return response
        finally:
            with trace.lock:
                trace.pending.pop(fields["request_id"], None)

    return send


def _chunk_method(method, trace):
    """Inject an observed queue into a private copy of pyBIS's pinned method.

    pyBIS exposes no queue/session injection hook. A function-local globals copy
    leaves its algorithm and original module untouched. If its implementation
    changes, retain phase diagnostics and report missing chunk instrumentation.
    """
    function = getattr(method, "__func__", None)
    if function is None or "DataSetUploadQueueNew" not in function.__code__.co_names:
        trace.event("chunk_instrumentation_unavailable")
        return method
    queue_class = function.__globals__.get("DataSetUploadQueueNew")
    if not isinstance(queue_class, type) or not hasattr(queue_class, "create_session"):
        trace.event("chunk_instrumentation_unavailable")
        return method

    class ObservedQueue(queue_class):
        def create_session(self, url_base):
            session = super().create_session(url_base)
            session.request = _observed_request(session.request, trace)
            return session

    namespace = dict(function.__globals__, DataSetUploadQueueNew=ObservedQueue)
    copied = FunctionType(
        function.__code__,
        namespace,
        function.__name__,
        function.__defaults__,
        function.__closure__,
    )
    copied.__kwdefaults__ = function.__kwdefaults__
    return MethodType(copied, method.__self__)


class _ObservedClient:
    """Proxy only this dataset's client, never the shared openBIS session."""

    def __init__(self, client, trace):
        self.client, self.trace = client, trace

    def __getattr__(self, name):
        return getattr(self.client, name)

    def _post_request_full_url(self, url, request, *args, **kwargs):
        if request.get("method") != "createUploadedDataSet":
            return self.client._post_request_full_url(url, request, *args, **kwargs)
        with phase("dataset_registration", self.trace, host=urlsplit(url).hostname):
            return self.client._post_request_full_url(url, request, *args, **kwargs)

    def get_dataset(self, *args, **kwargs):
        with phase("dataset_readback", self.trace):
            return self.client.get_dataset(*args, **kwargs)


@contextmanager
def observe_dataset(dataset):
    trace = CURRENT.get()
    if trace is None:
        yield
        return
    replacements = {}
    for name in ("upload_files_v3", "upload_files_v1"):
        method = getattr(dataset, name, None)
        if method is None:
            continue
        observed = _chunk_method(method, trace) if name.endswith("v3") else method

        def transfer(*args, _method=observed, _name=name, **kwargs):
            with phase(
                "chunk_transfer" if _name.endswith("v3") else "legacy_file_transfer",
                trace,
            ):
                return _method(*args, **kwargs)

        replacements[name] = transfer
    if "openbis" in dataset.__dict__:
        replacements["openbis"] = _ObservedClient(dataset.openbis, trace)
    saved = {
        name: (name in dataset.__dict__, dataset.__dict__.get(name))
        for name in replacements
    }
    try:
        for name, value in replacements.items():
            object.__setattr__(dataset, name, value)
        yield
    finally:
        for name, (existed, value) in saved.items():
            if existed:
                object.__setattr__(dataset, name, value)
            else:
                dataset.__dict__.pop(name, None)
