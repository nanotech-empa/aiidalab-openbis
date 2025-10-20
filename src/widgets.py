import ipywidgets as ipw
from src import utils
from IPython.display import display, Javascript
import pandas as pd
import os
import rdkit
from rdkit.Chem import AllChem, Draw, rdMolDescriptors
import shutil
import io

MATERIALS_CONCEPTS_TYPES = utils.read_json("metadata/materials_concepts_types.json")
SIMULATION_TYPES = utils.read_json("metadata/simulation_types.json")
INSTRUMENTS_TYPES = utils.read_json("metadata/instruments_types.json")
OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")
OPENBIS_COLLECTIONS_PATHS = utils.read_json("metadata/collection_paths.json")

institutions_project = "/LAB205_ADMINISTRATIVE/INSTITUTIONS"
people_project = "/LAB205_ADMINISTRATIVE/PEOPLE"


class AtomModelWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.atom_model_label = ipw.Label(value="Atomistic model")

        self.atom_model_dropdown = ipw.Dropdown()
        self.load_atom_models()

        self.sort_atom_model_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_atom_model_hbox = ipw.HBox(
            children=[
                self.sort_atom_model_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_registration_date_checkbox,
                self.sort_registration_date_label,
            ]
        )

        self.create_atom_model_button = ipw.Button(
            tooltip="Add", icon="plus", layout=ipw.Layout(width="50px", height="25px")
        )

        self.atom_model_hbox = ipw.HBox(
            children=[
                self.atom_model_label,
                self.atom_model_dropdown,
                self.create_atom_model_button,
            ]
        )

        self.create_new_atom_model_widgets = ipw.VBox()

        self.children = [
            self.atom_model_hbox,
            self.sort_atom_model_hbox,
            self.create_new_atom_model_widgets,
        ]

        self.sort_name_checkbox.observe(self.sort_atom_model_dropdown, names="value")
        self.sort_registration_date_checkbox.observe(
            self.sort_atom_model_dropdown, names="value"
        )
        self.create_atom_model_button.on_click(self.create_atom_model)

    def load_atom_models(self):
        atom_models = utils.get_openbis_objects(
            self.openbis_session, type=OPENBIS_OBJECT_TYPES["Atomistic Model"]
        )
        atom_model_options = [
            (f"{obj.props['name']}", obj.permId) for obj in atom_models
        ]
        atom_model_options.insert(0, ("Select atomistic model...", "-1"))
        self.atom_model_dropdown.options = atom_model_options
        self.atom_model_dropdown.value = "-1"

    def sort_atom_model_dropdown(self, change):
        options = self.atom_model_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "registration_date"])
        if (
            self.sort_name_checkbox.value
            and not self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="name", ascending=True)
        elif (
            not self.sort_name_checkbox.value
            and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="registration_date", ascending=False)
        elif (
            self.sort_name_checkbox.value and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(
                by=["name", "registration_date"], ascending=[True, False]
            )

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.atom_model_dropdown.options[0])
        self.atom_model_dropdown.options = options

    def create_atom_model(self, b):
        select_molecules_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select molecules</span>"
        )

        select_reacprod_concepts_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select reaction product concepts</span>"
        )

        select_slab_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select slab</span>"
        )

        molecules_accordion = ipw.Accordion()
        add_molecule_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        reacprod_concepts_accordion = ipw.Accordion()
        add_reacprod_concept_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add reaction product concept",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        material_type_options = [
            (key, value) for key, value in MATERIALS_CONCEPTS_TYPES.items()
        ]
        material_type_options.insert(0, ("Select material type...", "-1"))

        material_type_dropdown = ipw.Dropdown(
            options=material_type_options, value=material_type_options[0][1]
        )

        material_details_vbox = ipw.VBox()

        atom_model_props_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Atomistic model properties</span>"
        )

        name_label = ipw.Label(value="Name")
        name_textbox = ipw.Text()
        name_hbox = ipw.HBox([name_label, name_textbox])

        wfms_uuid_label = ipw.Label(value="WFMS UUID")
        wfms_uuid_textbox = ipw.Text()
        wfms_uuid_hbox = ipw.HBox([wfms_uuid_label, wfms_uuid_textbox])

        cell_label = ipw.Label(value="Cell")
        cell_textbox = ipw.Textarea(placeholder="{[[1,1,1], [2,2,2], [3,3,3]]}")
        cell_hbox = ipw.HBox([cell_label, cell_textbox])

        dimensionality_label = ipw.Label(value="Dimensionality")
        dimensionality_intbox = ipw.IntText()
        dimensionality_hbox = ipw.HBox([dimensionality_label, dimensionality_intbox])

        pbc_label = ipw.Label(value="PBC")
        pbc_x_checkbox = ipw.Checkbox(indent=False, layout=ipw.Layout(width="20px"))
        pbc_y_checkbox = ipw.Checkbox(indent=False, layout=ipw.Layout(width="20px"))
        pbc_z_checkbox = ipw.Checkbox(indent=False, layout=ipw.Layout(width="20px"))
        pbc_hbox = ipw.HBox([pbc_label, pbc_x_checkbox, pbc_y_checkbox, pbc_z_checkbox])

        volume_label = ipw.Label(value="Volume")
        volume_floatbox = ipw.FloatText()
        volume_hbox = ipw.HBox([volume_label, volume_floatbox])

        comments_label = ipw.Label(value="Comments")
        comments_textbox = ipw.Textarea()
        comments_hbox = ipw.HBox([comments_label, comments_textbox])

        atom_model_preview_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Upload image preview</span>"
        )

        atom_model_preview_uploader = ipw.FileUpload(multiple=False)

        atom_model_datasets_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Upload datasets</span>"
        )

        atom_model_datasets_uploader = ipw.FileUpload()

        atom_model_properties_widgets = ipw.VBox(
            children=[
                atom_model_props_title,
                name_hbox,
                wfms_uuid_hbox,
                cell_hbox,
                dimensionality_hbox,
                pbc_hbox,
                volume_hbox,
                comments_hbox,
            ]
        )

        atom_model_datasets_widgets = ipw.VBox(
            children=[
                atom_model_preview_title,
                atom_model_preview_uploader,
                atom_model_datasets_title,
                atom_model_datasets_uploader,
            ]
        )

        save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        cancel_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Cancel",
            icon="times",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        buttons_hbox = ipw.HBox(children=[save_button, cancel_button])

        def load_material_type_widgets(change):
            if material_type_dropdown.value == "-1":
                material_details_vbox.children = []
                return
            else:
                material_options = [("Select material...", "-1")]
                material_dropdown = ipw.Dropdown(
                    options=material_options, value=material_options[0][1]
                )

                sort_material_label = ipw.Label(
                    value="Sort by:",
                    layout=ipw.Layout(margin="0px", width="50px"),
                    style={"description_width": "initial"},
                )

                name_checkbox = ipw.Checkbox(
                    indent=False, layout=ipw.Layout(margin="2px", width="20px")
                )

                name_label = ipw.Label(
                    value="Name",
                    layout=ipw.Layout(margin="0px", width="50px"),
                    style={"description_width": "initial"},
                )

                registration_date_checkbox = ipw.Checkbox(
                    indent=False, layout=ipw.Layout(margin="2px", width="20px")
                )

                registration_date_label = ipw.Label(
                    value="Registration date",
                    layout=ipw.Layout(margin="0px", width="110px"),
                    style={"description_width": "initial"},
                )

                select_material_box = ipw.HBox(
                    children=[
                        material_dropdown,
                        sort_material_label,
                        name_checkbox,
                        name_label,
                        registration_date_checkbox,
                        registration_date_label,
                    ]
                )

                material_details_html = ipw.HTML()

                material_details_vbox.children = [
                    select_material_box,
                    material_details_html,
                ]

                material_type = material_type_dropdown.value
                material_objects = utils.get_openbis_objects(
                    self.openbis_session, type=material_type
                )
                materials_objects_names_permids = [
                    (obj.props["name"], obj.permId) for obj in material_objects
                ]
                material_options += materials_objects_names_permids
                material_dropdown.options = material_options

                def sort_material_dropdown(change):
                    options = material_options[1:]

                    df = pd.DataFrame(options, columns=["name", "registration_date"])
                    if name_checkbox.value and not registration_date_checkbox.value:
                        df = df.sort_values(by="name", ascending=True)
                    elif not name_checkbox.value and registration_date_checkbox.value:
                        df = df.sort_values(by="registration_date", ascending=False)
                    elif name_checkbox.value and registration_date_checkbox.value:
                        df = df.sort_values(
                            by=["name", "registration_date"], ascending=[True, False]
                        )

                    options = list(df.itertuples(index=False, name=None))
                    options.insert(0, material_options[0])
                    material_dropdown.options = options

                def load_material_details(change):
                    obj_permid = material_dropdown.value
                    if obj_permid == "-1":
                        return
                    else:
                        obj = utils.get_openbis_object(
                            self.openbis_session, sample_ident=obj_permid
                        )
                        obj_props = obj.props.all()
                        obj_details_string = "<div style='border: 1px solid grey; padding: 10px; margin: 10px;'>"
                        for key, value in obj_props.items():
                            if value:
                                prop_type = utils.get_openbis_property_type(
                                    self.openbis_session, code=key
                                )
                                prop_label = prop_type.label
                                obj_details_string += (
                                    f"<p><b>{prop_label}:</b> {value}</p>"
                                )

                        obj_details_string += "</div>"
                        material_details_html.value = obj_details_string

                name_checkbox.observe(sort_material_dropdown, names="value")
                registration_date_checkbox.observe(
                    sort_material_dropdown, names="value"
                )
                material_dropdown.observe(load_material_details, names="value")

        def add_molecule(b):
            molecules_accordion_children = list(molecules_accordion.children)
            molecule_index = len(molecules_accordion_children)
            molecule_widget = MoleculeWidget(
                self.openbis_session, molecules_accordion, molecule_index
            )
            molecules_accordion_children.append(molecule_widget)
            molecules_accordion.children = molecules_accordion_children

        def add_reacprod_concept(b):
            reacprod_concepts_accordion_children = list(
                reacprod_concepts_accordion.children
            )
            reacprod_concept_index = len(reacprod_concepts_accordion_children)
            reacprod_concept_widget = ReacProdConceptWidget(
                self.openbis_session,
                reacprod_concepts_accordion,
                reacprod_concept_index,
            )
            reacprod_concepts_accordion_children.append(reacprod_concept_widget)
            reacprod_concepts_accordion.children = reacprod_concepts_accordion_children

        def save_new_atom_model(b):
            atom_model_type = OPENBIS_OBJECT_TYPES["Atomistic Model"]
            atom_models_objs = utils.get_openbis_objects(
                self.openbis_session, type=atom_model_type
            )
            wfms_uuid = wfms_uuid_textbox.value
            atom_models_uuids = [obj.props["wfms_uuid"] for obj in atom_models_objs]
            if wfms_uuid in atom_models_uuids:
                display(Javascript(data="alert('Atomistic model already in openBIS!')"))
            else:
                pbc = [pbc_x_checkbox.value, pbc_y_checkbox.value, pbc_z_checkbox.value]
                cell_json = cell_textbox.value

                if not utils.is_valid_json(cell_json):
                    cell_json = ""

                atom_model_props = {
                    "name": name_textbox.value,
                    "wfms_uuid": wfms_uuid,
                    "cell": cell_json,
                    "dimensionality": dimensionality_intbox.value,
                    "periodic_boundary_conditions": pbc,
                    "volume": volume_floatbox.value,
                    "comments": comments_textbox.value,
                }

                selected_molecules_widgets = molecules_accordion.children
                selected_reac_prods_widgets = reacprod_concepts_accordion.children

                # Get material
                if material_type_dropdown.value == "-1":
                    selected_slab = []
                else:
                    selected_material_id = (
                        material_details_vbox.children[0].children[0].value
                    )
                    if selected_material_id == "-1":
                        selected_slab = []
                    else:
                        selected_slab = [selected_material_id]

                # Get molecules
                selected_molecules_ids = []
                for mol_widget in selected_molecules_widgets:
                    mol_id = mol_widget.dropdown.value
                    if mol_id == "-1":
                        continue
                    else:
                        selected_molecules_ids.append(mol_id)

                # Get reaction products concepts
                selected_reac_prods_ids = []
                for reac_prod_widget in selected_reac_prods_widgets:
                    reac_prod_id = reac_prod_widget.dropdown.value
                    if reac_prod_id == "-1":
                        continue
                    else:
                        selected_reac_prods_ids.append(reac_prod_id)

                atom_model_parents = (
                    selected_slab + selected_molecules_ids + selected_reac_prods_ids
                )

                atom_model_obj = utils.create_openbis_object(
                    self.openbis_session,
                    type=atom_model_type,
                    collection=OPENBIS_COLLECTIONS_PATHS["Atomistic Model"],
                    props=atom_model_props,
                    parents=atom_model_parents,
                )

                # Atomistic model preview
                for filename in atom_model_preview_uploader.value:
                    file_info = atom_model_preview_uploader.value[filename]
                    utils.write_file(file_info["content"], filename)
                    utils.create_openbis_dataset(
                        self.openbis_session,
                        type="ELN_PREVIEW",
                        sample=atom_model_obj,
                        files=[filename],
                    )
                    os.remove(filename)

                # Atomistic model datasets
                for filename in atom_model_datasets_uploader.value:
                    file_info = atom_model_datasets_uploader.value[filename]
                    utils.write_file(file_info["content"], filename)
                    utils.create_openbis_dataset(
                        self.openbis_session,
                        type="ATTACHMENT",
                        sample=atom_model_obj,
                        files=[filename],
                    )
                    os.remove(filename)

                self.create_new_atom_model_widgets.children = []
                self.atom_model_dropdown.options = self.load_atom_models()
                display(
                    Javascript(data="alert('Atomistic model successfully created!')")
                )

        def cancel_new_atom_model(b):
            self.create_new_atom_model_widgets.children = []

        save_button.on_click(save_new_atom_model)
        cancel_button.on_click(cancel_new_atom_model)
        material_type_dropdown.observe(load_material_type_widgets, names="value")
        add_molecule_button.on_click(add_molecule)
        add_reacprod_concept_button.on_click(add_reacprod_concept)

        self.create_new_atom_model_widgets.children = [
            select_molecules_title,
            molecules_accordion,
            add_molecule_button,
            select_reacprod_concepts_title,
            reacprod_concepts_accordion,
            add_reacprod_concept_button,
            select_slab_title,
            material_type_dropdown,
            material_details_vbox,
            atom_model_properties_widgets,
            atom_model_datasets_widgets,
            buttons_hbox,
        ]


