"""Cross-app import and UUID prefill, with no openBIS or AiiDA writes."""

import importlib
import sys
from types import SimpleNamespace

import ipywidgets as ipw
import pytest


def test_exporter_imports_from_another_notebook_directory(monkeypatch, tmp_path):
    from src import utils

    monkeypatch.chdir(tmp_path)
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
    for name in ("src.aiida_utils", "src.widgets", "src.simulations_widgets"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("src.simulations_widgets")
    assert "Energy Calculation" in module.SIMULATION_EXPORT_TYPES


def test_bridge_prefills_uuid_without_checking_or_exporting(monkeypatch):
    from aiida import orm
    from aiida_openbis.export import make_export_widget
    from src import simulations_widgets, utils

    monkeypatch.setattr(orm, "load_node", lambda uuid: SimpleNamespace(pk=42))
    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (object(), None))

    class Form(ipw.VBox):
        def __init__(self, session):
            super().__init__()
            self.simulation_details_vbox = SimpleNamespace(
                simulation_pk_input=ipw.IntText()
            )

    monkeypatch.setattr(simulations_widgets, "ExportSimulationsWidget", Form)
    widget = make_export_widget("source-uuid")
    assert widget.simulation_details_vbox.simulation_pk_input.value == 42
    widget.close()


def test_bridge_refuses_a_different_src_package(monkeypatch):
    from aiida_openbis import export

    monkeypatch.setattr(
        export.importlib.util,
        "find_spec",
        lambda _: SimpleNamespace(submodule_search_locations=["/different/app/src"]),
    )
    with pytest.raises(RuntimeError, match="shadowed"):
        export.plan_export("source-uuid")


def test_bridge_can_bootstrap_its_checkout_without_package_install(monkeypatch):
    from aiida_openbis import export

    monkeypatch.delitem(sys.modules, "src")
    original = export.importlib.util.find_spec
    monkeypatch.setattr(
        export.importlib.util,
        "find_spec",
        lambda name: None if name == "src" else original(name),
    )
    module = export._app_module("orca_export")
    assert module.__name__ == "src.orca_export"
