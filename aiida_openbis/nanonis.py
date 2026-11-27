"""Nanonis-compatible *derived simulation* files, without instrument calibration.

Numerical inputs use the STM archive convention: data[x, y], coordinates in
angstrom. SXM stores rows[y, x] as big-endian float32 and lengths in metres.
The original data and grid are retained in a separate NPZ, not overwritten.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import map_coordinates

BOHR_ANGSTROM = 0.52917721067  # cp2k-spm-tools STM coordinate convention
FORMAT_REVISION = 1


def _json(value):
    if isinstance(value, np.ndarray):
        return _json(value.tolist())
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    return value


def canonical_json(value):
    return json.dumps(_json(value), sort_keys=True, allow_nan=False)


@dataclass(frozen=True)
class Raster:
    """A display raster with explicit sample-centre coordinates."""

    values: np.ndarray
    origin_angstrom: np.ndarray
    steps_angstrom: np.ndarray
    interpolation: dict


def archive_grid(general, shape):
    """Read immutable STM grid metadata, including historical orthogonal grids."""
    if "dv_vectors" in general:
        steps = np.asarray(general["dv_vectors"], dtype=float)
        origin = np.asarray(general.get("origin"), dtype=float)
        if steps.shape != (3, 3) or origin.shape != (3,):
            raise ValueError(
                "STM vector grid requires a three-vector origin and basis."
            )
        if not np.allclose(steps[:2, 2], 0, atol=1e-10):
            raise ValueError("The STM plane is not parallel to XY.")
        return origin[:2] * BOHR_ANGSTROM, steps[:2, :2] * BOHR_ANGSTROM
    axes = []
    for name, count in zip(("x_arr", "y_arr"), shape):
        axis = np.asarray(general.get(name), dtype=float)
        if axis.ndim != 1 or len(axis) not in (count, count + 1):
            raise ValueError("STM axes do not match the stored image shape.")
        delta = np.diff(axis)
        if (
            not len(delta)
            or not np.isfinite(axis).all()
            or not np.allclose(delta, delta[0])
        ):
            raise ValueError("STM axes must be finite and regularly sampled.")
        axes.append((axis[0], delta[0]))
    return (
        np.array([a[0] for a in axes]) * BOHR_ANGSTROM,
        np.diag([a[1] for a in axes]) * BOHR_ANGSTROM,
    )


def display_raster(data, origin_angstrom, steps_angstrom, spacing_angstrom=None):
    """Use the CubeViewer's inverse-basis, linear/NaN sampling convention.

    Axes are sample centres, not outer pixel edges. Non-Cartesian grids are
    sampled on their XY bounding rectangle, without periodic wrapping. Samples
    outside the original index parallelogram remain NaN, never false zeros.
    """
    values = np.array(data, dtype=float, copy=True)
    origin = np.array(origin_angstrom, dtype=float, copy=True)
    steps = np.array(steps_angstrom, dtype=float, copy=True)
    if values.ndim != 2 or min(values.shape) < 2:
        raise ValueError(
            "Select a two-dimensional STM map with at least two samples per axis."
        )
    if np.isinf(values).any() or not np.isfinite(values).any():
        raise ValueError(
            "The selected map contains no valid finite signal or contains infinity."
        )
    if (
        origin.shape != (2,)
        or steps.shape != (2, 2)
        or not np.isfinite(origin).all()
        or not np.isfinite(steps).all()
    ):
        raise ValueError("The map needs a finite XY origin and two grid vectors.")
    if abs(np.linalg.det(steps)) <= np.finfo(float).eps * np.linalg.norm(steps) ** 2:
        raise ValueError("The STM in-plane grid is singular.")
    if (
        spacing_angstrom is None
        and np.allclose(steps, np.diag(np.diag(steps)), atol=1e-12)
        and np.all(np.diag(steps) > 0)
    ):
        return Raster(
            values, origin, steps, {"method": "none", "outside_domain": "NaN"}
        )
    spacing = (
        float(spacing_angstrom)
        if spacing_angstrom is not None
        else float(np.min(np.linalg.norm(steps, axis=1)))
    )
    if not np.isfinite(spacing) or spacing <= 0:
        raise ValueError("Cartesian pixel spacing must be finite and positive.")
    corners = (
        origin
        + np.array(
            [
                [0, 0],
                [values.shape[0] - 1, 0],
                [values.shape[0] - 1, values.shape[1] - 1],
                [0, values.shape[1] - 1],
            ]
        )
        @ steps
    )
    minimum, maximum = corners.min(axis=0), corners.max(axis=0)
    count = np.ceil((maximum - minimum) / spacing).astype(int) + 1
    x, y = np.meshgrid(
        minimum[0] + np.arange(count[0]) * spacing,
        minimum[1] + np.arange(count[1]) * spacing,
        indexing="ij",
    )
    positions = np.stack((x, y), axis=-1)
    indices = (positions - origin) @ np.linalg.inv(steps)
    upper = np.asarray(values.shape) - 1
    inside = np.all((indices >= -1e-9) & (indices <= upper + 1e-9), axis=-1)
    indices = np.clip(indices, 0, upper)
    sampled = map_coordinates(
        values,
        np.moveaxis(indices, -1, 0),
        order=1,
        mode="constant",
        cval=np.nan,
        prefilter=False,
    )
    sampled[~inside] = np.nan
    if not np.isfinite(sampled).any():
        raise ValueError("The chosen Cartesian raster contains no valid samples.")
    return Raster(
        sampled,
        minimum,
        np.diag([spacing, spacing]),
        {
            "method": "linear inverse-basis",
            "order": 1,
            "periodic": False,
            "outside_domain": "NaN",
            "spacing_angstrom": spacing,
        },
    )


def cell_rectangle(cell_vectors_angstrom):
    """Smallest XY rectangle containing one simulation parallelogram."""
    vectors = np.asarray(cell_vectors_angstrom, dtype=float)
    if (
        vectors.shape != (2, 2)
        or not np.isfinite(vectors).all()
        or abs(np.linalg.det(vectors)) < 1e-12
    ):
        raise ValueError(
            "The simulation needs two independent finite in-plane cell vectors."
        )
    corners = np.array([[0, 0], [1, 0], [0, 1], [1, 1]]) @ vectors
    lower, upper = corners.min(axis=0), corners.max(axis=0)
    return {
        "width_angstrom": float(upper[0] - lower[0]),
        "height_angstrom": float(upper[1] - lower[1]),
        "center_angstrom": ((lower + upper) / 2).tolist(),
    }


def normalize_image_area(area):
    width, height = float(area["width_angstrom"]), float(area["height_angstrom"])
    center = np.asarray(area["center_angstrom"], dtype=float)
    if (
        not np.isfinite([width, height]).all()
        or min(width, height) <= 0
        or center.shape != (2,)
        or not np.isfinite(center).all()
    ):
        raise ValueError(
            "Image width/height must be positive and its XY centre finite (angstrom)."
        )
    return {
        "width_angstrom": width,
        "height_angstrom": height,
        "center_angstrom": center.tolist(),
    }


def _native_grid(
    data, origin_angstrom, steps_angstrom, cell_vectors_angstrom, periodic_axes
):
    """Validate one complete native domain for both images and local sampling."""
    values = np.array(data, dtype=float, copy=True)
    origin = np.asarray(origin_angstrom, dtype=float)
    steps = np.asarray(steps_angstrom, dtype=float)
    cell = np.asarray(cell_vectors_angstrom, dtype=float)
    periodic = np.asarray(periodic_axes, dtype=bool)
    if (
        values.ndim != 2
        or min(values.shape) < 2
        or np.isinf(values).any()
        or not np.isfinite(values).any()
    ):
        raise ValueError("Select a valid two-dimensional map with finite samples.")
    if (
        origin.shape != (2,)
        or steps.shape != (2, 2)
        or not np.isfinite(origin).all()
        or not np.isfinite(steps).all()
        or abs(np.linalg.det(steps)) < 1e-14
    ):
        raise ValueError("The original XY grid must be finite and nonsingular.")
    cell_rectangle(cell)
    if periodic.shape != (2,):
        raise ValueError(
            "Specify periodicity along the two simulation lattice directions."
        )
    inverse = np.linalg.inv(steps)
    period_indices = cell @ inverse
    periods = [None, None]
    for axis in range(2):
        if not periodic[axis]:
            continue
        projected = period_indices[axis]
        count = int(round(abs(projected[axis])))
        if (
            count < 2
            or not np.isclose(abs(projected[axis]), count, rtol=1e-6, atol=1e-6)
            or not np.isclose(projected[1 - axis], 0, atol=1e-5)
        ):
            raise ValueError(
                "The stored grid does not resolve the native periodic cell along its grid axes."
            )
        if values.shape[axis] < count:
            raise ValueError(
                "The stored map covers less than one periodic cell; missing calculated data cannot be filled by PBC."
            )
        periods[axis] = count
    return values, origin, steps, cell, periodic, periods


def _sample_grid(grid, points_angstrom):
    values, origin, steps, cell, periodic, periods = grid
    points = np.asarray(points_angstrom, dtype=float)
    if points.ndim < 2 or points.shape[-1] != 2 or not np.isfinite(points).all():
        raise ValueError("Sampling points must be finite XY coordinates in angstrom.")
    indices = (points - origin) @ np.linalg.inv(steps)
    slices = tuple(
        slice(0, periods[axis]) if periodic[axis] else slice(None) for axis in range(2)
    )
    sampled_source = values[slices]
    for axis in range(2):
        if periodic[axis]:
            indices[..., axis] %= periods[axis]
    padded = np.pad(
        sampled_source,
        tuple((0, 1 if periodic[axis] else 0) for axis in range(2)),
        mode="wrap",
    )
    valid = np.ones(points.shape[:-1], dtype=bool)
    for axis in range(2):
        if not periodic[axis]:
            valid &= (indices[..., axis] >= -1e-9) & (
                indices[..., axis] <= values.shape[axis] - 1 + 1e-9
            )
            indices[..., axis] = np.clip(indices[..., axis], 0, values.shape[axis] - 1)
    sampled = map_coordinates(
        padded,
        np.moveaxis(indices, -1, 0),
        order=1,
        mode="constant",
        cval=np.nan,
        prefilter=False,
    )
    sampled[~valid] = np.nan
    return sampled


def sample_map(
    data,
    origin_angstrom,
    steps_angstrom,
    points_angstrom,
    *,
    cell_vectors_angstrom,
    periodic_axes,
):
    """Sample stored values at physical XY points with native lattice PBC.

    Uses exactly the same inverse-grid linear interpolation as the SXM raster.
    Missing nonperiodic data stays missing; no energy interpolation or averaging.
    """
    return _sample_grid(
        _native_grid(
            data, origin_angstrom, steps_angstrom, cell_vectors_angstrom, periodic_axes
        ),
        points_angstrom,
    )


def rectangular_raster(
    data, origin_angstrom, steps_angstrom, area, *, cell_vectors_angstrom, periodic_axes
):
    """Sample pixel centres and wrap only verified complete periodic lattice axes.

    Cell translations act in native grid coordinates, not independently on
    Cartesian rectangle edges. Padding supplies the neighbour across each
    periodic seam for the same linear interpolation used by the cube slicer.
    Source data/geometry remain unchanged. Cropped maps cannot supply a missing
    fundamental periodic domain and are rejected before publication.
    """
    grid = _native_grid(
        data, origin_angstrom, steps_angstrom, cell_vectors_angstrom, periodic_axes
    )
    values, origin, steps, cell, periodic, periods = grid
    area = normalize_image_area(area)
    # Retain native Cartesian pixel spacings; oblique grids use the smaller
    # native step norm for an isotropic derived display raster.
    if np.allclose(steps, np.diag(np.diag(steps)), atol=1e-12):
        spacing = np.abs(np.diag(steps))
    else:
        spacing = np.repeat(np.min(np.linalg.norm(steps, axis=1)), 2)
    lengths = np.array([area["width_angstrom"], area["height_angstrom"]])
    ratios = lengths / spacing
    ratios = np.where(
        np.isclose(ratios, np.round(ratios), rtol=1e-7, atol=1e-8),
        np.round(ratios),
        ratios,
    )
    shape = np.maximum(2, np.ceil(ratios).astype(int))
    delta = lengths / shape
    lower = np.array(area["center_angstrom"]) - lengths / 2
    first = lower + delta / 2
    x, y = np.meshgrid(
        first[0] + np.arange(shape[0]) * delta[0],
        first[1] + np.arange(shape[1]) * delta[1],
        indexing="ij",
    )
    sampled = _sample_grid(grid, np.stack([x, y], axis=-1))
    if not np.isfinite(sampled).any():
        raise ValueError("The selected image area contains no computed map data.")
    return Raster(
        sampled,
        first,
        np.diag(delta),
        {
            "method": "linear inverse-basis with native lattice PBC",
            "order": 1,
            "periodic_axes": periodic.tolist(),
            "period_index_counts": periods,
            "outside_nonperiodic_domain": "NaN",
            "image_area": area,
            "simulation_cell_vectors_angstrom": cell.tolist(),
            "pixel_count": shape.tolist(),
            "pixel_spacing_angstrom": delta.tolist(),
            "sampling_revision": 1,
        },
    )


def map_quantity(series):
    kind = series.get("type")
    if kind == "const-isovalue stm":
        return {
            "mode": "STM constant current (constant isovalue)",
            "name": "Z",
            "unit": "m",
            "scale": 1e-10,
            "quantity": "height_above_topmost_atom",
            "native_unit": "angstrom",
        }
    if kind in {"const-height stm", "const-height sts", "const-isovalue sts"}:
        return {
            "mode": "STS dI/dV on a constant-current surface"
            if kind == "const-isovalue sts"
            else "STS dI/dV at constant height"
            if kind == "const-height sts"
            else "STM current at constant height",
            "name": "Simulated_dIdV_au" if kind.endswith("sts") else "Simulated_STM_au",
            "unit": "a.u.",
            "scale": 1.0,
            "quantity": "simulated_dIdV"
            if kind.endswith("sts")
            else "simulated_integrated_STM_signal",
            "native_unit": "a.u.",
        }
    raise ValueError("Select a stored STM or STS map, not an unsupported observable.")


def write_sxm(path, raster, series, energy_ev, metadata, *, legacy_direction_copy=True):
    """Write one physical field; a legacy backward buffer is an explicit copy.

    The current openBIS Nanonis reader expects two buffers per channel. When
    enabled, the second is the same field encoded in reverse fast-axis order,
    not another simulation/acquisition. This is recorded in header and sidecar.
    """
    quantity = map_quantity(series)
    isovalue_mode = series["type"].startswith("const-isovalue")
    parameter = "isovalue" if isovalue_mode else "height"
    setpoint = float(series[parameter])
    if not np.isfinite(setpoint):
        raise ValueError("The stored simulation setpoint must be finite.")
    setpoint_unit = "native" if isovalue_mode else "angstrom"
    setpoint_name = "Simulation_3D_isovalue" if isovalue_mode else "Simulation_height"
    if not np.isfinite(energy_ev):
        raise ValueError("The map energy/bias must be finite.")
    values = np.asarray(raster.values)
    steps = np.asarray(raster.steps_angstrom)
    if not np.allclose(steps, np.diag(np.diag(steps))) or np.any(np.diag(steps) <= 0):
        raise ValueError(
            "SXM requires a Cartesian raster; regularize the original grid first."
        )
    now = datetime.now(timezone.utc)
    payload = {
        **_json(metadata),
        "simulated": True,
        "format_revision": FORMAT_REVISION,
        "series": _json(series),
        "energy_relative_to_fermi_ev": float(energy_ev),
        "bias_voltage_v": float(energy_ev),
        "simulation_setpoint": {
            "kind": "3D_field_isovalue"
            if isovalue_mode
            else "height_above_topmost_atom",
            "value": setpoint,
            "unit": setpoint_unit,
        },
        "quantity": quantity,
        "sample_origin_angstrom": raster.origin_angstrom.tolist(),
        "sample_steps_angstrom": steps.tolist(),
        "interpolation": raster.interpolation,
        "direction_encoding": "forward plus x-reversed compatibility copy; one physical field"
        if legacy_direction_copy
        else "forward only",
        "timestamp_role": "derived-file export, not experimental acquisition",
        "exported_utc": now.isoformat(),
    }
    extent = np.asarray(values.shape) * np.diag(steps) * 1e-10
    center = (
        raster.origin_angstrom + (np.asarray(values.shape) - 1) @ steps / 2
    ) * 1e-10
    # Store the real simulation parameter with its explicit native role.
    # Timing/gain zeros are format placeholders, never acquired instrument data.
    fields = [
        ("NANONIS_VERSION", "2"),
        ("SCANIT_TYPE", "FLOAT MSBFIRST"),
        ("SCAN_PIXELS", f"{values.shape[0]} {values.shape[1]}"),
        ("SCAN_RANGE", f"{extent[0]:.17g} {extent[1]:.17g}"),
        ("SCAN_OFFSET", f"{center[0]:.17g} {center[1]:.17g}"),
        ("SCAN_ANGLE", "0"),
        ("SCAN_DIR", "up"),
        ("BIAS", f"{energy_ev:.17g}"),
        ("SCAN_TIME", "0 0"),
        ("ACQ_TIME", "0"),
        ("REC_DATE", now.strftime("%d.%m.%Y")),
        ("REC_TIME", now.strftime("%H:%M:%S")),
        (
            "Z-CONTROLLER",
            "\tName\ton\tSetpoint\tP-gain\tI-gain\tT-const\n\t"
            + setpoint_name
            + f"\t{int(isovalue_mode)}\t{setpoint:.17g} {setpoint_unit}\t0\t0\t0",
        ),
        (
            "COMMENT",
            "SIMULATED CP2K STM/STS; no instrument calibration or acquisition. Timing/gain zeros are format placeholders; setpoint is the simulation parameter, not an experimental current. "
            + canonical_json(payload),
        ),
        (
            "DATA_INFO",
            "\tChannel\tName\tUnit\tDirection\tCalibration\tOffset\n\t0\t"
            + quantity["name"]
            + "\t"
            + quantity["unit"]
            + "\t"
            + ("both" if legacy_direction_copy else "forward")
            + "\t1\t0",
        ),
    ]
    # Match Nanonis v2's blank separator and two padding newlines before
    # the 0x1a04 marker; the established reader advances four bytes past it.
    header = (
        "".join(":" + key + ":\n" + value + "\n" for key, value in fields)
        + "\n:SCANIT_END:\n\n\n"
    )
    array = (values * quantity["scale"]).T.astype(">f4")
    if np.any(np.isinf(array)):
        raise ValueError(
            "The map cannot be represented as SXM float32 without overflow."
        )
    with Path(path).open("wb") as stream:
        stream.write(header.encode("utf-8"))
        stream.write(b"\x1a\x04")
        stream.write(array.tobytes())
        if legacy_direction_copy:
            stream.write(array[:, ::-1].tobytes())
    return payload


def write_dat(
    path,
    energy_ev,
    signal,
    metadata,
    *,
    signal_name="Simulated_STS",
    signal_unit="a.u.",
    x_name="Energy",
    x_unit="eV",
    x_quantity="energy_relative_to_fermi",
):
    """Write an explicit derived curve, with no fictitious ampere calibration."""
    energy, values = np.asarray(energy_ev, dtype=float), np.asarray(signal, dtype=float)
    if (
        energy.ndim != 1
        or energy.shape != values.shape
        or not len(energy)
        or not np.isfinite(energy).all()
        or np.isinf(values).any()
        or not np.isfinite(values).any()
    ):
        raise ValueError(
            "The curve needs matching energy/signal samples and finite energy values."
        )
    if any(c in signal_name + signal_unit + x_name + x_unit for c in "\t\r\n"):
        raise ValueError("Curve labels must not contain tab or newline characters.")
    now = datetime.now(timezone.utc)
    payload = {
        **_json(metadata),
        "simulated": True,
        "format_revision": FORMAT_REVISION,
        "timestamp_role": "derived-file export",
        "x_quantity": x_quantity,
        "x_unit": x_unit,
        "y_quantity": signal_name,
        "y_unit": signal_unit,
    }
    with Path(path).open("w", encoding="utf-8") as stream:
        stream.write(
            "Experiment\tCP2K STM/STS simulation\nSaved Date\t"
            + now.strftime("%d.%m.%Y %H:%M:%S")
            + "\nComment\t"
            + canonical_json(payload)
            + "\n\n\n[DATA]\n"
        )
        stream.write(
            x_name + " (" + x_unit + ")\t" + signal_name + " (" + signal_unit + ")\n"
        )
        np.savetxt(
            stream, np.column_stack((energy, values)), delimiter="\t", fmt="%.17g"
        )
    return payload


def original_map_npz(data, origin_angstrom, steps_angstrom, metadata, *, general=None):
    stream = io.BytesIO()
    np.savez_compressed(
        stream,
        values=np.asarray(data),
        origin_angstrom=np.asarray(origin_angstrom),
        steps_angstrom=np.asarray(steps_angstrom),
        metadata_json=np.asarray(canonical_json(metadata)),
        source_general_info_json=np.asarray(canonical_json(general or {})),
    )
    return stream.getvalue()


def selection_key(source_uuid, source_sha256, selection):
    return hashlib.sha256(
        canonical_json(
            {
                "source_uuid": source_uuid,
                "source_sha256": source_sha256,
                "selection": selection,
                "format_revision": FORMAT_REVISION,
            }
        ).encode()
    ).hexdigest()
