import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def simulations_widgets(monkeypatch):
    from src import utils

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, None))
    monkeypatch.setattr(
        utils,
        "get_interface_config_info",
        lambda: {
            "object_types": {},
            "object_types_codes": {},
            "slabs_concepts_types": {},
            "instruments_types": {},
        },
    )
    sys.modules.pop("src.aiida_utils", None)
    sys.modules.pop("src.widgets", None)
    sys.modules.pop("src.simulations_widgets", None)
    return importlib.import_module("src.simulations_widgets")


@pytest.mark.parametrize("selection", [None, "", "-1"])
def test_export_requires_experiment_selection(
    monkeypatch, simulations_widgets, selection
):
    messages = []
    monkeypatch.setattr(simulations_widgets, "_popup", messages.append)
    widget = SimpleNamespace(
        select_experiment_widget=SimpleNamespace(
            experiment_dropdown=SimpleNamespace(value=selection)
        )
    )

    simulations_widgets.ExportSimulationsWidget.export_simulation_to_openbis(
        widget, None
    )

    assert messages == ["Select an experiment before exporting."]


def test_resolution_options_include_existing_and_create(simulations_widgets):
    options = simulations_widgets.ExportSimulationsWidget._resolution_options(
        (("perm-2", "Zulu"), ("perm-1", "Alpha")),
        "Create new",
    )

    assert options == [
        ("Select an existing object...", ""),
        ("Alpha (perm-1)", "perm-1"),
        ("Zulu (perm-2)", "perm-2"),
        ("Create new", simulations_widgets._CREATE_NEW),
    ]


def test_existing_reference_selection_is_stored_by_aiida_uuid(
    simulations_widgets,
):
    widget = SimpleNamespace(
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Code",
            "aiida_uuid": "code-uuid",
            "selector": SimpleNamespace(value="code-permid"),
        },
        provenance_resolution_box=SimpleNamespace(children=["visible"]),
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is True
    assert widget._provenance_overrides["Code"] == {"code-uuid": "code-permid"}
    assert widget._pending_reference_resolution is None
    assert widget.provenance_resolution_box.children == []


def test_existing_executable_selection_is_stored_by_code_uuid(
    simulations_widgets,
):
    widget = SimpleNamespace(
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _executable_selection_widgets={
            "code-uuid": SimpleNamespace(value="executable-permid"),
            "create-code-uuid": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
        },
    )

    applied, create_missing = (
        simulations_widgets.ExportSimulationsWidget._apply_executable_selections(widget)
    )

    assert applied is True
    assert create_missing is True
    assert widget._provenance_overrides["Executable"] == {
        "code-uuid": "executable-permid"
    }


def test_create_new_code_stores_override(monkeypatch, simulations_widgets):
    created = []

    def create_openbis_object(_session, type, props, collection):
        created.append((type, props, collection))
        return SimpleNamespace(permId="new-code-permid")

    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_object",
        create_openbis_object,
    )
    widget = SimpleNamespace(
        openbis_session=SimpleNamespace(get_objects=lambda **_kwargs: []),
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Code",
            "aiida_uuid": "code-uuid",
            "selector": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
            "name": SimpleNamespace(value="cubehandler"),
            "description": SimpleNamespace(value="Cube handler utility"),
            "url": SimpleNamespace(value="https://example.org/cubehandler"),
            "collection": SimpleNamespace(value="/CODE/COLLECTION"),
            "location": None,
            "status": SimpleNamespace(value=""),
        },
        provenance_resolution_box=SimpleNamespace(children=["visible"]),
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is True
    assert created == [
        (
            "CODE",
            {
                "name": "cubehandler",
                "description": "Cube handler utility",
                "url": "https://example.org/cubehandler",
            },
            "/CODE/COLLECTION",
        )
    ]
    assert widget._provenance_overrides["Code"] == {"code-uuid": "new-code-permid"}


def test_create_new_computer_requires_location(monkeypatch, simulations_widgets):
    creations = []
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_object",
        lambda *_args, **kwargs: creations.append(kwargs),
    )
    status = SimpleNamespace(value="")
    widget = SimpleNamespace(
        openbis_session=SimpleNamespace(get_objects=lambda **_kwargs: []),
        _provenance_overrides={
            "Code": {},
            "Computer": {},
            "Executable": {},
        },
        _pending_reference_resolution={
            "kind": "Computer",
            "aiida_uuid": "computer-uuid",
            "selector": SimpleNamespace(value=simulations_widgets._CREATE_NEW),
            "name": SimpleNamespace(value="new-computer"),
            "description": SimpleNamespace(value="A new computer"),
            "url": None,
            "collection": SimpleNamespace(value="/COMPUTERS/LOCAL"),
            "location": SimpleNamespace(value=""),
            "status": status,
        },
    )

    applied = (
        simulations_widgets.ExportSimulationsWidget._apply_pending_reference_resolution(
            widget
        )
    )

    assert applied is False
    assert "location is required" in status.value
    assert creations == []


