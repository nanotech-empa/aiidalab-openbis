import io
import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


class FakeDict:
    def __init__(self, values):
        self._values = values

    def get_dict(self):
        return self._values


class FakeOpenbisObject:
    _counter = 0

    def __init__(self, object_type, props=None):
        FakeOpenbisObject._counter += 1
        self.type = object_type
        self.permId = f"fake-{FakeOpenbisObject._counter}"
        self.props = dict(props or {})
        self.parents = []
        self.children = []

    def add_parents(self, parent):
        self.parents.append(parent)

    def add_children(self, child):
        self.children.append(child)


class FakeSession:
    def __init__(self, objects=None):
        self.objects = objects or {}
        self.url = "https://openbis.example"

    def get_objects(
        self,
        type=None,
        collection=None,
        space=None,
        where=None,
        **_kwargs,
    ):
        objects = list(self.objects.get(type, []))
        if collection is not None:
            objects = [
                obj for obj in objects if getattr(obj, "collection", None) == collection
            ]
        if space is not None:
            objects = [
                obj
                for obj in objects
                if str(getattr(obj, "collection", "")).strip("/").split("/", 1)[0]
                == str(space).strip("/")
            ]
        for code, expected in (where or {}).items():
            key = code.lower()
            wildcard = str(expected).startswith("*") and str(expected).endswith("*")
            wanted = str(expected).strip("*")
            objects = [
                obj
                for obj in objects
                if (
                    wanted in str(obj.props.get(key, ""))
                    if wildcard
                    else str(obj.props.get(key, "")) == wanted
                )
            ]
        return objects

    def get_object(self, permid):
        for objects in self.objects.values():
            for obj in objects:
                if str(obj.permId) == str(permid):
                    return obj
        raise ValueError(permid)


@pytest.fixture
def aiida_utils(monkeypatch):
    from src import utils

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, None))
    sys.modules.pop("src.aiida_utils", None)
    return importlib.import_module("src.aiida_utils")


def test_log_paths_are_anchored_to_app_root(aiida_utils):
    from src import utils

    expected_root = Path(utils.__file__).resolve().parent.parent
    assert utils.APP_ROOT == expected_root
    assert utils.LOG_DIR == expected_root / "logs"
    assert (
        utils.LOG_FILE_PATH == expected_root / "logs" / "aiidalab_openbis_interface.log"
    )


def make_calculation(label, inputs=None, outputs=None):
    return SimpleNamespace(
        label=label,
        inputs=SimpleNamespace(**(inputs or {})),
        outputs=SimpleNamespace(**(outputs or {})),
    )


def make_workchain(include_cell_optimization):
    scf_output_parameters = {
        "number_of_electrons": 12.0,
        "dft_exchange_correlation": "PBE",
        "lda_plus_u_calculation": False,
        "spin_orbit_calculation": False,
        "non_colinear_calculation": False,
        "lsda": True,
        "fermi_energy": -3.2,
    }
    scf = make_calculation(
        "scf",
        inputs={
            "parameters": FakeDict(
                {"SYSTEM": {"tot_charge": -1.0, "vdw_corr": "grimme-d3"}}
            )
        },
        outputs={"output_parameters": FakeDict(scf_output_parameters)},
    )
    bands = make_calculation(
        "bands", outputs={"output_band": SimpleNamespace(uuid="bands-uuid")}
    )
    export_pdos = make_calculation(
        "export_pdos", outputs={"Dos": SimpleNamespace(uuid="dos-uuid")}
    )
    descendants = [scf, bands, export_pdos]

    if include_cell_optimization:
        descendants.insert(
            0,
            make_calculation(
                "cell_opt2",
                inputs={
                    "parameters": FakeDict(
                        {
                            "CONTROL": {"forc_conv_thr": 0.0001},
                            "CELL": {"cell_dofree": "x"},
                        }
                    )
                },
                outputs={
                    "output_parameters": FakeDict(
                        {"energy": -272.11386245988, "energy_units": "eV"}
                    ),
                    "output_structure": SimpleNamespace(uuid="optimized-structure"),
                },
            ),
        )

    return SimpleNamespace(
        uuid="nanoribbon-uuid",
        description="A nanoribbon calculation with a long description",
        is_finished_ok=True,
        called_descendants=descendants,
        inputs=SimpleNamespace(structure=SimpleNamespace(uuid="input-structure")),
    )


def configure_export_mocks(monkeypatch, aiida_utils, workchain):
    created_objects = []
    previews = []
    structures = {}
    session = FakeSession()

    def create_openbis_object(_session, type, props, collection, parents=None):
        obj = FakeOpenbisObject(type, props)
        obj.collection = collection
        obj.parents = list(parents or [])
        created_objects.append(obj)
        session.objects.setdefault(type, []).append(obj)
        return obj

    def structure_to_atomistic_model(_session, structure_uuid, _uuids):
        return structures.setdefault(
            structure_uuid, FakeOpenbisObject(f"structure:{structure_uuid}")
        )

    monkeypatch.setattr(aiida_utils.orm, "load_node", lambda _uuid: workchain)
    monkeypatch.setattr(
        aiida_utils.utils, "create_openbis_object", create_openbis_object
    )
    monkeypatch.setattr(aiida_utils.utils, "update_openbis_object", lambda _obj: None)
    monkeypatch.setattr(
        aiida_utils, "structure_to_atomistic_model", structure_to_atomistic_model
    )
    monkeypatch.setattr(
        aiida_utils, "find_bandgap", lambda *_args, **_kwargs: (True, 1.2, -0.6, 0.6)
    )
    monkeypatch.setattr(
        aiida_utils,
        "_ensure_executables",
        lambda _session, _workchain: ["executable-pw", "executable-projwfc"],
    )
    monkeypatch.setattr(
        aiida_utils,
        "_upload_preview",
        lambda _session, obj, _renderer, stem: previews.append((obj, stem)),
    )
    return created_objects, previews, structures, session


def test_normalize_exported_objects(aiida_utils):
    first = object()
    second = object()

    assert aiida_utils.normalize_exported_objects(None) == ()
    assert aiida_utils.normalize_exported_objects(first) == (first,)
    assert aiida_utils.normalize_exported_objects([first, None, second]) == (
        first,
        second,
    )


def test_find_nanoribbon_calculations_reports_missing_nodes(aiida_utils):
    workchain = SimpleNamespace(
        uuid="missing-children",
        called_descendants=[make_calculation("scf")],
    )

    with pytest.raises(ValueError, match="bands, export_pdos"):
        aiida_utils._find_nanoribbon_calculations(workchain)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(-10.0, "Hartree", -10.0), (-272.11386245988, "eV", -10.0), (-20.0, "Ry", -10.0)],
)
def test_energy_is_normalized_to_hartree(aiida_utils, value, unit, expected):
    value_hartree = aiida_utils._energy_in_hartree(
        {"energy": value, "energy_units": unit}
    )
    assert isinstance(value_hartree, float)
    assert value_hartree == pytest.approx(expected)


