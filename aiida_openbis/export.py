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


def make_export_widget(source_uuid, *, microscopy_review=None):
    """Open the common interface with a process UUID; never click Export."""
    simulations_widgets, utils = (
        _app_module("simulations_widgets"),
        _app_module("utils"),
    )
    session, _ = utils.connect_openbis_aiida()
    if session is None:
        raise ValueError("Configure your openBIS connection in the ELN app first.")
    kwargs = {"source_uuid": str(source_uuid)}
    if microscopy_review is not None:
        kwargs["microscopy_review"] = microscopy_review
    return simulations_widgets.ExportSimulationsWidget(session, **kwargs)


def plan_export(source_uuid):
    """Inspect stored ORCA or model data without connecting to openBIS."""
    from aiida import orm

    model = _app_module("model_export")
    native = _app_module("pythtb_export")
    node = orm.load_node(source_uuid)
    if native.supported(node):
        return _app_module("orca_export").inventory(source_uuid, adapter=native)
    return _app_module("orca_export").inventory(
        source_uuid, adapter=model if model.supported(node) else None
    )


def available_results(source_uuid):
    """List completed related calculations without an openBIS connection."""
    from aiida import orm

    model = _app_module("model_export")
    native = _app_module("pythtb_export")
    node = orm.load_node(source_uuid)
    if native.supported(node):
        return native.related_results(source_uuid)
    if model.supported(node):
        return [
            {
                "uuid": str(item.uuid),
                "label": item.label or item.process_label,
                "process_label": item.process_label,
                "title": "Model Hamiltonian results",
                "created": item.ctime.isoformat(),
            }
            for item in [node, *node.called_descendants]
            if model.supported(item) and item.is_finished_ok
        ]
    return _app_module("orca_export").related_results(source_uuid)


def review_stm_imaging(source_uuid, selections, *, image_area=None, sampling=None):
    """Inspect selected stored maps without connecting to openBIS."""
    from .stm_imaging import review

    return review(source_uuid, selections, image_area=image_area, sampling=sampling)


def describe_stm_imaging(source_uuid):
    """Read the native simulation cell/PBC for the viewer and chat area controls."""
    from .stm_imaging import describe

    return describe(source_uuid)


def download_stm_sampling(source_uuid, sampling):
    """Return DAT/metadata ZIP bytes without publishing or altering AiiDA data."""
    from .stm_imaging import sampling_zip

    return sampling_zip(source_uuid, sampling)
