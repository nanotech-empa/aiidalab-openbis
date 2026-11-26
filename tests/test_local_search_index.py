"""Check local-only matching, incremental merges and bounded descriptor workers."""

from datetime import datetime, timezone

import pytest

from src import chemical_index_worker as worker
from src import local_search_index as store
from src.chemical_search import OpenbisChemicalIndex, SearchRepresentation


def raw(key, modified, **properties):
    return {
        "permId": {"permId": key},
        "identifier": {"identifier": "/MOLECULES/" + key},
        "modificationDate": modified,
        "properties": properties,
    }


class Session:
    url = "https://example.invalid/openbis"

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_objects(self, **kwargs):
        self.calls.append(kwargs)
        return {"objects": self.rows, "totalCount": len(self.rows)}

    def get_datasets(self, **kwargs):
        raise AssertionError("Valid SMILES do not require CDXML downloads")


@pytest.mark.parametrize("sqlite_available", [True, False])
def test_index_load_search_without_server_or_target_fingerprinting(
    tmp_path, monkeypatch, sqlite_available
):
    if not sqlite_available:
        monkeypatch.setattr(store, "sqlite3", None)
    stamp = store.now_ms()
    session = Session(
        [
            raw(
                "benzene",
                stamp,
                NAME="1",
                CHEMDRAW_NAME="Benzene",
                SMILES="C1=CC=CC=C1",
            ),
            raw("toluene", stamp, NAME="2", SMILES="Cc1ccccc1"),
        ]
    )
    index = store.SearchIndex(tmp_path / "test")
    worker.refresh_molecules(session, index, "/COLLECTION")
    assert len(session.calls) == 1
    lookup = OpenbisChemicalIndex(session, "/COLLECTION", tmp_path / "legacy.json")
    lookup.shared = index
    lookup.load_shared()

    def unexpected(*args, **kwargs):
        pytest.fail("Search used the server or recomputed a target fingerprint")

    monkeypatch.setattr(session, "get_objects", unexpected)
    monkeypatch.setattr(lookup, "_fingerprint", unexpected)
    with worker.DescriptorWorker() as helper:
        query = SearchRepresentation(**helper.describe("SMILES", "c1ccccc1")[0])
    hits = lookup.search(query, min_similarity=0.0)
    assert [(hit.record.permid, hit.match_type) for hit in hits] == [
        ("benzene", "exact"),
        ("toluene", "query contained in target"),
    ]
    assert hits[0].record.chemdraw_name == "Benzene"
    assert hits[0].record.representations[0].search_smiles == "c1ccccc1"
    assert len(hits[0].record.representations[0].fingerprint) == 344
    assert 0.0 < hits[1].similarity < 0.75
    assert lookup.search(query, min_similarity=0.875) == hits[:1]
    assert lookup.search(query, min_similarity=1.0) == hits[:1]


def test_delta_merges_records_with_equal_timestamps_and_preserves_descriptors(
    tmp_path, monkeypatch
):
    stamp = int(datetime(2026, 11, 25, 10, tzinfo=timezone.utc).timestamp() * 1000)
    monkeypatch.setattr(worker, "now_ms", lambda: stamp)
    index = store.SearchIndex(tmp_path / "test")
    session = Session([raw("a", stamp, SMILES="C")])
    worker.refresh_molecules(session, index, "/COLLECTION")
    session.rows = [
        raw("a", stamp, SMILES="C", CHEMDRAW_NAME="Methane"),
        raw("b", stamp, SMILES="CC"),
    ]
    original = worker.DescriptorWorker.describe
    described = []

    def describe(self, kind, content, **kwargs):
        described.append(content)
        return original(self, kind, content, **kwargs)

    monkeypatch.setattr(worker.DescriptorWorker, "describe", describe)
    worker.refresh_molecules(session, index, "/COLLECTION")
    assert described == ["CC"]
    assert session.calls[-1]["where"] == {"modificationDate": ">=2026-11-24"}
    _, rows = index.read("molecule:/COLLECTION")
    assert set(rows) == {"a", "b"}
    assert rows["a"][1]["chemdraw_name"] == "Methane"
    session.rows = [raw("b", stamp, SMILES="CC")]
    worker.refresh_molecules(session, index, "/COLLECTION", full=True)
    assert set(index.read("molecule:/COLLECTION")[1]) == {"b"}
    assert described == ["CC"]


def test_archive_lookup_always_checks_latest_server_records(tmp_path):
    stamp = store.now_ms()
    index = store.SearchIndex(tmp_path / "test")
    session = Session([raw("archive-a", stamp, WFMS_UUID="uuid-a")])
    assert store.refresh_uuid_list(session, index, "AIIDA_NODE") == ["uuid-a"]
    session.rows = [raw("archive-b", stamp, WFMS_UUID="uuid-b")]
    assert set(store.refresh_uuid_list(session, index, "AIIDA_NODE")) == {
        "uuid-a",
        "uuid-b",
    }
    assert "where" in session.calls[-1]
    assert index.read("uuid:AIIDA_NODE")[1]["archive-b"][1]["uuid"] == "uuid-b"


def test_descriptor_timeout_reaps_worker_and_allows_next_molecule():
    with worker.DescriptorWorker(timeout=1e-6) as helper:
        with pytest.raises(TimeoutError):
            helper.describe("SMILES", "CCC")
        assert helper.process is None
        helper.timeout = 4
        assert helper.describe("SMILES", "C")[0]["search_smiles"] == "C"


def test_two_tabs_cannot_admit_same_background_job(tmp_path):
    index = store.SearchIndex(tmp_path / "test")
    with store.index_lock(index, "background", blocking=False) as first:
        assert first is not None
        with store.index_lock(index, "background", blocking=False) as second:
            assert second is None
    with store.index_lock(index, "background", blocking=False) as retry:
        assert retry is not None
