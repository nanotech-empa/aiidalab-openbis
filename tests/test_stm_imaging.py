"""Stored provenance, conversion, and interrupted microscopy export recovery."""

import copy
import io
from types import SimpleNamespace

from aiida import orm
from aiida.common.links import LinkType
from aiida.engine import ProcessState
import numpy as np
import pytest

from aiida_openbis import stm_imaging as stm
from nanonis_importer.spmpy import Spm


def point_request():
    return {
        "kind": "sts_points",
        "series_index": 2,
        "points": [{"id": "P1", "color": "#1f77b4", "position_angstrom": [0, 0]}],
    }


@pytest.fixture
def stored_stm(aiida_profile_clean):
    from aiida_openbis.nanonis import BOHR_ANGSTROM

    structure = orm.StructureData(
        cell=np.diag([5 * 0.3 * BOHR_ANGSTROM, 4 * 0.4 * BOHR_ANGSTROM, 12]), pbc=False
    )
    structure.append_atom(position=[0, 0, 0], symbols="H")
    structure.store()
    root = orm.WorkChainNode(process_type="aiida.workflows:nanotech_empa.cp2k.stm")
    root.set_process_label("Cp2kStmWorkChain")
    root.base.links.add_incoming(
        structure, link_type=LinkType.INPUT_WORK, link_label="structure"
    )
    root.store()
    native = orm.CalcJobNode()
    native.set_process_label("Cp2kCalculation")
    native.base.links.add_incoming(root, link_type=LinkType.CALL_CALC, link_label="scf")
    native.base.links.add_incoming(
        structure, link_type=LinkType.INPUT_CALC, link_label="structure"
    )
    params = orm.Dict(
        dict={
            "FORCE_EVAL": {
                "SUBSYS": {"CELL": {"PERIODIC": "XY"}},
                "DFT": {"POISSON": {"PERIODIC": "XY"}},
            }
        }
    ).store()
    native.base.links.add_incoming(
        params, link_type=LinkType.INPUT_CALC, link_label="parameters"
    )
    native.store()
    computer = orm.Computer(
        label="stm-test",
        hostname="localhost",
        transport_type="core.local",
        scheduler_type="core.direct",
        workdir="/tmp/stm-test",
    ).store()
    remote = orm.RemoteData(computer=computer, remote_path="/tmp/stm-test")
    remote.base.links.add_incoming(
        native, link_type=LinkType.CREATE, link_label="remote_folder"
    )
    remote.store()
    child = orm.CalcJobNode()
    child.base.links.add_incoming(
        remote, link_type=LinkType.INPUT_CALC, link_label="parent_calc_folder"
    )
    child.base.links.add_incoming(root, link_type=LinkType.CALL_CALC, link_label="stm")
    child.store()
    archive = io.BytesIO()
    values = np.arange(3 * 3 * 5 * 4, dtype=np.float32).reshape(3, 3, 5, 4) / 100
    general = {
        "energies": np.array([-0.5, 0, 0.5]),
        "x_arr": np.arange(6) * 0.3,
        "y_arr": np.arange(5) * 0.4,
    }
    series = [
        {"type": "const-height stm", "height": 5.5, "fwhm": 0.1},
        {"type": "const-isovalue stm", "isovalue": 1e-6, "fwhm": 0.1},
        {"type": "const-height sts", "height": 5.5, "fwhm": 0.1},
    ]
    np.savez_compressed(
        archive,
        stm_general_info=general,
        stm_series_info=series,
        stm_series_data=values,
    )
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_filelike(
        io.BytesIO(archive.getvalue()), "stm.npz"
    )
    retrieved.base.links.add_incoming(
        child, link_type=LinkType.CREATE, link_label="retrieved"
    )
    retrieved.store()
    for node in (native, child, root):
        node.set_process_state(ProcessState.FINISHED)
        node.set_exit_status(0)
        node.seal()
    return str(root.uuid), str(retrieved.uuid), values


