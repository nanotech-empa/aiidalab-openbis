"""Small public entry point for applications using the shared export GUI."""

import importlib
import importlib.util
import sys
from pathlib import Path


def _app_module(name):
    expected = Path(__file__).resolve().parents[1] / "src"
    try:
        spec = importlib.util.find_spec("src")
    except (ImportError, ValueError):
        spec = None
    locations = () if spec is None else spec.submodule_search_locations or ()
    if expected in {Path(path).resolve() for path in locations}:
        return importlib.import_module("src." + name)

    # Other AiiDAlab apps also use a top-level `src` package. Keep theirs intact
    # and load the real shared exporter under a distinct, package-relative name.
    namespace = "_aiidalab_openbis_app"
    package = sys.modules.get(namespace)
    if package is None:
        spec = importlib.util.spec_from_file_location(
            namespace,
            expected / "__init__.py",
            submodule_search_locations=[str(expected)],
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = package
        try:
            spec.loader.exec_module(package)
        except Exception:
            sys.modules.pop(namespace, None)
            raise
    if expected not in {Path(path).resolve() for path in package.__path__}:
        raise RuntimeError("A different openBIS exporter checkout is already loaded.")
    return importlib.import_module(namespace + "." + name)


def make_export_widget(source_uuid):
    """Open the common interface with a process UUID; never click Export."""
    simulations_widgets, utils = (
        _app_module("simulations_widgets"),
        _app_module("utils"),
    )
    session, _ = utils.connect_openbis_aiida()
    if session is None:
        raise ValueError("Configure your openBIS connection in the ELN app first.")
    return simulations_widgets.ExportSimulationsWidget(
        session, source_uuid=str(source_uuid)
    )


def plan_export(source_uuid):
    """Inspect local ORCA data without connecting to openBIS."""
    return _app_module("orca_export").inventory(source_uuid)


def available_results(source_uuid):
    """List completed related calculations without an openBIS connection."""
    return _app_module("orca_export").related_results(source_uuid)
