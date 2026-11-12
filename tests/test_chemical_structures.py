"""Tests for validated periodic chemical representations."""

from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from src.chemical_structures import (
    PeriodicStructureError,
    generate_periodic_cxsmiles,
    periodic_graph_from_cxsmiles,
    periodic_graph_key,
    periodic_graphs_from_cdxml,
    representation_from_cdxml,
    representation_from_smiles,
    AtomSpec,
    PeriodicGraph,
    _encode_cxsmiles,
)


GNR_CDXML = Path(__file__).parent / "data" / "periodic_gnr.cdxml"
EXPECTED_GNR_CXSMILES = (
    "c1(*)c(*)c2c(c3c1c1c(*)c(*)c4c5c(*)c(*)c6c(c5c(*)c(*)c4c1c(*)c3*)"
    "=C(*)C(=*)C(=C*)C(=C*)C6=*)=C(*)C(*)=C(C=*)C(C=*)=C2* "
    "|Sg:n:0,2,4,5,6,7,8,9,11,13,14,15,17,19,20,21,22,24,26,27,28,30,"
    "32,34,36,37,39,40,42,44,46,48,49,51,52,54:n:ht:"
    "35,50,32,26,24,37,39,42,52,55:0,2,10,12,16,18,48,45,61,58:|"
)


@pytest.fixture(scope="module")
def periodic_gnr():
    return generate_periodic_cxsmiles(GNR_CDXML.read_bytes())


def test_periodic_gnr_cxsmiles_round_trip(periodic_gnr):
    assert periodic_gnr.formula == "C36H4"
    assert periodic_gnr.atoms_per_repeat == 36
    assert periodic_gnr.crossing_bond_pairs == 10
    assert " |Sg:n:" in periodic_gnr.cxsmiles
    assert (
        periodic_graph_key(periodic_graph_from_cxsmiles(periodic_gnr.cxsmiles))
        == periodic_gnr.periodic_key
    )


def test_periodic_gnr_cxsmiles_is_stable(periodic_gnr):
    regenerated = generate_periodic_cxsmiles(GNR_CDXML.read_bytes())
    assert regenerated == periodic_gnr
    assert regenerated.cxsmiles == EXPECTED_GNR_CXSMILES


def test_bracket_annotation_offset_keeps_unique_periodic_mapping(periodic_gnr):
    root = ET.fromstring(GNR_CDXML.read_bytes().decode("utf-8-sig"))
    right_bracket = next(
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "graphic"
        and element.attrib.get("id") == "265"
    )
    bounds = [float(value) for value in right_bracket.attrib["BoundingBox"].split()]
    bounds[0] -= 2.0
    bounds[2] -= 2.0
    right_bracket.attrib["BoundingBox"] = " ".join(map(str, bounds))

    shifted = generate_periodic_cxsmiles(ET.tostring(root, encoding="unicode"))

    assert shifted.periodic_key == periodic_gnr.periodic_key


def test_invalid_crossing_pair_order_is_rejected(periodic_gnr):
    base, extension = periodic_gnr.cxsmiles.split(" |", maxsplit=1)
    fields = extension[:-1].split(":")
    tails = fields[6].split(",")
    fields[6] = ",".join(tails[1:] + tails[:1])
    changed = f"{base} |{':'.join(fields)}|"

    with pytest.raises(PeriodicStructureError, match="different bond orders"):
        periodic_graph_from_cxsmiles(changed)


def test_multiple_repeat_units_are_searchable_but_not_convertible():
    root = ET.fromstring(GNR_CDXML.read_bytes().decode("utf-8-sig"))
    page = next(
        element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "page"
    )
    group = next(
        element
        for element in page
        if element.tag.rsplit("}", 1)[-1] == "bracketedgroup"
    )
    duplicate = deepcopy(group)
    duplicate.attrib["id"] = "999"
    page.append(duplicate)
    content = ET.tostring(root, encoding="unicode")

    graphs = periodic_graphs_from_cdxml(content)

    assert len(graphs) == 2
    assert periodic_graph_key(graphs[0]) == periodic_graph_key(graphs[1])
    with pytest.raises(PeriodicStructureError, match="Exactly one bracketed"):
        generate_periodic_cxsmiles(content)


