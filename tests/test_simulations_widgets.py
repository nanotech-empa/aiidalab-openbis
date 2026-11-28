import gc
import importlib
import io
import sys
import weakref
from pathlib import Path
from types import MethodType, SimpleNamespace
from urllib.parse import urlencode

import pandas as pd
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
    sys.modules.pop("src.stm_previews", None)
    module = importlib.import_module("src.simulations_widgets")
    return module


def test_import_handoff_selects_exact_stm_without_import(monkeypatch, simulations_widgets):
    permid = "20261126131236981-4292"
    instance = "https://example.org/openbis"
    session = SimpleNamespace(url=instance + "/")
    widget = simulations_widgets.ImportSimulationsWidget(session)
    calls = []

    def get_object(connection, *, sample_ident):
        assert connection is session
        calls.append(sample_ident)
        return SimpleNamespace(
            permId=permid,
            type="SPM_SIMULATION",
            props={"name": "STM phenalenyl on Au(111)", "aiida_node": "20261126131229794-4287"},
        )

    monkeypatch.setattr(simulations_widgets.utils, "get_openbis_object", get_object)

    def url(server, identifier=permid):
        return "import.ipynb?" + urlencode({"simulation_permid": identifier, "openbis_instance": server})

    widget.select_simulation_from_url(url("https://another.example.org/openbis"))
    assert "another openBIS connection" in widget.import_simulations_message_html.value
    assert widget.import_simulations_button.disabled and not calls
    widget.select_simulation_from_url(url(instance, "28665"))
    assert widget.import_simulations_button.disabled and not calls
    widget.select_simulation_from_url(url(instance))
    assert calls == [permid]
    assert widget.found_simulations_select_multiple.value == (permid,)
    assert "phenalenyl on Au(111)" in widget.found_simulations_select_multiple.options[0][0]
    assert not widget.import_simulations_button.disabled
    assert "Click Import into AiiDA" in widget.import_simulations_message_html.value
    widget.close()


def test_export_link_reviews_source_and_selects_only_a_visible_experiment(simulations_widgets):
    ipw = simulations_widgets.ipw
    cls = simulations_widgets.ExportSimulationsWidget
    source = "84597a7e-f47d-4e09-832b-fd1d6406efb5"
    permid = "20261128-100"
    instance = "https://fixture/openbis"
    selected_sources = []
    project = ipw.Dropdown(options=["-1", "project-id"])
    experiments = ipw.Dropdown(options=["-1"])
    project.observe(lambda change: setattr(experiments, "options", ["-1", permid]), names="value")

    def get_experiment(uid, *, use_cache):
        assert uid == permid and not use_cache
        return SimpleNamespace(identifier="/S/P/E")

    def get_project(identifier):
        assert identifier == "/S/P"
        return SimpleNamespace(permId="project-id")

    widget = SimpleNamespace(
        openbis_session=SimpleNamespace(url=instance, get_experiment=get_experiment, get_project=get_project),
        set_source_uuid=selected_sources.append, export_status_html=ipw.HTML(),
        select_project_widget=SimpleNamespace(project_dropdown=project),
        select_experiment_widget=SimpleNamespace(experiment_dropdown=experiments),
    )
    widget.select_destination_experiment = MethodType(cls.select_destination_experiment, widget)
    def link(**extra):
        return "review.ipynb?" + urlencode(dict(export_uuid=source, **extra))

    assert not cls.prepare_from_url(widget, "review.ipynb?simulation_permid=" + permid)
    assert cls.prepare_from_url(widget, link())
    assert selected_sources == [source] and experiments.value == "-1"
    assert cls.prepare_from_url(widget, link(experiment_permid=permid, openbis_instance="wrong"))
    assert "Could not select" in widget.export_status_html.value
    assert project.value == "-1" and experiments.value == "-1"
    assert cls.prepare_from_url(widget, link(experiment_permid=permid, openbis_instance=instance))
    assert selected_sources[-1] == source and experiments.value == permid


def _stub_project_selector(monkeypatch, module):
    class Project(module.ipw.VBox):
        def __init__(self, session):
            super().__init__()
            self.project_dropdown = module.ipw.Dropdown(
                options=[
                    ("Select", "-1"),
                    ("Project", "project"),
                    ("Empty project", "empty-project"),
                ]
            )

    monkeypatch.setattr(module.widgets, "SelectProjectWidget", Project)


@pytest.mark.parametrize("result_type", ["GEOMETRY_OPTIMISATION", "SPM_SIMULATION"])
def test_export_workflow_starts_with_experiment_then_simulation(
    monkeypatch, simulations_widgets, result_type
):
    _stub_project_selector(monkeypatch, simulations_widgets)
    ipw = simulations_widgets.ipw

    class FakeSelectExperimentWidget(simulations_widgets.widgets.SelectExperimentWidget):
        def __init__(self, session):
            super().__init__(session)
            self.loaded_projects = []

        def load_experiments(self, project):
            self.loaded_projects.append(project)
            self.raw_experiments_df = pd.DataFrame(
                [{"display_name": "Collection", "permId": "collection", "is_mine": True}]
                if project == "project"
                else []
            )
            self.update_experiment_dropdown(None)

    class FakeSimulationDetailsWidget(ipw.VBox):
        def __init__(self, _session, _used_aiida):
            super().__init__()
            self.simulation_pk_input = ipw.IntText()
            self.check_simulation_button = ipw.Button()
            self.target_experiments = []
            self.loaded_sources = []
            self._preview_entries = {
                "result": {"suggestion": {"object_type": result_type}}
            }

        def set_target_experiment(self, experiment):
            self.target_experiments.append(experiment)

        def load_widgets(self, used_aiida):
            self.loaded_sources.append(used_aiida)

    monkeypatch.setattr(
        simulations_widgets.widgets,
        "SelectExperimentWidget",
        FakeSelectExperimentWidget,
    )
    monkeypatch.setattr(
        simulations_widgets,
        "SimulationDetailsWidget",
        FakeSimulationDetailsWidget,
    )

    session = SimpleNamespace(_get_username=lambda: "tester")
    widget = simulations_widgets.ExportSimulationsWidget(session)

    assert list(widget.simulation_source_selector.options) == [
        ("Simulation in this AiiDAlab instance", True),
        ("External simulation or archive", False),
    ]
    assert widget.used_aiida_checkbox is widget.simulation_source_selector
    assert widget.simulation_details_vbox.loaded_sources == [True]
    assert list(widget.children[:6]) == [
        widget.select_experiment_title,
        widget.select_project_widget,
        widget.select_experiment_widget,
        widget.simulation_details_title,
        widget.simulation_source_selector,
        widget.simulation_details_vbox,
    ]
    assert widget.save_simulations_button.description == "Export to openBIS"
    assert widget.save_simulations_button.tooltip == (
        "Export the reviewed simulation to openBIS"
    )
    widget.select_project_widget.project_dropdown.value = "project"
    assert widget.select_experiment_widget.loaded_projects == ["project"]
    widget.select_experiment_widget.experiment_dropdown.value = "collection"
    widget.select_project_widget.project_dropdown.value = "-1"
    assert widget.select_experiment_widget.experiment_dropdown.value == "-1"
    assert widget.simulation_details_vbox.target_experiments[-1] == "-1"

    created, messages, exports = [], [], []

    def create_experiment(openbis, **kwargs):
        assert openbis is session
        created.append(kwargs)
        return SimpleNamespace(permId="new-id")

    monkeypatch.setattr(
        simulations_widgets.utils, "create_openbis_collection", create_experiment
    )
    monkeypatch.setattr(simulations_widgets, "_popup", messages.append)
    monkeypatch.setattr(
        simulations_widgets.ExportSimulationsWidget,
        "_export_simulation_to_openbis",
        lambda _widget, button: exports.append(button),
    )

    selector = widget.select_experiment_widget
    assert selector.create_experiment_button.disabled
    project = widget.select_project_widget.project_dropdown
    project.value = "empty-project"
    assert not selector.create_experiment_button.disabled
    assert selector.create_experiment_button.layout.display != "none"
    assert selector.experiment_dropdown.value == "-1"
    selector.create_experiment_button.click()
    assert selector.create_new_experiment_widgets.children
    selector.new_exp_name_textbox.value = "  "
    selector.save_btn.click()
    assert messages == ["Experiment name cannot be empty."]
    assert not created

    selector.new_exp_name_textbox.value = "Unsaved name"
    project.value = "project"
    assert not selector.create_new_experiment_widgets.children
    assert not selector.new_exp_name_textbox.value
    project.value = "empty-project"
    selector.create_experiment_button.click()
    selector.cancel_btn.click()
    assert not selector.create_new_experiment_widgets.children
    assert not created
    selector.create_experiment_button.click()
    selector.new_exp_name_textbox.value = "  Benzene STM  "
    selector.new_exp_description_textbox.value = "  Microscopy export  "
    selector.filter_my_exp_cb.value = True
    selector.save_btn.click()
    selector.save_btn.click()
    expected_props = {"name": "Benzene STM", "description": "Microscopy export"}
    if result_type == "SPM_SIMULATION":
        expected_props["default_collection_view"] = "IMAGING_GALLERY_VIEW"
    assert created == [
        {
            "type": "EXPERIMENT",
            "project": "empty-project",
            "props": expected_props,
        }
    ]
    assert ("Benzene STM", "new-id") in selector.experiment_dropdown.options
    assert selector.experiment_dropdown.value == "new-id"
    assert widget.simulation_details_vbox.target_experiments[-1] == "new-id"
    assert not exports
    widget.close()


