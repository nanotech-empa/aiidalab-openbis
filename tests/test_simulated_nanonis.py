"""Physical fields and coordinates survive simulation-to-Nanonis conversion."""

import io
import json

import numpy as np
import pytest

from aiida_openbis.nanonis import (
    BOHR_ANGSTROM,
    archive_grid,
    display_raster,
    original_map_npz,
    selection_key,
    write_dat,
    write_sxm,
)
from nanonis_importer.spmpy.nanonispy.read import Scan, Spec


def test_orthogonal_grid_is_not_interpolated_or_normalized(tmp_path):
    data = np.arange(35, dtype=np.float32).reshape(7, 5) / 13
    before = data.copy()
    raster = display_raster(data, [2.1, -3.2], [[0.17, 0], [0, 0.23]])
    assert raster.interpolation["method"] == "none"
    np.testing.assert_array_equal(raster.values, data)
    path = tmp_path / "sim.sxm"
    metadata = write_sxm(
        path,
        raster,
        {"type": "const-height stm", "height": 5.5, "fwhm": 0.1},
        -0.5,
        {"source_uuid": "source", "simulated": True},
    )
    scan = Scan(str(path))
    np.testing.assert_array_equal(scan.signals["Simulated_STM_au"]["forward"], data.T)
    np.testing.assert_array_equal(
        scan.signals["Simulated_STM_au"]["backward"][:, ::-1], data.T
    )
    np.testing.assert_array_equal(data, before)
    np.testing.assert_allclose(
        scan.header["scan_range"], np.array([7 * 0.17, 5 * 0.23]) * 1e-10
    )
    # Recover each sample centre from the SXM centre/range convention.
    recovered_origin = (
        scan.header["scan_offset"]
        - scan.header["scan_range"] / 2
        + np.array([0.17, 0.23]) * 1e-10 / 2
    )
    np.testing.assert_allclose(
        recovered_origin, np.array([2.1, -3.2]) * 1e-10, rtol=1e-14
    )
    assert metadata["series"]["height"] == 5.5
    assert metadata["quantity"]["unit"] == "a.u."
    assert "one physical field" in metadata["direction_encoding"]
    assert "no instrument calibration" in scan.header["comment"]


def test_isovalue_map_contains_height_above_topmost_atom_not_fake_current(tmp_path):
    values = np.array([[4.2, 4.3, 4.5], [4.4, 4.8, 5.1]], dtype=np.float32)
    raster = display_raster(values, [0, 0], [[0.2, 0], [0, 0.2]])
    path = tmp_path / "height.sxm"
    metadata = write_sxm(
        path,
        raster,
        {"type": "const-isovalue stm", "isovalue": 1e-6},
        0.5,
        {"source_uuid": "source"},
    )
    scan = Scan(str(path))
    assert list(scan.signals) == ["Z"]
    np.testing.assert_allclose(scan.signals["Z"]["forward"] * 1e10, values.T, rtol=1e-7)
    assert metadata["quantity"]["quantity"] == "height_above_topmost_atom"
    assert metadata["series"]["isovalue"] == 1e-6
    assert metadata["bias_voltage_v"] == 0.5
    assert metadata["simulation_setpoint"] == {
        "kind": "3D_field_isovalue",
        "value": 1e-6,
        "unit": "native",
    }
    assert float(scan.header["z-controller"]["Setpoint"][0].split()[0]) == 1e-6
    assert "Current" not in scan.header["data_info"]["Name"]


@pytest.mark.parametrize(
    "steps",
    [
        [[0.2, 0], [0.1, 0.1732050807569]],
        [[0.1, 0.2], [-0.2, 0.1]],
        [[0, 0.2], [0.3, 0]],
        [[-0.2, 0], [0, 0.3]],
    ],
)
def test_inverse_basis_interpolation_matches_physical_linear_field(steps):
    steps = np.asarray(steps)
    shape = np.array([9, 7])
    origin = np.array([2.3, -1.7])
    i, j = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]), indexing="ij")
    points = origin + np.stack([i, j], axis=-1) @ steps
    original = 3 * points[..., 0] - 2 * points[..., 1] + 7
    raster = display_raster(original, origin, steps)
    x, y = np.meshgrid(
        np.arange(raster.values.shape[0]),
        np.arange(raster.values.shape[1]),
        indexing="ij",
    )
    target = raster.origin_angstrom + np.stack([x, y], axis=-1) @ raster.steps_angstrom
    finite = np.isfinite(raster.values)
    assert finite.any()
    np.testing.assert_allclose(
        raster.values[finite],
        (3 * target[..., 0] - 2 * target[..., 1] + 7)[finite],
        atol=1e-12,
    )
    source_indices = (target - origin) @ np.linalg.inv(steps)
    outside = np.any(
        (source_indices < -1e-8) | (source_indices > shape - 1 + 1e-8), axis=-1
    )
    assert np.isnan(raster.values[outside]).all()
    np.testing.assert_array_equal(original, 3 * points[..., 0] - 2 * points[..., 1] + 7)


