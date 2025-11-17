import ipywidgets as ipw
from . import utils, widgets
import pandas as pd
import json
from IPython.display import display, Javascript
from collections import Counter
import shutil
import base64
import io
import os
import matplotlib.pyplot as plt
import logging

OBSERVABLES_TYPES = utils.read_json("metadata/observables_types.json")
ACTIONS_TYPES = utils.read_json("metadata/actions_types.json")
ACTIONS_CODES = utils.read_json("metadata/actions_codes.json")
OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")
MATERIALS_TYPES = utils.read_json("metadata/materials_types.json")
OPENBIS_OBJECT_CODES = utils.read_json("metadata/object_codes.json")
OPENBIS_COLLECTIONS_PATHS = utils.read_json("metadata/collection_paths.json")

processes_project = "/LAB205_METHODS/PROCESSES"

if not os.path.exists("logs"):
    os.mkdir("logs")

logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class CreateSampleWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_material_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select material</span>"
        )

        material_type_options = [(key, value) for key, value in MATERIALS_TYPES.items()]
        material_type_options.insert(0, ("Select material type...", "-1"))

        self.material_type_dropdown = ipw.Dropdown(
            options=material_type_options, value=material_type_options[0][1]
        )

        self.material_details_vbox = ipw.VBox()

        self.sample_name_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Sample name</span>"
        )

        self.sample_name_textbox = ipw.Text(placeholder="Write sample name...")

        self.save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.children = [
            self.select_material_title,
            self.material_type_dropdown,
            self.material_details_vbox,
            self.sample_name_title,
            self.sample_name_textbox,
            self.save_button,
        ]

        self.material_type_dropdown.observe(
            self.load_material_type_widgets, names="value"
        )

        self.save_button.on_click(self.save_sample)

    def load_material_type_widgets(self, change):
        if self.material_type_dropdown.value == "-1":
            self.material_details_vbox.children = []
            logger.info("Material type is not selected.")
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
                    logger.info("Material is not selected.")
                    return
                else:
                    obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=obj_permid
                    )
                    obj_props = obj.props.all()
                    obj_name = obj_props.get("name", "") or ""
                    obj_details_string = "<div style='border: 1px solid grey; padding: 10px; margin: 10px;'>"
                    for key, value in obj_props.items():
                        if value:
                            prop_type = utils.get_openbis_property_type(
                                self.openbis_session, code=key
                            )
                            prop_label = prop_type.label
                            prop_datatype = prop_type.dataType
                            if prop_datatype == "SAMPLE":
                                if isinstance(value, list):
                                    prop_obj_names = []
                                    for id in value:
                                        prop_obj = utils.get_openbis_object(
                                            self.openbis_session, sample_ident=id
                                        )
                                        prop_obj_name = prop_obj.props["name"] or ""
                                        prop_obj_names.append(prop_obj_name)
                                    value = ", ".join(prop_obj_names)
                                else:
                                    obj = utils.get_openbis_object(
                                        self.openbis_session, sample_ident=value
                                    )
                                    value = obj.props["name"] or ""

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
                        else:
                            logger.info(f"{key} has no value.")

                    obj_details_string += "</div>"

                    material_details_html.value = obj_details_string

                    current_datetime = utils.get_current_datetime()
                    current_datetime_str = utils.convert_datetime_to_string(
                        current_datetime
                    )
                    self.sample_name_textbox.value = (
                        f"{current_datetime_str}_{obj_name}"
                    )

            name_checkbox.observe(sort_material_dropdown, names="value")
            registration_date_checkbox.observe(sort_material_dropdown, names="value")
            material_dropdown.observe(load_material_details, names="value")

    def save_sample(self, b):
        if self.material_type_dropdown.value == "-1":
            logger.info("Material type is not selected.")
            return
        else:
            if self.material_details_vbox.children[0].children[0].value == "-1":
                logger.info("Material is not selected.")
                return
            else:
                material_id = self.material_details_vbox.children[0].children[0].value

                material_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=material_id
                )

                # Check samples that use this material which are still active
                sample_objects = utils.get_openbis_objects(
                    self.openbis_session,
                    type=OPENBIS_OBJECT_TYPES["Sample"],
                    where={"object_status": "ACTIVE"},
                    attrs=["parents"],
                )

                for sample in sample_objects:
                    obj = sample
                    while obj:
                        parents = obj.parents
                        found_parent = False

                        for parent_id in parents:
                            parent = utils.get_openbis_object(
                                self.openbis_session, sample_ident=parent_id
                            )
                            parent_type = parent.type.code

                            if parent_type in [
                                OPENBIS_OBJECT_TYPES["Process Step"],
                                OPENBIS_OBJECT_TYPES["Sample"],
                            ]:
                                obj = parent
                                found_parent = True
                                break

                            elif (
                                parent_type == material_object.type.code
                                and parent.permId == material_object.permId
                            ):
                                sample.props["object_status"] = "DISPOSED"
                                utils.update_openbis_object(sample)
                                found_parent = True
                                break

                        if not found_parent:
                            obj = None

                        if sample.props["object_status"] == "DISPOSED":
                            break

                sample_name = self.sample_name_textbox.value
                sample_type = OPENBIS_OBJECT_TYPES["Sample"]
                sample_props = {"name": sample_name, "object_status": "ACTIVE"}
                sample_object = utils.create_openbis_object(
                    self.openbis_session,
                    type=sample_type,
                    collection=OPENBIS_COLLECTIONS_PATHS["Sample"],
                    props=sample_props,
                    parents=[material_object],
                )

                display(Javascript(data="alert('Sample created successfully!')"))

                logger.info(f"Sample {sample_object.permId} created successfully!")

                # Clear interface
                self.material_type_dropdown.value = "-1"
                self.sample_name_textbox.value = ""


class SampleHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session
        self.sample_history_objects = {}
        self.sample_history = ipw.Accordion()

        self.children = [self.sample_history]

    def load_sample_history(self, sample_object):
        process_steps = []
        sample_parents = sample_object.parents

        while sample_parents:
            next_parents = []
            for parent in sample_parents:
                parent_code = parent.split("/")[-1]
                if (
                    OPENBIS_OBJECT_CODES["Process Step"] == parent_code[0:4]
                    or OPENBIS_OBJECT_CODES["Sample"] == parent_code[0:4]
                ):
                    parent_object = utils.get_openbis_object(
                        self.openbis_session, sample_ident=parent
                    )
                    next_parents.extend(parent_object.parents)

                    if OPENBIS_OBJECT_CODES["Process Step"] == parent_code[0:4]:
                        process_steps.append(parent_object)
            sample_parents = next_parents
        sample_history_children = []
        for i, process_step in enumerate(process_steps):
            process_step_widget = ProcessStepHistoryWidget(
                self.openbis_session, process_step
            )
            sample_history_children.append(process_step_widget)
            process_step_title = (
                process_step_widget.name_html.value
                + " ("
                + process_step_widget.registration_date
                + ")"
            )
            self.sample_history.set_title(i, process_step_title)

        self.sample_history.children = sample_history_children
        logger.info("Sample history loaded successfully.")


class ProcessStepHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session, openbis_object):
        super().__init__()
        self.openbis_session = openbis_session
        self.openbis_object = openbis_object
        self.registration_date = None
        self.process_step_type = OPENBIS_OBJECT_TYPES["Process Step"]
        self.process_step_type_lower = self.process_step_type.lower()

        self.name_label = ipw.Label(value="Name:")
        self.name_html = ipw.HTML()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_html])

        self.description_label = ipw.Label(value="Description:")
        self.description_html = ipw.HTML()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_html]
        )

        self.comments_label = ipw.Label(value="Comments:")
        self.comments_html = ipw.HTML()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_html]
        )

        self.instrument_label = ipw.Label(value="Instrument:")
        self.instrument_html = ipw.HTML()
        self.instrument_hbox = ipw.HBox(
            children=[self.instrument_label, self.instrument_html]
        )

        self.actions_label = ipw.Label(value="Actions:")
        self.actions_accordion = ipw.Accordion()
        self.actions_vbox = ipw.VBox(
            children=[self.actions_label, self.actions_accordion]
        )

        self.observables_label = ipw.Label(value="Observables:")
        self.observables_accordion = ipw.Accordion()
        self.observables_vbox = ipw.VBox(
            children=[self.observables_label, self.observables_accordion]
        )

        self.load_process_step_data()

        self.children = [
            self.name_hbox,
            self.description_hbox,
            self.comments_hbox,
            self.instrument_hbox,
            self.actions_vbox,
            self.observables_vbox,
        ]

    def load_process_step_data(self):
        openbis_object_props = self.openbis_object.props.all()
        if openbis_object_props["name"]:
            self.name_html.value = openbis_object_props["name"]

        if openbis_object_props["description"]:
            self.description_html.value = openbis_object_props["description"]

        if openbis_object_props["comments"]:
            self.comments_html.value = openbis_object_props["comments"]

        self.registration_date = self.openbis_object.registrationDate

        if openbis_object_props["instrument"]:
            instrument_id = openbis_object_props["instrument"]

            instrument_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=instrument_id
            )

            self.instrument_html.value = instrument_object.props["name"]

        self.load_actions()
        self.load_observables()

    def load_actions(self):
        actions_ids = self.openbis_object.props["actions"]
        if actions_ids:
            actions_accordion_children = []
            for i, act_id in enumerate(actions_ids):
                act_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=act_id
                )
                act_widget = ActionHistoryWidget(self.openbis_session, act_object)
                actions_accordion_children.append(act_widget)
                act_title = act_widget.name_html.value
                self.actions_accordion.set_title(i, act_title)

            self.actions_accordion.children = actions_accordion_children

    def load_observables(self):
        observables_ids = self.openbis_object.props["observables"]
        if observables_ids:
            observables_accordion_children = []
            for i, obs_id in enumerate(observables_ids):
                obs_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=obs_id
                )
                obs_widget = ObservableHistoryWidget(self.openbis_session, obs_object)
                observables_accordion_children.append(obs_widget)
                obs_title = obs_widget.name_html.value
                self.observables_accordion.set_title(i, obs_title)

            self.observables_accordion.children = observables_accordion_children


class ActionHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session, openbis_object):
        super().__init__()
        self.openbis_session = openbis_session
        self.openbis_object = openbis_object
        self.object_type = self.openbis_object.type.code
        self.object_type_lower = self.object_type.lower()

        self.name_label = ipw.Label(value="Name:")
        self.name_html = ipw.HTML()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_html])

        self.duration_label = ipw.Label(value="Duration:")
        self.duration_html = ipw.HTML()
        self.duration_hbox = ipw.HBox(
            children=[self.duration_label, self.duration_html]
        )

        self.description_label = ipw.Label(value="Description:")
        self.description_html = ipw.HTML()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_html]
        )

        self.component_label = ipw.Label(value="Component:")
        self.component_html = ipw.HTML()
        self.component_hbox = ipw.HBox(
            children=[self.component_label, self.component_html]
        )

        self.component_settings_label = ipw.Label(value="Component settings:")
        self.component_settings_html = ipw.HTML()
        self.component_settings_hbox = ipw.HBox(
            children=[self.component_settings_label, self.component_settings_html]
        )

        self.comments_label = ipw.Label(value="Comments:")
        self.comments_html = ipw.HTML()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_html]
        )

        widget_children = [self.name_hbox, self.description_hbox, self.duration_hbox]

        if self.object_type == OPENBIS_OBJECT_TYPES["Annealing"]:
            self.target_temperature_label = ipw.Label(value="Target temperature:")
            self.target_temperature_html = ipw.HTML()
            self.target_temperature_hbox = ipw.HBox(
                children=[self.target_temperature_label, self.target_temperature_html]
            )
            widget_children.append(self.target_temperature_hbox)

        elif self.object_type == OPENBIS_OBJECT_TYPES["Cooldown"]:
            self.target_temperature_label = ipw.Label(value="Target temperature:")
            self.target_temperature_html = ipw.HTML()
            self.target_temperature_hbox = ipw.HBox(
                children=[self.target_temperature_label, self.target_temperature_html]
            )

            self.cryogen_label = ipw.Label(value="Cryogen:")
            self.cryogen_html = ipw.HTML()
            self.cryogen_hbox = ipw.HBox(
                children=[self.cryogen_label, self.cryogen_html]
            )

            widget_children.append(self.cryogen_hbox)
            widget_children.append(self.target_temperature_hbox)

        elif self.object_type == OPENBIS_OBJECT_TYPES["Deposition"]:
            self.substrate_temperature_label = ipw.Label(value="Substrate temperature:")
            self.substrate_temperature_html = ipw.HTML()
            self.substrate_temperature_hbox = ipw.HBox(
                children=[
                    self.substrate_temperature_label,
                    self.substrate_temperature_html,
                ]
            )

            self.substance_label = ipw.Label(value="Substance:")
            self.substance_html = ipw.HTML()
            self.substance_hbox = ipw.HBox(
                children=[self.substance_label, self.substance_html]
            )

            widget_children.append(self.substance_hbox)
            widget_children.append(self.substrate_temperature_hbox)

        elif self.object_type == OPENBIS_OBJECT_TYPES["Dosing"]:
            self.substrate_temperature_label = ipw.Label(value="Substrate temperature:")
            self.substrate_temperature_html = ipw.HTML()
            self.substrate_temperature_hbox = ipw.HBox(
                children=[
                    self.substrate_temperature_label,
                    self.substrate_temperature_html,
                ]
            )

            self.pressure_label = ipw.Label(value="Pressure:")
            self.pressure_html = ipw.HTML()
            self.pressure_hbox = ipw.HBox(
                children=[self.pressure_label, self.pressure_html]
            )

            self.dosing_gas_label = ipw.Label(value="Dosing gas:")
            self.dosing_gas_html = ipw.HTML()
            self.dosing_gas_hbox = ipw.HBox(
                children=[self.dosing_gas_label, self.dosing_gas_html]
            )

            widget_children.append(self.dosing_gas_hbox)
            widget_children.append(self.pressure_hbox)
            widget_children.append(self.substrate_temperature_hbox)

        elif self.object_type == OPENBIS_OBJECT_TYPES["Sputtering"]:
            self.sputter_ion_label = ipw.Label(value="Sputter ion:")
            self.sputter_ion_html = ipw.HTML()
            self.sputter_ion_hbox = ipw.HBox(
                children=[self.sputter_ion_label, self.sputter_ion_html]
            )

            self.pressure_label = ipw.Label(value="Pressure:")
            self.pressure_html = ipw.HTML()
            self.pressure_hbox = ipw.HBox(
                children=[self.pressure_label, self.pressure_html]
            )

            self.current_label = ipw.Label(value="Current:")
            self.current_html = ipw.HTML()
            self.current_hbox = ipw.HBox(
                children=[self.current_label, self.current_html]
            )

            self.angle_label = ipw.Label(value="Angle:")
            self.angle_html = ipw.HTML()
            self.angle_hbox = ipw.HBox(children=[self.angle_label, self.angle_html])

            self.substrate_temperature_label = ipw.Label(value="Substrate temperature:")
            self.substrate_temperature_html = ipw.HTML()
            self.substrate_temperature_hbox = ipw.HBox(
                children=[
                    self.substrate_temperature_label,
                    self.substrate_temperature_html,
                ]
            )

            widget_children.append(self.sputter_ion_hbox)
            widget_children.append(self.pressure_hbox)
            widget_children.append(self.current_hbox)
            widget_children.append(self.angle_hbox)
            widget_children.append(self.substrate_temperature_hbox)

        widget_children.append(self.comments_hbox)
        widget_children.append(self.component_hbox)
        widget_children.append(self.component_settings_hbox)

        self.load_action_data()
        self.children = widget_children

    def load_action_data(self):
        openbis_object_props = self.openbis_object.props.all()
        if openbis_object_props["name"]:
            self.name_html.value = openbis_object_props["name"]

        if openbis_object_props["description"]:
            self.description_html.value = openbis_object_props["description"]

        if openbis_object_props["duration"]:
            self.duration_html.value = openbis_object_props["duration"]

        if openbis_object_props["comments"]:
            self.comments_html.value = openbis_object_props["comments"]

        if "target_temperature" in openbis_object_props:
            target_temperature = openbis_object_props["target_temperature"]
            if target_temperature:
                self.target_temperature_html.value = utils.stringify_quantity_value(
                    target_temperature, "unit"
                )

        if "cryogen" in openbis_object_props:
            if openbis_object_props["cryogen"]:
                self.cryogen_html.value = openbis_object_props["cryogen"]

        if "substrate_temperature" in openbis_object_props:
            substrate_temperature = openbis_object_props["substrate_temperature"]
            if substrate_temperature:
                self.substrate_temperature_html.value = utils.stringify_quantity_value(
                    substrate_temperature, "unit"
                )

        if "dosing_gas" in openbis_object_props:
            if openbis_object_props["gas"]:
                self.dosing_gas_html.value = openbis_object_props["gas"]

        if "pressure" in openbis_object_props:
            pressure = openbis_object_props["pressure"]
            if pressure:
                self.pressure_html.value = utils.stringify_quantity_value(
                    pressure, "unit"
                )

        if "current" in openbis_object_props:
            current = openbis_object_props["current"]
            if current:
                self.current_html.value = utils.stringify_quantity_value(
                    current, "unit"
                )

        if "angle" in openbis_object_props:
            angle = openbis_object_props["angle"]
            if angle:
                self.angle_html.value = utils.stringify_quantity_value(angle, "unit")

        if "substance" in openbis_object_props:
            substance_id = openbis_object_props["substance"]
            if substance_id:
                substance_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=substance_id
                )
                substance_empa_number = substance_object.props["empa_number"]
                substance_batch = substance_object.props["batch"]
                substance_vial = substance_object.props["vial"]
                self.substance_html.value = (
                    "Identifier: " + substance_empa_number + substance_batch
                )
                if substance_vial:
                    self.substance_html.value += f"-{substance_vial}"

                substance_mols_ids = substance_object.props["molecules"]
                if substance_mols_ids:
                    mol_id = substance_mols_ids[0]
                    molecule_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=mol_id
                    )
                    molecule_obj_datasets = molecule_obj.get_datasets(
                        type="ELN_PREVIEW"
                    )
                    molecule_obj_preview = molecule_obj_datasets[0]
                    molecule_obj_preview.download(destination="images")
                    object_image_filepath = molecule_obj_preview.file_list[0]
                    html_image = utils.read_file(
                        f"images/{molecule_obj_preview.permId}/{object_image_filepath}"
                    )
                    image_encoded = base64.b64encode(html_image).decode("utf-8")
                    self.substance_html.value += f""" Molecule sketch: <img src="data:image/png;base64,{image_encoded}" width="100">"""

                    # Erase file after downloading it
                    shutil.rmtree(f"images/{molecule_obj_preview.permId}")

        component_id = openbis_object_props["component"]
        if component_id:
            component_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=component_id
            )
            self.component_html.value = component_object.props["name"]

        if openbis_object_props["component_settings"]:
            component_settings = json.loads(openbis_object_props["component_settings"])
            component_settings_string = ""
            for prop_key, prop_value in component_settings.items():
                prop_type = utils.get_openbis_property_type(
                    self.openbis_session, code=prop_key
                )
                prop_label = prop_type.label

                # Convert quantity values from json objects to strings
                if prop_value and isinstance(prop_value, dict):
                    unit_type = ""
                    for key in prop_value.keys():
                        if key == "unit":
                            unit_type = key
                            break
                    prop_value = utils.stringify_quantity_value(prop_value, unit_type)

                component_settings_string += f"<p>&bull; {prop_label}: {prop_value}</p>"

            self.component_settings_html.value = component_settings_string


class ObservableHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session, openbis_object):
        super().__init__()
        self.openbis_session = openbis_session
        self.openbis_object = openbis_object
        self.observable_type = self.openbis_object.type.code
        self.observable_type_lower = self.observable_type.lower()

        self.name_label = ipw.Label(value="Name:")
        self.name_html = ipw.HTML()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_html])

        self.description_label = ipw.Label(value="Description:")
        self.description_html = ipw.HTML()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_html]
        )

        self.ch_name_label = ipw.Label(value="Channel name:")
        self.ch_name_html = ipw.HTML()
        self.ch_name_hbox = ipw.HBox(children=[self.ch_name_label, self.ch_name_html])

        self.component_label = ipw.Label(value="Component:")
        self.component_html = ipw.HTML()
        self.component_hbox = ipw.HBox(
            children=[self.component_label, self.component_html]
        )

        self.component_settings_label = ipw.Label(value="Component settings:")
        self.component_settings_html = ipw.HTML()
        self.component_settings_hbox = ipw.HBox(
            children=[self.component_settings_label, self.component_settings_html]
        )

        self.comments_label = ipw.Label(value="Comments:")
        self.comments_html = ipw.HTML()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_html]
        )

        self.load_observable_data()

        self.children = [
            self.name_hbox,
            self.description_hbox,
            self.comments_hbox,
            self.ch_name_hbox,
            self.component_hbox,
            self.component_settings_hbox,
        ]

    def load_observable_data(self):
        openbis_object_props = self.openbis_object.props.all()
        if openbis_object_props["name"]:
            self.name_html.value = openbis_object_props["name"]

        if openbis_object_props["description"]:
            self.description_html.value = openbis_object_props["description"]

        if openbis_object_props["channel_name"]:
            self.ch_name_html.value = openbis_object_props["channel_name"]

        if openbis_object_props["comments"]:
            self.comments_html.value = openbis_object_props["comments"]

        component_id = openbis_object_props["component"]

        if component_id:
            component_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=component_id
            )
            self.component_html.value = component_object.props["name"]

        if openbis_object_props["component_settings"]:
            component_settings = json.loads(openbis_object_props["component_settings"])
            component_settings_string = ""
            for prop_key, prop_value in component_settings.items():
                prop_type = utils.get_openbis_property_type(
                    self.openbis_session, code=prop_key
                )
                prop_label = prop_type.label

                # Convert quantity values from json objects to strings
                if prop_value and isinstance(prop_value, dict):
                    unit_type = ""
                    for key in prop_value.keys():
                        if key == "unit":
                            unit_type = key
                            break
                    prop_value = utils.stringify_quantity_value(prop_value, unit_type)

                component_settings_string += f"<p>&bull; {prop_label}: {prop_value}</p>"

            self.component_settings_html.value = component_settings_string


class RegisterProcessWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        self.select_collection_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select collection</span>"
        )

        self.new_processes_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Register new steps</span>"
        )

        self.select_collection_label = ipw.Label(value="Collection")
        self.select_collection_dropdown = ipw.Dropdown()
        self.select_collection_hbox = ipw.HBox(
            [self.select_collection_label, self.select_collection_dropdown]
        )
        self.load_collections()

        self.process_properties_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Process properties</span>"
        )

        self.process_name_label = ipw.Label(value="Name")
        self.process_name_text = ipw.Text()
        self.process_name_hbox = ipw.HBox(
            [self.process_name_label, self.process_name_text]
        )

        self.process_short_name_label = ipw.Label(value="Short name")
        self.process_short_name_text = ipw.Text()
        self.process_short_name_hbox = ipw.HBox(
            [self.process_short_name_label, self.process_short_name_text]
        )

        self.process_description_label = ipw.Label(value="Description")
        self.process_description_text = ipw.Textarea()
        self.process_description_hbox = ipw.HBox(
            [self.process_description_label, self.process_description_text]
        )

        self.new_processes_accordion = ipw.Accordion()

        self.add_process_step_button = ipw.Button(
            description="Add process step",
            disabled=False,
            button_style="success",
            tooltip="Add process step",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.children = [
            self.select_collection_title,
            self.select_collection_hbox,
            self.process_properties_title,
            self.process_name_hbox,
            self.process_short_name_hbox,
            self.process_description_hbox,
            self.new_processes_title,
            self.new_processes_accordion,
            self.add_process_step_button,
            self.save_button,
        ]

        self.add_process_step_button.on_click(self.add_process_step)
        self.save_button.on_click(self.save_process_steps)

    def load_collections(self):
        collections = utils.get_openbis_collections(
            self.openbis_session, type="COLLECTION", project=processes_project
        )
        collection_options = []
        for col in collections:
            if "name" in col.props.all():
                col_option = (
                    f"{col.props['name']} from Project {col.project.code} and Space {col.project.space}",
                    col.permId,
                )
            else:
                col_option = (
                    f"{col.code} from Project {col.project.code} and Space {col.project.space}",
                    col.permId,
                )
            collection_options.append(col_option)
        collection_options.insert(0, ("Select collection...", "-1"))
        self.select_collection_dropdown.options = collection_options
        self.select_collection_dropdown.value = "-1"

    def add_process_step(self, b):
        processes_accordion_children = list(self.new_processes_accordion.children)
        process_step_index = len(processes_accordion_children)
        new_process_step_widget = RegisterProcessStepWidget(
            self.openbis_session, self.new_processes_accordion, process_step_index
        )
        processes_accordion_children.append(new_process_step_widget)
        self.new_processes_accordion.children = processes_accordion_children

    def save_process_steps(self, b):
        collection_id = self.select_collection_dropdown.value
        if collection_id == "-1":
            display(Javascript(data="alert('Select a collection.')"))
            logger.info("Collection was not selected.")
            return

        process_steps_widgets = self.new_processes_accordion.children

        if process_steps_widgets:
            openbis_transaction_objects = []

            process_name = ""
            if self.process_name_text.value:
                process_name = self.process_name_text.value

            process_short_name = ""
            if self.process_short_name_text.value:
                process_short_name = self.process_short_name_text.value

            process_description = ""
            if self.process_description_text.value:
                process_description = self.process_description_text.value

            process_properties = {
                "name": process_name,
                "short_name": process_short_name,
                "description": process_description,
                "process_steps_settings": [],
            }

            process_steps_instruments = []

            for process_widget in process_steps_widgets:
                process_step_name = process_widget.name_textbox.value
                process_step_description = process_widget.description_textbox.value
                process_step_instrument = process_widget.instrument_dropdown.value
                process_step_comments = process_widget.comments_textarea.value

                actions_widgets = process_widget.actions_accordion.children
                observables_widgets = process_widget.observables_accordion.children
                actions = []
                observables = []

                if actions_widgets:
                    for action_widget in actions_widgets:
                        action_properties = {}
                        action_type = action_widget.action_type_dropdown.value
                        duration_days = action_widget.duration_days_intbox.value
                        duration_hours = action_widget.duration_hours_intbox.value
                        duration_minutes = action_widget.duration_minutes_intbox.value
                        duration_seconds = action_widget.duration_seconds_intbox.value

                        if action_type == OPENBIS_OBJECT_TYPES["Annealing"]:
                            target_temperature = {
                                "value": action_widget.target_temperature_value_textbox.value,
                                "unit": action_widget.target_temperature_unit_dropdown.value,
                            }
                            action_properties["target_temperature"] = json.dumps(
                                target_temperature
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Cooldown"]:
                            target_temperature = {
                                "value": action_widget.target_temperature_value_textbox.value,
                                "unit": action_widget.target_temperature_unit_dropdown.value,
                            }
                            action_properties["target_temperature"] = json.dumps(
                                target_temperature
                            )
                            action_properties["cryogen"] = (
                                action_widget.cryogen_textbox.value
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Deposition"]:
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            substance = action_widget.substance_dropdown.value
                            if substance != "-1":
                                action_properties["substance"] = substance

                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Dosing"]:
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            pressure = {
                                "value": action_widget.pressure_value_textbox.value,
                                "unit": action_widget.pressure_unit_dropdown.value,
                            }
                            gas = action_widget.gas_dropdown.value
                            action_properties["gas"] = gas
                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )
                            action_properties["pressure"] = json.dumps(pressure)

                        elif action_type == OPENBIS_OBJECT_TYPES["Sputtering"]:
                            pressure = {
                                "value": action_widget.pressure_value_textbox.value,
                                "unit": action_widget.pressure_unit_dropdown.value,
                            }
                            current = {
                                "value": action_widget.current_value_textbox.value,
                                "unit": action_widget.current_unit_dropdown.value,
                            }
                            angle = {
                                "value": action_widget.angle_value_textbox.value,
                                "unit": action_widget.angle_unit_dropdown.value,
                            }
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            action_properties["pressure"] = json.dumps(pressure)
                            action_properties["current"] = json.dumps(current)
                            action_properties["angle"] = json.dumps(angle)
                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )
                            action_properties["sputter_ion"] = (
                                action_widget.sputter_ion_textbox.value
                            )

                        component_permid = action_widget.component_dropdown.value
                        if component_permid != "-1":
                            component_object = utils.get_openbis_object(
                                self.openbis_session, sample_ident=component_permid
                            )
                            component_object_settings = component_object.props[
                                "actions_settings"
                            ]

                            if component_object_settings:
                                component_settings = {}
                                component_object_settings = json.loads(
                                    component_object_settings
                                )
                                action_component_settings = []
                                for action_settings in component_object_settings:
                                    if "action_type" in action_settings:
                                        if (
                                            action_settings["action_type"]
                                            == action_type
                                        ):
                                            if (
                                                "component_properties"
                                                in action_settings
                                            ):
                                                action_component_settings = (
                                                    action_settings[
                                                        "component_properties"
                                                    ]
                                                )
                                                break

                                for setting in action_component_settings:
                                    if setting == "target_temperature":
                                        component_settings["target_temperature"] = {
                                            "value": action_widget.target_temperature_value_comp_textbox.value,
                                            "unit": action_widget.target_temperature_unit_comp_dropdown.value,
                                        }
                                    elif setting == "bias_voltage":
                                        component_settings["bias_voltage"] = {
                                            "value": action_widget.bias_voltage_value_textbox.value,
                                            "unit": action_widget.bias_voltage_unit_dropdown.value,
                                        }
                                    elif setting == "discharge_voltage":
                                        component_settings["discharge_voltage"] = {
                                            "value": action_widget.discharge_voltage_value_textbox.value,
                                            "unit": action_widget.discharge_voltage_unit_dropdown.value,
                                        }
                                    elif setting == "discharge_current":
                                        component_settings["discharge_current"] = {
                                            "value": action_widget.discharge_current_value_textbox.value,
                                            "unit": action_widget.discharge_current_unit_dropdown.value,
                                        }
                                    elif setting == "p_value":
                                        component_settings["p_value"] = float(
                                            action_widget.evaporator_p_value_textbox.value
                                        )

                                    elif setting == "i_value":
                                        component_settings["i_value"] = float(
                                            action_widget.evaporator_i_value_textbox.value
                                        )

                                    elif setting == "ep_percentage":
                                        component_settings["ep_percentage"] = float(
                                            action_widget.ep_percentage_textbox.value
                                        )

                                # Update current component settings
                                for (
                                    setting_key,
                                    setting_value,
                                ) in component_settings.items():
                                    if isinstance(setting_value, dict):
                                        component_object.props[setting_key] = (
                                            json.dumps(setting_value)
                                        )
                                    else:
                                        component_object.props[setting_key] = (
                                            setting_value
                                        )
                                utils.update_openbis_object(component_object)
                                logger.info(
                                    f"Component {component_object.permId} properties changed successfully."
                                )

                                action_properties["component_settings"] = json.dumps(
                                    component_settings
                                )

                            action_properties["name"] = action_widget.name_textbox.value
                            action_properties["description"] = (
                                action_widget.description_textbox.value
                            )
                            action_properties["duration"] = (
                                f"{duration_days} days {duration_hours:02}:{duration_minutes:02}:{duration_seconds:02}"
                            )
                            action_properties["component"] = component_permid
                            action_properties["comments"] = (
                                action_widget.comments_textarea.value
                            )

                            new_action_object = utils.create_openbis_object(
                                self.openbis_session,
                                type=action_type,
                                experiment=collection_id,
                                props=action_properties,
                            )
                            logger.info(
                                f"Action {new_action_object.permId} created successfully."
                            )

                            # Append action to list of actions
                            actions.append(new_action_object.permId)

                if observables_widgets:
                    for observable_widget in observables_widgets:
                        observable_properties = {}
                        observable_type = (
                            observable_widget.observable_type_dropdown.value
                        )

                        component_permid = observable_widget.component_dropdown.value
                        if component_permid != "-1":
                            component_object = utils.get_openbis_object(
                                self.openbis_session, sample_ident=component_permid
                            )
                            component_object_settings = component_object.props[
                                "observables_settings"
                            ]

                            if component_object_settings:
                                component_settings = {}
                                component_object_settings = json.loads(
                                    component_object_settings
                                )
                                observable_component_settings = []
                                for observable_settings in component_object_settings:
                                    if "observable_type" in observable_settings:
                                        if (
                                            observable_settings["observable_type"]
                                            == observable_type
                                        ):
                                            if (
                                                "component_properties"
                                                in observable_settings
                                            ):
                                                observable_component_settings = (
                                                    observable_settings[
                                                        "component_properties"
                                                    ]
                                                )
                                                break

                                for setting in observable_component_settings:
                                    if setting == "density":
                                        component_settings["density"] = {
                                            "value": observable_widget.density_value_textbox.value,
                                            "unit": observable_widget.density_unit_dropdown.value,
                                        }

                                    elif setting == "filament":
                                        component_settings["filament"] = (
                                            observable_widget.filament_textbox.value
                                        )

                                    elif setting == "filament_current":
                                        component_settings["filament_current"] = {
                                            "value": observable_widget.filament_current_value_textbox.value,
                                            "unit": observable_widget.filament_current_unit_dropdown.value,
                                        }

                                # Update current component settings
                                for (
                                    setting_key,
                                    setting_value,
                                ) in component_settings.items():
                                    if isinstance(setting_value, dict):
                                        component_object.props[setting_key] = (
                                            json.dumps(setting_value)
                                        )
                                    else:
                                        component_object.props[setting_key] = (
                                            setting_value
                                        )
                                utils.update_openbis_object(component_object)
                                logger.info(
                                    f"Component {component_object.permId} properties changed successfully."
                                )

                                observable_properties["component_settings"] = (
                                    json.dumps(component_settings)
                                )

                            observable_properties["name"] = (
                                observable_widget.name_textbox.value
                            )
                            observable_properties["description"] = (
                                observable_widget.description_textbox.value
                            )
                            observable_properties["channel_name"] = (
                                observable_widget.ch_name_textbox.value
                            )
                            observable_properties["component"] = component_permid
                            observable_properties["comments"] = (
                                observable_widget.comments_textarea.value
                            )

                            new_observable_object = utils.create_openbis_object(
                                self.openbis_session,
                                type=observable_type,
                                experiment=collection_id,
                                props=observable_properties,
                            )

                            logger.info(
                                f"Observable {new_observable_object.permId} created successfully."
                            )

                            openbis_transaction_objects.append(new_observable_object)

                            # Append observable to list of observables
                            observables.append(new_observable_object.permId)

                actions_settings = []
                for action_id in actions:
                    actions_settings.append({"action": action_id})

                observables_settings = []
                for observable_id in observables:
                    observables_settings.append({"observable": observable_id})

                process_step_settings = {
                    "name": process_step_name,
                    "description": process_step_description,
                    "instrument": process_step_instrument,
                    "comments": process_step_comments,
                    "actions_settings": actions_settings,
                    "observables_settings": observables_settings,
                }
                process_properties["process_steps_settings"].append(
                    process_step_settings
                )

                process_steps_instruments.append(process_step_instrument)

            # Convert property to JSON
            process_properties["process_steps_settings"] = json.dumps(
                process_properties["process_steps_settings"]
            )

            new_process_object = utils.create_openbis_object(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Process"],
                experiment=collection_id,
                props=process_properties,
            )

            logger.info(f"Process {new_process_object.permId} created successfully.")

            # Reset new processes accordion
            processes_accordion_children = list(self.new_processes_accordion.children)
            for index, _ in enumerate(processes_accordion_children):
                self.new_processes_accordion.set_title(index, "")

            self.new_processes_accordion.children = []

            self.select_collection_dropdown.value = "-1"

            logger.info("Resetting new process steps interface.")


class RegisterPreparationWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session
        self.sample_preparation_object = None

        self.select_experiment_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select experiment</span>"
        )

        self.select_sample_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Select sample</span>"
        )

        self.sample_history_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Sample history</span>"
        )

        self.new_processes_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 20px;'>Register new steps</span>"
        )

        self.process_short_name = ""

        self.select_experiment_dropdown = widgets.SelectExperimentWidget(
            self.openbis_session
        )
        self.select_sample_dropdown = widgets.SelectSampleWidget(self.openbis_session)
        self.sample_history_vbox = SampleHistoryWidget(self.openbis_session)
        self.new_processes_accordion = ipw.Accordion()

        self.load_process_button = ipw.Button(
            description="Load process",
            disabled=False,
            button_style="success",
            tooltip="Load process",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.add_process_step_button = ipw.Button(
            description="Add process step",
            disabled=False,
            button_style="success",
            tooltip="Add process step",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.process_buttons_hbox = ipw.HBox(
            children=[self.load_process_button, self.add_process_step_button]
        )

        self.sort_name_label = ipw.Label(
            value="Name",
            layout=ipw.Layout(margin="2px", width="50px"),
            style={"description_width": "initial"},
        )

        self.sort_name_checkbox = ipw.Checkbox(
            indent=False, layout=ipw.Layout(margin="2px", width="20px")
        )

        self.load_processes_hbox = ipw.HBox()
        self.processes_dropdown = ipw.Dropdown()

        self.save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.children = [
            self.select_experiment_title,
            self.select_experiment_dropdown,
            self.select_sample_title,
            self.select_sample_dropdown,
            self.sample_history_title,
            self.sample_history_vbox,
            self.new_processes_title,
            self.load_processes_hbox,
            self.new_processes_accordion,
            self.process_buttons_hbox,
            self.save_button,
        ]

        self.select_sample_dropdown.sample_dropdown.observe(
            self.load_sample_data, names="value"
        )

        self.load_process_button.on_click(self.load_process)
        self.processes_dropdown.observe(self.load_process_settings, names="value")
        self.add_process_step_button.on_click(self.add_process_step)
        self.save_button.on_click(self.save_process_steps)

    def load_sample_data(self, change):
        if self.select_sample_dropdown.sample_dropdown.value == "-1":
            self.sample_history_vbox.sample_history.children = []
            return

        sample_identifier = self.select_sample_dropdown.sample_dropdown.value
        sample_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=sample_identifier
        )

        sample_object_parents = sample_object.parents
        most_recent_parent = None

        for parent_id in sample_object_parents:
            parent_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=parent_id
            )

            parent_type = parent_object.type
            if parent_type == OPENBIS_OBJECT_TYPES["Process Step"]:
                if most_recent_parent:
                    if (
                        parent_object.registrationDate
                        > most_recent_parent.registrationDate
                    ):
                        most_recent_parent = parent_object
                else:
                    most_recent_parent = parent_object

        if most_recent_parent:
            if (
                most_recent_parent.experiment.permId
                != self.select_experiment_dropdown.experiment_dropdown.value
            ):
                self.select_experiment_dropdown.experiment_dropdown.value = (
                    most_recent_parent.experiment.permId
                )
                display(Javascript(data="alert('Experiment was changed!')"))

            for parent in most_recent_parent.parents:
                parent_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )

                if parent_object.type == OPENBIS_OBJECT_TYPES["Preparation"]:
                    self.sample_preparation_object = parent_object
                    break

        # Load sample history
        self.sample_history_vbox.load_sample_history(sample_object)

    def add_process_step(self, b):
        processes_accordion_children = list(self.new_processes_accordion.children)
        process_step_index = len(processes_accordion_children)
        new_process_step_widget = RegisterProcessStepWidget(
            self.openbis_session, self.new_processes_accordion, process_step_index
        )
        processes_accordion_children.append(new_process_step_widget)
        self.new_processes_accordion.children = processes_accordion_children

    def load_process(self, b):
        openbis_processes = utils.get_openbis_objects(
            self.openbis_session, type=OPENBIS_OBJECT_TYPES["Process"]
        )
        processes_options = []
        for obj in openbis_processes:
            if obj.props["process_steps_settings"]:
                processes_options.append((obj.props["name"], obj.permId))
        processes_options.insert(0, ("Select a process...", "-1"))
        self.processes_dropdown.options = processes_options
        self.processes_dropdown.value = "-1"

        cancel_button = ipw.Button(
            description="X",
            disabled=False,
            button_style="danger",
            tooltip="Cancel",
            layout=ipw.Layout(width="30px", height="30px"),
        )

        def close_load_processes(b):
            self.load_processes_hbox.children = []

        cancel_button.on_click(close_load_processes)

        self.load_processes_hbox.children = [self.processes_dropdown, cancel_button]

    def load_process_settings(self, change):
        process_id = self.processes_dropdown.value
        if process_id == "-1":
            return
        else:
            process_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=process_id
            )
            process_steps_settings = process_object.props["process_steps_settings"]
            self.process_short_name = process_object.props["short_name"] or ""
            if process_steps_settings:
                process_steps_settings = json.loads(process_steps_settings)
                for step_settings in process_steps_settings:
                    processes_accordion_children = list(
                        self.new_processes_accordion.children
                    )
                    process_step_index = len(processes_accordion_children)
                    new_process_step_widget = RegisterProcessStepWidget(
                        self.openbis_session,
                        self.new_processes_accordion,
                        process_step_index,
                        step_settings,
                    )
                    processes_accordion_children.append(new_process_step_widget)
                    self.new_processes_accordion.children = processes_accordion_children

            self.load_processes_hbox.children = []

            self.children = [
                self.select_experiment_title,
                self.select_experiment_dropdown,
                self.select_sample_title,
                self.select_sample_dropdown,
                self.sample_history_title,
                self.sample_history_vbox,
                self.new_processes_title,
                self.load_processes_hbox,
                self.new_processes_accordion,
                self.save_button,
            ]

    def save_process_steps(self, b):
        experiment_id = self.select_experiment_dropdown.experiment_dropdown.value
        if experiment_id == "-1":
            display(Javascript(data="alert('Select an experiment.')"))
            return

        current_sample_id = self.select_sample_dropdown.sample_dropdown.value
        if current_sample_id == "-1":
            display(Javascript(data="alert('Select a sample.')"))
            return

        processes_widgets = self.new_processes_accordion.children
        if processes_widgets:
            openbis_transaction_objects = []
            experiment_object = utils.get_openbis_collection(
                self.openbis_session, code=experiment_id
            )
            experiment_project_code = experiment_object.project.identifier

            current_sample = utils.get_openbis_object(
                self.openbis_session, sample_ident=current_sample_id
            )

            # If sample was used in a measurement session, a new preparation should start
            sample_object_children = current_sample.children
            for child_id in sample_object_children:
                child_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=child_id
                )
                if child_object.type == OPENBIS_OBJECT_TYPES["Measurement Session"]:
                    self.sample_preparation_object = None
                    break

            # Create preparation object when it does not exist
            if self.sample_preparation_object is None:
                self.sample_preparation_object = utils.create_openbis_object(
                    self.openbis_session,
                    type=OPENBIS_OBJECT_TYPES["Preparation"],
                    experiment=experiment_object.identifier,
                    props={"name": current_sample.props["name"]},
                )

            sample_preparation_id = self.sample_preparation_object.permId
            for process_widget in processes_widgets:
                # Reload sample preparation object to load children that was added in the cycle (e.g. process steps)
                self.sample_preparation_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=sample_preparation_id
                )
                sample_type = OPENBIS_OBJECT_TYPES["Sample"]
                process_code = ""
                current_sample.props["object_status"] = "INACTIVE"
                current_sample_name = current_sample.props["name"]
                utils.update_openbis_object(current_sample)

                process_step_type = OPENBIS_OBJECT_TYPES["Process Step"]
                new_process_object = utils.create_openbis_object(
                    self.openbis_session,
                    type=process_step_type,
                    experiment=experiment_object.identifier,
                )

                process_properties = {
                    "name": process_widget.name_textbox.value,
                    "description": process_widget.description_textbox.value,
                    "instrument": process_widget.instrument_dropdown.value,
                    "comments": process_widget.comments_textarea.value,
                }

                actions_widgets = process_widget.actions_accordion.children
                observables_widgets = process_widget.observables_accordion.children
                actions = []
                observables = []

                actions_codes = []
                if actions_widgets:
                    for action_widget in actions_widgets:
                        action_properties = {}
                        action_type = action_widget.action_type_dropdown.value
                        duration_days = action_widget.duration_days_intbox.value
                        duration_hours = action_widget.duration_hours_intbox.value
                        duration_minutes = action_widget.duration_minutes_intbox.value
                        duration_seconds = action_widget.duration_seconds_intbox.value

                        if action_type == OPENBIS_OBJECT_TYPES["Annealing"]:
                            target_temperature = {
                                "value": action_widget.target_temperature_value_textbox.value,
                                "unit": action_widget.target_temperature_unit_dropdown.value,
                            }
                            action_properties["target_temperature"] = json.dumps(
                                target_temperature
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Cooldown"]:
                            target_temperature = {
                                "value": action_widget.target_temperature_value_textbox.value,
                                "unit": action_widget.target_temperature_unit_dropdown.value,
                            }
                            action_properties["target_temperature"] = json.dumps(
                                target_temperature
                            )
                            action_properties["cryogen"] = (
                                action_widget.cryogen_textbox.value
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Deposition"]:
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            substance = action_widget.substance_dropdown.value
                            if substance != "-1":
                                action_properties["substance"] = substance

                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )

                        elif action_type == OPENBIS_OBJECT_TYPES["Dosing"]:
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            pressure = {
                                "value": action_widget.pressure_value_textbox.value,
                                "unit": action_widget.pressure_unit_dropdown.value,
                            }
                            gas = action_widget.gas_dropdown.value
                            action_properties["gas"] = gas
                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )
                            action_properties["pressure"] = json.dumps(pressure)

                        elif action_type == OPENBIS_OBJECT_TYPES["Sputtering"]:
                            pressure = {
                                "value": action_widget.pressure_value_textbox.value,
                                "unit": action_widget.pressure_unit_dropdown.value,
                            }
                            current = {
                                "value": action_widget.current_value_textbox.value,
                                "unit": action_widget.current_unit_dropdown.value,
                            }
                            angle = {
                                "value": action_widget.angle_value_textbox.value,
                                "unit": action_widget.angle_unit_dropdown.value,
                            }
                            substrate_temperature = {
                                "value": action_widget.substrate_temperature_value_textbox.value,
                                "unit": action_widget.substrate_temperature_unit_dropdown.value,
                            }
                            action_properties["pressure"] = json.dumps(pressure)
                            action_properties["current"] = json.dumps(current)
                            action_properties["angle"] = json.dumps(angle)
                            action_properties["substrate_temperature"] = json.dumps(
                                substrate_temperature
                            )
                            action_properties["sputter_ion"] = (
                                action_widget.sputter_ion_textbox.value
                            )

                        component_permid = action_widget.component_dropdown.value
                        if component_permid != "-1":
                            component_object = utils.get_openbis_object(
                                self.openbis_session, sample_ident=component_permid
                            )
                            component_object_settings = component_object.props[
                                "actions_settings"
                            ]

                            if component_object_settings:
                                component_settings = {}
                                component_object_settings = json.loads(
                                    component_object_settings
                                )
                                action_component_settings = []
                                for action_settings in component_object_settings:
                                    if action_settings["action_type"] == action_type:
                                        action_component_settings = action_settings[
                                            "component_properties"
                                        ]
                                        break

                                for setting in action_component_settings:
                                    if setting == "target_temperature":
                                        component_settings["target_temperature"] = {
                                            "value": action_widget.target_temperature_value_comp_textbox.value,
                                            "unit": action_widget.target_temperature_unit_comp_dropdown.value,
                                        }
                                    elif setting == "bias_voltage":
                                        component_settings["bias_voltage"] = {
                                            "value": action_widget.bias_voltage_value_textbox.value,
                                            "unit": action_widget.bias_voltage_unit_dropdown.value,
                                        }
                                    elif setting == "discharge_voltage":
                                        component_settings["discharge_voltage"] = {
                                            "value": action_widget.discharge_voltage_value_textbox.value,
                                            "unit": action_widget.discharge_voltage_unit_dropdown.value,
                                        }
                                    elif setting == "discharge_current":
                                        component_settings["discharge_current"] = {
                                            "value": action_widget.discharge_current_value_textbox.value,
                                            "unit": action_widget.discharge_current_unit_dropdown.value,
                                        }
                                    elif setting == "p_value":
                                        p_value_str = action_widget.evaporator_p_value_textbox.value
                                        if p_value_str:
                                            component_settings["p_value"] = float(
                                                p_value_str
                                            )

                                    elif setting == "i_value":
                                        i_value_str = action_widget.evaporator_i_value_textbox.value
                                        if i_value_str:
                                            component_settings["i_value"] = float(
                                                i_value_str
                                            )

                                    elif setting == "ep_percentage":
                                        ep_percentage_value_str = (
                                            action_widget.ep_percentage_textbox.value
                                        )
                                        if ep_percentage_value_str:
                                            component_settings["ep_percentage"] = float(
                                                ep_percentage_value_str
                                            )

                                # Update current component settings
                                for (
                                    setting_key,
                                    setting_value,
                                ) in component_settings.items():
                                    if isinstance(setting_value, dict):
                                        component_object.props[setting_key] = (
                                            json.dumps(setting_value)
                                        )
                                    else:
                                        component_object.props[setting_key] = (
                                            setting_value
                                        )
                                utils.update_openbis_object(component_object)

                                action_properties["component_settings"] = json.dumps(
                                    component_settings
                                )

                            action_properties["name"] = action_widget.name_textbox.value
                            action_properties["description"] = (
                                action_widget.description_textbox.value
                            )
                            action_properties["duration"] = (
                                f"{duration_days} days {duration_hours:02}:{duration_minutes:02}:{duration_seconds:02}"
                            )
                            action_properties["component"] = component_permid
                            action_properties["comments"] = (
                                action_widget.comments_textarea.value
                            )

                            action_collection_code = "ACTIONS_COLLECTION"
                            openbis_experiments = utils.get_openbis_collections(
                                self.openbis_session,
                                code=action_collection_code,
                                project=experiment_project_code,
                            )

                            if openbis_experiments.df.empty:
                                utils.create_openbis_collection(
                                    self.openbis_session,
                                    type="COLLECTION",
                                    code=action_collection_code,
                                    project=experiment_project_code,
                                    props={"name": "Actions"},
                                )

                            new_action_object = utils.create_openbis_object(
                                self.openbis_session,
                                type=action_type,
                                experiment=f"{experiment_project_code}/{action_collection_code}",
                                props=action_properties,
                            )

                            # Append action to list of actions
                            actions.append(new_action_object.permId)

                            # Get action code
                            actions_codes.append(ACTIONS_CODES[action_type])

                if observables_widgets:
                    for observable_widget in observables_widgets:
                        observable_properties = {}
                        observable_type = (
                            observable_widget.observable_type_dropdown.value
                        )

                        component_permid = observable_widget.component_dropdown.value
                        if component_permid != "-1":
                            component_object = utils.get_openbis_object(
                                self.openbis_session, sample_ident=component_permid
                            )
                            component_object_settings = component_object.props[
                                "observables_settings"
                            ]

                            if component_object_settings:
                                component_settings = {}
                                component_object_settings = json.loads(
                                    component_object_settings
                                )
                                observable_component_settings = []
                                for observable_settings in component_object_settings:
                                    if (
                                        observable_settings["observable_type"]
                                        == observable_type
                                    ):
                                        observable_component_settings = (
                                            observable_settings["component_properties"]
                                        )
                                        break

                                for setting in observable_component_settings:
                                    if setting == "density":
                                        component_settings["density"] = {
                                            "value": observable_widget.density_value_textbox.value,
                                            "unit": observable_widget.density_unit_dropdown.value,
                                        }

                                    elif setting == "filament":
                                        component_settings["filament"] = (
                                            observable_widget.filament_textbox.value
                                        )

                                    elif setting == "filament_current":
                                        component_settings["filament_current"] = {
                                            "value": observable_widget.filament_current_value_textbox.value,
                                            "unit": observable_widget.filament_current_unit_dropdown.value,
                                        }

                                # Update current component settings
                                for (
                                    setting_key,
                                    setting_value,
                                ) in component_settings.items():
                                    if isinstance(setting_value, dict):
                                        component_object.props[setting_key] = (
                                            json.dumps(setting_value)
                                        )
                                    else:
                                        component_object.props[setting_key] = (
                                            setting_value
                                        )
                                utils.update_openbis_object(component_object)

                                observable_properties["component_settings"] = (
                                    json.dumps(component_settings)
                                )

                            observable_properties["name"] = (
                                observable_widget.name_textbox.value
                            )
                            observable_properties["description"] = (
                                observable_widget.description_textbox.value
                            )
                            observable_properties["channel_name"] = (
                                observable_widget.ch_name_textbox.value
                            )
                            observable_properties["component"] = component_permid
                            observable_properties["comments"] = (
                                observable_widget.comments_textarea.value
                            )

                            observable_collection_code = "OBSERVABLES_COLLECTION"
                            openbis_experiments = utils.get_openbis_collections(
                                self.openbis_session,
                                code=observable_collection_code,
                                project=experiment_project_code,
                            )

                            if openbis_experiments.df.empty:
                                utils.create_openbis_collection(
                                    self.openbis_session,
                                    type="COLLECTION",
                                    code=observable_collection_code,
                                    project=experiment_project_code,
                                    props={"name": "Observables"},
                                )

                            new_observable_object = utils.create_openbis_object(
                                self.openbis_session,
                                type=observable_type,
                                experiment=f"{experiment_project_code}/{observable_collection_code}",
                                props=observable_properties,
                            )

                            utils.upload_datasets(
                                self.openbis_session,
                                new_observable_object,
                                observable_widget.upload_readings_widget,
                                "ATTACHMENT",
                            )

                            openbis_transaction_objects.append(new_observable_object)

                            # Append observable to list of observables
                            observables.append(new_observable_object.permId)

                process_properties["actions"] = actions
                process_properties["observables"] = observables

                if actions_codes and not self.process_short_name:
                    # Compute process code based on the selected actions
                    counts = Counter(actions_codes)
                    unique_codes = list(counts.keys())
                    num_repeats = (
                        counts[unique_codes[0]]
                        if len(counts) == 1
                        or all(
                            v == next(iter(counts.values())) for v in counts.values()
                        )
                        else 1
                    )

                    if len(actions_codes) == 1:
                        process_code = actions_codes[0]
                    elif num_repeats > 1 and all(
                        v == num_repeats for v in counts.values()
                    ):
                        process_code = f"({':'.join(unique_codes)}){num_repeats}"
                    else:
                        process_code = f"[{':'.join(actions_codes)}]"

                else:
                    process_code = self.process_short_name

                new_sample_name = f"{current_sample_name}:{process_code}"
                self.sample_preparation_object.props["name"] = f"PREP_{new_sample_name}"
                self.sample_preparation_object.add_children(new_process_object.permId)
                utils.update_openbis_object(self.sample_preparation_object)

                new_process_object.props = process_properties
                new_process_object.add_parents(
                    [
                        self.sample_preparation_object,
                        current_sample,
                    ]
                )
                utils.update_openbis_object(new_process_object)

                new_sample = utils.create_openbis_object(
                    self.openbis_session,
                    type=sample_type,
                    experiment=OPENBIS_COLLECTIONS_PATHS["Sample"],
                    parents=[new_process_object],
                    props={"name": new_sample_name, "object_status": "ACTIVE"},
                )

                # After a process step, the current sample is now the new one
                current_sample = new_sample

            # Refresh sample dropdown and sample history
            self.select_sample_dropdown.load_samples()
            self.select_sample_dropdown.sample_dropdown.value = new_sample.permId

            # Reset new processes accordion
            processes_accordion_children = list(self.new_processes_accordion.children)
            for index, process_step in enumerate(processes_accordion_children):
                self.new_processes_accordion.set_title(index, "")

            self.process_short_name = ""
            self.new_processes_accordion.children = []

            self.children = [
                self.select_experiment_title,
                self.select_experiment_dropdown,
                self.select_sample_title,
                self.select_sample_dropdown,
                self.sample_history_title,
                self.sample_history_vbox,
                self.new_processes_title,
                self.load_processes_hbox,
                self.new_processes_accordion,
                self.process_buttons_hbox,
                self.save_button,
            ]