def test_local_export_orders_related_objects_after_pk_and_hides_unavailable_products(
    simulations_widgets,
):
    attribute_names = [
        "simulations_dropdown_hbox",
        "simulation_check_status",
        "related_objects_title",
        "related_objects_help",
        "select_molecules_title",
        "molecules_accordion",
        "add_molecule_button",
        "select_material_title",
        "material_type_dropdown",
        "material_details_vbox",
        "select_reacprod_concepts_title",
        "reacprod_concepts_accordion",
        "add_reacprod_concept_button",
        "preview_suggestions_title",
        "preview_suggestions_status",
        "existing_exports_warning",
        "existing_exports_confirmation",
        "preview_suggestions_box",
    ]
    widget = SimpleNamespace(
        **{name: object() for name in attribute_names},
        product_molecules_available=False,
    )

    simulations_widgets.SimulationDetailsWidget.load_widgets(widget, True)

    assert widget.children == [
        widget.simulations_dropdown_hbox,
        widget.simulation_check_status,
        widget.related_objects_title,
        widget.related_objects_help,
        widget.select_molecules_title,
        widget.molecules_accordion,
        widget.add_molecule_button,
        widget.select_material_title,
        widget.material_type_dropdown,
        widget.material_details_vbox,
        widget.preview_suggestions_title,
        widget.preview_suggestions_status,
        widget.existing_exports_warning,
        widget.existing_exports_confirmation,
        widget.preview_suggestions_box,
    ]
    assert widget.select_reacprod_concepts_title not in widget.children

    widget.product_molecules_available = True
    simulations_widgets.SimulationDetailsWidget.load_widgets(widget, True)

    assert widget.children.index(widget.material_details_vbox) < widget.children.index(
        widget.select_reacprod_concepts_title
    )
    assert widget.children.index(
        widget.add_reacprod_concept_button
    ) < widget.children.index(widget.preview_suggestions_title)


def test_project_selector_uses_bulk_fields_and_correct_owner(
    monkeypatch, simulations_widgets
):
    class Projects:
        df = pd.DataFrame(
            [
                {
                    "code": "DEV",
                    "identifier": "/LAB/DEV",
                    "permId": "project-1",
                    "registrationDate": "2026-11-14",
                    "registrator": "current-user",
                },
                {
                    "code": "OTHER",
                    "identifier": "/LAB/OTHER",
                    "permId": "project-2",
                    "registrationDate": "2026-11-13",
                    "registrator": "another-user",
                },
            ]
        )

        def __iter__(self):
            raise AssertionError("Project wrappers would perform per-field requests")

    monkeypatch.setattr(
        simulations_widgets.widgets.utils, "get_openbis_projects", lambda _: Projects()
    )
    selector = simulations_widgets.widgets.SelectProjectWidget(
        SimpleNamespace(_get_username=lambda: "current-user")
    )
    assert ("DEV from Space LAB", "project-1") in selector.project_dropdown.options
    selector.filter_my_projects_cb.value = True
    assert selector.project_dropdown.options == (
        ("Select project...", "-1"),
        ("DEV from Space LAB", "project-1"),
    )


def test_experiment_selector_uses_bulk_properties(monkeypatch, simulations_widgets):
    class BulkExperiments:
        df = pd.DataFrame(
            [
                {
                    "permId": "experiment-permid",
                    "identifier": "/SPACE/PROJECT/EXP_1",
                    "registrator": "current-user",
                    "NAME": "Fast experiment",
                }
            ]
        )

        def __iter__(self):
            raise AssertionError("bulk experiments must not be iterated")

    calls = []

    def get_collections(_session, **kwargs):
        calls.append(kwargs)
        return BulkExperiments()

    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_collections",
        get_collections,
    )
    session = SimpleNamespace(_get_username=lambda: "current-user")

    widget = simulations_widgets.widgets.SelectExperimentWidget(session)

    # Fabio's separate project selector owns loading; construction stays lazy.
    assert calls == []
    widget.load_experiments("/SPACE/PROJECT")
    assert calls == [
        {"type": "EXPERIMENT", "project": "/SPACE/PROJECT", "props": ["name"]}
    ]
    assert widget.raw_experiments_df.to_dict(orient="records") == [
        {
            "display_name": ("Fast experiment"),
            "permId": "experiment-permid",
            "is_mine": True,
        }
    ]


def test_product_selector_reads_molecules_from_product_collection(
    monkeypatch, simulations_widgets
):
    calls = []
    products = [
        SimpleNamespace(
            permId="product-z",
            props={"name": "Zigzag GNR", "empa_number": None},
        ),
        SimpleNamespace(
            permId="product-a",
            props={"name": "Armchair GNR", "empa_number": None},
        ),
    ]

    def get_objects(_session, **kwargs):
        calls.append(kwargs)
        return products

    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_OBJECT_TYPES,
        "Molecule",
        "MOLECULE",
    )
    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_COLLECTIONS_PATHS,
        "Product Molecule",
        "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION",
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_objects",
        get_objects,
    )

    selector = simulations_widgets.widgets.MoleculeWidget(
        object(),
        simulations_widgets.ipw.Accordion(),
        0,
        collection_key="Product Molecule",
        role="product molecule",
    )

    assert calls == [
        {
            "collection": "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION",
            "type": "MOLECULE",
        }
    ]
    assert list(selector.dropdown.options) == [
        ("Select a product molecule...", "-1"),
        ("Armchair GNR", "product-a"),
        ("Zigzag GNR", "product-z"),
    ]
    assert selector.structure_search.results.value == ""
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_object",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_datasets=lambda **_kwargs: [],
            props=SimpleNamespace(all=lambda: {}),
        ),
    )
    selector._select_search_result("product-a")
    assert selector.dropdown.value == "product-a"


