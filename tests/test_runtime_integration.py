"""Regression checks for the packaging/ipywidgets merge; no openBIS writes."""

import configparser
from pathlib import Path
from types import SimpleNamespace

import ipywidgets as ipw
import numpy as np
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet


def test_supported_runtime_metadata():
    config = configparser.ConfigParser()
    config.read(Path(__file__).resolve().parents[1] / "setup.cfg")
    options = config["options"]
    assert options["packages"] == "find:"
    python = SpecifierSet(options["python_requires"])
    assert "3.12" in python
    assert "3.11" not in python
    requirements = {
        req.name: req
        for line in options["install_requires"].splitlines()
        if line.strip()
        for req in [Requirement(line)]
    }
    assert "2.8" in requirements["aiida-core"].specifier
    assert "2.7" not in requirements["aiida-core"].specifier
    assert "3.0" not in requirements["aiida-core"].specifier
    assert "0.1.4" in requirements["aiidalab-eln"].specifier
    assert "0.1.3" not in requirements["aiidalab-eln"].specifier


def test_accordion_children_titles_grow_shrink_and_empty():
    from src.sample_preparation_widgets import set_accordion_children_titles

    accordion = ipw.Accordion()
    first, second = ipw.HTML(), ipw.HTML()
    set_accordion_children_titles(accordion, [first, second], ["A", "B"])
    assert accordion.titles == ("A", "B")
    accordion.selected_index = 1
    set_accordion_children_titles(accordion, [first], ["remaining"])
    assert accordion.titles == ("remaining",)
    set_accordion_children_titles(accordion, [], [])
    assert accordion.children == () and accordion.titles == ()
    assert accordion.selected_index is None


def test_observable_history_preserves_master_names(monkeypatch):
    from src import sample_preparation_widgets as module

    dataset = SimpleNamespace(props={"name": "Measured temperature"})
    monkeypatch.setattr(module.utils, "get_openbis_dataset", lambda *args: dataset)
    # No name_html attribute: titles must still come from the dataset properties.
    monkeypatch.setattr(module, "ObservableHistoryWidget", lambda *args: ipw.HTML())
    widget = SimpleNamespace(
        openbis_session=object(),
        openbis_object=SimpleNamespace(
            get_datasets=lambda **kwargs: SimpleNamespace(
                df=SimpleNamespace(permId=SimpleNamespace(values=np.array(["a", "b"])))
            )
        ),
        observables_accordion=ipw.Accordion(),
    )
    module.ProcessStepHistoryWidget.load_observables(widget)
    assert widget.observables_accordion.titles == (
        "Measured temperature",
        "Measured temperature",
    )


def test_template_without_actions_keeps_master_guard():
    from src import sample_preparation_widgets as module

    widget = SimpleNamespace(
        name_textbox=ipw.Text(),
        description_textbox=ipw.Text(),
        comments_textarea=ipw.Textarea(),
    )
    step = SimpleNamespace(
        props={
            "name": "01 - Preparation",
            "description": "",
            "comments": "",
            "actions": None,
        },
        parents=[],
    )
    module.RegisterProcessStepWidget.load_process_step(widget, step)
    assert widget.name_textbox.value == "Preparation"


def test_measurement_logs_survive_runtime_path_reconciliation(tmp_path, monkeypatch):
    """Retain the current measurement helpers while anchoring logs to the app."""
    import json

    from src import utils

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, {}))
    from src import watchdog_widgets as module

    measurement = module.get_measurement_log_filepath(
        "measurement-1", tmp_path / "logs"
    )
    measurement.write_text(json.dumps({"data_folder": "/measurements/scan/"}))
    (measurement.parent / "broken.json").write_text("not JSON")
    assert module.find_measurement_logs_for_folder(
        "/measurements/scan", measurement.parent
    ) == [(measurement, {"data_folder": "/measurements/scan/"})]
    assert module.LOGS_FOLDER == utils.LOG_DIR


def test_offline_preparation_keeps_conditional_widget_imports(monkeypatch):
    """A missing session must not initialise the sample-preparation widgets."""
    import builtins
    import json

    from src import utils

    path = Path(__file__).resolve().parents[1] / "1_sample_preparation.ipynb"
    cells = json.loads(path.read_text())["cells"]
    startup = next(
        "".join(cell.get("source", []))
        for cell in cells
        if "OPENBIS_SESSION, SESSION_DATA" in "".join(cell.get("source", []))
    )
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert not (name == "src" and "create_samples_widget" in fromlist), (
            "Offline startup imported session-dependent widgets"
        )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (None, {}))
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    namespace = {}
    exec(compile(startup, str(path), "exec"), namespace)
    assert namespace["OPENBIS_SESSION"] is None
    assert namespace["openbis_connection_status_htmlbox"].value


def test_offline_chatbot_does_not_construct_agent_with_existing_llm_config():
    """Keep current chatbot behaviour while tolerating an unavailable ELN."""
    import json
    from unittest.mock import Mock

    path = Path(__file__).resolve().parents[1] / "4_openbis_chatbot.ipynb"
    cells = json.loads(path.read_text())["cells"]
    startup = next(
        "".join(cell.get("source", []))
        for cell in cells
        if "OPENBIS_SESSION, SESSION_DATA" in "".join(cell.get("source", []))
    )
    agent = Mock()
    fake_utils = SimpleNamespace(
        read_json=lambda path: {}
        if path.startswith("config/")
        else {
            key: "unused"
            for key in (
                "llm_provider",
                "llm_model",
                "llm_api_key",
                "langfuse_pkey",
                "langfuse_skey",
                "langfuse_host",
            )
        },
        connect_openbis_aiida=lambda: (None, None),
        openbis_connection_status_widget=lambda *_: ipw.HTML("Offline"),
    )
    namespace = {
        "utils": fake_utils,
        "os": SimpleNamespace(environ={}),
        "single_agent": SimpleNamespace(OpenBISAgent=agent),
    }
    exec(compile(startup, str(path), "exec"), namespace)
    agent.assert_not_called()
    url_cell = next(
        "".join(cell.get("source", []))
        for cell in cells
        if "eln_url =" in "".join(cell.get("source", []))
    )
    exec(compile(url_cell, str(path), "exec"), namespace)
    assert namespace["eln_url"] == ""
