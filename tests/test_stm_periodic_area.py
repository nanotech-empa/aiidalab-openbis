"""Cartesian SXM rectangles respect native lattice periods and pixel centres."""

import numpy as np
import pytest

from aiida_openbis.nanonis import (
    cell_rectangle,
    rectangular_raster,
    write_sxm,
)
from nanonis_importer.spmpy.nanonispy.read import Scan


def sample(data, steps, area=None, periodic=(True, True), origin=(0, 0)):
    steps = np.asarray(steps, dtype=float)
    cell = np.diag(np.shape(data)) @ steps
    return rectangular_raster(
        data,
        origin,
        steps,
        cell_rectangle(cell) if area is None else area,
        cell_vectors_angstrom=cell,
        periodic_axes=periodic,
    )


@pytest.mark.parametrize(
    "steps",
    [
        [[0.2, 0], [0.1, 0.17]],
        [[0.2, 0], [-0.1, 0.17]],
        [[0, 0.2], [0.3, 0]],
        [[-0.2, 0], [0, 0.3]],
    ],
)
def test_oblique_rectangle_corners_filled_and_lattice_translations_identical(steps):
    steps = np.asarray(steps)
    i, j = np.meshgrid(np.arange(9), np.arange(7), indexing="ij")
    data = np.cos(2 * np.pi * i / 9) + 0.3 * np.sin(2 * np.pi * j / 7)
    before = data.copy()
    cell = np.diag(data.shape) @ steps
    area = cell_rectangle(cell)
    actual = sample(data, steps, area)
    assert np.isfinite(
        actual.values
    ).all()  # Includes triangles outside one parallelogram.
    assert np.ptp(actual.values) > 0.1
    for translation in (cell[0], cell[1], cell[0] - 2 * cell[1]):
        shifted = {
            **area,
            "center_angstrom": (
                np.array(area["center_angstrom"]) + translation
            ).tolist(),
        }
        translated = sample(data, steps, shifted)
        np.testing.assert_allclose(actual.values, translated.values, atol=3e-14)
    np.testing.assert_array_equal(data, before)


def test_periodic_boundary_interpolates_between_last_and_first_sample():
    data = np.repeat(np.array([0.0, 2.0, 4.0, 6.0])[:, None], 4, axis=1)
    raster = sample(data, np.eye(2))
    # Samples at x=.5,1.5,2.5,3.5. The final one crosses the seam.
    np.testing.assert_allclose(raster.values[:, 0], [1, 3, 5, 3])


def test_mixed_periodicity_masks_only_nonperiodic_direction():
    data = np.arange(16, dtype=float).reshape(4, 4)
    area = {
        "width_angstrom": 8.0,
        "height_angstrom": 8.0,
        "center_angstrom": [2.0, 2.0],
    }
    raster = sample(data, np.eye(2), area, periodic=(True, False))
    assert np.isfinite(raster.values[:, 2:5]).all()
    assert np.isnan(raster.values[:, :2]).all()
    assert np.isnan(raster.values[:, 5:]).all()
    np.testing.assert_allclose(raster.values[:4, 2:5], raster.values[4:, 2:5])


@pytest.mark.parametrize(
    "size,center", [([1.3, 0.9], [-0.2, 0.8]), ([8.2, 6.4], [1.0, -2.0])]
)
def test_sxm_has_exact_requested_size_and_center_and_original_unchanged(
    tmp_path, size, center
):
    data = np.arange(24.0).reshape(6, 4)
    area = {
        "width_angstrom": size[0],
        "height_angstrom": size[1],
        "center_angstrom": center,
    }
    raster = sample(data, [[0.2, 0], [0.1, 0.3]], area)
    path = tmp_path / "area.sxm"
    write_sxm(path, raster, {"type": "const-height stm", "height": 4}, -0.5, {})
    scan = Scan(str(path))
    np.testing.assert_allclose(scan.header["scan_range"] * 1e10, size, rtol=1e-14)
    np.testing.assert_allclose(scan.header["scan_offset"] * 1e10, center, atol=1e-14)
    first = np.array(center) - np.array(size) / 2 + np.diag(raster.steps_angstrom) / 2
    np.testing.assert_allclose(raster.origin_angstrom, first)
    np.testing.assert_array_equal(data, np.arange(24.0).reshape(6, 4))


def test_missing_periodic_data_is_not_invented():
    with pytest.raises(ValueError, match="less than one periodic cell"):
        rectangular_raster(
            np.ones((3, 4)),
            [0, 0],
            np.eye(2),
            {"width_angstrom": 5, "height_angstrom": 4, "center_angstrom": [2.5, 2]},
            cell_vectors_angstrom=[[5, 0], [0, 4]],
            periodic_axes=[True, True],
        )


def test_nonperiodic_linear_field_uses_inverse_grid_without_wrapping():
    steps = np.array([[0.2, 0], [0.1, 0.3]])
    i, j = np.meshgrid(np.arange(9), np.arange(7), indexing="ij")
    xy = np.stack([i, j], axis=-1) @ steps
    data = 3 * xy[..., 0] - 2 * xy[..., 1]
    raster = sample(data, steps, periodic=(False, False))
    i, j = np.meshgrid(
        np.arange(raster.values.shape[0]),
        np.arange(raster.values.shape[1]),
        indexing="ij",
    )
    xy_out = raster.origin_angstrom + np.stack([i, j], axis=-1) @ raster.steps_angstrom
    mask = np.isfinite(raster.values)
    assert mask.any() and (~mask).any()
    np.testing.assert_allclose(
        raster.values[mask], (3 * xy_out[..., 0] - 2 * xy_out[..., 1])[mask], atol=1e-14
    )
