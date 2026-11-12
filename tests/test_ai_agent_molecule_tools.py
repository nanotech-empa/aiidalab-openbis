import importlib
import sys
import types

import pytest


class _Properties:
    def __init__(self, values):
        self._values = values

    def all(self):
        return dict(self._values)


class _Object:
    def __init__(self, permid, object_type, properties=None, parents=None):
        self.permId = permid
        self.type = types.SimpleNamespace(code=object_type)
        self.props = _Properties(properties or {})
        self.parents = list(parents or [])


@pytest.fixture
def chatbot_tools(monkeypatch):
    backend = types.ModuleType("ai_agent.openbis_utils")
    backend.objects = {}
    backend.get_openbis_object = backend.objects.get
    backend.get_openbis_objects = lambda **_kwargs: []
    monkeypatch.setitem(sys.modules, "ai_agent.openbis_utils", backend)
    sys.modules.pop("ai_agent.tools", None)
    module = importlib.import_module("ai_agent.tools")
    yield module, backend
    sys.modules.pop("ai_agent.tools", None)


def test_product_and_reaction_product_match_molecule_parent_relations(chatbot_tools):
    tools, backend = chatbot_tools
    component = _Object(
        "component",
        "MOLECULE",
        {"name": "DBBA", "smiles": "C=C", "sum_formula": "C12H8"},
    )
    unrelated = _Object("sample", "SAMPLE", {"name": "sample"})
    product = _Object(
        "product",
        "MOLECULE",
        {"name": "7AGNR", "sum_formula": "C42H18"},
        parents=["component", "sample"],
    )
    reaction_product = _Object(
        "reaction-product",
        "REACTION_PRODUCT",
        {"name": "grown ribbon"},
        parents=["product", "sample"],
    )
    backend.objects.update(
        {
            item.permId: item
            for item in (component, unrelated, product, reaction_product)
        }
    )

    query = tools.ReacProdConceptArgs(
        name="7AGNR",
        sum_formula="C42H18",
        molecules=[tools.MoleculeArgs(smiles="C=C")],
    )

    assert tools.molecule_parents(product) == [component]
    assert tools.reacprod_concept_found(product, query)
    assert tools.reacprod_found(
        reaction_product,
        tools.ReacProdArgs(name="grown ribbon", reacprod_concept=query),
    )


def test_substance_matcher_still_resolves_molecule_property_ids(chatbot_tools):
    tools, backend = chatbot_tools
    molecule = _Object("molecule", "MOLECULE", {"smiles": "CCO"})
    backend.objects[molecule.permId] = molecule
    substance = _Object(
        "substance",
        "SUBSTANCE",
        {"empa_number": 42, "batch": "a", "molecules": [molecule.permId]},
    )

    assert tools.substance_found(
        substance,
        tools.SubstanceArgs(
            empa_number=42,
            batch="a",
            molecules=[tools.MoleculeArgs(smiles="CCO")],
        ),
    )
