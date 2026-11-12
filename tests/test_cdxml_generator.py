"""Regression tests for reviewed AiiDA-structure to CDXML generation."""

from pathlib import Path

from ase.io import read
from aiidalab_widgets_empa.cdxml_rendering import render_cdxml_png

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
    assert editor.last_png == render_cdxml_png(editor.last_cdxml)
    assert max(int(editor.png_preview.width), int(editor.png_preview.height)) <= 300
    assert exported[0][0] == editor.last_cdxml
    assert "Download CDXML" in editor.export_result.value


def test_pending_bond_is_visible_only_in_review_png():
    import numpy as np
    from io import BytesIO
    from PIL import Image
    from src.cdxml_editor import bond_key
    from src.cdxml_generator import PeriodicBond

    editor = PeriodicCdxmlEditor(structure=read(DATA / "periodic_gnr_structure.xyz"))
    # Add a review-only candidate without accepting it into the chemical graph.
    candidate = PeriodicBond(begin=0, end=4, shift=0, distance=2.1, order=1)
    assert bond_key(candidate) not in {
        bond_key(bond) for bond in editor._current_bonds()
    }
    editor.candidates[bond_key(candidate)] = candidate
    reviewed = np.asarray(
        Image.open(BytesIO(editor._render_png(show_suggestions=True)))
    )
    orange = (
        (reviewed[:, :, 0] > 150)
        & (reviewed[:, :, 1] > 60)
        & (reviewed[:, :, 1] < 180)
        & (reviewed[:, :, 2] < 80)
    )
    assert orange.any()
    editor._export_clicked(None)
    final = np.asarray(Image.open(BytesIO(editor.last_png)))
    orange = (
        (final[:, :, 0] > 150)
        & (final[:, :, 1] > 60)
        & (final[:, :, 1] < 180)
        & (final[:, :, 2] < 80)
    )
    assert not orange.any()
    assert b"suggestion-" not in editor.last_cdxml