def _simulation(
    name,
    permid,
    type_code,
    aiida_node=None,
    datasets=None,
    comments="",
    registration_date="",
):
    return SimpleNamespace(
        props={
            "name": name,
            "comments": comments,
            "aiida_node": aiida_node,
        },
        permId=permid,
        type=SimpleNamespace(code=type_code),
        registrationDate=registration_date,
        get_datasets=lambda: list(datasets or []),
    )


def test_fuzzy_matching_tolerates_typos_and_extra_words(simulations_widgets):
    score = simulations_widgets.ImportSimulationsWidget._fuzzy_score(
        "this is a god pearr",
        "very good pear",
    )

    assert score >= simulations_widgets._FUZZY_MATCH_THRESHOLD


def test_contains_all_words_is_case_insensitive_and_order_independent(
    simulations_widgets,
):
    matches, score = simulations_widgets.ImportSimulationsWidget._text_matches(
        "EXPORT Test",
        "This is the test export result",
        "all_words",
    )
    missing, _ = simulations_widgets.ImportSimulationsWidget._text_matches(
        "export geometry",
        "This is the test export result",
        "all_words",
    )

    assert matches is True
    assert score == 100
    assert missing is False


def test_simulation_filter_combines_text_type_and_archive_status(
    simulations_widgets,
):
    data_only = _simulation(
        "test export",
        "simulation-1",
        "GEOMETRY_OPTIMISATION",
        comments="A very good pear calculation",
    )
    archived = _simulation(
        "test archive",
        "simulation-2",
        "GEOMETRY_OPTIMISATION",
        aiida_node="archive-1",
        comments="A very good pear calculation",
    )
    wrong_type = _simulation(
        "test export",
        "simulation-3",
        "DOS",
        comments="A very good pear calculation",
    )

    filtered, scores = simulations_widgets.ImportSimulationsWidget._filter_simulations(
        [data_only, archived, wrong_type],
        name_query="tset exprt",
        comments_query="god pearr",
        match_mode="fuzzy",
        simulation_type="GEOMETRY_OPTIMISATION",
        archive_status="data_only",
    )

    assert filtered == [data_only]
    assert scores["simulation-1"] >= simulations_widgets._FUZZY_MATCH_THRESHOLD


def test_material_match_all_and_any_have_explicit_set_semantics(
    simulations_widgets,
):
    combine = simulations_widgets.ImportSimulationsWidget._combine_simulation_permids
    material_results = [
        {"simulation-1", "simulation-2"},
        {"simulation-2", "simulation-3"},
    ]

    assert combine(material_results, "AND") == {"simulation-2"}
    assert combine(material_results, "OR") == {
        "simulation-1",
        "simulation-2",
        "simulation-3",
    }


def test_search_without_material_filters_searches_all_simulation_types(
    monkeypatch,
    simulations_widgets,
):
    target = _simulation(
        "test export",
        "simulation-1",
        "GEOMETRY_OPTIMISATION",
        comments="Manually uploaded geometry",
        registration_date="2026-09-08 06:38:37",
    )
    queried_types = []

    def get_objects(_session, type):
        queried_types.append(type)
        return [target] if type == "GEOMETRY_OPTIMISATION" else []

    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        get_objects,
    )
    widget = simulations_widgets.ImportSimulationsWidget(object())
    widget.name_search_text.value = "tset exprt"

    widget.search_simulations()

    assert set(queried_types) == set(simulations_widgets.SIMULATION_TYPES.values())
    assert [
        value for _label, value in widget.found_simulations_select_multiple.options
    ] == ["simulation-1"]
    assert "% match" in widget.found_simulations_select_multiple.options[0][0]
    assert widget.found_simulations_label.value == "Found simulations: 1"


@pytest.mark.parametrize(
    ("material_count", "disabled", "message"),
    [
        (0, True, "all simulations are searched"),
        (1, True, "One material filter selected"),
        (2, False, "All requires every selected material"),
    ],
)
def test_material_match_control_explains_when_all_any_applies(
    simulations_widgets,
    material_count,
    disabled,
    message,
):
    widget = SimpleNamespace(
        _selected_parent_permids=lambda: ["material"] * material_count,
        search_logical_operator_dropdown=SimpleNamespace(disabled=None),
        search_operator_help=SimpleNamespace(value=""),
    )

    simulations_widgets.ImportSimulationsWidget._update_material_match_controls(widget)

    assert widget.search_logical_operator_dropdown.disabled is disabled
    assert message in widget.search_operator_help.value


