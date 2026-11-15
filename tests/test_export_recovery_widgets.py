"""Persistent recovery feedback; no browser or openBIS writes are required."""

from types import SimpleNamespace

import pytest
from test_simulations_widgets import simulations_widgets as _widgets_fixture

from src.export_recovery import ExportCheck, ExportReport, LocalExportMetadataError

simulations_widgets = _widgets_fixture


@pytest.mark.parametrize(
    "state,error,title,retry",
    [
        ("missing", None, "Export incomplete", "Retry incomplete steps"),
        ("unknown", None, "could not be verified", "Verify export and retry"),
        ("complete", None, "Export completed", None),
        (
            "complete",
            LocalExportMetadataError("extras unavailable"),
            "local metadata update failed",
            "Retry local metadata update",
        ),
        (
            "complete",
            RuntimeError("relationship update failed"),
            "could not be verified",
            "Verify export and retry",
        ),
    ],
)
def test_persistent_report_and_retry_action(
    monkeypatch, simulations_widgets, state, error, title, retry
):
    module = simulations_widgets
    widget = SimpleNamespace(
        openbis_session=object(),
        export_status_html=module.ipw.HTML(),
        retry_export_button=module.ipw.Button(),
    )
    monkeypatch.setattr(
        module.export_status,
        "inspect_workchain_export",
        lambda *_args: ExportReport([ExportCheck("result", "Result", state)]),
    )
    module.ExportSimulationsWidget._show_export_report(
        widget, "experiment", "uuid", error
    )
    assert title in widget.export_status_html.value
    assert widget.retry_export_button.layout.display == ("" if retry else "none")
    if retry:
        assert widget.retry_export_button.description == retry


@pytest.mark.parametrize("fails", [False, True])
def test_double_click_guard_and_controls_restored(
    monkeypatch, simulations_widgets, fails
):
    module = simulations_widgets
    widget = SimpleNamespace(
        save_simulations_button=module.ipw.Button(),
        retry_export_button=module.ipw.Button(),
    )
    calls = []

    def export(self, button):
        calls.append(True)
        assert self.save_simulations_button.disabled
        assert self.retry_export_button.disabled
        module.ExportSimulationsWidget.export_simulation_to_openbis(self, button)
        if fails:
            raise RuntimeError("unexpected failure")

    monkeypatch.setattr(
        module.ExportSimulationsWidget, "_export_simulation_to_openbis", export
    )
    if fails:
        with pytest.raises(RuntimeError):
            module.ExportSimulationsWidget.export_simulation_to_openbis(widget, None)
    else:
        module.ExportSimulationsWidget.export_simulation_to_openbis(widget, None)
    assert calls == [True]
    assert not widget._exporting
    assert not widget.save_simulations_button.disabled
    assert not widget.retry_export_button.disabled


@pytest.mark.parametrize("fails", [False, True])
def test_upload_diagnostic_report_survives_failure(
    monkeypatch, simulations_widgets, fails
):
    import base64
    import json
    import re

    from src import upload_diagnostics

    module = simulations_widgets
    widget = SimpleNamespace(
        save_simulations_button=module.ipw.Button(),
        retry_export_button=module.ipw.Button(),
        export_status_html=module.ipw.HTML(value="Existing export status"),
    )

    def export(self, button):
        with upload_diagnostics.phase("dataset_save"):
            if fails:
                raise BrokenPipeError(32, "secret-token-not-for-report")

    monkeypatch.setattr(
        module.ExportSimulationsWidget, "_export_simulation_to_openbis", export
    )
    if fails:
        with pytest.raises(BrokenPipeError):
            module.ExportSimulationsWidget.export_simulation_to_openbis(widget, None)
    else:
        module.ExportSimulationsWidget.export_simulation_to_openbis(widget, None)
    markup = widget.export_status_html.value
    assert "Existing export status" in markup
    assert "Upload diagnostic report" in markup
    payload = base64.b64decode(re.search(r"base64,([^\"]+)", markup).group(1))
    assert b"secret-token-not-for-report" not in payload
    report = json.loads(payload)
    assert report["events"][-1]["event"] == "attempt_finished"
    assert any(event["event"] == "phase_failed" for event in report["events"]) == fails
    assert not widget.save_simulations_button.disabled