def test_cp2k_method_uses_workflow_parameters(aiida_utils):
    parameters = aiida_utils.get_dft_parameters_cp2k(
        "CP2K", {"xc_functional": "PBE0", "hfx_fraction": 0.25, "vdw": True}
    )
    assert parameters["xc_functional"] == "PBE0"
    assert aiida_utils._method_modifiers(parameters) == ["HYBRID", "VDW"]
    assert aiida_utils._method_modifiers({"vdw_corr": "none"}) == []


def test_fermi_energy_matches_multivalue_schema(aiida_utils):
    quantities = aiida_utils._fermi_energy({"fermi_energy": -3.2})
    assert len(quantities) == 1
    assert quantities == [-3.2]
    assert aiida_utils._fermi_energy({}) is None


@pytest.mark.parametrize(
    ("arrays", "attributes", "expected"),
    [
        (("force_constants",), {}, "PHONONS"),
        (("force_constants", "born_charges"), {"dielectric": [[1.0]]}, "PHONONS_IR"),
        (("force_constants", "raman_tensors"), {}, "PHONONS_RAMAN"),
        (
            ("force_constants", "born_charges", "raman_tensors"),
            {"dielectric": [[1.0]]},
            "PHONONS_IR_RAMAN",
        ),
    ],
)
def test_qe_vibrational_mode_follows_single_vibro_workchain(
    aiida_utils, arrays, attributes, expected
):
    data = SimpleNamespace(
        get_arraynames=lambda: arrays,
        base=SimpleNamespace(attributes=SimpleNamespace(all=attributes)),
    )
    workchain = SimpleNamespace(
        outputs={"harmonic": {"vibrational_data": {"result": data}}}
    )

    assert aiida_utils._qe_vibrational_mode(workchain) == expected


def test_qe_relax_metadata_uses_final_forces_and_direct_ionic_steps(
    monkeypatch, aiida_utils
):
    trajectory = SimpleNamespace(
        get_array=lambda name: np.asarray(
            [
                [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]],
                [[0.003, 0.004, 0.0], [0.0, 0.0, 0.0]],
            ]
        )
        if name == "forces"
        else None
    )
    called = [
        SimpleNamespace(
            process_label="PwBaseWorkChain",
            outputs=SimpleNamespace(
                output_parameters=FakeDict({"number_ionic_steps": 2})
            ),
        ),
        SimpleNamespace(
            process_label="PwBaseWorkChain",
            outputs=SimpleNamespace(
                output_parameters=FakeDict({"number_ionic_steps": 0})
            ),
        ),
    ]
    workchain = SimpleNamespace(
        called=called,
        outputs=SimpleNamespace(
            output_trajectory=trajectory,
            output_band=SimpleNamespace(uuid="bands-uuid"),
        ),
    )
    monkeypatch.setattr(
        aiida_utils,
        "find_bandgap",
        lambda *_args, **_kwargs: (True, 0.47, 6.1, 6.57),
    )

    metadata = aiida_utils._qe_relax_metadata(
        workchain,
        {
            "forces_units": "eV / angstrom",
            "fermi_energy": 6.166,
            "number_of_electrons": 8.0,
            "total_magnetization": 0.0,
        },
    )

    assert metadata["final_max_force_hartree_per_bohr"] == pytest.approx(
        0.005 * aiida_utils.Bohr / aiida_utils.Hartree
    )
    assert metadata["number_of_steps"] == 2
    assert metadata["fermi_energy_ev"] == [6.166]
    assert metadata["electronic_gap_ev"] == [0.47]
    assert metadata["total_magnetization_bohr_magneton"] == 0.0


def test_unknown_method_label_is_omitted(aiida_utils):
    workchain = SimpleNamespace(
        uuid="workflow-uuid",
        description="",
        is_finished_ok=True,
        inputs=SimpleNamespace(),
    )

    properties = aiida_utils._simulation_properties(
        workchain, "Energy calculation", {"xc_functional": "unknown"}, None
    )

    assert "method_label" not in properties


def test_legacy_qe_mapping_and_namespace_compatibility(aiida_utils):
    legacy = SimpleNamespace(
        base=SimpleNamespace(attributes=SimpleNamespace(all={"value": 7}))
    )
    modern_scalar = SimpleNamespace(value=3)
    plain_value = "already-unwrapped"
    old_relax = SimpleNamespace(
        inputs=SimpleNamespace(base_relax=SimpleNamespace(pw="legacy-pw"))
    )

    assert aiida_utils._node_mapping(FakeDict({"value": 3})) == {"value": 3}
    assert aiida_utils._node_mapping(legacy) == {"value": 7}
    assert aiida_utils._node_value(modern_scalar) == 3
    assert aiida_utils._node_value(legacy) == 7
    assert aiida_utils._node_value(plain_value) == plain_value
    assert aiida_utils._pw_relax_base(old_relax).pw == "legacy-pw"


def test_bands_only_output_does_not_invent_pdos(aiida_utils):
    bands_only = SimpleNamespace(band_structure=object())
    with_pdos = SimpleNamespace(projwfc=SimpleNamespace(Dos="dos-node"))

    assert aiida_utils._bands_dos_node(bands_only) is None
    assert aiida_utils._bands_dos_node(with_pdos) == "dos-node"


def test_executables_require_confirmation_and_reuse_openbis_links(
    monkeypatch, aiida_utils
):
    computer = SimpleNamespace(
        uuid="computer-uuid",
        label="localhost",
        hostname="localhost",
        description="Empa MacBook Pro 7723 of Carlo Pignedoli",
    )
    code = SimpleNamespace(
        uuid="code-uuid",
        label="cp2k-2024.3",
        full_label="cp2k-2024.3@localhost",
        description="cp2k.psmp (2024.3) setup by AiiDAlab.",
        filepath_executable="/opt/cp2k/bin/cp2k.psmp",
        default_calc_job_plugin="cp2k",
        computer=computer,
    )
    software = FakeOpenbisObject("CODE", {"name": "CP2K"})
    openbis_computer = FakeOpenbisObject(
        "COMPUTER",
        {"name": "MacBook Pro 7723"},
    )
    objects = {
        "CODE": [software],
        "COMPUTER": [openbis_computer],
        "EXECUTABLE": [],
    }
    session = FakeSession(objects)

    def create_openbis_object(_session, type, props, collection, parents=None):
        obj = FakeOpenbisObject(type, props)
        obj.collection = collection
        objects[type].append(obj)
        return obj

    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: [code])
    monkeypatch.setattr(
        aiida_utils.utils,
        "get_openbis_objects",
        lambda _session, type: objects[type],
    )
    monkeypatch.setattr(
        aiida_utils.utils, "create_openbis_object", create_openbis_object
    )

    with pytest.raises(aiida_utils.MissingExecutablesError) as error:
        aiida_utils._ensure_executables(session, object())

    requirement = error.value.requirements[0]
    assert requirement["code_name"] == "CP2K"
    assert requirement["computer_name"] == "MacBook Pro 7723"
    assert requirement["version"] == "2024.3"
    assert objects["EXECUTABLE"] == []

    first = aiida_utils._ensure_executables(session, object(), create_missing=True)
    second = aiida_utils._ensure_executables(session, object())

    assert first == second
    assert len(objects["CODE"]) == 1
    assert len(objects["COMPUTER"]) == 1
    assert len(objects["EXECUTABLE"]) == 1
    executable = objects["EXECUTABLE"][0]
    assert executable.collection == aiida_utils.OPENBIS_COLLECTIONS_PATHS["Executable"]
    assert executable.props["code"] == software.permId
    assert executable.props["computer"] == openbis_computer.permId
    assert "AiiDA Code UUID: code-uuid" in executable.props["comments"]
    assert "AiiDA Computer UUID: computer-uuid" in executable.props["comments"]
    assert (
        "AiiDA executable path: /opt/cp2k/bin/cp2k.psmp" in executable.props["comments"]
    )
    assert "AiiDA plugin: cp2k" in executable.props["comments"]