class MoleculeWidget(ipw.VBox):
    def __init__(self, openbis_session, parent_accordion, object_index):
        super().__init__()
        self.openbis_session = openbis_session
        self.parent_accordion = parent_accordion
        self.object_index = object_index
        self.title = ""

        molecules_objects = utils.get_openbis_objects(
            self.openbis_session,
            collection=OPENBIS_COLLECTIONS_PATHS["Precursor Molecule"],
            type=OPENBIS_OBJECT_TYPES["Molecule"],
        )
        dropdown_list = [(obj.props["name"], obj.permId) for obj in molecules_objects]
        dropdown_list.insert(0, ("Select a molecule...", "-1"))
        self.dropdown = ipw.Dropdown(value="-1", options=dropdown_list)
        self.details_vbox = ipw.VBox()

        self.remove_molecule_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip="Remove molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.molecule_sketch = ipw.Image(
            layout=ipw.Layout(width="300px", height="300px")
        )

        self.dropdown.observe(self.load_details, names="value")
        self.remove_molecule_button.on_click(self.remove_molecule)
        self.children = [
            self.dropdown,
            self.details_vbox,
            self.molecule_sketch,
            self.remove_molecule_button,
        ]

    def load_details(self, change):
        obj_permid = self.dropdown.value
        if obj_permid == "-1":
            return
        else:
            obj = utils.get_openbis_object(
                self.openbis_session, sample_ident=obj_permid
            )
            obj_datasets = obj.get_datasets(type="ELN_PREVIEW")
            obj_props = obj.props.all()
            obj_name = obj_props.get("name", "")
            self.parent_accordion.set_title(self.object_index, obj_name)
            self.title = obj_name

            obj_details_html = ipw.HTML()
            obj_details_string = (
                "<div style='border: 1px solid grey; padding: 10px; margin: 10px;'>"
            )
            for key, value in obj_props.items():
                if value:
                    prop_type = utils.get_openbis_property_type(
                        self.openbis_session, code=key
                    )
                    prop_label = prop_type.label
                    obj_details_string += f"<p><b>{prop_label}:</b> {value}</p>"

            obj_details_string += "</div>"
            obj_details_html.value = obj_details_string

            if obj_datasets:
                object_dataset = obj_datasets[0]
                object_dataset.download(destination="images")
                object_image_filepath = object_dataset.file_list[0]
                self.molecule_sketch.value = utils.read_file(
                    f"images/{object_dataset.permId}/{object_image_filepath}"
                )

                # Erase file after downloading it
                shutil.rmtree(f"images/{object_dataset.permId}")

            self.details_vbox.children = [obj_details_html]

    def remove_molecule(self, b):
        molecules_accordion_children = list(self.parent_accordion.children)
        num_molecules = len(molecules_accordion_children)
        molecules_accordion_children.pop(self.object_index)

        for index, molecule in enumerate(molecules_accordion_children):
            if index >= self.object_index:
                molecule.object_index -= 1
                self.parent_accordion.set_title(molecule.object_index, molecule.title)

        self.parent_accordion.set_title(num_molecules - 1, "")
        self.parent_accordion.children = molecules_accordion_children


