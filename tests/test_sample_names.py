"""Sample-name validation and recovery without a live openBIS connection."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class Properties(dict):
    def all(self):
        return dict(self)


@pytest.fixture
def sample_ui(monkeypatch):
    from src import utils

    assert (
        Path(utils.__file__).resolve().parent.parent
        == Path(__file__).resolve().parent.parent
    )

    interface = {
        "object_types": {"Sample": "SAMPLE", "Process Step": "PROCESS_STEP"},
        "object_types_codes": {},
        "slabs_types": {"Crystal": "CRYSTAL"},
        "slabs_concepts_types": {},
        "instruments_types": {},
    }
    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, None))
    monkeypatch.setattr(utils, "get_interface_config_info", lambda: interface)
    for module in ("src.create_samples_widget", "src.widgets"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    create = importlib.import_module("src.create_samples_widget")
    widgets = importlib.import_module("src.widgets")
    messages = []
    monkeypatch.setattr(create, "display", messages.append)
    monkeypatch.setattr(widgets, "display", messages.append)

    material = SimpleNamespace(
        permId="20990101-1",
        code="CRYSTAL_FIXTURE_001",
        type=SimpleNamespace(code="CRYSTAL"),
        props=Properties(name="Au(111)"),
        parents=[],
    )
    original = SimpleNamespace(
        permId="20990101-2",
        code="SAMPLE_FIXTURE_001",
        type=SimpleNamespace(code="SAMPLE"),
        props=Properties(name="Original sample", object_status="ACTIVE"),
        parents=[material.permId],
        registrator=SimpleNamespace(userId="fixture-user"),
    )
    objects = {material.permId: material, original.permId: original}
    writes = []
    lookups = []

    def get_object(_session, sample_ident):
        return objects[sample_ident]

    def get_objects(_session, type, **_kwargs):
        return [
            obj
            for obj in objects.values()
            if obj.type.code == type
            and obj.props.get("object_status", "ACTIVE") == "ACTIVE"
        ]

    def create_object(_session, *, type, collection, props, parents):
        obj = SimpleNamespace(
            permId="20990101-3",
            code="SAMPLE_FIXTURE_002",
            type=SimpleNamespace(code=type),
            props=Properties(props),
            parents=[parent.permId for parent in parents],
            registrator=SimpleNamespace(userId="fixture-user"),
        )
        writes.append(("create", obj.permId, dict(props)))
        objects[obj.permId] = obj
        return obj

    def update_object(obj):
        writes.append(("update", obj.permId, dict(obj.props)))
        return obj

    def get_sample(permid):
        lookups.append(permid)
        return objects[permid]

    monkeypatch.setattr(utils, "get_openbis_object", get_object)
    monkeypatch.setattr(utils, "get_openbis_objects", get_objects)
    monkeypatch.setattr(utils, "create_openbis_object", create_object)
    monkeypatch.setattr(utils, "update_openbis_object", update_object)
    monkeypatch.setattr(
        utils,
        "delete_openbis_object",
        lambda obj: writes.append(("delete", obj.permId)),
    )
    monkeypatch.setattr(
        utils,
        "get_openbis_property_type",
        lambda _session, code: SimpleNamespace(label=code, dataType="VARCHAR"),
    )
    session = SimpleNamespace(
        _get_username=lambda: "fixture-user", get_sample=get_sample
    )
    return SimpleNamespace(
        create=create,
        widgets=widgets,
        session=session,
        material=material,
        original=original,
        objects=objects,
        writes=writes,
        lookups=lookups,
        messages=messages,
    )


def creation_form(ui):
    widget = ui.create.CreateSampleWidget(ui.session)
    widget.material_type_dropdown.value = "CRYSTAL"
    widget.material_details_vbox.children[0].children[0].value = ui.material.permId
    return widget


@pytest.mark.parametrize("name", ["", " ", "\t\n", "\u00a0\u2003"])
def test_empty_creation_never_writes_or_retires_previous_sample(sample_ui, name):
    widget = creation_form(sample_ui)
    widget.sample_name_textbox.value = name

    widget.save_button.click()

    assert sample_ui.writes == []
    assert sample_ui.original.props["object_status"] == "ACTIVE"
    assert len(sample_ui.objects) == 2
    assert "Sample name cannot be empty" in widget.sample_name_error.value
    assert widget.material_type_dropdown.value == "CRYSTAL"
    assert widget.sample_name_textbox.value == name
    assert not sample_ui.messages


def test_corrected_name_creates_once_and_preserves_retirement_behavior(sample_ui):
    widget = creation_form(sample_ui)
    widget.sample_name_textbox.value = " "
    widget.save_button.click()
    assert sample_ui.writes == []

    widget.sample_name_textbox.value = "  Au(111) working sample  "
    widget.save_button.click()

    assert [write[0] for write in sample_ui.writes] == ["update", "create"]
    assert sample_ui.original.props["object_status"] == "DISPOSED"
    assert sample_ui.objects["20990101-3"].props == {
        "name": "Au(111) working sample",
        "object_status": "ACTIVE",
    }
    assert widget.sample_name_error.value == ""
    assert widget.material_type_dropdown.value == "-1"
    assert "Sample created successfully" in sample_ui.messages[-1].data


@pytest.mark.parametrize("name", [None, "", " \t", "\u00a0", "missing"])
def test_unnamed_samples_use_code_and_can_be_renamed_by_permid(sample_ui, name):
    sample = sample_ui.original
    if name == "missing":
        del sample.props["name"]
    else:
        sample.props["name"] = name
    widget = sample_ui.widgets.SelectSampleWidget(sample_ui.session)

    assert (sample.code, sample.permId) in widget.sample_dropdown.options
    widget.sort_name_cb.value = True
    widget.sample_dropdown.value = sample.permId
    widget.edit_sample_button.click()

    assert widget.sample_dropdown.disabled
    assert widget.edit_name_textbox.value == ""
    assert widget.edit_sample_widgets.children
    widget.edit_name_textbox.value = "  Renamed Au(111)  "
    widget.save_btn.click()

    assert sample_ui.lookups == [sample.permId]
    assert sample.props["name"] == "Renamed Au(111)"
    assert sample.props["object_status"] == "ACTIVE"
    assert sample.code == "SAMPLE_FIXTURE_001"
    assert widget.sample_dropdown.value == sample.permId
    assert ("Renamed Au(111)", sample.permId) in widget.sample_dropdown.options
    assert not widget.sample_dropdown.disabled
    assert len(sample_ui.writes) == 1


def test_named_sample_editor_uses_name_and_renames_only_selected_permid(sample_ui):
    sample = sample_ui.original
    other = SimpleNamespace(
        permId="20990101-4",
        code="SAMPLE_FIXTURE_004",
        type=sample.type,
        props=Properties(name=sample.props["name"], object_status="ACTIVE"),
        parents=sample.parents,
        registrator=sample.registrator,
    )
    sample_ui.objects[other.permId] = other
    widget = sample_ui.widgets.SelectSampleWidget(sample_ui.session)
    widget.sample_dropdown.value = other.permId
    widget.edit_sample_button.click()
    assert widget.edit_name_textbox.value == "Original sample"
    widget.edit_name_textbox.value = "Second sample"
    widget.save_btn.click()

    assert sample_ui.lookups == [other.permId]
    assert other.props["name"] == "Second sample"
    assert sample.props["name"] == "Original sample"


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_rename_never_writes(sample_ui, name):
    widget = sample_ui.widgets.SelectSampleWidget(sample_ui.session)
    widget.sample_dropdown.value = sample_ui.original.permId
    widget.edit_sample_button.click()
    widget.edit_name_textbox.value = name
    widget.save_btn.click()

    assert sample_ui.writes == []
    assert sample_ui.lookups == []
    assert sample_ui.original.props["name"] == "Original sample"
    assert "Sample name cannot be empty" in sample_ui.messages[-1].data