@pytest.mark.parametrize(
    "plugin",
    (
        "quantumespresso.pw",
        "quantumespresso.pp",
        "quantumespresso.dos",
        "quantumespresso.projwfc",
        "quantumespresso.ph",
        "quantumespresso.q2r",
        "quantumespresso.matdyn",
        "quantumespresso.dynmat",
    ),
)
def test_qe_plugin_family_maps_to_quantum_espresso(plugin, aiida_utils):
    code = SimpleNamespace(
        label=f"{plugin.rpartition('.')[2]}-7.4",
        default_calc_job_plugin=plugin,
    )

    assert aiida_utils._software_search_names(code) == (
        "Quantum ESPRESSO",
        code.label,
    )


def test_qe_code_matches_software_suite(monkeypatch, aiida_utils):
    computer = SimpleNamespace(
        uuid="computer-uuid",
        label="localhost",
        description="Empa MacBook Pro 7723 of Carlo Pignedoli",
    )
    code = SimpleNamespace(
        uuid="code-uuid",
        label="pw-7.4",
        full_label="pw-7.4@localhost",
        description="Quantum ESPRESSO pw.x (7.4)",
        filepath_executable="/opt/qe/bin/pw.x",
        default_calc_job_plugin="quantumespresso.pw",
        computer=computer,
    )
    objects = {
        "CODE": [FakeOpenbisObject("CODE", {"name": "Quantum ESPRESSO"})],
        "COMPUTER": [FakeOpenbisObject("COMPUTER", {"name": "MacBook Pro 7723"})],
        "EXECUTABLE": [],
    }
    session = FakeSession(objects)
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: [code])
    monkeypatch.setattr(
        aiida_utils.utils,
        "get_openbis_objects",
        lambda _session, type: objects[type],
    )

    with pytest.raises(aiida_utils.MissingExecutablesError) as error:
        aiida_utils._ensure_executables(session, object())

    assert error.value.requirements[0]["code_name"] == "Quantum ESPRESSO"
    assert error.value.requirements[0]["properties"]["name"] == "pw-7.4"


def test_manual_code_and_computer_selection_override_failed_name_match(
    monkeypatch, aiida_utils
):
    computer = SimpleNamespace(
        uuid="computer-uuid",
        label="unmatched-computer",
        description="",
    )
    code = SimpleNamespace(
        uuid="code-uuid",
        label="pw-7.4",
        full_label="pw-7.4@localhost",
        description="Quantum ESPRESSO pw.x",
        filepath_executable="/opt/qe/bin/pw.x",
        default_calc_job_plugin="quantumespresso.pw",
        computer=computer,
    )
    software = FakeOpenbisObject("CODE", {"name": "Quantum ESPRESSO"})
    openbis_computer = FakeOpenbisObject("COMPUTER", {"name": "MacBook Pro 7723"})
    objects = {
        "CODE": [software],
        "COMPUTER": [openbis_computer],
        "EXECUTABLE": [],
    }
    session = FakeSession(objects)
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: [code])
    monkeypatch.setattr(
        aiida_utils.utils,
        "get_openbis_objects",
        lambda _session, type: objects[type],
    )

    with pytest.raises(aiida_utils.MissingExecutablesError) as error:
        aiida_utils._ensure_executables(
            session,
            object(),
            provenance_overrides={
                "Code": {"code-uuid": software.permId},
                "Computer": {
                    "computer-uuid": openbis_computer.permId,
                },
            },
        )

    assert error.value.requirements[0]["code_name"] == "Quantum ESPRESSO"


def test_manual_executable_selection_bypasses_name_matching(monkeypatch, aiida_utils):
    computer = SimpleNamespace(
        uuid="computer-uuid",
        label="unmatched-computer",
        description="",
    )
    code = SimpleNamespace(
        uuid="code-uuid",
        label="unmatched-code",
        full_label="unmatched-code@unmatched-computer",
        description="",
        filepath_executable="/opt/code",
        default_calc_job_plugin="custom.code",
        computer=computer,
    )
    executable = FakeOpenbisObject("EXECUTABLE", {"name": "Existing executable"})
    objects = {"CODE": [], "COMPUTER": [], "EXECUTABLE": [executable]}
    session = FakeSession(objects)
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: [code])
    monkeypatch.setattr(
        aiida_utils.utils,
        "get_openbis_objects",
        lambda _session, type: objects[type],
    )

    resolved = aiida_utils._ensure_executables(
        session,
        object(),
        provenance_overrides={
            "Executable": {"code-uuid": executable.permId},
        },
    )

    assert resolved == [executable.permId]


def test_failed_match_exposes_manual_resolution_context(monkeypatch, aiida_utils):
    computer = SimpleNamespace(
        uuid="computer-uuid",
        label="localhost",
        description="Empa MacBook Pro 7723",
    )
    code = SimpleNamespace(
        uuid="code-uuid",
        label="cubehandler",
        full_label="cubehandler@localhost",
        description="cubehandler from https://example.org/cubehandler",
        filepath_executable="/opt/cubehandler",
        default_calc_job_plugin="nanotech_empa.cubehandler",
        computer=computer,
    )
    software = FakeOpenbisObject("CODE", {"name": "CP2K"})
    objects = {
        "CODE": [software],
        "COMPUTER": [FakeOpenbisObject("COMPUTER", {"name": "MacBook Pro 7723"})],
        "EXECUTABLE": [],
    }
    session = FakeSession(objects)
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: [code])
    monkeypatch.setattr(
        aiida_utils.utils,
        "get_openbis_objects",
        lambda _session, type: objects[type],
    )

    with pytest.raises(aiida_utils.OpenbisNameMatchError) as error:
        aiida_utils._ensure_executables(session, object())

    assert error.value.object_kind == "Code"
    assert error.value.aiida_uuid == "code-uuid"
    assert error.value.aiida_label == "cubehandler"
    assert error.value.openbis_options == ((software.permId, "CP2K"),)