class ReacProdConceptWidget(ipw.VBox):
    def __init__(self, openbis_session, parent_accordion, object_index):
        super().__init__()
        self.openbis_session = openbis_session
        self.parent_accordion = parent_accordion
        self.object_index = object_index
        self.title = ""

        molecules_objects = utils.get_openbis_objects(
            self.openbis_session,
            collection=OPENBIS_COLLECTIONS_PATHS["Reaction Product"],
            type=OPENBIS_OBJECT_TYPES["Reaction Product Concept"],
        )
        dropdown_list = [(obj.props["name"], obj.permId) for obj in molecules_objects]
        dropdown_list.insert(0, ("Select a reaction product concept...", "-1"))
        self.dropdown = ipw.Dropdown(value="-1", options=dropdown_list)
        self.details_vbox = ipw.VBox()

        self.remove_reacprod_concept_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip="Remove reaction product concept",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.dropdown.observe(self.load_details, names="value")
        self.remove_reacprod_concept_button.on_click(self.remove_reacprod_concept)
        self.children = [
            self.dropdown,
            self.details_vbox,
            self.remove_reacprod_concept_button,
        ]

    def load_details(self, change):
        obj_permid = self.dropdown.value
        if obj_permid == "-1":
            return
        else:
            obj = utils.get_openbis_object(
                self.openbis_session, sample_ident=obj_permid
            )
            obj_props = obj.props.all()
            obj_name = obj_props.get("name", "")
            self.parent_accordion.set_title(self.object_index, obj_name)
            self.title = obj_name

            obj_details_html = ipw.HTML()
            obj_details_string = (
                "<div style='border: 1px solid grey; padding: 10px; margin: 10px;'>"
            )
            for key, value in obj_props.items():
                if value:
                    prop_type = utils.get_openbis_property_type(
                        self.openbis_session, code=key
                    )
                    prop_label = prop_type.label
                    obj_details_string += f"<p><b>{prop_label}:</b> {value}</p>"

            obj_details_string += "</div>"
            obj_details_html.value = obj_details_string
            self.details_vbox.children = [obj_details_html]

    def remove_reacprod_concept(self, b):
        reacprod_concepts_accordion_children = list(self.parent_accordion.children)
        num_reacprod_concepts = len(reacprod_concepts_accordion_children)
        reacprod_concepts_accordion_children.pop(self.object_index)

        for index, reacprod_concept in enumerate(reacprod_concepts_accordion_children):
            if index >= self.object_index:
                reacprod_concept.object_index -= 1
                self.parent_accordion.set_title(
                    reacprod_concept.object_index, reacprod_concept.title
                )

        self.parent_accordion.set_title(num_reacprod_concepts - 1, "")
        self.parent_accordion.children = reacprod_concepts_accordion_children


class SelectInstrumentWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.instrument_label = ipw.Label(value="Instrument")

        self.instrument_dropdown = ipw.Dropdown()
        self.load_instruments()

        self.sort_instrument_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_instrument_hbox = ipw.HBox(
            children=[
                self.sort_instrument_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_registration_date_checkbox,
                self.sort_registration_date_label,
            ]
        )

        self.instrument_dropdown_hbox = ipw.HBox(
            children=[
                self.instrument_label,
                self.instrument_dropdown,
            ]
        )

        self.sort_name_checkbox.observe(self.sort_instrument_dropdown, names="value")
        self.sort_registration_date_checkbox.observe(
            self.sort_instrument_dropdown, names="value"
        )

        self.children = [self.instrument_dropdown_hbox, self.sort_instrument_hbox]

    def load_instruments(self):
        instruments = []
        for instrument_type in INSTRUMENTS_TYPES:
            instruments_objects = utils.get_openbis_objects(
                self.openbis_session, type=instrument_type
            )
            instruments.extend(instruments_objects)

        instrument_options = [
            (f"{obj.props['name']}", obj.permId) for obj in instruments
        ]
        instrument_options.insert(0, ("Select instrument...", "-1"))
        self.instrument_dropdown.options = instrument_options
        self.instrument_dropdown.value = "-1"

    def sort_instrument_dropdown(self, change):
        options = self.instrument_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "registration_date"])
        if (
            self.sort_name_checkbox.value
            and not self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="name", ascending=True)
        elif (
            not self.sort_name_checkbox.value
            and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="registration_date", ascending=False)
        elif (
            self.sort_name_checkbox.value and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(
                by=["name", "registration_date"], ascending=[True, False]
            )

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.instrument_dropdown.options[0])
        self.instrument_dropdown.options = options


class SelectExperimentWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.create_experiment_button = ipw.Button(
            tooltip="Add", icon="plus", layout=ipw.Layout(width="50px", height="25px")
        )

        self.experiment_label = ipw.Label(value="Experiment")

        self.experiment_dropdown = ipw.Dropdown(layout=ipw.Layout(width="500px"))
        self.load_experiments()

        self.sort_experiment_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_experiment_widgets = ipw.HBox(
            children=[
                self.sort_experiment_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_registration_date_checkbox,
                self.sort_registration_date_label,
            ]
        )

        self.experiment_dropdown_boxes = ipw.HBox(
            children=[
                self.experiment_label,
                self.experiment_dropdown,
                self.create_experiment_button,
            ]
        )

        self.create_new_experiment_widgets = ipw.VBox()

        self.children = [
            self.experiment_dropdown_boxes,
            self.sort_experiment_widgets,
            self.create_new_experiment_widgets,
        ]

        self.create_experiment_button.on_click(self.create_new_experiment)
        self.sort_name_checkbox.observe(self.sort_experiment_dropdown, names="value")
        self.sort_registration_date_checkbox.observe(
            self.sort_experiment_dropdown, names="value"
        )

    def load_experiments(self):
        experiments = utils.get_openbis_collections(
            self.openbis_session, type="EXPERIMENT"
        )
        experiment_options = []
        for exp in experiments:
            if "name" in exp.props.all():
                exp_option = (
                    f"{exp.props['name']} from Project {exp.project.code} and Space {exp.project.space}",
                    exp.permId,
                )
            else:
                exp_option = (
                    f"{exp.code} from Project {exp.project.code} and Space {exp.project.space}",
                    exp.permId,
                )
            experiment_options.append(exp_option)
        experiment_options.insert(0, ("Select experiment...", "-1"))
        self.experiment_dropdown.options = experiment_options
        self.experiment_dropdown.value = "-1"

    def sort_experiment_dropdown(self, change):
        options = self.experiment_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "registration_date"])
        if (
            self.sort_name_checkbox.value
            and not self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="name", ascending=True)
        elif (
            not self.sort_name_checkbox.value
            and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="registration_date", ascending=False)
        elif (
            self.sort_name_checkbox.value and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(
                by=["name", "registration_date"], ascending=[True, False]
            )

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.experiment_dropdown.options[0])
        self.experiment_dropdown.options = options

    def create_new_experiment(self, b):
        new_experiment_name_label = ipw.Label(value="Name")

        new_experiment_name_textbox = ipw.Text(placeholder="Write experiment name...")

        new_experiment_name_hbox = ipw.HBox(
            children=[new_experiment_name_label, new_experiment_name_textbox]
        )

        project_label = ipw.Label(value="Project")

        projects = utils.get_openbis_projects(self.openbis_session)
        project_dropdown_options = [
            (f"{proj.code} from Space {proj.space}", proj.permId) for proj in projects
        ]
        project_dropdown_options.insert(0, ("Select project...", "-1"))

        project_dropdown = ipw.Dropdown(options=project_dropdown_options, value="-1")

        project_hbox = ipw.HBox(children=[project_label, project_dropdown])

        sort_project_label = ipw.Label(value="Sort by:")

        sort_project_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        sort_project_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        sort_project_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        sort_project_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        sort_project_hbox = ipw.HBox(
            children=[
                sort_project_label,
                sort_project_name_checkbox,
                sort_project_name_label,
                sort_project_registration_date_checkbox,
                sort_project_registration_date_label,
            ]
        )

        save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        cancel_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Cancel",
            icon="times",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        buttons_hbox = ipw.HBox(children=[save_button, cancel_button])

        def save_new_experiment(b):
            experiment_props = {
                "name": new_experiment_name_textbox.value,
                "default_collection_view": "IMAGING_GALLERY_VIEW",
            }

            project_id = project_dropdown.value

            if project_id == "-1":
                display(Javascript(data="alert('Select a project.')"))
                return
            else:
                try:
                    utils.create_openbis_collection(
                        self.openbis_session,
                        type="EXPERIMENT",
                        project=project_dropdown.value,
                        props=experiment_props,
                    )
                    self.create_new_experiment_widgets.children = []
                    self.experiment_dropdown.options = self.load_experiments()
                    display(
                        Javascript(data="alert('Experiment successfully created!')")
                    )
                except ValueError:
                    display(
                        Javascript(
                            data="alert('Error! Check if experiment already exists (either in ELN or Trash).')"
                        )
                    )

        def cancel_new_experiment(b):
            self.create_new_experiment_widgets.children = []

        def sort_project_dropdown(change):
            options = project_dropdown_options[1:]

            df = pd.DataFrame(options, columns=["name", "registration_date"])
            if (
                sort_project_name_checkbox.value
                and not sort_project_registration_date_checkbox.value
            ):
                df = df.sort_values(by="name", ascending=True)
            elif (
                not sort_project_name_checkbox.value
                and sort_project_registration_date_checkbox.value
            ):
                df = df.sort_values(by="registration_date", ascending=False)
            elif (
                sort_project_name_checkbox.value
                and sort_project_registration_date_checkbox.value
            ):
                df = df.sort_values(
                    by=["name", "registration_date"], ascending=[True, False]
                )

            options = list(df.itertuples(index=False, name=None))
            options.insert(0, project_dropdown_options[0])
            project_dropdown.options = options

        save_button.on_click(save_new_experiment)
        cancel_button.on_click(cancel_new_experiment)
        sort_project_name_checkbox.observe(sort_project_dropdown)
        sort_project_registration_date_checkbox.observe(sort_project_dropdown)

        self.create_new_experiment_widgets.children = [
            new_experiment_name_hbox,
            project_hbox,
            sort_project_hbox,
            buttons_hbox,
        ]


class SelectSampleWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.sample_label = ipw.Label(value="Sample")

        self.sample_dropdown = ipw.Dropdown()
        self.load_samples()

        self.sort_sample_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_sample_hbox = ipw.HBox(
            children=[
                self.sort_sample_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_registration_date_checkbox,
                self.sort_registration_date_label,
            ]
        )

        self.sample_dropdown_hbox = ipw.HBox(
            children=[
                self.sample_label,
                self.sample_dropdown,
            ]
        )

        self.sort_name_checkbox.observe(self.sort_sample_dropdown, names="value")
        self.sort_registration_date_checkbox.observe(
            self.sort_sample_dropdown, names="value"
        )

        self.children = [self.sample_dropdown_hbox, self.sort_sample_hbox]

    def load_samples(self):
        sample_type = OPENBIS_OBJECT_TYPES["Sample"]
        samples = utils.get_openbis_objects(
            self.openbis_session, type=sample_type, where={"object_status": "ACTIVE"}
        )
        sample_options = [(f"{obj.props['name']}", obj.permId) for obj in samples]
        sample_options = sorted(sample_options, key=lambda x: x[1], reverse=True)
        sample_options.insert(0, ("Select sample...", "-1"))
        self.sample_dropdown.options = sample_options
        self.sample_dropdown.value = "-1"

    def sort_sample_dropdown(self, change):
        options = self.sample_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "registration_date"])
        if (
            self.sort_name_checkbox.value
            and not self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="name", ascending=True)
        elif (
            not self.sort_name_checkbox.value
            and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="registration_date", ascending=False)
        elif (
            self.sort_name_checkbox.value and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(
                by=["name", "registration_date"], ascending=[True, False]
            )

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.sample_dropdown.options[0])
        self.sample_dropdown.options = options


class SelectProjectWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.project_label = ipw.Label(value="Project")

        self.project_dropdown = ipw.Dropdown(layout=ipw.Layout(width="500px"))
        self.load_projects()

        self.sort_project_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_registration_date_label = ipw.Label(
            value="Registration date",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_registration_date_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_project_widgets = ipw.HBox(
            children=[
                self.sort_project_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_registration_date_checkbox,
                self.sort_registration_date_label,
            ]
        )

        self.project_dropdown_boxes = ipw.HBox(
            children=[self.project_label, self.project_dropdown]
        )

        self.children = [self.project_dropdown_boxes, self.sort_project_widgets]

        self.sort_name_checkbox.observe(self.sort_project_dropdown, names="value")
        self.sort_registration_date_checkbox.observe(
            self.sort_project_dropdown, names="value"
        )

    def load_projects(self):
        projects = utils.get_openbis_projects(self.openbis_session)
        project_options = []
        for prj in projects:
            prj_option = (f"{prj.code} from Space {prj.space.code}", prj.permId)
            project_options.append(prj_option)

        project_options.insert(0, ("Select project...", "-1"))
        self.project_dropdown.options = project_options
        self.project_dropdown.value = "-1"

    def sort_project_dropdown(self, change):
        options = self.project_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "registration_date"])
        if (
            self.sort_name_checkbox.value
            and not self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="name", ascending=True)
        elif (
            not self.sort_name_checkbox.value
            and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(by="registration_date", ascending=False)
        elif (
            self.sort_name_checkbox.value and self.sort_registration_date_checkbox.value
        ):
            df = df.sort_values(
                by=["name", "registration_date"], ascending=[True, False]
            )

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.project_dropdown.options[0])
        self.project_dropdown.options = options


class CreateDraftsWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_project_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select project</span>"
        )

        self.select_project_widget = SelectProjectWidget(self.openbis_session)

        self.select_results_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select results</span>"
        )

        self.select_results_label = ipw.Label(value="Results")
        self.select_results_selector = ipw.SelectMultiple()
        self.select_results_hbox = ipw.HBox(
            [self.select_results_label, self.select_results_selector]
        )

        self.drafts_properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Properties</span>"
        )

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox([self.name_label, self.name_textbox])

        self.draft_type_label = ipw.Label(value="Draft type")
        self.draft_type_dropdown = ipw.Dropdown(
            value="Preprint", options=["Preprint", "Postprint"]
        )
        self.draft_type_hbox = ipw.HBox(
            [self.draft_type_label, self.draft_type_dropdown]
        )

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Textarea()
        self.description_hbox = ipw.HBox(
            [self.description_label, self.description_textbox]
        )

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textbox = ipw.Textarea()
        self.comments_hbox = ipw.HBox([self.comments_label, self.comments_textbox])

        self.support_files_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Support files</span>"
        )
        self.support_files_uploader = ipw.FileUpload()

        self.select_project_widget.project_dropdown.observe(self.load_results)

        self.children = [
            self.select_project_title,
            self.select_project_widget,
            self.select_results_title,
            self.select_results_hbox,
            self.drafts_properties_title,
            self.name_hbox,
            self.draft_type_hbox,
            self.description_hbox,
            self.comments_hbox,
            self.support_files_title,
            self.support_files_uploader,
        ]

    def load_results(self, change):
        project_id = self.select_project_widget.project_dropdown.value
        results_objects = []

        if project_id != "-1":
            results = utils.get_openbis_objects(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Result"],
                project=project_id,
            )

            results_objects = [(obj.props["name"], obj.permId) for obj in results]

        self.select_results_selector.options = results_objects


class CreateAnalysisWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_project_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select project</span>"
        )

        self.select_project_widget = SelectProjectWidget(self.openbis_session)

        self.select_simulations_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select simulations</span>"
        )

        self.select_simulations_label = ipw.Label(value="Simulations")
        self.select_simulations_selector = ipw.SelectMultiple()
        self.select_simulations_hbox = ipw.HBox(
            [self.select_simulations_label, self.select_simulations_selector]
        )

        self.select_measurements_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select measurements</span>"
        )

        self.select_measurements_label = ipw.Label(value="Measurements")
        self.select_measurements_selector = ipw.SelectMultiple()
        self.select_measurements_hbox = ipw.HBox(
            [self.select_measurements_label, self.select_measurements_selector]
        )

        self.select_software_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select software</span>"
        )

        self.select_software_label = ipw.Label(value="Software")
        openbis_software = utils.get_openbis_objects(
            self.openbis_session, type="SOFTWARE"
        )
        software_options = [(obj.props["name"], obj.permId) for obj in openbis_software]
        self.select_software_selector = ipw.SelectMultiple(options=software_options)
        self.select_software_hbox = ipw.HBox(
            [self.select_software_label, self.select_software_selector]
        )

        self.select_code_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select code</span>"
        )

        self.select_code_label = ipw.Label(value="Code")
        openbis_code = utils.get_openbis_objects(self.openbis_session, type="CODE")
        code_options = [(obj.props["name"], obj.permId) for obj in openbis_code]
        self.select_code_selector = ipw.SelectMultiple(options=code_options)
        self.select_code_hbox = ipw.HBox(
            [self.select_code_label, self.select_code_selector]
        )

        self.analysis_properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Properties</span>"
        )

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox([self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Textarea()
        self.description_hbox = ipw.HBox(
            [self.description_label, self.description_textbox]
        )

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textbox = ipw.Textarea()
        self.comments_hbox = ipw.HBox([self.comments_label, self.comments_textbox])

        self.support_files_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Support files</span>"
        )
        self.support_files_uploader = ipw.FileUpload()

        self.select_project_widget.project_dropdown.observe(
            self.load_measurements_and_simulations
        )

        self.children = [
            self.select_project_title,
            self.select_project_widget,
            self.select_simulations_title,
            self.select_simulations_hbox,
            self.select_measurements_title,
            self.select_measurements_hbox,
            self.select_software_title,
            self.select_software_hbox,
            self.select_code_title,
            self.select_code_hbox,
            self.analysis_properties_title,
            self.name_hbox,
            self.description_hbox,
            self.comments_hbox,
            self.support_files_title,
            self.support_files_uploader,
        ]

    def load_measurements_and_simulations(self, change):
        project_id = self.select_project_widget.project_dropdown.value
        simulations_objects = []
        measurements_objects = []

        if project_id != "-1":
            for _, simulation_type in SIMULATION_TYPES.items():
                openbis_objs = utils.get_openbis_objects(
                    self.openbis_session, type=simulation_type, project=project_id
                )
                objs = [(obj.props["name"], obj.permId) for obj in openbis_objs]
                simulations_objects += objs

            measurements = utils.get_openbis_objects(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Measurement Session"],
                project=project_id,
            )

            for measurement in measurements:
                measurement_details = (measurement.props["name"], measurement.permId)
                if measurement.props["wfms_uuid"]:
                    simulations_objects.append(measurement_details)
                else:
                    measurements_objects.append(measurement_details)

        self.select_simulations_selector.options = simulations_objects
        self.select_measurements_selector.options = measurements_objects


class CreateResultsWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_project_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select project</span>"
        )

        self.select_project_widget = SelectProjectWidget(self.openbis_session)

        self.select_simulations_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select simulations</span>"
        )

        self.select_simulations_label = ipw.Label(value="Simulations")
        self.select_simulations_selector = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px", height="100px")
        )
        self.select_simulations_hbox = ipw.HBox(
            [self.select_simulations_label, self.select_simulations_selector]
        )

        self.select_measurements_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select measurements</span>"
        )

        self.select_measurements_label = ipw.Label(value="Measurements")
        self.select_measurements_selector = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px", height="100px")
        )
        self.select_measurements_hbox = ipw.HBox(
            [self.select_measurements_label, self.select_measurements_selector]
        )

        self.select_analysis_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select analysis</span>"
        )
        self.select_analysis_label = ipw.Label(value="Analysis")
        self.select_analysis_selector = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px", height="100px")
        )
        self.select_analysis_hbox = ipw.HBox(
            [self.select_analysis_label, self.select_analysis_selector]
        )

        self.results_properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Properties</span>"
        )

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox([self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Textarea()
        self.description_hbox = ipw.HBox(
            [self.description_label, self.description_textbox]
        )

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textbox = ipw.Textarea()
        self.comments_hbox = ipw.HBox([self.comments_label, self.comments_textbox])

        self.support_files_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Support files</span>"
        )
        self.support_files_uploader = ipw.FileUpload(multiple=True)

        self.select_project_widget.project_dropdown.observe(
            self.load_analysis_measurements_and_simulations
        )

        self.children = [
            self.select_project_title,
            self.select_project_widget,
            self.select_simulations_title,
            self.select_simulations_hbox,
            self.select_measurements_title,
            self.select_measurements_hbox,
            self.select_analysis_title,
            self.select_analysis_hbox,
            self.results_properties_title,
            self.name_hbox,
            self.description_hbox,
            self.comments_hbox,
            self.support_files_title,
            self.support_files_uploader,
        ]

    def reset_widgets(self):
        self.select_project_widget.project_dropdown.value = "-1"
        self.name_textbox.value = ""
        self.description_textbox.value = ""
        self.comments_textbox.value = ""
        self.support_files_uploader.value.clear()
        self.support_files_uploader._counter = 0

    def load_analysis_measurements_and_simulations(self, change):
        project_id = self.select_project_widget.project_dropdown.value
        analysis_objects = []
        simulations_objects = []
        measurements_objects = []

        if project_id != "-1":
            for _, simulation_type in SIMULATION_TYPES.items():
                openbis_objs = utils.get_openbis_objects(
                    self.openbis_session, type=simulation_type, project=project_id
                )
                objs = [
                    (f"{obj.props['name']} ({obj.type.code})", obj.permId)
                    for obj in openbis_objs
                ]
                simulations_objects += objs

            measurements = utils.get_openbis_objects(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Measurement Session"],
                project=project_id,
            )

            for measurement in measurements:
                measurement_details = (
                    f"{measurement.props['name']} ({measurement.type.code})",
                    measurement.permId,
                )
                measurements_objects.append(measurement_details)

            analysis = utils.get_openbis_objects(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Analysis"],
                project=project_id,
            )
            analysis_objects = [(obj.props["name"], obj.permId) for obj in analysis]

        self.select_simulations_selector.options = simulations_objects
        self.select_measurements_selector.options = measurements_objects
        self.select_analysis_selector.options = analysis_objects


class CreateSubstanceWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Properties</span>"
        )

        self.molecules_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Molecules</span>"
        )

        self.evaporation_temperatures_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Evaporation temperatures</span>"
        )

        headers_items = [
            ipw.Label(value="Datetime"),
            ipw.Label(value="Instrument name"),
            ipw.Label(value="Temperature (value)"),
            ipw.Label(value="Temperature (unit)"),
        ]

        row_items = [
            ipw.DatePicker(layout=ipw.Layout(width="80%")),
            ipw.Text(layout=ipw.Layout(width="80%")),
            ipw.Text(layout=ipw.Layout(width="80%")),
            ipw.Dropdown(layout=ipw.Layout(width="80%"), options=["C", "K"]),
        ]

        self.evaporation_temperatures_table = TableWidget(
            headers_items=headers_items, row_items=row_items
        )

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox([self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Textarea()
        self.description_hbox = ipw.HBox(
            [self.description_label, self.description_textbox]
        )

        self.molecules_label = ipw.Label(value="Molecules")
        self.molecules_accordion = ipw.Accordion()
        self.molecules_hbox = ipw.HBox([self.molecules_label, self.molecules_accordion])

        self.empa_number_label = ipw.Label(value="Empa number")
        self.empa_number_textbox = ipw.IntText()
        self.empa_number_hbox = ipw.HBox(
            [self.empa_number_label, self.empa_number_textbox]
        )

        self.batch_label = ipw.Label(value="Batch")
        self.batch_textbox = ipw.Text()
        self.batch_hbox = ipw.HBox([self.batch_label, self.batch_textbox])

        self.vial_label = ipw.Label(value="Vial")
        self.vial_textbox = ipw.Text()
        self.vial_hbox = ipw.HBox([self.vial_label, self.vial_textbox])

        self.purity_label = ipw.Label(value="Purity")
        self.purity_textbox = ipw.FloatText()
        self.purity_hbox = ipw.HBox([self.purity_label, self.purity_textbox])

        self.substance_type_label = ipw.Label(value="Substance type")
        self.substance_type_textbox = ipw.Text()
        self.substance_type_hbox = ipw.HBox(
            [self.substance_type_label, self.substance_type_textbox]
        )

        self.amount_label = ipw.Label(value="Amount")
        self.amount_value_textbox = ipw.Text()
        self.amount_unit_dropdown = ipw.Dropdown(options=["g", "mg", "ug", "ml", "ul"])
        self.amount_hbox = ipw.HBox(
            [self.amount_label, self.amount_value_textbox, self.amount_unit_dropdown]
        )

        self.location_label = ipw.Label(value="Location")
        instruments_options = self.load_instruments(
            collection=OPENBIS_COLLECTIONS_PATHS["Instrument"]
        )
        rooms_options = self.load_rooms(project="/ADMINISTRATIVE/LOCATIONS")
        location_options = instruments_options + rooms_options
        location_options.insert(0, ("Select a location...", "-1"))
        self.location_dropdown = ipw.Dropdown(options=location_options)
        self.location_hbox = ipw.HBox([self.location_label, self.location_dropdown])

        self.storage_conditions_label = ipw.Label(value="Special storage conditions")
        self.storage_conditions_selector = ipw.SelectMultiple(
            options=[
                "Fridge",
                "Freezer",
                "Poiseouns",
                "Dark",
                "Dry",
                "No oxygen",
                "Flammable",
            ]
        )
        self.storage_conditions_hbox = ipw.HBox(
            [self.storage_conditions_label, self.storage_conditions_selector]
        )

        self.package_opening_date_label = ipw.Label(value="Package opening date")
        self.package_opening_date = ipw.DatePicker()
        self.package_opening_date_hbox = ipw.HBox(
            [self.package_opening_date_label, self.package_opening_date]
        )

        self.object_status_label = ipw.Label(value="Object status")
        self.object_status_dropdown = ipw.Dropdown(
            options=["Active", "Inactive", "Broken", "Disposed"]
        )
        self.object_status_hbox = ipw.HBox(
            [self.object_status_label, self.object_status_dropdown]
        )

        self.supplier_label = ipw.Label(value="Supplier")
        supplier_options = self.load_suppliers(project=institutions_project)
        supplier_options.insert(0, ("Select a supplier...", "-1"))
        self.supplier_dropdown = ipw.Dropdown(options=supplier_options)
        self.supplier_hbox = ipw.HBox([self.supplier_label, self.supplier_dropdown])

        self.synthesised_by_label = ipw.Label(value="Synthesised by")
        synthesised_by_options = self.load_synthesisers(project=people_project)
        self.synthesised_by_selector = ipw.SelectMultiple(
            options=synthesised_by_options
        )
        self.synthesised_by_hbox = ipw.HBox(
            [self.synthesised_by_label, self.synthesised_by_selector]
        )

        self.supplier_own_name_label = ipw.Label(value="Supplier own name")
        self.supplier_own_name_textbox = ipw.Text()
        self.supplier_own_name_hbox = ipw.HBox(
            [self.supplier_own_name_label, self.supplier_own_name_textbox]
        )

        self.receive_date_label = ipw.Label(value="Receive date")
        self.receive_date = ipw.DatePicker()
        self.receive_date_hbox = ipw.HBox([self.receive_date_label, self.receive_date])

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textbox = ipw.Textarea()
        self.comments_hbox = ipw.HBox([self.comments_label, self.comments_textbox])

        self.add_molecule_button = ipw.Button(
            description="Add molecule", button_style="success"
        )
        self.add_molecule_button.on_click(self.add_molecule)

        self.create_molecule_vbox = ipw.VBox()
        self.create_molecule_button = ipw.Button(
            description="Create molecule", button_style="success"
        )
        self.create_molecule_button.on_click(self.create_molecule)

        self.molecules_buttons = ipw.HBox(
            children=[self.add_molecule_button, self.create_molecule_button]
        )

        self.children = [
            self.molecules_title,
            self.molecules_accordion,
            self.create_molecule_vbox,
            self.molecules_buttons,
            self.evaporation_temperatures_title,
            self.evaporation_temperatures_table,
            self.properties_title,
            self.name_hbox,
            self.description_hbox,
            self.empa_number_hbox,
            self.batch_hbox,
            self.vial_hbox,
            self.purity_hbox,
            self.substance_type_hbox,
            self.amount_hbox,
            self.location_hbox,
            self.storage_conditions_hbox,
            self.package_opening_date_hbox,
            self.object_status_hbox,
            self.supplier_hbox,
            self.synthesised_by_hbox,
            self.supplier_own_name_hbox,
            self.receive_date_hbox,
            self.comments_hbox,
        ]

    def load_synthesisers(self, **kwargs):
        synthesisers = utils.get_openbis_objects(self.openbis_session, **kwargs)
        synthesisers_identifiers = []
        for obj in synthesisers:
            obj_name = obj.props["name"]
            organisations = obj.props.get("organisations") or []
            organisations_names_list = []
            for organisation in organisations:
                organisation_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=organisation
                )
                organisation_name = organisation_obj.props["name"]
                organisations_names_list.append(organisation_name)

            organisations_names = ", ".join(organisations_names_list)
            synthesiser_id = f"{obj_name} ({organisations_names})"
            synthesisers_identifiers.append(synthesiser_id)

        return synthesisers_identifiers

    def load_suppliers(self, **kwargs):
        suppliers = utils.get_openbis_objects(self.openbis_session, **kwargs)
        suppliers_identifiers = [(obj.props["name"], obj.permId) for obj in suppliers]
        return suppliers_identifiers

    def load_rooms(self, **kwargs):
        rooms = utils.get_openbis_objects(self.openbis_session, **kwargs)
        rooms_identifiers = []
        for obj in rooms:
            room_name = obj.props["name"]
            room_id = (f"{room_name} (Room)", obj.permId)
            rooms_identifiers.append(room_id)
        return rooms_identifiers

    def load_instruments(self, **kwargs):
        instruments = utils.get_openbis_objects(self.openbis_session, **kwargs)
        instruments_identifiers = []
        for obj in instruments:
            instrument_name = obj.props["name"]
            instrument_id = (f"{instrument_name} (Instrument)", obj.permId)
            instruments_identifiers.append(instrument_id)
        return instruments_identifiers

    def load_objects(self, **kwargs):
        objects = utils.get_openbis_objects(self.openbis_session, **kwargs)
        objects_identifiers = [(obj.props["name"], obj.permId) for obj in objects]
        return objects_identifiers

    def add_molecule(self, b):
        molecules_accordion_children = list(self.molecules_accordion.children)
        molecule_index = len(molecules_accordion_children)
        new_molecule_widget = MoleculeWidget(
            self.openbis_session, self.molecules_accordion, molecule_index
        )
        molecules_accordion_children.append(new_molecule_widget)
        self.molecules_accordion.children = molecules_accordion_children

    def create_molecule(self, b):
        create_molecule_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 16px;'>Create molecule</span>"
        )

        general_props_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 14px;'>General properties</span>"
        )

        name_label = ipw.Label(value="Name")
        name_textbox = ipw.Text()
        name_hbox = ipw.HBox(children=[name_label, name_textbox])

        description_label = ipw.Label(value="Description")
        description_textbox = ipw.Textarea()
        description_hbox = ipw.HBox(children=[description_label, description_textbox])

        cas_number_label = ipw.Label(value="CAS number")
        cas_number_textbox = ipw.Text()
        cas_number_hbox = ipw.HBox(children=[cas_number_label, cas_number_textbox])

        iupac_name_label = ipw.Label(value="IUPAC name")
        iupac_name_textbox = ipw.Text()
        iupac_name_hbox = ipw.HBox(children=[iupac_name_label, iupac_name_textbox])

        comments_label = ipw.Label(value="Comments")
        comments_textbox = ipw.Textarea()
        comments_hbox = ipw.HBox(children=[comments_label, comments_textbox])

        chemical_props_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 14px;'>Chemical properties</span>"
        )
        chemical_props_vbox = ipw.VBox()

        smiles_label = ipw.Label(value="SMILES")
        smiles_textbox = ipw.Text()
        smiles_hbox = ipw.HBox(children=[smiles_label, smiles_textbox])

        sum_formula_label = ipw.Label(value="Sum formula")
        sum_formula_textbox = ipw.Text()
        sum_formula_hbox = ipw.HBox(children=[sum_formula_label, sum_formula_textbox])

        sketch_label = ipw.Label(value="Molecule sketch")
        sketch_image = ipw.Image()
        sketch_hbox = ipw.HBox(children=[sketch_label, sketch_image])

        molecule_cdxml_label = ipw.Label(value="Upload molecule CDXML file")
        molecule_cdxml_uploader = ipw.FileUpload(accept=".cdxml")
        molecule_cdxml_hbox = ipw.HBox(
            children=[molecule_cdxml_label, molecule_cdxml_uploader]
        )

        def load_molecule_structure(change):
            # Create structures directory if it does not exist
            os.makedirs("structures", exist_ok=True)

            for filename in molecule_cdxml_uploader.value:
                file_info = molecule_cdxml_uploader.value[filename]
                utils.write_file(file_info["content"], "structures/structure.cdxml")

            cdxml_molecule = utils.read_file("structures/structure.cdxml")
            molecules = rdkit.Chem.MolsFromCDXML(cdxml_molecule)

            if len(molecules) == 1:
                mol = molecules[0]  # Get first molecule
                molecule_sum_formula = rdMolDescriptors.CalcMolFormula(
                    mol
                )  # Sum Formula
                molecule_smiles = rdkit.Chem.MolToSmiles(mol)  # Canonical Smiles
                chem_mol = rdkit.Chem.MolFromSmiles(molecule_smiles)

                smiles_textbox.value = molecule_smiles
                sum_formula_textbox.value = molecule_sum_formula

                if chem_mol is not None:
                    AllChem.Compute2DCoords(
                        chem_mol
                    )  # Add coords to the atoms in the molecule
                    img = Draw.MolToImage(chem_mol)
                    buffer = io.BytesIO()
                    img.save(buffer, format="PNG")
                    sketch_image.value = buffer.getvalue()
                    img.save("structures/structure.png")

                chemical_props_vbox.children = [
                    smiles_hbox,
                    sum_formula_hbox,
                    sketch_hbox,
                    molecule_cdxml_hbox,
                ]

        def save_molecule(b):
            molecule_dict = {
                "name": name_textbox.value,
                "description": description_textbox.value,
                "comments": comments_textbox.value,
                "iupac_name": iupac_name_textbox.value,
                "cas_number": cas_number_textbox.value,
                "smiles": smiles_textbox.value,
                "sum_formula": sum_formula_textbox.value,
            }

            molecule_object = utils.create_openbis_object(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Molecule"],
                collection=OPENBIS_COLLECTIONS_PATHS["Precursor Molecule"],
                props=molecule_dict,
            )

            utils.create_openbis_dataset(
                self.openbis_session,
                sample=molecule_object,
                type="ELN_PREVIEW",
                files=["structures/structure.png"],
                props={"name": "Sketch"},
            )

            utils.create_openbis_dataset(
                self.openbis_session,
                sample=molecule_object,
                type="ATTACHMENT",
                files=["structures/structure.cdxml"],
                props={"name": "Structure file"},
            )

            shutil.rmtree("structures")

            display(Javascript(data="alert('Molecule created successfully!')"))
            self.create_molecule_vbox.children = []

        def close_molecule(b):
            self.create_molecule_vbox.children = []

        molecule_cdxml_uploader.observe(load_molecule_structure, names="value")
        chemical_props_vbox.children = [molecule_cdxml_hbox]

        save_molecule_button = ipw.Button(icon="fa-save")
        save_molecule_button.on_click(save_molecule)

        close_molecule_button = ipw.Button(icon="fa-times")
        close_molecule_button.on_click(close_molecule)

        save_close_molecule_buttons = ipw.HBox(
            children=[save_molecule_button, close_molecule_button]
        )

        self.create_molecule_vbox.children = [
            create_molecule_title,
            general_props_title,
            name_hbox,
            description_hbox,
            comments_hbox,
            chemical_props_title,
            iupac_name_hbox,
            cas_number_hbox,
            chemical_props_vbox,
            save_close_molecule_buttons,
        ]

    def reset_widgets(self):
        self.name_textbox.value = ""
        self.description_textbox.value = ""
        self.empa_number_textbox.value = 0
        self.batch_textbox.value = ""
        self.vial_textbox.value = ""
        self.purity_textbox.value = 0
        self.substance_type_textbox.value = ""
        self.storage_conditions_selector.value = []
        self.object_status_dropdown.value = "Active"
        self.synthesised_by_selector.value = []
        self.supplier_own_name_textbox.value = ""
        self.comments_textbox.value = ""
        self.amount_value_textbox.value = ""
        self.amount_unit_dropdown.value = "g"
        self.location_dropdown.value = "-1"
        self.package_opening_date.value = None
        self.supplier_dropdown.value = "-1"
        self.receive_date.value = None

        for index, _ in enumerate(self.molecules_accordion.children):
            self.molecules_accordion.set_title(index, "")

        self.molecules_accordion.children = []

        self.evaporation_temperatures_table.reset_table()


