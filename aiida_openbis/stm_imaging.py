"""Stored CP2K STM maps as microscopy data, with server-side retry identity.

Only UUIDs and plain data leave a load operation. Preparing a review is read-only;
publication is called by the existing, explicitly confirmed simulation exporter.
"""

from collections import defaultdict
import copy
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from .nanonis import (
    archive_grid,
    canonical_json,
    cell_rectangle,
    normalize_image_area,
    rectangular_raster,
    map_quantity,
    original_map_npz,
    selection_key,
    write_dat,
    write_sxm,
)

IDENTITY_FIELD = "aiidalab_simulated_stm"


def _native_geometry(stm_calculation_uuid):
    """Use the native SCF producer's cell/PBC, not a source node's UI flags."""
    from aiida import orm

    stm = orm.load_node(stm_calculation_uuid)
    folder = getattr(stm.inputs, "parent_calc_folder", None)
    native = folder.creator if isinstance(folder, orm.RemoteData) else None
    if native is None or native.process_label != "Cp2kCalculation":
        raise ValueError(
            "The stored STM needs its native CP2K parent to verify the simulation cell/PBC."
        )
    params = native.inputs.parameters.get_dict()
    force_eval = params.get("FORCE_EVAL", {})
    if isinstance(force_eval, list):
        if len(force_eval) != 1:
            raise ValueError(
                "The STM parent contains ambiguous FORCE_EVAL cell definitions."
            )
        force_eval = force_eval[0]
    periodic = str(
        force_eval.get("SUBSYS", {}).get("CELL", {}).get("PERIODIC", "")
    ).upper()
    if periodic not in {"NONE", "X", "Y", "Z", "XY", "XZ", "YZ", "XYZ"}:
        raise ValueError(
            "The native CP2K CELL.PERIODIC setting is unavailable or invalid."
        )
    structure = native.inputs.structure
    cell = np.asarray(structure.cell, dtype=float)
    if not np.allclose(cell[:2, 2], 0, atol=1e-8):
        raise ValueError(
            "The simulation's periodic A/B directions are not in the STM XY plane."
        )
    vectors = cell[:2, :2]
    default_area = cell_rectangle(vectors)
    return {
        "native_cp2k_uuid": str(native.uuid),
        "native_structure_uuid": str(structure.uuid),
        "cell_vectors_angstrom": cell.tolist(),
        "in_plane_vectors_angstrom": vectors.tolist(),
        "periodic_setting": periodic,
        "periodic_axes": [axis in periodic for axis in "XY"],
        "poisson_periodic_setting": force_eval.get("DFT", {})
        .get("POISSON", {})
        .get("PERIODIC"),
        "default_image_area": default_area,
    }


def describe(source_uuid):
    """Plain read-only geometry for the image-area controls; no server call."""
    archive = load_archive(str(source_uuid))
    return {
        "source_uuid": archive["source_uuid"],
        "structure_uuid": archive["structure_uuid"],
        **archive["simulation"],
    }


def load_archive(source_uuid):
    """Read the durable retrieved archive, including packed AiiDA repositories."""
    from aiida import orm

    root = orm.load_node(source_uuid)
    if root.process_label != "Cp2kStmWorkChain" or not root.is_finished_ok:
        raise ValueError("Select a successfully completed CP2K STM/STS workflow.")
    candidates = {}
    for process in [root, *root.called_descendants]:
        retrieved = getattr(process.outputs, "retrieved", None)
        if (
            retrieved is not None
            and "stm.npz" in retrieved.base.repository.list_object_names()
        ):
            candidates[str(retrieved.uuid)] = (retrieved, str(process.uuid))
    if len(candidates) != 1:
        raise ValueError(
            "The workflow must contain exactly one stored stm.npz archive."
        )
    retrieved_uuid, (retrieved, owner_uuid) = next(iter(candidates.items()))
    with retrieved.base.repository.open("stm.npz", mode="rb") as handle:
        raw = handle.read()
    # The workflow's own NPZ contains the established object-array metadata.
    # Do not use this loader for arbitrary uploaded files.
    with np.load(io.BytesIO(raw), allow_pickle=True) as archive:
        general = archive["stm_general_info"].item()
        series = [dict(item) for item in archive["stm_series_info"]]
        data = np.array(archive["stm_series_data"], copy=True)
    energies = np.asarray(general["energies"], dtype=float)
    if (
        data.ndim != 4
        or data.shape[:2] != (len(series), len(energies))
        or not np.isfinite(energies).all()
    ):
        raise ValueError("The stored STM series, energies and maps are inconsistent.")
    return {
        "source_uuid": str(root.uuid),
        "retrieved_uuid": retrieved_uuid,
        "archive_owner_uuid": owner_uuid,
        "structure_uuid": str(root.inputs.structure.uuid),
        "archive_sha256": hashlib.sha256(raw).hexdigest(),
        "simulation": _native_geometry(owner_uuid),
        "general": general,
        "series": series,
        "data": data,
    }