def test_name_matching_prefers_label_then_longest_name(aiida_utils):
    generic = FakeOpenbisObject("COMPUTER", {"name": "Daint"})
    specific = FakeOpenbisObject("COMPUTER", {"name": "daint@ALPS"})
    description_match = FakeOpenbisObject("COMPUTER", {"name": "MacBook Pro 7723"})

    matched = aiida_utils._match_named_openbis_object(
        "daint.alps_lp83",
        [generic, specific, description_match],
        "Computer",
        additional_names=("Empa MacBook Pro 7723",),
    )
    assert matched is specific


def test_name_matching_rejects_duplicate_best_matches(aiida_utils):
    first = FakeOpenbisObject("CODE", {"name": "CP2K"})
    duplicate = FakeOpenbisObject("CODE", {"name": "CP2K"})

    with pytest.raises(aiida_utils.OpenbisNameMatchError, match="ambiguously"):
        aiida_utils._match_named_openbis_object(
            "cp2k-2024.3", [first, duplicate], "Code"
        )


def test_export_workchain_preflights_before_archive(monkeypatch, aiida_utils):
    workchain = SimpleNamespace(
        uuid="workchain-uuid",
        pk=123,
        process_label="Cp2kGeoOptWorkChain",
        is_finished_ok=True,
    )
    monkeypatch.setattr(aiida_utils.orm, "load_node", lambda _uuid: workchain)
    monkeypatch.setattr(
        aiida_utils,
        "get_all_preceding_main_workchains",
        lambda _uuid: [workchain.uuid],
    )
    monkeypatch.setattr(
        aiida_utils,
        "get_uuids_from_oBIS",
        lambda _session: {"wc_uuids": [], "structure_uuids": []},
    )
    requirement = {
        "full_label": "cp2k@localhost",
        "properties": {},
    }

    def stop_at_preflight(
        _session,
        pending,
        create_missing=False,
        provenance_overrides=None,
    ):
        assert pending == [workchain]
        assert create_missing is False
        assert provenance_overrides is None
        raise aiida_utils.MissingExecutablesError([requirement])

    archives = []
    monkeypatch.setattr(
        aiida_utils, "_ensure_executables_for_workchains", stop_at_preflight
    )
    monkeypatch.setattr(
        aiida_utils,
        "create_and_export_AiiDA_archive",
        lambda *_args: archives.append(object()),
    )

    with pytest.raises(aiida_utils.MissingExecutablesError):
        aiida_utils.export_workchain(object(), "/PROJECT/EXPERIMENT", workchain.uuid)

    assert archives == []


def test_generated_archive_records_canonical_and_all_root_uuids(
    monkeypatch,
    aiida_utils,
):
    created = []
    datasets = []
    aiida_node = SimpleNamespace(permId="aiida-node-permid")

    monkeypatch.setattr(aiida_utils, "_objects_by_property", lambda *_args: [])

    def run(command, **kwargs):
        Path(command[3]).write_bytes(b"archive")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(aiida_utils.subprocess, "run", run)
    monkeypatch.setattr(
        aiida_utils.utils,
        "create_openbis_object",
        lambda session, **kwargs: created.append((session, kwargs)) or aiida_node,
    )
    monkeypatch.setattr(
        aiida_utils.utils,
        "create_openbis_dataset",
        lambda session, **kwargs: datasets.append((session, kwargs)),
    )

    result = aiida_utils.create_and_export_AiiDA_archive(
        "session",
        "11111111-1111-1111-1111-111111111111",
    )

    assert result is aiida_node
    assert created[0][1]["props"] == {
        "wfms_uuid": "11111111-1111-1111-1111-111111111111",
        "aiida_root_uuids": ["11111111-1111-1111-1111-111111111111"],
        "comments": "",
    }
    assert datasets[0][1]["sample"] is aiida_node


def test_export_workchain_passes_preflight_executables_to_exporter(
    monkeypatch, aiida_utils
):
    workchain = SimpleNamespace(
        uuid="workchain-uuid",
        pk=123,
        process_label="Cp2kGeoOptWorkChain",
        is_finished_ok=True,
    )
    resolved = {"code-uuid": "executable-permid"}
    monkeypatch.setattr(aiida_utils.orm, "load_node", lambda _uuid: workchain)
    monkeypatch.setattr(
        aiida_utils,
        "get_all_preceding_main_workchains",
        lambda _uuid: [workchain.uuid],
    )
    monkeypatch.setattr(
        aiida_utils,
        "get_uuids_from_oBIS",
        lambda _session: {"wc_uuids": [], "structure_uuids": []},
    )
    monkeypatch.setattr(
        aiida_utils,
        "_ensure_executables_for_workchains",
        lambda *_args, **_kwargs: resolved,
    )
    monkeypatch.setattr(
        aiida_utils,
        "create_and_export_AiiDA_archive",
        lambda *_args: SimpleNamespace(permId="archive-permid"),
    )
    exporter_calls = []

    def run_exporter(*args, **kwargs):
        exporter_calls.append((args, kwargs))
        return "exported"

    monkeypatch.setattr(aiida_utils, "_run_exporter", run_exporter)
    monkeypatch.setattr(
        aiida_utils, "record_openbis_exports", lambda *_args, **_kwargs: None
    )

    result = aiida_utils.export_workchain(
        object(), "/PROJECT/EXPERIMENT", workchain.uuid
    )

    assert result == ("exported",)
    args, kwargs = exporter_calls[0]
    assert args[-1] is resolved
    assert kwargs["preview_overrides"] is None