def test_molecule_preview_constrains_only_the_longest_side(
    monkeypatch, simulations_widgets
):
    import struct

    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_OBJECT_TYPES,
        "Molecule",
        "MOLECULE",
    )
    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_COLLECTIONS_PATHS,
        "Product Molecule",
        "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION",
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    selector = simulations_widgets.widgets.MoleculeWidget(
        object(),
        simulations_widgets.ipw.Accordion(),
        0,
        collection_key="Product Molecule",
    )

    def png_header(width, height):
        return (
            b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\x0dIHDR"
            + struct.pack(">II", width, height)
        )

    selector._set_molecule_sketch(png_header(600, 400))
    assert selector.molecule_sketch.width == "300"
    assert selector.molecule_sketch.height == "200"
    assert selector.molecule_sketch.layout.width == "300px"
    assert selector.molecule_sketch.layout.height == "200px"

    selector._set_molecule_sketch(png_header(300, 900))
    assert selector.molecule_sketch.width == "100"
    assert selector.molecule_sketch.height == "300"
    assert selector.molecule_sketch.layout.width == "100px"
    assert selector.molecule_sketch.layout.height == "300px"

    selector._set_molecule_sketch(png_header(150, 100))
    assert selector.molecule_sketch.width == "150"
    assert selector.molecule_sketch.height == "100"
    assert selector.molecule_sketch.layout.width == "150px"
    assert selector.molecule_sketch.layout.height == "100px"


def test_generated_cdxml_can_create_only_after_identity_search(
    monkeypatch, simulations_widgets
):
    from src.chemical_search import search_representation_from_cdxml
    from src.chemical_structures import representation_from_cdxml

    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_OBJECT_TYPES,
        "Molecule",
        "MOLECULE",
    )
    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_COLLECTIONS_PATHS,
        "Product Molecule",
        "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION",
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    selector = simulations_widgets.widgets.MoleculeWidget(
        object(),
        simulations_widgets.ipw.Accordion(),
        0,
        collection_key="Product Molecule",
        role="product molecule",
    )
    cdxml = (Path(__file__).parent / "data" / "periodic_gnr.cdxml").read_bytes()
    representation = representation_from_cdxml(cdxml)
    query = search_representation_from_cdxml(cdxml)
    selector._use_generated_cdxml(
        cdxml,
        "generated-gnr.cdxml",
        b"\x89PNG\r\n\x1a\nreviewed",
        representation,
    )

    selector._search_completed(query, ())

    assert selector.create_generated_button in selector.create_generated_box.children
    assert (
        "product molecule collection" in selector.create_generated_box.children[0].value
    )

    existing = SimpleNamespace(
        match_type="equivalent",
        record=SimpleNamespace(name="Existing GNR", permid="existing"),
    )
    selector.new_molecule_name.value = "Duplicate GNR"
    monkeypatch.setattr(
        selector.structure_search.index, "refresh", lambda **_kwargs: None
    )

    def search_identity(_query, *, min_similarity, limit):
        assert min_similarity == 0.0
        assert limit >= 1
        return [existing]

    monkeypatch.setattr(selector.structure_search.index, "search", search_identity)
    monkeypatch.setattr(
        simulations_widgets.widgets.molecule_creation,
        "create_molecule_from_cdxml",
        lambda *_args, **_kwargs: pytest.fail("duplicate creation must be blocked"),
    )

    selector._create_generated_molecule()

    assert "already exists" in selector.create_generated_box.children[0].value


def test_generated_cdxml_creation_selects_and_verifies_new_product(
    monkeypatch, simulations_widgets
):
    from src.chemical_search import search_representation_from_cdxml
    from src.chemical_structures import representation_from_cdxml

    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_OBJECT_TYPES,
        "Molecule",
        "MOLECULE",
    )
    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_COLLECTIONS_PATHS,
        "Product Molecule",
        "/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION",
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_objects",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_object",
        lambda *_args, **_kwargs: SimpleNamespace(
            get_datasets=lambda **_kwargs: [],
            props=SimpleNamespace(all=dict),
        ),
    )
    selector = simulations_widgets.widgets.MoleculeWidget(
        object(),
        simulations_widgets.ipw.Accordion(),
        0,
        collection_key="Product Molecule",
        role="product molecule",
    )
    cdxml = (Path(__file__).parent / "data" / "periodic_gnr.cdxml").read_bytes()
    representation = representation_from_cdxml(cdxml)
    query = search_representation_from_cdxml(cdxml)
    selector._use_generated_cdxml(
        cdxml,
        "generated-gnr.cdxml",
        b"\x89PNG\r\n\x1a\nreviewed",
        representation,
    )
    selector._search_completed(query, ())
    selector.new_molecule_name.value = "First product GNR"
    created = SimpleNamespace(permId="new-product")
    exact_hit = SimpleNamespace(
        match_type="exact",
        similarity=1.0,
        record=SimpleNamespace(
            permid="new-product",
            name="First product GNR",
            empa_number="",
        ),
    )
    searches = iter([[], [exact_hit]])
    monkeypatch.setattr(
        selector.structure_search.index, "refresh", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        selector.structure_search.index,
        "search",
        lambda *_args, **_kwargs: next(searches),
    )
    calls = []

    def create(_session, **kwargs):
        calls.append(kwargs)
        return created

    monkeypatch.setattr(
        simulations_widgets.widgets.molecule_creation,
        "create_molecule_from_cdxml",
        create,
    )

    selector._create_generated_molecule()

    assert calls[0]["collection"].endswith("/PRODUCT_COLLECTION")
    assert calls[0]["expected_representation"] == representation
    assert selector.dropdown.value == "new-product"
    assert "created, indexed" in selector.create_generated_box.children[0].value
    assert selector.structure_search.last_hits == (exact_hit,)


def test_simulation_add_product_uses_product_molecule_selector(
    monkeypatch, simulations_widgets
):
    calls = []

    class FakeMoleculeWidget(simulations_widgets.ipw.VBox):
        def __init__(self, session, accordion, index, **kwargs):
            super().__init__()
            calls.append((session, accordion, index, kwargs))
            self.dropdown = simulations_widgets.ipw.Dropdown()

    monkeypatch.setattr(
        simulations_widgets.widgets,
        "MoleculeWidget",
        FakeMoleculeWidget,
    )
    accordion = simulations_widgets.ipw.Accordion()
    widget = SimpleNamespace(
        openbis_session=object(),
        reacprod_concepts_accordion=accordion,
    )

    simulations_widgets.SimulationDetailsWidget.add_reacprod_concept(widget, None)

    assert calls == [
        (
            widget.openbis_session,
            accordion,
            0,
            {
                "collection_key": "Product Molecule",
                "role": "product molecule",
            },
        )
    ]
    assert len(accordion.children) == 1


def test_atom_model_selector_uses_bulk_names(monkeypatch, simulations_widgets):
    class BulkAtomModels:
        df = pd.DataFrame(
            [
                {"permId": "model-2", "NAME": "Zinc"},
                {"permId": "model-1", "NAME": None},
            ]
        )

        def __iter__(self):
            raise AssertionError("bulk atomistic models must not be iterated")

    calls = []

    def get_objects(_session, **kwargs):
        calls.append(kwargs)
        return BulkAtomModels()

    monkeypatch.setitem(
        simulations_widgets.widgets.OPENBIS_OBJECT_TYPES,
        "Atomistic Model",
        "ATOMISTIC_MODEL",
    )
    monkeypatch.setattr(
        simulations_widgets.widgets.utils,
        "get_openbis_objects",
        get_objects,
    )

    widget = simulations_widgets.widgets.AtomModelWidget(object())

    assert calls == [{"type": "ATOMISTIC_MODEL", "props": ["name"]}]
    assert list(widget.atom_model_dropdown.options) == [
        ("Select atomistic model...", "-1"),
        ("Zinc", "model-2"),
        ("model-1", "model-1"),
    ]