def review(source_uuid, selections, *, image_area=None, sampling=None):
    """Freeze only the source/selection identity; no server connection or writes."""
    archive = load_archive(str(source_uuid))
    simulation = archive["simulation"]
    area = normalize_image_area(
        simulation["default_image_area"] if image_area is None else image_area
    )
    chosen = set()
    for selection in selections:
        s, e = selection["series_index"], selection["energy_index"]
        if (
            type(s) is not int
            or type(e) is not int
            or not (0 <= s < len(archive["series"]))
            or not (0 <= e < len(archive["general"]["energies"]))
        ):
            raise ValueError("Select valid stored series and energy indices.")
        chosen.add((s, e))
    if not chosen and not sampling:
        raise ValueError(
            "Select at least one stored map, STS point spectrum or STM line profile."
        )
    entries = []
    for s, e in sorted(chosen):
        values = archive["data"][s, e]
        origin, steps = archive_grid(archive["general"], values.shape)
        raster = rectangular_raster(
            values,
            origin,
            steps,
            area,
            cell_vectors_angstrom=simulation["in_plane_vectors_angstrom"],
            periodic_axes=simulation["periodic_axes"],
        )
        series = archive["series"][s]
        entries.append(
            {
                "series_index": s,
                "energy_index": e,
                "energy_ev": float(archive["general"]["energies"][e]),
                "series": json.loads(canonical_json(series)),
                "quantity": map_quantity(series),
                "original_shape": list(values.shape),
                "display_shape": list(raster.values.shape),
                "interpolation": raster.interpolation,
            }
        )
    from .stm_sampling import derive_sampling, describe_groups

    groups = derive_sampling(archive, sampling or [])
    result = {
        key: archive[key]
        for key in (
            "source_uuid",
            "archive_sha256",
            "retrieved_uuid",
            "archive_owner_uuid",
            "structure_uuid",
        )
    }
    result.update(
        entries=entries,
        sampling=[group["request"] for group in groups],
        curve_groups=describe_groups(groups),
        image_area=area,
        simulation=simulation,
    )
    result["review_key"] = selection_key(
        result["source_uuid"], result["archive_sha256"], result
    )
    return result


def prepare_files(reviewed, directory):
    """Re-read immutable inputs and build every file before the first server write."""
    selections = [
        {k: item[k] for k in ("series_index", "energy_index")}
        for item in reviewed["entries"]
    ]
    current = review(
        reviewed["source_uuid"],
        selections,
        sampling=reviewed["sampling"],
        image_area=reviewed["image_area"],
    )
    if canonical_json(current) != canonical_json(reviewed):
        raise ValueError(
            "The STM source or review changed. Prepare a new export review."
        )
    archive = load_archive(reviewed["source_uuid"])
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    packages = []
    identity = {
        key: reviewed[key]
        for key in (
            "source_uuid",
            "archive_sha256",
            "retrieved_uuid",
            "archive_owner_uuid",
            "structure_uuid",
        )
    }
    for item in reviewed["entries"]:
        s, e = item["series_index"], item["energy_index"]
        spec = {
            "series_index": s,
            "energy_index": e,
            "kind": "map",
            "image_area": reviewed["image_area"],
            "periodic_axes": reviewed["simulation"]["periodic_axes"],
            "sampling_revision": 1,
        }
        key = selection_key(identity["source_uuid"], identity["archive_sha256"], spec)
        folder = directory / key
        folder.mkdir()
        values = archive["data"][s, e]
        origin, steps = archive_grid(archive["general"], values.shape)
        raster = rectangular_raster(
            values,
            origin,
            steps,
            reviewed["image_area"],
            cell_vectors_angstrom=reviewed["simulation"]["in_plane_vectors_angstrom"],
            periodic_axes=reviewed["simulation"]["periodic_axes"],
        )
        metadata = {
            **identity,
            "export_key": key,
            "selection": spec,
            "spin": archive["general"].get("spin"),
            "simulation": reviewed["simulation"],
        }
        path = folder / "simulation.sxm"
        metadata = write_sxm(path, raster, item["series"], item["energy_ev"], metadata)
        raw_path = folder / "original-grid.npz"
        raw_path.write_bytes(
            original_map_npz(
                values, origin, steps, metadata, general=archive["general"]
            )
        )
        sidecar = folder / "simulation.json"
        sidecar.write_text(canonical_json(metadata), encoding="utf-8")
        packages.append(
            {
                "key": key,
                "kind": "map",
                "path": path,
                "files": [raw_path, sidecar],
                "metadata": metadata,
            }
        )
    packages.extend(_curve_packages(archive, reviewed["sampling"], directory, identity))
    for package in packages:
        # Parse each complete file and validate its adaptor request before writes.
        package["preview_controls"] = preview_controls(package)
        package["metadata"]["file_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*package.get("curve_paths", [package["path"]]), *package["files"]]
        }
    return packages