def test_action_buttons_follow_selected_archive_availability(simulations_widgets):
    widget = SimpleNamespace(
        found_simulations_select_multiple=SimpleNamespace(value=("data-only",)),
        _simulation_archive_by_permid={
            "data-only": False,
            "archived": True,
        },
        import_simulations_button=SimpleNamespace(disabled=None),
        download_simulation_data_button=SimpleNamespace(disabled=None),
    )

    simulations_widgets.ImportSimulationsWidget._update_action_buttons(widget)

    assert widget.import_simulations_button.disabled is True
    assert widget.download_simulation_data_button.disabled is False

    widget.found_simulations_select_multiple.value = ("data-only", "archived")
    simulations_widgets.ImportSimulationsWidget._update_action_buttons(widget)

    assert widget.import_simulations_button.disabled is False
    assert widget.download_simulation_data_button.disabled is False


def test_simulation_options_use_unique_simulation_permids(simulations_widgets):
    archived = _simulation(
        "Unclassified archive",
        "simulation-2",
        "UNCLASSIFIED_SIMULATION",
        aiida_node="archive-1",
    )
    data_only = _simulation(
        "Manual result",
        "simulation-1",
        "UNCLASSIFIED_SIMULATION",
    )

    options = simulations_widgets.ImportSimulationsWidget._simulation_options(
        [archived, data_only]
    )

    assert [value for _label, value in options] == [
        "simulation-1",
        "simulation-2",
    ]
    assert "[data only]" in options[0][0]
    assert "[AiiDA archive]" in options[1][0]


def test_partition_simulations_deduplicates_shared_archive(simulations_widgets):
    geometry = _simulation(
        "Geometry",
        "simulation-1",
        "GEOMETRY_OPTIMISATION",
        aiida_node="archive-1",
    )
    unclassified = _simulation(
        "Unclassified",
        "simulation-2",
        "UNCLASSIFIED_SIMULATION",
        aiida_node="archive-1",
    )
    data_only = _simulation(
        "Manual result",
        "simulation-3",
        "UNCLASSIFIED_SIMULATION",
    )

    archives, without_archive = (
        simulations_widgets.ImportSimulationsWidget._partition_simulations_by_archive(
            [geometry, unclassified, data_only]
        )
    )

    assert archives == {"archive-1": [geometry, unclassified]}
    assert without_archive == [data_only]


def test_import_selected_simulations_imports_each_archive_once(
    monkeypatch,
    simulations_widgets,
):
    geometry = _simulation(
        "Geometry",
        "simulation-1",
        "GEOMETRY_OPTIMISATION",
        aiida_node="archive-1",
    )
    unclassified = _simulation(
        "Unclassified",
        "simulation-2",
        "UNCLASSIFIED_SIMULATION",
        aiida_node="archive-1",
    )
    data_only = _simulation(
        "Manual result",
        "simulation-3",
        "UNCLASSIFIED_SIMULATION",
    )
    imported = []
    workchain = SimpleNamespace(
        process_label="UnmappedWorkChain",
        pk=42,
        uuid="workflow-uuid",
    )
    monkeypatch.setattr(simulations_widgets, "WORKCHAIN_VIEWERS", {})
    popups = []
    monkeypatch.setattr(simulations_widgets, "_popup", popups.append)
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "record_openbis_exports",
        lambda *_args, **_kwargs: None,
    )

    widget = SimpleNamespace(
        openbis_session=object(),
        _selected_simulation_objects=lambda: [
            geometry,
            unclassified,
            data_only,
        ],
        _partition_simulations_by_archive=(
            simulations_widgets.ImportSimulationsWidget._partition_simulations_by_archive
        ),
        _simulation_names=(
            simulations_widgets.ImportSimulationsWidget._simulation_names
        ),
        _import_aiida_archive=lambda archive_id: (
            imported.append(archive_id) or (workchain,)
        ),
        _import_success_message=(
            simulations_widgets.ImportSimulationsWidget._import_success_message
        ),
        import_simulations_message_html=SimpleNamespace(value=""),
    )

    simulations_widgets.ImportSimulationsWidget.import_aiida_nodes(
        widget,
        None,
    )

    assert imported == ["archive-1"]
    assert "Geometry, Unclassified" in widget.import_simulations_message_html.value
    assert "No viewer is configured for UnmappedWorkChain" in (
        widget.import_simulations_message_html.value
    )
    assert "Manual result has no linked AiiDA archive" in popups[0]


