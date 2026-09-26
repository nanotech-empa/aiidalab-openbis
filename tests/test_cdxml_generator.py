"""Regression tests for reviewed AiiDA-structure to CDXML generation."""

from pathlib import Path

from ase.io import read

from src.cdxml_editor import PeriodicCdxmlEditor
from src.chemical_search import search_representation_from_cdxml
from src.chemical_structures import representation_from_cdxml

DATA = Path(__file__).parent / "data"


def test_reviewed_periodic_geometry_generates_validated_search_query():
    atoms = read(DATA / "periodic_gnr_structure.xyz")
    exported = []
    editor = PeriodicCdxmlEditor(
        structure=atoms,
        on_export=lambda *values: exported.append(values),
    )

    assert editor._valid
    editor._export_clicked(None)

    query = search_representation_from_cdxml(editor.last_cdxml, editor.filename)
    reference = representation_from_cdxml((DATA / "periodic_gnr.cdxml").read_bytes())
    assert query.periodic
    assert query.formula == "C36H4"
    assert query.periodic_key == reference.periodic_key
    assert editor.last_representation.cxsmiles == reference.cxsmiles
    assert editor.last_png.startswith(b"\x89PNG")
    assert exported[0][0] == editor.last_cdxml
    assert "Download CDXML" in editor.export_result.value
