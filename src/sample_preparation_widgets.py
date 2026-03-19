import re
import ipywidgets as ipw
from . import utils, widgets
from IPython.display import display, Javascript
from collections import Counter, defaultdict
import shutil
import base64
import time
import threading
import os
import logging
import custom_widgets as cw

OBSERVABLES_TYPES = utils.read_json("metadata/observables_types.json")
ACTIONS_TYPES = utils.read_json("metadata/actions_types.json")
ACTIONS_CODES = utils.read_json("metadata/actions_codes.json")
OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")
MATERIALS_TYPES = utils.read_json("metadata/materials_types.json")
OPENBIS_OBJECT_CODES = utils.read_json("metadata/object_codes.json")
OPENBIS_COLLECTIONS_PATHS = utils.read_json("metadata/collection_paths.json")
INSTRUMENT_COMPONENTS = None

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

        self.name_label = ipw.HTML(value="<b>Name:</b>")
        self.name_html = ipw.HTML()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_html])

        self.description_label = ipw.HTML(value="<b>Description:</b>")
        self.description_html = ipw.HTML()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_html]
        )

        self.comments_label = ipw.HTML(value="<b>Comments:</b>")
        self.comments_html = ipw.HTML()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_html]
        )

        self.instrument_label = ipw.HTML(value="<b>Instrument:</b>")
        self.instrument_html = ipw.HTML()
        self.instrument_hbox = ipw.HBox(
            children=[self.instrument_label, self.instrument_html]
        )

        self.actions_label = ipw.HTML(value="<b>Actions:</b>")
        self.actions_accordion = ipw.Accordion()
        self.actions_vbox = ipw.VBox(
            children=[self.actions_label, self.actions_accordion]
        )

        self.observables_label = ipw.HTML(value="<b>Observables:</b>")
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

        instruments_codes = [
            OPENBIS_OBJECT_CODES["Instrument"],
            OPENBIS_OBJECT_CODES["Instrument STM"],
        ]
        openbis_object_parents = self.openbis_object.parents
        for parent in openbis_object_parents:
            parent_code = parent.split("/")[-1]
            if parent_code[0:4] in instruments_codes:
                instrument_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )
                self.instrument_html.value = instrument_object.props["name"]
                break

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
                act_title = act_widget.name
                self.actions_accordion.set_title(i, act_title)

            self.actions_accordion.children = actions_accordion_children

    def load_observables(self):
        observables_ids = self.openbis_object.get_datasets(
            type="OBSERVABLE"
        ).df.permId.values
        if observables_ids:
            observables_accordion_children = []
            for i, obs_id in enumerate(observables_ids):
                obs_dataset = utils.get_openbis_dataset(self.openbis_session, obs_id)
                obs_widget = ObservableHistoryWidget(self.openbis_session, obs_dataset)
                observables_accordion_children.append(obs_widget)
                obs_title = obs_widget.name_html.value
                self.observables_accordion.set_title(i, obs_title)

            self.observables_accordion.children = observables_accordion_children


class ActionHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session, openbis_object):
        super().__init__()
        self.openbis_session = openbis_session
        self.openbis_object = openbis_object
        self.object_type = str(self.openbis_object.type)
        icon_mapping = {
            OPENBIS_OBJECT_TYPES.get("Annealing"): "🔥",
            OPENBIS_OBJECT_TYPES.get("Cooldown"): "❄️",
            OPENBIS_OBJECT_TYPES.get("Deposition"): "🟫",
            OPENBIS_OBJECT_TYPES.get("Dosing"): "💧",
            OPENBIS_OBJECT_TYPES.get("Sputtering"): "🔫",
            OPENBIS_OBJECT_TYPES.get("Coating"): "🧥",
            OPENBIS_OBJECT_TYPES.get("Delamination"): "🧩",
            OPENBIS_OBJECT_TYPES.get("Etching"): "📌",
            OPENBIS_OBJECT_TYPES.get("Fishing"): "🎣",
            OPENBIS_OBJECT_TYPES.get("Field Emission"): "⚡",
            OPENBIS_OBJECT_TYPES.get("Light Irradiation"): "💡",
            OPENBIS_OBJECT_TYPES.get("Mechanical Pressing"): "🔩",
            OPENBIS_OBJECT_TYPES.get("Rinse"): "🚿",
        }
        self.action_icon = icon_mapping.get(self.object_type, "")
        self.name = self.openbis_object.props["name"] or ""
        self.children = self.load_action_data()

    def load_action_data(self):
        props = self.openbis_object.props.all()
        props_widgets = []
        components_html_content = ""

        # Helper function to stop repeating widget layout code
        def make_row(label, val, prop_name):
            lbl = ipw.HTML(value=f"<b>{label}:</b>", layout=ipw.Layout(width="100px"))
            html = ipw.HTML(value=str(val))
            return cw.HBox(children=[lbl, html], metadata={"property_name": prop_name})

        # ONE unified loop for everything
        for prop_key, prop_val in props.items():
            if not prop_val or str(prop_key).endswith("_settings"):
                continue  # Skip empty values and raw settings IDs

            try:
                prop_type = utils.get_openbis_property_type(
                    self.openbis_session, code=prop_key
                )
                prop_label = prop_type.label
                prop_dataType = prop_type.dataType
                prop_sampleType = prop_type.sampleType
            except Exception:
                continue  # Skip if property type data isn't found

            # 1. Standard Fields
            if prop_dataType in [
                "VARCHAR",
                "MULTILINE_VARCHAR",
                "INTEGER",
                "FLOAT",
                "BOOLEAN",
            ]:
                props_widgets.append(make_row(prop_label, prop_val, prop_key))

            # 2. Gas Bottle
            elif prop_sampleType == "GAS_BOTTLE":
                gas_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=prop_val
                )
                gas_name = gas_obj.props.get("name", "") if gas_obj else ""
                props_widgets.append(make_row(prop_label, gas_name, prop_key))

            # 3. Substance & Image logic
            elif prop_sampleType == "SUBSTANCE":
                sub_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=prop_val
                )
                empa = sub_obj.props["empa_number"]
                batch = sub_obj.props["batch"]
                vial = sub_obj.props["vial"]

                sub_text = f"Identifier: {empa}{batch}" + (f"-{vial}" if vial else "")

                # Iterate parents directly to find ALL molecules
                molecule_images_html = ""
                for parent_id in sub_obj.parents:
                    parent_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=parent_id
                    )

                    if parent_obj.type.code == "MOLECULE":
                        datasets = parent_obj.get_datasets(type="ELN_PREVIEW")

                        if datasets and datasets[0].file_list:
                            preview_ds = datasets[0]
                            preview_ds.download(destination="images")
                            dataset_folder = os.path.join("images", preview_ds.permId)
                            img_path = os.path.join(
                                dataset_folder, preview_ds.file_list[0]
                            )

                            try:
                                html_image = utils.read_file(img_path)
                                image_encoded = base64.b64encode(html_image).decode(
                                    "utf-8"
                                )
                                # Add each image to our gallery string with a little margin and a subtle border
                                molecule_images_html += f"""
                                <img src="data:image/png;base64,{image_encoded}" width="100"
                                     style="margin-right: 10px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 4px; padding: 2px; background-color: white;">
                                """
                            finally:
                                if os.path.exists(dataset_folder):
                                    shutil.rmtree(dataset_folder, ignore_errors=True)

                # If we found any images, append them to the text using a flexbox container
                if molecule_images_html:
                    sub_text += f"""
                    <div style="margin-top: 10px;">Molecule sketches:</div>
                    <div style="display: flex; flex-wrap: wrap; margin-top: 5px;">
                        {molecule_images_html}
                    </div>
                    """

                props_widgets.append(make_row(prop_label, sub_text, prop_key))

            # 4. Components & Settings HTML block
            elif (
                prop_sampleType in OPENBIS_OBJECT_TYPES.values()
                and f"{prop_sampleType}_SETTINGS" in OPENBIS_OBJECT_TYPES.values()
            ):
                comp_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=prop_val
                )
                comp_name = comp_obj.props["name"]

                # Fixed missing opening <div> here
                components_html_content += (
                    f"<div style='margin-bottom: 10px;'>⚙️ {comp_name}"
                )

                settings_id = props.get(f"{prop_key}_settings")
                if settings_id:
                    s_obj = utils.get_openbis_object(
                        self.openbis_session, sample_ident=settings_id
                    )
                    s_props = s_obj.props()
                    s_props.pop("name", None)

                    if s_props:
                        components_html_content += (
                            "<ul style='margin-top: 0; padding-left: 20px;'>"
                        )
                        for s_key, s_val in s_props.items():
                            if not s_val:
                                continue
                            try:
                                s_label = utils.get_openbis_property_type(
                                    self.openbis_session, code=s_key
                                ).label
                            except ValueError:
                                s_label = s_key
                            components_html_content += f"<li>{s_label}: {s_val}</li>"
                        components_html_content += "</ul>"
                    else:
                        components_html_content += "<div style='font-style: italic; margin-left: 20px;'>No settings values defined.</div>"
                else:
                    components_html_content += "<div style='font-style: italic; margin-left: 20px;'>No settings attached.</div>"

                components_html_content += "</div>"  # Properly closes the block

        # Append the final compiled Components HTML string at the bottom
        if not components_html_content:
            components_html_content = (
                "<div style='font-style: italic;'>No components used.</div>"
            )

        props_widgets.append(
            make_row("Components", components_html_content, "components")
        )

        return props_widgets