def test_read_review_and_files_preserve_source_data_and_point_spectrum(
    stored_stm, tmp_path
):
    source, retrieved, original = stored_stm
    reviewed = stm.review(
        source,
        [
            {"series_index": 0, "energy_index": 0},
            {"series_index": 0, "energy_index": 2},
        ],
        sampling=[point_request()],
    )
    assert reviewed["retrieved_uuid"] == retrieved
    assert "data" not in reviewed
    packages = stm.prepare_files(reviewed, tmp_path)
    assert [p["kind"] for p in packages] == ["map", "map", "curve"]
    image = Spm(str(packages[0]["path"]))
    assert image.default_channels == ["Simulated_STM_au"]
    signal, unit = image.get_channel(image.default_channels[0])
    assert unit == "a.u."
    from aiida_openbis.nanonis import rectangular_raster, archive_grid

    archive = stm.load_archive(source)
    origin, steps = archive_grid(archive["general"], original.shape[2:])
    raster = rectangular_raster(
        original[0, 0],
        origin,
        steps,
        reviewed["image_area"],
        cell_vectors_angstrom=reviewed["simulation"]["in_plane_vectors_angstrom"],
        periodic_axes=[True, True],
    )
    np.testing.assert_allclose(signal, raster.values.T, rtol=1e-7)
    assert (
        reviewed["simulation"]["periodic_setting"] == "XY"
    )  # Actual native setting, despite source FFF.
    assert not any(orm.load_node(archive["structure_uuid"]).pbc)
    with np.load(packages[0]["files"][0], allow_pickle=False) as original_archive:
        import json

        general = json.loads(str(original_archive["source_general_info_json"]))
        np.testing.assert_array_equal(general["x_arr"], np.arange(6) * 0.3)
        assert general["energies"] == [-0.5, 0, 0.5]
    curve = Spm(str(packages[-1]["path"]))
    assert curve.signals[curve.default_channels[0]]["ChannelUnit"] == "V"
    np.testing.assert_allclose(
        curve.get_channel(curve.default_channels[1])[0],
        original[2, :, 0, 0],
    )
    np.testing.assert_array_equal(stm.load_archive(source)["data"], original)
    for package in packages:
        assert len(package["metadata"]["file_sha256"]) >= 2


def test_stale_or_tampered_review_rejected_before_creating_files(stored_stm, tmp_path):
    reviewed = stm.review(stored_stm[0], [{"series_index": 1, "energy_index": 0}])
    reviewed["archive_sha256"] = "wrong"
    with pytest.raises(ValueError, match="changed"):
        stm.prepare_files(reviewed, tmp_path / "empty")
    assert not (tmp_path / "empty").exists()


def test_invalid_indices_and_wrong_sampling_type_rejected(stored_stm):
    source = stored_stm[0]
    for s, e in [(-1, 0), (0, 3), (False, 0), (0, 1.2)]:
        with pytest.raises(ValueError):
            stm.review(source, [{"series_index": s, "energy_index": e}])
    with pytest.raises(ValueError, match="STS"):
        request = point_request()
        request["series_index"] = 0
        stm.review(source, [], sampling=[request])


