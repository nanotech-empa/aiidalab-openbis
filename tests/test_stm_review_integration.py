"""Shared exporter validates maps before writes and uses the matching SPM result."""

from types import MethodType, SimpleNamespace

import pytest

from aiida_openbis import stm_imaging
from test_simulations_widgets import simulations_widgets as _shared_fixture

simulations_widgets = _shared_fixture


def test_shared_export_rejects_stale_files_before_standard_write(
    monkeypatch, simulations_widgets
):
    calls = []
    monkeypatch.setattr(
        simulations_widgets.orm, "load_node", lambda _: SimpleNamespace(uuid="source")
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "export_workchain",
        lambda *args, **kwargs: calls.append("write"),
    )

    def reject(*args):
        raise ValueError("stale stored archive")

    monkeypatch.setattr(stm_imaging, "prepare_files", reject)
    widget = SimpleNamespace(
        _microscopy_review={"source_uuid": "source"},
        openbis_session=object(),
        export_status_html=simulations_widgets.ipw.HTML(),
    )
    with pytest.raises(ValueError, match="stale"):
        simulations_widgets.ExportSimulationsWidget._export_reviewed_workchain(
            widget, "experiment", "source"
        )
    assert calls == []


def test_shared_export_attaches_maps_to_matching_result_not_first_object(
    monkeypatch, simulations_widgets
):
    events = []
    monkeypatch.setattr(
        simulations_widgets.orm, "load_node", lambda _: SimpleNamespace(uuid="source")
    )
    monkeypatch.setattr(
        stm_imaging,
        "prepare_files",
        lambda *args: events.append("files validated") or ["prepared"],
    )
    outputs = [
        SimpleNamespace(
            permId="preceding-geoopt",
            _aiidalab_source_uuid="geoopt",
            _aiidalab_result_role="geometry_optimization",
        ),
        SimpleNamespace(
            permId="other",
            _aiidalab_source_uuid="other-source",
            _aiidalab_result_role="spm",
        ),
        SimpleNamespace(
            permId="correct-spm",
            _aiidalab_source_uuid="source",
            _aiidalab_result_role="spm",
        ),
    ]
    reviewed_keys = ("geoopt:geometry_optimization", "source:spm")

    def export(session, experiment, source, **kwargs):
        assert (session, experiment, source) == (
            widget.openbis_session,
            "experiment",
            "source",
        )
        assert kwargs["reviewed_result_keys"] == reviewed_keys
        events.append("standard export")
        return outputs

    monkeypatch.setattr(simulations_widgets.aiida_utils, "export_workchain", export)

    def publish(session, experiment, sample, packages):
        assert "Attaching 1 microscopy dataset(s)" in widget.export_status_html.value
        events.append((sample, packages))
        return [{"perm_id": "image"}]

    monkeypatch.setattr(stm_imaging, "publish", publish)
    widget = SimpleNamespace(
        _microscopy_review={"source_uuid": "source"},
        openbis_session=object(),
        export_status_html=simulations_widgets.ipw.HTML(),
    )
    result = simulations_widgets.ExportSimulationsWidget._export_reviewed_workchain(
        widget, "experiment", "source", reviewed_result_keys=reviewed_keys
    )
    assert result is outputs
    assert events == [
        "files validated",
        "standard export",
        ("correct-spm", ["prepared"]),
    ]
    assert widget._microscopy_results == [{"perm_id": "image"}]