def test_skewed_raster_and_original_are_separate_portable_payloads(tmp_path):
    data = np.arange(35, dtype=np.float32).reshape(7, 5)
    steps = np.array([[0.2, 0], [0.1, 0.2]])
    raster = display_raster(data, [2, 3], steps)
    assert np.isnan(raster.values).any()
    path = tmp_path / "skew.sxm"
    write_sxm(
        path,
        raster,
        {"type": "const-height stm", "height": 6},
        -1,
        {"source_uuid": "source"},
    )
    decoded = Scan(str(path)).signals["Simulated_STM_au"]["forward"].T
    np.testing.assert_allclose(decoded, raster.values, rtol=1e-7, equal_nan=True)
    payload = original_map_npz(
        data, [2, 3], steps, {"source_uuid": "source", "height": 6}
    )
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        np.testing.assert_array_equal(archive["values"], data)
        np.testing.assert_array_equal(archive["steps_angstrom"], steps)
        assert json.loads(str(archive["metadata_json"]))["source_uuid"] == "source"


def test_archive_axis_and_vector_metadata_preserve_bohr_to_angstrom():
    legacy = {"x_arr": np.arange(8) * 0.4 + 3, "y_arr": np.arange(6) * 0.7 - 2}
    origin, steps = archive_grid(legacy, (7, 5))
    np.testing.assert_allclose(origin, np.array([3, -2]) * BOHR_ANGSTROM)
    np.testing.assert_allclose(steps, np.diag([0.4, 0.7]) * BOHR_ANGSTROM)
    general = {
        "origin": np.array([3, -2, 1]),
        "dv_vectors": np.array([[0.4, 0, 0], [0.2, 0.7, 0], [0, 0, 0.3]]),
    }
    origin, steps = archive_grid(general, (7, 5))
    np.testing.assert_allclose(steps, np.array([[0.4, 0], [0.2, 0.7]]) * BOHR_ANGSTROM)


@pytest.mark.parametrize("kind", ["const-height sts", "const-isovalue sts"])
def test_sts_stays_native_signal_even_on_an_isovalue_surface(tmp_path, kind):
    raster = display_raster(np.ones((4, 3)), [0, 0], np.eye(2))
    path = tmp_path / "sts.sxm"
    result = write_sxm(
        path, raster, {"type": kind, "isovalue": 1e-6, "height": 5}, 0.5, {}
    )
    assert result["quantity"]["unit"] == "a.u."
    assert list(Scan(str(path)).signals) == ["Simulated_dIdV_au"]


def test_dat_curve_roundtrip_preserves_energy_and_native_signal(tmp_path):
    energy = np.linspace(-1, 1, 101)
    signal = np.exp(-(energy**2))
    path = tmp_path / "curve.dat"
    metadata = write_dat(
        path,
        energy,
        signal,
        {"source_uuid": "source", "sampling": "mean over original stored XY samples"},
    )
    curve = Spec(str(path))
    np.testing.assert_allclose(
        curve.signals["Energy (eV)"], energy, rtol=1e-15, atol=1e-15
    )
    np.testing.assert_allclose(
        curve.signals["Simulated_STS (a.u.)"], signal, rtol=1e-15
    )
    assert metadata["x_quantity"] == "energy_relative_to_fermi"
    assert "Current (A)" not in curve.signals


def test_export_identity_changes_for_new_source_selection_or_format():
    key = selection_key("uuid", "source-sha", {"series": 0, "energy": 1})
    assert key == selection_key("uuid", "source-sha", {"energy": 1, "series": 0})
    assert key != selection_key("uuid", "source-sha", {"series": 0, "energy": 2})
    assert key != selection_key("uuid", "new-source-sha", {"series": 0, "energy": 1})


@pytest.mark.parametrize(
    "steps", [np.zeros((2, 2)), [[1, 1], [1, 1]], [[np.nan, 0], [0, 1]]]
)
def test_invalid_grid_cannot_be_silently_exported(steps):
    with pytest.raises(ValueError):
        display_raster(np.ones((3, 3)), [0, 0], steps)


def test_unsupported_observable_and_infinite_data_rejected_before_file_write(tmp_path):
    with pytest.raises(ValueError):
        display_raster(np.full((3, 3), np.inf), [0, 0], np.eye(2))
    path = tmp_path / "not-created.sxm"
    raster = display_raster(np.ones((3, 3)), [0, 0], np.eye(2))
    with pytest.raises(ValueError):
        write_sxm(path, raster, {"type": "made-up-current"}, 0, {})
    assert not path.exists()