class RegisterProcessStepWidget(ipw.VBox):
    def __init__(
        self,
        openbis_session,
        processes_accordion,
        process_step_index,
        step_settings=None,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.processes_accordion = processes_accordion
        self.process_step_index = process_step_index

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Text()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_textbox]
        )

        self.instrument_label = ipw.Label(value="Instrument")
        instrument_objects = utils.get_openbis_objects(
            self.openbis_session, collection=OPENBIS_COLLECTIONS_PATHS["Instrument"]
        )
        instrument_options = [
            (obj.props["name"], obj.permId) for obj in instrument_objects
        ]
        instrument_options.insert(0, ("Select an instrument...", "-1"))
        self.instrument_dropdown = ipw.Dropdown(options=instrument_options, value="-1")
        self.instrument_hbox = ipw.HBox(
            children=[self.instrument_label, self.instrument_dropdown]
        )

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textarea = ipw.Textarea()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_textarea]
        )

        self.actions_label = ipw.Label(value="Actions")
        self.actions_accordion = ipw.Accordion()
        self.add_action_button = ipw.Button(
            description="Add action",
            disabled=False,
            button_style="success",
            tooltip="Add action",
            layout=ipw.Layout(width="150px", height="25px"),
        )
        self.actions_vbox = ipw.VBox(
            children=[
                self.actions_label,
                self.actions_accordion,
                self.add_action_button,
            ]
        )

        self.observables_label = ipw.Label(value="Observables")
        self.observables_accordion = ipw.Accordion()
        self.add_observable_button = ipw.Button(
            description="Add observable",
            disabled=False,
            button_style="success",
            tooltip="Add observable",
            layout=ipw.Layout(width="150px", height="25px"),
        )
        self.observables_vbox = ipw.VBox(
            children=[
                self.observables_label,
                self.observables_accordion,
                self.add_observable_button,
            ]
        )

        self.remove_process_step_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip="Remove process step",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.remove_process_step_button.on_click(self.remove_process_step)
        self.name_textbox.observe(self.change_process_step_title, names="value")
        self.add_action_button.on_click(self.add_action)
        self.add_observable_button.on_click(self.add_observable)

        # Load process step settings if provided
        if step_settings:
            self.load_process_step(step_settings)

        self.children = [
            self.name_hbox,
            self.description_hbox,
            self.instrument_hbox,
            self.comments_hbox,
            self.actions_vbox,
            self.observables_vbox,
            self.remove_process_step_button,
        ]

    def load_process_step(self, settings):
        self.name_textbox.value = settings.get("name", "")
        self.description_textbox.value = settings.get("description", "")
        self.instrument_dropdown.value = settings.get("instrument", "-1")
        self.comments_textarea.value = settings.get("comments", "")
        actions_settings = settings.get("actions_settings", {})
        observables_settings = settings.get("observables_settings", {})
        for action_settings in actions_settings:
            actions_accordion_children = list(self.actions_accordion.children)
            action_index = len(actions_accordion_children)
            new_action_widget = RegisterActionWidget(
                self.openbis_session,
                self.actions_accordion,
                action_index,
                self.instrument_dropdown.value,
                action_settings,
            )
            actions_accordion_children.append(new_action_widget)
            self.actions_accordion.children = actions_accordion_children

        for observable_settings in observables_settings:
            observables_accordion_children = list(self.observables_accordion.children)
            observable_index = len(observables_accordion_children)
            new_observable_widget = RegisterObservableWidget(
                self.openbis_session,
                self.observables_accordion,
                observable_index,
                self.instrument_dropdown.value,
                observable_settings,
            )
            observables_accordion_children.append(new_observable_widget)
            self.observables_accordion.children = observables_accordion_children

    def change_process_step_title(self, change):
        title = self.name_textbox.value
        self.processes_accordion.set_title(self.process_step_index, title)

    def remove_process_step(self, b):
        processes_accordion_children = list(self.processes_accordion.children)
        num_process_steps = len(processes_accordion_children)
        processes_accordion_children.pop(self.process_step_index)

        for index, process_step in enumerate(processes_accordion_children):
            if index >= self.process_step_index:
                process_step.process_step_index -= 1
                self.processes_accordion.set_title(
                    process_step.process_step_index, process_step.name_textbox.value
                )

        self.processes_accordion.set_title(num_process_steps - 1, "")
        self.processes_accordion.children = processes_accordion_children

    def add_action(self, b):
        instrument_permid = self.instrument_dropdown.value
        if instrument_permid != "-1":
            actions_accordion_children = list(self.actions_accordion.children)
            action_index = len(actions_accordion_children)
            new_action_widget = RegisterActionWidget(
                self.openbis_session,
                self.actions_accordion,
                action_index,
                instrument_permid,
            )
            actions_accordion_children.append(new_action_widget)
            self.actions_accordion.children = actions_accordion_children

    def add_observable(self, b):
        instrument_permid = self.instrument_dropdown.value
        if instrument_permid != "-1":
            observables_accordion_children = list(self.observables_accordion.children)
            observable_index = len(observables_accordion_children)
            new_observable_widget = RegisterObservableWidget(
                self.openbis_session,
                self.observables_accordion,
                observable_index,
                instrument_permid,
            )
            observables_accordion_children.append(new_observable_widget)
            self.observables_accordion.children = observables_accordion_children


