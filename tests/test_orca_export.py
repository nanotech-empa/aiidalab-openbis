"""Real isolated provenance graphs; no ORCA execution or live openBIS writes."""

import pytest
from aiida import orm
from aiida.common.links import LinkType
from aiida.tools.archive import create_archive

from src import aiida_archives, orca_export, simulation_schema


def finish(node):
    node.set_process_state("finished")
    node.set_exit_status(0)
    node.seal()
    return node


def process(op, inputs, outputs, calculation=False):
    prefix = (
        "aiida.calculations:empa_orca." if calculation else "aiida.workflows:empa_orca."
    )
    root = (orm.CalcJobNode if calculation else orm.WorkChainNode)(
        process_type=prefix + op
    )
    root.set_process_label(orca_export.PROCESS_TYPES[prefix + op])
    for key, data in inputs.items():
        root.base.links.add_incoming(
            data, LinkType.INPUT_CALC if calculation else LinkType.INPUT_WORK, key
        )
    root.store()
    creator = root
    if not calculation:
        creator = orm.CalcJobNode()
        creator.base.links.add_incoming(root, LinkType.CALL_CALC, "run")
        creator.store()
    for key, data in outputs.items():
        data.base.links.add_incoming(creator, LinkType.CREATE, key)
        data.store()
        if not calculation:
            data.base.links.add_incoming(root, LinkType.RETURN, key)
    if creator != root:
        finish(creator)
    return finish(root)


@pytest.fixture
def geometry(aiida_profile_clean, tmp_path):
    structure = orm.StructureData(pbc=False)
    structure.append_atom(position=(0, 0, 0), symbols="N")
    structure.append_atom(position=(0, 0, 1.15), symbols="O")
    structure.store()
    final = structure.clone()
    settings = orm.Dict(
        dict={
            "method": "PBE",
            "basis": "def2-SVP",
            "charge": 0,
            "multiplicity": 2,
            "constraints": [],
        }
    ).store()
    summary = orm.Dict(
        dict={"converged": True, "energy_hartree": -129.1, "frame_count": 3}
    )
    folder = tmp_path / "retrieved"
    folder.mkdir()
    (folder / "aiida.out").write_text("Stored native output")
    (folder / "preview.cube").write_text("Stored reduced cube")
    retrieved = orm.FolderData()
    retrieved.base.repository.put_object_from_tree(folder)
    return process(
        "geometry",
        {
            "structure": structure,
            "settings": settings,
            "optimize": orm.Bool(True).store(),
        },
        {"structure": final, "optimization_summary": summary, "retrieved": retrieved},
    )


def assert_schema(definitions):
    for item in definitions.values():
        assignments = simulation_schema.OBJECT_TYPES[item["object_type"]]["assignments"]
        allowed = {a["code"].lower() for a in assignments}
        mandatory = {a["code"].lower() for a in assignments if a["mandatory"]}
        assert set(item["properties"]) <= allowed
        assert mandatory <= set(item["properties"])


def test_geometry_schema_and_exact_structure_relationships(geometry):
    definitions = orca_export.definitions(geometry)
    assert_schema(definitions)
    props = definitions["geometry_optimization"]["properties"]
    assert props["final_energy_hartree"] == -129.1
    assert props["spin_multiplicity"] == 2
    assert (
        "number_of_steps" not in props
    )  # trajectory frames are not optimization iterations
    assert orca_export.structures(geometry, "geometry_optimization") == (
        [geometry.inputs.structure.uuid],
        [geometry.outputs.structure.uuid],
    )


def test_inventory_uses_repository_without_transport(geometry, monkeypatch):
    monkeypatch.setattr(
        orm.Computer, "get_transport", lambda *_: pytest.fail("No remote access")
    )
    plan = orca_export.inventory(geometry.uuid)
    assert {row["filename"] for row in plan["stored_files"]} == {
        "aiida.out",
        "preview.cube",
    }
    assert plan["structure_uuid"] == geometry.outputs.structure.uuid
    assert plan["external_references"] == []