def test_find_aiida_archive_dataset_requires_exactly_one_archive(
    simulations_widgets,
):
    archive_dataset = SimpleNamespace(
        file_list=["original/archive.aiida"],
    )
    preview_dataset = SimpleNamespace(
        file_list=["original/preview.png"],
    )
    aiida_node = SimpleNamespace(
        get_datasets=lambda: [preview_dataset, archive_dataset]
    )

    dataset, filename = (
        simulations_widgets.ImportSimulationsWidget._find_aiida_archive_dataset(
            aiida_node
        )
    )

    assert dataset is archive_dataset
    assert filename == "original/archive.aiida"

    aiida_node.get_datasets = list
    with pytest.raises(ValueError, match="no .aiida archive"):
        (
            simulations_widgets.ImportSimulationsWidget._find_aiida_archive_dataset(
                aiida_node
            )
        )


def test_import_aiida_archive_uses_temporary_download(
    monkeypatch,
    simulations_widgets,
):
    destinations = []

    class ArchiveDataset:
        permId = "dataset-1"
        file_list = ("original/archive.aiida",)

        def download(self, files, destination):
            destinations.append(Path(destination))
            archive = Path(destination) / self.permId / "original" / "archive.aiida"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"archive")

    dataset = ArchiveDataset()
    aiida_node = SimpleNamespace(
        props={"wfms_uuid": "workflow-uuid"},
        get_datasets=lambda: [dataset],
    )
    workchain = object()

    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_object",
        lambda *_args, **_kwargs: aiida_node,
    )
    monkeypatch.setattr(
        simulations_widgets,
        "_archive_root_processes",
        lambda _path: (
            {
                "uuid": "workflow-uuid",
                "process_label": "TestWorkChain",
            },
        ),
    )

    def run(command, **kwargs):
        assert command[:3] == ["verdi", "archive", "import"]
        assert Path(command[3]).is_file()
        assert kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(simulations_widgets.subprocess, "run", run)
    monkeypatch.setattr(
        simulations_widgets.orm,
        "load_node",
        lambda uuid: workchain if uuid == "workflow-uuid" else None,
    )
    widget = SimpleNamespace(
        openbis_session=object(),
        _find_aiida_archive_dataset=(
            simulations_widgets.ImportSimulationsWidget._find_aiida_archive_dataset
        ),
        _downloaded_dataset_path=(
            simulations_widgets.ImportSimulationsWidget._downloaded_dataset_path
        ),
    )

    result = simulations_widgets.ImportSimulationsWidget._import_aiida_archive(
        widget,
        "archive-1",
    )

    assert result == (workchain,)
    assert len(destinations) == 1
    assert not destinations[0].exists()


def test_declared_archive_roots_support_single_and_multiple_records(
    simulations_widgets,
):
    aiida_node = SimpleNamespace(
        props={
            "wfms_uuid": "11111111-1111-1111-1111-111111111111",
            "aiida_root_uuids": [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
            ],
            "comments": (
                "AiiDA root process UUID: "
                "11111111-1111-1111-1111-111111111111\n"
                "AiiDA root process UUID: "
                "22222222-2222-2222-2222-222222222222"
            ),
        }
    )

    assert simulations_widgets._declared_archive_root_uuids(aiida_node) == (
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    )


def test_declared_archive_roots_support_legacy_comment_records(
    simulations_widgets,
):
    aiida_node = SimpleNamespace(
        props={
            "comments": (
                "AiiDA root process UUID: "
                "33333333-3333-3333-3333-333333333333"
            ),
        }
    )

    assert simulations_widgets._declared_archive_root_uuids(aiida_node) == (
        "33333333-3333-3333-3333-333333333333",
    )


def test_aiida_root_uuids_schema_is_multivalued_and_additive(
    simulations_widgets,
):
    definition = simulations_widgets.simulation_schema.PROPERTY_TYPES[
        "AIIDA_ROOT_UUIDS"
    ]
    assignments = (
        simulations_widgets.simulation_schema.ADDITIVE_OBJECT_TYPE_ASSIGNMENTS
    )

    assert definition["dataType"] == "VARCHAR"
    assert definition["multiValue"] is True
    assert assignments == {
        "AIIDA_NODE": [
            {
                "code": "AIIDA_ROOT_UUIDS",
                "mandatory": False,
                "section": "Provenance",
            }
        ]
    }


def test_multiple_archive_roots_are_listed_in_import_message(
    monkeypatch,
    simulations_widgets,
):
    monkeypatch.setattr(
        simulations_widgets,
        "WORKCHAIN_VIEWERS",
        {"SupportedWorkChain": "viewer.ipynb"},
    )
    simulations = [
        _simulation(
            "Manual archive",
            "simulation-1",
            "UNCLASSIFIED_SIMULATION",
        )
    ]
    roots = (
        SimpleNamespace(
            process_label="SupportedWorkChain",
            pk=11,
            uuid="11111111-1111-1111-1111-111111111111",
        ),
        SimpleNamespace(
            process_label="OtherWorkChain",
            pk=12,
            uuid="22222222-2222-2222-2222-222222222222",
        ),
    )

    message = (
        simulations_widgets.ImportSimulationsWidget._import_success_message(
            simulations,
            roots,
        )
    )

    assert "Root processes (2)" in message
    assert "11111111-1111-1111-1111-111111111111" in message
    assert "22222222-2222-2222-2222-222222222222" in message
    assert "viewer.ipynb?pk=11" in message


