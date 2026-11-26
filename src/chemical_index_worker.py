"""Bound native chemistry work and refresh the shared local molecule snapshot."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from dataclasses import asdict
from pathlib import Path

from .local_search_index import (
    MAX_AGE_MS,
    account_index,
    fetch_objects,
    identifier,
    index_lock,
    now_ms,
    object_fields,
)

PROJECT = Path(__file__).resolve().parent.parent
DESCRIPTOR_TIMEOUT = 4.0


class DescriptorWorker:
    """Reuse one plain-data subprocess; replace it if a native call stalls."""

    def __init__(self, timeout=DESCRIPTOR_TIMEOUT):
        self.timeout = timeout
        self.process = self.socket = self.reader = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        if self.reader:
            self.reader.close()
            self.socket.close()
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            self.process = self.socket = self.reader = None

    def _start(self):
        sock, child = socket.socketpair()
        with child:
            try:
                self.process = subprocess.Popen(
                    [
                        sys.executable,
                        "-B",
                        "-m",
                        "src.chemical_index_worker",
                        "describe",
                        str(child.fileno()),
                    ],
                    cwd=PROJECT,
                    pass_fds=(child.fileno(),),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                sock.close()
                raise
        self.socket = sock
        self.reader = sock.makefile("rb")

    def describe(self, kind, content, *, formula="", source_id=""):
        if self.process is None:
            self._start()
        request = [kind, content, formula, source_id]
        self.socket.settimeout(self.timeout)
        try:
            self.socket.sendall(json.dumps(request).encode() + b"\n")
            response = json.loads(self.reader.readline())
        except (TimeoutError, OSError, ValueError) as error:
            self.close()
            if isinstance(error, TimeoutError):
                raise TimeoutError("molecular descriptor time limit exceeded") from None
            raise ValueError("molecular descriptor worker failed") from None
        if "error" in response:
            raise ValueError(response["error"])
        return response["descriptors"]


def _describe(fd):
    # This process owns no credentials, openBIS client, profile or widget state.
    from .chemical_search import (
        Chem,
        DataStructs,
        _MORGAN,
        rdBase,
        search_representation_from_cxsmiles,
        search_representation_from_smiles,
        search_representations_from_cdxml,
    )

    with socket.socket(fileno=fd) as channel, channel.makefile("rb") as reader:
        blocker = rdBase.BlockLogs()
        for line in reader:
            try:
                kind, content, formula, source_id = json.loads(line)
                if kind == "SMILES":
                    representations = [
                        search_representation_from_smiles(
                            content, source_id=source_id or "property:SMILES"
                        )
                    ]
                elif kind == "CXSMILES":
                    representations = [
                        search_representation_from_cxsmiles(content, formula=formula)
                    ]
                elif kind == "CDXML":
                    representations = search_representations_from_cdxml(
                        base64.b64decode(content, validate=True), source_id
                    )
                else:
                    raise ValueError("Invalid molecular input kind")
                descriptors = []
                for rep in representations:
                    mol = Chem.MolFromSmiles(rep.search_smiles)
                    bitvector = DataStructs.BitVectToBinaryText(
                        _MORGAN.GetFingerprint(mol)
                    )
                    descriptors.append(
                        dict(
                            asdict(rep),
                            fingerprint=base64.b64encode(bitvector).decode("ascii"),
                        )
                    )
                response = {"descriptors": descriptors}
            except Exception as error:
                response = {"error": type(error).__name__}
            channel.sendall(json.dumps(response).encode() + b"\n")
        del blocker


def _record(raw, collection):
    from datetime import datetime, timezone

    key, modified, props = object_fields(raw)
    row = {
        "permid": key,
        "identifier": identifier(raw.get("identifier")),
        "collection": collection,
        "name": str(props.get("name") or ""),
        "chemdraw_name": str(props.get("chemdraw_name") or ""),
        "empa_number": str(props.get("empa_number") or ""),
        "formula": str(props.get("sum_formula") or ""),
        "smiles": str(props.get("smiles") or "").strip(),
        "cxsmiles": str(props.get("cxsmiles") or "").strip(),
        "modification_date": datetime.fromtimestamp(
            modified / 1000, timezone.utc
        ).isoformat(),
        "representations": [],
        "errors": [],
    }
    return key, modified, row


def refresh_molecules(session, index, collection, *, full=False):
    """Update changed records only. An explicit full inventory also prunes deletions."""
    from .chemical_search import (
        DATASET_TYPES,
        _dataset_cdxml_files,
        _reference,
        _type_code,
        download_dataset_file,
    )

    scope = f"molecule:{collection}"
    state, old = index.read(scope)
    checked_at = now_ms()
    cursor = state[1] if state and state[2] else 0
    all_records = (
        full or not cursor or checked_at // 86_400_000 != state[0] // 86_400_000
    )
    records = {} if all_records else old.copy()
    raw_rows = fetch_objects(
        session, "MOLECULE", collection=collection, cursor=0 if all_records else cursor
    )
    fallback = {}
    with DescriptorWorker() as worker:
        for raw in raw_rows:
            key, modified, row = _record(raw, collection)
            previous = old.get(key)
            same_structure = previous and all(
                previous[1][field] == row[field]
                for field in ("smiles", "cxsmiles", "formula")
            )
            reusable = same_structure and (
                any(
                    rep["source"] in {"SMILES", "CXSMILES"}
                    for rep in previous[1]["representations"]
                )
                or (not all_records and previous[0] == modified)
            )
            if state and state[2] and reusable:
                row["representations"] = previous[1]["representations"]
                row["errors"] = previous[1]["errors"]
                records[key] = modified, row
                continue
            for kind in ("SMILES", "CXSMILES"):
                code = row[kind.lower()]
                if not code:
                    continue
                try:
                    row["representations"].extend(
                        worker.describe(kind, code, formula=row["formula"])
                    )
                except (TimeoutError, ValueError) as error:
                    row["errors"].append(f"{kind}: {error}")
            if not row["representations"]:
                fallback[key] = row
                if row["identifier"]:
                    fallback[row["identifier"]] = row
            records[key] = modified, row
        if fallback:
            permids = sorted({row["permid"] for row in fallback.values()})
            for dataset in session.get_datasets(sample=permids) or []:
                row = fallback.get(_reference(dataset.sample))
                if row is None or _type_code(dataset.type) not in DATASET_TYPES:
                    continue
                try:
                    filenames = _dataset_cdxml_files(dataset)
                except Exception:
                    row["errors"].append("CDXML: could not inspect dataset files")
                    continue
                for filename in filenames:
                    try:
                        content = download_dataset_file(dataset, filename)
                        reps = worker.describe(
                            "CDXML",
                            base64.b64encode(content).decode("ascii"),
                            source_id=f"{_reference(dataset)}::{filename}",
                        )
                        row["representations"].extend(reps)
                    except Exception as error:
                        row["errors"].append(f"CDXML: {type(error).__name__}")
    latest = max((modified for modified, _ in records.values()), default=0)
    index.write(scope, records, checked_at=checked_at, cursor=latest)
    return len(records)


def prepare_index_in_background(session, collections, *, force=False, uuid_lists=False):
    """Start at most one update per account. Hold no widget, ORM or client reference."""
    index = account_index(session)
    if index is None:
        return False
    collections = tuple(dict.fromkeys(collections))
    if not force:
        cutoff = now_ms() - MAX_AGE_MS
        collections = tuple(
            collection
            for collection in collections
            if not (state := index.state(f"molecule:{collection}"))
            or not state[2]
            or state[0] < cutoff
        )
        uuid_lists = uuid_lists and any(
            index.state(f"uuid:{code}") is None
            for code in ("AIIDA_NODE", "ATOMISTIC_MODEL")
        )
        if not collections and not uuid_lists:
            return False

    payload = json.dumps(
        {
            "stem": str(index.stem),
            "url": str(session.url),
            "token": session.token,
            "collections": collections,
            "uuid_lists": uuid_lists,
        }
    ).encode()

    # The child inherits the lock, so even closing the launching browser tab
    # cannot admit a second writer while the first worker is still active.
    with index_lock(index, "background", blocking=False) as lock:
        if lock is None:
            return False
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "src.chemical_index_worker", "refresh"],
            cwd=PROJECT,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(lock.fileno(),),
        )
    threading.Thread(
        target=_finish_background, args=(process, payload), daemon=True
    ).start()
    return True


def refresh_in_progress(index):
    with index_lock(index, "background", blocking=False) as lock:
        return lock is None


def _finish_background(process, payload):
    try:
        process.communicate(input=payload, timeout=190)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def _refresh_timeout(_signal, _frame):
    raise TimeoutError("openBIS index refresh exceeded its time limit")


def _refresh():
    import requests

    from .local_search_index import SearchIndex, refresh_uuid_list
    from .utils import connect_openbis

    # pyBIS does not set HTTP timeouts for metadata requests or DSS downloads.
    # Confine the deadline to this short-lived read-only process.
    original_request = requests.Session.request

    def request_with_timeout(client, *args, **kwargs):
        kwargs.setdefault("timeout", (5, 15))
        return original_request(client, *args, **kwargs)

    requests.Session.request = request_with_timeout

    # Only this worker receives the secret, via stdin. Disable pyBIS diagnostics
    # that can print an authenticated request (the parent also discards stderr).
    signal.signal(signal.SIGALRM, _refresh_timeout)
    signal.alarm(180)
    request = json.load(sys.stdin)
    index = SearchIndex(request["stem"])
    # Parent keeps the lock open until this process exits.
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink):
        session, _ = connect_openbis(request["url"], request["token"])
        if session is None:
            raise RuntimeError("The openBIS connection is unavailable")
        for collection in request["collections"]:
            refresh_molecules(session, index, collection)
        if request["uuid_lists"]:
            for code in ("AIIDA_NODE", "ATOMISTIC_MODEL"):
                refresh_uuid_list(session, index, code)


if __name__ == "__main__":
    if sys.argv[1] == "describe":
        _describe(int(sys.argv[2]))
    else:
        _refresh()
