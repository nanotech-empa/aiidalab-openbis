"""Manual split/review/retry regression tests without live openBIS writes."""

from pathlib import Path
from types import MethodType, SimpleNamespace

import ipywidgets as ipw
import pytest
from test_aiida_archives import three_roots as _three_roots
from test_aiida_utils import FakeOpenbisObject, FakeSession, publish_dataset
from test_simulations_widgets import simulations_widgets as _simulations_widgets

from src import aiida_archives, manual_simulations

three_roots = _three_roots
simulations_widgets = _simulations_widgets


@pytest.fixture
def manual_case(monkeypatch, simulations_widgets, three_roots):
    module = simulations_widgets
    source, roots, *_ = three_roots
    session = FakeSession()
    created, uploads = [], []

    def create(_session, **kwargs):
        obj = FakeOpenbisObject(kwargs["type"], kwargs["props"])
        obj.collection = kwargs["collection"]
        obj.parents = list(kwargs.get("parents", []))
        created.append(obj)
        session.objects.setdefault(obj.type, []).append(obj)
        return obj

    def upload(_session, **kwargs):
        files = {Path(p).name: Path(p).read_bytes() for p in kwargs["files"]}
        if kwargs["sample"].type == "AIIDA_NODE":
            uuid = kwargs["sample"].props["wfms_uuid"]
            aiida_archives.validate_root(kwargs["files"][0], uuid)
            assert list(files) == [f"{uuid}.aiida"]
        uploads.append((kwargs["sample"].permId, kwargs["type"], files))
        return publish_dataset(_session, **kwargs)

    monkeypatch.setattr(module.utils, "create_openbis_object", create)
    monkeypatch.setattr(module.utils, "create_openbis_dataset", upload)
    monkeypatch.setattr(module.utils, "update_openbis_object", lambda _obj: None)
    monkeypatch.setattr(module, "_popup", lambda _message: None)
    widget = SimpleNamespace(
        openbis_session=session,
        _manual_archive_review=None,
        manual_archive_review_box=ipw.VBox(),
        export_status_html=ipw.HTML(),
        export_message_html=ipw.HTML(),
        retry_export_button=ipw.Button(),
    )
    widget._review_manual_archive = MethodType(
        module.ExportSimulationsWidget._review_manual_archive, widget
    )
    export = MethodType(module.ExportSimulationsWidget._export_manual_archive, widget)
    properties = {
        "name": "My calculation",
        "simulation_description": "Shared description",
        "converged": True,
        "executables": ["code-1"],
    }
    archive_file = {"name": "original.aiida", "content": source.read_bytes()}
    preview = {"name": "preview.png", "content": b"preview"}
    raw = {"name": "notes.txt", "content": b"notes"}
    return SimpleNamespace(
        module=module,
        source=source,
        roots=roots,
        session=session,
        widget=widget,
        properties=properties,
        created=created,
        uploads=uploads,
        upload=upload,
        preview=preview,
        raw=raw,
        run=lambda: export(
            archive_file,
            "/SPACE/PROJECT/EXP",
            "UNCLASSIFIED_SIMULATION",
            properties,
            ["parent-1"],
            [preview],
            [raw],
        ),
    )