@pytest.mark.parametrize(
    ("roots", "expected_workflow_uuid"),
    [
        ((), None),
        (
            (
                {
                    "uuid": "11111111-1111-1111-1111-111111111111",
                    "process_label": "OneWorkChain",
                },
            ),
            "11111111-1111-1111-1111-111111111111",
        ),
        (
            (
                {
                    "uuid": "11111111-1111-1111-1111-111111111111",
                    "process_label": "FirstWorkChain",
                },
                {
                    "uuid": "22222222-2222-2222-2222-222222222222",
                    "process_label": "SecondWorkChain",
                },
            ),
            None,
        ),
    ],
)
def test_manual_archive_creates_one_aiida_node(
    roots,
    expected_workflow_uuid,
    tmp_path,
    monkeypatch,
    simulations_widgets,
):
    created = []
    datasets = []
    aiida_node = SimpleNamespace(permId="aiida-node-1")

    monkeypatch.setattr(
        simulations_widgets,
        "_archive_root_processes",
        lambda archive_path: (
            tuple(roots)
            if archive_path.read_bytes() == b"valid archive"
            else ()
        ),
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_object",
        lambda session, **kwargs: created.append((session, kwargs)) or aiida_node,
    )

    def create_dataset(session, **kwargs):
        assert Path(kwargs["files"][0]).is_file()
        assert Path(kwargs["files"][0]).read_bytes() == b"valid archive"
        datasets.append((session, kwargs))

    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_dataset",
        create_dataset,
    )
    widget = SimpleNamespace(openbis_session="session")

    result = (
        simulations_widgets.ExportSimulationsWidget._create_manual_aiida_node(
            widget,
            {"name": "../archive.aiida", "content": b"valid archive"},
            "Manual simulation",
        )
    )

    assert result is aiida_node
    assert created[0][1]["type"] == simulations_widgets.OPENBIS_OBJECT_TYPES[
        "AiiDA Node"
    ]
    assert created[0][1]["collection"] == (
        simulations_widgets.OPENBIS_COLLECTIONS_PATHS["AiiDA Node"]
    )
    properties = created[0][1]["props"]
    assert properties.get("wfms_uuid") == expected_workflow_uuid
    assert properties.get("aiida_root_uuids", []) == [
        root["uuid"] for root in roots
    ]
    assert properties["comments"] == ""
    assert datasets[0][1]["sample"] is aiida_node


def test_manual_upload_rejects_multiple_aiida_archives(simulations_widgets):
    uploader = SimpleNamespace(
        value=(
            {"name": "first.aiida", "content": b"one"},
            {"name": "second.AIIDA", "content": b"two"},
        )
    )

    with pytest.raises(ValueError, match="at most one"):
        simulations_widgets.ExportSimulationsWidget._uploaded_aiida_archive(
            uploader
        )


def test_prepare_data_download_excludes_previews(
    tmp_path,
    simulations_widgets,
):
    downloaded = []

    class Dataset:
        def __init__(self, permid, type_code, filename, payload):
            self.permId = permid
            self.type = SimpleNamespace(code=type_code)
            self.file_list = [filename]
            self.filename = filename
            self.payload = payload

        def download(self, destination):
            downloaded.append(self.permId)
            path = Path(destination) / self.permId / self.filename
            path.parent.mkdir(parents=True)
            path.write_bytes(self.payload)

    raw_dataset = Dataset(
        "raw-1",
        "RAW_DATA",
        "original/results.tar.gz",
        b"scientific data",
    )
    preview_dataset = Dataset(
        "preview-1",
        "ELN_PREVIEW",
        "original/preview.png",
        b"preview",
    )
    simulation = _simulation(
        "Manual result",
        "simulation-1",
        "UNCLASSIFIED_SIMULATION",
        datasets=[preview_dataset, raw_dataset],
    )

    download_directory, downloaded_files = (
        simulations_widgets.ImportSimulationsWidget._prepare_data_download(
            [simulation],
            download_root=tmp_path,
        )
    )

    assert downloaded == ["raw-1"]
    assert [
        path.relative_to(download_directory).as_posix() for path in downloaded_files
    ] == ["raw-1/original/results.tar.gz"]
    assert downloaded_files[0].read_bytes() == b"scientific data"


