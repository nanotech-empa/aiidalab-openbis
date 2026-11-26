"""Local STS point spectra and STM distance profiles from immutable map arrays."""

import re

import numpy as np

from .nanonis import archive_grid, map_quantity, sample_map


PALETTE = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


def marker_color(index):
    """Keep the first familiar colours and extend them without a short palette cycle."""
    if index < len(PALETTE):
        return PALETTE[index]
    import colorsys

    rgb = colorsys.hsv_to_rgb((index * 0.618033988749895) % 1, 0.72, 0.85)
    return "#" + "".join(f"{round(component * 255):02x}" for component in rgb)


def _position(value):
    point = np.asarray(value, dtype=float)
    if point.shape != (2,) or not np.isfinite(point).all():
        raise ValueError("Use finite XY coordinates in angstrom.")
    return point.tolist()


def _marker(item, prefix):
    name = str(item["id"])
    color = str(item["color"])
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
        raise ValueError(
            "Point/line labels must be simple names, for example P1 or L1."
        )
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Use a six-digit RGB colour for each point/line.")
    result = {"id": name, "color": color.lower()}
    if prefix == "P":
        result["position_angstrom"] = _position(item["position_angstrom"])
    else:
        result["start_angstrom"] = _position(item["start_angstrom"])
        result["end_angstrom"] = _position(item["end_angstrom"])
        if (
            np.linalg.norm(
                np.subtract(result["start_angstrom"], result["end_angstrom"])
            )
            < 1e-10
        ):
            raise ValueError("A line needs two different endpoints.")
    return result


def derive_sampling(archive, requests):
    """Return plain curve arrays; never average images or interpolate energies.

    XY interpolation/wrapping is identical to the SXM raster. STS samples every
    stored energy at fixed physical points. STM samples one selected bias along
    each line, including endpoints, at intervals no larger than one native step.
    Nonperiodic missing data remain NaN and break plotted curves.
    """
    result = []
    for request in requests:
        index = request["series_index"]
        if type(index) is not int or not 0 <= index < len(archive["series"]):
            raise ValueError("Select a valid stored series for sampling.")
        info = archive["series"][index]
        values = archive["data"][index]
        energies = np.asarray(archive["general"]["energies"], dtype=float)
        origin, steps = archive_grid(archive["general"], values.shape[-2:])
        geometry = archive["simulation"]
        kwargs = {
            "cell_vectors_angstrom": geometry["in_plane_vectors_angstrom"],
            "periodic_axes": geometry["periodic_axes"],
        }
        kind = request["kind"]
        spec = {"kind": kind, "series_index": index}
        curves = []
        quantity = map_quantity(info)
        if kind == "sts_points":
            if info["type"] not in {"const-height sts", "const-isovalue sts"}:
                raise ValueError("Point spectra require an STS dI/dV series.")
            if len(energies) < 2 or len(np.unique(energies)) != len(energies):
                raise ValueError(
                    "A point spectrum needs at least two distinct stored energies."
                )
            markers = [_marker(item, "P") for item in request["points"]]
            if not markers:
                raise ValueError("Add at least one STS sampling point.")
            spec["points"] = markers
            reference = request.get("reference_energy_index")
            if reference is not None:
                if type(reference) is not int or not 0 <= reference < len(energies):
                    raise ValueError("Select a valid reference map for the STS points.")
                spec["reference_energy_index"] = reference
            positions = [m["position_angstrom"] for m in markers]
            order = np.argsort(energies)
            sampled = np.array(
                [
                    sample_map(values[e], origin, steps, positions, **kwargs)
                    for e in order
                ]
            )
            for i, marker in enumerate(markers):
                curves.append(
                    {
                        **marker,
                        "x": energies[order].tolist(),
                        "y": sampled[:, i].tolist(),
                    }
                )
            x_name, x_unit, x_quantity = "Bias", "V", "bias_voltage"
        elif kind == "stm_lines":
            if info["type"] not in {"const-height stm", "const-isovalue stm"}:
                raise ValueError(
                    "Distance profiles require an STM current or height map."
                )
            e = request["energy_index"]
            if type(e) is not int or not 0 <= e < len(energies):
                raise ValueError("Select a valid stored bias for the STM profile.")
            markers = [_marker(item, "L") for item in request["lines"]]
            if not markers:
                raise ValueError("Add at least one STM profile line.")
            spec.update(energy_index=e, lines=markers)
            spacing = float(np.min(np.linalg.norm(steps, axis=1)))
            for marker in markers:
                start, end = (
                    np.array(marker["start_angstrom"]),
                    np.array(marker["end_angstrom"]),
                )
                length = float(np.linalg.norm(end - start))
                count = max(2, int(np.ceil(length / spacing)) + 1)
                xy = np.linspace(start, end, count)
                signal = sample_map(values[e], origin, steps, xy, **kwargs)
                curves.append(
                    {
                        **marker,
                        "x": np.linspace(0, length, count).tolist(),
                        "y": signal.tolist(),
                        "sample_positions_angstrom": xy.tolist(),
                    }
                )
            spec["bias_voltage_v"] = float(energies[e])
            x_name, x_unit, x_quantity = "Distance", "angstrom", "distance_along_line"
        else:
            raise ValueError("Choose STS point spectra or STM line profiles.")
        if len({m["id"] for m in markers}) != len(markers):
            raise ValueError("Each point/line must have a different label.")
        for curve in curves:
            if not np.isfinite(curve["y"]).any():
                raise ValueError(
                    f"{curve['id']} has no calculated data at the selected coordinates."
                )
        result.append(
            {
                "request": spec,
                "series": info,
                "quantity": quantity,
                "x_name": x_name,
                "x_unit": x_unit,
                "x_quantity": x_quantity,
                "curves": curves,
                "interpolation": "linear inverse-grid with native lattice PBC; no energy interpolation or spatial average",
            }
        )
    return result


def describe_groups(groups):
    """Small reproducible review, excluding the derived sample arrays."""
    return [
        {k: v for k, v in group.items() if k != "curves"}
        | {
            "curve_count": len(group["curves"]),
            "labels": [c["id"] for c in group["curves"]],
        }
        for group in groups
    ]
