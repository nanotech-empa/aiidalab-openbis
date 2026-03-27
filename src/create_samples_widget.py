import ipywidgets as ipw
from . import utils
import os
import json
import pandas as pd
import logging
from IPython.display import display, Javascript

INTERFACE_CONFIG_INFO = utils.get_interface_config_info()
OPENBIS_OBJECT_TYPES, _ = (
    INTERFACE_CONFIG_INFO["object_types"],
    INTERFACE_CONFIG_INFO["object_types_codes"],
)
MATERIALS_TYPES = INTERFACE_CONFIG_INFO["slabs_types"]
OPENBIS_COLLECTIONS_PATHS = utils.read_json("metadata/collection_paths.json")

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

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.select_material_title = ipw.HTML(
            f"<div style='{header_style}'>Select material</div>"
        )
        self.sample_name_title = ipw.HTML(
            f"<div style='{header_style}'>Sample name</div>"
        )

        material_type_options = [(key, value) for key, value in MATERIALS_TYPES.items()]
        material_type_options.insert(0, ("Select material type...", "-1"))

        self.material_type_dropdown = ipw.Dropdown(
            options=material_type_options, value=material_type_options[0][1]
        )

        self.material_details_vbox = ipw.VBox()
        self.sample_name_textbox = ipw.Text(placeholder="Write sample name...")

        self.create_sample_notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Getting Started: Creating a New Sample
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <div style="color: #34495e; font-size: 14px; margin-bottom: 12px;">
                        Before you can record any preparation steps, you must physically "register" your starting sample in the system here.
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
                        <li style="margin-bottom: 6px;"><b>Select material:</b> Choose the base material type you are starting with.</li>
                        <li style="margin-bottom: 6px;"><b>Sample name:</b> Provide a descriptive name for your sample (this can be edited later if needed).</li>
                        <li><b>Save (💾):</b> Registers the new sample in openBIS, making it available in the <i>Register preparation</i> tab.</li>
                    </ul>

                    <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; border-radius: 3px; font-size: 14px; color: #856404;">
                        ⚠️ <b>Important Rule regarding Materials:</b><br>
                        If you start a new sample using a material that already has an active sample in openBIS, the older sample will automatically become <b>Inactive</b>. This reflects reality: if you are starting fresh with a specific material piece, its previous tracked state no longer exists!
                    </div>
                </div>
            </details>
            """
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
            self.create_sample_notes,
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

                            if prop_datatype == "CONTROLLEDVOCABULARY":
                                if isinstance(value, list):
                                    value = [
                                        v.lower().replace("_", " ").title()
                                        for v in value
                                    ]
                                    value = ", ".join(value)
                                else:
                                    value = value.lower().replace("_", " ").title()

                            elif prop_datatype == "SAMPLE":
                                if isinstance(value, list):
                                    prop_obj_names = []
                                    for id in value:
                                        prop_obj = utils.get_openbis_object(
                                            self.openbis_session, sample_ident=id
                                        )
                                        prop_obj_props = prop_obj.props.all()
                                        prop_obj_name = (
                                            prop_obj_props.get("name", "") or ""
                                        )
                                        prop_obj_names.append(prop_obj_name)
                                    value = ", ".join(prop_obj_names)
                                else:
                                    prop_obj = utils.get_openbis_object(
                                        self.openbis_session, sample_ident=value
                                    )
                                    prop_obj_props = prop_obj.props.all()
                                    value = prop_obj_props.get("name", "") or ""

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

                    for parent_id in obj.parents:
                        parent = utils.get_openbis_object(
                            self.openbis_session, sample_ident=parent_id
                        )
                        parent_type = parent.type.code.lower().replace("_", " ").title()
                        parent_props = parent.props.all()
                        parent_name = parent_props.get("name", "") or ""
                        obj_details_string += (
                            f"<p><b>Parent {parent_type}:</b> {parent_name}</p>"
                        )

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