@pytest.mark.parametrize(
    "op", ["dyson_cubes", "kondo_cubes", "dyson_maps", "kondo_maps"]
)
def test_dyson_and_kondo_spatial_results_are_spm(geometry, op):
    state = {
        "structure_uuid": geometry.outputs.structure.uuid,
        "initial_state": {"charge": -1, "multiplicity": 2},
    }
    input_name = "channels" if "kondo" in op else "transitions"
    node = process(
        op,
        {
            input_name: orm.Dict(dict=state).store(),
            "parameters": orm.Dict(dict={"height": 1.5}).store(),
        },
        {},
        calculation=op.endswith("maps"),
    )
    definitions = orca_export.definitions(node)
    assert_schema(definitions)
    item = definitions["spm"]
    assert item["object_type"] == "SPM_SIMULATION"
    assert item["properties"]["spm_mode"] == ["ORBITALS"]
    assert item["properties"]["charge"] == -1
    assert item["properties"]["spin_multiplicity"] == 2
    assert orca_export.structure_uuid(node) == geometry.outputs.structure.uuid


def test_casci_preserves_one_multiroot_result_without_fake_single_energy(geometry):
    table = {
        "structure_uuid": geometry.outputs.structure.uuid,
        "states": [
            {"root": 0, "energy_hartree": -129.1},
            {"root": 1, "energy_hartree": -129.0},
        ],
    }
    node = process(
        "casci",
        {
            "orbital_reference": orm.Dict(
                dict={"structure_uuid": geometry.outputs.structure.uuid}
            ).store(),
            "settings": geometry.inputs.settings,
        },
        {"state_energies": orm.Dict(dict=table)},
    )
    definitions = orca_export.definitions(node)
    assert_schema(definitions)
    assert list(definitions) == ["unclassified"]
    assert definitions["unclassified"]["properties"]["method_family"] == "CAS"
    assert "total_energy_hartree" not in definitions["unclassified"]["properties"]
    assert node.outputs.state_energies.get_dict() == table


def test_single_root_archive_preserves_stored_files_and_uuid(geometry, tmp_path):
    archive = tmp_path / "orca.aiida"
    create_archive(
        [geometry],
        filename=archive,
        create_backward=False,
        call_calc_backward=False,
        call_work_backward=False,
    )
    roots = aiida_archives.root_processes(archive)
    assert len(roots) == 1 and roots[0]["uuid"] == geometry.uuid
    with aiida_archives.archive_backend(archive) as backend:
        retrieved = (
            orm.QueryBuilder(backend=backend)
            .append(orm.FolderData, filters={"uuid": geometry.outputs.retrieved.uuid})
            .one()[0]
        )
        assert (
            retrieved.base.repository.get_object_content("preview.cube")
            == "Stored reduced cube"
        )


def test_failed_and_other_plugin_results_are_rejected(geometry):
    other = orm.WorkChainNode(process_type="aiida.workflows:some_other.geometry")
    other.set_process_label("GeometryWorkChain")
    assert not orca_export.supported(other)
    with pytest.raises(ValueError, match="supported"):
        orca_export.operation(other)
    failed = orm.WorkChainNode(
        process_type="aiida.workflows:empa_orca.geometry"
    ).store()
    with pytest.raises(ValueError, match="successfully"):
        orca_export.definitions(failed)


def test_map_figure_keeps_kondo_identity_and_plane_metadata(geometry):
    metadata = {
        "structure_uuid": geometry.outputs.structure.uuid,
        "initial_state": {"charge": -1, "multiplicity": 2},
        "parameters": {"channel_ids": ["ko_1"], "heights_angstrom": [1.5]},
    }
    node = process(
        "map_figure",
        {"map_metadata": orm.Dict(dict=metadata).store()},
        {},
        calculation=True,
    )
    item = orca_export.definitions(node)["spm"]
    assert_schema({"spm": item})
    assert item["properties"]["method_label"].startswith("Kondo")
    assert item["properties"]["image_modes"] == ["CONSTANT_HEIGHT"]
    assert '"heights_angstrom": [1.5]' in item["properties"]["comments"]
