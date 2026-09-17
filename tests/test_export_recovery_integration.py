"""Stateful export interruption tests with no live openBIS writes."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from ase.io.jsonio import decode
from PIL import Image
from test_aiida_utils import (
    FakeOpenbisObject,
    FakeSession,
    make_cp2k_scf_workchain,
    publish_dataset,
)
from test_aiida_utils import aiida_utils as _aiida_utils_fixture

from src import export_status
from src.export_recovery import ExportVerificationError, LocalExportMetadataError

# Reuse the fixture that prevents live connections when importing the exporter.
aiida_utils = _aiida_utils_fixture


@pytest.fixture
def export_case(monkeypatch, aiida_utils, aiida_profile_clean):
    workchain = make_cp2k_scf_workchain()
    workchain.pk = 1
    structure = aiida_utils.orm.StructureData(
        ase=aiida_utils.Atoms("CH4", cell=[10, 10, 10], pbc=False)
    )
    workchain.inputs.structure = structure
    session = FakeSession()
    created = []
    uploads = []
    archives_built = []

    def load_node(identifier):
        return structure if str(identifier) == structure.uuid else workchain

    def create(_session, **kwargs):
        obj = FakeOpenbisObject(kwargs["type"], kwargs["props"])
        obj.collection = kwargs["collection"]
        obj.parents = list(kwargs.get("parents", []))
        created.append(obj)
        session.objects.setdefault(obj.type, []).append(obj)
        return obj

    def upload(_session, **kwargs):
        uploads.append(
            (
                kwargs["sample"].type,
                kwargs["type"],
                {Path(p).name: Path(p).read_bytes() for p in kwargs["files"]},
            )
        )
        return publish_dataset(_session, **kwargs)

    def build_archive(command, **_kwargs):
        archives_built.append(command)
        Path(command[3]).write_bytes(b"original archive snapshot")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(aiida_utils.orm, "load_node", load_node)
    monkeypatch.setattr(
        aiida_utils, "get_all_preceding_main_workchains", lambda _uuid: [workchain.uuid]
    )
    monkeypatch.setattr(
        aiida_utils, "_ensure_executables_for_workchains", lambda *_args, **_kwargs: {}
    )
    monkeypatch.setattr(
        aiida_utils, "record_openbis_exports", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(aiida_utils.utils, "create_openbis_object", create)
    monkeypatch.setattr(aiida_utils.utils, "create_openbis_dataset", upload)
    monkeypatch.setattr(aiida_utils.utils, "update_openbis_object", lambda _obj: None)
    monkeypatch.setattr(aiida_utils.subprocess, "run", build_archive)
    monkeypatch.setattr(
        aiida_utils,
        "geo_to_png",
        lambda _atoms, path: Image.new("RGB", (20, 10)).save(path),
    )
    return SimpleNamespace(
        session=session,
        workchain=workchain,
        structure=structure,
        created=created,
        uploads=uploads,
        upload=upload,
        archives_built=archives_built,
        run=lambda: aiida_utils.export_workchain(
            session, "/SPACE/PROJECT/EXPERIMENT", workchain.uuid
        ),
        report=lambda: export_status.inspect_workchain_export(
            session, "/SPACE/PROJECT/EXPERIMENT", workchain.uuid
        ),
    )


@pytest.mark.parametrize("stage", ["archive", "structure", "preview", "charge"])
@pytest.mark.parametrize("after_write", [False, True])
def test_interrupted_export_reuses_objects_and_completes_only_missing_uploads(
    monkeypatch, aiida_utils, export_case, stage, after_write
):
    case = export_case
    interrupted = []

    def upload(session, **kwargs):
        kind = kwargs["sample"].type
        dataset_type = kwargs["type"]
        matches = (
            (stage == "archive" and kind == "AIIDA_NODE")
            or (
                stage == "structure"
                and kind == "ATOMISTIC_MODEL"
                and dataset_type == "RAW_DATA"
            )
            or (
                stage == "preview"
                and kind == "ENERGY_CALCULATION"
                and dataset_type == "ELN_PREVIEW"
            )
            or (
                stage == "charge"
                and kind == "CHARGE_ANALYSIS"
                and dataset_type == "RAW_DATA"
            )
        )
        if matches and not interrupted:
            interrupted.append(True)
            if after_write:
                case.upload(session, **kwargs)
            raise TimeoutError("simulated upload interruption")
        return case.upload(session, **kwargs)

    monkeypatch.setattr(aiida_utils.utils, "create_openbis_dataset", upload)
    if after_write:
        case.run()
    else:
        with pytest.raises(TimeoutError):
            case.run()
        assert not case.report().complete
    assert interrupted

    objects_before_retry = {obj.permId for obj in case.created}
    case.run()
    assert case.report().complete
    assert objects_before_retry <= {obj.permId for obj in case.created}
    assert len(case.created) == 4  # archive, structure, energy and charge
    uploads_after_retry = list(case.uploads)
    case.run()
    assert case.uploads == uploads_after_retry
    assert len(case.created) == 4
    assert sum(kind == "AIIDA_NODE" for kind, _, _ in case.uploads) == 1
    assert len(case.archives_built) == (
        2 if stage == "archive" and not after_write else 1
    )

    stored_json = next(
        files["structure_json.json"]
        for _, _, files in case.uploads
        if "structure_json.json" in files
    )
    assert decode(stored_json.decode()).get_chemical_formula() == "CH4"


def test_retry_keeps_reviewed_properties_and_existing_bader_files(
    monkeypatch, aiida_utils, export_case
):
    case = export_case
    energy, charge = case.run()
    energy.props["name"] = "User-reviewed title"
    data = next(ds for ds in charge.datasets if ds.type == "RAW_DATA")
    data.file_list.remove("AVF.dat")
    report = case.report()
    assert not report.complete
    assert any(
        check.state == "missing" and "AVF.dat" in check.label for check in report.checks
    )
    count = len(case.uploads)
    case.run()
    assert case.report().complete
    assert energy.props["name"] == "User-reviewed title"
    assert len(case.uploads) == count + 1
    assert set(case.uploads[-1][2]) == {"AVF.dat"}


def test_new_check_reports_missing_preview_without_rendering_a_complete_result(
    monkeypatch, aiida_utils, export_case
):
    case = export_case
    energy, charge = case.run()
    energy.datasets.clear()
    suggestions = aiida_utils.render_workchain_preview_suggestions(
        case.workchain.uuid,
        openbis_session=case.session,
        experiment_id="/SPACE/PROJECT/EXPERIMENT",
    )
    energy_suggestion = next(
        item for item in suggestions if item["result_role"] == "energy_calculation"
    )
    charge_suggestion = next(
        item for item in suggestions if item["result_role"] == "charge_analysis"
    )
    assert energy_suggestion["needs_preview"]
    assert energy_suggestion["content"] is not None
    assert charge_suggestion["existing"]["permid"] == charge.permId
    assert charge_suggestion["content"] is None


def test_unknown_dataset_state_prevents_retry_writes(
    monkeypatch, aiida_utils, export_case
):
    case = export_case
    case.run()
    archive = case.session.objects["AIIDA_NODE"][0]

    def unavailable():
        raise OSError("server unavailable")

    archive.get_datasets = unavailable
    uploads = len(case.uploads)
    assert case.report().unknown
    with pytest.raises(ExportVerificationError):
        case.run()
    assert len(case.uploads) == uploads


def test_local_extra_failure_leaves_remote_export_complete(
    monkeypatch, aiida_utils, export_case
):
    """A metadata retry must not replace remote datasets."""
    case = export_case

    def fail_extras(*_args, **_kwargs):
        raise RuntimeError("local extra cache unavailable")

    monkeypatch.setattr(aiida_utils, "record_openbis_exports", fail_extras)
    with pytest.raises(LocalExportMetadataError):
        case.run()
    assert case.report().complete
    uploads = list(case.uploads)
    monkeypatch.setattr(
        aiida_utils, "record_openbis_exports", lambda *_args, **_kwargs: None
    )
    case.run()
    assert case.uploads == uploads


def test_retry_repairs_missing_source_result_link_without_uploads(export_case):
    case = export_case
    energy, charge = case.run()
    charge.parents = [parent for parent in charge.parents if parent is not energy]
    report = case.report()
    assert not report.complete
    assert any(
        check.key.endswith("/source-result") and check.state == "missing"
        for check in report.checks
    )
    uploads = list(case.uploads)
    case.run()
    assert case.report().complete
    assert case.uploads == uploads


def test_retry_preserves_existing_archive_when_local_extras_change(export_case):
    case = export_case
    case.run()
    case.structure.base.extras.set("eln", {"new_annotation": "not in the old archive"})
    uploads = list(case.uploads)
    case.run()
    assert case.report().complete
    assert case.uploads == uploads
    assert len(case.archives_built) == 1


def test_status_accepts_pybis_collection_entities(export_case, aiida_utils):
    case = export_case
    _, charge = case.run()
    charge.collection = SimpleNamespace(identifier="/SPACE/PROJECT/EXPERIMENT")
    report = export_status.inspect_result(
        case.session,
        case.workchain,
        "charge_analysis",
        charge,
        aiida_utils._result_property_definitions(case.workchain),
    )
    assert report.complete


@pytest.mark.parametrize(
    "kind", ["ATOMISTIC_MODEL", "AIIDA_NODE", "ENERGY_CALCULATION"]
)
def test_duplicate_identity_is_unverified_and_stops_recovery(export_case, kind):
    case = export_case
    case.run()
    original = case.session.objects[kind][0]
    case.session.objects[kind].append(original)
    assert case.report().unknown
    uploads = list(case.uploads)
    with pytest.raises(ExportVerificationError):
        case.run()
    assert case.uploads == uploads
