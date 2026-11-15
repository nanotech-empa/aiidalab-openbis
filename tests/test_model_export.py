"""Real recorded results and provenance, with no scientific or openBIS jobs."""

import io
import asyncio

import numpy as np
import pytest
from aiida import orm
from aiida.tools.archive import create_archive
from ase import Atoms

from aiida_openbis.snapshots import save_snapshot
from src import (
    aiida_archives,
    aiida_utils,
    export_status,
    model_export,
    simulation_schema,
)


def payload(kind="pythtb", periodic=False):
    return {
        "kind": kind,
        "title": "Model result",
        "periodic": periodic,
        "hubbard_u_ev": None,
        "converged": True,
        "solver": "ED",
    }


def test_widget_callback_records_in_running_event_loop(aiida_profile_clean):
    from aiida_openbis.snapshots import run_recording_callback

    async def notebook_message():
        uid = await run_recording_callback(lambda: save_snapshot(payload()))
        assert orm.load_node(uid).is_finished_ok
        assert await run_recording_callback(lambda: save_snapshot(payload())) == uid

    asyncio.run(notebook_message())


def assert_schema(definitions):
    for item in definitions.values():
        assignments = simulation_schema.OBJECT_TYPES[item["object_type"]]["assignments"]
        assert set(item["properties"]) <= {a["code"].lower() for a in assignments}
        assert {a["code"].lower() for a in assignments if a["mandatory"]} <= set(
            item["properties"]
        )


def test_snapshot_roundtrip_identity_and_complex_arrays(aiida_profile_clean, tmp_path):
    atoms = Atoms("C2", positions=[[0, 0, 0], [1.4, 0, 0]])
    arrays = {"energies_tb": np.array([-1.0, 1.0]), "orbital_0": np.array([1j, -1j])}
    uid = save_snapshot(payload(), arrays, {"model.txt": b"original result"}, atoms)
    assert (
        save_snapshot(payload(), arrays, {"model.txt": b"original result"}, atoms)
        == uid
    )
    node = orm.load_node(uid)
    assert node.process_type == model_export.SNAPSHOT_TYPE
    assert_schema(model_export.definitions(node))
    assert aiida_utils.get_export_main_workchains(uid) == [uid]
    assert [str(n.uuid) for n in aiida_utils._exportable_workchains(node)] == [uid]
    with node.outputs.result.base.repository.open("arrays.npz", "rb") as stream:
        with np.load(io.BytesIO(stream.read())) as stored:
            np.testing.assert_array_equal(stored["orbital_0"], arrays["orbital_0"])
    archive = tmp_path / "result.aiida"
    create_archive([node], filename=archive)
    assert aiida_archives.root_processes(archive)[0]["uuid"] == uid
    model_export.render_preview(uid, "levels", tmp_path / "preview.png")
    assert (tmp_path / "preview.png").stat().st_size > 100


@pytest.mark.parametrize("kind", ["spin_graph", "hubbard"])
def test_abstract_models_have_no_fake_atoms_charge_or_spin(aiida_profile_clean, kind):
    uid = save_snapshot(payload(kind), files={"model-results.json": b"{}"})
    node = orm.load_node(uid)
    definitions = model_export.definitions(node)
    assert_schema(definitions)
    assert model_export.structures(node, "model_results") == ([], [])
    assert export_status._structures(node, "model_results", aiida_utils) == ([], [])
    props = definitions["model_results"]["properties"]
    assert "charge" not in props
    assert "spin_multiplicity" not in props
    assert props["method_family"] == "ED"
    assert definitions["model_results"]["object_type"] == "MODEL_HAMILTONIAN"
    assert props["model"] == (
        "Spin Hamiltonian" if kind == "spin_graph" else "Hubbard Hamiltonian"
    )


def test_snapshot_rejects_nonfinite_and_unsafe_attachments(aiida_profile_clean):
    with pytest.raises(ValueError, match="finite"):
        save_snapshot(payload(), {"energies": [float("nan")]})
    with pytest.raises(ValueError, match="filename"):
        save_snapshot(payload(), files={"../private": b"data"})


