import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

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
    assert aiida_utils._method_modifiers(parameters) == ["hybrid", "vdW"]
    assert aiida_utils._method_modifiers({"vdw_corr": "none"}) == []


def test_fermi_energy_matches_multivalue_schema(aiida_utils):
    quantities = aiida_utils._fermi_energy({"fermi_energy": -3.2})
    assert len(quantities) == 1
    assert quantities == [-3.2]
    assert aiida_utils._fermi_energy({}) is None


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


def test_code_matching_is_strictly_label_based(monkeypatch, aiida_utils):
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

    with pytest.raises(aiida_utils.OpenbisNameMatchError, match="pw-7.4"):
        aiida_utils._ensure_executables(session, object())


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
        assert simulation.props["method_modifiers"] == ["vdW", "spin_collinear"]
        assert simulation.props["charge"] == -1.0
        assert simulation.props["converged"] is True
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
            "aiida_result_role": "pdos",
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
        "aiida_result_role": "pdos",
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
            "aiida_result_role": "stm",
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
            "aiida_result_role": "stm",
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
            "aiida_result_role": "pdos",
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
            "result_role": "pdos",
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

    suggestions = aiida_utils.render_workchain_preview_suggestions(root.uuid)

    assert suggestions == [
        {
            "key": "target-uuid:pdos",
            "source_uuid": "target-uuid",
            "result_role": "pdos",
            "title": "Projected DOS",
            "name": "pdos.png",
            "content": b"suggested-png",
            "error": None,
        }
    ]


def test_mark_export_result_bypasses_pybis_attribute_validation(aiida_utils):
    class PybisLikeObject:
        def __setattr__(self, name, value):
            raise ValueError(f"No such pyBIS attribute: {name}")

    obj = PybisLikeObject()
    result = aiida_utils._mark_export_result(obj, created=True)

    assert result is obj
    assert obj._aiidalab_created is True
