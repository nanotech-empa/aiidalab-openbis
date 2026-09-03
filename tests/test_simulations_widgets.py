import importlib
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def simulations_widgets(monkeypatch):
    from src import utils

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, None))
    monkeypatch.setattr(
        utils,
        "get_interface_config_info",
        lambda: {
            "object_types": {},
            "object_types_codes": {},
            "slabs_concepts_types": {},
            "instruments_types": {},
        },
    )
    sys.modules.pop("src.aiida_utils", None)
    sys.modules.pop("src.widgets", None)
    sys.modules.pop("src.simulations_widgets", None)
    return importlib.import_module("src.simulations_widgets")


def test_resolution_options_include_existing_and_create(simulations_widgets):
    options = simulations_widgets.ExportSimulationsWidget._resolution_options(
        (("perm-2", "Zulu"), ("perm-1", "Alpha")),
        "Create new",
    )

    assert options == [
        ("Select an existing object...", ""),
        ("Alpha (perm-1)", "perm-1"),
        ("Zulu (perm-2)", "perm-2"),
        ("Create new", simulations_widgets._CREATE_NEW),
    ]


def test_existing_reference_selection_is_stored_by_aiida_uuid(
    simulations_widgets,
):
    widget = SimpleNamespace(
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Code",
            "aiida_uuid": "code-uuid",
            "selector": SimpleNamespace(value="code-permid"),
        },
        provenance_resolution_box=SimpleNamespace(children=["visible"]),
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is True
    assert widget._provenance_overrides["Code"] == {"code-uuid": "code-permid"}
    assert widget._pending_reference_resolution is None
    assert widget.provenance_resolution_box.children == []


def test_existing_executable_selection_is_stored_by_code_uuid(
    simulations_widgets,
):
    widget = SimpleNamespace(
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _executable_selection_widgets={
            "code-uuid": SimpleNamespace(value="executable-permid"),
            "create-code-uuid": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
        },
    )

    simulations_widgets.ExportSimulationsWidget._apply_executable_selections(widget)

    assert widget._provenance_overrides["Executable"] == {
        "code-uuid": "executable-permid"
    }


def test_create_new_code_stores_override(monkeypatch, simulations_widgets):
    created = []

    def create_openbis_object(_session, type, props, collection):
        created.append((type, props, collection))
        return SimpleNamespace(permId="new-code-permid")

    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_object",
        create_openbis_object,
    )
    widget = SimpleNamespace(
        openbis_session=object(),
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Code",
            "aiida_uuid": "code-uuid",
            "selector": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
            "name": SimpleNamespace(value="cubehandler"),
            "description": SimpleNamespace(value="Cube handler utility"),
            "url": SimpleNamespace(value="https://example.org/cubehandler"),
            "collection": SimpleNamespace(value="/CODE/COLLECTION"),
            "location": None,
            "status": SimpleNamespace(value=""),
        },
        provenance_resolution_box=SimpleNamespace(children=["visible"]),
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is True
    assert created == [
        (
            "CODE",
            {
                "name": "cubehandler",
                "description": "Cube handler utility",
                "url": "https://example.org/cubehandler",
            },
            "/CODE/COLLECTION",
        )
    ]
    assert widget._provenance_overrides["Code"] == {"code-uuid": "new-code-permid"}


def test_create_new_computer_requires_location(monkeypatch, simulations_widgets):
    creations = []
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_object",
        lambda *_args, **kwargs: creations.append(kwargs),
    )
    status = SimpleNamespace(value="")
    widget = SimpleNamespace(
        openbis_session=object(),
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Computer",
            "aiida_uuid": "computer-uuid",
            "selector": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
            "name": SimpleNamespace(value="new-computer"),
            "description": SimpleNamespace(value="A new computer"),
            "url": None,
            "collection": None,
            "location": SimpleNamespace(value=""),
            "status": status,
        },
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is False
    assert "location is required" in status.value
    assert creations == []
