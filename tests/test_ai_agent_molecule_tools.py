import importlib
import sys
import types

import pytest


class _Properties:
    def __init__(self, values):
        self._values = values

    def all(self):
        return dict(self._values)

    def __getitem__(self, key):
        return self._values.get(key)


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


def test_product_tools_use_product_collection_and_precursor_parents(chatbot_tools):
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
    product.children = ["simulation"]
    simulation = _Object("simulation", "GEOMETRY_OPTIMISATION", {"name": "relaxed"})
    simulation.children = ["product"]
    backend.objects.update(
        {item.permId: item for item in (component, unrelated, product, simulation)}
    )
    calls = []

    def query_objects(**query):
        calls.append(query)
        assert query["type"] == "MOLECULE"
        assert query["collection"].endswith("/PRODUCT_COLLECTION")
        assert query["attrs"] == ["parents", "children"]
        return (
            [product] if query.get("permId", product.permId) == product.permId else []
        )

    backend.get_openbis_objects = query_objects
    query = {
        "name": "7AGNR",
        "sum_formula": "C42H18",
        "precursors": [{"smiles": "C=C"}],
    }

    assert tools.molecule_parents(product) == [component]
    assert tools.get_product_molecules_by_properties.invoke({"product": query}) == [
        "Product molecule 7AGNR (product)."
    ]
    assert calls[0]["where"] == {"name": "7AGNR", "sum_formula": "C42H18"}
    assert tools.get_simulations_by_product_molecule.invoke({"product": query}) == [
        "- Geometry Optimisation: relaxed (simulation). It is child of 7AGNR (product)."
    ]
    assert (
        tools.get_product_molecules_by_properties.invoke(
            {"product": {"permId": "component"}}
        )
        == []
    )
    assert (
        tools.get_product_molecules_by_properties.invoke(
            {"product": {"precursors": [{"permId": "sample"}]}}
        )
        == []
    )


@pytest.mark.parametrize("use_parent", [False, True])
def test_substance_matcher_resolves_molecule_property_ids_and_parents(
    chatbot_tools, use_parent
):
    tools, backend = chatbot_tools
    molecule = _Object("molecule", "MOLECULE", {"smiles": "CCO"})
    backend.objects[molecule.permId] = molecule
    substance = _Object(
        "substance",
        "SUBSTANCE",
        {
            "empa_number": 777,
            "batch": "a",
            "molecules": [] if use_parent else molecule.permId,
        },
        parents=[molecule.permId] if use_parent else [],
    )

    assert tools.substance_found(
        substance,
        tools.SubstanceArgs(
            empa_number=777,
            batch="a",
            molecules=[tools.MoleculeArgs(smiles="CCO")],
        ),
    )