@pytest.fixture
def imaging_server(monkeypatch):
    import pybis
    from nanonis_importer import nanonis_importer as importer

    configs, datasets, previews, writes = {}, [], [], []
    fail_preview = [False]

    class Control:
        def __init__(self, *args, **kwargs):
            pass

        def get_property_config(self, perm_id):
            return copy.deepcopy(configs[perm_id])

        def update_property_config(self, perm_id, config):
            configs[perm_id] = copy.deepcopy(config)

        def create_imaging_dataset(self, **kwargs):
            perm_id = f"dataset-{len(datasets)}"
            dataset = SimpleNamespace(permId=perm_id)
            datasets.append(dataset)
            configs[perm_id] = copy.deepcopy(kwargs["config"])
            writes.append(kwargs)
            return dataset

        def make_preview(self, perm_id, index, preview):
            previews.append(perm_id)
            expected = (
                {"Channel", "X-axis", "Y-axis", "Color-scale", "Colormap", "Scaling"}
                if configs[perm_id].images[0].config.adaptor.endswith("SxmAdaptor")
                else {
                    "Channel X",
                    "Channel Y",
                    "X-axis",
                    "Y-axis",
                    "Grouping",
                    "Scaling",
                }
            )
            assert expected <= preview.config.keys()
            if fail_preview[0]:
                raise RuntimeError("preview server temporarily unavailable")
            return preview

    monkeypatch.setattr(pybis, "ImagingControl", Control)
    monkeypatch.setattr(importer, "ImagingControl", Control)
    session = SimpleNamespace(get_datasets=lambda **kwargs: datasets)
    return SimpleNamespace(
        session=session,
        configs=configs,
        datasets=datasets,
        writes=writes,
        previews=previews,
        fail_preview=fail_preview,
    )


def test_lost_preview_and_extras_reset_reuse_same_server_dataset(
    stored_stm, tmp_path, imaging_server
):
    reviewed = stm.review(stored_stm[0], [{"series_index": 0, "energy_index": 0}])
    packages = stm.prepare_files(reviewed, tmp_path)
    server = imaging_server
    server.fail_preview[0] = True
    with pytest.raises(RuntimeError, match="preview"):
        stm.publish(server.session, "/SPACE/PROJECT/COLLECTION", "spm-permid", packages)
    assert len(server.datasets) == 1
    assert (
        not server.configs["dataset-0"]
        .metadata[stm.IDENTITY_FIELD]
        .get("preview_ready")
    )
    # No AiiDA extras consulted: server identity survives resets and reimport.
    node = orm.load_node(stored_stm[0])
    node.base.extras.set("openbis_export", "outdated-local-marker")
    node.base.extras.clear()
    del node
    server.fail_preview[0] = False
    result = stm.publish(
        server.session, "/SPACE/PROJECT/COLLECTION", "spm-permid", packages
    )
    assert len(server.datasets) == 1 and result[0]["created"] is False
    assert server.writes[0]["sample"] == "spm-permid"
    assert server.writes[0]["files"] == [str(packages[0]["path"])]
    identity = server.writes[0]["config"].metadata[stm.IDENTITY_FIELD]
    assert identity["file_sha256"] == {
        "simulation.sxm": packages[0]["metadata"]["file_sha256"]["simulation.sxm"]
    }
    assert identity["archive_sha256"] == reviewed["archive_sha256"]
    assert identity["selection"] == packages[0]["metadata"]["selection"]
    assert len(packages[0]["files"]) == 2
    assert server.configs["dataset-0"].metadata[stm.IDENTITY_FIELD]["preview_ready"]
    count = len(server.previews)
    stm.publish(server.session, "/SPACE/PROJECT/COLLECTION", "spm-permid", packages)
    assert len(server.previews) == count


def test_unknown_inventory_or_duplicate_identity_never_means_create(
    stored_stm, tmp_path, imaging_server
):
    packages = stm.prepare_files(
        stm.review(stored_stm[0], [{"series_index": 1, "energy_index": 0}]), tmp_path
    )
    server = imaging_server
    stm.publish(server.session, "collection", "sample", packages)
    server.datasets.append(SimpleNamespace(permId="duplicate"))
    server.configs["duplicate"] = copy.deepcopy(server.configs["dataset-0"])
    with pytest.raises(ValueError, match="Multiple"):
        stm.publish(server.session, "collection", "sample", packages)
    assert len(server.writes) == 1
    server.configs.clear()
    with pytest.raises(KeyError):
        stm.publish(server.session, "collection", "sample", packages)
    assert len(server.writes) == 1