class ObservableHistoryWidget(ipw.VBox):
    def __init__(self, openbis_session, openbis_dataset):
        super().__init__()
        self.openbis_session = openbis_session
        self.openbis_dataset = openbis_dataset

        self.name_label = ipw.HTML(value="<b>Name:</b>")
        self.name_html = ipw.HTML()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_html])

        self.description_label = ipw.HTML(value="<b>Description:</b>")
        self.description_html = ipw.HTML()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_html]
        )

        self.components_label = ipw.HTML(value="<b>Components:</b>")
        self.components_html = ipw.HTML()
        self.components_hbox = ipw.HBox(
            children=[self.components_label, self.components_html]
        )

        self.download_button = ipw.Button(
            button_style="",
            icon="download",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        self.download_button.on_click(self.download_files)

        self.load_observable_data()

        self.children = [
            self.name_hbox,
            self.description_hbox,
            self.components_hbox,
            self.download_button,
        ]

    def load_observable_data(self):
        openbis_dataset_props = self.openbis_dataset.props.all()
        if openbis_dataset_props["name"]:
            self.name_html.value = openbis_dataset_props["name"]

        if openbis_dataset_props["description"]:
            self.description_html.value = openbis_dataset_props["description"]

        components_ids = openbis_dataset_props["components"]

        if components_ids:
            for component_id in components_ids:
                component_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=component_id
                )
                self.components_html.value += f"<p>{component_object.props['name']}</p>"

    def delayed_cleanup(self, folder_path, zip_filepath, delay_seconds=60):
        """Waits in the background, then deletes the temporary files."""
        time.sleep(delay_seconds)
        try:
            # Remove the unzipped folder
            if os.path.exists(folder_path):
                shutil.rmtree(folder_path)

            # Remove the zip file
            if os.path.exists(zip_filepath):
                os.remove(zip_filepath)

        except Exception as e:
            print(f"Cleanup error: {e}")

    def download_files(self, b):
        try:
            # 1. Define temporary paths
            temp_dir = "./temp_dataset_download"
            os.makedirs(temp_dir, exist_ok=True)

            # 2. Download from openBIS
            self.openbis_dataset.download(destination=temp_dir)

            # 3. Zip it up
            zip_name = f"dataset_{self.openbis_dataset.permId}"
            shutil.make_archive(zip_name, "zip", temp_dir)
            zip_filename = f"{zip_name}.zip"

            # 4. Trigger the browser download
            js_code = f"""
            var link = document.createElement('a');
            link.href = '{zip_filename}';
            link.download = '{zip_filename}';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            """
            display(Javascript(js_code))

            # 5. Start the background cleanup process
            # This runs silently in the background without freezing your notebook
            cleanup_thread = threading.Thread(
                target=self.delayed_cleanup,
                args=(temp_dir, zip_filename, 60),  # 60 seconds delay
            )
            cleanup_thread.start()

        except Exception as e:
            print(f"❌ Error: {e}")


class RegisterPreparationWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session
        self.sample_preparation_object = None

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.select_experiment_title = ipw.HTML(
            f"<div style='{header_style}'>Select experiment</div>"
        )
        self.select_sample_title = ipw.HTML(
            f"<div style='{header_style}'>Select sample</div>"
        )
        self.sample_history_title = ipw.HTML(
            f"<div style='{header_style}'>Sample history</div>"
        )
        self.new_processes_title = ipw.HTML(
            f"<div style='{header_style}'>Register new steps</div>"
        )

        self.notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Understanding the Workflow & UI
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
                        <li><span style="color: #2980b9; font-weight: bold;">Process steps</span> happen <b>sequentially</b> (one after the other).</li>
                        <li><span style="color: #d35400; font-weight: bold;">Actions</span> within a step happen <b>simultaneously</b> (all at the exact same time).</li>
                        <li><span style="color: #27ae60; font-weight: bold;">Observables</span> are <b>datasets</b> attached to a specific process step.</li>
                    </ul>

                    <div style="font-weight: bold; font-size: 14px; color: #2c3e50; margin-bottom: 8px;">
                        Getting Started:
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5;">
                        <li style="margin-bottom: 6px;">
                            <b>Select experiment:</b> Determines where the preparation is going to be saved in openBIS.
                            <i>(Note: This auto-fills when you select a sample, but if the experiment does not exist, you can create one by clicking the <b>+</b> button).</i>
                        </li>
                        <li style="margin-bottom: 6px;"><b>Select sample:</b> Choose a sample created in the <i>Create sample</i> tab.</li>
                        <li style="margin-bottom: 6px;"><b>Sample history:</b> Displays what was already done on the sample.</li>
                        <li style="margin-bottom: 6px;"><b>Load process:</b> Use a template process step (or set of steps) that was previously defined using the <i>Register process</i> tab.</li>
                        <li style="margin-bottom: 6px;"><b>Add process step:</b> Construct the different processes performed on the sample from scratch.</li>
                        <li><b>Save (💾):</b> Saves the newly registered history and resets the interface for the next task.</li>
                    </ul>
                </div>
            </details>
            """
        )

        self.process_short_name = ""

        self.select_experiment_dropdown = widgets.SelectExperimentWidget(
            self.openbis_session
        )
        self.select_sample_dropdown = widgets.SelectSampleWidget(self.openbis_session)
        self.sample_history_vbox = SampleHistoryWidget(self.openbis_session)
        self.new_processes_accordion = ipw.Accordion()

        self.load_process_button = ipw.Button(
            description="Load process", button_style="info", icon="folder-open"
        )
        self.add_process_step_button = ipw.Button(
            description="Add process step", button_style="success", icon="plus"
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

        # Save button (make it wide enough to match, and give it a clear style)
        self.save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        # Put the form actions in one row, and separate the save button with a little margin
        button_row = ipw.HBox(
            [self.load_process_button, self.add_process_step_button],
            layout=ipw.Layout(margin="10px 0px"),
        )
        save_row = ipw.HBox(
            [self.save_button], layout=ipw.Layout(margin="20px 0px 0px 0px")
        )

        self.children = [
            self.notes,
            self.select_experiment_title,
            self.select_experiment_dropdown,
            self.select_sample_title,
            self.select_sample_dropdown,
            self.sample_history_title,
            self.sample_history_vbox,
            self.new_processes_title,
            self.load_processes_hbox,
            self.new_processes_accordion,
            button_row,
            save_row,
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

        self.sample_preparation_object = None
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
        processes_options = [
            (obj.props["name"], obj.permId) for obj in openbis_processes
        ]
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
            process_step_list = process_object.props["process_steps"]
            self.process_short_name = process_object.props["short_name"] or ""
            if process_step_list:
                for process_step_id in process_step_list:
                    process_step = utils.get_openbis_object(
                        self.openbis_session, sample_ident=process_step_id
                    )
                    processes_accordion_children = list(
                        self.new_processes_accordion.children
                    )
                    process_step_index = len(processes_accordion_children)
                    new_process_step_widget = RegisterProcessStepWidget(
                        self.openbis_session,
                        self.new_processes_accordion,
                        process_step_index,
                        process_step=process_step,
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
                self.process_buttons_hbox,
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

        settings_collection = utils.get_openbis_collection(
            self.openbis_session, OPENBIS_COLLECTIONS_PATHS["Settings"]
        )

        process_steps_widgets = self.new_processes_accordion.children

        if process_steps_widgets:
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
            for process_widget in process_steps_widgets:
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
                    "comments": process_widget.comments_textarea.value,
                }

                actions_widgets = process_widget.actions_accordion.children
                observables_widgets = process_widget.observables_accordion.children
                actions = []
                actions_codes = []
                process_step_icons = []

                if actions_widgets:
                    for action_widget in actions_widgets:
                        action_properties_values = {}
                        action_type = action_widget.action_type_dropdown.value
                        action_properties_widgets = (
                            action_widget.action_properties_widgets.children
                        )

                        if action_type == "-1":
                            continue

                        action_properties = (
                            utils.get_openbis_object_type(
                                self.openbis_session, type=action_type
                            )
                            .get_property_assignments()
                            .df.code.values
                        )

                        components_found = False
                        for prop in action_properties:
                            prop_type = utils.get_openbis_property_type(
                                self.openbis_session, code=prop
                            )
                            prop_dataType = str(prop_type.dataType)
                            prop_lower = prop.lower()

                            for widget in action_properties_widgets:
                                if "property_name" in widget.metadata:
                                    if widget.metadata["property_name"] == prop:
                                        if prop == "DURATION":
                                            duration_days = widget.children[1].value
                                            duration_hours = widget.children[3].value
                                            duration_minutes = widget.children[5].value
                                            duration_seconds = widget.children[7].value
                                            duration = f"{duration_days} days {duration_hours:02}:{duration_minutes:02}:{duration_seconds:02}"

                                            action_properties_values[prop_lower] = (
                                                duration
                                            )

                                        elif prop_dataType in ["SAMPLE", "OBJECT"]:
                                            selected_value = widget.children[1].value
                                            if selected_value != "-1":
                                                action_properties_values[prop_lower] = (
                                                    selected_value
                                                )

                                        else:
                                            action_properties_values[prop_lower] = (
                                                widget.children[1].value
                                            )

                                        break

                                    elif (
                                        not components_found
                                        and f"{prop}_SETTINGS" in action_properties
                                        and prop_dataType in ["SAMPLE", "OBJECT"]
                                        and widget.metadata["property_name"]
                                        == "COMPONENTS"
                                    ):
                                        # This part of the code finds all components and settings used in the current action
                                        for component_widget in widget.children:
                                            component_name = (
                                                component_widget.metadata.get(
                                                    "component_name"
                                                )
                                            )
                                            component_type = (
                                                component_widget.metadata.get(
                                                    "component_type"
                                                )
                                            )
                                            component_settings_type = (
                                                f"{component_type}_SETTINGS"
                                            )
                                            component_settings_type_lower = (
                                                component_settings_type.lower()
                                            )
                                            component_permid = (
                                                component_widget.children[
                                                    0
                                                ].metadata.get("object_id")
                                            )
                                            component_settings_permid = (
                                                component_widget.children[1]
                                                .children[1]
                                                .value
                                            )
                                            component_type_lower = (
                                                component_type.lower()
                                            )
                                            action_properties_values[
                                                component_type_lower
                                            ] = component_permid
                                            if component_settings_permid != "-1":
                                                action_properties_values[
                                                    component_settings_type_lower
                                                ] = component_settings_permid
                                            else:
                                                component_settings_properties_values = {}
                                                component_settings_name = (
                                                    f"{component_name} with "
                                                )
                                                for (
                                                    setting_widget
                                                ) in component_widget.children[
                                                    2
                                                ].children:
                                                    setting_prop_type = (
                                                        setting_widget.metadata.get(
                                                            "property_name"
                                                        )
                                                    )
                                                    setting_prop_label = (
                                                        setting_widget.children[0]
                                                        .value.removeprefix("<b>")
                                                        .removesuffix("</b>")
                                                        .removesuffix(":")
                                                    )
                                                    setting_prop_value = (
                                                        setting_widget.children[1].value
                                                    )
                                                    setting_prop_type_lower = (
                                                        setting_prop_type.lower()
                                                    )
                                                    component_settings_properties_values[
                                                        setting_prop_type_lower
                                                    ] = setting_prop_value
                                                    component_settings_name += f"{setting_prop_label}: {setting_prop_value}, "

                                                component_settings_name = (
                                                    component_settings_name.rstrip(", ")
                                                )
                                                component_settings_properties_values[
                                                    "name"
                                                ] = component_settings_name

                                                new_component_settings = utils.create_openbis_object(
                                                    self.openbis_session,
                                                    type=component_settings_type,
                                                    experiment=settings_collection.permId,
                                                    props=component_settings_properties_values,
                                                    parents=[component_permid],
                                                )

                                                component_settings_permid = (
                                                    new_component_settings.permId
                                                )

                                                action_properties_values[
                                                    component_settings_type_lower
                                                ] = component_settings_permid

                                            component_object = utils.get_openbis_object(
                                                self.openbis_session,
                                                sample_ident=component_permid,
                                            )

                                            component_settings_object = utils.get_openbis_object(
                                                self.openbis_session,
                                                sample_ident=component_settings_permid,
                                            )
                                            component_settings_props = (
                                                component_settings_object.props()
                                            )

                                            for (
                                                prop_key,
                                                prop_value,
                                            ) in component_settings_props.items():
                                                if prop_key in [
                                                    "name",
                                                    "description",
                                                    "comments",
                                                ]:
                                                    continue
                                                else:
                                                    prop_type = (
                                                        utils.get_openbis_property_type(
                                                            self.openbis_session,
                                                            code=prop_key,
                                                        )
                                                    )
                                                    prop_dataType = str(
                                                        prop_type.dataType
                                                    )
                                                    if prop_dataType == "INTEGER":
                                                        prop_value = int(prop_value)
                                                    elif prop_dataType == "REAL":
                                                        prop_value = float(prop_value)
                                                    component_object.props[prop_key] = (
                                                        prop_value
                                                    )

                                            utils.update_openbis_object(
                                                component_object
                                            )

                                        components_found = True
                                        break

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

                        process_step_icons.append(action_widget.action_icon)

                        if (
                            action_widget.action_icon
                            not in action_properties_values["name"]
                        ):
                            action_properties_values["name"] = (
                                action_widget.action_icon
                                + " "
                                + action_properties_values["name"]
                            )

                        new_action_object = utils.create_openbis_object(
                            self.openbis_session,
                            type=action_type,
                            experiment=f"{experiment_project_code}/{action_collection_code}",
                            props=action_properties_values,
                        )

                        new_action_code = str(new_action_object.code)
                        actions_codes.append(new_action_code[0:4])
                        actions.append(new_action_object.permId)

                process_properties["actions"] = actions

                if actions_codes:
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

                new_sample_name = f"{current_sample_name}:{process_code}"
                self.sample_preparation_object.props["name"] = (
                    f"Preparation of {new_sample_name}"
                )
                self.sample_preparation_object.add_children(new_process_object.permId)
                utils.update_openbis_object(self.sample_preparation_object)

                new_process_object_parents = [
                    self.sample_preparation_object,
                    current_sample,
                ]
                new_process_object.props = process_properties
                instrument_permid = process_widget.instrument_dropdown.value

                if instrument_permid != "-1":
                    new_process_object_parents.append(instrument_permid)

                new_process_object.props["name"] = (
                    f"[{''.join(process_step_icons)}] {new_process_object.props['name']}"
                )
                new_process_object.add_parents(new_process_object_parents)
                utils.update_openbis_object(new_process_object)

                # Get observable info and add them as datasets to the process step object
                if observables_widgets:
                    for observable_widget in observables_widgets:
                        observable_type = "OBSERVABLE"
                        observable_properties_widgets = (
                            observable_widget.observable_properties_widgets.children
                        )

                        observable_properties = (
                            utils.get_openbis_dataset_type(
                                self.openbis_session, type=observable_type
                            )
                            .get_property_assignments()
                            .df.code.values
                        )

                        observable_properties_values = {}
                        for prop in observable_properties:
                            prop_lower = prop.lower()
                            prop_type = utils.get_openbis_property_type(
                                self.openbis_session, code=prop
                            )
                            prop_dataType = str(prop_type.dataType)

                            for widget in observable_properties_widgets:
                                if "property_name" in widget.metadata:
                                    if widget.metadata["property_name"] == prop:
                                        widget_value = widget.children[1].value
                                        if widget_value:
                                            if isinstance(widget_value, tuple):
                                                widget_value = list(widget_value)
                                            observable_properties_values[prop_lower] = (
                                                widget_value
                                            )
                                        break

                        if "📈" not in observable_properties_values["name"]:
                            observable_properties_values["name"] = (
                                "📈 " + observable_properties_values["name"]
                            )

                        utils.upload_datasets(
                            self.openbis_session,
                            new_process_object,
                            observable_widget.upload_readings_widget,
                            props=observable_properties_values,
                            dataset_type="OBSERVABLE",
                        )

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


class RegisterProcessWidget(ipw.VBox):
    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session

        header_style = "font-weight: bold; font-size: 16px; color: #34495e; margin-bottom: 5px; border-bottom: 1px solid #ecf0f1; padding-bottom: 3px;"

        self.select_collection_title = ipw.HTML(
            f"<div style='{header_style}'>Select collection</div>"
        )
        self.process_properties_title = ipw.HTML(
            f"<div style='{header_style}'>Process properties</div>"
        )
        self.new_processes_title = ipw.HTML(
            f"<div style='{header_style}'>Register new steps</div>"
        )

        self.select_collection_label = ipw.HTML(value="<b>Collection:</b>")
        self.select_collection_dropdown = ipw.Dropdown()
        self.select_collection_hbox = ipw.HBox(
            [self.select_collection_label, self.select_collection_dropdown]
        )
        self.load_collections()

        self.process_name_label = ipw.HTML(value="<b>Name:</b>")
        self.process_name_text = ipw.Text()
        self.process_name_hbox = ipw.HBox(
            [self.process_name_label, self.process_name_text]
        )

        self.process_short_name_label = ipw.HTML(value="<b>Short name:</b>")
        self.process_short_name_text = ipw.Text()
        self.process_short_name_hbox = ipw.HBox(
            [self.process_short_name_label, self.process_short_name_text]
        )

        self.process_description_label = ipw.HTML(value="<b>Description:</b>")
        self.process_description_text = ipw.Textarea()
        self.process_description_hbox = ipw.HBox(
            [self.process_description_label, self.process_description_text]
        )

        self.new_processes_accordion = ipw.Accordion()

        self.add_process_step_button = ipw.Button(
            description="Add process step", button_style="success", icon="plus"
        )

        self.save_button = ipw.Button(
            description="",
            disabled=False,
            button_style="",
            tooltip="Save",
            icon="save",
            layout=ipw.Layout(width="100px", height="50px"),
        )

        # Put the form actions in one row, and separate the save button with a little margin
        button_row = ipw.HBox(
            [self.add_process_step_button], layout=ipw.Layout(margin="10px 0px")
        )
        save_row = ipw.HBox(
            [self.save_button], layout=ipw.Layout(margin="20px 0px 0px 0px")
        )

        self.register_process_notes = ipw.HTML(
            value="""
            <details style="background-color: #f4f6f9; border-left: 5px solid #2980b9; padding: 12px; margin-bottom: 15px; border-radius: 4px; font-family: sans-serif; cursor: pointer;">
                <summary style="font-weight: bold; font-size: 16px; color: #2c3e50; outline: none;">
                    💡 Save Process Templates
                </summary>

                <div style="margin-top: 12px; cursor: default;">
                    <div style="color: #34495e; font-size: 14px; margin-bottom: 12px;">
                        Use this tab to build <b>Templates</b> (recipes) for processes that you perform frequently. Instead of building the same sequence from scratch every time, you can save it here and easily load it later in the <i>Register preparation</i> tab.
                    </div>

                    <ul style="margin: 0; padding-left: 20px; color: #34495e; font-size: 14px; line-height: 1.5; margin-bottom: 15px;">
                        <li style="margin-bottom: 6px;"><b>Select collection:</b> Choose the openBIS collection where this template will be stored.</li>
                        <li style="margin-bottom: 6px;"><b>Process properties:</b> Define the overall template.
                            <ul style="margin-top: 4px; padding-left: 20px;">
                                <li><i>Name:</i> The full descriptive name of the process.</li>
                                <li><i>Short name:</i> A quick abbreviation (e.g., "SPAN" for Sputtering-Annealing).</li>
                                <li><i>Description:</i> Notes on what this specific recipe does.</li>
                            </ul>
                        </li>
                        <li style="margin-bottom: 6px;"><b>Register new steps:</b> Click <b>Add process step</b> to build the sequence. Just like in the preparation tab, you can add multiple sequential steps and attach simultaneous actions to them.</li>
                        <li><b>Save (💾):</b> Saves this template to openBIS so it can be quickly imported later.</li>
                    </ul>

                    <div style="background-color: #e8f4f8; border-left: 4px solid #17a2b8; padding: 10px; border-radius: 3px; font-size: 14px; color: #0c5460;">
                        ℹ️ <b>Note:</b><br>
                        You are <b>not</b> applying these steps to a physical sample right now. You are simply saving a reusable blueprint!
                    </div>
                </div>
            </details>
            """
        )

        self.children = [
            self.register_process_notes,
            self.select_collection_title,
            self.select_collection_hbox,
            self.process_properties_title,
            self.process_name_hbox,
            self.process_short_name_hbox,
            self.process_description_hbox,
            self.new_processes_title,
            self.new_processes_accordion,
            button_row,
            save_row,
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
            self.openbis_session,
            self.new_processes_accordion,
            process_step_index,
            allow_observables=False,
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
                "process_steps": [],
            }

            for process_widget in process_steps_widgets:
                process_step_name = process_widget.name_textbox.value
                process_step_description = process_widget.description_textbox.value
                process_step_instrument = process_widget.instrument_dropdown.value
                process_step_comments = process_widget.comments_textarea.value
                actions_widgets = process_widget.actions_accordion.children
                actions = []

                if actions_widgets:
                    for action_widget in actions_widgets:
                        action_properties_values = {}
                        action_type = action_widget.action_type_dropdown.value
                        action_properties_widgets = (
                            action_widget.action_properties_widgets.children
                        )

                        if action_type == "-1":
                            continue

                        action_properties = (
                            utils.get_openbis_object_type(
                                self.openbis_session, type=action_type
                            )
                            .get_property_assignments()
                            .df.code.values
                        )

                        components_found = False
                        for prop in action_properties:
                            prop_type = utils.get_openbis_property_type(
                                self.openbis_session, code=prop
                            )
                            prop_dataType = str(prop_type.dataType)
                            prop_lower = prop.lower()

                            for widget in action_properties_widgets:
                                if "property_name" in widget.metadata:
                                    if widget.metadata["property_name"] == prop:
                                        if prop == "DURATION":
                                            duration_days = widget.children[1].value
                                            duration_hours = widget.children[3].value
                                            duration_minutes = widget.children[5].value
                                            duration_seconds = widget.children[7].value
                                            duration = f"{duration_days} days {duration_hours:02}:{duration_minutes:02}:{duration_seconds:02}"

                                            action_properties_values[prop_lower] = (
                                                duration
                                            )
                                        else:
                                            action_properties_values[prop_lower] = (
                                                widget.children[1].value
                                            )

                                        break

                                    elif (
                                        not components_found
                                        and f"{prop}_SETTINGS" in action_properties
                                        and prop_dataType in ["SAMPLE", "OBJECT"]
                                        and widget.metadata["property_name"]
                                        == "COMPONENTS"
                                    ):
                                        # This part of the code finds all components and settings used in the current action
                                        for component_widget in widget.children:
                                            component_name = (
                                                component_widget.metadata.get(
                                                    "component_name"
                                                )
                                            )
                                            component_type = (
                                                component_widget.metadata.get(
                                                    "component_type"
                                                )
                                            )
                                            component_settings_type = (
                                                f"{component_type}_SETTINGS"
                                            )
                                            component_settings_type_lower = (
                                                component_settings_type.lower()
                                            )
                                            component_permid = (
                                                component_widget.children[
                                                    0
                                                ].metadata.get("object_id")
                                            )
                                            component_settings_permid = (
                                                component_widget.children[1]
                                                .children[1]
                                                .value
                                            )
                                            component_type_lower = (
                                                component_type.lower()
                                            )
                                            action_properties_values[
                                                component_type_lower
                                            ] = component_permid
                                            if component_settings_permid != "-1":
                                                action_properties_values[
                                                    component_settings_type_lower
                                                ] = component_settings_permid
                                            else:
                                                component_settings_properties_values = {}
                                                component_settings_name = (
                                                    f"{component_name} with "
                                                )
                                                for (
                                                    setting_widget
                                                ) in component_widget.children[
                                                    2
                                                ].children:
                                                    setting_prop_type = (
                                                        setting_widget.metadata.get(
                                                            "property_name"
                                                        )
                                                    )
                                                    setting_prop_label = (
                                                        setting_widget.children[0]
                                                        .value.removeprefix("<b>")
                                                        .removesuffix("</b>")
                                                        .removesuffix(":")
                                                    )
                                                    setting_prop_value = (
                                                        setting_widget.children[1].value
                                                    )
                                                    setting_prop_type_lower = (
                                                        setting_prop_type.lower()
                                                    )
                                                    component_settings_properties_values[
                                                        setting_prop_type_lower
                                                    ] = setting_prop_value
                                                    component_settings_name += f"{setting_prop_label}: {setting_prop_value}, "

                                                component_settings_name = (
                                                    component_settings_name.rstrip(", ")
                                                )
                                                component_settings_properties_values[
                                                    "name"
                                                ] = component_settings_name

                                                new_component_settings = utils.create_openbis_object(
                                                    self.openbis_session,
                                                    type=component_settings_type,
                                                    experiment=collection_id,
                                                    props=component_settings_properties_values,
                                                    parents=[component_permid]
                                                )

                                                action_properties_values[
                                                    component_settings_type_lower
                                                ] = new_component_settings.permId

                                        components_found = True
                                        break

                        if (
                            action_widget.action_icon
                            not in action_properties_values["name"]
                        ):
                            action_properties_values["name"] = (
                                action_widget.action_icon
                                + " "
                                + action_properties_values["name"]
                            )

                        new_action_object = utils.create_openbis_object(
                            self.openbis_session,
                            type=action_type,
                            experiment=collection_id,
                            props=action_properties_values,
                        )

                        actions.append(new_action_object.permId)

                process_step_settings = {
                    "name": process_step_name,
                    "description": process_step_description,
                    "comments": process_step_comments,
                    "actions": actions,
                }

                new_process_step_parents = []
                if process_step_instrument != "-1":
                    new_process_step_parents.append(process_step_instrument)

                new_process_step_object = utils.create_openbis_object(
                    self.openbis_session,
                    type=OPENBIS_OBJECT_TYPES["Process Step"],
                    experiment=collection_id,
                    props=process_step_settings,
                    parents=new_process_step_parents,
                )

                process_properties["process_steps"].append(
                    new_process_step_object.permId
                )

            new_process_object = utils.create_openbis_object(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["Process"],
                experiment=collection_id,
                props=process_properties,
            )

            display(Javascript(data="alert('Process created successfully.')"))
            logger.info(f"Process {new_process_object.permId} created successfully.")

            # Reset new processes accordion
            processes_accordion_children = list(self.new_processes_accordion.children)
            for index, _ in enumerate(processes_accordion_children):
                self.new_processes_accordion.set_title(index, "")

            self.new_processes_accordion.children = []

            self.process_name_text.value = ""
            self.process_short_name_text.value = ""
            self.process_description_text.value = ""
            self.select_collection_dropdown.value = "-1"

            logger.info("Resetting new process steps interface.")


class RegisterProcessStepWidget(ipw.VBox):
    def __init__(
        self,
        openbis_session,
        processes_accordion,
        process_step_index,
        process_step=None,
        allow_observables=True,
    ):
        super().__init__()
        self.openbis_session = openbis_session
        self.processes_accordion = processes_accordion
        self.process_step_index = process_step_index

        self.name_label = ipw.HTML(value="<b>Name:</b>")
        self.name_textbox = ipw.Text()
        self.name_hbox = ipw.HBox(children=[self.name_label, self.name_textbox])

        self.description_label = ipw.HTML(value="<b>Description:</b>")
        self.description_textbox = ipw.Text()
        self.description_hbox = ipw.HBox(
            children=[self.description_label, self.description_textbox]
        )

        self.instrument_label = ipw.HTML(value="<b>Instrument:</b>")
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

        self.comments_label = ipw.HTML(value="<b>Comments:</b>")
        self.comments_textarea = ipw.Textarea()
        self.comments_hbox = ipw.HBox(
            children=[self.comments_label, self.comments_textarea]
        )

        self.actions_label = ipw.HTML(value="<b>Actions:</b>")
        self.actions_accordion = ipw.Accordion()
        self.add_action_button = ipw.Button(
            description="Add action",
            disabled=False,
            button_style="success",
            icon="plus",
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

        self.observables_label = ipw.HTML(value="<b>Observables:</b>")
        self.observables_accordion = ipw.Accordion()

        self.remove_process_step_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            icon="trash",
            tooltip="Remove process step",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.remove_process_step_button.on_click(self.remove_process_step)
        self.name_textbox.observe(self.change_process_step_title, names="value")
        self.add_action_button.on_click(self.add_action)

        # Load process step settings if provided
        if process_step:
            self.load_process_step(process_step)

        # In case we are saving a process we do not need observables because they are only generated on real-time
        if allow_observables:
            self.add_observable_button = ipw.Button(
                description="Add observable",
                disabled=False,
                button_style="success",
                icon="plus",
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
            self.add_observable_button.on_click(self.add_observable)
            self.children = [
                self.name_hbox,
                self.description_hbox,
                self.comments_hbox,
                self.instrument_hbox,
                self.actions_vbox,
                self.observables_vbox,
                self.remove_process_step_button,
            ]
        else:
            self.children = [
                self.name_hbox,
                self.description_hbox,
                self.comments_hbox,
                self.instrument_hbox,
                self.actions_vbox,
                self.remove_process_step_button,
            ]

    def load_process_step(self, process_step):
        """
        Load process step settings from process template and populate the widgets accordingly.
        """
        self.name_textbox.value = process_step.props["name"] or ""
        self.description_textbox.value = process_step.props["description"] or ""
        self.comments_textarea.value = process_step.props["comments"] or ""

        for parent_id in process_step.parents:
            parent_obj = utils.get_openbis_object(self.openbis_session, parent_id)
            if parent_obj.type.code in [
                OPENBIS_OBJECT_TYPES["Instrument"],
                OPENBIS_OBJECT_TYPES["Instrument STM"],
            ]:
                self.instrument_dropdown.value = parent_obj.permId
                break

        actions_list = process_step.props["actions"]
        for action_id in actions_list:
            action_object = utils.get_openbis_object(
                self.openbis_session, sample_ident=action_id
            )
            actions_accordion_children = list(self.actions_accordion.children)
            action_index = len(actions_accordion_children)
            new_action_widget = RegisterActionWidget(
                self.openbis_session,
                self.actions_accordion,
                action_index,
                self.instrument_dropdown.value,
                action_object,
            )
            actions_accordion_children.append(new_action_widget)
            self.actions_accordion.children = actions_accordion_children

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

        global INSTRUMENT_COMPONENTS

        if INSTRUMENT_COMPONENTS is None:
            self.instrument_components = self.find_instrument_components(
                instrument_permid
            )
            INSTRUMENT_COMPONENTS = {
                k: list(v) for k, v in self.instrument_components.items()
            }
        else:
            self.instrument_components = {
                k: list(v) for k, v in INSTRUMENT_COMPONENTS.items()
            }

        action_type_options = [("Select an action type...", "-1")] + list(
            ACTIONS_TYPES.items()
        )

        self.action_type_dropdown = ipw.Dropdown(
            options=action_type_options, value="-1"
        )
        self.action_type_hbox = ipw.HBox(
            children=[ipw.HTML(value="<b>Action type:</b>"), self.action_type_dropdown]
        )
        self.action_properties_widgets = ipw.VBox()

        self.all_actions_properties = {}
        for action_type in ACTIONS_TYPES.values():
            props = (
                utils.get_openbis_object_type(openbis_session, type=action_type)
                .get_property_assignments()
                .df.code.values
            )
            self.all_actions_properties.update(dict.fromkeys(props, None))

        self.remove_action_button = ipw.Button(
            description="Remove",
            button_style="danger",
            icon="trash",
            tooltip="Remove action",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.action_type_dropdown.observe(self.load_action_properties, names="value")
        self.remove_action_button.on_click(self.remove_action)

        if action_settings:
            self.load_action(action_settings)

        self.children = [
            self.action_type_hbox,
            self.action_properties_widgets,
            self.remove_action_button,
        ]

    def find_instrument_components(self, instrument_permid):
        obj = self.openbis_session.get_object(instrument_permid)
        obj_type = str(obj.type)

        assignments_df = (
            utils.get_openbis_object_type(self.openbis_session, type=obj_type)
            .get_property_assignments()
            .df
        )
        component_ids_to_fetch = []

        for _, row in assignments_df.iterrows():
            prop_code = row["code"]
            prop_type = row.get("dataType")
            if not prop_type:
                prop_type = utils.get_property_type(
                    self.openbis_session, prop_code
                ).dataType

            if prop_type == "SAMPLE":
                prop_value = obj.props[prop_code.lower()]
                if prop_value:
                    if not isinstance(prop_value, list):
                        prop_value = [prop_value]

                    component_ids_to_fetch.extend(prop_value)
        all_components = defaultdict(list)
        if component_ids_to_fetch:
            for comp_id in component_ids_to_fetch:
                comp_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=comp_id
                )
                comp_obj_type = str(comp_obj.type)
                if comp_obj_type not in [
                    "PERSON",
                    "ORGANISATION",
                    "TEAM",
                    "GROUP",
                    "ROOM",
                ]:
                    all_components[comp_obj_type].append(comp_obj)
        return dict(all_components)

    def load_substance_mol_image(self, change):
        substance_id = change["new"]

        # 1. Clear previous images from the container
        self.substance_images_container.children = []

        if substance_id == "-1":
            return

        substance_obj = utils.get_openbis_object(
            self.openbis_session, sample_ident=substance_id
        )
        mols_ids = substance_obj.get_parents(type="MOLECULE").df.permId.values

        if len(mols_ids) == 0:
            return

        # 2. Prepare a list to hold our new image widgets
        image_widgets = []

        # 3. Loop through EVERY molecule ID associated with the substance
        for mol_id in mols_ids:
            molecule_obj = utils.get_openbis_object(
                self.openbis_session, sample_ident=mol_id
            )
            datasets = molecule_obj.get_datasets(type="ELN_PREVIEW")

            # Skip if this specific molecule doesn't have an image
            if not datasets or not datasets[0].file_list:
                continue

            preview_ds = datasets[0]
            preview_ds.download(destination="images")

            dataset_folder = os.path.join("images", preview_ds.permId)
            img_path = os.path.join(dataset_folder, preview_ds.file_list[0])

            try:
                img_bytes = utils.read_file(img_path)

                # Create the raw image widget
                img_widget = ipw.Image(
                    value=img_bytes, layout=ipw.Layout(width="100px", height="100px")
                )

                # Create a tiny, centered label for the bottom of the card (uses the molecule name if it exists)
                mol_name = molecule_obj.props["name"]
                label_widget = ipw.HTML(
                    value=f"<div style='text-align: center; font-size: 11px; color: #666; width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;'>{mol_name}</div>"
                )

                # Wrap the image and label in a "Card" container with CSS styling
                card_widget = ipw.VBox(
                    children=[img_widget, label_widget],
                    layout=ipw.Layout(
                        border="1px solid #d3d3d3",  # Subtle gray border
                        border_radius="6px",  # Rounded corners
                        padding="8px",  # Breathing room inside the box
                        margin="0 12px 12px 0",  # Space between different cards
                        background_color="#ffffff",  # Forces a white background
                        align_items="center",  # Centers the image and text horizontally
                        justify_content="center",  # Centers vertically
                    ),
                )

                image_widgets.append(card_widget)

            finally:
                # Clean up this specific dataset folder immediately
                if os.path.exists(dataset_folder):
                    shutil.rmtree(dataset_folder, ignore_errors=True)

        # 4. Inject all the generated image widgets into the UI container at once
        self.substance_images_container.children = image_widgets

    def load_action(self, settings):
        action_object = settings
        action_properties_values = action_object.props.all()
        action_type = action_object.type.code
        self.action_type_dropdown.value = action_type
        action_properties = (
            utils.get_openbis_object_type(self.openbis_session, type=action_type)
            .get_property_assignments()
            .df.code.values
        )

        for prop in action_properties:
            prop_lower = prop.lower()
            prop_type = utils.get_openbis_property_type(self.openbis_session, code=prop)
            prop_dataType = str(prop_type.dataType)
            prop_value = action_properties_values[prop_lower]
            for widget_idx, widget in enumerate(
                self.action_properties_widgets.children
            ):
                if "property_name" in widget.metadata:
                    if widget.metadata["property_name"] == prop:
                        if prop == "DURATION":
                            match = re.match(
                                r"(\d+)\s+days\s+(\d+):(\d+):(\d+)", prop_value
                            )
                            if match:
                                days, hours, minutes, seconds = map(int, match.groups())
                                widget.children[1].value = days
                                widget.children[3].value = hours
                                widget.children[5].value = minutes
                                widget.children[7].value = seconds

                        elif (
                            prop_dataType in ["SAMPLE", "OBJECT"]
                            and not widget.metadata["property_name"] == "COMPONENT"
                        ):
                            widget.children[1].value = prop_value or "-1"

                        else:
                            widget.children[1].value = prop_value or ""

                    elif (
                        f"{prop}_SETTINGS" in action_properties
                        and prop_dataType in ["SAMPLE", "OBJECT"]
                        and widget.metadata["property_name"] == "COMPONENT"
                        and prop_value
                    ):
                        component_object = utils.get_openbis_object(
                            self.openbis_session, sample_ident=prop_value
                        )
                        component_type = str(component_object.type)
                        widget.children[1].value = prop_value
                        settings_widget = self.action_properties_widgets.children[
                            widget_idx + 1
                        ]
                        prop_lower = f"{prop_lower}_settings"
                        for component_idx, component_setting in enumerate(
                            settings_widget.children
                        ):
                            if (
                                component_setting.metadata.get("component_type", "")
                                == component_type
                            ):
                                settings_widget.children[component_idx].children[
                                    1
                                ].children[1].value = action_properties_values[
                                    prop_lower
                                ]
                                break

    def load_action_properties(self, change):
        action_type = self.action_type_dropdown.value
        if action_type == "-1":
            self.action_properties_widgets.children = []
            return

        icon_mapping = {
            OPENBIS_OBJECT_TYPES.get("Annealing"): "🔥",
            OPENBIS_OBJECT_TYPES.get("Cooldown"): "❄️",
            OPENBIS_OBJECT_TYPES.get("Deposition"): "🟫",
            OPENBIS_OBJECT_TYPES.get("Dosing"): "💧",
            OPENBIS_OBJECT_TYPES.get("Sputtering"): "🔫",
            OPENBIS_OBJECT_TYPES.get("Coating"): "🧥",
            OPENBIS_OBJECT_TYPES.get("Delamination"): "🧩",
            OPENBIS_OBJECT_TYPES.get("Etching"): "📌",
            OPENBIS_OBJECT_TYPES.get("Fishing"): "🎣",
            OPENBIS_OBJECT_TYPES.get("Field Emission"): "⚡",
            OPENBIS_OBJECT_TYPES.get("Light Irradiation"): "💡",
            OPENBIS_OBJECT_TYPES.get("Mechanical Pressing"): "🔩",
            OPENBIS_OBJECT_TYPES.get("Rinse"): "🚿",
        }
        self.action_icon = icon_mapping.get(action_type, "⚙️")
        self.actions_accordion.set_title(self.action_index, self.action_icon)

        action_properties = (
            utils.get_openbis_object_type(self.openbis_session, type=action_type)
            .get_property_assignments()
            .df.code.values
        )

        action_component_types = []
        action_properties_widgets = []
        component_widgets_appended = False

        comp_widget_ref = None

        widget_type_map = {
            "VARCHAR": ipw.Text,
            "MULTILINE_VARCHAR": ipw.Textarea,
            "BOOLEAN": ipw.Checkbox,
            "REAL": ipw.FloatText,
            "INTEGER": ipw.IntText,
        }

        for prop in action_properties:
            prop_type = utils.get_openbis_property_type(self.openbis_session, code=prop)
            prop_label = str(prop_type.label)
            prop_dataType = str(prop_type.dataType)
            prop_sampleType = str(prop_type.sampleType)

            if f"{prop}_SETTINGS" in action_properties and prop_dataType in [
                "SAMPLE",
                "OBJECT",
            ]:
                action_component_types.append(prop_sampleType)
                if not component_widgets_appended:
                    component_widgets_appended = True
                    comp_dropdown_widget = ipw.Dropdown(
                        options=[("Loading...", "-1")], value="-1"
                    )
                    comp_widget_ref = cw.HBox(
                        children=[
                            ipw.HTML(value="<b>Component:</b>"),
                            comp_dropdown_widget,
                        ],
                        metadata={"property_name": "COMPONENT"},
                    )
                    selected_components_vbox = cw.VBox(
                        metadata={"property_name": "COMPONENTS"}
                    )
                    action_properties_widgets.extend(
                        [comp_widget_ref, selected_components_vbox]
                    )

            elif prop == "DURATION":
                duration_widgets = cw.HBox(
                    children=[
                        ipw.HTML(value="<b>Duration:</b>"),
                        ipw.BoundedIntText(
                            value=0, min=0, layout=ipw.Layout(width="40px")
                        ),
                        ipw.Label("days"),
                        ipw.BoundedIntText(
                            value=0, max=23, layout=ipw.Layout(width="40px")
                        ),
                        ipw.Label(":"),
                        ipw.BoundedIntText(
                            value=0, max=59, layout=ipw.Layout(width="40px")
                        ),
                        ipw.Label(":"),
                        ipw.BoundedIntText(
                            value=0, max=59, layout=ipw.Layout(width="40px")
                        ),
                    ],
                    metadata={"property_name": prop},
                )
                action_properties_widgets.append(duration_widgets)

            elif prop == "SUBSTANCE":
                substances_list = utils.get_openbis_objects(
                    self.openbis_session,
                    collection=OPENBIS_COLLECTIONS_PATHS["Precursor Substance"],
                    type=OPENBIS_OBJECT_TYPES["Substance"],
                )
                substance_options = [("Select a substance...", "-1")]
                for obj in substances_list:
                    props = obj.props.all()
                    if "empa_number" in props and "batch" in props:
                        name = f"{props['empa_number']}{props['batch']}"
                        substance_options.append((name, obj.permId))
                    else:
                        logging.info(
                            f"Substance {obj.permId} is missing EMPA number or batch."
                        )

                self.substance_dropdown = ipw.Dropdown(
                    options=substance_options, value="-1"
                )

                self.substance_images_container = ipw.HBox(
                    layout=ipw.Layout(flex_wrap="wrap")
                )

                self.substance_dropdown.observe(
                    self.load_substance_mol_image, names="value"
                )

                substance_widgets = cw.HBox(
                    children=[
                        ipw.HTML(value="<b>Substance:</b>"),
                        self.substance_dropdown,
                        self.substance_images_container,  # Added container here
                    ],
                    metadata={"property_name": prop},
                )
                action_properties_widgets.append(substance_widgets)

            elif prop == "GAS":
                gas_list = utils.get_openbis_objects(
                    self.openbis_session, type=OPENBIS_OBJECT_TYPES["Gas Bottle"]
                )
                gas_options = [("Select a dosing gas...", "-1")] + [
                    (obj.props["name"], obj.permId) for obj in gas_list
                ]
                action_properties_widgets.append(
                    cw.HBox(
                        children=[
                            ipw.HTML(value="<b>Dosing gas:</b>"),
                            ipw.Dropdown(options=gas_options, value="-1"),
                        ],
                        metadata={"property_name": prop},
                    )
                )

            else:
                if prop_dataType not in widget_type_map:
                    continue

                prop_value_widget = widget_type_map[prop_dataType]()
                if prop == "NAME":
                    prop_value_widget.observe(self.change_action_title, names="value")
                    default_action_name = action_type.replace("_", " ").title()
                    prop_value_widget.value = (
                        f"{default_action_name} {self.action_index + 1}"
                    )

                action_properties_widgets.append(
                    cw.HBox(
                        children=[
                            ipw.HTML(value=f"<b>{prop_label}:</b>"),
                            prop_value_widget,
                        ],
                        metadata={"property_name": prop},
                    )
                )

        if action_component_types:
            unique_component_types = list(set(action_component_types))

            # Master dictionary of available components: {permId: (name, type)}
            available_components_dict = {}
            for c_type in unique_component_types:
                c_objs = self.instrument_components.get(c_type, [])
                for obj in c_objs:
                    available_components_dict[obj.permId] = (obj.props["name"], c_type)

            # 1. Generate the list of components
            component_options = [
                (name, permId)
                for permId, (name, c_type) in available_components_dict.items()
            ]

            # 2. Sort the list alphabetically by the 'name' (which is the first item: x[0])
            # Adding .lower() ensures "apple" and "Zebra" sort correctly ignoring capitalization
            component_options.sort(key=lambda x: x[0].lower())

            # 3. Add the default 'Select' option to the very beginning and assign it
            comp_dropdown_widget.options = [
                ("Select a component to add...", "-1")
            ] + component_options
            comp_dropdown_widget.value = "-1"

            def add_component_ui(change):
                permid = change["new"]
                if permid == "-1":
                    return

                c_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=permid
                )
                c_name, c_type = available_components_dict[permid]

                # 1. Build the UI wrapper for this specific component
                remove_btn = ipw.Button(
                    icon="close",
                    button_style="danger",
                    layout=ipw.Layout(width="25px", height="25px", padding="0px"),
                    tooltip="Remove component",
                )
                header = cw.HBox(
                    children=[ipw.HTML(value=f"<b>⚙️ {c_name}</b>"), remove_btn],
                    metadata={"object_id": permid},
                )

                # 2. Build Settings Dropdown
                settings_type = f"{c_type}_SETTINGS"
                settings_objs = utils.get_openbis_objects(
                    self.openbis_session, type=settings_type, attrs=["parents"]
                )

                # Filter out any settings that don't have the current component as a parent
                filtered_settings = [
                    obj
                    for obj in settings_objs
                    if obj.parents
                    and (c_object.identifier in obj.parents or permid in obj.parents)
                ]

                # Build the options using the filtered list
                dynamic_options = [
                    (obj.props["name"], obj.permId) for obj in filtered_settings
                ]
                dynamic_options.sort(key=lambda x: x[1])

                settings_options = [("Select settings...", "-1")] + dynamic_options
                settings_dropdown = ipw.Dropdown(options=settings_options, value="-1")
                settings_dropdown_hbox = cw.HBox(
                    children=[ipw.HTML(value="<b>Settings:</b>"), settings_dropdown]
                )

                is_updating_settings = False

                def reset_settings_dropdown(change):
                    nonlocal is_updating_settings
                    # Only reset if we are NOT currently running the load_settings_values loop
                    if settings_dropdown.value != "-1" and not is_updating_settings:
                        settings_dropdown.value = "-1"

                # 3. Build Input Fields
                prop_types = (
                    utils.get_openbis_object_type(
                        self.openbis_session, type=settings_type
                    )
                    .get_property_assignments()
                    .df.code.values
                )
                settings_props_widgets = []
                for s_prop in prop_types:
                    if s_prop == "NAME":
                        continue
                    s_prop_type = utils.get_openbis_property_type(
                        self.openbis_session, code=s_prop
                    )
                    s_dataType = str(s_prop_type.dataType)
                    if s_dataType in widget_type_map:
                        w = widget_type_map[s_dataType]()
                        s_prop_lower = s_prop.lower()
                        s_value = c_object.props[s_prop_lower]
                        if s_value is not None:
                            w.value = s_value

                        w.observe(reset_settings_dropdown, names="value")
                        settings_props_widgets.append(
                            cw.HBox(
                                children=[
                                    ipw.HTML(value=f"<b>{str(s_prop_type.label)}:</b>"),
                                    w,
                                ],
                                metadata={"property_name": s_prop},
                            )
                        )

                settings_fields_vbox = ipw.VBox(children=settings_props_widgets)

                # 4. Settings Value Callback
                def load_settings_values(s_change):
                    nonlocal is_updating_settings

                    s_permid = s_change["new"]
                    if s_permid != "-1":
                        s_obj = utils.get_openbis_object(
                            self.openbis_session, sample_ident=s_permid
                        )
                        props = {k.upper(): v for k, v in s_obj.props().items()}

                        # 1. Block the reset callback
                        is_updating_settings = True

                        try:
                            # 2. Update all the widgets
                            for widget in settings_fields_vbox.children:
                                prop_name = widget.metadata["property_name"]
                                if prop_name in props and props[prop_name] is not None:
                                    widget.children[1].value = props[prop_name]
                        finally:
                            # 3. Unblock the reset callback after ALL widgets are done updating
                            is_updating_settings = False

                settings_dropdown.observe(load_settings_values, names="value")

                component_block = cw.VBox(
                    children=[header, settings_dropdown_hbox, settings_fields_vbox],
                    layout=ipw.Layout(
                        border="1px solid #d3d3d3",
                        padding="10px",
                        margin="10px 0",
                        border_radius="5px",
                    ),
                    metadata={"component_type": c_type, "component_name": c_name},
                )

                # 5. Handle "Remove" Button clicks
                def remove_this_component(b):
                    selected_components_vbox.children = [
                        c
                        for c in selected_components_vbox.children
                        if c != component_block
                    ]

                    # Add ALL components of this specific type back to the dropdown
                    components_to_restore = [
                        (name, pid)
                        for pid, (name, t) in available_components_dict.items()
                        if t == c_type
                    ]

                    comp_dropdown_widget.unobserve(add_component_ui, names="value")

                    current_options = list(comp_dropdown_widget.options)
                    current_options.extend(components_to_restore)

                    # 1. Separate the default option from the actual components
                    default_option = [opt for opt in current_options if opt[1] == "-1"]
                    actual_components = [
                        opt for opt in current_options if opt[1] != "-1"
                    ]

                    # 2. Sort the actual components alphabetically by name (case-insensitive)
                    actual_components.sort(key=lambda x: x[0].lower())

                    # 3. Recombine them with the default option at the top
                    comp_dropdown_widget.options = default_option + actual_components

                    comp_dropdown_widget.value = "-1"
                    comp_dropdown_widget.observe(add_component_ui, names="value")

                remove_btn.on_click(remove_this_component)

                # 6. Finally: Apply changes to the UI
                selected_components_vbox.children = list(
                    selected_components_vbox.children
                ) + [component_block]

                # Remove ALL components of the newly added type from the main dropdown
                comp_dropdown_widget.unobserve(add_component_ui, names="value")
                new_options = [
                    opt
                    for opt in comp_dropdown_widget.options
                    if opt[1] == "-1" or available_components_dict[opt[1]][1] != c_type
                ]
                comp_dropdown_widget.options = new_options
                comp_dropdown_widget.value = "-1"
                comp_dropdown_widget.observe(add_component_ui, names="value")

            comp_dropdown_widget.observe(add_component_ui, names="value")

        self.action_properties_widgets.children = action_properties_widgets

    def change_action_title(self, change):
        self.actions_accordion.set_title(
            self.action_index, f"{self.action_icon} {change['new']}"
        )

    def remove_action(self, b):
        children = list(self.actions_accordion.children)
        children.pop(self.action_index)

        for i in range(self.action_index, len(children)):
            children[i].action_index = i

        self.actions_accordion.children = children

        for i, action in enumerate(children):
            action_name = f"{action.action_icon} "
            if self.action_properties_widgets.children:
                for widget in action.action_properties_widgets.children:
                    if widget.metadata.get("property_name", "") == "NAME":
                        action_name += widget.children[1].value
                        break
            self.actions_accordion.set_title(i, action_name)

        self.actions_accordion.set_title(len(children), "")


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

        global INSTRUMENT_COMPONENTS

        if INSTRUMENT_COMPONENTS is None:
            self.instrument_components = self.find_instrument_components(
                instrument_permid
            )
            INSTRUMENT_COMPONENTS = {
                k: list(v) for k, v in self.instrument_components.items()
            }
        else:
            self.instrument_components = {
                k: list(v) for k, v in INSTRUMENT_COMPONENTS.items()
            }

        observable_prop_types = (
            utils.get_openbis_dataset_type(self.openbis_session, type="OBSERVABLE")
            .get_property_assignments()
            .df.code.values
        )

        observable_properties_widgets = []
        for prop in observable_prop_types:
            prop_type = utils.get_openbis_property_type(self.openbis_session, code=prop)
            prop_label = str(prop_type.label)
            prop_dataType = str(prop_type.dataType)
            prop_multiValue = prop_type.multiValue

            if prop_multiValue:
                if prop_dataType == "SAMPLE":
                    sample_options = []
                    for obj_type, obj_list in self.instrument_components.items():
                        for obj in obj_list:
                            sample_options.append((obj.props["name"], obj.permId))

                    sample_options.sort(key=lambda x: x[0].lower())
                    widget = ipw.SelectMultiple(
                        options=sample_options,
                        value=[],
                        layout=ipw.Layout(height="300px", width="200px"),
                    )

                else:
                    multi_widget_map = {
                        "VARCHAR": (
                            ipw.Text,
                            {"placeholder": "Enter comma-separated values"},
                        ),
                        "BOOLEAN": (
                            ipw.Text,
                            {"placeholder": "Enter comma-separated True/False"},
                        ),
                        "REAL": (
                            ipw.Text,
                            {"placeholder": "Enter comma-separated numbers"},
                        ),
                        "INTEGER": (
                            ipw.Text,
                            {"placeholder": "Enter comma-separated integers"},
                        ),
                        "TIMESTAMP": (
                            ipw.Text,
                            {"placeholder": "Enter comma-separated dates"},
                        ),
                    }

                    if prop_dataType not in multi_widget_map:
                        continue

                    widget_class, widget_kwargs = multi_widget_map[prop_dataType]
                    widget = widget_class(**widget_kwargs)

            else:
                if prop_dataType == "SAMPLE":
                    sample_options = []
                    for obj_type, obj_list in self.instrument_components.items():
                        for obj in obj_list:
                            sample_options.append((obj.props["name"], obj.permId))
                    widget = ipw.Dropdown(options=sample_options, value="-1")

                else:
                    single_widget_map = {
                        "VARCHAR": ipw.Text,
                        "MULTILINE_VARCHAR": ipw.Textarea,
                        "BOOLEAN": ipw.Checkbox,
                        "REAL": ipw.FloatText,
                        "INTEGER": ipw.IntText,
                        "TIMESTAMP": ipw.Text,  # Could be enhanced with ipw.DatePicker()
                    }

                    if prop_dataType not in single_widget_map:
                        continue

                    # Create the single-value widget directly
                    widget_class = single_widget_map[prop_dataType]
                    widget = widget_class()

            if prop == "NAME":
                widget.observe(self.change_observable_title, names="value")
                widget.value = "Logs"

            observable_properties_widgets.append(
                cw.HBox(
                    children=[ipw.HTML(value=f"<b>{prop_label}:</b>"), widget],
                    metadata={"property_name": prop},
                )
            )

        self.observable_properties_widgets = ipw.VBox(
            children=observable_properties_widgets
        )

        self.upload_readings_label = ipw.HTML(value="<b>Upload readings:</b>")
        self.upload_readings_widget = ipw.FileUpload(multiple=False)
        self.upload_readings_hbox = ipw.HBox(
            children=[self.upload_readings_label, self.upload_readings_widget]
        )

        self.remove_observable_button = ipw.Button(
            description="Remove",
            disabled=False,
            button_style="danger",
            icon="trash",
            tooltip="Remove observable",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.remove_observable_button.on_click(self.remove_observable)

        if observable_settings:
            self.load_observable(observable_settings)

        self.children = [
            self.observable_properties_widgets,
            self.upload_readings_hbox,
            self.remove_observable_button,
        ]

    def find_instrument_components(self, instrument_permid):
        obj = self.openbis_session.get_object(instrument_permid)
        obj_type = str(obj.type)

        assignments_df = (
            utils.get_openbis_object_type(self.openbis_session, type=obj_type)
            .get_property_assignments()
            .df
        )
        component_ids_to_fetch = []

        for _, row in assignments_df.iterrows():
            prop_code = row["code"]
            prop_type = row.get("dataType")
            if not prop_type:
                prop_type = utils.get_property_type(
                    self.openbis_session, prop_code
                ).dataType

            if prop_type == "SAMPLE":
                prop_value = obj.props[prop_code.lower()]
                if prop_value:
                    if not isinstance(prop_value, list):
                        prop_value = [prop_value]

                    component_ids_to_fetch.extend(prop_value)
        all_components = defaultdict(list)
        if component_ids_to_fetch:
            for comp_id in component_ids_to_fetch:
                comp_obj = utils.get_openbis_object(
                    self.openbis_session, sample_ident=comp_id
                )
                comp_obj_type = str(comp_obj.type)
                if comp_obj_type not in [
                    "PERSON",
                    "ORGANISATION",
                    "TEAM",
                    "GROUP",
                    "ROOM",
                ]:
                    all_components[comp_obj_type].append(comp_obj)
        return dict(all_components)

    def change_observable_title(self, change):
        self.observables_accordion.set_title(
            self.observable_index, f"📈 {change['new']}"
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