@pytest.mark.parametrize("stop", ["computer", "interrupt"])
def test_export_leaves_waiting_state_and_unlocks_controls(
    monkeypatch, simulations_widgets, stop
):
    module = simulations_widgets
    cls = module.ExportSimulationsWidget
    ipw = module.ipw
    monkeypatch.setattr(module.utils, "get_openbis_objects", lambda *_a, **_k: [])

    def stop_export(*_args, **_kwargs):
        assert widget.save_simulations_button.disabled
        assert "Export in progress" in widget.export_status_html.value
        if stop == "interrupt":
            raise KeyboardInterrupt
        error = module.aiida_utils.OpenbisNameMatchError("No matching computer")
        error.object_kind = "Computer"
        error.aiida_uuid = "local-computer-uuid"
        error.aiida_label = "localhost"
        error.aiida_description = ""
        error.openbis_options = (("computer-permid", "Existing computer"),)
        raise error

    monkeypatch.setattr(cls, "_export_reviewed_workchain", stop_export)
    widget = SimpleNamespace(
        openbis_session=object(),
        _pending_reference_resolution=None,
        _resolution_options=cls._resolution_options,
        _provenance_overrides={},
        provenance_resolution_box=ipw.VBox(),
        executable_resolution_box=ipw.VBox(),
        executable_confirmation_message=ipw.HTML(),
        export_status_html=ipw.HTML(),
        save_simulations_button=ipw.Button(),
        retry_export_button=ipw.Button(),
        select_experiment_widget=SimpleNamespace(
            experiment_dropdown=SimpleNamespace(value="experiment"),
        ),
        used_aiida_checkbox=SimpleNamespace(value=True),
        simulation_details_vbox=SimpleNamespace(
            simulations_dropdown=SimpleNamespace(value="source"),
            molecules_accordion=ipw.Accordion(),
            reacprod_concepts_accordion=ipw.Accordion(),
            material_type_dropdown=SimpleNamespace(value="-1"),
            preview_overrides=dict,
            property_overrides=dict,
            _preview_entries={},
        ),
        _apply_pending_reference_resolution=lambda: True,
        _apply_executable_selections=lambda: (True, False),
    )
    widget._show_reference_resolution = MethodType(
        cls._show_reference_resolution, widget
    )

    cls.export_simulation_to_openbis(widget, None)

    assert not widget._exporting
    assert not widget.save_simulations_button.disabled
    assert "Export in progress" not in widget.export_status_html.value
    if stop == "computer":
        assert "Export paused" in widget.export_status_html.value
        assert "localhost" in widget.export_status_html.value
        assert widget._pending_reference_resolution["selector"].value == ""
    else:
        assert "Export interrupted" in widget.export_status_html.value
        assert not widget.provenance_resolution_box.children


def test_existing_spm_append_skips_standard_export_and_targets_original_collection(
    monkeypatch, simulations_widgets
):
    module = simulations_widgets
    cls = module.ExportSimulationsWidget
    ipw = module.ipw
    request = {"kind": "sts_points", "points": [{"id": "P2"}]}
    plan = {
        "sample": "existing-spm",
        "collection": "/SPACE/PROJECT/ORIGINAL",
        "additions": [request],
        "pending_previews": [],
    }
    widget = SimpleNamespace(
        openbis_session=SimpleNamespace(url="https://example.invalid"),
        _microscopy_review={"source_uuid": "source"},
        _initial_microscopy_attempt=None,
        _microscopy_append_review=plan,
        _microscopy_append_plan=lambda _experiment: plan,
        microscopy_append_status=ipw.HTML(),
        export_status_html=ipw.HTML(),
        save_simulations_button=ipw.Button(),
        retry_export_button=ipw.Button(),
        select_experiment_widget=SimpleNamespace(
            experiment_dropdown=SimpleNamespace(value="another-experiment"),
        ),
        used_aiida_checkbox=SimpleNamespace(value=True),
        simulation_details_vbox=SimpleNamespace(
            simulations_dropdown=SimpleNamespace(value="source"),
            molecules_accordion=ipw.Accordion(),
            reacprod_concepts_accordion=ipw.Accordion(),
            material_type_dropdown=SimpleNamespace(value="-1"),
        ),
        _apply_pending_reference_resolution=lambda: pytest.fail(
            "append needs no provenance"
        ),
    )
    for name in (
        "_append_microscopy_data",
        "_show_microscopy_append_plan",
        "microscopy_publication_plan",
    ):
        setattr(widget, name, MethodType(getattr(cls, name), widget))
    monkeypatch.setattr(
        cls,
        "_export_reviewed_workchain",
        lambda *_args, **_kwargs: pytest.fail(
            "append must not re-export the simulation"
        ),
    )

    def review(source, maps, *, sampling):
        assert (source, maps, sampling) == ("source", [], [request])
        return "reviewed-dat"

    def publish(session, experiment, sample, packages):
        assert (session, experiment, sample, packages) == (
            widget.openbis_session,
            plan["collection"],
            plan["sample"],
            ["dat"],
        )
        return [{"perm_id": "image", "created": True}]

    monkeypatch.setattr(stm_imaging, "review", review)
    monkeypatch.setattr(stm_imaging, "prepare_files", lambda *_args: ["dat"])
    monkeypatch.setattr(stm_imaging, "publish", publish)

    cls.export_simulation_to_openbis(widget, widget.save_simulations_button)

    assert "Added 1 DAT dataset(s)" in widget.export_status_html.value
    assert "No new DAT files" in widget.microscopy_append_status.value