class RegisterActionWidget(ipw.VBox):
    def __init__(
        self,
        openbis_session,
        actions_accordion,
        action_index,
        instrument_permid,
        action_settings=None,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.actions_accordion = actions_accordion
        self.action_index = action_index
        self.instrument_permid = instrument_permid

        self.action_type_label = ipw.Label(value="Action type")
        action_type_options = [(key, value) for key, value in ACTIONS_TYPES.items()]
        action_type_options.insert(0, ("Select an action type...", "-1"))

        self.action_type_dropdown = ipw.Dropdown(
            options=action_type_options, value="-1"
        )

        self.action_type_hbox = ipw.HBox(
            children=[self.action_type_label, self.action_type_dropdown]
        )
        self.action_properties_widgets = ipw.VBox()

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Text()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_textbox]
        )

        self.duration_label = ipw.Label(value="Duration")
        self.duration_days_intbox = ipw.BoundedIntText(
            value=0, min=0, layout=ipw.Layout(width="40px")
        )
        self.duration_days_label = ipw.Label("days")
        self.duration_hours_intbox = ipw.BoundedIntText(
            value=0, max=23, layout=ipw.Layout(width="40px")
        )
        self.duration_hours_label = ipw.Label(":")
        self.duration_minutes_intbox = ipw.BoundedIntText(
            value=0, max=59, layout=ipw.Layout(width="40px")
        )
        self.duration_minutes_label = ipw.Label(":")
        self.duration_seconds_intbox = ipw.BoundedIntText(
            value=0, max=59, layout=ipw.Layout(width="40px")
        )
        self.duration_hbox = ipw.HBox(
            children=[
                self.duration_label,
                self.duration_days_intbox,
                self.duration_days_label,
                self.duration_hours_intbox,
                self.duration_hours_label,
                self.duration_minutes_intbox,
                self.duration_minutes_label,
                self.duration_seconds_intbox,
            ]
        )

        self.substance_label = ipw.Label(value="Substance")
        substances_list = utils.get_openbis_objects(
            self.openbis_session,
            collection=OPENBIS_COLLECTIONS_PATHS["Precursor Substance"],
            type=OPENBIS_OBJECT_TYPES["Substance"],
        )

        substances_names_ids = []
        for obj in substances_list:
            obj_props = obj.props.all()
            if "empa_number" in obj_props and "batch" in obj_props:
                name = obj_props["empa_number"] + obj_props["batch"]
                if "vial" in obj_props:
                    if obj_props["vial"]:
                        name += obj_props["vial"]
                substances_names_ids.append((name, obj.permId))
            else:
                logging.info(f"Substance {obj.permId} is missing EMPA number or batch.")

        substance_options = substances_names_ids
        substance_options.insert(0, ("Select a substance...", "-1"))
        self.substance_dropdown = ipw.Dropdown(options=substance_options, value="-1")
        self.substance_mol_image = ipw.Image(
            layout=ipw.Layout(width="100px", height="100px")
        )
        self.substance_hbox = ipw.HBox(
            children=[
                self.substance_label,
                self.substance_dropdown,
                self.substance_mol_image,
            ]
        )

        self.gas_label = ipw.Label(value="Dosing gas")
        gas_list = utils.get_openbis_objects(
            self.openbis_session, collection=OPENBIS_COLLECTIONS_PATHS["Chemical"]
        )
        gas_options = [(obj.props["name"], obj.permId) for obj in gas_list]
        gas_options.insert(0, ("Select a dosing gas...", "-1"))
        self.gas_dropdown = ipw.Dropdown(options=gas_options, value="-1")
        self.gas_hbox = ipw.HBox(children=[self.gas_label, self.gas_dropdown])

        self.target_temperature_label = ipw.Label("Target temperature")
        self.target_temperature_value_textbox = ipw.Text()
        self.target_temperature_unit_dropdown = ipw.Dropdown(
            options=["K", "C"], value="C"
        )
        self.target_temperature_hbox = ipw.HBox(
            children=[
                self.target_temperature_label,
                self.target_temperature_value_textbox,
                self.target_temperature_unit_dropdown,
            ]
        )

        self.cryogen_label = ipw.Label("Cryogen")
        self.cryogen_textbox = ipw.Text()
        self.cryogen_hbox = ipw.HBox(
            children=[self.cryogen_label, self.cryogen_textbox]
        )

        self.substrate_temperature_label = ipw.Label("Substrate temperature")
        self.substrate_temperature_value_textbox = ipw.Text()
        self.substrate_temperature_unit_dropdown = ipw.Dropdown(
            options=["K", "C"], value="C"
        )
        self.substrate_temperature_hbox = ipw.HBox(
            children=[
                self.substrate_temperature_label,
                self.substrate_temperature_value_textbox,
                self.substrate_temperature_unit_dropdown,
            ]
        )

        self.pressure_label = ipw.Label("Pressure")
        self.pressure_value_textbox = ipw.Text()
        self.pressure_unit_dropdown = ipw.Dropdown(options=["mBar", "Pa"], value="mBar")
        self.pressure_hbox = ipw.HBox(
            children=[
                self.pressure_label,
                self.pressure_value_textbox,
                self.pressure_unit_dropdown,
            ]
        )

        self.sputter_ion_label = ipw.Label("Sputter Ion")
        self.sputter_ion_textbox = ipw.Text()
        self.sputter_ion_hbox = ipw.HBox(
            children=[self.sputter_ion_label, self.sputter_ion_textbox]
        )

        self.current_label = ipw.Label("Current")
        self.current_value_textbox = ipw.Text()
        self.current_unit_dropdown = ipw.Dropdown(options=["A", "mA"], value="A")
        self.current_hbox = ipw.HBox(
            children=[
                self.current_label,
                self.current_value_textbox,
                self.current_unit_dropdown,
            ]
        )

        self.angle_label = ipw.Label("Angle")
        self.angle_value_textbox = ipw.Text()
        self.angle_unit_dropdown = ipw.Dropdown(options=["deg"], value="deg")
        self.angle_hbox = ipw.HBox(
            children=[
                self.angle_label,
                self.angle_value_textbox,
                self.angle_unit_dropdown,
            ]
        )

        self.instrument_type_components_dictionary = {
            OPENBIS_OBJECT_TYPES["Instrument STM"]: [
                "pumps",
                "gauges",
                "vacuum_chambers",
                "ports_valves",
                "preparation_tools",
                "analysers",
                "mechanical_components",
                "stm_components",
                "control_data_acquisition",
                "temperature_environment_control",
                "auxiliary_components",
                "tips_sensors",
                "accessories",
            ]
        }

        self.component_label = ipw.Label(value="Component")
        self.component_dropdown = ipw.Dropdown()
        self.component_hbox = ipw.HBox(
            children=[self.component_label, self.component_dropdown]
        )
        self.component_settings_label = ipw.Label(value="Component settings:")
        self.component_settings_vbox = ipw.VBox()
        self.component_settings_hbox = ipw.HBox(
            children=[self.component_settings_label, self.component_settings_vbox]
        )
        self.component_vbox = ipw.VBox(
            children=[self.component_hbox, self.component_settings_hbox]
        )

        # BEGIN - Widgets for component properties
        self.bias_voltage_label = ipw.Label("Bias voltage")
        self.bias_voltage_value_textbox = ipw.Text()
        self.bias_voltage_unit_dropdown = ipw.Dropdown(options=["V", "mV"], value="V")
        self.bias_voltage_hbox = ipw.HBox(
            children=[
                self.bias_voltage_label,
                self.bias_voltage_value_textbox,
                self.bias_voltage_unit_dropdown,
            ]
        )

        self.discharge_voltage_label = ipw.Label("Discharge voltage")
        self.discharge_voltage_value_textbox = ipw.Text()
        self.discharge_voltage_unit_dropdown = ipw.Dropdown(
            options=["V", "kV"], value="V"
        )
        self.discharge_voltage_hbox = ipw.HBox(
            children=[
                self.discharge_voltage_label,
                self.discharge_voltage_value_textbox,
                self.discharge_voltage_unit_dropdown,
            ]
        )

        self.discharge_current_label = ipw.Label("Discharge current")
        self.discharge_current_value_textbox = ipw.Text()
        self.discharge_current_unit_dropdown = ipw.Dropdown(
            options=["A", "mA"], value="A"
        )
        self.discharge_current_hbox = ipw.HBox(
            children=[
                self.discharge_current_label,
                self.discharge_current_value_textbox,
                self.discharge_current_unit_dropdown,
            ]
        )

        # Target temperature set in the component
        self.target_temperature_comp_label = ipw.Label("Target temperature")
        self.target_temperature_value_comp_textbox = ipw.Text()
        self.target_temperature_unit_comp_dropdown = ipw.Dropdown(
            options=["K", "C"], value="C"
        )
        self.target_temperature_comp_hbox = ipw.HBox(
            children=[
                self.target_temperature_comp_label,
                self.target_temperature_value_comp_textbox,
                self.target_temperature_unit_comp_dropdown,
            ]
        )

        self.evaporator_p_value_label = ipw.Label("P-value")
        self.evaporator_p_value_textbox = ipw.Text()
        self.evaporator_p_value_hbox = ipw.HBox(
            children=[self.evaporator_p_value_label, self.evaporator_p_value_textbox]
        )

        self.evaporator_i_value_label = ipw.Label("I-value")
        self.evaporator_i_value_textbox = ipw.Text()
        self.evaporator_i_value_hbox = ipw.HBox(
            children=[self.evaporator_i_value_label, self.evaporator_i_value_textbox]
        )

        self.ep_percentage_label = ipw.Label("EP (%)")
        self.ep_percentage_textbox = ipw.Text()
        self.ep_percentage_hbox = ipw.HBox(
            children=[self.ep_percentage_label, self.ep_percentage_textbox]
        )

        self.components_properties_widgets = {
            "target_temperature": self.target_temperature_comp_hbox,
            "bias_voltage": self.bias_voltage_hbox,
            "discharge_voltage": self.discharge_voltage_hbox,
            "discharge_current": self.discharge_current_hbox,
            "p_value": self.evaporator_p_value_hbox,
            "i_value": self.evaporator_i_value_hbox,
            "ep_percentage": self.ep_percentage_hbox,
        }
        # END - Widgets for component properties

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textarea = ipw.Textarea()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_textarea]
        )

        self.remove_action_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip="Remove action",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.name_textbox.observe(self.change_action_title, names="value")
        self.action_type_dropdown.observe(self.load_action_properties, names="value")
        self.component_dropdown.observe(
            self.load_component_settings_list, names="value"
        )
        self.substance_dropdown.observe(self.load_substance_mol_image, names="value")
        self.remove_action_button.on_click(self.remove_action)

        if action_settings:
            self.load_action(action_settings)

        self.children = [
            self.action_type_hbox,
            self.action_properties_widgets,
            self.remove_action_button,
        ]

    def load_substance_mol_image(self, change):
        substance_id = self.substance_dropdown.value
        if substance_id == "-1":
            self.substance_mol_image.value = b""
        else:
            substance_obj = utils.get_openbis_object(
                self.openbis_session, sample_ident=substance_id
            )
            substance_mols_ids = substance_obj.props["molecules"]
            if substance_mols_ids:
                mol_id = substance_mols_ids[0]
                molecule_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=mol_id
                )
                molecule_obj_datasets = molecule_obj.get_datasets(type="ELN_PREVIEW")
                molecule_obj_preview = molecule_obj_datasets[0]
                molecule_obj_preview.download(destination="images")
                object_image_filepath = molecule_obj_preview.file_list[0]
                self.substance_mol_image.value = utils.read_file(
                    f"images/{molecule_obj_preview.permId}/{object_image_filepath}"
                )

                # Erase file after downloading it
                shutil.rmtree(f"images/{molecule_obj_preview.permId}")

    def load_action(self, settings):
        action_permid = settings["action"]
        action_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=action_permid
        )
        action_props = action_object.props.all()
        action_type = action_object.type.code
        self.action_type_dropdown.value = action_type
        self.name_textbox.value = action_props["name"] or ""
        duration_str = action_props["duration"]

        # Split into days and time
        if "days" in duration_str:
            days_part, time_part = duration_str.split(" days ")
            self.duration_days_intbox.value = int(days_part)
        else:
            self.duration_days_intbox.value = 0
            time_part = duration_str

        # Split time into hours, minutes, seconds
        hours, minutes, seconds = map(int, time_part.split(":"))
        self.duration_hours_intbox.value = hours
        self.duration_minutes_intbox.value = minutes
        self.duration_seconds_intbox.value = seconds

        self.description_textbox.value = action_props.get("description", "") or ""
        self.sputter_ion_textbox.value = action_props.get("sputter_ion", "") or ""

        action_pressure = action_props.get("pressure", "")
        if action_pressure:
            action_pressure = json.loads(action_pressure)
            self.pressure_value_textbox.value = str(action_pressure["value"])
            self.pressure_unit_dropdown.value = action_pressure["unit"]

        action_current = action_props.get("current", "")
        if action_current:
            action_current = json.loads(action_current)
            self.current_value_textbox.value = str(action_current["value"])
            self.current_unit_dropdown.value = action_current["unit"]

        action_angle = action_props.get("angle", "")
        if action_angle:
            action_angle = json.loads(action_angle)
            self.angle_value_textbox.value = str(action_angle["value"])
            self.angle_unit_dropdown.value = action_angle["unit"]

        action_target_temperature = action_props.get("target_temperature", "")
        if action_target_temperature:
            action_target_temperature = json.loads(action_target_temperature)
            self.target_temperature_value_textbox.value = str(
                action_target_temperature["value"]
            )
            self.target_temperature_unit_dropdown.value = action_target_temperature[
                "unit"
            ]

        action_cryogen = action_props.get("cryogen", "")
        if action_cryogen:
            self.cryogen_textbox.value = action_cryogen

        action_substance = action_props.get("substance", "")
        if action_substance:
            self.substance_dropdown.value = action_substance

        component_permid = action_props.get("component", "")
        if component_permid:
            component_settings = action_props.get("component_settings", {})
            if component_settings:
                component_settings = json.loads(component_settings)
                self.component_dropdown.value = component_permid
                if "target_temperature" in component_settings:
                    self.target_temperature_value_comp_textbox.value = str(
                        component_settings["target_temperature"]["value"]
                    )
                    self.target_temperature_unit_comp_dropdown.value = (
                        component_settings["target_temperature"]["unit"]
                    )

                if "bias_voltage" in component_settings:
                    self.bias_voltage_value_textbox.value = str(
                        component_settings["bias_voltage"]["value"]
                    )
                    self.bias_voltage_unit_dropdown.value = component_settings[
                        "bias_voltage"
                    ]["unit"]

                if "discharge_voltage" in component_settings:
                    self.discharge_voltage_value_textbox.value = str(
                        component_settings["discharge_voltage"]["value"]
                    )
                    self.discharge_voltage_unit_dropdown.value = component_settings[
                        "discharge_voltage"
                    ]["unit"]

                if "discharge_current" in component_settings:
                    self.discharge_current_value_textbox.value = str(
                        component_settings["discharge_current"]["value"]
                    )
                    self.discharge_current_unit_dropdown.value = component_settings[
                        "discharge_current"
                    ]["unit"]

                self.evaporator_p_value_textbox.value = str(
                    component_settings.get("p_value", "")
                )
                self.evaporator_i_value_textbox.value = str(
                    component_settings.get("i_value", "")
                )
                self.ep_percentage_textbox.value = str(
                    component_settings.get("ep_percentage", "")
                )
            else:
                logging.info(f"No component settings found for action {action_permid}.")
        else:
            logging.info(f"No component associated with action {action_permid}.")

        action_substrate_temperature = action_props.get("substrate_temperature", "")
        if action_substrate_temperature:
            action_substrate_temperature = json.loads(action_substrate_temperature)
            self.substrate_temperature_value_textbox.value = str(
                action_substrate_temperature["value"]
            )
            self.substrate_temperature_unit_dropdown.value = (
                action_substrate_temperature["unit"]
            )

        self.comments_textarea.value = action_props["comments"] or ""

    def load_action_properties(self, change):
        action_type = self.action_type_dropdown.value
        if action_type == "-1":
            self.action_properties_widgets.children = []
        else:
            action_properties = [
                self.name_hbox,
                self.description_hbox,
                self.duration_hbox,
            ]

            if action_type == OPENBIS_OBJECT_TYPES["Annealing"]:
                action_properties.append(self.target_temperature_hbox)
                self.action_icon = "🔥"

            elif action_type == OPENBIS_OBJECT_TYPES["Cooldown"]:
                action_properties.append(self.target_temperature_hbox)
                action_properties.append(self.cryogen_hbox)
                self.action_icon = "❄️"

            elif action_type == OPENBIS_OBJECT_TYPES["Deposition"]:
                action_properties.append(self.substance_hbox)
                action_properties.append(self.substrate_temperature_hbox)
                self.action_icon = "🟫"

            elif action_type == OPENBIS_OBJECT_TYPES["Dosing"]:
                action_properties.append(self.substrate_temperature_hbox)
                action_properties.append(self.pressure_hbox)
                action_properties.append(self.gas_hbox)
                self.action_icon = "💧"

            elif action_type == OPENBIS_OBJECT_TYPES["Sputtering"]:
                action_properties.append(self.pressure_hbox)
                action_properties.append(self.current_hbox)
                action_properties.append(self.angle_hbox)
                action_properties.append(self.substrate_temperature_hbox)
                action_properties.append(self.sputter_ion_hbox)
                self.action_icon = "🔫"

            elif action_type == OPENBIS_OBJECT_TYPES["Coating"]:
                self.action_icon = "🧥"
            elif action_type == OPENBIS_OBJECT_TYPES["Delamination"]:
                self.action_icon = "🧩"
            elif action_type == OPENBIS_OBJECT_TYPES["Etching"]:
                self.action_icon = "📌"
            elif action_type == OPENBIS_OBJECT_TYPES["Fishing"]:
                self.action_icon = "🎣"
            elif action_type == OPENBIS_OBJECT_TYPES["Field Emission"]:
                self.action_icon = "⚡"
            elif action_type == OPENBIS_OBJECT_TYPES["Light Irradiation"]:
                self.action_icon = "💡"
            elif action_type == OPENBIS_OBJECT_TYPES["Mechanical Pressing"]:
                self.action_icon = "🔩"
            elif action_type == OPENBIS_OBJECT_TYPES["Rinse"]:
                self.action_icon = "🚿"

            action_properties.append(self.component_hbox)
            action_properties.append(self.component_settings_hbox)
            action_properties.append(self.comments_hbox)

            component_options = self.get_instrument_components(
                self.instrument_permid, action_type
            )
            component_options.insert(0, ("Select a component...", "-1"))
            self.component_dropdown.options = component_options
            self.component_dropdown.value = "-1"

            self.action_properties_widgets.children = action_properties

            self.actions_accordion.set_title(self.action_index, self.action_icon)

    def get_instrument_components(self, instrument_permid, action_type):
        component_list = []
        if instrument_permid != "-1":
            instrument_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=instrument_permid
            )
            instrument_type = instrument_object.type.code
            instrument_components_properties = (
                self.instrument_type_components_dictionary[instrument_type]
            )
            all_instrument_components = []
            for prop in instrument_components_properties:
                prop_value = instrument_object.props[prop]
                if prop_value:
                    for component_id in prop_value:
                        component_object = utils.get_openbis_object(
                            self.openbis_session, sample_ident=component_id
                        )
                        all_instrument_components.append(component_object)

                        # Evaporators contain sub-components (evaporator slots)
                        evaporator_type = OPENBIS_OBJECT_TYPES["Evaporator"]
                        if component_object.type == evaporator_type:
                            evaporator_slots = component_object.props[
                                "evaporator_slots"
                            ]
                            if evaporator_slots:
                                for evaporator_slot_id in evaporator_slots:
                                    evaporator_slot_object = utils.get_openbis_object(
                                        self.openbis_session,
                                        sample_ident=evaporator_slot_id,
                                    )
                                    all_instrument_components.append(
                                        evaporator_slot_object
                                    )

            for component_object in all_instrument_components:
                component_actions_settings_prop = component_object.props[
                    "actions_settings"
                ]
                if component_actions_settings_prop:
                    component_actions_settings = json.loads(
                        component_actions_settings_prop
                    )
                    for component_action_settings in component_actions_settings:
                        component_action_type = component_action_settings["action_type"]
                        if action_type == component_action_type:
                            component_list.append(
                                (
                                    component_object.props["name"],
                                    component_object.permId,
                                )
                            )
        return component_list

    def load_component_settings_list(self, change):
        action_type = self.action_type_dropdown.value
        if action_type != "-1":
            component_permid = self.component_dropdown.value
            if component_permid != "-1":
                component_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=component_permid
                )
                component_settings_property = component_object.props["actions_settings"]
                component_settings_widgets = []
                if component_settings_property:
                    component_settings = json.loads(component_settings_property)
                    for settings in component_settings:
                        if action_type == settings["action_type"]:
                            settings_properties = settings.get(
                                "component_properties", {}
                            )
                            for prop in settings_properties:
                                setting_widget = self.components_properties_widgets.get(
                                    prop, None
                                )
                                if setting_widget:
                                    if component_object.props[prop]:
                                        if prop == "target_temperature":
                                            target_temperature_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.target_temperature_value_comp_textbox.value = target_temperature_comp[
                                                "value"
                                            ]
                                            self.target_temperature_unit_comp_dropdown.value = target_temperature_comp[
                                                "unit"
                                            ]

                                        elif prop == "bias_voltage":
                                            bias_voltage_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.bias_voltage_value_textbox.value = (
                                                bias_voltage_comp["value"]
                                            )
                                            self.bias_voltage_unit_dropdown.value = (
                                                bias_voltage_comp["unit"]
                                            )

                                        elif prop == "discharge_voltage":
                                            discharge_voltage_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.discharge_voltage_value_textbox.value = discharge_voltage_comp[
                                                "value"
                                            ]
                                            self.discharge_voltage_unit_dropdown.value = discharge_voltage_comp[
                                                "unit"
                                            ]

                                        elif prop == "discharge_current":
                                            discharge_current_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.discharge_current_value_textbox.value = discharge_current_comp[
                                                "value"
                                            ]
                                            self.discharge_current_unit_dropdown.value = discharge_current_comp[
                                                "unit"
                                            ]

                                        elif prop == "p_value":
                                            self.evaporator_p_value_textbox.value = str(
                                                component_object.props[prop]
                                            )

                                        elif prop == "i_value":
                                            self.evaporator_i_value_textbox.value = str(
                                                component_object.props[prop]
                                            )

                                        elif prop == "ep_percentage":
                                            self.ep_percentage_textbox.value = str(
                                                component_object.props[prop]
                                            )

                                    component_settings_widgets.append(
                                        self.components_properties_widgets[prop]
                                    )
                self.component_settings_vbox.children = component_settings_widgets

    def change_action_title(self, change):
        title = self.name_textbox.value
        self.actions_accordion.set_title(
            self.action_index, f"{self.action_icon} {title}"
        )

    def remove_action(self, b):
        actions_accordion_children = list(self.actions_accordion.children)
        num_actions = len(actions_accordion_children)
        actions_accordion_children.pop(self.action_index)

        for index, action in enumerate(actions_accordion_children):
            if index >= self.action_index:
                action.action_index -= 1
                self.actions_accordion.set_title(
                    action.action_index, action.name_textbox.value
                )

        self.actions_accordion.set_title(num_actions - 1, "")
        self.actions_accordion.children = actions_accordion_children