def test_periodic_model_preserves_unknown_gap(aiida_profile_clean):
    uid = save_snapshot(
        payload(periodic=True), {"energies_tb": [[-1.0, 1.0]], "k_distance": [0.0]}
    )
    definitions = model_export.definitions(orm.load_node(uid))
    assert_schema(definitions)
    assert "band_gap_ev" not in definitions["bands"]["properties"]


@pytest.mark.parametrize("periodic", [False, True])
def test_wannier_identity_has_one_object_per_type(aiida_profile_clean, periodic):
    from aiida_openbis.export import available_results, plan_export

    data = dict(payload(periodic=periodic), wannier={"stored": True})
    uid = save_snapshot(data)
    planned = plan_export(uid)
    types = [item["object_type"] for item in planned["results"].values()]
    assert len(types) == len(set(types))
    assert available_results(uid)[0]["uuid"] == uid
    assert planned["external_references"] == []
    with pytest.raises(ValueError, match="reserved"):
        save_snapshot(data, files={"arrays.npz": b"overwrite"})


def test_all_model_paths_are_classified(aiida_profile_clean):
    for kind, extras in [
        ("pythtb", {}),
        ("pythtb", {"wannier": {"stored": True}}),
        ("pythtb", {"periodic": True, "wannier": {"stored": True}, "hubbard_u_ev": 2}),
        ("spin_graph", {"solver": "DMRG"}),
        ("hubbard", {"solver": "ED"}),
    ]:
        uid = save_snapshot(dict(payload(kind), **extras))
        definitions = model_export.definitions(orm.load_node(uid))
        assert_schema(definitions)
        assert all(
            row["object_type"] != "UNCLASSIFIED_SIMULATION"
            for row in definitions.values()
        )


def test_legacy_unclassified_export_blocks_duplicate_reclassification(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(aiida_utils, "_collection_space_code", lambda *a: "TEST")
    queries = []

    def objects(**kwargs):
        queries.append(kwargs)
        return (
            [SimpleNamespace(permId="old-record")]
            if kwargs["type"] == "UNCLASSIFIED_SIMULATION"
            else []
        )

    session = SimpleNamespace(get_objects=objects)
    for kind in ("MODEL_HAMILTONIAN", "ELECTRONIC_STRUCTURE"):
        with pytest.raises(ValueError, match="duplicate result has not been created"):
            aiida_utils.find_existing_simulation_result(
                session, "collection", kind, "source-uuid"
            )
    assert all(q["where"] == {"AIIDA_SOURCE_UUID": "source-uuid"} for q in queries)


def test_itensor_chain_preview_uses_saved_topology(
    aiida_profile_clean, tmp_path, monkeypatch
):
    from aiida.common.links import LinkType
    from src import model_previews

    metadata = orm.Dict(
        dict={
            "model": "mixed_spin_heisenberg_chain_v1",
            "site_spins": [0.5, 1, 0.5],
            "couplings_meV": [2.0, 3.0],
            "ground_energy_meV": -4.2,
        }
    ).store()
    node = orm.WorkChainNode(process_type="aiida.workflows:itensor_spin.spectra")
    node.base.links.add_incoming(metadata, LinkType.INPUT_WORK, "ground_state_metadata")
    node.store()
    captured = []
    original = model_previews.figure

    def render(payload):
        captured.append(payload)
        return original(payload)

    monkeypatch.setattr(model_previews, "figure", render)
    target = tmp_path / "chain.png"
    model_export.render_preview(str(node.uuid), "model_results", target)
    graph = captured[0]["results"][0]["graph"]
    assert graph["site_spins"] == [0.5, 1, 0.5]
    assert graph["exchange_edges"] == [
        {"i": 1, "j": 2, "J_meV": 2.0},
        {"i": 2, "j": 3, "J_meV": 3.0},
    ]
    assert target.stat().st_size > 1000
