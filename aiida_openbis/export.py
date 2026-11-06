"""Small public entry point for applications using the shared export GUI."""

import importlib
import importlib.util
import sys
from pathlib import Path


def _app_module(name):
    expected = Path(__file__).resolve().parents[1] / "src"
    spec = importlib.util.find_spec("src")
    if spec is None:
        # AiiDAlab can run this app directly from its checkout without installing
        # its optional legacy chatbot dependencies. Load its real source package.
        spec = importlib.util.spec_from_file_location(
            "src", expected / "__init__.py", submodule_search_locations=[str(expected)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules["src"] = package
        try:
            spec.loader.exec_module(package)
        except Exception:
            sys.modules.pop("src", None)
            raise
    locations = () if spec is None else spec.submodule_search_locations or ()
    if expected not in {Path(path).resolve() for path in locations}:
        raise RuntimeError(
            "The matching openBIS source package is unavailable or shadowed."
        )
    return importlib.import_module("src." + name)


def make_export_widget(source_uuid):
    """Open a review form for a stored process; this never clicks Export."""
    from aiida import orm

    simulations_widgets, utils = (
        _app_module("simulations_widgets"),
        _app_module("utils"),
    )
    node = orm.load_node(source_uuid)
    # Only the plain PK is carried into the shared form. It reloads on Check.
    pk = node.pk
    del node
    session, _ = utils.connect_openbis_aiida()
    if session is None:
        raise ValueError("Configure your openBIS connection in the ELN app first.")
    widget = simulations_widgets.ExportSimulationsWidget(session)
    widget.simulation_details_vbox.simulation_pk_input.value = pk
    return widget


def plan_export(source_uuid):
    """Inspect local ORCA data without connecting to openBIS."""
    return _app_module("orca_export").inventory(source_uuid)


def available_results(source_uuid):
    """List completed related calculations without an openBIS connection."""
    return _app_module("orca_export").related_results(source_uuid)