def test_non_periodic_cdxml_does_not_generate_cxsmiles():
    content = b"""<CDXML><page><fragment>
      <n id="1" p="0 0"/><n id="2" p="1 0"/>
      <b id="3" B="1" E="2" Order="1"/>
    </fragment></page></CDXML>"""

    with pytest.raises(PeriodicStructureError, match="no bracketed repeat unit"):
        generate_periodic_cxsmiles(content)


def test_finite_cdxml_generates_smiles_only():
    content = b"""<CDXML><page><fragment>
      <n id="1" p="0 0"/><n id="2" p="1 0"/>
      <b id="3" B="1" E="2" Order="1"/>
    </fragment></page></CDXML>"""

    representation = representation_from_cdxml(content)

    assert representation.smiles == "CC"
    assert representation.cxsmiles == ""
    assert representation.formula == "C2H6"
    assert representation.periodic is False


def test_smiles_input_is_canonicalized():
    representation = representation_from_smiles("C(O)C")

    assert representation.smiles == "CCO"
    assert representation.cxsmiles == ""
    assert representation.formula == "C2H6O"


def test_synthetic_fused_five_seven_repeat_keys_ignore_atom_order_and_kekule_phase():
    from dataclasses import replace
    from src.chemical_structures import periodic_formula

    # Two four-site rails with offset rungs: adjacent bounded faces have 5 and 7 edges.
    graph = PeriodicGraph(
        (AtomSpec(6),) * 8,
        (
            (0, 1, 0, 2.0),
            (1, 2, 0, 1.0),
            (2, 3, 0, 2.0),
            (3, 0, 1, 1.0),
            (4, 5, 0, 2.0),
            (5, 6, 0, 1.0),
            (6, 7, 0, 2.0),
            (7, 4, 1, 1.0),
            (0, 4, 0, 1.0),
            (1, 6, 0, 1.0),
        ),
    )
    assert periodic_formula(graph) == "C8H4"
    original = periodic_graph_key(graph)
    order = (4, 7, 1, 5, 0, 6, 3, 2)
    inverse = {old: new for new, old in enumerate(order)}
    changed = replace(
        graph,
        atoms=tuple(graph.atoms[index] for index in order),
        bonds=tuple(
            (inverse[b], inverse[e], shift, kind)
            for b, e, shift, kind in reversed(graph.bonds)
        ),
    )
    assert periodic_graph_key(changed) == original
    assert (
        periodic_graph_key(periodic_graph_from_cxsmiles(_encode_cxsmiles(graph)))
        == original
    )


def test_periodic_key_retains_isotopes_charges_and_radicals():
    from dataclasses import replace

    graph = PeriodicGraph((AtomSpec(6, explicit_hydrogens=2),), ((0, 0, 1, 1.0),))
    base = periodic_graph_key(graph)
    assert (
        periodic_graph_key(
            replace(graph, atoms=(AtomSpec(6, isotope=13, explicit_hydrogens=2),))
        )
        != base
    )
    radical = replace(
        graph, atoms=(AtomSpec(6, radical_electrons=1, explicit_hydrogens=1),)
    )
    assert periodic_graph_key(radical) != base
    charged = replace(graph, atoms=(AtomSpec(6, charge=-1, explicit_hydrogens=1),))
    assert periodic_graph_key(charged) != base


def test_periodic_stereochemistry_is_reported_instead_of_discarded():
    root = ET.fromstring(GNR_CDXML.read_bytes().decode("utf-8-sig"))
    next(
        element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "b"
    ).set("BS", "E")
    with pytest.raises(PeriodicStructureError, match="stereochemistry"):
        generate_periodic_cxsmiles(ET.tostring(root))


def test_unreadable_finite_CIP_assignment_does_not_become_an_achiral_exact_key():
    content = b'<CDXML><page><fragment><n id="1" p="0 0" AS="R"/><n id="2" p="30 0" Element="9"/><n id="3" p="0 30" Element="17"/><n id="4" p="-30 0" Element="35"/><b B="1" E="2"/><b B="1" E="3"/><b B="1" E="4"/></fragment></page></CDXML>'
    with pytest.raises(ValueError, match="cannot be verified"):
        representation_from_cdxml(content)
