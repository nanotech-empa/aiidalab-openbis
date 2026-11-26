"""Private, versioned snapshots of searchable openBIS metadata and descriptors."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import sqlite3
except ImportError:  # CPython builds can omit the extension.
    sqlite3 = None


CACHE_DIR = Path.home() / ".cache" / "aiidalab-openbis"
MAX_AGE_MS = 5 * 60_000
VERSION = 1
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS snapshots (scope TEXT PRIMARY KEY, "
    "checked_at INTEGER NOT NULL, cursor INTEGER NOT NULL, ready INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS entries (scope TEXT NOT NULL, key TEXT NOT NULL, "
    "modified INTEGER NOT NULL, payload TEXT NOT NULL, "
    "PRIMARY KEY(scope,key)) WITHOUT ROWID",
)


def now_ms():
    return time.time_ns() // 1_000_000


def account_index(session):
    """Return the cache for a validated pyBIS connection, without storing its token."""
    from pybis import Openbis

    if not isinstance(session, Openbis):
        return None
    username = session._get_username()
    if not username:
        return None
    identity = f"{str(session.url).rstrip('/')}\n{username}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:32]
    return SearchIndex(CACHE_DIR / f"search-index-{digest}")


def identifier(value):
    if isinstance(value, dict):
        return str(
            value.get("permId") or value.get("identifier") or value.get("code") or ""
        )
    return str(value or "")


def date_filter(cursor):
    """Re-read overlapping dates, and deduplicate by permId.

    pyBIS accepts UTC calendar dates for this criterion. A one-day overlap
    also covers server timezone boundaries and rows sharing a modification stamp.
    """
    day = datetime.fromtimestamp(cursor / 1000, timezone.utc) - timedelta(days=1)
    return {"modificationDate": f">={day.date().isoformat()}"}


def fetch_objects(session, object_type, *, collection=None, cursor=0):
    kwargs = {"type": object_type, "raw_response": True}
    if collection is not None:
        kwargs["collection"] = collection
    if cursor:
        kwargs["where"] = date_filter(cursor)
    response = session.get_objects(**kwargs)
    rows = response["objects"]
    if len(rows) != response["totalCount"]:
        raise ValueError("openBIS returned an incomplete inventory")
    return rows


def object_fields(raw):
    key = identifier(raw["permId"])
    modified = int(raw.get("modificationDate") or raw["registrationDate"])
    props = {key.lower(): value for key, value in raw.get("properties", {}).items()}
    if not key:
        raise ValueError("openBIS record is missing permId")
    return key, modified, props


def _private_file(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The OS applies this mode before the first byte is written.
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)


class SearchIndex:
    """One per-account cache, with transactional SQLite or atomic JSON snapshots."""

    def __init__(self, stem):
        self.stem = Path(stem)
        self.path = self.stem.with_suffix(".sqlite3" if sqlite3 else ".json")

    def state(self, scope):
        return self.read(scope, include_rows=False)[0]

    def read(self, scope, *, include_rows=True):
        if sqlite3 is None:
            try:
                snapshot = json.loads(self._json_path(scope).read_text())
            except FileNotFoundError:
                return None, {}
            if snapshot.get("version") != VERSION:
                return None, {}
            return tuple(snapshot["state"]), snapshot["rows"] if include_rows else {}
        if not self.path.exists():
            return None, {}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] != VERSION:
                return None, {}
            state = db.execute(
                "SELECT checked_at,cursor,ready FROM snapshots WHERE scope=?", (scope,)
            ).fetchone()
            if not include_rows:
                return state, {}
            rows = {
                key: (modified, json.loads(payload))
                for key, modified, payload in db.execute(
                    "SELECT key,modified,payload FROM entries WHERE scope=?", (scope,)
                )
            }
        return state, rows

    def _json_path(self, scope):
        key = hashlib.sha256(scope.encode()).hexdigest()[:32]
        return self.stem.with_name(f"{self.stem.name}-{key}").with_suffix(".json")

    def write(self, scope, rows, *, checked_at, cursor, ready=True):
        state = checked_at, cursor, int(ready)
        if sqlite3 is None:
            path = self._json_path(scope)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, delete=False
            ) as file:
                tmp = Path(file.name)
                try:
                    json.dump({"version": VERSION, "state": state, "rows": rows}, file)
                    file.flush()
                    tmp.replace(path)
                finally:
                    tmp.unlink(missing_ok=True)
            return
        _private_file(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version != VERSION:
                db.execute("DROP TABLE IF EXISTS entries")
                db.execute("DROP TABLE IF EXISTS snapshots")
                for sql in _SCHEMA:
                    db.execute(sql)
                db.execute(f"PRAGMA user_version={VERSION}")
            db.execute("DELETE FROM entries WHERE scope=?", (scope,))
            db.executemany(
                "INSERT INTO entries VALUES (?,?,?,?)",
                (
                    (scope, key, modified, json.dumps(payload, separators=(",", ":")))
                    for key, (modified, payload) in rows.items()
                ),
            )
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (scope, *state)
            )


@contextmanager
def index_lock(index, scope, *, blocking=True):
    key = hashlib.sha256(scope.encode()).hexdigest()[:16]
    path = index.stem.with_name(f"{index.stem.name}-{key}.lock")
    _private_file(path)
    with path.open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield None
        else:
            yield lock


def refresh_uuid_list(session, index, object_type):
    """Combine cached UUIDs with newly modified records, serialized across tabs."""
    with index_lock(index, f"uuid:{object_type}"):
        return _refresh_uuid_list(session, index, object_type)


def _refresh_uuid_list(session, index, object_type):
    """Look for recent openBIS records on each lookup, merging by permId."""
    scope = f"uuid:{object_type}"
    state, local = index.read(scope)
    checked_at = now_ms()
    cursor = state[1] if state else 0
    # Periodically reconcile deletions, which a timestamp delta cannot return.
    full = not cursor or checked_at // 86_400_000 != state[0] // 86_400_000
    rows = fetch_objects(session, object_type, cursor=0 if full else cursor)
    if full:
        local.clear()
    for raw in rows:
        key, modified, props = object_fields(raw)
        local[key] = (
            modified,
            {"permid": key, "uuid": str(props.get("wfms_uuid") or "")},
        )
    latest = max((modified for modified, _ in local.values()), default=0)
    index.write(scope, local, checked_at=checked_at, cursor=latest)
    return [row["uuid"] for _, row in local.values() if row["uuid"]]