def _curve_packages(archive, requests, directory, identity):
    from .stm_sampling import derive_sampling

    packages = []
    for group in derive_sampling(archive, requests):
        spec = {"sampling": group["request"], "sampling_revision": 1}
        key = selection_key(identity["source_uuid"], identity["archive_sha256"], spec)
        folder = Path(directory) / key
        folder.mkdir(parents=True)
        metadata = {
            **identity,
            "export_key": key,
            "selection": spec,
            "series": group["series"],
            "simulation": archive["simulation"],
            "interpolation": group["interpolation"],
            "markers": [
                {
                    k: v
                    for k, v in curve.items()
                    if k not in {"x", "y", "sample_positions_angstrom"}
                }
                for curve in group["curves"]
            ],
        }
        if group["request"]["kind"] == "stm_lines":
            bias = group["request"]["bias_voltage_v"]
            metadata.update(bias_voltage_v=bias, energy_relative_to_fermi_ev=bias)
        request = group["request"]
        reference = request.get("reference_energy_index", request.get("energy_index"))
        if reference is not None:
            metadata["reference_map"] = {
                "series_index": request["series_index"],
                "energy_index": reference,
            }
        paths = []
        for curve in group["curves"]:
            path = folder / (curve["id"] + ".dat")
            write_dat(
                path,
                curve["x"],
                curve["y"],
                {
                    **metadata,
                    "marker": {k: v for k, v in curve.items() if k not in {"x", "y"}},
                },
                signal_name=group["quantity"]["quantity"],
                signal_unit=group["quantity"]["native_unit"],
                x_name=group["x_name"],
                x_unit=group["x_unit"],
                x_quantity=group["x_quantity"],
            )
            paths.append(path)
        metadata.update(
            x_quantity=group["x_quantity"],
            x_unit=group["x_unit"],
            y_quantity=group["quantity"]["quantity"],
            y_unit=group["quantity"]["native_unit"],
        )
        sidecar = folder / "sampling.json"
        sidecar.write_text(canonical_json(metadata), encoding="utf-8")
        packages.append(
            {
                "key": key,
                "kind": "curve",
                "path": paths[0],
                "curve_paths": paths,
                "files": [sidecar],
                "metadata": metadata,
            }
        )
    return packages


def sampling_zip(source_uuid, requests):
    """Read-only browser download of DATs plus exact point/line provenance."""
    import tempfile
    import zipfile

    reviewed = review(source_uuid, [], sampling=requests)
    with tempfile.TemporaryDirectory(prefix="stm-sampling-") as directory:
        packages = prepare_files(reviewed, directory)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for package in packages:
                for path in [*package["curve_paths"], *package["files"]]:
                    bundle.write(path, str(path.relative_to(directory)))
        return stream.getvalue()


def _existing(imaging, session, sample):
    """Read identity from openBIS, even after AiiDA extras reset/import."""
    result = defaultdict(list)
    for dataset in session.get_datasets(type="IMAGING_DATA", sample=sample):
        config = imaging.get_property_config(str(dataset.permId))
        metadata = config.metadata or {}
        identity = metadata.get(IDENTITY_FIELD)
        if identity:
            if not isinstance(identity, dict) or not identity.get("export_key"):
                raise ValueError(
                    "An existing simulation imaging dataset has unreadable identity."
                )
            result[identity["export_key"]].append((str(dataset.permId), config))
    return result


def _curve_identity(request, marker):
    """Identify a sampled trace by its physical inputs, not its display label."""
    prefix = (request["kind"], request["series_index"])
    if request["kind"] == "sts_points":
        return (*prefix, tuple(marker["position_angstrom"]))
    return (
        *prefix,
        request["energy_index"],
        tuple(marker["start_angstrom"]),
        tuple(marker["end_angstrom"]),
    )


