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


def _simulation(name, permid, type_code, aiida_node=None, datasets=None):
    return SimpleNamespace(
        props={"name": name, "aiida_node": aiida_node},
        permId=permid,
        type=SimpleNamespace(code=type_code),
        get_datasets=lambda: list(datasets or []),
    )


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
            imported.append(archive_id) or workchain
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

    assert result is workchain
    assert len(destinations) == 1
    assert not destinations[0].exists()


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
    widget.fields["METHOD_FAMILY"].value = "DFT"
    widget.fields["METHOD_LABEL"].value = "PBE"
    widget.fields["CHARGE"].value = "0"
    widget.fields["BAND_GAP_EV"].value = "1.25"

    values = widget.values()

    assert values["band_gap_ev"] == pytest.approx(1.25)
    assert values["charge"] == pytest.approx(0.0)
    assert values["converged"] is False
    widget.load_widgets("-1")
    assert widget.children == ()


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