def test_three_editable_cards_then_only_three_derived_archives(manual_case):
    case = manual_case
    case.run()
    assert case.created == case.uploads == []
    review = case.widget._manual_archive_review
    assert len(review["editors"]) == 3
    for root, editor in zip(review["roots"], review["editors"]):
        assert root["label"] in editor.fields["NAME"].value
        assert editor.fields["SIMULATION_DESCRIPTION"].value == "Shared description"
    review["editors"][1].fields["NAME"].value = "Separately reviewed title"
    review["editors"][1].fields["COMMENTS"].value = "Only this record"
    case.run()  # explicit confirmation still absent
    assert case.created == []
    review["confirmed"].value = True
    case.run()
    assert len(case.created) == 6
    archives = [obj for obj in case.created if obj.type == "AIIDA_NODE"]
    results = [obj for obj in case.created if obj.type == "UNCLASSIFIED_SIMULATION"]
    assert len(archives) == len(results) == 3
    assert results[1].props["name"] == "Separately reviewed title"
    assert results[1].props["comments"] == "Only this record"
    for root, archive, result in zip(review["roots"], archives, results):
        assert archive.props == {"wfms_uuid": root["uuid"], "comments": ""}
        assert result.props["aiida_source_uuid"] == root["uuid"]
        assert result.props["aiida_node"] == archive.permId
        assert result.props["executables"] == ["code-1"]
        assert result.parents == ["parent-1"]
        assert {name for ds in result.datasets for name in ds.file_list} == {
            "preview.png",
            "notes.txt",
        }
    assert all("original.aiida" not in files for _, _, files in case.uploads)
    assert "Export completed" in case.widget.export_status_html.value
    assert case.widget.retry_export_button.layout.display == "none"
    previous_uploads = list(case.uploads)
    case.run()
    assert case.uploads == previous_uploads
    assert len(case.created) == 6


def test_all_cards_validate_before_first_write_and_changes_require_review(manual_case):
    case = manual_case
    case.run()
    review = case.widget._manual_archive_review
    review["confirmed"].value = True
    review["editors"][-1].fields["NAME"].value = ""
    with pytest.raises(ValueError):
        case.run()
    assert case.created == []
    case.properties["simulation_description"] = "Changed shared metadata"
    case.run()
    assert case.widget._manual_archive_review is not review
    assert not case.widget._manual_archive_review["confirmed"].value
    assert case.created == []


@pytest.mark.parametrize("after_write", [False, True])
@pytest.mark.parametrize("stage", ["archive", "preview", "raw"])
def test_interrupted_batch_reuses_objects_and_uploads_only_missing(
    monkeypatch, manual_case, after_write, stage
):
    case = manual_case
    case.run()
    case.widget._manual_archive_review["confirmed"].value = True
    interrupted = []
    matched = []

    def upload(session, **kwargs):
        matches = {
            "archive": kwargs["sample"].type == "AIIDA_NODE",
            "preview": kwargs["type"] == "ELN_PREVIEW",
            "raw": kwargs["type"] == "RAW_DATA"
            and kwargs["sample"].type != "AIIDA_NODE",
        }[stage]
        if matches:
            matched.append(True)
        if matches and len(matched) == 2 and not interrupted:
            interrupted.append(True)
            if after_write:
                case.upload(session, **kwargs)
            raise TimeoutError("simulated interrupted upload")
        return case.upload(session, **kwargs)

    monkeypatch.setattr(case.module.utils, "create_openbis_dataset", upload)
    case.run()
    assert interrupted
    if not after_write:
        assert "Export incomplete" in case.widget.export_status_html.value
        assert case.widget.retry_export_button.layout.display != "none"
    case.run()
    assert "Export completed" in case.widget.export_status_html.value
    assert len(case.created) == 6
    assert len(case.uploads) == 9  # 3 archives + 3 previews + 3 other attachments
    previous_uploads = list(case.uploads)
    case.run()
    assert case.uploads == previous_uploads


def test_unknown_server_state_never_creates_replacements(monkeypatch, manual_case):
    case = manual_case
    case.run()
    case.widget._manual_archive_review["confirmed"].value = True

    def unavailable(**_kwargs):
        raise ConnectionError("Cannot read inventory")

    monkeypatch.setattr(case.session, "get_objects", unavailable)
    case.run()
    assert case.created == case.uploads == []
    assert "Cannot read inventory" in case.widget.export_status_html.value
    assert "Export completed" not in case.widget.export_status_html.value


def test_zero_roots_or_classified_multi_root_rejected(monkeypatch, manual_case):
    case = manual_case
    with pytest.raises(ValueError, match="Select Unclassified"):
        case.widget._review_manual_archive(
            case.source, "classified", "BAND_STRUCTURE", case.properties
        )
    monkeypatch.setattr(case.module.aiida_archives, "root_processes", lambda _path: ())
    with pytest.raises(ValueError, match="No main process"):
        case.run()
    assert case.created == []


