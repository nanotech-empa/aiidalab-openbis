import ipywidgets as ipw
from . import utils, widgets, aiida_utils
import subprocess
from aiida import orm
import shutil
import pandas as pd
import json
from IPython.display import display, Javascript
import io
import contextlib

string_io = io.StringIO()

MATERIALS_CONCEPTS_TYPES = utils.read_json("metadata/materials_concepts_types.json")
SIMULATION_TYPES = utils.read_json("metadata/simulation_types.json")
OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")
WORKCHAIN_VIEWERS = utils.read_json("metadata/workchain_viewers.json")


class ImportSimulationsWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_molecules_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select molecules</span>"
        )

        self.select_reacprod_concepts_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select reaction product concepts</span>"
        )

        self.select_slab_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select slab</span>"
        )

        self.search_simulations_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Search simulations</span>"
        )

        self.molecules_accordion = ipw.Accordion()
        self.add_molecule_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.reacprod_concepts_accordion = ipw.Accordion()
        self.add_reacprod_concept_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add reaction product concept",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.select_material_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select material</span>"
        )

        material_type_options = [
            (key, value) for key, value in MATERIALS_CONCEPTS_TYPES.items()
        ]
        material_type_options.insert(0, ("Select material type...", "-1"))

        self.material_type_dropdown = ipw.Dropdown(
            options=material_type_options, value=material_type_options[0][1]
        )

        self.material_details_vbox = ipw.VBox()

        self.search_logical_operator_label = ipw.Label(value="Search logical operator")
        self.search_logical_operator_dropdown = ipw.Dropdown(
            value="AND", options=["AND", "OR"], layout=ipw.Layout(width="150px")
        )
        self.search_button = ipw.Button(
            disabled=False,
            icon="search",
            tooltip="Search simulations in openBIS",
            layout=ipw.Layout(width="50px", height="25px"),
        )
        self.search_logical_operator_hbox = ipw.HBox(
            children=[
                self.search_logical_operator_label,
                self.search_logical_operator_dropdown,
                self.search_button,
            ]
        )

        self.found_simulations_label = ipw.Label(value="Found simulations")
        self.found_simulations_select_multiple = ipw.SelectMultiple(
            description="",
            disabled=False,
            layout=ipw.Layout(width="500px"),
            style={"description_width": "110px"},
        )
        self.found_simulations_hbox = ipw.HBox(
            children=[
                self.found_simulations_label,
                self.found_simulations_select_multiple,
            ]
        )

        self.import_simulations_button = ipw.Button(
            tooltip="Import simulations",
            icon="download",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.import_simulations_message_html = ipw.HTML()

        # Increase search button icon size
        increase_search_button = ipw.HTML(
            """<style>
            .fa-search {font-size: 1.5em !important;}
            .fa-download {font-size: 2em !important;}
            </style>
            """
        )

        # Add functionality to the widgets
        self.material_type_dropdown.observe(
            self.load_material_type_widgets, names="value"
        )
        self.add_molecule_button.on_click(self.add_molecule)
        self.add_reacprod_concept_button.on_click(self.add_reacprod_concept)
        self.search_button.on_click(self.search_simulations)
        self.import_simulations_button.on_click(self.import_aiida_nodes)

        self.children = [
            self.select_molecules_title,
            self.molecules_accordion,
            self.add_molecule_button,
            self.select_reacprod_concepts_title,
            self.reacprod_concepts_accordion,
            self.add_reacprod_concept_button,
            self.select_slab_title,
            self.material_type_dropdown,
            self.material_details_vbox,
            self.search_simulations_title,
            self.search_logical_operator_hbox,
            increase_search_button,
            self.found_simulations_hbox,
            self.import_simulations_button,
            self.import_simulations_message_html,
        ]

    def search_simulations(self, b):
        parents_permid_list = []
        for molecule_widget in self.molecules_accordion.children:
            molecule_permid = molecule_widget.dropdown.value
            if molecule_permid != "-1":
                parents_permid_list.append(molecule_permid)

        if self.material_type_dropdown.value != "-1":
            material_permid = self.material_details_vbox.children[0].children[0].value
            if material_permid != "-1":
                parents_permid_list.append(material_permid)

        for reacprod_concept_widget in self.reacprod_concepts_accordion.children:
            reacprod_concept_permid = reacprod_concept_widget.dropdown.value
            if reacprod_concept_permid != "-1":
                parents_permid_list.append(reacprod_concept_permid)

        simulation_permid_set = set()
        logical_operator = self.search_logical_operator_dropdown.value

        if (
            logical_operator == "OR"
        ):  # In OR, all the simulations found are added to the list
            for parent in parents_permid_list:
                parent_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )
                simulation_objects_children = utils.find_openbis_simulations(
                    self.openbis_session, parent_object, SIMULATION_TYPES
                )

                for simulation_object in simulation_objects_children:
                    simulation_permid = simulation_object.permId
                    simulation_permid_set.add(simulation_permid)

        else:  # In AND, only the simulations that appear in all selected materials are added to the list
            for idx, parent in enumerate(parents_permid_list):
                parent_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )
                simulation_objects_children = utils.find_openbis_simulations(
                    self.openbis_session, parent_object, SIMULATION_TYPES
                )

                parent_simulation_permid_list = []
                for simulation_object in simulation_objects_children:
                    simulation_permid = simulation_object.permId
                    parent_simulation_permid_list.append(simulation_permid)

                if idx == 0:
                    simulation_permid_set = set(parent_simulation_permid_list)
                else:
                    simulation_permid_set.intersection_update(
                        parent_simulation_permid_list
                    )

        simulation_permid_list = list(simulation_permid_set)
        aiida_node_permid_list = []
        for simulation_permid in simulation_permid_list:
            simulation_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=simulation_permid
            )
            simulation_aiida_node = simulation_object.props["aiida_node"]
            aiida_node_permid_list.append(simulation_aiida_node)

        simulation_aiida_node_list = []
        for idx, simulation_permid in enumerate(simulation_permid_list):
            simulation_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=simulation_permid
            )
            simulation_info = f"{simulation_object.props['name']} - {simulation_object.type.code} ({simulation_object.permId})"
            aiida_node_permid = aiida_node_permid_list[idx]
            simulation_aiida_node_list.append([simulation_info, aiida_node_permid])

        self.found_simulations_select_multiple.options = simulation_aiida_node_list

    def import_aiida_nodes(self, b):
        selected_simulations = self.found_simulations_select_multiple.value
        selected_labels = [
            label
            for label, value in self.found_simulations_select_multiple.options
            if value in selected_simulations
        ]

        selected_simulations_messages = ""
        for idx, aiida_node_permid in enumerate(selected_simulations):
            selected_label = selected_labels[idx]

            if aiida_node_permid:
                aiida_node_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=aiida_node_permid
                )
                object_datasets = aiida_node_object.get_datasets()

                for dataset in object_datasets:
                    dataset_filenames = dataset.file_list
                    is_aiida_file = False
                    if len(dataset_filenames) == 1:
                        for filename in dataset_filenames:
                            if ".aiida" in filename:
                                is_aiida_file = True

                    if is_aiida_file:
                        dataset.download(destination="aiida_nodes")
                        aiida_node_filename = dataset.file_list[0]
                        aiida_node_filepath = (
                            f"aiida_nodes/{dataset.permId}/{aiida_node_filename}"
                        )
                        command = ["verdi", "archive", "import", aiida_node_filepath]

                        # Execute the command
                        result = subprocess.run(command, capture_output=True, text=True)
                        if result.returncode != 0:
                            print(f"An error occurred: {result.stderr}")
                        else:
                            workchain = orm.load_node(
                                aiida_node_object.props["wfms_uuid"]
                            )
                            workchain_viewer_link = WORKCHAIN_VIEWERS[
                                workchain.process_label
                            ]
                            notebook_link = f"{workchain_viewer_link}?pk={workchain.pk}"

                            simulation_message = f'<a href="{notebook_link}">Workchain {selected_label} successfully imported.</a>\n'
                            selected_simulations_messages += simulation_message

                        shutil.rmtree(f"aiida_nodes/{dataset.permId}/")
            else:
                simulation_message = f"Workchain {selected_label} cannot be imported because it was done manually.\n"
                selected_simulations_messages += simulation_message

        self.import_simulations_message_html.value = selected_simulations_messages

    def load_material_type_widgets(self, change):
        if self.material_type_dropdown.value == "-1":
            self.material_details_vbox.children = []
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

            self.material_details_vbox.children = [
                select_material_box,
                material_details_html,
            ]

            material_type = self.material_type_dropdown.value
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
                            prop_datatype = prop_type.dataType
                            if prop_datatype == OPENBIS_OBJECT_TYPES["Sample"]:
                                if isinstance(value, list):
                                    prop_obj_names = []
                                    for id in value:
                                        prop_obj = utils.get_openbis_object(
                                            self.openbis_session, sample_ident=id
                                        )
                                        prop_obj_name = prop_obj.props["name"]
                                        prop_obj_names.append(prop_obj_name)
                                    value = ", ".join(prop_obj_names)
                                else:
                                    obj = utils.get_openbis_object(
                                        self.openbis_session, sample_ident=value
                                    )
                                    value = obj.props["name"]

                            elif prop_datatype == "JSON":
                                json_content = json.loads(value)
                                if utils.is_quantity_value(json_content):
                                    value = f"<p>{json_content['value']} {json_content['unit']}</p>"
                                else:
                                    value = "<ul>"
                                    for k, v in json_content.items():
                                        if isinstance(v, dict):
                                            if utils.is_quantity_value(v):
                                                value += f"<li><b>{k}:</b> {v['value']} {v['unit']}</li>"
                                            else:
                                                value += f"<li><b>{k}:</b> {v}</li>"
                                        else:
                                            value += f"<li><b>{k}:</b> {v}</li>"

                                    value += "</ul>"

                            elif (
                                prop_datatype == "XML"
                                and prop_type.metaData["custom_widget"] == "Spreadsheet"
                            ):
                                table_headers = value.headers
                                table_data = value.data

                                # Build table header
                                table_html = "<table style='width:100%; border-collapse:collapse;'>"
                                table_html += "<thead><tr>"
                                for h in table_headers:
                                    table_html += f"<th style='padding:0; text-align:left; font-weight:bold;'>{h}</th>"
                                table_html += "</tr></thead>"

                                # Build table body
                                table_html += "<tbody>"
                                for row in table_data:
                                    table_html += "<tr>"
                                    for cell in row:
                                        table_html += (
                                            f"<td style='padding:0;'>{cell}</td>"
                                        )
                                    table_html += "</tr>"
                                table_html += "</tbody></table>"
                                value = table_html

                            obj_details_string += f"<p><b>{prop_label}:</b> {value}</p>"

                    obj_details_string += "</div>"

                    material_details_html.value = obj_details_string

            name_checkbox.observe(sort_material_dropdown, names="value")
            registration_date_checkbox.observe(sort_material_dropdown, names="value")
            material_dropdown.observe(load_material_details, names="value")

    def add_molecule(self, b):
        molecules_accordion_children = list(self.molecules_accordion.children)
        molecule_index = len(molecules_accordion_children)
        molecule_widget = widgets.MoleculeWidget(
            self.openbis_session, self.molecules_accordion, molecule_index
        )
        molecules_accordion_children.append(molecule_widget)
        self.molecules_accordion.children = molecules_accordion_children

    def add_reacprod_concept(self, b):
        reacprod_concepts_accordion_children = list(
            self.reacprod_concepts_accordion.children
        )
        reacprod_concept_index = len(reacprod_concepts_accordion_children)
        reacprod_concept_widget = widgets.ReacProdConceptWidget(
            self.openbis_session,
            self.reacprod_concepts_accordion,
            reacprod_concept_index,
        )
        reacprod_concepts_accordion_children.append(reacprod_concept_widget)
        self.reacprod_concepts_accordion.children = reacprod_concepts_accordion_children


class ExportSimulationsWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_experiment_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select experiment</span>"
        )

        self.simulation_details_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Simulation details</span>"
        )

        self.select_experiment_widget = widgets.SelectExperimentWidget(
            self.openbis_session
        )

        self.used_aiida_checkbox = ipw.Checkbox(
            value=False, description="Simulation developed using AiiDA", indent=False
        )

        self.simulation_details_vbox = SimulationDetailsWidget(
            self.openbis_session, True
        )

        self.save_simulations_button = ipw.Button(
            tooltip="Import simulations",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        # Increase search button icon size
        increase_search_button = ipw.HTML(
            """<style>
            .fa-search {font-size: 1.5em !important;}
            .fa-download {font-size: 2em !important;}
            .fa-save {font-size: 2em !important;}
            </style>
            """
        )

        # Add functionality to the widgets
        self.used_aiida_checkbox.observe(
            self.load_simulations_details_widgets, names="value"
        )
        self.save_simulations_button.on_click(self.export_simulation_to_openbis)
        self.used_aiida_checkbox.value = True

        self.children = [
            self.select_experiment_title,
            self.select_experiment_widget,
            self.simulation_details_title,
            self.used_aiida_checkbox,
            self.simulation_details_vbox,
            increase_search_button,
            self.save_simulations_button,
        ]

    def load_simulations_details_widgets(self, change):
        used_aiida = self.used_aiida_checkbox.value
        self.simulation_details_vbox.load_widgets(used_aiida)

    def export_simulation_to_openbis(self, b):
        selected_experiment_id = self.select_experiment_widget.experiment_dropdown.value
        if selected_experiment_id == "-1":
            display(Javascript(data="alert('Select an experiment.')"))
        else:
            selected_molecules_widgets = (
                self.simulation_details_vbox.molecules_accordion.children
            )
            selected_reac_prods_widgets = (
                self.simulation_details_vbox.reacprod_concepts_accordion.children
            )

            # Get material
            if self.simulation_details_vbox.material_type_dropdown.value == "-1":
                selected_slab = []
            else:
                selected_material_id = (
                    self.simulation_details_vbox.material_details_vbox.children[0]
                    .children[0]
                    .value
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

            if self.used_aiida_checkbox.value:
                selected_simulation_id = (
                    self.simulation_details_vbox.simulations_dropdown.value
                )
                if selected_simulation_id == "-1":
                    display(Javascript(data="alert('Select a simulation.')"))
                else:
                    atom_model_parents = (
                        selected_slab + selected_molecules_ids + selected_reac_prods_ids
                    )
                    last_export = aiida_utils.export_workchain(
                        self.openbis_session,
                        selected_experiment_id,
                        selected_simulation_id,
                    )

                    if last_export:
                        if not isinstance(last_export, tuple):
                            last_export = (last_export,)

                        for export in last_export:
                            first_atom_model = utils.find_first_atomistic_model(
                                self.openbis_session,
                                export,
                                OPENBIS_OBJECT_TYPES["Atomistic Model"],
                            )

                            if len(first_atom_model.parents) == 0:
                                first_atom_model.parents = atom_model_parents
                                utils.update_openbis_object(first_atom_model)
                        display(Javascript(data="alert('Upload successful!')"))
                    else:
                        display(
                            Javascript(
                                data="alert('Simulation is already in openBIS!')"
                            )
                        )

            else:
                simulation_type = (
                    self.simulation_details_vbox.simulation_type_dropdown.value
                )
                if simulation_type == "-1":
                    return
                else:
                    # Get atomistic models
                    atom_model_widget = self.simulation_details_vbox.atom_model_widget
                    selected_atom_model_id = atom_model_widget.atom_model_dropdown.value
                    if selected_atom_model_id == "-1":
                        selected_atom_model_id = []
                    else:
                        selected_atom_model_id = [selected_atom_model_id]

                    selected_codes_ids = (
                        self.simulation_details_vbox.codes_multi_selector.value
                    )
                    selected_codes_ids = list(selected_codes_ids)

                    simulation_props_widget = (
                        self.simulation_details_vbox.simulation_properties_widget
                    )

                    level_theory_params = (
                        simulation_props_widget.level_theory_parameters_textbox.value
                    )
                    if not utils.is_valid_json(level_theory_params):
                        level_theory_params = ""

                    input_parameters = (
                        simulation_props_widget.method_input_parameters_textbox.value
                    )
                    if not utils.is_valid_json(input_parameters):
                        input_parameters = ""

                    output_parameters = (
                        simulation_props_widget.method_output_parameters_textbox.value
                    )
                    if not utils.is_valid_json(output_parameters):
                        output_parameters = ""

                    simulation_props = {
                        "name": simulation_props_widget.name_textbox.value,
                        "wfms_uuid": simulation_props_widget.wfms_uuid_textbox.value,
                        "input_parameters": input_parameters,
                        "output_parameters": output_parameters,
                        "comments": simulation_props_widget.comments_textbox.value,
                    }

                    simulation_types_with_level_theory = [
                        OPENBIS_OBJECT_TYPES["Band Structure"],
                        OPENBIS_OBJECT_TYPES["Geometry Optimisation"],
                        OPENBIS_OBJECT_TYPES["PDOS"],
                        OPENBIS_OBJECT_TYPES["Vibrational Spectroscopy"],
                    ]
                    if simulation_type in simulation_types_with_level_theory:
                        simulation_props["level_theory_method"] = (
                            simulation_props_widget.level_theory_method_textbox.value
                        )
                        simulation_props["level_theory_parameters"] = (
                            level_theory_params
                        )

                        if simulation_type == OPENBIS_OBJECT_TYPES["Band Structure"]:
                            band_gap = {
                                "value": simulation_props_widget.band_gap_value_textbox.value,
                                "unit": simulation_props_widget.band_gap_unit_textbox.value,
                            }
                            simulation_props["band_gap"] = band_gap

                        elif (
                            simulation_type
                            == OPENBIS_OBJECT_TYPES["Geometry Optimisation"]
                        ):
                            simulation_props["cell_opt_constraints"] = (
                                simulation_props_widget.cell_opt_constraints_textbox.value
                            )
                            simulation_props["cell_optimised"] = (
                                simulation_props_widget.cell_optimised_checkbox.value
                            )
                            simulation_props["driver_code"] = (
                                simulation_props_widget.driver_code_textbox.value
                            )
                            simulation_props["constrained"] = (
                                simulation_props_widget.constrained_checkbox.value
                            )

                            force_convergence_threshold = {
                                "value": simulation_props_widget.force_convergence_threshold_value_textbox.value,
                                "unit": simulation_props_widget.force_convergence_threshold_unit_textbox.value,
                            }
                            simulation_props["force_convergence_threshold"] = (
                                force_convergence_threshold
                            )

                    elif (
                        simulation_type
                        == OPENBIS_OBJECT_TYPES["Unclassified Simulation"]
                    ):
                        simulation_props["description"] = (
                            simulation_props_widget.description_textbox.value
                        )

                    simulation_props["codes"] = selected_codes_ids

                    simulation_parents = selected_atom_model_id

                    with contextlib.redirect_stdout(string_io):
                        simulation_obj = utils.create_openbis_object(
                            self.openbis_session,
                            type=simulation_type,
                            collection=selected_experiment_id,
                            parents=simulation_parents,
                            props=simulation_props,
                        )

                    # Simulation preview
                    with contextlib.redirect_stdout(string_io):
                        utils.upload_datasets(
                            self.openbis_session,
                            simulation_obj,
                            self.simulation_details_vbox.upload_image_preview_uploader,
                            "ELN_PREVIEW",
                        )

                    # Simulation datasets
                    with contextlib.redirect_stdout(string_io):
                        utils.upload_datasets(
                            self.openbis_session,
                            simulation_obj,
                            self.simulation_details_vbox.upload_datasets_uploader,
                            "ATTACHMENT",
                        )


class SimulationDetailsWidget(ipw.VBox):
    def __init__(self, openbis_session, used_aiida):
        super().__init__()
        self.openbis_session = openbis_session
        self.used_aiida = used_aiida

        self.select_molecules_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select molecules</span>"
        )

        self.select_reacprod_concepts_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select reaction product concepts</span>"
        )

        self.select_slab_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select slab</span>"
        )

        self.select_simulation_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select simulation</span>"
        )

        self.molecules_accordion = ipw.Accordion()
        self.add_molecule_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.reacprod_concepts_accordion = ipw.Accordion()
        self.add_reacprod_concept_button = ipw.Button(
            description="Add",
            disabled=False,
            button_style="success",
            tooltip="Add reaction product concept",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.select_material_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select material</span>"
        )

        material_type_options = [
            (key, value) for key, value in MATERIALS_CONCEPTS_TYPES.items()
        ]
        material_type_options.insert(0, ("Select material type...", "-1"))

        self.material_type_dropdown = ipw.Dropdown(
            options=material_type_options, value=material_type_options[0][1]
        )

        self.material_details_vbox = ipw.VBox()

        self.simulations_label = ipw.Label(value="Simulation")
        self.simulations_dropdown = ipw.Dropdown()
        self.load_aiida_simulations()
        self.sort_simulations_label = ipw.Label(value="Sort by:")

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_pk_label = ipw.Label(
            value="PK",
            layout=ipw.Layout(margin="2px", width="110px"),
            style={"description_width": "initial"},
        )

        self.sort_pk_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.sort_simulations_hbox = ipw.HBox(
            children=[
                self.sort_simulations_label,
                self.sort_name_checkbox,
                self.sort_name_label,
                self.sort_pk_checkbox,
                self.sort_pk_label,
            ]
        )

        self.simulations_dropdown_hbox = ipw.HBox(
            children=[
                self.simulations_label,
                self.simulations_dropdown,
            ]
        )

        self.select_simulation_type_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select simulation type</span>"
        )

        self.simulation_type_label = ipw.Label(value="Simulation type")
        simulation_types = [(key, value) for key, value in SIMULATION_TYPES.items()]
        simulation_types.insert(0, ("Select simulation type...", "-1"))

        self.simulation_type_dropdown = ipw.Dropdown(
            options=simulation_types, value="-1"
        )

        self.simulation_type_hbox = ipw.HBox(
            children=[
                self.simulation_type_label,
                self.simulation_type_dropdown,
            ]
        )

        self.simulation_properties_widget = SimulationPropertiesWidget(
            self.openbis_session
        )

        self.select_atom_model_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select atomistic model</span>"
        )
        self.atom_model_widget = widgets.AtomModelWidget(self.openbis_session)

        self.select_codes_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select codes</span>"
        )

        self.codes_label = ipw.Label(value="Codes")
        codes_objects = utils.get_openbis_objects(
            self.openbis_session, type=OPENBIS_OBJECT_TYPES["Code"]
        )
        codes_options = [(obj.props["name"], obj.permId) for obj in codes_objects]
        self.codes_multi_selector = ipw.SelectMultiple(options=codes_options)
        self.codes_hbox = ipw.HBox(
            children=[self.codes_label, self.codes_multi_selector]
        )

        self.upload_image_preview_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Upload image preview</span>"
        )

        self.upload_image_preview_uploader = ipw.FileUpload(
            multiple=False, accept=".jpg, .jpeg, .png,"
        )

        self.upload_datasets_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Upload datasets</span>"
        )

        self.upload_datasets_uploader = ipw.FileUpload(multiple=True)

        self.simulation_type_dropdown.observe(
            self.load_simulation_type_properties, names="value"
        )
        self.material_type_dropdown.observe(
            self.load_material_type_widgets, names="value"
        )
        self.add_molecule_button.on_click(self.add_molecule)
        self.add_reacprod_concept_button.on_click(self.add_reacprod_concept)

    def load_simulation_type_properties(self, change):
        simulation_type = self.simulation_type_dropdown.value
        self.simulation_properties_widget.load_widgets(simulation_type)

    def load_aiida_simulations(self):
        qb = orm.QueryBuilder()
        qb.append(orm.WorkChainNode)
        results = qb.all()

        # List of calculations that can be exported
        labels = list(WORKCHAIN_VIEWERS.keys())

        # Create the QueryBuilder
        qb = orm.QueryBuilder()
        qb.append(
            orm.WorkChainNode,
            filters={
                "attributes.process_label": {"in": labels},  # Filter by process_label
                "extras": {
                    "!has_key": "exported"
                },  # Exclude nodes with the 'exported' key in extras
                "attributes.process_state": {"in": ["finished"]},
            },
            project=[
                "id",
                "uuid",
                "attributes.process_label",
                "attributes.metadata_inputs.metadata.description",
                "attributes.metadata_inputs.metadata.label",
            ],  # Project the PK (id) and process_label
        )
        # Execute the query
        results = qb.all()
        options = []
        for result in results:
            if result[3]:
                name_pk_string = f"{result[3][:20]} - {result[2]} (PK: {result[0]})"
            else:
                name_pk_string = f"{result[2]} (PK: {result[0]})"

            name_pk_tuple = (name_pk_string, result[0])
            options.append(name_pk_tuple)

        options.insert(0, ("Select a simulation...", "-1"))
        self.simulations_dropdown.options = options
        self.simulations_dropdown.value = "-1"

    def sort_simulations_dropdown(self, change):
        options = self.simulations_dropdown.options[1:]

        df = pd.DataFrame(options, columns=["name", "PK"])
        if self.sort_name_checkbox.value and not self.sort_pk_checkbox.value:
            df = df.sort_values(by="name", ascending=True)
        elif not self.sort_name_checkbox.value and self.sort_pk_checkbox.value:
            df = df.sort_values(by="PK", ascending=False)
        elif self.sort_name_checkbox.value and self.sort_pk_checkbox.value:
            df = df.sort_values(by=["name", "PK"], ascending=[True, False])

        options = list(df.itertuples(index=False, name=None))
        options.insert(0, self.simulations_dropdown.options[0])
        self.simulations_dropdown.options = options

    def load_widgets(self, used_aiida):
        self.used_aiida = used_aiida
        if self.used_aiida:
            self.children = [
                self.select_molecules_title,
                self.molecules_accordion,
                self.add_molecule_button,
                self.select_reacprod_concepts_title,
                self.reacprod_concepts_accordion,
                self.add_reacprod_concept_button,
                self.select_material_title,
                self.material_type_dropdown,
                self.material_details_vbox,
                self.select_simulation_title,
                self.simulations_dropdown_hbox,
                self.sort_simulations_hbox,
            ]

        else:
            self.children = [
                self.select_simulation_type_title,
                self.simulation_type_hbox,
                self.simulation_properties_widget,
                self.select_atom_model_title,
                self.atom_model_widget,
                self.select_codes_title,
                self.codes_hbox,
                self.upload_image_preview_title,
                self.upload_image_preview_uploader,
                self.upload_datasets_title,
                self.upload_datasets_uploader,
            ]

    def load_material_type_widgets(self, change):
        if self.material_type_dropdown.value == "-1":
            self.material_details_vbox.children = []
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

            self.material_details_vbox.children = [
                select_material_box,
                material_details_html,
            ]

            material_type = self.material_type_dropdown.value
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
                            obj_details_string += f"<p><b>{prop_label}:</b> {value}</p>"

                    obj_details_string += "</div>"

                    material_details_html.value = obj_details_string

            name_checkbox.observe(sort_material_dropdown, names="value")
            registration_date_checkbox.observe(sort_material_dropdown, names="value")
            material_dropdown.observe(load_material_details, names="value")

    def add_molecule(self, b):
        molecules_accordion_children = list(self.molecules_accordion.children)
        molecule_index = len(molecules_accordion_children)
        molecule_widget = widgets.MoleculeWidget(
            self.openbis_session, self.molecules_accordion, molecule_index
        )
        molecules_accordion_children.append(molecule_widget)
        self.molecules_accordion.children = molecules_accordion_children

    def add_reacprod_concept(self, b):
        reacprod_concepts_accordion_children = list(
            self.reacprod_concepts_accordion.children
        )
        reacprod_concept_index = len(reacprod_concepts_accordion_children)
        reacprod_concept_widget = widgets.ReacProdConceptWidget(
            self.openbis_session,
            self.reacprod_concepts_accordion,
            reacprod_concept_index,
        )
        reacprod_concepts_accordion_children.append(reacprod_concept_widget)
        self.reacprod_concepts_accordion.children = reacprod_concepts_accordion_children


class SimulationPropertiesWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session
        self.simulation_type = ""

        self.simulation_properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Simulation properties</span>"
        )

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Textarea()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_textbox]
        )

        self.wfms_uuid_label = ipw.Label(value="WFMS UUID")
        self.wfms_uuid_textbox = ipw.Text()
        self.wfms_uuid_hbox = ipw.HBox(
            children=[self.wfms_uuid_label, self.wfms_uuid_textbox]
        )

        self.band_gap_label = ipw.Label(value="Band gap:")
        self.band_gap_value_textbox = ipw.Text()
        self.band_gap_unit_textbox = ipw.Dropdown(options=["eV", "J", "Ha"], value="Ha")
        self.band_gap_hbox = ipw.HBox(
            children=[
                self.band_gap_label,
                self.band_gap_value_textbox,
                self.band_gap_unit_textbox,
            ]
        )

        self.cell_opt_constraints_label = ipw.Label(value="Cell opt constraints")
        self.cell_opt_constraints_textbox = ipw.Text()
        self.cell_opt_constraints_hbox = ipw.HBox(
            children=[
                self.cell_opt_constraints_label,
                self.cell_opt_constraints_textbox,
            ]
        )

        self.cell_optimised_label = ipw.Label(value="Cell optimised")
        self.cell_optimised_checkbox = ipw.Checkbox(indent=False)
        self.cell_optimised_hbox = ipw.HBox(
            children=[self.cell_optimised_label, self.cell_optimised_checkbox]
        )

        self.driver_code_label = ipw.Label(value="Driver code")
        self.driver_code_textbox = ipw.Text()
        self.driver_code_hbox = ipw.HBox(
            children=[self.driver_code_label, self.driver_code_textbox]
        )

        self.constrained_label = ipw.Label(value="Constrained")
        self.constrained_checkbox = ipw.Checkbox(indent=False)
        self.constrained_hbox = ipw.HBox(
            children=[self.constrained_label, self.constrained_checkbox]
        )

        self.force_convergence_threshold_label = ipw.Label(
            value="Force convergence threshold: "
        )
        self.force_convergence_threshold_value_label = ipw.Label(value="Value")
        self.force_convergence_threshold_value_textbox = ipw.Text(
            layout=ipw.Layout(width="100px")
        )
        self.force_convergence_threshold_unit_label = ipw.Label(value="Unit")
        self.force_convergence_threshold_unit_textbox = ipw.Text(
            layout=ipw.Layout(width="100px")
        )
        self.force_convergence_threshold_hbox = ipw.HBox(
            children=[
                self.force_convergence_threshold_label,
                self.force_convergence_threshold_value_label,
                self.force_convergence_threshold_value_textbox,
                self.force_convergence_threshold_unit_label,
                self.force_convergence_threshold_unit_textbox,
            ]
        )

        self.level_theory_method_label = ipw.Label(value="Level of theory (method)")
        self.level_theory_method_textbox = ipw.Text()
        self.level_theory_method_hbox = ipw.HBox(
            children=[self.level_theory_method_label, self.level_theory_method_textbox]
        )

        self.level_theory_parameters_label = ipw.Label(
            value="Level of theory (parameters)"
        )
        self.level_theory_parameters_textbox = ipw.Textarea(
            placeholder='{"uks": false, "charge": 0.0, "plus_u": false, "xc_functional": "PBESOL"}'
        )
        self.level_theory_parameters_hbox = ipw.HBox(
            children=[
                self.level_theory_parameters_label,
                self.level_theory_parameters_textbox,
            ]
        )

        self.method_input_parameters_label = ipw.Label(value="Method input parameters")
        self.method_input_parameters_textbox = ipw.Textarea(
            placeholder='{"degauss": 0.0, "volume": 0.0}'
        )
        self.method_input_parameters_hbox = ipw.HBox(
            children=[
                self.method_input_parameters_label,
                self.method_input_parameters_textbox,
            ]
        )

        self.method_output_parameters_label = ipw.Label(
            value="Method output parameters"
        )
        self.method_output_parameters_textbox = ipw.Textarea(
            placeholder='{"energy": 0.0, "has_electric_field": false}'
        )
        self.method_output_parameters_hbox = ipw.HBox(
            children=[
                self.method_output_parameters_label,
                self.method_output_parameters_textbox,
            ]
        )

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textbox = ipw.Textarea()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_textbox]
        )

    def load_widgets(self, simulation_type):
        self.simulation_type = simulation_type

        if simulation_type == OPENBIS_OBJECT_TYPES["Band Structure"]:
            self.children = [
                self.simulation_properties_title,
                self.name_hbox,
                self.wfms_uuid_hbox,
                self.band_gap_hbox,
                self.level_theory_method_hbox,
                self.level_theory_parameters_hbox,
                self.method_input_parameters_hbox,
                self.method_output_parameters_hbox,
                self.comments_hbox,
            ]

        elif simulation_type == OPENBIS_OBJECT_TYPES["Geometry Optimisation"]:
            self.children = [
                self.simulation_properties_title,
                self.name_hbox,
                self.wfms_uuid_hbox,
                self.cell_opt_constraints_hbox,
                self.cell_optimised_hbox,
                self.driver_code_hbox,
                self.constrained_hbox,
                self.force_convergence_threshold_hbox,
                self.level_theory_method_hbox,
                self.level_theory_parameters_hbox,
                self.method_input_parameters_hbox,
                self.method_output_parameters_hbox,
                self.comments_hbox,
            ]

        elif simulation_type == OPENBIS_OBJECT_TYPES["PDOS"]:
            self.children = [
                self.simulation_properties_title,
                self.name_hbox,
                self.wfms_uuid_hbox,
                self.level_theory_method_hbox,
                self.level_theory_parameters_hbox,
                self.method_input_parameters_hbox,
                self.method_output_parameters_hbox,
                self.comments_hbox,
            ]

        elif simulation_type == OPENBIS_OBJECT_TYPES["Vibrational Spectroscopy"]:
            self.children = [
                self.simulation_properties_title,
                self.name_hbox,
                self.wfms_uuid_hbox,
                self.level_theory_method_hbox,
                self.level_theory_parameters_hbox,
                self.method_input_parameters_hbox,
                self.method_output_parameters_hbox,
                self.comments_hbox,
            ]

        elif simulation_type == OPENBIS_OBJECT_TYPES["Unclassified Simulation"]:
            self.children = [
                self.simulation_properties_title,
                self.name_hbox,
                self.description_hbox,
                self.method_input_parameters_hbox,
                self.method_output_parameters_hbox,
                self.comments_hbox,
            ]