def review_dat_additions(session, sample, reviewed):
    """Plan new DAT groups and pending previews from the SPM dataset inventory."""
    from pybis import ImagingControl

    existing = _existing(ImagingControl(session, service_type="AS"), session, sample)
    saved = set()
    pending = []
    for matches in existing.values():
        if len(matches) != 1:
            raise ValueError(
                "Multiple microscopy datasets have the same export identity."
            )
        _, config = matches[0]
        identity = config.metadata[IDENTITY_FIELD]
        if (
            identity.get("source_uuid") != reviewed["source_uuid"]
            or identity.get("archive_sha256") != reviewed["archive_sha256"]
        ):
            continue
        request = identity.get("selection", {}).get("sampling")
        if request is None:
            continue
        field = "points" if request["kind"] == "sts_points" else "lines"
        keys = {_curve_identity(request, marker) for marker in request[field]}
        saved.update(keys)
        if not identity.get("preview_ready"):
            pending.append((keys, request))

    additions = []
    requested = set()
    for request in reviewed["sampling"]:
        field = "points" if request["kind"] == "sts_points" else "lines"
        markers = []
        for marker in request[field]:
            key = _curve_identity(request, marker)
            if key not in saved and key not in requested:
                markers.append(marker)
            requested.add(key)
        if markers:
            additions.append({**request, field: markers})
    return additions, [request for keys, request in pending if keys & requested]


def preview_controls(package):
    """Supply the full adaptor request, including the actual native channel."""
    from nanonis_importer import nanonis_importer as importer

    image = importer.spm(str(package["path"]))
    if package["kind"] == "map":
        channel = image.default_channels[0]
        return {
            "Channel": channel,
            "X-axis": ["0", str(image.get_param("width")[0])],
            "Y-axis": ["0", str(image.get_param("height")[0])],
            "Color-scale": importer.get_color_scale_range(image, channel)[:2],
            "Colormap": "gray",
            "Scaling": "linear",
            # Old server bundles call unknown channel units N/A. The controls
            # and metadata retain the actual unit; do not render a false label.
            "include labels": "False",
            "include parameters": "False",
        }
    images = [
        importer.spm(str(path))
        for path in package.get("curve_paths", [package["path"]])
    ]
    x, y = image.default_channels
    x_values = np.concatenate([img.get_channel(x)[0] for img in images])
    y_values = np.concatenate([img.get_channel(y)[0] for img in images])
    return {
        "Channel X": x,
        "Channel Y": y,
        "X-axis": [str(np.nanmin(x_values)), str(np.nanmax(x_values))],
        "Y-axis": [str(np.nanmin(y_values)), str(np.nanmax(y_values))],
        "Grouping": [
            path.name for path in package.get("curve_paths", [package["path"]])
        ],
        "Colormap": "rainbow",
        "Scaling": "lin-lin",
        "Print legend": "True",
    }


def publish(session, experiment, sample, packages):
    """Reuse server identities and complete missing previews on explicit retry.

    Every file has already been prepared before this call. A failed/ambiguous
    inventory is not permission to create another dataset. Concurrent exports
    from independent clients still require server-side uniqueness support.
    """
    from pybis import ImagingControl
    from nanonis_importer import nanonis_importer as importer

    imaging = ImagingControl(session, service_type="AS")
    existing = _existing(imaging, session, sample)
    if any(len(existing[item["key"]]) > 1 for item in packages):
        raise ValueError(
            "Multiple microscopy datasets match this source and selection. Review the existing records."
        )
    completed = []
    for item in packages:
        matches = existing[item["key"]]
        created = not matches
        if created:
            metadata = item["metadata"]
            if item["kind"] == "map":
                # DSS stores a single SXM in original/, which the Nanonis
                # renderer scans directly. The linked AiiDA archive retains
                # the native grid and the Imaging metadata retains conversion.
                name = item["path"].name
                metadata = {
                    **metadata,
                    "file_sha256": {name: metadata["file_sha256"][name]},
                }
            kwargs = dict(
                session=session,
                experiment=experiment,
                sample=sample,
                dataset_metadata={IDENTITY_FIELD: metadata},
            )
            if item["kind"] == "map":
                dataset = importer.create_sxm_dataset(
                    file_path=str(item["path"]), **kwargs
                )
            else:
                dataset = importer.create_dat_dataset(
                    folder_path=str(item["path"].parent),
                    auxiliary_files=item["files"],
                    **kwargs,
                )
            perm_id = str(dataset.permId)
            config = imaging.get_property_config(perm_id)
            existing[item["key"]].append((perm_id, config))
        else:
            perm_id, config = matches[0]
        metadata = copy.deepcopy(config.metadata or {})
        state = metadata[IDENTITY_FIELD]
        # Save preview readiness only after the server acknowledged its update.
        if not state.get("preview_ready"):
            controls = item["preview_controls"]
            preview = importer.create_preview(
                session, perm_id, controls, tags=["SIMULATION"]
            )
            importer.update_image_with_preview(session, perm_id, 0, preview)
            config = imaging.get_property_config(perm_id)
            metadata = copy.deepcopy(config.metadata or {})
            metadata[IDENTITY_FIELD]["preview_ready"] = True
            config.metadata = metadata
            imaging.update_property_config(perm_id, config)
        completed.append(
            {
                "perm_id": perm_id,
                "export_key": item["key"],
                "created": created,
                "preview_ready": True,
            }
        )
    return completed
