"""Cross-app import and UUID prefill, with no openBIS or AiiDA writes."""

import importlib
import sys
from types import SimpleNamespace

import ipywidgets as ipw


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


def test_bridge_prefills_uuid_without_exporting(monkeypatch):
    from aiida_openbis.export import make_export_widget

    simulations_widgets = importlib.import_module("src.simulations_widgets")
    utils = importlib.import_module("src.utils")

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (object(), None))

    class Form(ipw.VBox):
        def __init__(self, session, *, source_uuid=None):
            super().__init__()
            self.source_uuid = source_uuid

    monkeypatch.setattr(simulations_widgets, "ExportSimulationsWidget", Form)
    widget = make_export_widget("source-uuid")
    assert widget.source_uuid == "source-uuid"
    widget.close()


def test_bridge_keeps_another_apps_src_package_intact(monkeypatch):
    from aiida_openbis import export

    foreign = SimpleNamespace(
        __spec__=SimpleNamespace(submodule_search_locations=["/different/app/src"])
    )
    monkeypatch.setitem(sys.modules, "src", foreign)
    module = export._app_module("orca_export")
    assert module.__name__ == "_aiidalab_openbis_app.orca_export"
    assert sys.modules["src"] is foreign
    assert module.__file__.endswith("/src/orca_export.py")


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
    assert module.__name__ == "_aiidalab_openbis_app.orca_export"


def test_full_review_import_is_isolated_from_another_apps_src(tmp_path):
    import os
    import subprocess
    import textwrap
    from pathlib import Path
    from aiida_openbis import export

    code = textwrap.dedent("""
        import importlib.machinery
        import sys
        import types
        from aiida_openbis import export
        foreign = types.ModuleType('src')
        foreign.__spec__ = importlib.machinery.ModuleSpec('src', loader=None, is_package=True)
        foreign.__spec__.submodule_search_locations = ['/another/app/src']
        sys.modules['src'] = foreign
        utils = export._app_module('utils')
        utils.connect_openbis_aiida = lambda: (None, None)
        utils.get_interface_config_info = lambda: {
            'object_types': {}, 'object_types_codes': {},
            'slabs_concepts_types': {}, 'instruments_types': {},
        }
        review = export._app_module('simulations_widgets')
        assert review.widgets.utils is utils
        assert review.widgets.molecule_creation.utils is utils
        assert review.widgets.chemical_search.__package__ == '_aiidalab_openbis_app'
        assert sys.modules['src'] is foreign
    """)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(export.__file__).resolve().parents[1]),
        },
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