def test_find_openbis_simulations_stops_at_cycles(
    monkeypatch,
    simulations_widgets,
):
    class Object:
        def __init__(self, permid, type_code, children):
            self.permId = permid
            self.identifier = f"/OBJECTS/{permid}"
            self.type = SimpleNamespace(code=type_code)
            self.children = children

    root = Object("root", "ATOMISTIC_MODEL", ["/OBJECTS/result"])
    result = Object(
        "result",
        "UNCLASSIFIED_SIMULATION",
        ["/OBJECTS/root"],
    )
    objects = {
        "/OBJECTS/root": root,
        "/OBJECTS/result": result,
    }
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_object",
        lambda _session, sample_ident: objects[sample_ident],
    )

    found = simulations_widgets.utils.find_openbis_simulations(
        object(),
        root,
        {"Unclassified": "UNCLASSIFIED_SIMULATION"},
    )

    assert found == {result}


def test_executable_creation_requires_explicit_selection(
    monkeypatch, simulations_widgets
):
    popups = []
    monkeypatch.setattr(simulations_widgets, "_popup", popups.append)
    widget = SimpleNamespace(
        _executable_selection_widgets={
            "code-uuid": SimpleNamespace(value=""),
        },
        _provenance_overrides={"Executable": {}},
    )

    valid, create_missing = (
        simulations_widgets.ExportSimulationsWidget._apply_executable_selections(widget)
    )

    assert (valid, create_missing) == (False, False)
    assert popups == ["Resolve every missing executable before exporting."]


def test_prepare_archive_download_for_browser(
    tmp_path, monkeypatch, simulations_widgets
):
    class ArchiveDataset:
        permId = "archive-dataset"
        file_list = ["original/export.aiida"]

        def download(self, files, destination):
            assert files == ["original/export.aiida"]
            path = Path(destination) / self.permId / files[0]
            path.parent.mkdir(parents=True)
            path.write_bytes(b"archive")

    aiida_node = SimpleNamespace(get_datasets=lambda: [ArchiveDataset()])
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_object",
        lambda *_args, **_kwargs: aiida_node,
    )

    directory, files = (
        simulations_widgets.ImportSimulationsWidget._prepare_archive_download(
            object(), ["aiida-node"], download_root=tmp_path
        )
    )

    assert len(files) == 1
    assert files[0].relative_to(directory).as_posix() == (
        "archive-dataset/original/export.aiida"
    )
    assert files[0].read_bytes() == b"archive"


def test_manual_simulation_fields_follow_new_schema(simulations_widgets):
    widget = simulations_widgets.SimulationPropertiesWidget(object())
    widget.load_widgets("BAND_STRUCTURE")

    assert "BAND_GAP_EV" in widget.fields
    assert "BAND_GAP" not in widget.fields
    assert "AIIDA_NODE" not in widget.fields
    widget.fields["NAME"].value = "Band result"
    widget.fields["METHOD_FAMILY"].value = "MFH_TB"
    widget.fields["METHOD_MODIFIERS"].value = ("DFT_U", "SPIN_ORBIT")
    widget.fields["METHOD_LABEL"].value = "PBE"
    widget.fields["CHARGE"].value = "0"
    widget.fields["BAND_GAP_EV"].value = "1.25"

    values = widget.values()

    assert values["band_gap_ev"] == pytest.approx(1.25)
    assert values["charge"] == pytest.approx(0.0)
    assert values["converged"] is False
    assert values["method_family"] == "MFH_TB"
    assert values["method_modifiers"] == ["DFT_U", "SPIN_ORBIT"]
    assert isinstance(
        widget.fields["METHOD_MODIFIERS"], simulations_widgets.MultiCheckboxWidget
    )
    assert widget.fields["METHOD_MODIFIERS"]._checkboxes["DFT_U"].value is True
    assert widget.fields["METHOD_MODIFIERS"]._checkboxes["SPIN_ORBIT"].value is True
    assert widget.fields["METHOD_FAMILY"].description == "Method family *"
    assert widget.fields["METHOD_LABEL"].description == "Method label"
    assert dict(widget.fields["METHOD_FAMILY"].options)["MFH-TB"] == "MFH_TB"
    widget.load_widgets("-1")
    assert widget.children == ()


def test_manual_simulation_editor_covers_every_schema_assignment(
    simulations_widgets,
):
    excluded = simulations_widgets.SimulationPropertiesWidget._EXCLUDED_PROPERTIES
    for (
        object_type,
        definition,
    ) in simulations_widgets.simulation_schema.OBJECT_TYPES.items():
        widget = simulations_widgets.SimulationPropertiesWidget(object())
        widget.load_widgets(object_type)
        expected = {
            assignment["code"]
            for assignment in definition["assignments"]
            if assignment["code"] not in excluded
        }
        assert set(widget.fields) == expected


