import html
import json
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from difflib import SequenceMatcher
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
_FUZZY_MATCH_THRESHOLD = 65
_FUZZY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "very",
    "with",
}


def _popup(message):
    """Show a compact notebook popup without interpolating JavaScript code."""
    display(Javascript(data=f"alert({json.dumps(str(message))})"))


def _first_uploaded_file(files_widget):
    """Return one uploaded file in a stable internal representation."""
    uploaded = utils.uploaded_files(files_widget)
    return uploaded[0] if uploaded else None


def _image_format(filename):
    return "jpeg" if Path(filename).suffix.lower() in {".jpg", ".jpeg"} else "png"


_AIIDA_ROOT_UUID_RE = re.compile(
    r"^AiiDA root process UUID:\s*([0-9a-fA-F-]{36})\s*$",
    re.MULTILINE,
)


def _archive_root_processes(archive_path):
    """Return process roots stored in an AiiDA archive without importing it."""
    from aiida.storage.sqlite_zip.backend import SqliteZipBackend

    storage = SqliteZipBackend(SqliteZipBackend.create_profile(str(archive_path)))
    try:
        processes = (
            orm.QueryBuilder(backend=storage)
            .append(orm.ProcessNode, project="*")
            .all(flat=True)
        )
        roots = [
            {
                "uuid": str(process.uuid),
                "process_label": str(process.process_label or process.node_type),
            }
            for process in processes
            if process.caller is None
        ]
        return tuple(sorted(roots, key=lambda item: item["uuid"]))
    finally:
        storage.close()