@pytest.mark.parametrize("include_cell_optimization", [False, True])
def test_nanoribbon_export_uses_simplified_schema(
    monkeypatch, aiida_utils, include_cell_optimization
):
    workchain = make_workchain(include_cell_optimization)
    created_objects, previews, structures, session = configure_export_mocks(
        monkeypatch, aiida_utils, workchain
    )

    geometry, bands, dos = aiida_utils.NanoribbonWorkChain_export(
        session,
        "/PROJECT/EXPERIMENT",
        workchain.uuid,
        [],
        "aiida-archive-permid",
    )

    assert bands.type == "BAND_STRUCTURE"
    assert dos.type == "DOS"
    assert bands.props["band_gap_ev"] == pytest.approx(1.2)
    assert dos.props["pdos"] is True
    assert dos.props["projection_description"]
    for simulation in (bands, dos):
        assert simulation.props["method_family"] == "DFT"
        assert simulation.props["method_label"] == "PBE"
        assert simulation.props["method_modifiers"] == ["VDW", "SPIN_COLLINEAR"]
        assert simulation.props["charge"] == -1.0
        assert simulation.props["converged"] is True
        assert simulation.props["comments"] == workchain.description
        assert simulation.props["aiida_node"] == "aiida-archive-permid"
        assert simulation.props["executables"] == [
            "executable-pw",
            "executable-projwfc",
        ]
        assert "input_parameters" not in simulation.props
        assert "output_parameters" not in simulation.props

    expected_structure = (
        "optimized-structure" if include_cell_optimization else "input-structure"
    )
    assert bands.parents == [structures[expected_structure]]
    assert dos.parents == [structures[expected_structure]]

    if include_cell_optimization:
        assert geometry.type == "GEOMETRY_OPTIMISATION"
        assert geometry.props["cell_optimization"] is True
        assert geometry.props["cell_constraints"] == "x"
        assert geometry.props["final_energy_hartree"] == pytest.approx(-10.0)
        assert geometry.props["aiida_node"] == "aiida-archive-permid"
        assert geometry.parents == [structures["input-structure"]]
        assert structures["optimized-structure"].parents == [geometry]
        assert geometry.children == [structures["optimized-structure"]]
        assert len(created_objects) == 3
        assert [stem for _, stem in previews] == [
            "band_structure",
            "pdos",
            "optimized_geometry",
        ]
    else:
        assert geometry is None
        assert len(created_objects) == 2
        assert [stem for _, stem in previews] == ["band_structure", "pdos"]


def test_simulation_identity_is_scoped_to_target_space(monkeypatch, aiida_utils):
    existing = FakeOpenbisObject(
        "DOS",
        {
            "name": "unused",
            "aiida_source_uuid": "source-uuid",
        },
    )
    existing.collection = "/SPACE/PROJECT/COLLECTION_A"
    session = FakeSession({"DOS": [existing]})
    rendered = []
    created = []

    def create(_session, type, props, collection, parents):
        obj = FakeOpenbisObject(type, props)
        obj.collection = collection
        obj.parents = list(parents)
        created.append(obj)
        return obj

    monkeypatch.setattr(aiida_utils.utils, "create_openbis_object", create)
    monkeypatch.setattr(
        aiida_utils,
        "_upload_preview",
        lambda *_args: rendered.append(True),
    )
    properties = {
        "name": "PDOS",
        "aiida_source_uuid": "source-uuid",
    }

    reused_in_same_space = aiida_utils._create_simulation_object(
        session,
        "/SPACE/OTHER_PROJECT/COLLECTION_B",
        "DOS",
        properties,
        [],
        object(),
        "pdos",
    )
    exported_to_different_space = aiida_utils._create_simulation_object(
        session,
        "/PRIVATE/PROJECT/COLLECTION",
        "DOS",
        properties,
        ["parent"],
        object(),
        "pdos",
    )

    assert reused_in_same_space is existing
    assert reused_in_same_space._aiidalab_created is False
    assert exported_to_different_space is created[0]
    assert exported_to_different_space._aiidalab_created is True
    assert exported_to_different_space.parents == ["parent"]
    assert rendered == [True]


def test_simulation_identity_resolves_collection_permid_to_space(aiida_utils):
    existing = FakeOpenbisObject(
        "SPM_SIMULATION",
        {
            "aiida_source_uuid": "source-uuid",
        },
    )
    queried_spaces = []

    class PermidCollectionSession:
        def get_collection(self, collection_id):
            assert collection_id == "collection-permid"
            return SimpleNamespace(
                project=SimpleNamespace(space=SimpleNamespace(code="SPACE"))
            )

        def get_objects(self, **kwargs):
            queried_spaces.append(kwargs["space"])
            return [existing]

    reused = aiida_utils._create_simulation_object(
        PermidCollectionSession(),
        "collection-permid",
        "SPM_SIMULATION",
        {
            "aiida_source_uuid": "source-uuid",
        },
        [],
        object(),
        "stm",
    )

    assert reused is existing
    assert reused._aiidalab_created is False
    assert queried_spaces == ["SPACE"]


def test_collection_space_code_accepts_collection_identifier(aiida_utils):
    class NoLookupSession:
        def get_collection(self, _collection_id):
            pytest.fail("collection identifiers do not require a server lookup")

    assert (
        aiida_utils._collection_space_code(
            NoLookupSession(), "/SPACE/PROJECT/COLLECTION"
        )
        == "SPACE"
    )


def test_record_openbis_exports_updates_structured_workchain_extra(
    monkeypatch, aiida_utils
):
    class Extras:
        def __init__(self):
            self.values = {}

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

    extras = Extras()
    source = SimpleNamespace(base=SimpleNamespace(extras=extras))
    monkeypatch.setattr(aiida_utils.orm, "load_node", lambda _uuid: source)
    result = FakeOpenbisObject(
        "DOS",
        {
            "aiida_source_uuid": "source-uuid",
        },
    )
    result.collection = "/SPACE/PROJECT/COLLECTION"
    session = FakeSession()

    aiida_utils.record_openbis_exports(session, [result])
    result.permId = "replacement-permid"
    aiida_utils.record_openbis_exports(session, [result])

    records = extras.values[aiida_utils.OPENBIS_EXPORTS_EXTRA]
    assert records == [
        {
            "server": "https://openbis.example",
            "collection": "/SPACE/PROJECT/COLLECTION",
            "object_type": "DOS",
            "result_role": "dos",
            "permid": "replacement-permid",
            "url": "",
        }
    ]


def test_upload_preview_content_uses_user_replacement(
    tmp_path, monkeypatch, aiida_utils
):
    uploaded = []

    def create_dataset(_session, **kwargs):
        path = Path(kwargs["files"][0])
        uploaded.append((kwargs["type"], path.suffix, path.read_bytes()))

    monkeypatch.setattr(aiida_utils.utils, "create_openbis_dataset", create_dataset)
    aiida_utils._upload_preview_content(
        object(),
        object(),
        lambda _path: pytest.fail("renderer should not run for a replacement"),
        "pdos",
        preview_override={"name": "chosen.jpg", "content": b"replacement"},
    )

    assert uploaded == [("ELN_PREVIEW", ".jpg", b"replacement")]