def test_attachment_filenames_must_be_unambiguous():
    with pytest.raises(ValueError, match="distinct"):
        manual_simulations.attachment_names([{"name": "a/x"}, {"name": "b/x"}])


def test_original_upload_is_excluded_from_simulation_attachments(simulations_widgets):
    module = simulations_widgets
    forwarded = []
    details = SimpleNamespace(
        molecules_accordion=ipw.VBox(),
        reacprod_concepts_accordion=ipw.VBox(),
        material_type_dropdown=SimpleNamespace(value="-1"),
        simulation_type_dropdown=SimpleNamespace(value="UNCLASSIFIED_SIMULATION"),
        atom_model_widget=SimpleNamespace(
            atom_model_dropdown=SimpleNamespace(value="-1")
        ),
        simulation_properties_widget=SimpleNamespace(values=lambda: {"name": "Manual"}),
        executables_multi_selector=SimpleNamespace(value=()),
        upload_image_preview_uploader=SimpleNamespace(
            value=({"name": "preview.png", "content": b"image"},)
        ),
        upload_datasets_uploader=SimpleNamespace(
            value=(
                {"name": "original.AIIDA", "content": b"archive"},
                {"name": "notes.txt", "content": b"notes"},
            )
        ),
    )
    widget = SimpleNamespace(
        select_experiment_widget=SimpleNamespace(
            experiment_dropdown=SimpleNamespace(value="/SPACE/PROJECT/EXP")
        ),
        simulation_details_vbox=details,
        used_aiida_checkbox=SimpleNamespace(value=False),
        _uploaded_aiida_archive=module.ExportSimulationsWidget._uploaded_aiida_archive,
        _export_manual_archive=lambda *args: forwarded.append(args),
    )
    module.ExportSimulationsWidget._export_simulation_to_openbis(widget, None)
    assert len(forwarded) == 1
    archive_file, _, _, _, _, previews, raw = forwarded[0]
    assert archive_file["name"] == "original.AIIDA"
    assert [item["name"] for item in previews] == ["preview.png"]
    assert [item["name"] for item in raw] == ["notes.txt"]


def test_import_rejects_unsplit_archive_before_database_import(
    monkeypatch, manual_case
):
    case = manual_case
    module = case.module

    class Dataset:
        permId = "dataset-1"
        file_list = ("original/multi.aiida",)

        def download(self, files, destination):
            path = Path(destination) / self.permId / files[0]
            path.parent.mkdir(parents=True)
            path.write_bytes(case.source.read_bytes())

    dataset = Dataset()
    node = SimpleNamespace(
        props={"wfms_uuid": case.roots[0].uuid}, get_datasets=lambda: [dataset]
    )
    monkeypatch.setattr(
        module.utils, "get_openbis_object", lambda *args, **kwargs: node
    )
    calls = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: calls.append(args)
    )
    widget = SimpleNamespace(
        openbis_session=case.session,
        _find_aiida_archive_dataset=module.ImportSimulationsWidget._find_aiida_archive_dataset,
        _downloaded_dataset_path=module.ImportSimulationsWidget._downloaded_dataset_path,
    )
    with pytest.raises(ValueError, match="exactly one main process"):
        module.ImportSimulationsWidget._import_aiida_archive(widget, "archive-1")
    assert calls == []


def test_lost_object_creation_response_is_recoverable(monkeypatch, manual_case):
    case = manual_case
    case.run()
    case.widget._manual_archive_review["confirmed"].value = True
    create = case.module.utils.create_openbis_object
    interrupted = []

    def lost_response(session, **kwargs):
        result = create(session, **kwargs)
        if kwargs["type"] == "UNCLASSIFIED_SIMULATION" and not interrupted:
            interrupted.append(True)
            raise TimeoutError("Object was created, but response lost")
        return result

    monkeypatch.setattr(case.module.utils, "create_openbis_object", lost_response)
    case.run()
    assert "Export incomplete" in case.widget.export_status_html.value
    case.run()
    assert "Export completed" in case.widget.export_status_html.value
    assert len(case.created) == 6
    assert len(case.uploads) == 9