def test_external_export_inventories_are_loaded_lazily(
    monkeypatch, simulations_widgets
):
    ipw = simulations_widgets.ipw
    object_types = simulations_widgets.OPENBIS_OBJECT_TYPES
    calls = []

    class BulkObjects:
        def __init__(self, records):
            self.df = pd.DataFrame(records)

        def __iter__(self):
            raise AssertionError("bulk inventories must not be iterated")

    class FakeAtomModelWidget(ipw.VBox):
        def __init__(self, _session):
            super().__init__()
            calls.append(("atom-model-widget", {}))

    inventories = {
        object_types["Executable"]: [
            {
                "permId": "executable-permid",
                "NAME": "cp2k-2024.3",
                "CODE": "code-permid",
                "COMPUTER": "computer-permid",
            }
        ],
        object_types["Code"]: [{"permId": "code-permid", "NAME": "CP2K"}],
        object_types["Computer"]: [{"permId": "computer-permid", "NAME": "Daint"}],
    }

    def get_objects(_session, **kwargs):
        calls.append((kwargs["type"], kwargs))
        return BulkObjects(inventories[kwargs["type"]])

    monkeypatch.setattr(
        simulations_widgets.widgets,
        "AtomModelWidget",
        FakeAtomModelWidget,
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_objects",
        get_objects,
    )

    widget = simulations_widgets.SimulationDetailsWidget(object(), True)

    assert calls == []

    widget.load_widgets(False)

    assert [call[0] for call in calls] == [
        "atom-model-widget",
        object_types["Executable"],
        object_types["Code"],
        object_types["Computer"],
    ]
    assert list(widget.executables_multi_selector.options) == [
        (
            "cp2k-2024.3; code CP2K; computer Daint",
            "executable-permid",
        )
    ]

    widget.load_widgets(True)
    widget.load_widgets(False)

    assert len(calls) == 4


def test_preview_image_widget_resamples_without_distortion(simulations_widgets):
    from PIL import Image

    content = io.BytesIO()
    Image.new("RGB", (1600, 900), color="white").save(content, format="PNG")

    widget = simulations_widgets._preview_image_widget(
        content.getvalue(), "preview.png"
    )

    assert widget.width == "500"
    assert widget.height == "281"
    with Image.open(io.BytesIO(widget.value)) as image:
        assert image.size == (500, 281)


@pytest.fixture
def preview_details(monkeypatch, simulations_widgets):
    """Real details widget with only server-backed selectors replaced."""
    monkeypatch.setattr(
        simulations_widgets.widgets,
        "AtomModelWidget",
        lambda _session: simulations_widgets.ipw.VBox(),
    )
    monkeypatch.setattr(
        simulations_widgets.utils, "get_openbis_objects", lambda *_args, **_kwargs: []
    )
    widget = simulations_widgets.SimulationDetailsWidget(object(), True)
    widget.simulations_dropdown.options = [("test workflow", 1)]
    widget.target_experiment_id = "test-collection"
    yield widget
    widget.close()


def _preview_suggestion(simulations_widgets, *, existing):
    from PIL import Image

    content = io.BytesIO()
    Image.new("RGB", (32, 16), color="white").save(content, format="PNG")
    return {
        "key": "test:bands",
        "title": "Test bands",
        "result_role": "bands",
        "object_type": "BAND_STRUCTURE",
        "properties": {"name": "Test bands", "method_family": "DFT"},
        "name": "bands.png",
        "content": content.getvalue(),
        "needs_preview": True,
        "export_checks": [
            simulations_widgets.export_recovery.ExportCheck(
                "test/object", "Bands", "complete"
            )
        ],
        "existing": {"permid": "saved-bands"} if existing else None,
    }


@pytest.mark.parametrize("existing", [True, False])
def test_preview_refresh_releases_previous_cards(
    monkeypatch, simulations_widgets, preview_details, existing
):
    from ipywidgets.widgets.widget import _instances

    suggestion = _preview_suggestion(simulations_widgets, existing=existing)
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "render_workchain_preview_suggestions",
        lambda *_args, **_kwargs: [suggestion],
    )
    baseline = set(_instances)
    removed = []
    for _ in range(20):
        preview_details.load_aiida_preview_suggestions()
        uploader = preview_details._preview_entries["test:bands"]["uploader"]
        removed.append(weakref.ref(uploader))
        preview_details._clear_preview_suggestions()
        assert uploader.value == ()
        assert not uploader._trait_notifiers.get("value", {}).get("change", [])
        del uploader
    gc.collect()
    assert all(ref() is None for ref in removed)
    assert set(_instances) == baseline


def test_replacement_preview_releases_old_image(
    monkeypatch, simulations_widgets, preview_details
):
    from datetime import datetime, timezone
    from ipywidgets.widgets.widget import _instances

    suggestion = _preview_suggestion(simulations_widgets, existing=False)
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "render_workchain_preview_suggestions",
        lambda *_args, **_kwargs: [suggestion],
    )
    preview_details.load_aiida_preview_suggestions()
    baseline = set(_instances)
    entry = preview_details._preview_entries["test:bands"]
    card = preview_details.preview_suggestions_box.children[0]
    image_box = card.children[4]
    previous = image_box.children[0]
    uploaded = {
        "name": "replacement.png",
        "type": "image/png",
        "size": len(suggestion["content"]),
        "content": memoryview(suggestion["content"]),
        "last_modified": datetime.now(timezone.utc),
    }
    entry["uploader"].value = (uploaded,)
    assert previous.comm is None
    assert not previous.value
    assert image_box.children[0].value
    assert len(_instances) == len(baseline)
    assert (
        preview_details.preview_overrides()["test:bands"]["content"]
        == suggestion["content"]
    )


def test_property_form_replacement_does_not_accumulate_widgets(simulations_widgets):
    from ipywidgets.widgets.widget import _instances

    widget = simulations_widgets.SimulationPropertiesWidget(object())
    baseline = set(_instances)
    for _ in range(20):
        widget.load_widgets("BAND_STRUCTURE")
        widget.load_widgets("-1")
        assert set(_instances) == baseline
        assert widget.title.comm is not None
    widget.close()
    widget.close()


@pytest.mark.parametrize("switch_modes", [False, True])
def test_details_close_releases_hidden_owned_forms(
    monkeypatch, simulations_widgets, switch_modes
):
    from ipywidgets.widgets.widget import _instances

    monkeypatch.setattr(
        simulations_widgets.widgets,
        "AtomModelWidget",
        lambda _session: simulations_widgets.ipw.VBox(),
    )
    monkeypatch.setattr(
        simulations_widgets.utils, "get_openbis_objects", lambda *_args, **_kwargs: []
    )
    baseline = set(_instances)
    widget = simulations_widgets.SimulationDetailsWidget(object(), True)
    if switch_modes:
        widget.load_widgets(False)
        widget.load_widgets(True)
    reference = weakref.ref(widget)
    widget.close()
    widget.close()
    del widget
    gc.collect()
    assert reference() is None
    assert set(_instances) == baseline


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