def test_curves_use_real_dat_imaging_route(stored_stm, tmp_path, imaging_server):
    reviewed = stm.review(
        stored_stm[0],
        [
            {"series_index": 0, "energy_index": 0},
            {"series_index": 2, "energy_index": 2},
        ],
        sampling=[{**point_request(), "reference_energy_index": 2}],
    )
    packages = stm.prepare_files(reviewed, tmp_path)
    result = stm.publish(imaging_server.session, "collection", "sample", packages)
    assert len(result) == 3
    assert (
        imaging_server.writes[-1]["config"]
        .images[0]
        .config.adaptor.endswith("DatAdaptor")
    )
    assert len(imaging_server.writes[-1]["files"]) == 2
    assert imaging_server.writes[-1]["config"].metadata[stm.IDENTITY_FIELD][
        "reference_map"
    ] == {"series_index": 2, "energy_index": 2}


def test_append_adds_only_new_curves_to_existing_spm(
    stored_stm, tmp_path, imaging_server
):
    source = stored_stm[0]
    server = imaging_server
    selection = [{"series_index": 0, "energy_index": 0}]
    first = stm.review(source, selection, sampling=[point_request()])
    stm.publish(
        server.session,
        "/SPACE/PROJECT/COLLECTION",
        "existing-spm",
        stm.prepare_files(first, tmp_path / "initial"),
    )
    request = point_request()
    request["points"][0].update(id="Renamed", color="#ff0000")
    request["points"].append(
        {"id": "P2", "color": "#0000ff", "position_angstrom": [0.1, 0.1]}
    )
    line = {
        "kind": "stm_lines",
        "series_index": 0,
        "energy_index": 1,
        "lines": [
            {
                "id": "L1",
                "color": "#ff0000",
                "start_angstrom": [0, 0],
                "end_angstrom": [0.1, 0.1],
            }
        ],
    }
    later = stm.review(source, selection, sampling=[request, line])

    additions, pending = stm.review_dat_additions(server.session, "existing-spm", later)
    assert not pending
    assert [point["id"] for point in additions[0]["points"]] == ["P2"]
    assert additions[1]["lines"] == line["lines"]
    append = stm.review(source, [], sampling=additions)
    stm.publish(
        server.session,
        "/SPACE/PROJECT/COLLECTION",
        "existing-spm",
        stm.prepare_files(append, tmp_path / "append"),
    )
    assert len(server.datasets) == 4
    assert all(write["sample"] == "existing-spm" for write in server.writes)
    assert all(
        write["config"].images[0].config.adaptor.endswith("DatAdaptor")
        for write in server.writes[2:]
    )
    assert stm.review_dat_additions(server.session, "existing-spm", later) == ([], [])


def test_append_recovers_pending_dat_preview_in_place(
    stored_stm, tmp_path, imaging_server
):
    source = stored_stm[0]
    server = imaging_server
    reviewed = stm.review(source, [], sampling=[point_request()])
    packages = stm.prepare_files(reviewed, tmp_path)
    server.fail_preview[0] = True
    with pytest.raises(RuntimeError, match="preview"):
        stm.publish(server.session, "collection", "existing-spm", packages)

    assert stm.review_dat_additions(server.session, "existing-spm", reviewed) == (
        [],
        reviewed["sampling"],
    )
    server.fail_preview[0] = False
    result = stm.publish(server.session, "collection", "existing-spm", packages)
    assert len(server.writes) == 1
    assert result[0]["preview_ready"] and not result[0]["created"]


