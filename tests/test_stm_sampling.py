"""Point spectra and line profiles keep physical coordinates, axes and values."""

import copy
import io
import zipfile

import numpy as np
import pytest

from aiida_openbis.nanonis import (
    BOHR_ANGSTROM,
    cell_rectangle,
    rectangular_raster,
    sample_map,
)
from aiida_openbis.stm_sampling import derive_sampling
from test_stm_imaging import stored_stm as _stored_stm_fixture

stored_stm = _stored_stm_fixture


def archive(steps=None, periodic=(True, True)):
    steps = np.array(steps if steps is not None else [[0.2, 0], [0.1, 0.3]])
    cell = np.diag([10, 8]) @ steps
    i, j = np.meshgrid(np.arange(10), np.arange(8), indexing="ij")
    xy = np.stack([i, j], axis=-1) @ steps
    energies = np.array([-0.5, 0, 0.5])
    field = 2 * xy[..., 0] + 3 * xy[..., 1]
    # Four kinds; the fixed-height STS varies analytically with bias and position.
    data = np.stack(
        [
            np.stack([field + 4 * e for e in energies]),
            np.stack([5 + field + e for e in energies]),
            np.stack([field + 4 * e for e in energies]),
            np.stack([field + 7 * e for e in energies]),
        ]
    )
    return {
        "data": data,
        "series": [
            {"type": "const-height stm", "height": 4},
            {"type": "const-isovalue stm", "isovalue": 1e-6},
            {"type": "const-height sts", "height": 4},
            {"type": "const-isovalue sts", "isovalue": 1e-6},
        ],
        "general": {
            "energies": energies,
            "origin": [0, 0, 0],
            "dv_vectors": [
                [*(steps[0] / BOHR_ANGSTROM), 0],
                [*(steps[1] / BOHR_ANGSTROM), 0],
                [0, 0, 1],
            ],
        },
        "simulation": {
            "in_plane_vectors_angstrom": cell.tolist(),
            "periodic_axes": list(periodic),
            "default_image_area": cell_rectangle(cell),
        },
    }


def points(series=2):
    return {
        "kind": "sts_points",
        "series_index": series,
        "points": [
            {"id": "P1", "color": "#1f77b4", "position_angstrom": [0.8, 0.6]},
            {"id": "P2", "color": "#ff7f0e", "position_angstrom": [1.0, 0.9]},
        ],
    }


def line(series=0, e=1, reverse=False):
    ends = [[0.5, 0.6], [1.3, 1.2]]
    if reverse:
        ends.reverse()
    return {
        "kind": "stm_lines",
        "series_index": series,
        "energy_index": e,
        "lines": [
            {
                "id": "L1",
                "color": "#1f77b4",
                "start_angstrom": ends[0],
                "end_angstrom": ends[1],
            }
        ],
    }


@pytest.mark.parametrize("series,slope", [(2, 4), (3, 7)])
def test_sts_spectra_are_at_distinct_fixed_points_and_all_native_energies(
    series, slope
):
    source = archive()
    before = source["data"].copy()
    result = derive_sampling(source, [points(series)])[0]
    assert result["x_unit"] == "V" and result["x_quantity"] == "bias_voltage"
    assert result["quantity"]["native_unit"] == "a.u."
    for marker, curve in zip(points(series)["points"], result["curves"]):
        x, y = marker["position_angstrom"]
        np.testing.assert_allclose(curve["x"], [-0.5, 0, 0.5])
        np.testing.assert_allclose(
            curve["y"], 2 * x + 3 * y + slope * np.array(curve["x"]), atol=1e-12
        )
        assert curve["color"] == marker["color"] and curve["id"] == marker["id"]
    np.testing.assert_array_equal(source["data"], before)


@pytest.mark.parametrize("series,base", [(0, 0), (1, 5)])
def test_stm_profiles_use_distance_not_bias_and_keep_endpoints_and_reversal(
    series, base
):
    source = archive()
    req = line(series)
    result = derive_sampling(source, [req])[0]
    curve = result["curves"][0]
    assert (
        result["x_unit"] == "angstrom" and result["x_quantity"] == "distance_along_line"
    )
    assert result["request"]["bias_voltage_v"] == 0
    xy = np.array(curve["sample_positions_angstrom"])
    np.testing.assert_allclose(xy[0], req["lines"][0]["start_angstrom"])
    np.testing.assert_allclose(xy[-1], req["lines"][0]["end_angstrom"])
    np.testing.assert_allclose(
        curve["y"], base + 2 * xy[:, 0] + 3 * xy[:, 1], atol=1e-12
    )
    assert curve["x"][0] == 0 and curve["x"][-1] == pytest.approx(1.0)
    reverse = derive_sampling(source, [line(series, reverse=True)])[0]["curves"][0]
    np.testing.assert_allclose(reverse["y"], curve["y"][::-1], atol=1e-12)
    assert (result["quantity"]["native_unit"] == "angstrom") == (series == 1)