class TableWidget(ipw.GridBox):
    def __init__(self, headers_items, row_items):
        super().__init__()

        self.headers_items = headers_items
        self.row_items = row_items
        self.gridbox_items = headers_items + row_items
        num_cols = len(headers_items)

        self.table_gridbox = ipw.GridBox(
            self.gridbox_items,
            layout=ipw.Layout(grid_template_columns=f"repeat({num_cols}, 15%)"),
        )

        self.table_gridbox = ipw.GridBox(
            self.gridbox_items,
            layout=ipw.Layout(grid_template_columns=f"repeat({num_cols}, 15%)"),
        )

        self.add_row_button = ipw.Button(icon="fa-plus", button_style="success")
        self.remove_row_button = ipw.Button(icon="fa-minus", button_style="danger")
        self.table_buttons = ipw.HBox(
            children=[self.add_row_button, self.remove_row_button]
        )

        self.add_row_button.on_click(self.add_row)
        self.remove_row_button.on_click(self.remove_row)

        self.children = [self.table_gridbox, self.table_buttons]

    def add_row(self, b):
        grid_box_items = list(self.table_gridbox.children)
        new_row_items = utils.clone_widgets_empty(self.row_items)
        grid_box_items.extend(new_row_items)
        self.table_gridbox.children = grid_box_items

    def remove_row(self, b):
        grid_box_items = list(self.table_gridbox.children)
        if len(grid_box_items) > 8:
            self.table_gridbox.children = grid_box_items[:-4]
        elif len(grid_box_items) > 4:
            new_row_items = utils.clone_widgets_empty(self.row_items)
            self.table_gridbox.children = self.headers_items + new_row_items

    def reset_table(self):
        new_row_items = utils.clone_widgets_empty(self.row_items)
        self.table_gridbox.children = self.headers_items + new_row_items