def test_aiida_export_links_selected_molecule_to_atomistic_model(
    monkeypatch, simulations_widgets
):
    molecule_permid = "molecule-permid"
    atomistic_model = SimpleNamespace(parents=["slab-permid"])
    exported_result = SimpleNamespace(
        permId="simulation-permid",
        parents=[],
        props={"name": "Geometry optimization"},
        _aiidalab_created=True,
    )
    updated = []
    messages = []
    from src.export_recovery import ExportCheck, ExportReport

    monkeypatch.setattr(
        simulations_widgets.export_status,
        "inspect_workchain_export",
        lambda *_args: ExportReport([ExportCheck("result", "Result", "complete")]),
    )

    monkeypatch.setattr(simulations_widgets, "_popup", messages.append)
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "export_workchain",
        lambda *_args, **_kwargs: exported_result,
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "normalize_exported_objects",
        lambda exported: [exported],
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "_openbis_eln_url",
        lambda _object: "",
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "find_first_atomistic_model",
        lambda *_args, **_kwargs: atomistic_model,
    )
    monkeypatch.setattr(
        simulations_widgets.utils,
        "update_openbis_object",
        updated.append,
    )

    widget = SimpleNamespace(
        openbis_session=object(),
        select_experiment_widget=SimpleNamespace(
            experiment_dropdown=SimpleNamespace(value="experiment-permid")
        ),
        simulation_details_vbox=SimpleNamespace(
            molecules_accordion=SimpleNamespace(
                children=[
                    SimpleNamespace(dropdown=SimpleNamespace(value=molecule_permid))
                ]
            ),
            reacprod_concepts_accordion=SimpleNamespace(children=[]),
            material_type_dropdown=SimpleNamespace(value="-1"),
            simulations_dropdown=SimpleNamespace(value="workflow-uuid"),
            preview_overrides=dict,
            property_overrides=dict,
            _preview_entries={"workflow-uuid:geometry_optimization": {}},
        ),
        used_aiida_checkbox=SimpleNamespace(value=True),
        _apply_pending_reference_resolution=lambda: True,
        _apply_executable_selections=lambda: (True, False),
        _provenance_overrides={},
        _clear_resolution_controls=lambda: None,
        export_message_html=SimpleNamespace(value=""),
        export_status_html=SimpleNamespace(value=""),
        retry_export_button=SimpleNamespace(layout=SimpleNamespace(display="none")),
    )

    simulations_widgets.ExportSimulationsWidget.export_simulation_to_openbis(
        widget, None
    )

    assert atomistic_model.parents == ["slab-permid", molecule_permid]
    assert updated == [atomistic_model]
    assert messages == ["Exported 1 simulation result(s) successfully."]


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
        props={"wfms_uuid": "11111111-1111-1111-1111-111111111111"},
        get_datasets=lambda: [dataset],
    )
    workchain = object()

    monkeypatch.setattr(
        simulations_widgets.utils,
        "get_openbis_object",
        lambda *_args, **_kwargs: aiida_node,
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_archives,
        "validate_root",
        lambda path, uuid: uuid if path.read_bytes() == b"archive" else None,
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
        lambda uuid: (
            workchain if uuid == "11111111-1111-1111-1111-111111111111" else None
        ),
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


def test_declared_archive_root_requires_one_scalar_uuid(simulations_widgets):
    uuid = "11111111-1111-1111-1111-111111111111"
    node = SimpleNamespace(props={"wfms_uuid": uuid})
    assert simulations_widgets._declared_archive_root_uuid(node) == uuid
    for invalid in (None, "", [uuid], uuid + "," + uuid):
        node.props = {"wfms_uuid": invalid}
        with pytest.raises(ValueError, match="WFMS_UUID"):
            simulations_widgets._declared_archive_root_uuid(node)


def test_multivalue_root_property_is_not_provisioned(simulations_widgets):
    schema = simulations_widgets.simulation_schema
    assert "AIIDA_ROOT_UUIDS" not in schema.PROPERTY_TYPES
    assert "AIIDA_NODE" not in schema.ADDITIVE_OBJECT_TYPE_ASSIGNMENTS


def test_absolute_magnetization_schema_is_optional_and_additive(
    simulations_widgets,
):
    schema = simulations_widgets.simulation_schema
    definition = schema.PROPERTY_TYPES["ABSOLUTE_MAGNETIZATION_BOHR_MAGNETON"]

    assert definition["dataType"] == "REAL"
    for object_code, object_definition in schema.OBJECT_TYPES.items():
        property_codes = [item["code"] for item in object_definition["assignments"]]
        if "TOTAL_MAGNETIZATION_BOHR_MAGNETON" not in property_codes:
            continue
        additions = schema.ADDITIVE_OBJECT_TYPE_ASSIGNMENTS[object_code]
        assert property_codes[-len(additions) :] == [item["code"] for item in additions]
        assert additions[0] == {
            "code": "ABSOLUTE_MAGNETIZATION_BOHR_MAGNETON",
            "mandatory": False,
            "section": "Electronic properties",
        }


def test_spm_gallery_field_is_an_optional_additive_assignment(simulations_widgets):
    schema = simulations_widgets.simulation_schema
    definition = schema.PROPERTY_TYPES["DEFAULT_OBJECT_VIEW"]
    assert definition["vocabulary"] == "DEFAULT_OBJECT_VIEWS"
    assert definition["dataType"] == "CONTROLLEDVOCABULARY"
    assert not definition["multiValue"]
    assert schema.ADDITIVE_OBJECT_TYPE_ASSIGNMENTS["SPM_SIMULATION"][-1] == {
        "code": "DEFAULT_OBJECT_VIEW",
        "mandatory": False,
        "section": "General information",
    }
    assert all(
        item["code"] != "DEFAULT_OBJECT_VIEW"
        for item in schema.base_assignments(
            "SPM_SIMULATION", schema.OBJECT_TYPES["SPM_SIMULATION"]["assignments"]
        )
    )


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

    message = simulations_widgets.ImportSimulationsWidget._import_success_message(
        simulations,
        roots,
    )

    assert "Root processes (2)" in message
    assert "11111111-1111-1111-1111-111111111111" in message
    assert "22222222-2222-2222-2222-222222222222" in message
    assert "viewer.ipynb?pk=11" in message


def test_manual_upload_rejects_multiple_aiida_archives(simulations_widgets):
    uploader = SimpleNamespace(
        value=(
            {"name": "first.aiida", "content": b"one"},
            {"name": "second.AIIDA", "content": b"two"},
        )
    )

    with pytest.raises(ValueError, match="at most one"):
        simulations_widgets.ExportSimulationsWidget._uploaded_aiida_archive(uploader)


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
        file_list = ("original/export.aiida",)

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


def test_property_overrides_are_collected_only_for_new_results(
    simulations_widgets,
):
    widget = SimpleNamespace(
        _preview_entries={
            "source:bands": {
                "property_widget": SimpleNamespace(
                    values=lambda include_empty: {"name": "Edited bands"}
                ),
                "existing": False,
            },
            "source:geometry_optimization": {
                "existing": True,
            },
        }
    )

    assert simulations_widgets.SimulationDetailsWidget.property_overrides(widget) == {
        "source:bands": {"name": "Edited bands"}
    }


@pytest.mark.parametrize(
    ("process_label", "simulation_type", "viewer"),
    [
        ("Cp2kScfWorkChain", "BAND_UNFOLDING", "view_cp2k_unfolding.ipynb"),
        ("Cp2kReplicaWorkChain", "MINIMUM_ENERGY_PATH", "view_replica.ipynb"),
        ("Cp2kPdosWorkChain", "DOS", "view_pdos.ipynb"),
    ],
)
def test_cp2k_imports_route_to_installed_viewers(
    simulations_widgets,
    process_label,
    simulation_type,
    viewer,
):
    simulations = [_simulation("Imported result", "sim-1", simulation_type)]
    workchain = SimpleNamespace(
        process_label=process_label,
        pk=42,
        uuid="workflow-uuid",
    )

    link = simulations_widgets.ImportSimulationsWidget._import_success_message(
        simulations, workchain
    )

    assert f"{viewer}?pk=42" in link


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
            "source:geometry_optimization": {
                "suggestion": {"title": "Geometry optimization"},
                "existing": True,
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


def test_existing_result_is_shown_as_status_without_editor(
    monkeypatch,
    simulations_widgets,
):
    suggestion = {
        "key": "source:geometry_optimization",
        "result_role": "geometry_optimization",
        "export_checks": [
            simulations_widgets.export_recovery.ExportCheck(
                "source:geometry_optimization/object",
                "Geometry optimization",
                "complete",
            )
        ],
        "existing": {
            "permid": "existing-permid",
            "url": "https://openbis.example/existing",
        },
    }
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "render_workchain_preview_suggestions",
        lambda *_args, **_kwargs: [suggestion],
    )
    suggestion["accessible_existing"] = [
        {
            "permid": "existing-permid",
            "name": "Existing geometry",
            "url": "https://openbis.example/existing",
            "collection": "/SPACE/PROJECT/COLLECTION",
        }
    ]
    widget = SimpleNamespace(
        _preview_entries={},
        preview_suggestions_box=SimpleNamespace(children=[]),
        existing_exports_warning=SimpleNamespace(value=""),
        existing_exports_confirmation=simulations_widgets.ipw.Checkbox(
            layout=simulations_widgets.ipw.Layout(display="none")
        ),
        simulations_dropdown=SimpleNamespace(value=6708),
        target_experiment_id="experiment-permid",
        preview_suggestions_status=SimpleNamespace(value=""),
        openbis_session=object(),
    )

    widget._clear_preview_suggestions = MethodType(
        simulations_widgets.SimulationDetailsWidget._clear_preview_suggestions, widget
    )
    simulations_widgets.SimulationDetailsWidget.load_aiida_preview_suggestions(widget)

    assert widget._preview_entries == {
        "source:geometry_optimization": {
            "suggestion": suggestion,
            "existing": True,
        }
    }
    assert len(widget.preview_suggestions_box.children) == 1
    status = widget.preview_suggestions_box.children[0].value
    assert "Geometry optimization" in status
    assert "already present" in status
    assert "open in openBIS" in status
    assert "1 already present" in widget.preview_suggestions_status.value
    assert "already has simulation results" in widget.existing_exports_warning.value
    assert widget.existing_exports_confirmation.layout.display == ""
    assert widget.existing_exports_confirmation.value is False


def test_target_experiment_refreshes_checked_simulation(simulations_widgets):
    calls = []
    widget = SimpleNamespace(
        target_experiment_id="-1",
        simulations_dropdown=SimpleNamespace(value=6708),
        load_aiida_preview_suggestions=lambda: calls.append(True),
    )

    simulations_widgets.SimulationDetailsWidget.set_target_experiment(
        widget,
        "experiment-permid",
    )

    assert widget.target_experiment_id == "experiment-permid"
    assert calls == [True]


def test_new_pk_clears_previous_export_feedback(simulations_widgets):
    cleared = []
    widget = SimpleNamespace(
        export_message_html=SimpleNamespace(value="old openBIS links"),
        _clear_resolution_controls=lambda: cleared.append(True),
    )

    simulations_widgets.ExportSimulationsWidget._clear_previous_export_feedback(widget)

    assert widget.export_message_html.value == ""
    assert cleared == [True]


def test_clear_all_resets_import_search(simulations_widgets):
    widget = SimpleNamespace(
        molecules_accordion=SimpleNamespace(children=[object()]),
        reacprod_concepts_accordion=SimpleNamespace(children=[object()]),
        material_type_dropdown=SimpleNamespace(value="SLAB"),
        material_details_vbox=SimpleNamespace(children=[object()]),
        name_search_text=SimpleNamespace(value="name"),
        comments_search_text=SimpleNamespace(value="comments"),
        text_match_mode_dropdown=SimpleNamespace(value="all_words"),
        simulation_type_search_dropdown=SimpleNamespace(value="DOS"),
        archive_status_dropdown=SimpleNamespace(value="archive"),
        search_logical_operator_dropdown=SimpleNamespace(value="OR", disabled=False),
        search_operator_help=SimpleNamespace(value="old"),
        found_simulations_select_multiple=SimpleNamespace(
            value=("result",), options=(("Result", "result"),)
        ),
        found_simulations_label=SimpleNamespace(value="Found simulations: 1"),
        _simulation_archive_by_permid={"result": True},
        import_simulations_message_html=SimpleNamespace(value="old"),
        download_simulation_data_message_html=SimpleNamespace(value="old"),
        _update_action_buttons=lambda: None,
    )

    simulations_widgets.ImportSimulationsWidget.clear_simulation_selection(widget)

    assert widget.molecules_accordion.children == []
    assert widget.reacprod_concepts_accordion.children == []
    assert widget.material_type_dropdown.value == "-1"
    assert widget.name_search_text.value == ""
    assert widget.comments_search_text.value == ""
    assert widget.text_match_mode_dropdown.value == "fuzzy"
    assert widget.simulation_type_search_dropdown.value == ""
    assert widget.archive_status_dropdown.value == "all"
    assert widget.search_logical_operator_dropdown.value == "AND"
    assert widget.search_logical_operator_dropdown.disabled is True
    assert widget.found_simulations_select_multiple.options == ()
    assert widget.found_simulations_label.value == "Found simulations: 0"
    assert widget._simulation_archive_by_permid == {}


def test_existing_export_confirmation_is_required(simulations_widgets):
    checkbox = simulations_widgets.ipw.Checkbox(
        value=False, layout=simulations_widgets.ipw.Layout(display="")
    )
    widget = SimpleNamespace(existing_exports_confirmation=checkbox)

    assert not simulations_widgets.SimulationDetailsWidget.existing_export_confirmed(
        widget
    )
    assert not simulations_widgets.SimulationDetailsWidget.duplicate_existing_requested(
        widget
    )
    checkbox.value = True
    assert simulations_widgets.SimulationDetailsWidget.existing_export_confirmed(widget)
    assert simulations_widgets.SimulationDetailsWidget.duplicate_existing_requested(
        widget
    )
    checkbox.layout.display = "none"
    assert not simulations_widgets.SimulationDetailsWidget.duplicate_existing_requested(
        widget
    )


def test_inferred_molecules_are_prepopulated_and_replaced(
    monkeypatch,
    simulations_widgets,
):
    class FakeMoleculeWidget(simulations_widgets.ipw.VBox):
        def __init__(self, _session, _accordion, object_index):
            super().__init__()
            self.object_index = object_index
            self.title = ""
            self.dropdown = simulations_widgets.ipw.Dropdown(
                options=[("Select a molecule...", "-1")], value="-1"
            )

    molecule = SimpleNamespace(
        permId="molecule-permid",
        props={"name": "methane", "empa_number": "1001"},
    )
    structure = object()
    accordion = simulations_widgets.ipw.Accordion()
    widget = SimpleNamespace(
        openbis_session=object(),
        molecules_accordion=accordion,
    )
    monkeypatch.setattr(
        simulations_widgets.widgets, "MoleculeWidget", FakeMoleculeWidget
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "openbis_molecules_for_input_structure",
        lambda _session, _structure: (molecule,),
    )

    simulations_widgets.SimulationDetailsWidget._populate_inferred_molecules(
        widget,
        SimpleNamespace(inputs=SimpleNamespace(structure=structure)),
    )

    inferred = accordion.children[0]
    assert inferred.dropdown.value == molecule.permId
    assert getattr(inferred, simulations_widgets._INFERRED_MOLECULE_ATTR) is True

    manual = FakeMoleculeWidget(None, accordion, 1)
    manual.dropdown.options = [
        ("Select a molecule...", "-1"),
        ("305 (example)", "manual-permid"),
    ]
    manual.dropdown.value = "manual-permid"
    manual.title = "example"
    accordion.children = [inferred, manual]

    simulations_widgets.SimulationDetailsWidget._clear_inferred_molecules(widget)

    assert accordion.children == (manual,)
    assert inferred.comm is None
    assert manual.comm is not None
    assert accordion.comm is not None
    assert manual.object_index == 0
    assert manual.dropdown.value == "manual-permid"


def test_unsupported_pk_clears_previous_preview_state(
    monkeypatch,
    simulations_widgets,
):
    unsupported = SimpleNamespace(pk=6136, process_label="UnsupportedWorkChain")
    monkeypatch.setattr(simulations_widgets.orm, "load_node", lambda _pk: unsupported)
    widget = SimpleNamespace(
        simulation_check_status=SimpleNamespace(value="old status"),
        _preview_entries={"old": {}},
        preview_suggestions_box=SimpleNamespace(
            children=[simulations_widgets.ipw.HTML()]
        ),
        preview_suggestions_status=SimpleNamespace(value="old preview status"),
        simulations_dropdown=SimpleNamespace(
            options=[("Old workflow", 1)],
            value=1,
        ),
        simulation_pk_input=SimpleNamespace(value=6136),
        _clear_inferred_molecules=lambda: None,
        _exportable_ancestor=lambda _node: None,
    )

    widget._clear_preview_suggestions = MethodType(
        simulations_widgets.SimulationDetailsWidget._clear_preview_suggestions, widget
    )
    widget.clear_checked_simulation = MethodType(
        simulations_widgets.SimulationDetailsWidget.clear_checked_simulation, widget
    )
    simulations_widgets.SimulationDetailsWidget.check_aiida_simulation(widget)

    assert widget._preview_entries == {}
    assert widget.preview_suggestions_box.children == []
    assert widget.preview_suggestions_status.value == ""
    assert widget.simulations_dropdown.value == "-1"
    assert "unsupported workflow" in widget.simulation_check_status.value


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

    expanded = simulations_widgets.ImportSimulationsWidget._simulation_dependencies(
        widget, [neb]
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


def test_spm_editor_uses_multi_mode_checkboxes_and_numeric_lists(
    simulations_widgets,
):
    widget = simulations_widgets.SimulationPropertiesWidget(object())
    widget.load_widgets("SPM_SIMULATION")
    widget.set_values(
        {
            "name": "STM and STS test",
            "method_family": "DFT",
            "charge": 0.0,
            "spm_mode": ["STM", "STS"],
            "image_modes": ["CONSTANT_HEIGHT", "CONSTANT_ISOVALUE"],
            "bias_voltages_v": [-1.0, 0.0, 1.0],
            "heights_angstrom": [4.0, 6.0],
            "isovalues_au": [1e-7],
            "p_tip_ratios": "0.0",
        }
    )

    assert isinstance(
        widget.fields["SPM_MODE"], simulations_widgets.MultiCheckboxWidget
    )
    assert widget.fields["SPM_MODE"].value == ("STM", "STS")
    assert widget.fields["IMAGE_MODES"].value == (
        "CONSTANT_HEIGHT",
        "CONSTANT_ISOVALUE",
    )
    values = widget.values()
    assert values["bias_voltages_v"] == [-1.0, 0.0, 1.0]
    assert values["heights_angstrom"] == [4.0, 6.0]
    assert values["isovalues_au"] == [1e-7]
    assert values["p_tip_ratios"] == [0.0]

    widget.fields["HEIGHTS_ANGSTROM"].value = "[6.0, 4.0]"
    assert widget.values()["heights_angstrom"] == [6.0, 4.0]
    widget.fields["ISOVALUES_AU"].value = "[]"
    assert widget.values(include_empty=True)["isovalues_au"] is None
    widget.fields["ISOVALUES_AU"].value = "[NaN]"
    with pytest.raises(ValueError, match="finite numbers"):
        widget.values()


def test_simulation_add_product_offers_checked_aiida_structure(
    monkeypatch, simulations_widgets
):
    calls = []

    class FakeMoleculeWidget(simulations_widgets.ipw.VBox):
        def __init__(self, session, accordion, index, **kwargs):
            super().__init__()
            calls.append((session, accordion, index, kwargs))

    monkeypatch.setattr(
        simulations_widgets.widgets,
        "MoleculeWidget",
        FakeMoleculeWidget,
    )
    structure = object()
    monkeypatch.setattr(
        simulations_widgets.orm,
        "load_node",
        lambda uuid: SimpleNamespace(inputs=SimpleNamespace(structure=structure)),
    )
    accordion = simulations_widgets.ipw.Accordion()
    widget = SimpleNamespace(
        openbis_session=object(),
        reacprod_concepts_accordion=accordion,
        _checked_workchain="checked-workflow-uuid",
    )

    simulations_widgets.SimulationDetailsWidget.add_reacprod_concept(widget, None)

    assert calls[0][3] == {
        "collection_key": "Product Molecule",
        "role": "product molecule",
        "structure": structure,
    }


def test_prefilled_shared_form_reviews_whole_entry_without_source_picker(
    monkeypatch, simulations_widgets
):
    _stub_project_selector(monkeypatch, simulations_widgets)
    ipw = simulations_widgets.ipw

    class Experiment(simulations_widgets.widgets.SelectExperimentWidget):
        def __init__(self, session):
            super().__init__(session)
            self.experiment_dropdown.options = [
                ("Select", "-1"), ("Chosen experiment", "experiment")
            ]

    class Details(ipw.VBox):
        def __init__(self, session, used_aiida):
            super().__init__()
            self.simulation_pk_input = ipw.IntText()
            self.check_simulation_button = ipw.Button()
            self.manual_molecules = ["selected-molecule"]
            self.source_history = []
            self.checks = 0

        def set_target_experiment(self, value):
            self.target = value

        def load_widgets(self, value):
            pass

        def set_process_uuid(self, uid):
            self.simulation_pk_input.value = 10
            self.source_history.append(uid)

        def check_aiida_simulation(self):
            self.checks += 1

    monkeypatch.setattr(
        simulations_widgets.widgets, "SelectExperimentWidget", Experiment
    )
    monkeypatch.setattr(simulations_widgets, "SimulationDetailsWidget", Details)
    widget = simulations_widgets.ExportSimulationsWidget(
        SimpleNamespace(_get_username=lambda: "tester"), source_uuid="geometry-uuid"
    )
    details = widget.simulation_details_vbox
    assert not hasattr(widget, "source_selection")
    assert details.source_history == ["geometry-uuid"]
    assert details.checks == 1
    assert details.simulation_pk_input.disabled
    assert details.simulation_pk_input.layout.display == "none"
    assert widget.simulation_source_selector.layout.display == "none"
    assert details.check_simulation_button.description == "Refresh entry results"
    assert details.check_simulation_button.layout.width == "auto"
    widget.select_experiment_widget.experiment_dropdown.value = "experiment"
    widget.set_source_uuid("geometry-uuid")
    assert widget.simulation_details_vbox is details
    assert details.target == "experiment"
    assert details.manual_molecules == ["selected-molecule"]
    assert details.checks == 2
    widget._exporting = True
    widget.set_source_uuid("another-entry")
    assert details.source_history == ["geometry-uuid", "geometry-uuid"]
    widget._exporting = False
    widget.close()


def test_molecule_name_filter_matches_names_numbers_ids_and_keeps_selected_link(
    monkeypatch, simulations_widgets
):
    w = simulations_widgets.widgets
    objects = [
        SimpleNamespace(
            permId="benzene-id", props={"name": "Benzene", "empa_number": 123}
        ),
        SimpleNamespace(
            permId="phenal-id", props={"name": "Phenalenyl radical", "empa_number": 456}
        ),
        SimpleNamespace(
            permId="benzene-other",
            props={"name": "Benzene derivative", "empa_number": 789},
        ),
    ]
    reads = []
    changes = []
    monkeypatch.setitem(w.OPENBIS_OBJECT_TYPES, "Molecule", "MOLECULE")
    monkeypatch.setitem(
        w.OPENBIS_COLLECTIONS_PATHS, "Precursor Molecule", "/TEST/MOLECULES"
    )
    monkeypatch.setattr(
        w.utils,
        "get_openbis_objects",
        lambda *args, **kwargs: reads.append(kwargs) or objects,
    )
    monkeypatch.setattr(
        w.MoleculeWidget,
        "load_details",
        lambda self, change: changes.append(change["new"]),
    )
    selector = w.MoleculeWidget(object(), simulations_widgets.ipw.Accordion(), 0)
    original = list(selector.dropdown.options)
    selector.name_search.value = "BENZ"
    assert [v for _, v in selector.dropdown.options] == [
        "-1",
        "benzene-other",
        "benzene-id",
    ]
    selector.dropdown.value = "benzene-id"
    assert changes == ["benzene-id"]
    external = []
    selector.dropdown.observe(
        lambda change: external.append(change["new"]), names="value"
    )
    selector.name_search.value = "phenal"
    assert (
        selector.dropdown.value == "benzene-id"
        and selector.dropdown.options[0][1] == "benzene-id"
    )
    assert external == [] and changes == ["benzene-id"]
    assert "1 matching" in selector.name_search_status.value
    selector.name_search.value = "456"
    assert any(v == "phenal-id" for _, v in selector.dropdown.options)
    selector.name_search.value = "benzene-other"
    assert any(v == "benzene-other" for _, v in selector.dropdown.options)
    selector.name_search.value = "does-not-exist"
    assert selector.dropdown.value == "benzene-id"
    selector.name_search.value = ""
    assert {v for _, v in selector.dropdown.options} == {v for _, v in original}
    assert len(reads) == 1 and external == []


def test_molecule_filter_retains_a_new_structural_search_selection(
    monkeypatch, simulations_widgets
):
    w = simulations_widgets.widgets
    monkeypatch.setitem(w.OPENBIS_OBJECT_TYPES, "Molecule", "MOLECULE")
    monkeypatch.setitem(
        w.OPENBIS_COLLECTIONS_PATHS, "Product Molecule", "/TEST/PRODUCTS"
    )
    monkeypatch.setattr(w.utils, "get_openbis_objects", lambda *args, **kwargs: [])
    monkeypatch.setattr(w.MoleculeWidget, "load_details", lambda *_: None)
    selector = w.MoleculeWidget(
        object(),
        simulations_widgets.ipw.Accordion(),
        0,
        collection_key="Product Molecule",
    )
    selector.structure_search._hits_by_permid = {
        "new-benzene": SimpleNamespace(
            record=SimpleNamespace(name="Benzene from structural search")
        )
    }
    selector._select_search_result("new-benzene")
    selector.name_search.value = "other"
    assert selector.dropdown.value == "new-benzene"
    selector.name_search.value = "BENZENE"
    assert any(v == "new-benzene" for _, v in selector.dropdown.options)


def _stm_preview_fixture(monkeypatch, module):
    """Stored arrays with deliberately distinct STS, STM and uniform frames."""
    import numpy as np

    picker_module = importlib.import_module(module.__package__ + ".stm_previews")
    archive = (
        {"energies": np.array([-1.0, 0.0, 1.0])},
        [
            {"type": "const-height sts", "height": 6.0},
            {"type": "const-isovalue stm", "isovalue": 1e-7},
        ],
        np.array(
            [
                [
                    [[0.0, 1.0], [2.0, 3.0]],
                    [[0.0, 0.0], [0.0, 0.0]],
                    [[4.0, 3.0], [2.0, 1.0]],
                ],
                [
                    [[1.0, 2.0], [3.0, 4.0]],
                    [[2.0, 2.0], [2.0, 2.0]],
                    [[5.0, 4.0], [3.0, 2.0]],
                ],
            ]
        ),
    )
    reads = []

    def load(uuid):
        reads.append(uuid)
        return archive

    monkeypatch.setattr(picker_module, "_load_archive", load)
    return picker_module, archive, reads


def test_stm_preview_picker_loads_lazily_and_uses_exact_stored_choice(
    monkeypatch, simulations_widgets
):
    module, archive, reads = _stm_preview_fixture(monkeypatch, simulations_widgets)
    calls, selected = [], []
    original = module.aiida_utils._render_stm_selected_preview

    def render(data, series, index, path):
        calls.append((data, series, index))
        return original(data, series, index, path)

    monkeypatch.setattr(module.aiida_utils, "_render_stm_selected_preview", render)
    picker = module.StmPreviewPicker("source-uuid", selected.append)
    assert reads == []
    picker.selected_index = 0
    assert reads == ["source-uuid"]
    picker.series.value = 0
    picker.bias.value = 0.82
    assert "+1.00 V" in picker.status.value
    assert selected == []  # Draft edits do not silently change the thumbnail.
    picker.use_button.click()
    assert calls[0][0] is archive
    assert calls[0][1:] == (0, 2)
    assert selected[0]["name"] == "stm-s0-e2.png"
    assert "STS dI/dV" in selected[0]["label"]
    assert "bias +1.00 V" in selected[0]["label"]
    assert selected[0]["content"].startswith(b"\x89PNG")
    picker.selected_index = None
    picker.selected_index = 0
    assert len(reads) == 1
    picker.close()
    assert picker._archive is None and picker._on_use is None
    assert not picker.bias._trait_notifiers.get("value", {}).get("change", [])
    assert not picker.use_button._click_handlers.callbacks


def test_stm_preview_picker_uniform_choice_and_invalid_bias(
    monkeypatch, simulations_widgets
):
    module, archive, _ = _stm_preview_fixture(monkeypatch, simulations_widgets)
    selected = []
    picker = module.StmPreviewPicker("source-uuid", selected.append)
    picker.selected_index = 0
    picker.series.value = 1
    picker.bias.value = 0
    assert "uniform" in picker.status.value
    picker.use_button.click()
    assert selected[0]["name"] == "stm-s1-e1.png"
    assert "isovalue" in selected[0]["label"]
    picker.bias.value = 100
    assert picker.use_button.disabled and "between -1 and 1" in picker.status.value
    picker.bias.value = float("nan")
    assert picker.use_button.disabled and "finite bias" in picker.status.value
    archive[2][1, 2] = float("nan")
    picker.bias.value = 1
    assert picker.use_button.disabled and "no finite" in picker.status.value
    assert len(selected) == 1
    picker.close()


@pytest.mark.parametrize("existing", [False, True])
def test_selected_stm_map_and_upload_use_same_visible_and_exported_image(
    monkeypatch, simulations_widgets, preview_details, existing
):
    from datetime import datetime, timezone
    from PIL import Image

    module, _, _ = _stm_preview_fixture(monkeypatch, simulations_widgets)
    suggestion = _preview_suggestion(simulations_widgets, existing=existing)
    suggestion.update(
        process_label="Cp2kStmWorkChain", source_uuid="source-uuid", result_role="spm"
    )
    monkeypatch.setattr(
        simulations_widgets.aiida_utils,
        "render_workchain_preview_suggestions",
        lambda *a, **k: [suggestion],
    )
    preview_details.load_aiida_preview_suggestions()
    entry = preview_details._preview_entries["test:bands"]
    picker = entry["map_picker"]
    picker.selected_index = 0
    picker.series.value = 0
    picker.bias.value = -1
    picker.use_button.click()
    first = preview_details.preview_overrides()["test:bands"]
    assert first["name"] == "stm-s0-e0.png"
    card = preview_details.preview_suggestions_box.children
    image_box = card[0].children[4] if not existing else card[1]
    assert bytes(image_box.children[0].value) == first["content"]
    if existing:
        assert preview_details.property_overrides() == {}  # Keep saved fields.
    data = io.BytesIO()
    Image.new("RGB", (32, 16), color="red").save(data, format="PNG")
    entry["uploader"].value = (
        {
            "name": "my-image.png",
            "type": "image/png",
            "size": len(data.getvalue()),
            "content": memoryview(data.getvalue()),
            "last_modified": datetime.now(timezone.utc),
        },
    )
    assert (
        preview_details.preview_overrides()["test:bands"]["content"] == data.getvalue()
    )
    picker.series.value = 1
    picker.bias.value = 1
    picker.use_button.click()
    assert entry["uploader"].value == ()
    final = preview_details.preview_overrides()["test:bands"]
    assert final["name"] == "stm-s1-e2.png"
    assert bytes(image_box.children[0].value) == final["content"]
    preview_details._clear_preview_suggestions()
    assert picker._archive is None and picker._on_use is None
    assert not entry["uploader"]._trait_notifiers.get("value", {}).get("change", [])