def test_lost_create_acknowledgement_is_recovered_from_server(
    stored_stm, tmp_path, imaging_server, monkeypatch
):
    from nanonis_importer import nanonis_importer as importer

    packages = stm.prepare_files(
        stm.review(stored_stm[0], [{"series_index": 0, "energy_index": 0}]), tmp_path
    )
    create = importer.create_sxm_dataset

    def lost_reply(**kwargs):
        create(**kwargs)
        raise RuntimeError("response lost after committed dataset")

    monkeypatch.setattr(importer, "create_sxm_dataset", lost_reply)
    with pytest.raises(RuntimeError, match="response lost"):
        stm.publish(imaging_server.session, "collection", "sample", packages)
    assert len(imaging_server.datasets) == 1
    monkeypatch.setattr(importer, "create_sxm_dataset", create)
    result = stm.publish(imaging_server.session, "collection", "sample", packages)
    assert len(imaging_server.datasets) == 1
    assert not result[0]["created"] and result[0]["preview_ready"]


@pytest.mark.parametrize(
    "series,channel,unit",
    [
        (
            {"type": "const-height stm", "height": 5.5, "fwhm": 0.1},
            "Simulated_STM_au",
            "a.u.",
        ),
        ({"type": "const-isovalue stm", "isovalue": 1e-6, "fwhm": 0.1}, "z", "nm"),
        (
            {"type": "const-height sts", "height": 5.5, "fwhm": 0.1},
            "Simulated_dIdV_au",
            "a.u.",
        ),
        (
            {"type": "const-isovalue sts", "isovalue": 1e-6, "fwhm": 0.1},
            "Simulated_dIdV_au",
            "a.u.",
        ),
    ],
)
def test_single_simulated_channel_is_a_complete_imaging_configuration(
    tmp_path, imaging_server, series, channel, unit
):
    from aiida_openbis.nanonis import display_raster, write_sxm
    from nanonis_importer import nanonis_importer as importer

    path = tmp_path / "single-channel.sxm"
    write_sxm(
        path,
        display_raster(np.arange(20).reshape(5, 4) / 10, [0, 0], np.eye(2)),
        series,
        0.5,
        {},
    )
    importer.create_sxm_dataset(
        imaging_server.session, "collection", str(path), "sample"
    )
    config = imaging_server.writes[0]["config"].images[0].config
    control = next(item for item in config.inputs if item.label == "Channel")
    assert control.values == [channel]
    colors = next(item for item in config.inputs if item.label == "Color-scale")
    assert colors.visibility[0].unit == unit
    assert config.filters == {}
    assert "I" not in control.values


def test_isovalue_metadata_never_reports_an_experimental_picoampere_setpoint(
    stored_stm, tmp_path, imaging_server
):
    reviewed = stm.review(stored_stm[0], [{"series_index": 1, "energy_index": 0}])
    packages = stm.prepare_files(reviewed, tmp_path)
    stm.publish(imaging_server.session, "collection", "sample", packages)
    metadata = imaging_server.writes[0]["config"].images[0].metadata
    assert metadata["3D-field isovalue (native)"] == "1e-06"
    assert metadata["Bias (V)"] == "-0.5"
    assert metadata["Mode"] == "STM constant current (constant isovalue)"
    assert "pA" not in str(metadata)


def test_area_changes_map_identity_but_not_fixed_point_spectrum(stored_stm, tmp_path):
    selections = [{"series_index": 0, "energy_index": e} for e in (0, 2)]
    first = stm.review(stored_stm[0], selections, sampling=[point_request()])
    other_area = copy.deepcopy(first["image_area"])
    other_area["width_angstrom"] *= 2
    second = stm.review(
        stored_stm[0], selections, sampling=[point_request()], image_area=other_area
    )
    a = stm.prepare_files(first, tmp_path / "a")
    b = stm.prepare_files(second, tmp_path / "b")
    assert a[0]["key"] != b[0]["key"]
    assert a[-1]["key"] == b[-1]["key"]
    assert a[-1]["metadata"]["selection"] == b[-1]["metadata"]["selection"]
    assert stm.describe(stored_stm[0])["default_image_area"] == first["image_area"]
    first["image_area"]["width_angstrom"] *= 3
    with pytest.raises(ValueError, match="changed"):
        stm.prepare_files(first, tmp_path / "stale")
    assert not (tmp_path / "stale").exists()