def test_property_review_populates_codes_and_reports_cleared_optional_values(
    simulations_widgets,
):
    widget = simulations_widgets.SimulationPropertiesWidget(object())
    widget.load_widgets("BAND_STRUCTURE")
    widget.set_values(
        {
            "name": "Reviewed bands",
            "method_family": "MFH_TB",
            "method_modifiers": ["DFT_U"],
            "method_label": "PBE+U",
            "charge": 0.0,
            "band_gap_ev": 1.0,
            "converged": True,
            "comments": "Workflow description",
        }
    )
    widget.fields["COMMENTS"].value = ""

    values = widget.values(include_empty=True)

    assert widget.fields["METHOD_FAMILY"].value == "MFH_TB"
    assert widget.fields["METHOD_MODIFIERS"].value == ("DFT_U",)
    assert values["comments"] is None


def test_property_overrides_are_collected_per_result(simulations_widgets):
    widget = SimpleNamespace(
        _preview_entries={
            "source:bands": {
                "property_widget": SimpleNamespace(
                    values=lambda include_empty: {"name": "Edited bands"}
                )
            }
        }
    )

    assert simulations_widgets.SimulationDetailsWidget.property_overrides(widget) == {
        "source:bands": {"name": "Edited bands"}
    }


def test_viewer_link_opens_new_tab(simulations_widgets):
    simulations = [_simulation("Geometry", "sim-1", "GEOMETRY_OPTIMISATION")]
    workchain = SimpleNamespace(process_label="Cp2kGeoOptWorkChain", pk=42)

    link = simulations_widgets.ImportSimulationsWidget._import_success_message(
        simulations, workchain
    )

    assert 'target="_blank"' in link
    assert "/apps/apps/surfaces/view_geometry_optimization.ipynb?pk=42" in link


def test_uploaded_file_compatibility_shapes(simulations_widgets):
    legacy = SimpleNamespace(value={"legacy.png": {"content": memoryview(b"legacy")}})
    current = SimpleNamespace(
        value=({"name": "current.jpg", "content": memoryview(b"current")},)
    )

    assert simulations_widgets._first_uploaded_file(legacy) == {
        "name": "legacy.png",
        "content": b"legacy",
    }
    assert simulations_widgets._first_uploaded_file(current) == {
        "name": "current.jpg",
        "content": b"current",
    }


def test_preview_overrides_use_suggestion_or_replacement(simulations_widgets):
    widget = SimpleNamespace(
        _preview_entries={
            "source:bands": {
                "suggestion": {
                    "title": "Bands",
                    "name": "bands.png",
                    "content": b"suggestion",
                },
                "uploader": SimpleNamespace(value=()),
            },
            "source:pdos": {
                "suggestion": {
                    "title": "PDOS",
                    "name": "pdos.png",
                    "content": b"old",
                },
                "uploader": SimpleNamespace(
                    value=(
                        {
                            "name": "replacement.jpg",
                            "content": memoryview(b"replacement"),
                        },
                    )
                ),
            },
        }
    )

    result = simulations_widgets.SimulationDetailsWidget.preview_overrides(widget)

    assert result == {
        "source:bands": {"name": "bands.png", "content": b"suggestion"},
        "source:pdos": {
            "name": "replacement.jpg",
            "content": b"replacement",
        },
    }


@pytest.mark.parametrize(
    "value",
    [
        {"legacy.dat": {"content": memoryview(b"legacy")}},
        ({"name": "current.dat", "content": memoryview(b"current")},),
    ],
)
def test_upload_datasets_supports_ipywidgets_7_and_8(
    value, monkeypatch, simulations_widgets
):
    written = []
    created = []
    removed = []
    monkeypatch.setattr(
        simulations_widgets.utils,
        "write_file",
        lambda content, filename: written.append((filename, bytes(content))),
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_dataset",
        lambda session, **kwargs: created.append((session, kwargs)),
    )
    monkeypatch.setattr(
        simulations_widgets.utils.os,
        "remove",
        lambda filename: removed.append(filename),
    )

    simulations_widgets.utils.upload_datasets(
        "session",
        "object",
        SimpleNamespace(value=value),
        props={"kind": "test"},
        dataset_type="RAW_DATA",
    )

    assert len(written) == len(created) == len(removed) == 1
    filename, content = written[0]
    assert filename in {"legacy.dat", "current.dat"}
    assert content in {b"legacy", b"current"}
    assert created[0][1] == {
        "type": "RAW_DATA",
        "sample": "object",
        "files": [filename],
        "props": {"kind": "test"},
    }
    assert removed == [filename]