def test_render_workchain_preview_suggestions_reports_each_result(
    tmp_path, monkeypatch, aiida_utils
):
    root = SimpleNamespace(uuid="root-uuid")
    target = SimpleNamespace(uuid="target-uuid")

    def render(path):
        Path(path).write_bytes(b"suggested-png")

    monkeypatch.setattr(aiida_utils.orm, "load_node", lambda _uuid: root)
    monkeypatch.setattr(aiida_utils, "_exportable_workchains", lambda _wc: [target])
    monkeypatch.setattr(
        aiida_utils,
        "_preview_definitions",
        lambda _wc: [("pdos", "Projected DOS", "pdos", render)],
    )
    monkeypatch.setattr(
        aiida_utils,
        "_result_property_definitions",
        lambda _wc: {
            "pdos": {
                "object_type": "DOS",
                "properties": {"name": "PDOS result"},
            }
        },
    )

    suggestions = aiida_utils.render_workchain_preview_suggestions(root.uuid)

    assert suggestions == [
        {
            "key": "target-uuid:pdos",
            "source_uuid": "target-uuid",
            "result_role": "pdos",
            "title": "Projected DOS",
            "object_type": "DOS",
            "properties": {"name": "PDOS result"},
            "name": "pdos.png",
            "content": b"suggested-png",
            "error": None,
        }
    ]


def test_reviewed_properties_override_values_but_not_provenance(aiida_utils):
    workchain = SimpleNamespace(uuid="source-uuid")
    properties = {
        "name": "Automatic name",
        "comments": "Automatic comments",
        "projection_description": "Automatic projection",
        "aiida_node": "archive",
    }

    reviewed = aiida_utils._apply_property_overrides(
        properties,
        {
            "source-uuid:pdos": {
                "name": "Reviewed name",
                "comments": "Reviewed comments",
                "projection_description": None,
                "aiida_node": "not-allowed",
            }
        },
        workchain,
        "pdos",
    )

    assert reviewed["name"] == "Reviewed name"
    assert reviewed["comments"] == "Reviewed comments"
    assert "projection_description" not in reviewed
    assert reviewed["aiida_node"] == "archive"


def test_mark_export_result_bypasses_pybis_attribute_validation(aiida_utils):
    class PybisLikeObject:
        def __setattr__(self, name, value):
            raise ValueError(f"No such pyBIS attribute: {name}")

    obj = PybisLikeObject()
    result = aiida_utils._mark_export_result(obj, created=True)

    assert result is obj
    assert obj._aiidalab_created is True


def make_npz_bytes(**arrays):
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    return buffer.getvalue()


class FakeRepository:
    def __init__(self, text_files=None, object_names=None):
        self.text_files = dict(text_files or {})
        self.object_names = list(object_names or self.text_files)

    def open(self, filename, mode="r"):
        import io

        if filename not in self.text_files:
            raise FileNotFoundError(filename)
        value = self.text_files[filename]
        if "b" in mode:
            value = value if isinstance(value, bytes) else value.encode()
            return _ClosingBuffer(io.BytesIO(value))
        return _ClosingBuffer(io.StringIO(value))

    def list_object_names(self):
        return list(self.object_names)


class _ClosingBuffer:
    def __init__(self, buffer):
        self.buffer = buffer

    def __enter__(self):
        return self.buffer

    def __exit__(self, *_args):
        self.buffer.close()


def make_cp2k_scf_workchain(include_bader=True, include_unfolding=False):
    output_text = """
                     Mulliken Population Analysis
                           Hirshfeld Charges
 LOWDIN POPULATION ANALYSIS
 Fermi Energy [eV] :   -9.320618
 HOMO - LUMO gap [eV] :   11.176662
"""
    structure = SimpleNamespace(
        uuid="methane-structure",
        get_formula=lambda: "CH4",
    )
    outputs = {
        "output_parameters": FakeDict(
            {
                "dft_type": "RKS",
                "energy": -8.076608987239,
                "energy_units": "a.u.",
                "printed_bandgap_spin1_ev": 11.176662,
                "motion_step_info": {"scf_converged": [True]},
            }
        ),
        "retrieved": SimpleNamespace(
            base=SimpleNamespace(
                repository=FakeRepository({"aiida.out": output_text})
            )
        ),
    }
    if include_bader:
        outputs["bader_retrieved"] = SimpleNamespace(
            base=SimpleNamespace(
                repository=FakeRepository(object_names=["ACF.dat"])
            )
        )
    if include_unfolding:
        outputs["unfolding_retrieved"] = SimpleNamespace(
            base=SimpleNamespace(repository=FakeRepository(
                {
                    "unfolding_bands.npz": make_npz_bytes(
                        supercell_matrix=[[2, 0, 0], [0, 2, 0], [0, 0, 1]],
                        path_labels=["G", "K", "M", "G"],
                        path_k_indices=[0, 1],
                        path_x=[0.0, 1.0],
                        ref_energy_ev=-5.0,
                        evals_ev_spin_0=[-6.0, -4.0],
                        weights_spin_0=[[1.0, 0.2], [0.4, 0.8]],
                        x_ticks=[0.0, 1.0],
                        x_tick_labels=["G", "K"],
                    )
                }
            ))
        )
    return SimpleNamespace(
        uuid="cp2k-scf-uuid",
        process_label="Cp2kScfWorkChain",
        description="1001 test Bader charges",
        is_finished_ok=True,
        inputs=SimpleNamespace(
            structure=structure,
            cp2k_code=SimpleNamespace(description="CP2K"),
            dft_params=FakeDict(
                {"charge": 0, "multiplicity": 1, "uks": False, "vdw": True, "xc_functional": "PBE"}
            ),
            unfolding_path=SimpleNamespace(value="G-K-M-G"),
        ),
        outputs=SimpleNamespace(**outputs),
        called_descendants=[],
    )


def make_qe_banduppy_workchain():
    structure = SimpleNamespace(
        uuid="mos2-supercell",
        get_formula=lambda: "MoS2",
    )
    archive = make_npz_bytes(
        unfolded_bandstructure=[
            [0.0, 0.0, -4.0, 1.0],
            [0.0, 0.0, -2.0, 0.5],
            [1.0, 1.0, -3.5, 0.7],
            [1.0, 1.0, -2.5, 0.8],
        ],
        kline=[0.0, 1.0],
        special_labels=json.dumps({"0": "G", "1": "M"}),
        supercell_matrix=[[6, 0, 0], [0, 6, 0], [0, 0, 1]],
        fermi_energy=-3.0,
    )
    return SimpleNamespace(
        uuid="qe-banduppy-uuid",
        process_label="QeBanduppyUnfoldingWorkChain",
        description="charged MoS2 unfolding",
        is_finished_ok=True,
        inputs=SimpleNamespace(
            structure=structure,
            parameters=FakeDict(
                {"SYSTEM": {"tot_charge": -1.0, "vdw_corr": "grimme-d3"}}
            ),
            unfolding_parameters=FakeDict(
                {
                    "supercell_matrix": [[6, 0, 0], [0, 6, 0], [0, 0, 1]],
                    "labels": ["G", "M", "K", "G"],
                }
            ),
        ),
        outputs=SimpleNamespace(
            reference_bands_parameters=FakeDict(
                {
                    "dft_exchange_correlation": "PBE",
                    "lsda": True,
                    "non_colinear_calculation": False,
                }
            ),
            banduppy_retrieved=SimpleNamespace(
                base=SimpleNamespace(
                    repository=FakeRepository({"unfolding_bands.npz": archive})
                )
            ),
        ),
        called_descendants=[],
    )