def test_sts_lattice_translation_and_image_sampling_share_identical_interpolation():
    source = archive()
    req = points()
    first = derive_sampling(source, [req])[0]
    translated = copy.deepcopy(req)
    for point in translated["points"]:
        point["position_angstrom"] = (
            np.array(point["position_angstrom"])
            + source["simulation"]["in_plane_vectors_angstrom"][1]
        ).tolist()
    second = derive_sampling(source, [translated])[0]
    for a, b in zip(first["curves"], second["curves"]):
        np.testing.assert_allclose(a["y"], b["y"], atol=1e-12)
    steps = np.array(source["general"]["dv_vectors"])[:2, :2] * BOHR_ANGSTROM
    data = source["data"][2, 0]
    cell = source["simulation"]["in_plane_vectors_angstrom"]
    raster = rectangular_raster(
        data,
        [0, 0],
        steps,
        cell_rectangle(cell),
        cell_vectors_angstrom=cell,
        periodic_axes=[True, True],
    )
    i, j = np.meshgrid(
        np.arange(raster.values.shape[0]),
        np.arange(raster.values.shape[1]),
        indexing="ij",
    )
    xy = raster.origin_angstrom + np.stack([i, j], axis=-1) @ raster.steps_angstrom
    sampled = sample_map(
        data, [0, 0], steps, xy, cell_vectors_angstrom=cell, periodic_axes=[True, True]
    )
    np.testing.assert_array_equal(sampled, raster.values)


def test_missing_nonperiodic_data_and_mixed_measurement_modes_are_rejected():
    source = archive(periodic=(False, False))
    req = points()
    req["points"][0]["position_angstrom"] = [100, 100]
    with pytest.raises(ValueError, match="no calculated data"):
        derive_sampling(source, [req])
    with pytest.raises(ValueError, match="STS"):
        derive_sampling(source, [points(0)])
    with pytest.raises(ValueError, match="STM"):
        derive_sampling(source, [line(2)])
    req = line()
    req["lines"][0]["end_angstrom"] = req["lines"][0]["start_angstrom"]
    with pytest.raises(ValueError, match="different endpoints"):
        derive_sampling(source, [req])


def test_point_zip_and_profile_dat_roundtrip_have_native_axes_and_coordinates(
    stored_stm, tmp_path
):
    from aiida_openbis import stm_imaging as stm
    from nanonis_importer.spmpy import Spm

    req = points()
    req["points"][0]["position_angstrom"] = [0, 0]
    req["points"][1]["position_angstrom"] = [0.15, 0.2]
    content = stm.sampling_zip(stored_stm[0], [req])
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        assert len([n for n in bundle.namelist() if n.endswith(".dat")]) == 2
        assert any(n.endswith("/sampling.json") for n in bundle.namelist())
    # Source fixture has a small periodic cell; physical endpoints stay explicit.
    req = line(1)
    req["lines"][0].update(start_angstrom=[0, 0], end_angstrom=[0.3, 0.2])
    reviewed = stm.review(stored_stm[0], [], sampling=[req])
    packages = stm.prepare_files(reviewed, tmp_path)
    image = Spm(str(packages[0]["path"]))
    assert image.signals[image.default_channels[0]]["ChannelUnit"] == "angstrom"
    assert image.signals[image.default_channels[1]]["ChannelUnit"] == "angstrom"
    assert packages[0]["metadata"]["selection"]["sampling"]["bias_voltage_v"] == 0
    assert packages[0]["metadata"]["bias_voltage_v"] == 0
    assert packages[0]["preview_controls"]["Grouping"] == ["L1.dat"]


def test_line_across_two_periods_keeps_full_distance_and_native_repeat():
    source = archive()
    request = line(0)
    request["lines"][0].update(start_angstrom=[0, 0], end_angstrom=[4, 0])
    curve = derive_sampling(source, [request])[0]["curves"][0]
    assert curve["x"][-1] == 4  # The line is not shortened by minimum-image wrapping.
    assert len(curve["x"]) > 10
    assert curve["y"][0] == pytest.approx(curve["y"][-1], abs=1e-12)
    assert np.ptp(curve["y"]) > 1


def test_marker_colours_extend_beyond_the_initial_palette():
    from aiida_openbis.stm_sampling import marker_color

    assert len({marker_color(i) for i in range(32)}) == 32
