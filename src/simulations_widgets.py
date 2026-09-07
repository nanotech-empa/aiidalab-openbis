import html
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

import ipywidgets as ipw
import pandas as pd
from aiida import orm
from IPython.display import Javascript, display

from . import aiida_utils, simulation_schema, utils, widgets

OPENBIS_CONFIG = utils.read_json("config/openbis_config.json")
MATERIALS_CONCEPTS_TYPES = OPENBIS_CONFIG["OpenBIS Materials Concepts Types"]
SIMULATION_TYPES = OPENBIS_CONFIG["Simulations"]["Types"]
SIMULATION_EXPORT_TYPES = OPENBIS_CONFIG["Simulation Export Types"]
OPENBIS_OBJECT_TYPES = OPENBIS_CONFIG["OpenBIS Types"]
OPENBIS_COLLECTIONS_PATHS = OPENBIS_CONFIG["Collections"]["Paths"]
WORKCHAIN_VIEWERS = OPENBIS_CONFIG["Workchain Viewers"]

_CREATE_NEW = "__create_new_openbis_object__"
_DOWNLOAD_ROOT = Path(__file__).resolve().parent.parent / "temp_dataset_download"
_DOWNLOAD_LIFETIME_SECONDS = 600


def _popup(message):
    """Show a compact notebook popup without interpolating JavaScript code."""
    display(Javascript(data=f"alert({json.dumps(str(message))})"))


def _first_uploaded_file(files_widget):
    """Return one uploaded file in a stable internal representation."""
    value = files_widget.value
    if not value:
        return None

    # ipywidgets 7 exposes a filename-keyed mapping, whereas ipywidgets 8
    # exposes a tuple of uploaded-file mappings.  Supporting both shapes keeps
    # the app usable in the current Python 3.9 and 3.12 AiiDAlab images.
    if isinstance(value, dict):
        name, file_info = next(iter(value.items()))
    else:
        file_info = value[0]
        name = file_info.get("name", "preview.png")
    return {"name": str(name), "content": bytes(file_info["content"])}