def test_qe_banduppy_properties_use_common_unfolding_schema(aiida_utils):
    definition = aiida_utils._qe_banduppy_property_definition(
        make_qe_banduppy_workchain(),
        aiida_node_id="archive-permid",
        executable_ids=["pw-executable", "banduppy-executable"],
    )["band_unfolding"]

    properties = definition["properties"]
    assert definition["object_type"] == "BAND_UNFOLDING"
    assert properties["unfolding_implementation"] == "BANDUPPY"
    assert properties["charge"] == pytest.approx(-1.0)
    assert properties["method_modifiers"] == ["VDW", "SPIN_COLLINEAR"]
    assert json.loads(properties["supercell_matrix"]) == [
        [6, 0, 0],
        [0, 6, 0],
        [0, 0, 1],
    ]
    assert properties["k_path"] == "G-M-K-G"
    assert properties["fermi_energy_ev"] == pytest.approx([-3.0])
    assert properties["energy_min_ev"] == pytest.approx(-1.0)
    assert properties["energy_max_ev"] == pytest.approx(1.0)
    assert properties["executables"] == [
        "pw-executable",
        "banduppy-executable",
    ]


@pytest.mark.parametrize(
    "workchain",
    [
        make_cp2k_scf_workchain(include_bader=False, include_unfolding=True),
        make_qe_banduppy_workchain(),
    ],
)
def test_unfolding_preview_supports_cp2k_and_banduppy(
    aiida_utils, tmp_path, workchain
):
    output = tmp_path / f"{workchain.process_label}.png"
    aiida_utils._render_unfolding_preview(workchain, output)
    assert output.is_file()
    assert output.stat().st_size > 0


def test_qe_banduppy_export_uses_input_supercell_as_parent(
    monkeypatch, aiida_utils
):
    workchain = make_qe_banduppy_workchain()
    created, previews, structures, session = configure_export_mocks(
        monkeypatch, aiida_utils, workchain
    )

    result = aiida_utils.QeBanduppyUnfoldingWorkChain_export(
        session,
        "/PROJECT/EXPERIMENT",
        workchain.uuid,
        [],
        "archive-permid",
        executable_ids=["pw-executable", "banduppy-executable"],
    )

    assert [obj.type for obj in created] == ["BAND_UNFOLDING"]
    assert result.parents == [structures["mos2-supercell"]]
    assert result.props["aiida_node"] == "archive-permid"
    assert [stem for _obj, stem in previews] == ["band_unfolding"]


def test_cp2k_fermi_and_gap_values_preserve_spin_channels(aiida_utils):
    output = """
 Fermi Energy [eV] :   -5.169447
 Fermi Energy [eV] :   -5.145157
"""
    parameters = {
        "dft_type": "UKS",
        "bandgap_spin1_au": 0.1,
        "bandgap_spin2_au": 0.2,
    }

    assert aiida_utils._cp2k_fermi_energies(parameters, output) == [
        -5.169447,
        -5.145157,
    ]
    assert aiida_utils._cp2k_electronic_gaps(parameters) == pytest.approx(
        [0.1 * aiida_utils.Hartree, 0.2 * aiida_utils.Hartree]
    )


def test_cp2k_scf_properties_detect_real_charge_outputs(
    monkeypatch, aiida_utils
):
    workchain = make_cp2k_scf_workchain()
    codes = [
        SimpleNamespace(label="bader", full_label="bader@localhost"),
        SimpleNamespace(label="cp2k", full_label="cp2k@localhost"),
    ]
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: codes)

    definitions = aiida_utils._cp2k_scf_property_definitions(
        workchain,
        aiida_node_id="archive-permid",
        executable_ids=["bader-executable", "cp2k-executable"],
    )

    assert list(definitions) == ["energy_calculation", "charge_analysis"]
    energy = definitions["energy_calculation"]["properties"]
    charge = definitions["charge_analysis"]["properties"]
    assert energy["name"].startswith("Energy calculation CH4")
    assert energy["total_energy_hartree"] == pytest.approx(-8.076608987239)
    assert energy["fermi_energy_ev"] == pytest.approx([-9.320618])
    assert energy["electronic_gap_ev"] == pytest.approx([11.176662])
    assert energy["executables"] == ["cp2k-executable"]
    assert energy["converged"] is True
    assert charge["charge_analysis_method"] == (
        "Mulliken; Hirshfeld; Löwdin; Bader"
    )
    assert charge["executables"] == ["cp2k-executable", "bader-executable"]
    assert charge["aiida_node"] == "archive-permid"
    assert "total_energy_hartree" not in charge


def test_cp2k_scf_properties_add_unfolding_band_without_duplicate_arrays(
    monkeypatch, aiida_utils
):
    workchain = make_cp2k_scf_workchain(
        include_bader=False, include_unfolding=True
    )
    codes = [
        SimpleNamespace(label="cp2k", full_label="cp2k@localhost"),
        SimpleNamespace(label="cp2k-unfolding", full_label="cp2k-unfolding@localhost"),
    ]
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: codes)

    definitions = aiida_utils._cp2k_scf_property_definitions(
        workchain,
        aiida_node_id="archive-permid",
        executable_ids=["cp2k-executable", "unfolding-executable"],
    )

    definition = definitions["band_unfolding"]
    band = definition["properties"]
    assert definition["object_type"] == "BAND_UNFOLDING"
    assert band["unfolding_implementation"] == "CP2K_SPARSE_AO"
    assert band["spin_multiplicity"] == 1
    assert json.loads(band["supercell_matrix"]) == [
        [2, 0, 0],
        [0, 2, 0],
        [0, 0, 1],
    ]
    assert band["k_path"] == "G-K-M-G"
    assert band["fermi_energy_ev"] == pytest.approx([-9.320618])
    assert band["energy_min_ev"] == pytest.approx(-1.0)
    assert band["energy_max_ev"] == pytest.approx(1.0)
    assert band["executables"] == [
        "cp2k-executable",
        "unfolding-executable",
    ]
    assert "unfolding_bands" not in band
    assert "unfolding_projections" not in band


