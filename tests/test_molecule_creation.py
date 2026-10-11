"""Tests for validated MOLECULE creation and attachment handling."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src import molecule_creation
from src.chemical_structures import representation_from_cdxml

GNR_CDXML = Path(__file__).parent / "data" / "periodic_gnr.cdxml"
PNG = b"\x89PNG\r\n\x1a\nreviewed-sketch"


class FakeObjectType:
    def __init__(self, codes):
        self._codes = codes

    def get_property_assignments(self):
        return SimpleNamespace(df=pd.DataFrame({"code": self._codes}))


class FakeSession:
    def __init__(self, codes=("NAME", "SUM_FORMULA", "CXSMILES")):
        self.object_type = FakeObjectType(codes)

    def get_object_type(self, code, use_cache=False):
        assert code == "MOLECULE"
        assert use_cache is False
        return self.object_type


def test_periodic_molecule_creation_preserves_reviewed_files(monkeypatch):
    session = FakeSession()
    cdxml = GNR_CDXML.read_bytes()
    representation = representation_from_cdxml(cdxml)
    created = SimpleNamespace(permId="new-molecule")
    object_calls = []
    dataset_calls = []
    temporary_paths = []

    def create_object(_session, **kwargs):
        object_calls.append(kwargs)
        return created

    def create_dataset(_session, **kwargs):
        path = Path(kwargs["files"][0])
        temporary_paths.append(path)
        dataset_calls.append(
            {
                "type": kwargs["type"],
                "name": kwargs["props"]["name"],
                "content": path.read_bytes(),
                "sample": kwargs["sample"],
            }
        )

    monkeypatch.setattr(molecule_creation.utils, "create_openbis_object", create_object)
    monkeypatch.setattr(
        molecule_creation.utils, "create_openbis_dataset", create_dataset
    )

    result = molecule_creation.create_molecule_from_cdxml(
        session,
        collection="/PRODUCTS",
        name="Reviewed GNR",
        description="Generated from AiiDA structure",
        comments="Checked bonds",
        cdxml=cdxml,
        png=PNG,
        filename="../reviewed.cdxml",
        expected_representation=representation,
    )

    assert result is created
    assert object_calls == [
        {
            "type": "MOLECULE",
            "collection": "/PRODUCTS",
            "props": {
                "name": "Reviewed GNR",
                "sum_formula": representation.formula,
                "description": "Generated from AiiDA structure",
                "comments": "Checked bonds",
                "cxsmiles": representation.cxsmiles,
            },
        }
    ]
    assert [item["type"] for item in dataset_calls] == [
        "ATTACHMENT",
        "ELN_PREVIEW",
    ]
    assert dataset_calls[0]["content"] == cdxml
    assert dataset_calls[1]["content"] == PNG
    assert all(item["sample"] is created for item in dataset_calls)
    assert all(
        path.name in {"reviewed.cdxml", "reviewed.png"} for path in temporary_paths
    )
    assert not any(path.exists() for path in temporary_paths)


def test_missing_cxsmiles_assignment_fails_before_remote_write(monkeypatch):
    session = FakeSession(("NAME", "SUM_FORMULA", "SMILES"))
    wrote = False

    def create_object(*_args, **_kwargs):
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(molecule_creation.utils, "create_openbis_object", create_object)

    with pytest.raises(molecule_creation.MoleculeCreationError, match="CXSMILES"):
        molecule_creation.create_molecule_from_cdxml(
            session,
            collection="/PRODUCTS",
            name="GNR",
            cdxml=GNR_CDXML.read_bytes(),
            png=PNG,
        )

    assert wrote is False


def test_partial_upload_reports_existing_object_permid(monkeypatch):
    session = FakeSession()
    created = SimpleNamespace(permId="partially-created")
    calls = 0

    monkeypatch.setattr(
        molecule_creation.utils,
        "create_openbis_object",
        lambda *_args, **_kwargs: created,
    )

    def create_dataset(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("preview unavailable")

    monkeypatch.setattr(
        molecule_creation.utils, "create_openbis_dataset", create_dataset
    )

    with pytest.raises(molecule_creation.PartialMoleculeCreationError) as caught:
        molecule_creation.create_molecule_from_cdxml(
            session,
            collection="/PRODUCTS",
            name="GNR",
            cdxml=GNR_CDXML.read_bytes(),
            png=PNG,
        )

    assert caught.value.permid == "partially-created"
    assert caught.value.completed_datasets == ("ATTACHMENT",)
    assert "Do not create another object" in str(caught.value)