class RegisterObservableWidget(ipw.VBox):
    def __init__(
        self,
        openbis_session,
        observables_accordion,
        observable_index,
        instrument_permid,
        observable_settings=None,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.observables_accordion = observables_accordion
        self.observable_index = observable_index
        self.instrument_permid = instrument_permid

        self.observable_type_label = ipw.Label(value="Observable type")
        observable_type_options = [
            (key, value) for key, value in OBSERVABLES_TYPES.items()
        ]
        observable_type_options.insert(0, ("Select an observable type...", "-1"))
        self.observable_type_dropdown = ipw.Dropdown(
            options=observable_type_options, value="-1"
        )

        self.observable_type_hbox = ipw.HBox(
            children=[self.observable_type_label, self.observable_type_dropdown]
        )
        self.observable_properties_widgets = ipw.VBox()

        self.name_label = ipw.Label(value="Name")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_textbox])

        self.description_label = ipw.Label(value="Description")
        self.description_textbox = ipw.Text()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_textbox]
        )

        self.ch_name_label = ipw.Label(value="Channel name")
        self.ch_name_textbox = ipw.Text()
        self.ch_name_hbox = ipw.HBox(
            children=[self.ch_name_label, self.ch_name_textbox]
        )

        self.instrument_type_components_dictionary = {
            OPENBIS_OBJECT_TYPES["Instrument STM"]: [
                "pumps",
                "gauges",
                "vacuum_chambers",
                "ports_valves",
                "preparation_tools",
                "analysers",
                "mechanical_components",
                "stm_components",
                "control_data_acquisition",
                "temperature_environment_control",
                "auxiliary_components",
                "tips_sensors",
                "accessories",
            ]
        }

        self.component_label = ipw.Label(value="Component")
        self.component_dropdown = ipw.Dropdown()
        self.component_hbox = ipw.HBox(
            children=[self.component_label, self.component_dropdown]
        )
        self.component_settings_label = ipw.Label(value="Component settings:")
        self.component_settings_vbox = ipw.VBox()
        self.component_settings_hbox = ipw.HBox(
            children=[self.component_settings_label, self.component_settings_vbox]
        )
        self.component_vbox = ipw.VBox(
            children=[self.component_hbox, self.component_settings_hbox]
        )

        # BEGIN - Widgets for component properties
        self.filament_label = ipw.Label("Filament")
        self.filament_textbox = ipw.Text()
        self.filament_hbox = ipw.HBox(
            children=[self.filament_label, self.filament_textbox]
        )

        self.filament_current_label = ipw.Label("Filament current")
        self.filament_current_value_textbox = ipw.Text()
        self.filament_current_unit_dropdown = ipw.Dropdown(
            options=["A", "mA"], value="A"
        )
        self.filament_current_hbox = ipw.HBox(
            children=[
                self.filament_current_label,
                self.filament_current_value_textbox,
                self.filament_current_unit_dropdown,
            ]
        )

        self.density_label = ipw.Label("Density")
        self.density_value_textbox = ipw.Text()
        self.density_unit_dropdown = ipw.Dropdown(
            options=["g/m3", "g/cm3"], value="g/m3"
        )
        self.density_hbox = ipw.HBox(
            children=[
                self.density_label,
                self.density_value_textbox,
                self.density_unit_dropdown,
            ]
        )
        # END

        self.components_properties_widgets = {
            "filament": self.filament_hbox,
            "filament_current": self.filament_current_hbox,
            "density": self.density_hbox,
        }

        self.comments_label = ipw.Label(value="Comments")
        self.comments_textarea = ipw.Textarea()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_textarea]
        )

        self.upload_readings_label = ipw.Label(value="Upload readings")
        self.upload_readings_widget = ipw.FileUpload(
            multiple=False, accept=".csv, .txt"
        )
        self.upload_readings_hbox = ipw.HBox(
            children=[self.upload_readings_label, self.upload_readings_widget]
        )

        self.plot_readings_widget = ipw.Output()

        self.remove_observable_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            tooltip="Remove observable",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.name_textbox.observe(self.change_observable_title, names="value")
        self.observable_type_dropdown.observe(
            self.load_observable_properties, names="value"
        )
        self.component_dropdown.observe(
            self.load_component_settings_list, names="value"
        )
        self.upload_readings_widget.observe(self.plot_readings, names="value")
        self.remove_observable_button.on_click(self.remove_observable)

        if observable_settings:
            self.load_observable(observable_settings)

        self.children = [
            self.observable_type_hbox,
            self.observable_properties_widgets,
            self.remove_observable_button,
        ]

    def load_observable(self, settings):
        observable_permid = settings["observable"]
        observable_object = utils.get_openbis_object(
            self.openbis_session, sample_ident=observable_permid
        )
        observable_props = observable_object.props.all()
        observable_type = observable_object.type.code
        self.observable_type_dropdown.value = observable_type
        self.name_textbox.value = observable_props["name"] or ""
        self.description_textbox.value = observable_props["description"] or ""
        self.ch_name_textbox.value = observable_props["channel_name"] or ""
        self.comments_textarea.value = observable_props["comments"] or ""

        component_permid = observable_props.get("component", {})
        if component_permid:
            component_settings = observable_props.get("component_settings", {})
            if component_settings:
                component_settings = json.loads(component_settings)
                self.component_dropdown.value = component_permid
                if "density" in component_settings:
                    self.density_value_textbox.value = str(
                        component_settings["density"]["value"]
                    )
                    self.density_unit_dropdown.value = component_settings["density"][
                        "unit"
                    ]
                if "filament_current" in component_settings:
                    self.filament_current_value_textbox.value = str(
                        component_settings["filament_current"]["value"]
                    )
                    self.filament_current_unit_dropdown.value = component_settings[
                        "filament_current"
                    ]["unit"]

                self.filament_textbox.value = str(
                    component_settings.get("filament", "")
                )
            else:
                logging.info(
                    f"No component settings found for observable {observable_permid}."
                )
        else:
            logging.info(
                f"No component associated with observable {observable_permid}."
            )

    def load_observable_properties(self, change):
        observable_type = self.observable_type_dropdown.value
        if observable_type == "-1":
            self.observable_properties_widgets.children = []
        else:
            observable_properties = [
                self.name_hbox,
                self.description_hbox,
                self.ch_name_hbox,
                self.component_hbox,
                self.component_settings_hbox,
                self.comments_hbox,
                self.upload_readings_hbox,
                self.plot_readings_widget,
            ]

            component_options = self.get_instrument_components(
                self.instrument_permid, observable_type
            )
            component_options.insert(0, ("Select a component...", "-1"))
            self.component_dropdown.options = component_options
            self.component_dropdown.value = "-1"

            self.observable_properties_widgets.children = observable_properties

            if observable_type == OPENBIS_OBJECT_TYPES["Current"]:
                self.observable_icon = "⚡"
            elif observable_type == OPENBIS_OBJECT_TYPES["Elemental Composition"]:
                self.observable_icon = "⚛️"
            elif observable_type == OPENBIS_OBJECT_TYPES["Pressure"]:
                self.observable_icon = "Ψ"
            elif observable_type == OPENBIS_OBJECT_TYPES["Voltage"]:
                self.observable_icon = "🔌"
            elif observable_type == OPENBIS_OBJECT_TYPES["Temperature"]:
                self.observable_icon = "🌡️"
            elif observable_type == OPENBIS_OBJECT_TYPES["Resistance"]:
                self.observable_icon = "⛔"
            elif observable_type == OPENBIS_OBJECT_TYPES["Inductance"]:
                self.observable_icon = "🌀"
            elif observable_type == OPENBIS_OBJECT_TYPES["pH Value"]:
                self.observable_icon = "🧪"
            elif observable_type == OPENBIS_OBJECT_TYPES["Speed"]:
                self.observable_icon = "💨"
            elif observable_type == OPENBIS_OBJECT_TYPES["Force"]:
                self.observable_icon = "💪"
            elif observable_type == OPENBIS_OBJECT_TYPES["Flux"]:
                self.observable_icon = "🌊"
            elif observable_type == OPENBIS_OBJECT_TYPES["Observable"]:
                self.observable_icon = "📏"

            self.observables_accordion.set_title(
                self.observable_index, self.observable_icon
            )

    def get_instrument_components(self, instrument_permid, observable_type):
        component_list = []
        if instrument_permid != "-1":
            instrument_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=instrument_permid
            )
            instrument_type = str(instrument_object.type)
            instrument_components_properties = (
                self.instrument_type_components_dictionary[instrument_type]
            )
            all_instrument_components = []
            for prop in instrument_components_properties:
                prop_value = instrument_object.props[prop]
                if prop_value:
                    for component_id in prop_value:
                        component_object = utils.get_openbis_object(
                            self.openbis_session, sample_ident=component_id
                        )
                        all_instrument_components.append(component_object)

                        # Evaporators contain sub-components (evaporator slots)
                        evaporator_type = OPENBIS_OBJECT_TYPES["Evaporator"]
                        if component_object.type == evaporator_type:
                            evaporator_slots = component_object.props[
                                "evaporator_slots"
                            ]
                            if evaporator_slots:
                                for evaporator_slot_id in evaporator_slots:
                                    evaporator_slot_object = utils.get_openbis_object(
                                        self.openbis_session,
                                        sample_ident=evaporator_slot_id,
                                    )
                                    all_instrument_components.append(
                                        evaporator_slot_object
                                    )

            for component_object in all_instrument_components:
                component_observables_settings_prop = component_object.props[
                    "observables_settings"
                ]
                if component_observables_settings_prop:
                    component_observables_settings = json.loads(
                        component_observables_settings_prop
                    )
                    for component_observable_settings in component_observables_settings:
                        component_observable_type = component_observable_settings[
                            "observable_type"
                        ]
                        if observable_type == component_observable_type:
                            component_list.append(
                                (
                                    component_object.props["name"],
                                    component_object.permId,
                                )
                            )

        return component_list

    def load_component_settings_list(self, change):
        observable_type = self.observable_type_dropdown.value
        if observable_type != "-1":
            component_permid = self.component_dropdown.value
            if component_permid != "-1":
                component_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=component_permid
                )
                component_settings_property = component_object.props[
                    "observables_settings"
                ]
                component_settings_widgets = []
                if component_settings_property:
                    component_settings = json.loads(component_settings_property)
                    for settings in component_settings:
                        if observable_type == settings["observable_type"]:
                            settings_properties = settings.get(
                                "component_properties", {}
                            )
                            for prop in settings_properties:
                                setting_widget = self.components_properties_widgets.get(
                                    prop, None
                                )
                                if setting_widget:
                                    if component_object.props[prop]:
                                        if prop == "density":
                                            density_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.density_value_textbox.value = (
                                                density_comp["value"]
                                            )
                                            self.density_unit_dropdown.value = (
                                                density_comp["unit"]
                                            )

                                        elif prop == "filament_current":
                                            filament_current_comp = json.loads(
                                                component_object.props[prop]
                                            )
                                            self.filament_current_value_textbox.value = filament_current_comp[
                                                "value"
                                            ]
                                            self.filament_current_unit_dropdown.value = filament_current_comp[
                                                "unit"
                                            ]

                                        elif prop == "filament":
                                            self.filament_textbox.value = (
                                                component_object.props[prop]
                                            )

                                    component_settings_widgets.append(
                                        self.components_properties_widgets[prop]
                                    )

                self.component_settings_vbox.children = component_settings_widgets

    def change_observable_title(self, change):
        title = self.name_textbox.value
        self.observables_accordion.set_title(
            self.observable_index, f"{self.observable_icon} {title}"
        )

    def remove_observable(self, b):
        observables_accordion_children = list(self.observables_accordion.children)
        num_observables = len(observables_accordion_children)
        observables_accordion_children.pop(self.observable_index)

        for index, observable in enumerate(observables_accordion_children):
            if index >= self.observable_index:
                observable.observable_index -= 1
                self.observables_accordion.set_title(
                    observable.observable_index, observable.name_textbox.value
                )

        self.observables_accordion.set_title(num_observables - 1, "")
        self.observables_accordion.children = observables_accordion_children

    def plot_readings(self, change):
        # Create structures directory if it does not exist
        for filename in self.upload_readings_widget.value:
            file_info = self.upload_readings_widget.value[filename]
            content = file_info["content"].decode("utf-8")
            try:
                df = pd.read_csv(io.StringIO(content), sep=",")

                if df.shape[1] < 2:
                    raise ValueError("Dataframe has less than 2 columns.")

                self.plot_readings_widget.clear_output()
                with self.plot_readings_widget:
                    plt.figure(figsize=(6, 4))
                    plt.plot(df.iloc[:, 0], df.iloc[:, 1])
                    plt.xlabel(df.columns[0])
                    plt.ylabel(df.columns[1])
                    plt.grid(True)
                    plt.show()

            except Exception:
                display(Javascript(data="alert('Data cannot be plotted!')"))