def test_cp2k_scf_export_links_charge_to_structure_and_energy(
    monkeypatch, aiida_utils
):
    workchain = make_cp2k_scf_workchain()
    codes = [
        SimpleNamespace(label="bader", full_label="bader@localhost"),
        SimpleNamespace(label="cp2k", full_label="cp2k@localhost"),
    ]
    monkeypatch.setattr(aiida_utils, "_workchain_codes", lambda _workchain: codes)
    created, previews, structures, session = configure_export_mocks(
        monkeypatch, aiida_utils, workchain
    )

    energy, charge = aiida_utils.Cp2kScfWorkChain_export(
        session,
        "/PROJECT/EXPERIMENT",
        workchain.uuid,
        [],
        "archive-permid",
        executable_ids=["bader-executable", "cp2k-executable"],
    )

    assert [obj.type for obj in created] == [
        "ENERGY_CALCULATION",
        "CHARGE_ANALYSIS",
    ]
    assert energy.parents == [structures["methane-structure"]]
    assert charge.parents == [structures["methane-structure"], energy]
    assert "aiida_result_role" not in charge.props
    assert charge._aiidalab_result_role == "charge_analysis"
    assert [stem for _, stem in previews] == [
        "energy_calculation",
        "charge_analysis",
    ]


class FakeArray:
    def __init__(self, **arrays):
        self.arrays = arrays

    def get_array(self, name):
        return self.arrays[name]


def _mep_structure(uuid):
    return SimpleNamespace(uuid=uuid, get_formula=lambda: "CH4")


def _mep_inputs(**extra):
    values = {
        "code": SimpleNamespace(description="CP2K"),
        "dft_params": FakeDict(
            {"charge": 0, "vdw": True, "xc_functional": "PBE"}
        ),
        "sys_params": FakeDict(
            {
                "colvars": "distance atoms 1 2",
                "colvars_targets": [1.2],
                "colvars_increments": [0.05],
                "constraints": (
                    "collective 1 [eV/angstrom^2] 40 [angstrom] 1.095"
                ),
            }
        ),
    }
    values.update(extra)
    return SimpleNamespace(**values)


def test_replica_chain_mep_properties(aiida_utils):
    structures = {
        "initial_scf": _mep_structure("initial"),
        "step_0001": _mep_structure("middle"),
        "step_0002": _mep_structure("final"),
    }
    details = {
        "initial_scf": FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -8.076609,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.095],
            }
        ),
        "step_0001": FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -8.075873,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.132],
            }
        ),
        "step_0002": FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -8.073712,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.171],
            }
        ),
    }
    workchain = SimpleNamespace(
        uuid="replica-uuid",
        process_label="Cp2kReplicaWorkChain",
        description="1001 gas phase replica chain",
        is_finished_ok=True,
        inputs=_mep_inputs(structure=structures["initial_scf"]),
        outputs=SimpleNamespace(
            structures=SimpleNamespace(**structures),
            details=SimpleNamespace(**details),
        ),
    )

    definition = aiida_utils._cp2k_mep_property_definition(workchain)[
        "minimum_energy_path"
    ]
    properties = definition["properties"]

    assert definition["object_type"] == "MINIMUM_ENERGY_PATH"
    assert properties["mep_method"] == "REPLICA_CHAIN"
    assert properties["relative_energies_ev"][0] == pytest.approx(0.0)
    assert properties["forward_barrier_ev"] == pytest.approx(
        (8.076609 - 8.073712) * aiida_utils.Hartree
    )
    assert properties["backward_barrier_ev"] == pytest.approx(0.0)
    assert properties["number_of_images"] == 3
    assert '"actual_values"' in properties["collective_variables"]
    assert properties["constraints_description"].startswith("collective 1")


def test_neb_mep_properties_and_endpoints(monkeypatch, aiida_utils):
    initial = _mep_structure("initial")
    final = _mep_structure("final")
    workchain = SimpleNamespace(
        uuid="neb-uuid",
        process_label="Cp2kNebWorkChain",
        description="1001 gas phase CI-NEB",
        is_finished_ok=True,
        inputs=_mep_inputs(
            structure=initial,
            replicas=SimpleNamespace(replica_001=final),
            neb_params=FakeDict({"band_type": "CI-NEB"}),
        ),
        outputs=SimpleNamespace(
            replica_energies=FakeArray(
                energies=[
                    [-8.0, -7.9, -7.8, -7.7],
                    [-8.076609, -8.076211, -8.076182, -8.073712],
                ]
            ),
            replica_distances=FakeArray(
                distances=[
                    [0.0, 0.2, 0.2, 0.2],
                    [0.0, 0.1, 0.2, 0.3],
                ]
            ),
        ),
    )

    definition = aiida_utils._cp2k_mep_property_definition(workchain)[
        "minimum_energy_path"
    ]
    properties = definition["properties"]
    endpoints = aiida_utils._neb_input_endpoints(workchain)

    assert endpoints == (initial, final)
    assert properties["mep_method"] == "NEB"
    assert properties["neb_variant"] == "CI_NEB"
    assert properties["relative_energies_ev"] == pytest.approx(
        [
            0.0,
            0.000398 * aiida_utils.Hartree,
            0.000427 * aiida_utils.Hartree,
            0.002897 * aiida_utils.Hartree,
        ]
    )
    assert properties["forward_barrier_ev"] == pytest.approx(
        0.002897 * aiida_utils.Hartree
    )
    assert properties["backward_barrier_ev"] == pytest.approx(0.0)


def test_replica_chain_export_links_only_endpoints_and_preceding_mep(
    monkeypatch, aiida_utils
):
    initial = _mep_structure("initial")
    middle = _mep_structure("middle")
    final = _mep_structure("final")
    details = SimpleNamespace(
        initial_scf=FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -8.0,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.0],
            }
        ),
        step_0001=FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -7.9,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.1],
            }
        ),
        step_0002=FakeDict(
            {
                "output_parameters": {
                    "energy_scf": -7.8,
                    "energy_units": "a.u.",
                },
                "cvs_actual": [1.2],
            }
        ),
    )
    workchain = SimpleNamespace(
        uuid="replica-export-uuid",
        process_label="Cp2kReplicaWorkChain",
        description="replica export",
        is_finished_ok=True,
        inputs=_mep_inputs(structure=initial),
        outputs=SimpleNamespace(
            details=details,
            structures=SimpleNamespace(
                initial_scf=initial,
                step_0001=middle,
                step_0002=final,
            ),
        ),
    )
    created, _previews, structures, session = configure_export_mocks(
        monkeypatch, aiida_utils, workchain
    )
    predecessor = FakeOpenbisObject("MINIMUM_ENERGY_PATH")
    monkeypatch.setattr(
        aiida_utils,
        "_preceding_mep_objects",
        lambda *_args: [predecessor],
    )

    exported = aiida_utils.Cp2kMepWorkChain_export(
        session,
        "/SPACE/PROJECT/COLLECTION",
        workchain.uuid,
        [],
        "archive-permid",
        executable_ids=["cp2k-executable"],
    )

    assert exported is created[0]
    assert exported.parents == [structures["initial"], structures["final"], predecessor]
    assert "aiida_result_role" not in exported.props
    assert exported._aiidalab_result_role == "minimum_energy_path"
