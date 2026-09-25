import html
import io
import os
import shutil
import struct

import ipywidgets as ipw
import pandas as pd
import rdkit
from IPython.display import Javascript, display
from rdkit.Chem import AllChem, Draw, rdMolDescriptors

from src import chemical_search, molecule_creation, utils

INTERFACE_CONFIG_INFO = utils.get_interface_config_info()
OPENBIS_OBJECT_TYPES, _ = (
    INTERFACE_CONFIG_INFO["object_types"],
    INTERFACE_CONFIG_INFO["object_types_codes"],
)
MATERIALS_CONCEPTS_TYPES = INTERFACE_CONFIG_INFO["slabs_concepts_types"]
INSTRUMENTS_TYPES = INTERFACE_CONFIG_INFO["instruments_types"]

OPENBIS_CONFIG = utils.read_json("config/openbis_config.json")
SIMULATION_TYPES = OPENBIS_CONFIG["Simulations"]["Types"]
OPENBIS_COLLECTIONS_PATHS = OPENBIS_CONFIG["Collections"]["Paths"]
OPENBIS_PROJECTS_PATHS = OPENBIS_CONFIG["Projects"]["Paths"]
institutions_project = OPENBIS_PROJECTS_PATHS.get("Institution")
people_project = OPENBIS_PROJECTS_PATHS.get("Person")
locations_project = OPENBIS_PROJECTS_PATHS.get("Location")


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
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Atomistic Model"],
            props=["name"],
        )
        atom_model_frame = getattr(atom_models, "df", None)
        if atom_model_frame is not None:
            atom_model_options = []
            for record in atom_model_frame.to_dict(orient="records"):
                name = record.get("NAME")
                if name is None or pd.isna(name) or not str(name).strip():
                    name = record["permId"]
                atom_model_options.append((str(name), str(record["permId"])))
        else:
            atom_model_options = [
                (f"{obj.props['name']}", obj.permId) for obj in atom_models
            ]
        atom_model_options.sort()
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
            value="<span style='font-weight: bold; font-size: 18px;'>Select product molecules</span>"
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
            tooltip="Add product molecule",
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

        description_label = ipw.Label(value="Description")
        description_textbox = ipw.Textarea()
        description_hbox = ipw.HBox([description_label, description_textbox])

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
                description_hbox,
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
                materials_objects_names_permids.sort()
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
            wfms_uuid = wfms_uuid_textbox.value.strip()
            existing = (
                list(
                    utils.get_openbis_objects(
                        self.openbis_session,
                        type=atom_model_type,
                        where={"WFMS_UUID": wfms_uuid},
                    )
                    or []
                )
                if wfms_uuid
                else []
            )
            if existing:
                display(Javascript(data="alert('Atomistic model already in openBIS!')"))
            else:
                pbc = [pbc_x_checkbox.value, pbc_y_checkbox.value, pbc_z_checkbox.value]
                cell_json = cell_textbox.value

                if not utils.is_valid_json(cell_json):
                    cell_json = ""

                atom_model_props = {
                    "name": name_textbox.value,
                    "description": description_textbox.value,
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

                utils.upload_datasets(
                    self.openbis_session,
                    atom_model_obj,
                    atom_model_preview_uploader,
                    props={},
                    dataset_type="ELN_PREVIEW",
                )
                utils.upload_datasets(
                    self.openbis_session,
                    atom_model_obj,
                    atom_model_datasets_uploader,
                    props={},
                    dataset_type="ATTACHMENT",
                )

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
    def __init__(
        self,
        openbis_session,
        parent_accordion,
        object_index,
        collection_key="Precursor Molecule",
        role="molecule",
        structure=None,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.parent_accordion = parent_accordion
        self.object_index = object_index
        self.collection_key = collection_key
        self.role = role
        self.title = ""
        self.structure = structure
        self.generated_cdxml = b""
        self.generated_png = b""
        self.generated_representation = None

        molecules_objects = utils.get_openbis_objects(
            self.openbis_session,
            collection=OPENBIS_COLLECTIONS_PATHS[collection_key],
            type=OPENBIS_OBJECT_TYPES["Molecule"],
        )
        dropdown_list = []
        self._labels_by_permid = {}
        for obj in molecules_objects:
            name = obj.props.get("name") or str(obj.permId)
            empa_number = obj.props.get("empa_number")
            label = (
                f"{empa_number} ({name})"
                if collection_key == "Precursor Molecule" and empa_number
                else str(name)
            )
            self._labels_by_permid[str(obj.permId)] = label
            dropdown_list.append((label, obj.permId))

        if collection_key == "Precursor Molecule":
            # Keep the established newest/highest EMPA-number-first ordering.
            def precursor_sort_key(item):
                first_word = str(item[0]).split(maxsplit=1)[0]
                try:
                    return int(first_word)
                except ValueError:
                    return -1

            dropdown_list.sort(key=precursor_sort_key, reverse=True)
        else:
            dropdown_list.sort(key=lambda item: item[0].casefold())
        placeholder = (
            "Select a product molecule..."
            if collection_key == "Product Molecule"
            else "Select a molecule..."
        )
        dropdown_list.insert(0, (placeholder, "-1"))
        self.dropdown = ipw.Dropdown(value="-1", options=dropdown_list)
        self.details_vbox = ipw.VBox()
        self.collection = OPENBIS_COLLECTIONS_PATHS[collection_key]
        self.structure_search = chemical_search.MoleculeStructureSearchWidget(
            self.openbis_session,
            self.collection,
            on_select=self._select_search_result,
            on_search_complete=self._search_completed,
            on_query_change=self._search_query_changed,
        )
        self.structure_search_accordion = ipw.Accordion(
            children=[self.structure_search],
            selected_index=None,
        )
        self.structure_search_accordion.set_title(0, "Find by SMILES or CDXML")
        self.create_generated_box = ipw.VBox()

        self.cdxml_generator_accordion = None
        if structure is not None:
            self.open_cdxml_generator_button = ipw.Button(
                description="Open CDXML generator",
                button_style="info",
                tooltip="Review inferred bonds and generate periodic CDXML",
            )
            self.cdxml_generator_status = ipw.HTML(
                "For planar C/H structures with one bonded periodic direction. "
                "Ambiguous long bonds and radicals remain under user control."
            )
            self.cdxml_generator_box = ipw.VBox(
                [self.cdxml_generator_status, self.open_cdxml_generator_button]
            )
            self.cdxml_generator_accordion = ipw.Accordion(
                children=[self.cdxml_generator_box],
                selected_index=None,
            )
            self.cdxml_generator_accordion.set_title(
                0, "Generate CDXML from AiiDA structure"
            )
            self.open_cdxml_generator_button.on_click(self._open_cdxml_generator)

        self.remove_molecule_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip=f"Remove {role}",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.molecule_sketch = ipw.Image(
            format="png",
            layout=ipw.Layout(width="300px", height="auto"),
        )

        self.dropdown.observe(self.load_details, names="value")
        self.remove_molecule_button.on_click(self.remove_molecule)
        children = [self.dropdown]
        if self.cdxml_generator_accordion is not None:
            children.append(self.cdxml_generator_accordion)
        children.extend(
            [
                self.structure_search_accordion,
                self.create_generated_box,
                self.details_vbox,
                self.molecule_sketch,
                self.remove_molecule_button,
            ]
        )
        self.children = children

    def _open_cdxml_generator(self, _button=None):
        self.open_cdxml_generator_button.disabled = True
        try:
            from src.cdxml_editor import PeriodicCdxmlEditor

            self.cdxml_editor = PeriodicCdxmlEditor(
                structure=self.structure,
                on_export=self._use_generated_cdxml,
            )
            self.cdxml_generator_box.children = [self.cdxml_editor]
        except Exception as exc:
            self.open_cdxml_generator_button.disabled = False
            self.cdxml_generator_status.value = (
                "<span style='color:#b00020'><b>Could not open the CDXML "
                f"generator:</b> {html.escape(str(exc))}</span>"
            )

    def _use_generated_cdxml(self, content, filename, png, representation):
        self.generated_cdxml = bytes(content)
        self.generated_png = bytes(png)
        self.generated_representation = representation
        self.structure_search.set_cdxml_query(content, filename)
        self.create_generated_box.children = [
            ipw.HTML("Search this generated CDXML before creating a MOLECULE record.")
        ]
        self.structure_search_accordion.selected_index = 0

    def _search_query_changed(self):
        self.create_generated_box.children = []

    def _set_creation_status(self, message, kind="info"):
        colors = {"info": "#1f5a94", "ok": "#187b35", "error": "#b00020"}
        self.creation_status.value = (
            f"<span style='color:{colors[kind]}'>{html.escape(str(message))}</span>"
        )

    def _search_completed(self, query, hits):
        if self.structure_search._generated_cdxml is None or not self.generated_cdxml:
            self.create_generated_box.children = []
            return
        identity_hits = [
            hit for hit in hits if hit.match_type in {"exact", "equivalent"}
        ]
        if identity_hits:
            matches = ", ".join(
                hit.record.name or hit.record.permid for hit in identity_hits
            )
            self.create_generated_box.children = [
                ipw.HTML(
                    "<span style='color:#187b35'><b>An identical or equivalent "
                    "MOLECULE already exists.</b> Select it from the search results: "
                    f"{html.escape(matches)}</span>"
                )
            ]
            return

        representation = self.generated_representation
        if representation is None:
            self.create_generated_box.children = []
            return
        representation_name = "CXSMILES" if representation.periodic else "SMILES"
        representation_value = (
            representation.cxsmiles
            if representation.periodic
            else representation.smiles
        )
        destination = (
            "product molecule collection"
            if self.collection_key == "Product Molecule"
            else "precursor molecule collection"
        )
        self.new_molecule_name = ipw.Text(
            description="Name",
            placeholder="Required molecular concept name",
            style={"description_width": "90px"},
            layout=ipw.Layout(width="100%"),
        )
        self.new_molecule_description = ipw.Textarea(
            description="Description",
            style={"description_width": "90px"},
            layout=ipw.Layout(width="100%", height="55px"),
        )
        self.new_molecule_comments = ipw.Textarea(
            description="Comments",
            style={"description_width": "90px"},
            layout=ipw.Layout(width="100%", height="55px"),
        )
        self.reviewed_matches = ipw.Checkbox(
            value=not bool(hits),
            description="I reviewed the non-identity matches shown above",
            indent=False,
            layout=ipw.Layout(display="" if hits else "none", width="100%"),
        )
        self.create_generated_button = ipw.Button(
            description="Create MOLECULE",
            button_style="success",
            icon="save",
            tooltip=f"Create in the {destination}",
        )
        self.creation_status = ipw.HTML()
        self.create_generated_button.on_click(self._create_generated_molecule)
        self.create_generated_box.children = [
            ipw.HTML(
                "<hr><b>No identical molecular concept was found.</b> Create the "
                f"reviewed structure in the {html.escape(destination)}.<br>"
                f"Formula: <code>{html.escape(representation.formula)}</code><br>"
                f"{representation_name}: "
                f"<code>{html.escape(representation_value)}</code>"
            ),
            self.new_molecule_name,
            self.new_molecule_description,
            self.new_molecule_comments,
            self.reviewed_matches,
            self.create_generated_button,
            self.creation_status,
        ]

    def _create_generated_molecule(self, _button=None):
        if not self.new_molecule_name.value.strip():
            self._set_creation_status(
                "Enter a name before creating the MOLECULE.", "error"
            )
            return
        if not self.reviewed_matches.value:
            self._set_creation_status(
                "Review the listed matches before creating a new record.", "error"
            )
            return
        if (
            self.structure_search.input_kind.value != "cdxml"
            or self.structure_search._generated_cdxml is None
        ):
            self._set_creation_status(
                "The active search is no longer the generated CDXML.", "error"
            )
            return

        self.create_generated_button.disabled = True
        created = None
        try:
            self._set_creation_status(
                "Refreshing the collection and checking identity…"
            )
            self.structure_search.index.refresh(progress=self._set_creation_status)
            query = self.structure_search._query()
            current_hits = self.structure_search.index.search(
                query,
                min_similarity=0.75,
                limit=max(1, len(self.structure_search.index.records)),
            )
            identity_hits = [
                hit for hit in current_hits if hit.match_type in {"exact", "equivalent"}
            ]
            if identity_hits:
                self._search_completed(query, tuple(current_hits))
                return

            filename, _content = self.structure_search._generated_cdxml
            created = molecule_creation.create_molecule_from_cdxml(
                self.openbis_session,
                collection=self.collection,
                name=self.new_molecule_name.value,
                description=self.new_molecule_description.value,
                comments=self.new_molecule_comments.value,
                cdxml=self.generated_cdxml,
                png=self.generated_png,
                filename=filename,
                expected_representation=self.generated_representation,
            )
        except molecule_creation.PartialMoleculeCreationError as exc:
            self._set_creation_status(str(exc), "error")
            return
        except Exception as exc:
            self._set_creation_status(
                f"Creation failed before completion: {type(exc).__name__}: {exc}",
                "error",
            )
            return
        finally:
            self.create_generated_button.disabled = False

        permid = str(created.permId)
        label = self.new_molecule_name.value.strip()
        try:
            self._labels_by_permid[permid] = label
            current_values = {str(value) for _label, value in self.dropdown.options}
            if permid not in current_values:
                self.dropdown.options = list(self.dropdown.options) + [
                    (label, created.permId)
                ]
            self.dropdown.value = created.permId
            self.structure_search.index.refresh(progress=self._set_creation_status)
            refreshed_hits = self.structure_search.index.search(
                self.structure_search._query(),
                min_similarity=0.75,
                limit=max(1, len(self.structure_search.index.records)),
            )
            confirmed = any(
                hit.record.permid == permid and hit.match_type == "exact"
                for hit in refreshed_hits
            )
            if not confirmed:
                raise RuntimeError("the new object was not found as an exact match")
            self.structure_search.last_query = self.structure_search._query()
            self.structure_search.last_hits = tuple(refreshed_hits)
            self.structure_search._hits_by_permid = {
                hit.record.permid: hit for hit in refreshed_hits
            }
            self.structure_search.results.options = [("Select a match...", "")] + [
                (
                    f"{hit.match_type} · Q{chemical_search.tanimoto_to_match_quality(hit.similarity)} "
                    f"(T={100 * hit.similarity:.1f}%) · "
                    f"{hit.record.empa_number or hit.record.name or hit.record.permid}",
                    hit.record.permid,
                )
                for hit in refreshed_hits
            ]
            self.structure_search._set_status(
                f"Created and indexed {label} as an exact match.", "ok"
            )
            try:
                url = utils.generate_openbis_object_url(self.openbis_session, created)
                link = (
                    f" <a href='{html.escape(url, quote=True)}' target='_blank'>"
                    "Open in openBIS</a>"
                )
            except Exception:
                link = ""
            self.create_generated_box.children = [
                ipw.HTML(
                    "<span style='color:#187b35'><b>MOLECULE created, indexed, "
                    f"and selected:</b> {html.escape(permid)}.{link}</span>"
                )
            ]
        except Exception as exc:
            self.create_generated_box.children = [
                ipw.HTML(
                    "<span style='color:#b36b00'><b>The MOLECULE was created and "
                    "selected, but index verification failed.</b> Do not create it "
                    f"again. PermID: {html.escape(permid)}. "
                    f"{html.escape(type(exc).__name__ + ': ' + str(exc))}</span>"
                )
            ]

    def _select_search_result(self, permid):
        values = {
            str(value): value
            for _label, value in self.dropdown.options
        }
        value = values.get(str(permid))
        if value is None:
            hit = self.structure_search._hits_by_permid.get(str(permid))
            label = (
                hit.record.name
                if hit is not None and hit.record.name
                else str(permid)
            )
            self.dropdown.options = list(self.dropdown.options) + [(label, permid)]
            value = permid
        self.dropdown.value = value

    def _set_molecule_sketch(self, content):
        """Display a PNG with its longest side at 300 px and no distortion."""
        data = bytes(content)
        self.molecule_sketch.value = data
        width = height = 0
        if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
            width, height = struct.unpack(">II", data[16:24])
        if height > width:
            self.molecule_sketch.layout.width = "auto"
            self.molecule_sketch.layout.height = "300px"
        else:
            self.molecule_sketch.layout.width = "300px"
            self.molecule_sketch.layout.height = "auto"

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
            selected_label = self._labels_by_permid.get(
                str(obj_permid), obj_name or str(obj_permid)
            )
            if self.object_index < len(self.parent_accordion.children):
                self.parent_accordion.set_title(self.object_index, selected_label)
            self.title = selected_label

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
                object_image_filepath = str(object_dataset.file_list[0])
                self._set_molecule_sketch(
                    chemical_search.download_dataset_file(
                        object_dataset,
                        object_image_filepath,
                    )
                )
            else:
                self._set_molecule_sketch(b"")

            self.details_vbox.children = [obj_details_html]

    def remove_molecule(self, b):
        molecules_accordion_children = list(self.parent_accordion.children)
        molecules_accordion_children.pop(self.object_index)

        for index, molecule in enumerate(molecules_accordion_children):
            molecule.object_index = index

        self.parent_accordion.children = molecules_accordion_children
        self.parent_accordion.titles = tuple(
            molecule.title for molecule in molecules_accordion_children
        )


class ReacProdConceptWidget(MoleculeWidget):
    """Compatibility alias for a product molecule selector."""

    def __init__(self, openbis_session, parent_accordion, object_index):
        super().__init__(
            openbis_session,
            parent_accordion,
            object_index,
            collection_key="Product Molecule",
            role="product molecule",
        )


class SelectInstrumentWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.instrument_label = ipw.HTML(value="<b>Instrument:</b>")

        self.instrument_dropdown = ipw.Dropdown()
        self.load_instruments()

        self.sort_instrument_label = ipw.HTML(value="<b>Sort by:</b>")

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
        for instrument_type in INSTRUMENTS_TYPES.values():
            instruments_objects = utils.get_openbis_objects(
                self.openbis_session, type=instrument_type
            )
            instruments.extend(instruments_objects)

        instrument_options = [
            (f"{obj.props['name']}", obj.permId) for obj in instruments
        ]
        instrument_options.sort()
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
        self.current_user = self.openbis_session._get_username()

        # 1. State DataFrames
        self.raw_experiments_df = None
        self.raw_projects_df = None

        # 2. Build the UI components (but keep the creation panel hidden at first)
        self._setup_main_ui()
        self._setup_create_ui()

        # 3. Assemble and load initial data
        self.children = [self.main_ui_container, self.create_new_experiment_widgets]
        self.load_experiments()

    # ==========================================
    # 1. UI SETUP METHODS
    # ==========================================
    def _setup_main_ui(self):
        """Sets up the main Experiment selection dropdown and filters."""
        self.experiment_label = ipw.HTML(
            value="<b>Experiment:</b>", layout=ipw.Layout(width="80px")
        )
        self.experiment_dropdown = ipw.Dropdown(
            options=[("Select experiment...", "-1")],
            value="-1",
            layout=ipw.Layout(width="500px"),
        )
        self.create_experiment_button = ipw.Button(
            tooltip="Add new experiment",
            icon="plus",
            layout=ipw.Layout(width="50px", height="28px"),
        )
        self.create_experiment_button.on_click(self.show_create_panel)

        self.exp_hbox = ipw.HBox(
            [
                self.experiment_label,
                self.experiment_dropdown,
                self.create_experiment_button,
            ]
        )

        # Sorting and Filtering
        self.sort_label = ipw.HTML(
            value="<b>Sort by:</b>", layout=ipw.Layout(width="80px")
        )
        self.sort_name_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_name_label = ipw.Label("Name", layout=ipw.Layout(width="60px"))
        self.sort_date_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_date_label = ipw.Label("Registration Date")

        self.filter_label = ipw.HTML(
            value="<b>Filter:</b>", layout=ipw.Layout(width="80px")
        )
        self.filter_my_exp_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.filter_my_exp_label = ipw.Label("My Experiments Only")

        self.sort_hbox = ipw.HBox(
            children=[
                self.sort_label,
                self.sort_name_cb,
                self.sort_name_label,
                self.sort_date_cb,
                self.sort_date_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )
        self.filter_hbox = ipw.HBox(
            children=[
                self.filter_label,
                self.filter_my_exp_cb,
                self.filter_my_exp_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )

        # Observers
        self.sort_name_cb.observe(self.update_experiment_dropdown, names="value")
        self.sort_date_cb.observe(self.update_experiment_dropdown, names="value")
        self.filter_my_exp_cb.observe(self.update_experiment_dropdown, names="value")

        self.main_ui_container = ipw.VBox(
            [self.exp_hbox, self.sort_hbox, self.filter_hbox]
        )

    def _setup_create_ui(self):
        """Sets up the 'Create New Experiment' form (initially empty/hidden)."""
        self.create_new_experiment_widgets = (
            ipw.VBox()
        )  # We populate this when the '+' is clicked

        # Project UI
        self.project_label = ipw.HTML(
            value="<b>Project:</b>", layout=ipw.Layout(width="80px")
        )
        self.project_dropdown = ipw.Dropdown(
            options=[("Select project...", "-1")],
            value="-1",
            layout=ipw.Layout(width="500px"),
        )
        self.project_hbox = ipw.HBox([self.project_label, self.project_dropdown])

        # Sort Row
        self.sort_proj_label = ipw.HTML(
            value="<b>Sort by:</b>", layout=ipw.Layout(width="80px")
        )
        self.sort_proj_name_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_proj_name_label = ipw.Label("Name", layout=ipw.Layout(width="60px"))
        self.sort_proj_date_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_proj_date_label = ipw.Label("Registration Date")

        self.sort_proj_hbox = ipw.HBox(
            children=[
                self.sort_proj_label,
                self.sort_proj_name_cb,
                self.sort_proj_name_label,
                self.sort_proj_date_cb,
                self.sort_proj_date_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )

        # Filter Row (Now on its own line)
        self.filter_proj_label = ipw.HTML(
            value="<b>Filter:</b>", layout=ipw.Layout(width="80px")
        )
        self.filter_my_proj_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.filter_my_proj_label = ipw.Label("My Projects Only")

        self.filter_proj_hbox = ipw.HBox(
            children=[
                self.filter_proj_label,
                self.filter_my_proj_cb,
                self.filter_my_proj_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )

        # Name Input
        self.new_exp_name_label = ipw.HTML(
            value="<b>Name:</b>", layout=ipw.Layout(width="80px")
        )
        self.new_exp_name_textbox = ipw.Text(
            placeholder="Write experiment name...", layout=ipw.Layout(width="500px")
        )
        self.new_exp_name_hbox = ipw.HBox(
            [self.new_exp_name_label, self.new_exp_name_textbox]
        )

        # Buttons (Reverted back to your original uncolored, 50px height styling)
        self.save_btn = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )
        self.cancel_btn = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Cancel",
            icon="times",
            layout=ipw.Layout(width="100px", height="50px"),
        )
        self.buttons_hbox = ipw.HBox([self.save_btn, self.cancel_btn])

        # Observers for Projects
        self.sort_proj_name_cb.observe(self.update_project_dropdown, names="value")
        self.sort_proj_date_cb.observe(self.update_project_dropdown, names="value")
        self.filter_my_proj_cb.observe(self.update_project_dropdown, names="value")
        self.save_btn.on_click(self.save_new_experiment)
        self.cancel_btn.on_click(self.hide_create_panel)

        # Assembling the layout with the new filter row included
        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.create_panel_content = [
            ipw.HTML(f"<div style='{header_style}'>Create new experiment</div>"),
            self.project_hbox,
            self.sort_proj_hbox,
            self.filter_proj_hbox,  # <-- New filter row added here
            self.new_exp_name_hbox,
            self.buttons_hbox,
            ipw.HTML("<hr>"),
        ]

    # ==========================================
    # 2. DATA LOADING METHODS
    # ==========================================
    def load_experiments(self):
        """Fetch experiments and their display properties in one openBIS request."""
        experiments = utils.get_openbis_collections(
            self.openbis_session,
            type="EXPERIMENT",
            props=["name"],
        )

        data = []
        experiment_frame = getattr(experiments, "df", None)
        if experiment_frame is not None:
            for record in experiment_frame.to_dict(orient="records"):
                identifier_parts = [
                    part
                    for part in str(record.get("identifier") or "").split("/")
                    if part
                ]
                space = identifier_parts[0] if identifier_parts else ""
                project = identifier_parts[1] if len(identifier_parts) > 1 else ""
                code = identifier_parts[-1] if identifier_parts else ""
                name = record.get("NAME")
                if name is None or pd.isna(name) or not str(name).strip():
                    name = code
                registrator = record.get("registrator")
                data.append(
                    {
                        "display_name": (
                            f"{name} from Project {project} and Space {space}"
                        ),
                        "permId": str(record["permId"]),
                        "is_mine": registrator == self.current_user,
                    }
                )
        else:
            for exp in experiments:
                name = exp.props["name"] if "name" in exp.props.all() else exp.code
                display_name = (
                    f"{name} from Project {exp.project.code} "
                    f"and Space {exp.project.space}"
                )
                registrator = getattr(exp.registrator, "userId", exp.registrator)

                data.append(
                    {
                        "display_name": display_name,
                        "permId": exp.permId,
                        "is_mine": registrator == self.current_user,
                    }
                )

        self.raw_experiments_df = pd.DataFrame(data)
        self.update_experiment_dropdown(None)

    def load_projects(self):
        """Fetches projects from openBIS ONCE and stores them."""
        if self.raw_projects_df is not None:
            return  # Skip if already loaded

        projects = utils.get_openbis_projects(self.openbis_session)

        data = []
        for proj in projects:
            display_name = f"{proj.code} from Space {proj.space}"
            registrator = getattr(proj.registrator, "userId", proj.registrator)

            data.append(
                {
                    "display_name": display_name,
                    "permId": proj.permId,
                    "is_mine": registrator == self.current_user,
                }
            )

        self.raw_projects_df = pd.DataFrame(data)
        self.update_project_dropdown(None)

    # ==========================================
    # 3. DROPDOWN UPDATE ENGINES
    # ==========================================
    def update_experiment_dropdown(self, change):
        if self.raw_experiments_df is None or self.raw_experiments_df.empty:
            return

        df = self.raw_experiments_df.copy()

        if self.filter_my_exp_cb.value:
            df = df[df["is_mine"]]

        sort_cols, sort_asc = ["is_mine"], [False]
        if self.sort_name_cb.value:
            sort_cols.append("display_name")
            sort_asc.append(True)
        if self.sort_date_cb.value or (
            not self.sort_name_cb.value and not self.sort_date_cb.value
        ):
            sort_cols.append("permId")
            sort_asc.append(False)

        df = df.sort_values(by=sort_cols, ascending=sort_asc)
        options = list(
            df[["display_name", "permId"]].itertuples(index=False, name=None)
        )
        options.insert(0, ("Select experiment...", "-1"))
        selected = self.experiment_dropdown.value
        self.experiment_dropdown.options = options
        if selected not in {value for _label, value in options}:
            self.experiment_dropdown.value = "-1"

    def update_project_dropdown(self, change):
        if self.raw_projects_df is None or self.raw_projects_df.empty:
            return

        df = self.raw_projects_df.copy()

        if self.filter_my_proj_cb.value:
            df = df[df["is_mine"]]

        sort_cols, sort_asc = ["is_mine"], [False]
        if self.sort_proj_name_cb.value:
            sort_cols.append("display_name")
            sort_asc.append(True)
        if self.sort_proj_date_cb.value or (
            not self.sort_proj_name_cb.value and not self.sort_proj_date_cb.value
        ):
            sort_cols.append("permId")
            sort_asc.append(False)

        df = df.sort_values(by=sort_cols, ascending=sort_asc)
        options = list(
            df[["display_name", "permId"]].itertuples(index=False, name=None)
        )
        options.insert(0, ("Select project...", "-1"))
        selected = self.project_dropdown.value
        self.project_dropdown.options = options
        if selected not in {value for _label, value in options}:
            self.project_dropdown.value = "-1"

    # ==========================================
    # 4. ACTION HANDLERS
    # ==========================================
    def show_create_panel(self, b):
        self.load_projects()  # Load data only when button is clicked
        self.create_new_experiment_widgets.children = self.create_panel_content

    def hide_create_panel(self, b=None):
        self.create_new_experiment_widgets.children = []
        self.new_exp_name_textbox.value = ""  # Clear the input

    def save_new_experiment(self, b):
        project_id = self.project_dropdown.value
        exp_name = self.new_exp_name_textbox.value.strip()

        if project_id == "-1":
            display(Javascript(data="alert('Select a project.')"))
            return
        if not exp_name:
            display(Javascript(data="alert('Experiment name cannot be empty.')"))
            return

        try:
            new_experiment = utils.create_openbis_collection(
                self.openbis_session,
                type="EXPERIMENT",
                project=project_id,
                props={
                    "name": exp_name,
                    "default_collection_view": "IMAGING_GALLERY_VIEW",
                },
            )
            self.hide_create_panel()
            self.load_experiments()  # Reload the main DataFrame
            self.experiment_dropdown.value = new_experiment.permId
            display(Javascript(data="alert('Experiment successfully created!')"))

        except ValueError:
            display(
                Javascript(data="alert('Error! Check if experiment already exists.')")
            )


class SelectSampleWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        # 1. State variables to hold our raw data
        self.current_user = self.openbis_session._get_username()
        self.raw_data_df = (
            None  # We will store the unfiltered, unsorted openBIS data here
        )

        # 2. Build the UI
        self._setup_ui()
        self._setup_edit_ui()

        # 3. Load the data exactly once
        self.children = [self.main_ui_container, self.edit_sample_widgets]
        self.load_samples()

    def _setup_ui(self):
        """Sets up all the UI widgets and their observers."""
        # --- Dropdown ---
        self.sample_label = ipw.HTML(
            value="<b>Sample:</b>", layout=ipw.Layout(width="70px")
        )
        self.sample_dropdown = ipw.Dropdown(layout=ipw.Layout(width="500px"))

        self.edit_sample_button = ipw.Button(
            tooltip="Edit selected sample",
            icon="edit",
            layout=ipw.Layout(width="50px", height="28px"),
        )

        self.edit_sample_button.on_click(self.show_edit_panel)

        # --- Sorting Checkboxes ---
        self.sort_label = ipw.HTML(
            value="<b>Sort by:</b>", layout=ipw.Layout(width="70px")
        )

        self.sort_name_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_name_label = ipw.Label("Name", layout=ipw.Layout(width="60px"))

        self.sort_date_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.sort_date_label = ipw.Label("Registration Date")

        # --- New Filtering Checkbox ---
        self.filter_label = ipw.HTML(
            value="<b>Filter:</b>", layout=ipw.Layout(width="70px")
        )
        self.filter_my_samples_cb = ipw.Checkbox(
            indent=False, layout=ipw.Layout(width="20px", margin="0px")
        )
        self.filter_my_samples_label = ipw.Label("My Samples Only")

        # --- Observers (Connect UI to the update function) ---
        # Instead of multiple functions, any UI change triggers the single update_dropdown function
        self.sort_name_cb.observe(self.update_dropdown, names="value")
        self.sort_date_cb.observe(self.update_dropdown, names="value")
        self.filter_my_samples_cb.observe(self.update_dropdown, names="value")

        # --- Layout Assembly ---
        self.sample_hbox = ipw.HBox(
            [self.sample_label, self.sample_dropdown, self.edit_sample_button]
        )

        self.sort_hbox = ipw.HBox(
            children=[
                self.sort_label,
                self.sort_name_cb,
                self.sort_name_label,
                self.sort_date_cb,
                self.sort_date_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )

        self.filter_hbox = ipw.HBox(
            children=[
                self.filter_label,
                self.filter_my_samples_cb,
                self.filter_my_samples_label,
            ],
            layout=ipw.Layout(align_items="center"),
        )

        self.main_ui_container = ipw.VBox(
            [self.sample_hbox, self.sort_hbox, self.filter_hbox]
        )

    def _setup_edit_ui(self):
        """Sets up the 'Edit Sample Name' form (initially hidden)."""
        self.edit_sample_widgets = ipw.VBox()

        # Name input text box
        self.edit_name_label = ipw.HTML(
            value="<b>New Name:</b>", layout=ipw.Layout(width="80px")
        )
        self.edit_name_textbox = ipw.Text(
            placeholder="Enter new sample name...", layout=ipw.Layout(width="500px")
        )
        self.edit_name_hbox = ipw.HBox([self.edit_name_label, self.edit_name_textbox])

        # Buttons matches your original sizing
        self.save_btn = ipw.Button(
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )
        self.cancel_btn = ipw.Button(
            tooltip="Cancel",
            icon="times",
            layout=ipw.Layout(width="100px", height="50px"),
        )
        self.buttons_hbox = ipw.HBox([self.save_btn, self.cancel_btn])

        self.save_btn.on_click(self.save_sample_edit)
        self.cancel_btn.on_click(self.hide_edit_panel)

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.edit_panel_content = [
            ipw.HTML(f"<div style='{header_style}'>Edit selected sample</div>"),
            self.edit_name_hbox,
            self.buttons_hbox,
            ipw.HTML("<hr>"),
        ]

    def load_samples(self):
        """Fetches data from openBIS ONCE and stores it in a master DataFrame."""
        sample_type = OPENBIS_OBJECT_TYPES["Sample"]  # Ensure this is defined globally
        samples = utils.get_openbis_objects(
            self.openbis_session,
            type=sample_type,
            attrs=["parents"],
            where={"object_status": "ACTIVE"},
        )

        # Build a structured list of dictionaries for Pandas
        data = []
        for obj in samples:
            name = obj.props["name"] if "name" in obj.props.all() else obj.code
            registrator = getattr(obj.registrator, "userId", obj.registrator)
            parents = obj.parents

            # If the user cannot see the parents, then the user does not have access to the history
            if parents:
                for parent in parents:
                    parent_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=parent
                    )
                    if parent_obj.type.code == OPENBIS_OBJECT_TYPES["Process Step"]:
                        break

                data.append(
                    {
                        "display_name": name,
                        "permId": obj.permId,  # Using permId as a proxy for registration date
                        "registrator": registrator,
                        "is_mine": registrator == self.current_user,
                    }
                )

        # Store as a master DataFrame
        self.raw_data_df = pd.DataFrame(data)

        # Trigger the initial population of the dropdown
        self.update_dropdown(None)

    def update_dropdown(self, change):
        """Filters and sorts the master DataFrame based on the current UI state."""
        if self.raw_data_df is None or self.raw_data_df.empty:
            return

        # 1. Start with a fresh copy of the raw data
        df = self.raw_data_df.copy()

        # 2. Apply Filters first
        if self.filter_my_samples_cb.value:
            df = df[df["is_mine"]]

        # 3. Apply Sorting
        sort_columns = []
        sort_ascending = []

        # Define how "user first" sorting works: True values (is_mine) come before False
        sort_columns.append("is_mine")
        sort_ascending.append(False)

        if self.sort_name_cb.value:
            sort_columns.append("display_name")
            sort_ascending.append(True)  # A-Z

        if self.sort_date_cb.value:
            sort_columns.append("permId")
            sort_ascending.append(False)  # Newest first (descending)
        elif not self.sort_name_cb.value and not self.sort_date_cb.value:
            # Default fallback sort if nothing is checked: just sort by newest
            sort_columns.append("permId")
            sort_ascending.append(False)

        # Execute the sort
        df = df.sort_values(by=sort_columns, ascending=sort_ascending)

        # 4. Format for the ipywidgets Dropdown
        # The dropdown requires a list of tuples: [("Display Text", "Value"), ...]
        options = list(
            df[["display_name", "permId"]].itertuples(index=False, name=None)
        )

        options.insert(0, ("Select sample...", "-1"))

        # 5. Update the widget
        self.sample_dropdown.options = options
        self.sample_dropdown.value = "-1"

    def show_edit_panel(self, b):
        sample_id = self.sample_dropdown.value

        # Block opening if no valid sample is chosen
        if sample_id == "-1":
            display(Javascript(data="alert('Please select a sample to edit first.')"))
            return

        # Disable the dropdown so user cannot switch selections during editing
        self.sample_dropdown.disabled = True

        # Grab current display name to pre-populate textbox
        current_label = [
            opt[0] for opt in self.sample_dropdown.options if opt[1] == sample_id
        ][0]
        self.edit_name_textbox.value = current_label

        # Render panel
        self.edit_sample_widgets.children = self.edit_panel_content

    def hide_edit_panel(self, b=None):
        # Re-enable dropdown
        self.sample_dropdown.disabled = False
        self.edit_sample_widgets.children = []
        self.edit_name_textbox.value = ""

    def save_sample_edit(self, b):
        sample_id = self.sample_dropdown.value
        new_name = self.edit_name_textbox.value.strip()

        if not new_name:
            display(Javascript(data="alert('Sample name cannot be empty.')"))
            return

        try:
            # Fetch object via openbis session
            sample_obj = self.openbis_session.get_sample(sample_id)
            sample_obj.props["name"] = new_name
            utils.update_openbis_object(sample_obj)

            # Post-save UI reset
            self.hide_edit_panel()
            self.load_samples()  # Refresh DataFrame & Repopulate dropdown
            self.sample_dropdown.value = (
                sample_id  # Set focus back onto the edited sample
            )
            display(Javascript(data="alert('Sample updated successfully!')"))

        except Exception as e:
            display(Javascript(data=f"alert('Error updating sample: {str(e)}')"))


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
            ],
            layout=ipw.Layout(align_items="center"),
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

        project_options.sort()
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
        self.select_results_selector = ipw.SelectMultiple(
            layout=ipw.Layout(width="500px", height="100px")
        )
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
        self.support_files_uploader = ipw.FileUpload(multiple=True)

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

    def reset_widgets(self):
        self.select_project_widget.project_dropdown.value = "-1"
        self.name_textbox.value = ""
        self.draft_type_dropdown.value = "Preprint"
        self.description_textbox.value = ""
        self.comments_textbox.value = ""
        self.support_files_uploader.value.clear()
        self.support_files_uploader._counter = 0

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

        self.select_software_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select software</span>"
        )

        self.select_software_label = ipw.Label(value="Software")
        openbis_software = utils.get_openbis_objects(
            self.openbis_session, type="SOFTWARE"
        )
        software_options = [
            (f"{obj.props['name']} - {obj.props['version']}", obj.permId)
            for obj in openbis_software
        ]
        self.select_software_selector = ipw.SelectMultiple(
            options=software_options, layout=ipw.Layout(width="500px", height="100px")
        )
        self.select_software_hbox = ipw.HBox(
            [self.select_software_label, self.select_software_selector]
        )

        self.select_code_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select code</span>"
        )

        self.select_code_label = ipw.Label(value="Code")
        openbis_code = utils.get_openbis_objects(self.openbis_session, type="CODE")
        code_options = [(f"{obj.props['name']}", obj.permId) for obj in openbis_code]
        self.select_code_selector = ipw.SelectMultiple(
            options=code_options, layout=ipw.Layout(width="500px", height="100px")
        )
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
        self.support_files_uploader = ipw.FileUpload(multiple=True)

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

    def reset_widgets(self):
        self.select_project_widget.project_dropdown.value = "-1"
        self.name_textbox.value = ""
        self.description_textbox.value = ""
        self.comments_textbox.value = ""
        self.select_code_selector.value = []
        self.select_software_selector.value = []
        self.support_files_uploader.value.clear()
        self.support_files_uploader._counter = 0

    def load_measurements_and_simulations(self, change):
        project_id = self.select_project_widget.project_dropdown.value
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
        self.amount_value_textbox = ipw.FloatText()
        self.amount_unit_dropdown = ipw.Dropdown(options=["g", "mg", "ug", "ml", "ul"])
        self.amount_hbox = ipw.HBox(
            [self.amount_label, self.amount_value_textbox, self.amount_unit_dropdown]
        )

        self.location_label = ipw.Label(value="Location")
        instruments_options = self.load_instruments(
            collection=OPENBIS_COLLECTIONS_PATHS["Instrument"]
        )
        rooms_options = self.load_rooms(project=locations_project)
        location_options = instruments_options + rooms_options
        location_options.insert(0, ("Select a location...", "-1"))
        self.location_dropdown = ipw.Dropdown(options=location_options)
        self.location_hbox = ipw.HBox([self.location_label, self.location_dropdown])

        self.storage_conditions_label = ipw.Label(value="Special storage conditions")
        self.storage_conditions_selector = ipw.SelectMultiple(
            options=[
                "Fridge",
                "Freezer",
                "Poisonous",
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
            description="Link molecule", button_style="success"
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
            groups = obj.props.get("groups") or []
            organisations = obj.props.get("organisations") or []

            if groups:
                groups_names_list = []
                for group in groups:
                    group_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=group
                    )
                    group_name = group_obj.props["name"]
                    groups_names_list.append(group_name)

                groups_names = ", ".join(groups_names_list)
                synthesiser_id = f"{obj_name} ({groups_names})"

            elif organisations:
                organisations_names_list = []
                for organisation in organisations:
                    organisation_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=organisation
                    )
                    organisation_name = organisation_obj.props["name"]
                    organisations_names_list.append(organisation_name)

                organisations_names = ", ".join(organisations_names_list)
                synthesiser_id = f"{obj_name} ({organisations_names})"

            else:
                synthesiser_id = obj_name

            synthesiser_details = (synthesiser_id, obj.permId)
            synthesisers_identifiers.append(synthesiser_details)

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

        # Get last empa number
        molecules_objects = utils.get_openbis_objects(
            self.openbis_session,
            type=OPENBIS_OBJECT_TYPES["Molecule"],
            props=["empa_number"],
        )
        last_empa_number = pd.to_numeric(molecules_objects.df.EMPA_NUMBER).max()
        empa_number_label = ipw.Label(value="Empa number")
        empa_number_textbox = ipw.IntText(value=last_empa_number + 1)
        empa_number_hbox = ipw.HBox(children=[empa_number_label, empa_number_textbox])

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
                "empa_number": empa_number_textbox.value,
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
            empa_number_hbox,
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
        self.amount_value_textbox.value = 0
        self.amount_unit_dropdown.value = "g"
        self.location_dropdown.value = "-1"
        self.package_opening_date.value = None
        self.supplier_dropdown.value = "-1"
        self.receive_date.value = None

        self.molecules_accordion.children = []
        self.molecules_accordion.titles = ()

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