def _declared_archive_root_uuids(aiida_node_object):
    """Read root UUID markers from an AIIDA_NODE, including older records."""
    roots = []
    workflow_uuid = aiida_utils._openbis_property(aiida_node_object, "wfms_uuid")
    if workflow_uuid:
        roots.append(str(workflow_uuid))
    root_uuids = aiida_utils._openbis_property(
        aiida_node_object, "aiida_root_uuids"
    )
    if isinstance(root_uuids, str):
        roots.append(root_uuids)
    elif root_uuids:
        roots.extend(str(uuid) for uuid in root_uuids)
    # Records created before AIIDA_ROOT_UUIDS was introduced stored roots in
    # COMMENTS. Keep this read-only fallback until those records are migrated.
    comments = aiida_utils._openbis_property(aiida_node_object, "comments") or ""
    roots.extend(_AIIDA_ROOT_UUID_RE.findall(str(comments)))
    return tuple(dict.fromkeys(roots))


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
            value=(
                "<span style='font-weight: bold; font-size: 20px;'>"
                "Select material or slab</span>"
            )
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

        search_text_style = {"description_width": "120px"}
        search_text_layout = ipw.Layout(width="600px")
        self.name_search_text = ipw.Text(
            description="Name",
            placeholder="Optional name search",
            style=search_text_style,
            layout=search_text_layout,
        )
        self.comments_search_text = ipw.Text(
            description="Comments",
            placeholder="Optional comments search",
            style=search_text_style,
            layout=search_text_layout,
        )
        self.text_match_mode_dropdown = ipw.Dropdown(
            description="Text matching",
            options=[
                ("Fuzzy (typo tolerant)", "fuzzy"),
                ("Contains all words", "all_words"),
            ],
            value="fuzzy",
            style=search_text_style,
            layout=ipw.Layout(width="380px"),
        )
        simulation_type_options = [("All simulation types", "")]
        simulation_type_options.extend(SIMULATION_TYPES.items())
        self.simulation_type_search_dropdown = ipw.Dropdown(
            description="Simulation type",
            options=simulation_type_options,
            value="",
            style=search_text_style,
            layout=ipw.Layout(width="380px"),
        )
        self.archive_status_dropdown = ipw.Dropdown(
            description="Archive status",
            options=[
                ("All", "all"),
                ("AiiDA archive", "archive"),
                ("Data only", "data_only"),
            ],
            value="all",
            style=search_text_style,
            layout=ipw.Layout(width="380px"),
        )
        self.search_filters_box = ipw.VBox(
            [
                self.name_search_text,
                self.comments_search_text,
                self.text_match_mode_dropdown,
                self.simulation_type_search_dropdown,
                self.archive_status_dropdown,
            ]
        )

        self.search_logical_operator_label = ipw.Label(value="Match materials:")
        self.search_logical_operator_dropdown = ipw.Dropdown(
            value="AND",
            options=[
                ("All selected materials", "AND"),
                ("Any selected material", "OR"),
            ],
            disabled=True,
            layout=ipw.Layout(width="230px"),
        )
        self.search_button = ipw.Button(
            description="Search",
            disabled=False,
            icon="search",
            tooltip="Search simulations in openBIS",
            layout=ipw.Layout(width="110px", height="30px"),
        )
        self.search_logical_operator_hbox = ipw.HBox(
            children=[
                self.search_logical_operator_label,
                self.search_logical_operator_dropdown,
                self.search_button,
            ]
        )
        self.search_operator_help = ipw.HTML(
            value=(
                "<small>No material filters selected: all simulations are searched. "
                "All/Any applies only when two or more materials are selected.</small>"
            )
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
            disabled=True,
            layout=ipw.Layout(width="180px", height="50px"),
        )
        self.download_simulation_data_button = ipw.Button(
            description="Download data",
            tooltip="Download data files or linked .aiida archives in the browser",
            icon="download",
            disabled=True,
            layout=ipw.Layout(width="180px", height="50px"),
        )
        self._simulation_archive_by_permid = {}

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
        self.material_type_dropdown.observe(
            self._update_material_match_controls, names="value"
        )
        self.molecules_accordion.observe(
            self._update_material_match_controls, names="children"
        )
        self.reacprod_concepts_accordion.observe(
            self._update_material_match_controls, names="children"
        )
        self.add_molecule_button.on_click(self.add_molecule)
        self.add_reacprod_concept_button.on_click(self.add_reacprod_concept)
        self.search_button.on_click(self.search_simulations)
        self.import_simulations_button.on_click(self.import_aiida_nodes)
        self.download_simulation_data_button.on_click(self.download_simulation_data)
        self.clear_simulations_button.on_click(self.clear_simulation_selection)
        self.found_simulations_select_multiple.observe(
            self._update_action_buttons, names="value"
        )

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
            self.search_filters_box,
            self.search_logical_operator_hbox,
            self.search_operator_help,
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
    def _normalize_search_text(value):
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = "".join(
            character
            for character in normalized
            if not unicodedata.combining(character)
        )
        return " ".join(normalized.casefold().split())

    @classmethod
    def _search_words(cls, value, remove_stopwords=False):
        words = re.findall(r"[a-z0-9]+", cls._normalize_search_text(value))
        if remove_stopwords:
            significant = [word for word in words if word not in _FUZZY_STOPWORDS]
            if significant:
                return significant
        return words

    @classmethod
    def _fuzzy_score(cls, query, candidate):
        query = cls._normalize_search_text(query)
        candidate = cls._normalize_search_text(candidate)
        if not query or not candidate:
            return 0
        if query == candidate:
            return 100

        character_score = 100 * SequenceMatcher(None, query, candidate).ratio()
        if query in candidate:
            character_score = max(character_score, 95)

        query_words = cls._search_words(query, remove_stopwords=True)
        candidate_words = cls._search_words(candidate, remove_stopwords=True)
        token_score = 0
        if query_words and candidate_words:
            token_score = (
                100
                * sum(
                    max(
                        SequenceMatcher(None, query_word, candidate_word).ratio()
                        for candidate_word in candidate_words
                    )
                    for query_word in query_words
                )
                / len(query_words)
            )

        sorted_word_score = (
            100
            * SequenceMatcher(
                None,
                " ".join(sorted(query_words)),
                " ".join(sorted(candidate_words)),
            ).ratio()
        )
        return round(max(character_score, token_score, sorted_word_score))

    @classmethod
    def _text_matches(cls, query, candidate, mode):
        if not cls._normalize_search_text(query):
            return True, 100
        if mode == "all_words":
            query_words = cls._search_words(query)
            candidate_words = set(cls._search_words(candidate))
            matches = bool(query_words) and all(
                word in candidate_words for word in query_words
            )
            return matches, 100 if matches else 0

        score = cls._fuzzy_score(query, candidate)
        return score >= _FUZZY_MATCH_THRESHOLD, score

    @staticmethod
    def _simulation_type_code(simulation):
        return str(getattr(simulation.type, "code", simulation.type))

    @staticmethod
    def _simulation_has_archive(simulation):
        return bool(aiida_utils._openbis_property(simulation, "aiida_node"))

    @classmethod
    def _filter_simulations(
        cls,
        simulations,
        name_query="",
        comments_query="",
        match_mode="fuzzy",
        simulation_type="",
        archive_status="all",
    ):
        filtered = []
        scores = {}
        fuzzy_search_active = match_mode == "fuzzy" and (
            cls._normalize_search_text(name_query)
            or cls._normalize_search_text(comments_query)
        )

        for simulation in simulations:
            if (
                simulation_type
                and cls._simulation_type_code(simulation) != simulation_type
            ):
                continue

            has_archive = cls._simulation_has_archive(simulation)
            if archive_status == "archive" and not has_archive:
                continue
            if archive_status == "data_only" and has_archive:
                continue

            name = aiida_utils._openbis_property(simulation, "name") or ""
            comments = aiida_utils._openbis_property(simulation, "comments") or ""
            name_matches, name_score = cls._text_matches(name_query, name, match_mode)
            comments_match, comments_score = cls._text_matches(
                comments_query, comments, match_mode
            )
            if not name_matches or not comments_match:
                continue

            filtered.append(simulation)
            if fuzzy_search_active:
                active_scores = []
                if cls._normalize_search_text(name_query):
                    active_scores.append(name_score)
                if cls._normalize_search_text(comments_query):
                    active_scores.append(comments_score)
                scores[str(simulation.permId)] = round(
                    sum(active_scores) / len(active_scores)
                )

        return filtered, scores

    def _selected_parent_permids(self):
        parent_permids = []
        for molecule_widget in self.molecules_accordion.children:
            value = molecule_widget.dropdown.value
            if value not in (None, "", "-1"):
                parent_permids.append(str(value))

        if (
            self.material_type_dropdown.value != "-1"
            and self.material_details_vbox.children
        ):
            select_material_box = self.material_details_vbox.children[0]
            if select_material_box.children:
                value = select_material_box.children[0].value
                if value not in (None, "", "-1"):
                    parent_permids.append(str(value))

        for concept_widget in self.reacprod_concepts_accordion.children:
            value = concept_widget.dropdown.value
            if value not in (None, "", "-1"):
                parent_permids.append(str(value))

        return parent_permids

    @staticmethod
    def _combine_simulation_permids(permid_sets, logical_operator):
        if not permid_sets:
            return set()
        combined = set(permid_sets[0])
        for permids in permid_sets[1:]:
            if logical_operator == "OR":
                combined.update(permids)
            else:
                combined.intersection_update(permids)
        return combined

    def _update_material_match_controls(self, _change=None):
        material_count = len(self._selected_parent_permids())
        self.search_logical_operator_dropdown.disabled = material_count < 2
        if material_count == 0:
            message = (
                "No material filters selected: all simulations are searched. "
                "All/Any applies only when two or more materials are selected."
            )
        elif material_count == 1:
            message = (
                "One material filter selected. Add another material to choose "
                "between matching all or any."
            )
        else:
            message = "All requires every selected material; Any requires at least one."
        self.search_operator_help.value = f"<small>{message}</small>"

    def _update_action_buttons(self, _change=None):
        selected = tuple(self.found_simulations_select_multiple.value)
        self.download_simulation_data_button.disabled = not selected
        self.import_simulations_button.disabled = not any(
            self._simulation_archive_by_permid.get(str(permid), False)
            for permid in selected
        )

    def _all_simulations(self, simulation_type=""):
        type_codes = (
            [simulation_type]
            if simulation_type
            else list(dict.fromkeys(SIMULATION_TYPES.values()))
        )
        simulations = {}
        for type_code in type_codes:
            objects = utils.get_openbis_objects(
                self.openbis_session,
                type=type_code,
            )
            if objects is None:
                continue
            for simulation in objects:
                simulations[str(simulation.permId)] = simulation
        return list(simulations.values())

    def _simulations_from_materials(self, parent_permids, logical_operator):
        simulations_by_permid = {}
        parent_result_sets = []
        for parent_permid in parent_permids:
            parent_object = utils.get_openbis_object(
                self.openbis_session,
                sample_ident=parent_permid,
            )
            simulations = utils.find_openbis_simulations(
                self.openbis_session,
                parent_object,
                SIMULATION_TYPES,
            )
            permids = set()
            for simulation in simulations:
                permid = str(simulation.permId)
                permids.add(permid)
                simulations_by_permid[permid] = simulation
            parent_result_sets.append(permids)

        selected_permids = self._combine_simulation_permids(
            parent_result_sets,
            logical_operator,
        )
        return [simulations_by_permid[permid] for permid in selected_permids]

    @staticmethod
    def _simulation_label(simulation, match_score=None):
        name = aiida_utils._openbis_property(simulation, "name") or simulation.permId
        type_code = getattr(simulation.type, "code", simulation.type)
        availability = (
            "AiiDA archive"
            if aiida_utils._openbis_property(simulation, "aiida_node")
            else "data only"
        )
        score_label = f" [{match_score}% match]" if match_score is not None else ""
        return (
            f"{name} - {type_code} ({simulation.permId}) "
            f"[{availability}]{score_label}"
        )

    @classmethod
    def _simulation_options(cls, simulations, scores=None):
        scores = scores or {}
        ordered = sorted(
            simulations,
            key=lambda item: (
                cls._simulation_label(item).lower(),
                str(item.permId),
            ),
        )
        ordered.sort(
            key=lambda item: str(getattr(item, "registrationDate", "") or ""),
            reverse=True,
        )
        if scores:
            ordered.sort(
                key=lambda item: scores.get(str(item.permId), 0),
                reverse=True,
            )
        return [
            (
                cls._simulation_label(
                    simulation,
                    match_score=scores.get(str(simulation.permId)),
                ),
                str(simulation.permId),
            )
            for simulation in ordered
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

    def _simulation_dependencies(self, selected_simulations):
        """Return selected simulations plus archive-bearing scientific ancestors."""
        simulation_types = set(SIMULATION_TYPES.values())
        traversable_types = simulation_types | {
            OPENBIS_OBJECT_TYPES["Atomistic Model"]
        }
        ordered = []
        visited = set()

        def visit(openbis_object):
            permid = str(openbis_object.permId)
            if permid in visited:
                return
            visited.add(permid)
            type_code = ImportSimulationsWidget._simulation_type_code(
                openbis_object
            )
            if type_code not in traversable_types:
                return

            for parent in getattr(openbis_object, "parents", ()) or ():
                if hasattr(parent, "permId"):
                    parent_object = parent
                else:
                    parent_object = utils.get_openbis_object(
                        self.openbis_session,
                        sample_ident=str(parent),
                    )
                visit(parent_object)

            if type_code in simulation_types:
                ordered.append(openbis_object)

        for simulation in selected_simulations:
            visit(simulation)
        return ordered

    def search_simulations(self, _button=None):
        parent_permids = self._selected_parent_permids()
        logical_operator = self.search_logical_operator_dropdown.value
        simulation_type = self.simulation_type_search_dropdown.value

        if parent_permids:
            simulations = self._simulations_from_materials(
                parent_permids,
                logical_operator,
            )
        else:
            simulations = self._all_simulations(simulation_type)

        simulations, scores = self._filter_simulations(
            simulations,
            name_query=self.name_search_text.value,
            comments_query=self.comments_search_text.value,
            match_mode=self.text_match_mode_dropdown.value,
            simulation_type=simulation_type,
            archive_status=self.archive_status_dropdown.value,
        )
        self._simulation_archive_by_permid = {
            str(simulation.permId): self._simulation_has_archive(simulation)
            for simulation in simulations
        }
        self.found_simulations_select_multiple.options = self._simulation_options(
            simulations,
            scores=scores,
        )
        self.found_simulations_select_multiple.value = ()
        count = len(simulations)
        self.found_simulations_label.value = f"Found simulations: {count}"
        self.import_simulations_message_html.value = ""
        self.download_simulation_data_message_html.value = ""
        self._update_action_buttons()

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
            archive_roots = tuple(
                item["uuid"] for item in _archive_root_processes(archive_path)
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

        root_uuids = archive_roots or _declared_archive_root_uuids(aiida_node_object)
        return tuple(orm.load_node(uuid) for uuid in root_uuids)

    @classmethod
    def _import_success_message(cls, simulations, workchains):
        simulation_names = cls._simulation_names(simulations)
        if workchains is None:
            workchains = ()
        elif not isinstance(workchains, (list, tuple)):
            workchains = (workchains,)
        else:
            workchains = tuple(workchains)
        if not workchains:
            return (
                f"Imported AiiDA archive for {simulation_names}. "
                "No root process was identified."
            )

        if len(workchains) == 1:
            workchain = workchains[0]
            viewer_link = WORKCHAIN_VIEWERS.get(workchain.process_label)
            if viewer_link:
                notebook_link = f"{viewer_link}?pk={workchain.pk}"
                return (
                    f'<a href="{html.escape(notebook_link, quote=True)}" target="_blank">'
                    f"Imported AiiDA archive for {simulation_names}.</a>"
                )
            return (
                f"Imported AiiDA archive for {simulation_names}. "
                f"Root UUID: {html.escape(str(workchain.uuid))}. "
                f"No viewer is configured for "
                f"{html.escape(workchain.process_label)}."
            )

        root_items = []
        for workchain in workchains:
            label = html.escape(workchain.process_label)
            uuid = html.escape(str(workchain.uuid))
            viewer_link = WORKCHAIN_VIEWERS.get(workchain.process_label)
            if viewer_link:
                notebook_link = html.escape(
                    f"{viewer_link}?pk={workchain.pk}",
                    quote=True,
                )
                root_items.append(
                    f'<li><a href="{notebook_link}" target="_blank">'
                    f"{label} - {uuid}</a></li>"
                )
            else:
                root_items.append(f"<li>{label} - {uuid}</li>")
        return (
            f"Imported AiiDA archive for {simulation_names}. "
            f"Root processes ({len(workchains)}):<ul>"
            + "".join(root_items)
            + "</ul>"
        )

    def import_aiida_nodes(self, b):
        selected_simulations = self._selected_simulation_objects()
        if not selected_simulations:
            _popup("Select at least one simulation.")
            self.import_simulations_message_html.value = ""
            return
        selected_simulations = ImportSimulationsWidget._simulation_dependencies(
            self, selected_simulations
        )

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
            self._update_material_match_controls()
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
            material_dropdown.observe(
                self._update_material_match_controls,
                names="value",
            )
            self._update_material_match_controls()

    def add_molecule(self, b):
        molecules_accordion_children = list(self.molecules_accordion.children)
        molecule_index = len(molecules_accordion_children)
        molecule_widget = widgets.MoleculeWidget(
            self.openbis_session, self.molecules_accordion, molecule_index
        )
        molecule_widget.dropdown.observe(
            self._update_material_match_controls,
            names="value",
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
        reacprod_concept_widget.dropdown.observe(
            self._update_material_match_controls,
            names="value",
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
                pending["status"].value = (
                    "<p style='color:#b00020'>Name is required.</p>"
                )
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
                    pending["status"].value = (
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
                self._provenance_overrides["Executable"][
                    aiida_code_uuid
                ] = selector.value
        return True, create_missing

    def _clear_resolution_controls(self):
        self._pending_reference_resolution = None
        self._executable_selection_widgets = {}
        self.provenance_resolution_box.children = []
        self.executable_resolution_box.children = []
        self.executable_confirmation_message.value = ""

    @staticmethod
    def _uploaded_aiida_archive(files_widget):
        archives = [
            uploaded_file
            for uploaded_file in utils.uploaded_files(files_widget)
            if Path(uploaded_file["name"]).suffix.lower() == ".aiida"
        ]
        if len(archives) > 1:
            raise ValueError(
                "Upload at most one .aiida archive in the input/output data bundle."
            )
        return archives[0] if archives else None

    def _create_manual_aiida_node(self, archive_file, simulation_name):
        with tempfile.TemporaryDirectory(
            prefix="aiidalab-openbis-manual-archive-"
        ) as dirname:
            archive_path = Path(dirname) / Path(archive_file["name"]).name
            archive_path.write_bytes(archive_file["content"])
            roots = _archive_root_processes(archive_path)

            properties = {
                "name": f"AiiDA archive for {simulation_name}",
                "description": (
                    "AiiDA provenance archive uploaded with a simulation record."
                ),
                "comments": "",
            }
            if roots:
                properties["aiida_root_uuids"] = [root["uuid"] for root in roots]
            if len(roots) == 1:
                properties["wfms_uuid"] = roots[0]["uuid"]

            aiida_node = utils.create_openbis_object(
                self.openbis_session,
                type=OPENBIS_OBJECT_TYPES["AiiDA Node"],
                collection=OPENBIS_COLLECTIONS_PATHS["AiiDA Node"],
                props=properties,
            )
            utils.create_openbis_dataset(
                self.openbis_session,
                type="RAW_DATA",
                sample=aiida_node,
                files=[archive_path],
            )
            return aiida_node

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
                        property_overrides = (
                            self.simulation_details_vbox.property_overrides()
                        )
                        exported = aiida_utils.export_workchain(
                            self.openbis_session,
                            selected_experiment_id,
                            selected_simulation_id,
                            create_missing_executables=create_missing,
                            provenance_overrides=self._provenance_overrides,
                            preview_overrides=preview_overrides,
                            property_overrides=property_overrides,
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
                    except (
                        Exception
                    ) as error:  # noqa: BLE001 - show export errors in UI
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
                    simulation_props = (
                        self.simulation_details_vbox.simulation_properties_widget.values()
                    )
                    selected_executables = list(
                        self.simulation_details_vbox.executables_multi_selector.value
                    )
                    if selected_executables:
                        simulation_props["executables"] = selected_executables

                    data_uploader = (
                        self.simulation_details_vbox.upload_datasets_uploader
                    )
                    archive_file = self._uploaded_aiida_archive(data_uploader)
                    if archive_file is not None:
                        aiida_node = self._create_manual_aiida_node(
                            archive_file,
                            simulation_props.get("name") or simulation_type,
                        )
                        simulation_props["aiida_node"] = str(aiida_node.permId)

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
                        data_uploader,
                        props={},
                        dataset_type="RAW_DATA",
                        filename_filter=lambda filename: (
                            Path(filename).suffix.lower() != ".aiida"
                        ),
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

        # The dropdown remains an internal selected-value carrier so the
        # export path stays unchanged; users identify the workflow directly.
        self.simulations_dropdown = ipw.Dropdown(
            options=[("No checked simulation", "-1")],
            value="-1",
        )
        self.simulation_pk_input = ipw.IntText(
            value=0,
            description="Workflow PK",
            style={"description_width": "100px"},
        )
        self.check_simulation_button = ipw.Button(
            description="Check",
            icon="check",
            tooltip="Validate this AiiDA workflow PK",
        )
        self.simulation_check_status = ipw.HTML()

        self.simulations_dropdown_hbox = ipw.HBox(
            children=[
                self.simulation_pk_input,
                self.check_simulation_button,
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

        self.check_simulation_button.on_click(self.check_aiida_simulation)
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

    @staticmethod
    def _exportable_ancestor(node):
        """Return the nearest directly or indirectly exportable WorkChain."""
        candidate = node
        if not getattr(candidate, "process_label", None):
            candidate = getattr(candidate, "creator", None)
        visited = set()
        while candidate is not None:
            uuid = str(getattr(candidate, "uuid", ""))
            if uuid in visited:
                break
            visited.add(uuid)
            if getattr(candidate, "process_label", "") in aiida_utils.workchain_exporters:
                return candidate
            # Container workflows such as QeAppWorkChain do not have a direct
            # exporter: one export action dispatches their supported child
            # WorkChains while keeping a single archive for the container.
            descendants = getattr(candidate, "called_descendants", ()) or ()
            if any(
                getattr(descendant, "process_label", "")
                in aiida_utils.workchain_exporters
                for descendant in descendants
            ):
                return candidate
            candidate = getattr(candidate, "caller", None)
        return None

    def check_aiida_simulation(self, _button=None):
        """Validate a PK and prepare previews only for supported WorkChains."""
        self.simulation_check_status.value = ""
        self.simulations_dropdown.options = [("No checked simulation", "-1")]
        self.simulations_dropdown.value = "-1"
        pk = int(self.simulation_pk_input.value or 0)
        if pk <= 0:
            self.simulation_check_status.value = (
                "<p style='color:#b00020'>Enter a valid positive PK.</p>"
            )
            return
        try:
            node = orm.load_node(pk)
        except Exception:  # noqa: BLE001 - AiiDA backend-specific not-found errors
            self.simulation_check_status.value = (
                f"<p style='color:#b00020'>No AiiDA node exists with PK {pk}.</p>"
            )
            return

        workchain = self._exportable_ancestor(node)
        if workchain is None:
            self.simulation_check_status.value = (
                f"<p style='color:#b00020'>PK {pk} is an intermediate step or "
                "belongs to an unsupported workflow, and no supported parent "
                "WorkChain was found.</p>"
            )
            return
        if not workchain.is_finished_ok:
            self.simulation_check_status.value = (
                f"<p style='color:#b00020'>Workflow PK {workchain.pk} is not "
                "finished successfully and cannot be exported.</p>"
            )
            return

        description = aiida_utils._workchain_description(workchain)
        suffix = f": {html.escape(description)}" if description else ""
        if workchain.pk != pk:
            prefix = (
                f"PK {pk} is an intermediate step. Use supported parent "
                f"WorkChain PK {workchain.pk}"
            )
        else:
            prefix = f"Supported {html.escape(workchain.process_label)} PK {pk}"
        self.simulation_check_status.value = (
            f"<p style='color:#237804'>{prefix}{suffix}</p>"
        )
        label = f"{workchain.process_label} (PK: {workchain.pk})"
        self.simulations_dropdown.options = [(label, workchain.pk)]
        self.simulations_dropdown.value = workchain.pk

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
            property_widget = SimulationPropertiesWidget(self.openbis_session)
            property_widget.load_widgets(suggestion["object_type"])
            property_widget.set_values(suggestion["properties"])
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
                "property_widget": property_widget,
            }
            cards.append(
                ipw.VBox(
                    [
                        ipw.HTML(f"<b>{html.escape(suggestion['title'])}</b>"),
                        ipw.HTML(
                            "<p>Review or edit the automatically derived openBIS "
                            "fields below.</p>"
                        ),
                        property_widget,
                        ipw.HTML("<b>ELN preview</b>"),
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

    def property_overrides(self):
        if not self._preview_entries:
            raise ValueError(
                "No simulation field suggestions are ready. Reselect the simulation "
                "to prepare them."
            )
        return {
            key: entry["property_widget"].values(include_empty=True)
            for key, entry in self._preview_entries.items()
        }

    def load_simulation_type_properties(self, change):
        simulation_type = self.simulation_type_dropdown.value
        self.simulation_properties_widget.load_widgets(simulation_type)

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
                self.simulation_check_status,
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
            (label, code)
            for code, label in simulation_schema.VOCABULARIES.get(vocabulary, [])
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

    def set_values(self, properties):
        """Populate assigned fields from lower-case pyBIS property values."""
        for code, widget in self.fields.items():
            definition = simulation_schema.PROPERTY_TYPES[code]
            key = code.lower()
            if key not in properties or properties[key] is None:
                continue
            value = properties[key]
            if definition.get("multiValue"):
                if definition["dataType"] == "REAL":
                    widget.value = ", ".join(str(item) for item in value)
                else:
                    widget.value = tuple(value)
            elif definition["dataType"] == "BOOLEAN":
                widget.value = bool(value)
            else:
                widget.value = str(value)

    def values(self, include_empty=False):
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
                if assignment["mandatory"] or value or include_empty:
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
                elif include_empty:
                    properties[code.lower()] = None
                continue
            properties[code.lower()] = value

        if missing:
            raise ValueError("Complete the required fields: " + ", ".join(missing))
        if self.simulation_type == "MINIMUM_ENERGY_PATH":
            method = properties.get("mep_method")
            conditional = {
                "NEB": ("neb_variant", "NEB variant"),
                "REPLICA_CHAIN": (
                    "collective_variables",
                    "Collective variables",
                ),
                "OTHER": (
                    "other_method_description",
                    "Other MEP method description",
                ),
            }
            required = conditional.get(method)
            if required and not properties.get(required[0]):
                raise ValueError(
                    f"{required[1]} is required when MEP method is {method}."
                )
        return properties
