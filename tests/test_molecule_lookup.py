"""Molecule suggestions across preprocessing, without live openBIS connections."""

from types import SimpleNamespace

import pytest
from test_aiida_utils import FakeOpenbisObject, FakeSession
from test_aiida_utils import aiida_utils as _aiida_utils_fixture
from test_simulations_widgets import simulations_widgets as _widgets_fixture

aiida_utils = _aiida_utils_fixture
simulations_widgets = _widgets_fixture


@pytest.fixture
def structures(aiida_utils, aiida_profile_clean):
    """Build provenance only in the disposable test profile."""
    orm = aiida_utils.orm
    link_type = aiida_utils.LinkType

    def new_structure():
        return orm.StructureData(ase=aiida_utils.Atoms("CH4")).store()

    def preprocess(inputs, creator_class=orm.CalcFunctionNode, caller=None):
        creator = creator_class()
        if caller is not None:
            creator.base.links.add_incoming(
                caller, link_type=link_type.CALL_CALC, link_label="prepare"
            )
        for label, node in inputs.items():
            creator.base.links.add_incoming(
                node, link_type=link_type.INPUT_CALC, link_label=label
            )
        creator.store()
        output = orm.StructureData(ase=aiida_utils.Atoms("CH4"))
        output.base.links.add_incoming(
            creator, link_type=link_type.CREATE, link_label="result"
        )
        return output.store()

    def link_molecule(structure, molecule):
        structure.base.extras.set(
            "eln",
            {
                "eln_type": "openbis",
                "eln_instance": "https://openbis.example",
                "data_type": "MOLECULE",
                "sample_uuid": molecule.permId,
            },
        )

    return SimpleNamespace(
        new=new_structure, preprocess=preprocess, link_molecule=link_molecule
    )


def test_direct_structure_links_take_priority(aiida_utils, structures):
    previous = FakeOpenbisObject("MOLECULE")
    current = FakeOpenbisObject("MOLECULE")
    session = FakeSession({"MOLECULE": [previous, current]})
    source = structures.new()
    structures.link_molecule(source, previous)
    output = structures.preprocess({"NODE": source})
    structures.link_molecule(output, current)

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == (
        current,
    )


@pytest.mark.parametrize("label", ["NODE", "structure", "arbitrary_name"])
def test_preprocessing_input_names_do_not_matter(aiida_utils, structures, label):
    molecule = FakeOpenbisObject("MOLECULE")
    session = FakeSession({"MOLECULE": [molecule]})
    source = structures.new()
    structures.link_molecule(source, molecule)
    # Legacy spin helpers also have generic Data inputs: these are not structures.
    output = structures.preprocess({label: source, "U": aiida_utils.orm.Data().store()})
    before = (source.base.extras.all, output.base.extras.all)

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == (
        molecule,
    )
    assert (source.base.extras.all, output.base.extras.all) == before


def test_preprocessing_chain_recovers_existing_model_link(aiida_utils, structures):
    molecule = FakeOpenbisObject("MOLECULE")
    source = structures.new()
    model = FakeOpenbisObject("ATOMISTIC_MODEL", {"wfms_uuid": source.uuid})
    model.parents = [molecule]
    session = FakeSession({"MOLECULE": [molecule], "ATOMISTIC_MODEL": [model]})
    prepared = structures.preprocess({"NODE": source})
    output = structures.preprocess({"input_geometry": prepared})

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == (
        molecule,
    )


@pytest.mark.parametrize("preprocessed", [False, True])
def test_missing_molecule_metadata_is_normal(aiida_utils, structures, preprocessed):
    structure = structures.new()
    if preprocessed:
        structure = structures.preprocess({"NODE": structure})
    assert (
        aiida_utils.openbis_molecules_for_input_structure(FakeSession(), structure)
        == ()
    )


def test_ambiguous_structure_inputs_are_not_combined(aiida_utils, structures):
    molecule = FakeOpenbisObject("MOLECULE")
    session = FakeSession({"MOLECULE": [molecule]})
    first, second = structures.new(), structures.new()
    structures.link_molecule(first, molecule)
    output = structures.preprocess({"first": first, "second": second})

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == ()


def test_repeated_links_to_same_structure_are_unambiguous(aiida_utils, structures):
    molecule = FakeOpenbisObject("MOLECULE")
    session = FakeSession({"MOLECULE": [molecule]})
    source = structures.new()
    structures.link_molecule(source, molecule)
    output = structures.preprocess({"first": source, "second": source})

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == (
        molecule,
    )


def test_preprocessing_without_structure_inputs_stops(aiida_utils, structures):
    output = structures.preprocess({"parameters": aiida_utils.orm.Data().store()})
    assert (
        aiida_utils.openbis_molecules_for_input_structure(FakeSession(), output) == ()
    )


@pytest.mark.parametrize("boundary", ["calcjob", "called_calcfunction"])
def test_lookup_stops_at_calculation_boundaries(aiida_utils, structures, boundary):
    molecule = FakeOpenbisObject("MOLECULE")
    session = FakeSession({"MOLECULE": [molecule]})
    source = structures.new()
    structures.link_molecule(source, molecule)
    if boundary == "calcjob":
        output = structures.preprocess(
            {"structure": source}, creator_class=aiida_utils.orm.CalcJobNode
        )
    else:
        output = structures.preprocess(
            {"NODE": source}, caller=aiida_utils.orm.WorkChainNode().store()
        )

    assert aiida_utils.openbis_molecules_for_input_structure(session, output) == ()


def test_lookup_errors_are_not_hidden(monkeypatch, aiida_utils, structures):
    def unavailable(*_args):
        raise ConnectionError("Molecule lookup unavailable")

    monkeypatch.setattr(aiida_utils, "openbis_molecules_for_structure", unavailable)
    with pytest.raises(ConnectionError, match="Molecule lookup unavailable"):
        aiida_utils.openbis_molecules_for_input_structure(
            FakeSession(), structures.new()
        )


def test_widget_checks_actual_workflow_input(monkeypatch, simulations_widgets):
    structure = object()
    session = object()
    inspected = []

    def lookup(actual_session, actual_structure):
        inspected.append((actual_session, actual_structure))
        return ()

    monkeypatch.setattr(
        simulations_widgets.aiida_utils, "openbis_molecules_for_input_structure", lookup
    )
    widget = SimpleNamespace(
        openbis_session=session,
        molecules_accordion=simulations_widgets.ipw.Accordion(),
    )
    workchain = SimpleNamespace(inputs=SimpleNamespace(structure=structure))
    simulations_widgets.SimulationDetailsWidget._populate_inferred_molecules(
        widget, workchain
    )
    assert inspected == [(session, structure)]
    assert widget.molecules_accordion.children == ()
