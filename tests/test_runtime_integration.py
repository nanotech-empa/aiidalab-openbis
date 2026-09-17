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
