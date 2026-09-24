"""Tests for collection-scoped SMILES/CDXML search."""

from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
from types import SimpleNamespace

from src.chemical_search import (
    OpenbisChemicalIndex,
    match_quality_to_tanimoto,
    search_representation_from_cdxml,
    search_representation_from_smiles,
    search_representations_from_cdxml,
    tanimoto_to_match_quality,
)
from src.chemical_structures import generate_periodic_cxsmiles


GNR_CDXML = Path(__file__).parent / "data" / "periodic_gnr.cdxml"


class Properties(dict):
    def all(self):
        return dict(self)


class FakeSession:
    url = "https://openbis-dev.example"

    def __init__(self, objects, datasets=()):
        self.objects = list(objects)
        self.datasets = list(datasets)
        self.object_calls = []
        self.dataset_calls = []

    def get_objects(self, **kwargs):
        self.object_calls.append(kwargs)
        return self.objects

    def get_datasets(self, **kwargs):
        self.dataset_calls.append(kwargs)
        return self.datasets


class FakeDataset:
    type = "ATTACHMENT"

    def __init__(self, permid, sample, filename, content):
        self.permId = permid
        self.sample = sample
        self.file_list = [filename]
        self.filename = filename
        self.content = content

    def download(self, files, destination):
        assert files == [self.filename]
        target = Path(destination) / self.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.content)


def molecule(permid, **properties):
    return SimpleNamespace(
        permId=permid,
        identifier=f"/MOLECULES/{permid}",
        modificationDate="2026-09-24",
        props=Properties(properties),
    )


def test_quality_scale_starts_at_seventy_five_percent():
    assert match_quality_to_tanimoto(0) == 0.75
    assert match_quality_to_tanimoto(100) == 1.0
    assert tanimoto_to_match_quality(0.75) == 0
    assert tanimoto_to_match_quality(1.0) == 100


def test_index_is_scoped_to_one_molecule_collection(tmp_path):
    session = FakeSession(
        [
            molecule(
                "ethanol",
                name="Ethanol",
                empa_number=42,
                sum_formula="C2H6O",
                smiles="CCO",
            )
        ]
    )
    collection = "/LAB205_MATERIALS/MOLECULES/PRECURSOR_COLLECTION"
    index = OpenbisChemicalIndex(
        session,
        collection,
        cache_path=tmp_path / "index.json",
    ).refresh()

    assert session.object_calls == [
        {"type": "MOLECULE", "collection": collection}
    ]
    assert session.dataset_calls == [{"sample": ["ethanol"]}]
    hit = index.search(search_representation_from_smiles("OCC"))[0]
    assert hit.record.permid == "ethanol"
    assert hit.match_type == "exact"
    assert hit.similarity == 1.0


def test_periodic_cxsmiles_property_matches_periodic_cdxml(tmp_path):
    generated = generate_periodic_cxsmiles(GNR_CDXML.read_bytes())
    collection = "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION"
    session = FakeSession(
        [
            molecule(
                "gnr",
                name="Test GNR",
                sum_formula=generated.formula,
                cxsmiles=generated.cxsmiles,
            )
        ]
    )
    index = OpenbisChemicalIndex(
        session,
        collection,
        cache_path=tmp_path / "index.json",
    ).refresh()

    query = search_representation_from_cdxml(GNR_CDXML.read_bytes())
    hits = index.search(query)

    assert len(hits) == 1
    assert hits[0].record.permid == "gnr"
    assert hits[0].match_type == "exact"
    assert hits[0].periodic is True
    assert index.summary["with_cxsmiles"] == 1


def test_search_index_expands_multiple_periodic_repeat_units():
    root = ET.fromstring(GNR_CDXML.read_bytes().decode("utf-8-sig"))
    page = next(
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "page"
    )
    group = next(
        element
        for element in page
        if element.tag.rsplit("}", 1)[-1] == "bracketedgroup"
    )
    duplicate = deepcopy(group)
    duplicate.attrib["id"] = "999"
    page.append(duplicate)

    representations = search_representations_from_cdxml(
        ET.tostring(root, encoding="unicode"),
        "two-repeats.cdxml",
    )

    assert len(representations) == 2
    assert representations[0].strict_key == representations[1].strict_key
    assert representations[0].source_id.endswith("#repeat-1")
    assert representations[1].source_id.endswith("#repeat-2")


def test_cdxml_attachment_is_fallback_for_missing_properties(tmp_path):
    record = molecule("attachment-only", name="Attachment only")
    dataset = FakeDataset(
        "dataset-1",
        record.permId,
        "structure.cdxml",
        b"""<CDXML><page><fragment>
          <n id="1" p="0 0"/><n id="2" p="1 0"/>
          <b id="3" B="1" E="2" Order="1"/>
        </fragment></page></CDXML>""",
    )
    session = FakeSession([record], [dataset])
    index = OpenbisChemicalIndex(
        session,
        "/LAB205_MATERIALS/MOLECULES/PRECURSOR_COLLECTION",
        cache_path=tmp_path / "index.json",
    ).refresh()

    hits = index.search(search_representation_from_smiles("CC"))

    assert len(hits) == 1
    assert hits[0].record.permid == record.permId
    assert hits[0].match_type == "exact"
    assert index.summary["cdxml_parsed"] == 1


def test_cache_rejects_another_collection(tmp_path):
    cache = tmp_path / "index.json"
    session = FakeSession([molecule("ethanol", name="Ethanol", smiles="CCO")])
    OpenbisChemicalIndex(session, "/COLLECTION/A", cache_path=cache).refresh()

    other = OpenbisChemicalIndex(session, "/COLLECTION/B", cache_path=cache)

    try:
        other.load()
    except ValueError as exc:
        assert "another collection" in str(exc)
    else:
        raise AssertionError("A chemical index must not cross collection boundaries")