def test_upload_datasets_can_filter_uploaded_files(
    monkeypatch,
    simulations_widgets,
):
    created = []
    monkeypatch.setattr(
        simulations_widgets.utils,
        "write_file",
        lambda _content, _filename: None,
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "create_openbis_dataset",
        lambda _session, **kwargs: created.append(kwargs),
    )
    monkeypatch.setattr(
        simulations_widgets.utils.os,
        "remove",
        lambda _filename: None,
    )
    uploader = SimpleNamespace(
        value=(
            {"name": "archive.aiida", "content": b"archive"},
            {"name": "results.tar.gz", "content": b"results"},
        )
    )

    simulations_widgets.utils.upload_datasets(
        "session",
        "simulation",
        uploader,
        props={},
        dataset_type="RAW_DATA",
        filename_filter=lambda filename: not filename.endswith(".aiida"),
    )

    assert [item["files"] for item in created] == [["results.tar.gz"]]


def test_import_expands_mep_and_atomistic_model_ancestors(
    monkeypatch, simulations_widgets
):
    geometry = _simulation(
        "Geometry",
        "geometry",
        "GEOMETRY_OPTIMISATION",
        aiida_node="archive-geometry",
    )
    replica = _simulation(
        "Replica path",
        "replica",
        "MINIMUM_ENERGY_PATH",
        aiida_node="archive-replica",
    )
    neb = _simulation(
        "NEB path",
        "neb",
        "MINIMUM_ENERGY_PATH",
        aiida_node="archive-neb",
    )
    endpoint = SimpleNamespace(
        permId="endpoint",
        type=SimpleNamespace(code="ATOMISTIC_MODEL"),
        parents=["geometry"],
    )
    geometry.parents = []
    replica.parents = ["endpoint"]
    neb.parents = ["endpoint", "replica"]
    objects = {
        "geometry": geometry,
        "replica": replica,
        "neb": neb,
        "endpoint": endpoint,
    }
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_object",
        lambda _session, sample_ident: objects[str(sample_ident)],
    )
    widget = SimpleNamespace(
        openbis_session=object(),
        _simulation_type_code=(
            simulations_widgets.ImportSimulationsWidget._simulation_type_code
        ),
    )

    expanded = (
        simulations_widgets.ImportSimulationsWidget._simulation_dependencies(
            widget, [neb]
        )
    )

    assert expanded == [geometry, replica, neb]


@pytest.mark.parametrize(
    ("method", "field", "message"),
    [
        ("NEB", "NEB_VARIANT", "NEB variant"),
        ("REPLICA_CHAIN", "COLLECTIVE_VARIABLES", "Collective variables"),
        ("OTHER", "OTHER_METHOD_DESCRIPTION", "Other MEP method description"),
    ],
)
def test_manual_mep_requires_method_specific_field(
    simulations_widgets, method, field, message
):
    widget = simulations_widgets.SimulationPropertiesWidget(object())
    widget.load_widgets("MINIMUM_ENERGY_PATH")
    required_values = {
        "NAME": "Methane path",
        "METHOD_FAMILY": "DFT",
        "METHOD_LABEL": "PBE",
        "CHARGE": "0",
        "MEP_METHOD": method,
        "RELATIVE_ENERGIES_EV": "0, 0.1",
        "FORWARD_BARRIER_EV": "0.1",
        "BACKWARD_BARRIER_EV": "0",
        "NUMBER_OF_IMAGES": "2",
    }
    for code, value in required_values.items():
        widget.fields[code].value = value

    with pytest.raises(ValueError, match=message):
        widget.values()

    if field == "NEB_VARIANT":
        widget.fields[field].value = "CI_NEB"
    else:
        widget.fields[field].value = "specified"
    values = widget.values()

    assert values[field.lower()]


def test_intermediate_pk_resolves_to_supported_parent(simulations_widgets):
    parent = SimpleNamespace(
        uuid="parent",
        pk=10,
        process_label="Cp2kGeoOptWorkChain",
        caller=None,
    )
    intermediate = SimpleNamespace(
        uuid="intermediate",
        pk=11,
        process_label="Cp2kBaseWorkChain",
        caller=parent,
    )

    resolved = simulations_widgets.SimulationDetailsWidget._exportable_ancestor(
        intermediate
    )

    assert resolved is parent
    assert (
        simulations_widgets.SimulationDetailsWidget._exportable_ancestor(
            SimpleNamespace(
                uuid="unsupported",
                process_label="UnsupportedWorkChain",
                caller=None,
            )
        )
        is None
    )


def test_container_workchain_with_exportable_descendants_is_supported(
    simulations_widgets,
):
    child = SimpleNamespace(
        uuid="bands",
        pk=12,
        process_label="BandsWorkChain",
    )
    container = SimpleNamespace(
        uuid="qe-app",
        pk=11,
        process_label="QeAppWorkChain",
        caller=None,
        called_descendants=[child],
    )

    resolved = simulations_widgets.SimulationDetailsWidget._exportable_ancestor(
        container
    )

    assert resolved is container