def _image_format(filename):
    return "jpeg" if Path(filename).suffix.lower() in {".jpg", ".jpeg"} else "png"


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
            description="Add molecule",
            disabled=False,
            button_style="success",
            tooltip="Add molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.reacprod_concepts_accordion = ipw.Accordion()
        reaction_products_available = (
            "Reaction Product Concept" in widgets.OPENBIS_OBJECT_TYPES
        )
        self.add_reacprod_concept_button = ipw.Button(
            description=(
                "Add reaction product concept"
                if reaction_products_available
                else "Reaction products unavailable"
            ),
            disabled=not reaction_products_available,
            button_style="success",
            tooltip=(
                "Add reaction product concept"
                if reaction_products_available
                else "The connected openBIS schema has no REACTION_PRODUCT_CONCEPT type"
            ),
            layout=ipw.Layout(width="230px", height="25px"),
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

        self.found_simulations_label = ipw.Label(value="Found simulations: 0")
        self.found_simulations_select_multiple = ipw.SelectMultiple(
            description="",
            disabled=False,
            layout=ipw.Layout(width="850px", height="180px"),
            style={"description_width": "110px"},
        )
        self.clear_simulations_button = ipw.Button(
            description="Clear selection",
            icon="times",
            layout=ipw.Layout(width="150px"),
        )
        self.found_simulations_hbox = ipw.HBox(
            children=[
                self.found_simulations_label,
                self.found_simulations_select_multiple,
                self.clear_simulations_button,
            ]
        )

        self.import_simulations_button = ipw.Button(
            description="Import into AiiDA",
            tooltip="Import the AiiDA archives linked to the selected simulations",
            icon="download",
            layout=ipw.Layout(width="180px", height="50px"),
        )
        self.download_simulation_data_button = ipw.Button(
            description="Download data",
            tooltip="Download data files or linked .aiida archives in the browser",
            icon="download",
            layout=ipw.Layout(width="180px", height="50px"),
        )

        self.import_simulations_message_html = ipw.HTML()
        self.download_simulation_data_message_html = ipw.HTML()

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
        self.download_simulation_data_button.on_click(self.download_simulation_data)
        self.clear_simulations_button.on_click(self.clear_simulation_selection)

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
            ipw.HBox(
                [
                    self.import_simulations_button,
                    self.download_simulation_data_button,
                ]
            ),
            self.import_simulations_message_html,
            self.download_simulation_data_message_html,
        ]

    @staticmethod
    def _simulation_label(simulation):
        name = aiida_utils._openbis_property(simulation, "name") or simulation.permId
        type_code = getattr(simulation.type, "code", simulation.type)
        availability = (
            "AiiDA archive"
            if aiida_utils._openbis_property(simulation, "aiida_node")
            else "data only"
        )
        return f"{name} - {type_code} ({simulation.permId}) [{availability}]"

    @classmethod
    def _simulation_options(cls, simulations):
        return [
            (cls._simulation_label(simulation), str(simulation.permId))
            for simulation in sorted(
                simulations,
                key=lambda item: (
                    cls._simulation_label(item).lower(),
                    str(item.permId),
                ),
            )
        ]

    @staticmethod
    def _partition_simulations_by_archive(simulations):
        archive_simulations = {}
        data_only_simulations = []
        for simulation in simulations:
            archive_id = aiida_utils._openbis_property(simulation, "aiida_node")
            if archive_id:
                archive_simulations.setdefault(str(archive_id), []).append(simulation)
            else:
                data_only_simulations.append(simulation)
        return archive_simulations, data_only_simulations

    @staticmethod
    def _simulation_names(simulations):
        return ", ".join(
            html.escape(
                str(
                    aiida_utils._openbis_property(simulation, "name")
                    or simulation.permId
                )
            )
            for simulation in simulations
        )

    def _selected_simulation_objects(self):
        return [
            utils.get_openbis_object(
                self.openbis_session,
                sample_ident=simulation_permid,
            )
            for simulation_permid in self.found_simulations_select_multiple.value
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

        if logical_operator == "OR":
            for parent in parents_permid_list:
                parent_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )
                simulation_objects_children = utils.find_openbis_simulations(
                    self.openbis_session, parent_object, SIMULATION_EXPORT_TYPES
                )
                simulation_permid_set.update(
                    str(simulation_object.permId)
                    for simulation_object in simulation_objects_children
                )
        else:
            for idx, parent in enumerate(parents_permid_list):
                parent_object = utils.get_openbis_object(
                    self.openbis_session, sample_ident=parent
                )
                simulation_objects_children = utils.find_openbis_simulations(
                    self.openbis_session, parent_object, SIMULATION_EXPORT_TYPES
                )
                parent_simulation_permids = {
                    str(simulation_object.permId)
                    for simulation_object in simulation_objects_children
                }
                if idx == 0:
                    simulation_permid_set = parent_simulation_permids
                else:
                    simulation_permid_set.intersection_update(parent_simulation_permids)

        simulations = [
            utils.get_openbis_object(
                self.openbis_session,
                sample_ident=simulation_permid,
            )
            for simulation_permid in simulation_permid_set
        ]
        self.found_simulations_select_multiple.options = self._simulation_options(
            simulations
        )
        count = len(simulations)
        self.found_simulations_label.value = f"Found simulations: {count}"
        _popup(f"Found {count} simulation{'s' if count != 1 else ''}.")
        self.import_simulations_message_html.value = ""
        self.download_simulation_data_message_html.value = ""

    def clear_simulation_selection(self, _button=None):
        self.found_simulations_select_multiple.value = ()

    @staticmethod
    def _find_aiida_archive_dataset(aiida_node_object):
        archive_files = []
        for dataset in aiida_node_object.get_datasets() or []:
            for filename in dataset.file_list or []:
                if str(filename).lower().endswith(".aiida"):
                    archive_files.append((dataset, str(filename)))

        if not archive_files:
            raise ValueError("The linked AIIDA_NODE has no .aiida archive dataset.")
        if len(archive_files) > 1:
            raise ValueError(
                "The linked AIIDA_NODE has more than one .aiida archive file."
            )
        return archive_files[0]

    @staticmethod
    def _downloaded_dataset_path(destination, dataset, filename):
        expected_path = Path(destination) / str(dataset.permId) / filename
        if expected_path.is_file():
            return expected_path

        candidates = [
            path
            for path in Path(destination).rglob(Path(filename).name)
            if path.is_file()
        ]
        if len(candidates) != 1:
            raise FileNotFoundError(
                f"Could not locate downloaded openBIS file {filename}."
            )
        return candidates[0]

    def _import_aiida_archive(self, aiida_node_permid):
        aiida_node_object = utils.get_openbis_object(
            self.openbis_session,
            sample_ident=aiida_node_permid,
        )
        dataset, filename = self._find_aiida_archive_dataset(aiida_node_object)

        with tempfile.TemporaryDirectory(
            prefix="aiidalab-openbis-import-"
        ) as destination:
            dataset.download(files=[filename], destination=destination)
            archive_path = self._downloaded_dataset_path(
                destination,
                dataset,
                filename,
            )
            result = subprocess.run(
                ["verdi", "archive", "import", str(archive_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(message or "AiiDA archive import failed.")

        workchain_uuid = aiida_utils._openbis_property(aiida_node_object, "wfms_uuid")
        if not workchain_uuid:
            raise ValueError("The linked AIIDA_NODE has no workflow UUID.")
        return orm.load_node(workchain_uuid)

    @classmethod
    def _import_success_message(cls, simulations, workchain):
        simulation_names = cls._simulation_names(simulations)
        viewer_link = WORKCHAIN_VIEWERS.get(workchain.process_label)
        if viewer_link:
            notebook_link = f"{viewer_link}?pk={workchain.pk}"
            return (
                f'<a href="{html.escape(notebook_link, quote=True)}" target="_blank">'
                f"Imported AiiDA archive for {simulation_names}.</a>"
            )
        return (
            f"Imported AiiDA archive for {simulation_names}. "
            f"No viewer is configured for {html.escape(workchain.process_label)}."
        )

    def import_aiida_nodes(self, b):
        selected_simulations = self._selected_simulation_objects()
        if not selected_simulations:
            _popup("Select at least one simulation.")
            self.import_simulations_message_html.value = ""
            return

        archives, data_only = self._partition_simulations_by_archive(
            selected_simulations
        )
        links = []
        notices = []
        for archive_id, simulations in archives.items():
            try:
                workchain = self._import_aiida_archive(archive_id)
                aiida_utils.record_openbis_exports(self.openbis_session, simulations)
            except Exception as error:  # noqa: BLE001 - surface import errors in UI
                notices.append(
                    f"Could not import the AiiDA archive for "
                    f"{self._simulation_names(simulations)}: {error}"
                )
            else:
                links.append(self._import_success_message(simulations, workchain))

        if data_only:
            notices.append(
                f"{self._simulation_names(data_only)} has no linked AiiDA archive; "
                "use Download data instead."
            )

        self.import_simulations_message_html.value = (
            "<ul>" + "".join(f"<li>{link}</li>" for link in links) + "</ul>"
            if links
            else ""
        )
        if notices:
            _popup(" ".join(notices))

    @staticmethod
    def _dataset_type_code(dataset):
        return str(getattr(dataset.type, "code", dataset.type))

    @classmethod
    def _downloadable_datasets(cls, simulation):
        return [
            dataset
            for dataset in simulation.get_datasets() or []
            if cls._dataset_type_code(dataset) != "ELN_PREVIEW"
        ]

    @classmethod
    def _prepare_archive_download(
        cls, openbis_session, archive_ids, download_root=None
    ):
        root = Path(download_root or _DOWNLOAD_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        destination = Path(
            tempfile.mkdtemp(
                prefix="openbis-aiida-archives-",
                dir=str(root),
            )
        )
        try:
            for archive_id in archive_ids:
                aiida_node = utils.get_openbis_object(
                    openbis_session, sample_ident=archive_id
                )
                dataset, filename = cls._find_aiida_archive_dataset(aiida_node)
                dataset.download(files=[filename], destination=str(destination))
            downloaded_files = sorted(
                path for path in destination.rglob("*.aiida") if path.is_file()
            )
            if not downloaded_files:
                raise ValueError("No linked .aiida archives could be downloaded.")
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        return destination, downloaded_files

    @classmethod
    def _prepare_data_download(cls, simulations, download_root=None):
        root = Path(download_root or _DOWNLOAD_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        destination = Path(
            tempfile.mkdtemp(
                prefix="openbis-simulation-data-",
                dir=str(root),
            )
        )

        try:
            downloaded_datasets = set()
            for simulation in simulations:
                for dataset in cls._downloadable_datasets(simulation):
                    dataset_id = str(dataset.permId)
                    if dataset_id in downloaded_datasets:
                        continue
                    dataset.download(destination=str(destination))
                    downloaded_datasets.add(dataset_id)

            downloaded_files = sorted(
                path for path in destination.rglob("*") if path.is_file()
            )
            if not downloaded_files:
                raise ValueError(
                    "The selected data-only simulations have no downloadable "
                    "non-preview datasets."
                )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

        return destination, downloaded_files

    @staticmethod
    def _remove_download_after_delay(path, delay_seconds):
        time.sleep(delay_seconds)
        shutil.rmtree(path, ignore_errors=True)

    @classmethod
    def _schedule_download_cleanup(cls, path):
        threading.Thread(
            target=cls._remove_download_after_delay,
            args=(path, _DOWNLOAD_LIFETIME_SECONDS),
            daemon=True,
        ).start()

    def download_simulation_data(self, b):
        selected_simulations = self._selected_simulation_objects()
        if not selected_simulations:
            _popup("Select at least one simulation.")
            return

        archives, data_only = self._partition_simulations_by_archive(
            selected_simulations
        )
        prepared = []
        errors = []
        if archives:
            try:
                prepared.append(
                    self._prepare_archive_download(
                        self.openbis_session, tuple(archives)
                    )
                )
            except Exception as error:  # noqa: BLE001 - surface download errors in UI
                errors.append(f"AiiDA archives: {error}")
        if data_only:
            try:
                prepared.append(self._prepare_data_download(data_only))
            except Exception as error:  # noqa: BLE001 - surface download errors in UI
                errors.append(f"Data-only simulations: {error}")

        if not prepared:
            _popup("Could not prepare the download. " + " ".join(errors))
            self.download_simulation_data_message_html.value = ""
            return

        links = []
        for download_directory, downloaded_files in prepared:
            for downloaded_file in downloaded_files:
                relative_path = downloaded_file.relative_to(Path.home())
                href = f"/files/{quote(relative_path.as_posix(), safe='/')}"
                label = downloaded_file.relative_to(download_directory).as_posix()
                links.append(
                    f'<a href="{html.escape(href, quote=True)}" '
                    f'download="{html.escape(downloaded_file.name, quote=True)}" '
                    'target="_blank">'
                    f"{html.escape(label)}</a>"
                )
            self._schedule_download_cleanup(download_directory)

        self.download_simulation_data_message_html.value = (
            "Download: " + ", ".join(links) + ". "
            "These temporary links expire after 10 minutes."
        )
        if errors:
            _popup("Some selected data could not be prepared. " + " ".join(errors))

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
        self._provenance_overrides = {
            "Code": {},
            "Computer": {},
            "Executable": {},
        }
        self._pending_reference_resolution = None
        self._executable_selection_widgets = {}

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

        self.provenance_resolution_box = ipw.VBox()
        self.executable_resolution_box = ipw.VBox()
        self.executable_confirmation_message = ipw.HTML()
        self.export_message_html = ipw.HTML()

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
            self.provenance_resolution_box,
            self.executable_resolution_box,
            self.executable_confirmation_message,
            self.save_simulations_button,
            self.export_message_html,
        ]

    def load_simulations_details_widgets(self, change):
        used_aiida = self.used_aiida_checkbox.value
        self.simulation_details_vbox.load_widgets(used_aiida)

    @staticmethod
    def _resolution_options(openbis_options, create_label):
        options = [("Select an existing object...", "")]
        options.extend(
            (f"{name} ({permid})", permid)
            for permid, name in sorted(
                openbis_options, key=lambda item: (item[1].lower(), item[0])
            )
        )
        options.append((create_label, _CREATE_NEW))
        return options

    def _show_reference_resolution(self, error):
        kind = error.object_kind
        selector = ipw.Dropdown(
            options=self._resolution_options(
                error.openbis_options, f"Create a new {kind.upper()}..."
            ),
            description=f"{kind}:",
            layout=ipw.Layout(width="95%"),
        )
        name = ipw.Text(
            value=error.aiida_label,
            description="Name:",
            layout=ipw.Layout(width="95%"),
        )
        description = ipw.Textarea(
            value=error.aiida_description,
            description="Description:",
            layout=ipw.Layout(width="95%"),
        )
        status = ipw.HTML()

        fields = [name, description]
        collection = None
        url = None
        location = None
        if kind == "Code":
            url_match = re.search(r"https?://[^\s]+", error.aiida_description)
            suggested_url = url_match.group(0).rstrip(".,);") if url_match else ""
            url = ipw.Text(
                value=suggested_url,
                description="URL:",
                layout=ipw.Layout(width="95%"),
            )
            collection = ipw.Dropdown(
                options=[
                    ("Custom/open software", OPENBIS_COLLECTIONS_PATHS["Custom Code"]),
                    (
                        "Proprietary software",
                        OPENBIS_COLLECTIONS_PATHS["Proprietary Code"],
                    ),
                ],
                description="Collection:",
                layout=ipw.Layout(width="95%"),
            )
            fields.extend([url, collection])
        else:
            text = f"{error.aiida_label} {error.aiida_description}".lower()
            external = any(word in text for word in ("daint", "alps", "cluster", "hpc"))
            collection = ipw.Dropdown(
                options=[
                    (
                        "Local Empa computer",
                        OPENBIS_COLLECTIONS_PATHS["Computer Local"],
                    ),
                    (
                        "External/HPC resource",
                        OPENBIS_COLLECTIONS_PATHS["Computer External"],
                    ),
                ],
                value=(
                    OPENBIS_COLLECTIONS_PATHS["Computer External"]
                    if external
                    else OPENBIS_COLLECTIONS_PATHS["Computer Local"]
                ),
                description="Collection:",
                layout=ipw.Layout(width="95%"),
            )
            organisations = list(
                utils.get_openbis_objects(self.openbis_session, type="ORGANISATION")
                or []
            )
            organisation_options = [("Select a location...", "")]
            organisation_options.extend(
                (
                    (f"{aiida_utils._openbis_property(obj, 'name')} ({obj.permId})"),
                    obj.permId,
                )
                for obj in sorted(
                    organisations,
                    key=lambda obj: str(
                        aiida_utils._openbis_property(obj, "name") or ""
                    ).lower(),
                )
            )
            location = ipw.Dropdown(
                options=organisation_options,
                description="Location:",
                layout=ipw.Layout(width="95%"),
            )
            fields.extend([location, collection])

        new_fields = ipw.VBox(
            fields,
            layout=ipw.Layout(display="none"),
        )

        def toggle_new_fields(change):
            new_fields.layout.display = "" if change["new"] == _CREATE_NEW else "none"

        selector.observe(toggle_new_fields, names="value")
        self._pending_reference_resolution = {
            "kind": kind,
            "aiida_uuid": error.aiida_uuid,
            "selector": selector,
            "name": name,
            "description": description,
            "url": url,
            "collection": collection,
            "location": location,
            "new_fields": new_fields,
            "status": status,
        }
        available = "".join(
            f"<li>{html.escape(str(name))} ({html.escape(str(permid))})</li>"
            for permid, name in sorted(
                error.openbis_options, key=lambda item: (item[1].lower(), item[0])
            )
        )
        self.provenance_resolution_box.children = [
            ipw.HTML(
                "<p><b>Resolve AiiDA provenance before export</b></p>"
                "<p><b>AiiDAlab identifiers</b></p><ul>"
                f"<li>Name: {html.escape(error.aiida_label)}</li>"
                f"<li>Description: {html.escape(error.aiida_description or 'none')}</li>"
                "</ul>"
                f"<p><b>Available openBIS {html.escape(kind.upper())} objects</b></p>"
                f"<ul>{available or '<li>none</li>'}</ul>"
                "<p>Select the intended existing object, or create it below. "
                "Then click Save again.</p>"
            ),
            selector,
            new_fields,
            status,
        ]
        self.executable_resolution_box.children = []
        self.executable_confirmation_message.value = ""

    def _apply_pending_reference_resolution(self):
        pending = self._pending_reference_resolution
        if pending is None:
            return True

        selected = pending["selector"].value
        if not selected:
            pending["status"].value = (
                "<p style='color:#b00020'>Select an existing object or "
                "choose Create new.</p>"
            )
            return False

        kind = pending["kind"]
        if selected == _CREATE_NEW:
            name = pending["name"].value.strip()
            if not name:
                pending[
                    "status"
                ].value = "<p style='color:#b00020'>Name is required.</p>"
                return False
            exact_name_matches = list(
                self.openbis_session.get_objects(
                    type=OPENBIS_OBJECT_TYPES[kind],
                    where={"NAME": name},
                )
                or []
            )
            duplicate = next(
                (
                    obj
                    for obj in exact_name_matches
                    if aiida_utils._normalize_object_name(
                        aiida_utils._openbis_property(obj, "name")
                    )
                    == aiida_utils._normalize_object_name(name)
                ),
                None,
            )
            if duplicate is not None:
                pending["status"].value = (
                    "<p style='color:#b00020'>An openBIS "
                    f"{kind.upper()} named {html.escape(name)} already exists "
                    f"({duplicate.permId}). Select it from the existing-object "
                    "list instead.</p>"
                )
                return False

            properties = {
                "name": name,
                "description": pending["description"].value.strip(),
            }
            if kind == "Code":
                url = pending["url"].value.strip()
                if url:
                    properties["url"] = url
                collection = pending["collection"].value
            else:
                location = pending["location"].value
                if not location:
                    pending[
                        "status"
                    ].value = (
                        "<p style='color:#b00020'>A computer location is required.</p>"
                    )
                    return False
                properties["location"] = location
                collection = pending["collection"].value

            try:
                selected_object = utils.create_openbis_object(
                    self.openbis_session,
                    type=OPENBIS_OBJECT_TYPES[kind],
                    props=properties,
                    collection=collection,
                )
            except Exception as error:  # noqa: BLE001 - surface pyBIS errors in UI
                pending["status"].value = (
                    "<p style='color:#b00020'>Could not create the openBIS "
                    f"{kind.upper()}: {html.escape(str(error))}</p>"
                )
                return False
            selected = selected_object.permId

        self._provenance_overrides[kind][pending["aiida_uuid"]] = selected
        self._pending_reference_resolution = None
        self.provenance_resolution_box.children = []
        return True

    def _show_missing_executables(self, error):
        rows = []
        selectors = {}
        for requirement in error.requirements:
            details = (
                "<ul>"
                f"<li><b>AiiDAlab code:</b> {html.escape(requirement['full_label'])}</li>"
                f"<li><b>openBIS code:</b> {html.escape(str(requirement['code_name']))}</li>"
                f"<li><b>openBIS computer:</b> {html.escape(str(requirement['computer_name']))}</li>"
                f"<li><b>Executable path:</b> {html.escape(str(requirement['executable_path']))}</li>"
                f"<li><b>Plugin:</b> {html.escape(str(requirement['plugin']))}</li>"
                "</ul>"
            )
            selector = ipw.Dropdown(
                options=[
                    ("Select an existing executable or create one...", ""),
                    *[
                        (f"{name} ({permid})", permid)
                        for permid, name in sorted(
                            requirement["executable_options"],
                            key=lambda item: (item[1].lower(), item[0]),
                        )
                    ],
                    ("Create a new EXECUTABLE", _CREATE_NEW),
                ],
                value="",
                description="Executable:",
                layout=ipw.Layout(width="95%"),
            )
            selectors[requirement["aiida_code_uuid"]] = selector
            rows.extend([ipw.HTML(details), selector])

        self._executable_selection_widgets = selectors
        self.executable_resolution_box.children = rows
        self.executable_confirmation_message.value = (
            "<p><b>Resolve missing executable records.</b></p>"
            "<p>Explicitly select an existing executable or choose Create new "
            "for every row, then click Save again. Nothing has been exported yet.</p>"
        )

    def _apply_executable_selections(self):
        create_missing = False
        for aiida_code_uuid, selector in self._executable_selection_widgets.items():
            if not selector.value:
                _popup("Resolve every missing executable before exporting.")
                return False, False
            if selector.value == _CREATE_NEW:
                create_missing = True
            else:
                self._provenance_overrides["Executable"][aiida_code_uuid] = (
                    selector.value
                )
        return True, create_missing

    def _clear_resolution_controls(self):
        self._pending_reference_resolution = None
        self._executable_selection_widgets = {}
        self.provenance_resolution_box.children = []
        self.executable_resolution_box.children = []
        self.executable_confirmation_message.value = ""

    def export_simulation_to_openbis(self, b):
        selected_experiment_id = self.select_experiment_widget.experiment_dropdown.value
        if selected_experiment_id in (None, "", "-1"):
            _popup("Select an experiment before exporting.")
            return
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
                    _popup("Select a simulation.")
                else:
                    atom_model_parents = (
                        selected_slab + selected_molecules_ids + selected_reac_prods_ids
                    )
                    if not self._apply_pending_reference_resolution():
                        return
                    selections_valid, create_missing = (
                        self._apply_executable_selections()
                    )
                    if not selections_valid:
                        return
                    try:
                        preview_overrides = (
                            self.simulation_details_vbox.preview_overrides()
                        )
                        exported = aiida_utils.export_workchain(
                            self.openbis_session,
                            selected_experiment_id,
                            selected_simulation_id,
                            create_missing_executables=create_missing,
                            provenance_overrides=self._provenance_overrides,
                            preview_overrides=preview_overrides,
                        )
                    except aiida_utils.MissingExecutablesError as error:
                        self._show_missing_executables(error)
                        return
                    except aiida_utils.OpenbisNameMatchError as error:
                        self._show_reference_resolution(error)
                        return
                    except aiida_utils.ExecutableResolutionError as error:
                        _popup(f"Cannot map AiiDA provenance to openBIS: {error}")
                        return
                    except Exception as error:  # noqa: BLE001 - show export errors in UI
                        _popup(f"Could not export the simulation: {error}")
                        return

                    self._clear_resolution_controls()
                    exported_objects = aiida_utils.normalize_exported_objects(exported)
                    for exported_object in exported_objects:
                        if not getattr(exported_object, "_aiidalab_created", True):
                            continue
                        first_atom_model = utils.find_first_atomistic_model(
                            self.openbis_session,
                            exported_object,
                            OPENBIS_OBJECT_TYPES["Atomistic Model"],
                        )
                        if (
                            first_atom_model is not None
                            and len(first_atom_model.parents) == 0
                        ):
                            first_atom_model.parents = atom_model_parents
                            utils.update_openbis_object(first_atom_model)

                    links = []
                    for exported_object in exported_objects:
                        name = aiida_utils._openbis_property(exported_object, "name")
                        label = html.escape(str(name or exported_object.permId))
                        url = aiida_utils._openbis_eln_url(exported_object)
                        if url:
                            links.append(
                                f'<li><a href="{html.escape(url, quote=True)}" '
                                f'target="_blank">{label}</a></li>'
                            )
                        else:
                            links.append(f"<li>{label} ({exported_object.permId})</li>")
                    self.export_message_html.value = (
                        "<p>Simulation results in openBIS:</p><ul>"
                        + "".join(links)
                        + "</ul>"
                        if links
                        else ""
                    )
                    created_count = sum(
                        bool(getattr(obj, "_aiidalab_created", True))
                        for obj in exported_objects
                    )
                    existing_count = len(exported_objects) - created_count
                    if created_count and existing_count:
                        _popup(
                            f"Exported {created_count} new result(s); reused "
                            f"{existing_count} result(s) already present in this openBIS space."
                        )
                    elif created_count:
                        _popup(
                            f"Exported {created_count} simulation result(s) successfully."
                        )
                    elif existing_count:
                        _popup(
                            "All simulation results were already present in this "
                            "openBIS space. The existing links are shown below."
                        )
                    else:
                        _popup(
                            "No supported finished simulation result was found to export."
                        )

            else:
                simulation_type = (
                    self.simulation_details_vbox.simulation_type_dropdown.value
                )
                if simulation_type == "-1":
                    _popup("Select a simulation type.")
                    return

                atom_model_widget = self.simulation_details_vbox.atom_model_widget
                selected_atom_model_id = atom_model_widget.atom_model_dropdown.value
                simulation_parents = (
                    [] if selected_atom_model_id == "-1" else [selected_atom_model_id]
                )
                if (
                    simulation_type
                    != SIMULATION_EXPORT_TYPES["Unclassified Simulation"]
                    and not simulation_parents
                ):
                    _popup("Select the input atomistic model.")
                    return
                if not self.simulation_details_vbox.upload_image_preview_uploader.value:
                    _popup("Upload the required simulation preview image.")
                    return
                if not self.simulation_details_vbox.upload_datasets_uploader.value:
                    _popup("Upload the required input/output data bundle.")
                    return

                try:
                    simulation_props = self.simulation_details_vbox.simulation_properties_widget.values()
                    selected_executables = list(
                        self.simulation_details_vbox.executables_multi_selector.value
                    )
                    if selected_executables:
                        simulation_props["executables"] = selected_executables
                    simulation_obj = utils.create_openbis_object(
                        self.openbis_session,
                        type=simulation_type,
                        collection=selected_experiment_id,
                        parents=simulation_parents,
                        props=simulation_props,
                    )
                    utils.upload_datasets(
                        self.openbis_session,
                        simulation_obj,
                        self.simulation_details_vbox.upload_image_preview_uploader,
                        props={},
                        dataset_type="ELN_PREVIEW",
                    )
                    utils.upload_datasets(
                        self.openbis_session,
                        simulation_obj,
                        self.simulation_details_vbox.upload_datasets_uploader,
                        props={},
                        dataset_type="RAW_DATA",
                    )
                except Exception as error:  # noqa: BLE001 - show openBIS errors in UI
                    _popup(f"Could not export the simulation: {error}")
                    return

                url = aiida_utils._openbis_eln_url(simulation_obj)
                name = aiida_utils._openbis_property(simulation_obj, "name")
                label = html.escape(str(name or simulation_obj.permId))
                self.export_message_html.value = (
                    f'<p>Simulation in openBIS: <a href="{html.escape(url, quote=True)}" '
                    f'target="_blank">{label}</a></p>'
                    if url
                    else f"<p>Simulation in openBIS: {label} ({simulation_obj.permId})</p>"
                )
                _popup("Simulation exported successfully.")


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
            description="Add molecule",
            disabled=False,
            button_style="success",
            tooltip="Add molecule",
            layout=ipw.Layout(width="150px", height="25px"),
        )

        self.reacprod_concepts_accordion = ipw.Accordion()
        reaction_products_available = (
            "Reaction Product Concept" in widgets.OPENBIS_OBJECT_TYPES
        )
        self.add_reacprod_concept_button = ipw.Button(
            description=(
                "Add reaction product concept"
                if reaction_products_available
                else "Reaction products unavailable"
            ),
            disabled=not reaction_products_available,
            button_style="success",
            tooltip=(
                "Add reaction product concept"
                if reaction_products_available
                else "The connected openBIS schema has no REACTION_PRODUCT_CONCEPT type"
            ),
            layout=ipw.Layout(width="230px", height="25px"),
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

        self.preview_suggestions_title = ipw.HTML(
            value=(
                "<span style='font-weight: bold; font-size: 18px;'>"
                "ELN preview suggestions</span>"
            )
        )
        self.preview_suggestions_status = ipw.HTML()
        self.preview_suggestions_box = ipw.VBox()
        self._preview_entries = {}

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

        self.select_executables_title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>Select executables</span>"
        )

        self.executables_label = ipw.Label(value="Executables")
        executable_objects = list(
            utils.get_openbis_objects(
                self.openbis_session, type=OPENBIS_OBJECT_TYPES["Executable"]
            )
            or []
        )
        executable_options = [
            (details, permid)
            for permid, details in aiida_utils._openbis_executable_options(
                self.openbis_session, executable_objects
            )
        ]
        self.executables_multi_selector = ipw.SelectMultiple(
            options=executable_options, layout=ipw.Layout(width="850px", height="120px")
        )
        self.executables_hbox = ipw.HBox(
            children=[self.executables_label, self.executables_multi_selector]
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

        self.simulations_dropdown.observe(
            self.load_aiida_preview_suggestions, names="value"
        )
        self.simulation_type_dropdown.observe(
            self.load_simulation_type_properties, names="value"
        )
        self.material_type_dropdown.observe(
            self.load_material_type_widgets, names="value"
        )
        self.add_molecule_button.on_click(self.add_molecule)
        self.add_reacprod_concept_button.on_click(self.add_reacprod_concept)

    def load_aiida_preview_suggestions(self, change=None):
        self._preview_entries = {}
        self.preview_suggestions_box.children = []
        selected_simulation = self.simulations_dropdown.value
        if selected_simulation == "-1":
            self.preview_suggestions_status.value = ""
            return

        self.preview_suggestions_status.value = "<p>Preparing preview suggestions…</p>"
        try:
            suggestions = aiida_utils.render_workchain_preview_suggestions(
                selected_simulation
            )
        except Exception as error:  # noqa: BLE001 - surface preview errors in UI
            self.preview_suggestions_status.value = (
                "<p style='color:#b00020'>Could not prepare ELN previews: "
                f"{html.escape(str(error))}</p>"
            )
            return

        cards = []
        for suggestion in suggestions:
            content = suggestion["content"]
            preview = (
                ipw.Image(
                    value=content,
                    format="png",
                    layout=ipw.Layout(max_width="560px", height="auto"),
                )
                if content is not None
                else ipw.HTML(
                    "<p style='color:#b00020'>No suggestion could be generated: "
                    f"{html.escape(str(suggestion['error']))}</p>"
                )
            )
            preview_box = ipw.VBox([preview])
            uploader = ipw.FileUpload(
                accept=".jpg,.jpeg,.png", multiple=False, description="Replace preview"
            )
            status = ipw.HTML(
                "<p>Suggested image will be used unless you replace it.</p>"
                if content is not None
                else "<p>Drop a replacement image here before exporting.</p>"
            )

            def show_replacement(
                _change, uploader=uploader, preview_box=preview_box, status=status
            ):
                uploaded = _first_uploaded_file(uploader)
                if uploaded is None:
                    return
                preview_box.children = [
                    ipw.Image(
                        value=uploaded["content"],
                        format=_image_format(uploaded["name"]),
                        layout=ipw.Layout(max_width="560px", height="auto"),
                    )
                ]
                status.value = (
                    "<p style='color:#237804'>Replacement image selected.</p>"
                )

            uploader.observe(show_replacement, names="value")
            self._preview_entries[suggestion["key"]] = {
                "suggestion": suggestion,
                "uploader": uploader,
            }
            cards.append(
                ipw.VBox(
                    [
                        ipw.HTML(f"<b>{html.escape(suggestion['title'])}</b>"),
                        preview_box,
                        uploader,
                        status,
                    ],
                    layout=ipw.Layout(
                        border="1px solid #cccccc", padding="10px", margin="4px 0"
                    ),
                )
            )

        self.preview_suggestions_box.children = cards
        self.preview_suggestions_status.value = (
            f"<p>Prepared {len(cards)} ELN preview suggestion(s). "
            "Review each image or drop a replacement before exporting.</p>"
            if cards
            else "<p>No supported simulation result previews were found.</p>"
        )

    def preview_overrides(self):
        if not self._preview_entries:
            raise ValueError(
                "No ELN preview suggestions are ready. Reselect the simulation "
                "to prepare them."
            )

        previews = {}
        for key, entry in self._preview_entries.items():
            uploaded = _first_uploaded_file(entry["uploader"])
            suggestion = entry["suggestion"]
            selected = uploaded or (
                {"name": suggestion["name"], "content": suggestion["content"]}
                if suggestion["content"] is not None
                else None
            )
            if selected is None:
                raise ValueError(
                    f"A replacement preview is required for {suggestion['title']}."
                )
            previews[key] = selected
        return previews

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
                self.preview_suggestions_title,
                self.preview_suggestions_status,
                self.preview_suggestions_box,
            ]

        else:
            self.children = [
                self.select_simulation_type_title,
                self.simulation_type_hbox,
                self.simulation_properties_widget,
                self.select_atom_model_title,
                self.atom_model_widget,
                self.select_executables_title,
                self.executables_hbox,
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
    """Schema-driven editor for manual, non-AiiDA simulation records."""

    _EXCLUDED_PROPERTIES = frozenset(
        {
            "EXECUTABLES",
            "AIIDA_NODE",
            "AIIDA_SOURCE_UUID",
            "AIIDA_RESULT_ROLE",
        }
    )

    def __init__(self, openbis_session):
        super().__init__()
        self.openbis_session = openbis_session
        self.simulation_type = ""
        self.fields = {}
        self.assignments = []
        self.title = ipw.HTML(
            value="<span style='font-weight: bold; font-size: 18px;'>"
            "Simulation properties</span>"
        )

    @staticmethod
    def _vocabulary_options(property_definition):
        vocabulary = property_definition.get("vocabulary")
        return [
            (label, label)
            for _code, label in simulation_schema.VOCABULARIES.get(vocabulary, [])
        ]

    @classmethod
    def _field_widget(cls, property_definition, mandatory):
        data_type = property_definition["dataType"]
        label = property_definition["label"] + (" *" if mandatory else "")
        style = {"description_width": "220px"}
        layout = ipw.Layout(width="850px")
        if data_type == "BOOLEAN":
            return ipw.Checkbox(description=label, indent=False)
        if data_type == "MULTILINE_VARCHAR":
            return ipw.Textarea(description=label, style=style, layout=layout)
        if data_type == "CONTROLLEDVOCABULARY":
            options = cls._vocabulary_options(property_definition)
            if property_definition.get("multiValue"):
                return ipw.SelectMultiple(
                    options=options,
                    description=label,
                    style=style,
                    layout=ipw.Layout(width="850px", height="100px"),
                )
            return ipw.Dropdown(
                options=[("Select...", "")] + options,
                description=label,
                style=style,
                layout=layout,
            )
        placeholder = ""
        if data_type == "REAL" and property_definition.get("multiValue"):
            placeholder = "Comma-separated numeric values"
        elif data_type in {"REAL", "INTEGER"}:
            placeholder = "Numeric value"
        return ipw.Text(
            description=label,
            placeholder=placeholder,
            style=style,
            layout=layout,
        )

    def load_widgets(self, simulation_type):
        self.simulation_type = simulation_type
        self.fields = {}
        self.assignments = []
        if simulation_type not in simulation_schema.OBJECT_TYPES:
            self.children = []
            return

        sections = {}
        for assignment in simulation_schema.OBJECT_TYPES[simulation_type][
            "assignments"
        ]:
            code = assignment["code"]
            if code in self._EXCLUDED_PROPERTIES:
                continue
            definition = simulation_schema.PROPERTY_TYPES[code]
            widget = self._field_widget(definition, assignment["mandatory"])
            self.fields[code] = widget
            self.assignments.append(assignment)
            sections.setdefault(assignment["section"], []).append(widget)

        children = [self.title]
        for section, section_fields in sections.items():
            children.append(ipw.HTML(f"<h4>{html.escape(section)}</h4>"))
            children.extend(section_fields)
        self.children = children

    def values(self):
        """Validate widgets and return lower-case pyBIS property values."""
        properties = {}
        missing = []
        for assignment in self.assignments:
            code = assignment["code"]
            definition = simulation_schema.PROPERTY_TYPES[code]
            widget = self.fields[code]
            value = widget.value
            data_type = definition["dataType"]

            if data_type == "BOOLEAN":
                if assignment["mandatory"] or value:
                    properties[code.lower()] = bool(value)
                continue
            if definition.get("multiValue"):
                if data_type == "REAL":
                    raw_values = [
                        item.strip() for item in str(value).split(",") if item.strip()
                    ]
                    try:
                        value = [float(item) for item in raw_values]
                    except ValueError as error:
                        raise ValueError(
                            f"{definition['label']} must contain numbers."
                        ) from error
                else:
                    value = list(value)
            else:
                value = str(value).strip()
                if value and data_type == "REAL":
                    try:
                        value = float(value)
                    except ValueError as error:
                        raise ValueError(
                            f"{definition['label']} must be a number."
                        ) from error
                elif value and data_type == "INTEGER":
                    try:
                        value = int(value)
                    except ValueError as error:
                        raise ValueError(
                            f"{definition['label']} must be an integer."
                        ) from error

            if value in ("", [], ()):  # optional fields are omitted from pyBIS
                if assignment["mandatory"]:
                    missing.append(definition["label"])
                continue
            properties[code.lower()] = value

        if missing:
            raise ValueError("Complete the required fields: " + ", ".join(missing))
        return properties
