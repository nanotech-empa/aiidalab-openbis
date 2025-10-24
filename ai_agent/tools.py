from langchain_core.tools import tool
from . import openbis_utils
from pydantic import BaseModel, Field, model_validator
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
import subprocess
import shutil
from langchain.schema import Document
from langchain_text_splitters.character import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_openai import OpenAIEmbeddings

# from langchain_anthropic import AnthropicEmbeddings
import json
from langchain_chroma import Chroma
import os


# Pydantic models for input validation
class OpenBISObjectArgs(BaseModel):
    permId: Optional[str] = Field(
        default="", description="PermID of the openBIS object"
    )
    name: Optional[str] = Field(default="", description="Name of the openBIS object")


class MoleculeArgs(OpenBISObjectArgs):
    empa_number: Optional[int] = Field(
        default=0, description="Empa number that identifies the molecule in "
    )
    smiles: Optional[str] = Field(default="", description="SMILES string, e.g. 'CCO'")
    sum_formula: Optional[str] = Field(
        default="", description="Molecular sum formula, e.g. 'CH4'"
    )
    iupac_name: Optional[str] = Field(
        default="", description="IUPAC name, e.g. 'benzene'"
    )


class SubstanceArgs(OpenBISObjectArgs):
    empa_number: Optional[int] = Field(
        default=0, description="Empa identifier number, e.g. 704"
    )
    batch: Optional[str] = Field(
        default="", description="Batch letter of the substance, e.g. 'a'"
    )
    molecules: Optional[List[MoleculeArgs]] = Field(
        default_factory=list,
        description="A list of one or more molecules that describe the substance.",
    )


class ReacProdConceptArgs(OpenBISObjectArgs):
    sum_formula: Optional[str] = Field(
        default="", description="Molecular sum formula, e.g. 'CH4'"
    )
    molecules: Optional[List[MoleculeArgs]] = Field(
        default_factory=list,
        description="A list of one or more molecules that describe the reaction product.",
    )


class ReacProdArgs(OpenBISObjectArgs):
    reacprod_concept: Optional[ReacProdConceptArgs] = Field(
        default_factory=list, description="Reaction product theoretical concept."
    )


class CrystalConceptArgs(OpenBISObjectArgs):
    face: Optional[str] = Field(
        default="", description="Material face, e.g. 111 or 10000"
    )
    material: Optional[str] = Field(
        default="", description="Crystal material, e.g. Au, Pt, Ag, Pd"
    )


class CrystalArgs(OpenBISObjectArgs):
    crystal_concept: Optional[CrystalConceptArgs] = Field(
        default=None,
        description="Crystal concept that contains properties of the crystal",
    )
    face: Optional[str] = Field(
        default="", description="Material face, e.g. 111 or 10000"
    )
    material: Optional[str] = Field(
        default="", description="Crystal material, e.g. Au, Pt, Ag, Pd"
    )


class TwoDLayerMaterialArgs(OpenBISObjectArgs):
    top_layer_material: Optional[str] = Field(
        default="", description="Top layer material"
    )
    layer_count: Optional[str] = Field(
        default="", description="Number of layers in string"
    )
    substrate: Optional[str] = Field(default="", description="Substrate material")
    growth_method: Optional[str] = Field(
        default="", description="Growth/Fabrication method"
    )


class ObjectStatusEnum(str, Enum):
    Active = "Active"
    Broken = "Broken"
    Disposed = "Disposed"
    Inactive = "Inactive"


class SampleArgs(OpenBISObjectArgs):
    object_status: ObjectStatusEnum = Field(
        default="", title="Object status", description="Current status of the object"
    )


class TimestampInterval(BaseModel):
    begin_date_str: str = Field(
        ...,
        description="Datetime in format YYYY-MM-DD HH:MM:SS, e.g., '2025-07-25 08:30:00'",
    )
    end_date_str: str = Field(
        ...,
        description="Datetime in format YYYY-MM-DD HH:MM:SS, e.g., '2025-07-25 18:30:00'",
    )

    @model_validator(mode="after")
    def validate_datetime_order(self) -> "TimestampInterval":
        try:
            begin = datetime.strptime(self.begin_date_str, "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(self.end_date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            raise ValueError(f"Invalid datetime format: {e}")

        if begin >= end:
            raise ValueError("begin_date_str must be earlier than end_date_str")

        return self


# Functions
def read_json(filename: str) -> dict:
    with open(filename, "r") as file:
        return json.load(file)


def auto_label(type_str: str) -> str:
    return type_str.replace("_", " ").title()


def crystal_found(obj, crystal):
    if not obj or not crystal.crystal_concept:
        return False

    obj_props = obj.props.all()
    crystal_concept_permId = obj_props.get("crystal_concept")
    if not crystal_concept_permId:
        return False

    crystal_concept_obj = openbis_utils.get_openbis_object(crystal_concept_permId)
    if not crystal_concept_obj:
        return False

    crystal_concept_props = crystal_concept_obj.props.all()

    if (
        crystal.crystal_concept.face
        and crystal.crystal_concept.face != crystal_concept_props.get("face")
    ):
        return False
    if (
        crystal.crystal_concept.material
        and crystal.crystal_concept.material != crystal_concept_props.get("material")
    ):
        return False

    return True


def substance_found(obj, substance):
    if not obj:
        return False

    obj_props = obj.props.all()
    obj_empa_number = int(obj_props.get("empa_number") or 0)
    obj_batch = obj_props.get("batch") or ""
    obj_molecules = obj_props.get("molecules") or []

    if substance.empa_number > 0 and obj_empa_number != substance.empa_number:
        return False

    if substance.batch and obj_batch != substance.batch:
        return False

    if substance.molecules:
        if not obj_molecules:
            return False

        for prompt_molecule in substance.molecules:
            matched = False
            for molecule_permId in obj_molecules:
                molecule_obj = openbis_utils.get_openbis_object(molecule_permId)
                molecule_props = molecule_obj.props.all()

                if (
                    prompt_molecule.smiles
                    and prompt_molecule.smiles != molecule_props.get("smiles")
                ):
                    continue
                if (
                    prompt_molecule.sum_formula
                    and prompt_molecule.sum_formula != molecule_props.get("sum_formula")
                ):
                    continue
                if (
                    prompt_molecule.iupac_name
                    and prompt_molecule.iupac_name != molecule_props.get("iupac_name")
                ):
                    continue

                matched = True
                break

            if not matched:
                return False

    return True


def reacprod_concept_found(obj, reacprod_concept):
    if not obj:
        return False

    obj_props = obj.props.all()
    obj_name = obj_props.get("name")
    obj_molecules = obj_props.get("molecules") or []

    if reacprod_concept.name and obj_name != reacprod_concept.name:
        return False

    if reacprod_concept.molecules:
        if not obj_molecules:
            return False

        for prompt_molecule in reacprod_concept.molecules:
            matched = False
            for molecule_permId in obj_molecules:
                molecule_obj = openbis_utils.get_openbis_object(molecule_permId)
                molecule_props = molecule_obj.props.all()

                if (
                    prompt_molecule.smiles
                    and prompt_molecule.smiles != molecule_props.get("smiles")
                ):
                    continue
                if (
                    prompt_molecule.sum_formula
                    and prompt_molecule.sum_formula != molecule_props.get("sum_formula")
                ):
                    continue
                if (
                    prompt_molecule.iupac_name
                    and prompt_molecule.iupac_name != molecule_props.get("iupac_name")
                ):
                    continue

                matched = True
                break

            if not matched:
                return False

    return True


def reacprod_found(obj, reac_prod):
    if not obj:
        return False

    obj_props = obj.props.all()
    obj_name = obj_props.get("name")
    obj_concept_id = obj_props.get("reaction_product_concept")

    if reac_prod.name and obj_name != reac_prod.name:
        return False

    if reac_prod.reacprod_concept:
        if not obj_concept_id:
            return False

        reacprod_concept = openbis_utils.get_openbis_object(obj_concept_id)
        reacprod_props = reacprod_concept.props.all()

        if reac_prod.reacprod_concept.sum_formula:
            if (
                reacprod_props.get("sum_formula")
                != reac_prod.reacprod_concept.sum_formula
            ):
                return False

        if reac_prod.reacprod_concept.molecules:
            reacprod_concept_molecules = reacprod_props.get("molecules") or []
            if not reacprod_concept_molecules:
                return False

            for prompt_mol in reac_prod.reacprod_concept.molecules:
                matched = False
                for mol_id in reacprod_concept_molecules:
                    molecule_obj = openbis_utils.get_openbis_object(mol_id)
                    mol_props = molecule_obj.props.all()
                    mol_empa_number = int(mol_props.get("empa_number") or 0)

                    if (
                        prompt_mol.empa_number
                        and prompt_mol.empa_number != mol_empa_number
                    ):
                        continue
                    if prompt_mol.smiles and prompt_mol.smiles != mol_props.get(
                        "smiles"
                    ):
                        continue
                    if (
                        prompt_mol.sum_formula
                        and prompt_mol.sum_formula != mol_props.get("sum_formula")
                    ):
                        continue
                    if prompt_mol.iupac_name and prompt_mol.iupac_name != mol_props.get(
                        "iupac_name"
                    ):
                        continue

                    matched = True
                    break

                if not matched:
                    return False

    return True


def create_vectorDB(db_path, embedding_model, chunks):
    if os.path.exists(db_path):
        vectordb = Chroma(persist_directory=db_path, embedding_function=embedding_model)

        existing_ids = set()
        for doc in vectordb.get(include=["metadatas"])["metadatas"]:
            if doc and "permId" in doc:
                existing_ids.add(doc["permId"])

        new_docs = []
        for doc in chunks:
            doc_id = doc.metadata["permId"]
            if doc_id not in existing_ids:
                new_docs.append(doc)

        if new_docs:
            vectordb.add_documents(new_docs)
    else:
        vectordb = Chroma.from_documents(
            chunks, embedding_model, persist_directory=db_path
        )

    return vectordb


SIMULATION_TYPES = [
    "ATOMISTIC_MODEL",
    "BAND_STRUCTURE",
    "GEOMETRY_OPTIMISATION",
    "STM_SIMULATION",
    "MINIMUM_ENERGY_POTENTIAL",
    "PDOS",
    "POTENTIAL_ENERGY_CALCULATION",
    "SIMULATION",
    "UNCLASSIFIED_SIMULATION",
    "VIBRATIONAL_SPECTROSCOPY",
]


# Generic openBIS tools
@tool
def get_openbis_objects(obj_type: str) -> List[str]:
    """
    Return list of openBIS object permIDs based on the object type.

    Args:
        obj_type (str): openBIS object type
    Return:
        objects_data: List of strings with the names and the permIDs in parenthesis of all the objects found.

    E.g.:
        User: Give me all instruments in openBIS
        Tool: get_openbis_objects(obj_type="INSTRUMENT")
        Tool: get_openbis_objects(obj_type="INSTRUMENT.STM")
    """
    objects = openbis_utils.get_openbis_objects(type=obj_type, props=["name"])

    objects_data = []
    for obj in objects:
        objects_data.append(f"Object {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_openbis_object_by_permId(permId: str) -> Dict:
    """
    Return an object available in openBIS by permanent ID (permId). PermId follows the following
    pattern: YYYYMMDDHHMMSSmmm-####. Example: 20250717115421436-984.

    Args:
        permId (str): openBIS object permanent ID (permId). Follows the pattern YYYYMMDDHHMMSSmmm-####.
        Example: 20250717115421436-984

    """
    obj = openbis_utils.get_openbis_object(permId)
    obj_data = openbis_utils.get_openbis_object_data(obj)

    return obj_data


@tool
def get_openbis_objects_by_name(name: str) -> List[str]:
    """
    Search openBIS objects by name and return all the permIDs of the matching objects.

    Args:
        name (str): openBIS object name
    """
    objects = openbis_utils.get_openbis_objects(
        where={"name": name},
    )
    objects_data = []
    for obj in objects:
        objects_data.append(f"The permID of the object is {obj.permId}.")

    return objects_data


@tool
def get_openbis_objects_by_date(time_interval: TimestampInterval) -> List[str]:
    """
    Search objects in openBIS registered between a given time interval and return the permIDs of the matching objects.

    Args:
        time_interval: An object containing:
            - begin_date_str (str): Start of the time interval in format YYYY-MM-DD HH:MM:SS
            - end_date_str (str): End of the time interval in format YYYY-MM-DD HH:MM:SS

    Returns:
        A list of strings with openBIS objects permIDs matching the interval.
    """
    begin_date = datetime.strptime(time_interval.begin_date_str, "%Y-%m-%d %H:%M:%S")
    end_date = datetime.strptime(time_interval.end_date_str, "%Y-%m-%d %H:%M:%S")

    objects = openbis_utils.get_openbis_objects()
    objects_data = []
    for obj in objects:
        obj_registration_date = datetime.strptime(
            obj.registrationDate, "%Y-%m-%d %H:%M:%S"
        )
        if begin_date <= obj_registration_date and end_date >= obj_registration_date:
            objects_data.append(f"The permID of the object is {obj.permId}.")

    return objects_data


# @tool
def get_openbis_objects_by_description(description: str) -> List[Dict]:
    """
    Return objects available in openBIS by description.
    """
    objects = openbis_utils.get_openbis_objects()
    objects_data = []
    for obj in objects:
        obj_props = obj.props.all()
        obj_description = obj_props.get("description", "")
        # TODO: Here the tool needs to check by similarity and not by equality
        if obj_description == description:
            objects_data.append(f"The permID of the object is {obj.permId}.")

    return objects_data


# Specific tools
# Inventory
@tool
def get_reacprods_by_properties(reac_prod: ReacProdArgs) -> List[str]:
    """
    Search for reaction products in openBIS using one or more identifying attributes.

    This tool retrieves reaction products permIDs by matching the given properties. These permIDs
    can then be used to retrieve more information about the reaction products.

    Unprovided fields will be ignored in the search.

    Args:
        reac_prod (ReacProdArgs): A data object describing the reaction product to search for. It may include:
            - name (str, optional): Name
            - reacprod_concept (ReacProdConceptArgs, optional): Theoretical version of the reaction product
                The reaction product concept may include:
                    - sum_formula (str, optional): Molecular sum formula
                    - molecules (List[MoleculeArgs], optional): A list of one or more molecules that describe the substance.
                        Each molecule may include:
                            - name (str, optional): Name
                            - smiles (str, optional): SMILES string, e.g. "CCO"
                            - empa_number (str, optional): Empa identifier, e.g. 650
                            - sum_formula (str, optional): Molecular sum formula, e.g. "CH4"
                            - iupac_name (str, optional): IUPAC name, e.g. "benzene"

    Returns:
        List[str]: List of strings with the names and the permIDs in parenthesis of all
        the reaction products in openBIS that match the input.
    """

    obj_type = "REACTION_PRODUCT"
    objects = openbis_utils.get_openbis_objects(type=obj_type, props=["name"])
    objects_data = []
    for obj in objects:
        load_obj_data = reacprod_found(obj, reac_prod)
        if load_obj_data:
            objects_data.append(f"Reaction Product {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_substances_by_properties(substance: SubstanceArgs) -> List[str]:
    """
    Search for substances in openBIS using one or more identifying attributes.

    This tool retrieves substances permIDs by matching the given Empa identifier (empa number and batch together), e.g.
    704a (empa number is 704 and batch is a), or any molecular descriptor (SMILES, sum formula, IUPAC name).
    You can specify any subset of these fields. These permIDs can then be used to retrieve more information about the substances.

    Unprovided fields will be ignored in the search. Sometimes the users
    might call the substance as molecule. So be aware of that. If they ask for a molecule by the empa number and the batch,
    e.g, 650a, it means that they want the substance with that empa number and batch.

    Args:
        substance (SubstanceArgs): A data object describing the substance to search for. It may include:
            - empa_number (int, optional): Empa identifier number, e.g. 704.
            - batch (str, optional): Batch letter of the substance, e.g. 'a'.
            - molecules (List[MoleculeArgs], optional): A list of one or more molecules that describe the substance.
              Each molecule may include:
                - smiles (str, optional): SMILES string, e.g. "CCO"
                - sum_formula (str, optional): Molecular sum formula, e.g. "CH4"
                - iupac_name (str, optional): IUPAC name, e.g. "benzene"

    Returns:
        List[str]: List of strings with the names and the permIDs in parenthesis of all the substances in openBIS that match the input.

    Example:
        >>> get_substances_by_attributes(
        ...     SubstanceArgs(
        ...         empa_number=704,
        ...         batch="a",
        ...         molecules=[MoleculeArgs(smiles="CCO")]
        ...     )
        ... )
        # Returns all matching substance objects permIDs with Empa ID 704a and containing a molecule with SMILES "CCO".
    """

    obj_type = "SUBSTANCE"
    objects = openbis_utils.get_openbis_objects(type=obj_type, props=["name"])
    objects_data = []
    for obj in objects:
        load_obj_data = substance_found(obj, substance)
        if load_obj_data:
            objects_data.append(f"Substance {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_crystals_by_properties(crystal: CrystalArgs) -> List[str]:
    """
    Search for crystals in openBIS using one or more identifying attributes.

    This tool retrieves crystals permIDs by matching the given crystal concept descriptor (face, material).
    You can specify any subset of these fields. Unprovided fields will be ignored in the search.
    These permIDs can then be used to retrieve more information about the substances.

    If the user asks for crystals Au111 or Gold-111, its means that one wants crystals with a crystal
    concept with material Au and face 111.

    Args:
        crystal (CrystalArgs): A data object describing the crystal to search for. It may include:
            - crystal_concept (CrystalConceptArgs, optional): crystal concept that contains properties of the crystal
              Each crystal_concept may include:
                - face (str, optional): Material face, e.g. 111 or 10000
                - material (str, optional): Crystal material, e.g. Au, Pt, Ag, Pd

    Returns:
        List[str]: List of strings with the names and the permIDs in parenthesis of all the crystals in openBIS that match the input.

    Example:
        >>> get_crystals_by_attributes(
        ...     CrystalArgs(
        ...         crystal_concept=[CrystalConceptArgs(face="111", material="Au")]
        ...     )
        ... )
        # Returns all matching crystal objects permIDs containing a crystal concept with face 111 and material Au.
    """
    obj_type = "CRYSTAL"
    objects = openbis_utils.get_openbis_objects(type=obj_type, props=["name"])
    objects_data = []
    for obj in objects:
        load_obj_data = crystal_found(obj, crystal)
        if load_obj_data:
            objects_data.append(f"Crystal {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_2d_materials_by_properties(two_d_material: TwoDLayerMaterialArgs) -> List[str]:
    """
    Search for 2D layer materials in openBIS using one or more identifying attributes.

    This tool retrieves 2D layer materials permIDs by matching the given top layer material, layer count,
    substrate, growth/fabrication method.

    You can specify any subset of these fields. Unprovided fields will be ignored in the search.

    These permIDs can then be used to retrieve more information about the substances.

    Args:
        two_d_material (TwoDLayerMaterialArgs): A data object describing the 2d layer material
        to search for. It may include:
            - top_layer_material (str, optional): Top layer material
            - layer_count (str, optional): Number of layers in string
            - substrate (str, optional): Substrate material
            - growth_method (str, optional): Growth/Fabrication method

    Returns:
        List[str]: List of strings with the names and the permIDs in parenthesis of all the 2D layer materials in openBIS that match the input.

    Example:
        >>> get_2d_materials_by_attributes(
        ...     TwoDLayerMaterialArgs(
        ...         top_layer_material='MoS2'
        ...     )
        ... )
        # Returns all matching 2d later material objects permIDs
    """

    obj_type = "2D_LAYER_MATERIAL"
    query_parameters = {}
    if two_d_material.top_layer_material:
        query_parameters["top_layer_material"] = two_d_material.top_layer_material

    if two_d_material.layer_count:
        query_parameters["layer_count"] = two_d_material.layer_count

    if two_d_material.substrate:
        query_parameters["substrate"] = two_d_material.substrate

    if two_d_material.growth_method:
        query_parameters["growth_method"] = two_d_material.growth_method

    objects = openbis_utils.get_openbis_objects(
        type=obj_type, where=query_parameters, props=["name"]
    )
    objects_data = []

    for obj in objects:
        objects_data.append(f"2D layer material {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_measurements_by_sample(sample: SampleArgs) -> List[str]:
    """
    Get all the measurements that were done using the sample chosen by the user.

    Args:
        sample (SampleArgs): A data object describing the sample used for taking measurements. It may include:
            - permId(optional, str): PermID, e.g., 20250922145817954-468
            - name (optional, str): Name, e.g. 20250929143406_Au111_Gino:[IONB:HEAT]
    Return:
        List[str]: Summary of measurements performed using the input sample.
    """
    objects_data = []
    if sample.permId:
        obj = openbis_utils.get_openbis_object(sample.permId)
    else:
        query_parameters = {}
        if sample.name:
            query_parameters["name"] = sample.name

        objects = openbis_utils.get_openbis_objects(
            type="SAMPLE", props=["name"], attrs=["children"], where=query_parameters
        )

        if len(objects) == 0:
            return ["No sample was found."]
        elif len(objects) == 1:
            obj = objects[0]
        else:
            for obj in objects:
                objects_data.append(f"Sample {obj.props['name']} ({obj.permId}).")
            return objects_data

    measurements_summary = []
    stack = [(obj, obj.props["name"], obj.permId)]

    while stack:
        current_obj, current_name, current_id = stack.pop()

        for child in current_obj.children:
            child_obj = openbis_utils.get_openbis_object(child)
            if child_obj.type.code == "MEASUREMENT_SESSION":
                child_name = child_obj.props["name"] or "No name"
                child_id = child_obj.permId
                obj_type_label = auto_label(child_obj.type.code)
                measurements_summary.append(
                    f"- {obj_type_label}: {child_name} ({child_id}). It is child of {current_name} ({current_id})."
                )

                # push the child to stack so its children will also be explored
                stack.append((child_obj, child_name, child_id))

    return measurements_summary


# Simulations
@tool
def get_simulations_by_crystal_concept(
    crystal_concept: CrystalConceptArgs,
) -> List[str]:
    """
    Get all the simulations that were done using the crystal concept chosen by the user.

    Args:
        crystal_concept (CrystalConceptArgs): A data object describing the crystal concept to search for. It may include:
            - permId(optional, str): PermID, e.g., 20250922145817954-468
            - face (optional, str): Face, e.g. 111 or 11001
            - material (optional, str): Material, e.g. Au, Ag, Pt, etc.
    Return:
        List[str]: Summary of simulations performed using the input crystal concept. In case there are more than one possible crystal concepts,
        the function returns the names and permIDs with the crystal concepts in order for the user to pick the one that the user wants to search about.
    """
    objects_data = []
    obj_type = "CRYSTAL_CONCEPT"
    if crystal_concept.permId:
        obj = openbis_utils.get_openbis_object(crystal_concept.permId)
        if obj is None:
            return ["No crystal concept was found."]
    else:
        query_parameters = {}
        if crystal_concept.name:
            query_parameters["name"] = crystal_concept.name
        if crystal_concept.face:
            query_parameters["face"] = crystal_concept.face
        if crystal_concept.material:
            query_parameters["material"] = crystal_concept.material

        objects = openbis_utils.get_openbis_objects(
            type=obj_type, props=["name"], attrs=["children"], where=query_parameters
        )

        if len(objects) == 0:
            return ["No crystal concept was found."]
        elif len(objects) == 1:
            obj = objects[0]
        else:
            for obj in objects:
                objects_data.append(
                    f"Crystal concept {obj.props['name']} ({obj.permId})."
                )
            return objects_data

    simulations_summary = []
    stack = [(obj, obj.props["name"], obj.permId)]

    while stack:
        current_obj, current_name, current_id = stack.pop()

        for child in current_obj.children:
            child_obj = openbis_utils.get_openbis_object(child)
            child_name = child_obj.props["name"] or "No name"
            child_id = child_obj.permId

            if child_obj.type.code in SIMULATION_TYPES:
                obj_type_label = auto_label(child_obj.type.code)
                simulations_summary.append(
                    f"- {obj_type_label}: {child_name} ({child_id}). It is child of {current_name} ({current_id})."
                )

            # push the child to stack so its children will also be explored
            stack.append((child_obj, child_name, child_id))

    return simulations_summary


@tool
def get_simulations_by_molecule(molecule: MoleculeArgs) -> List[str]:
    """
    Get all the simulations that were done using the molecule chosen by the user.

    Args:
        molecule (MoleculeArgs): A data object describing the molecule to search for. It may include:
            - permId(optional, str): PermID, e.g., 20250922145817954-468
            - name (optional, str): Name, e.g. 704 or DBBA
            - empa_number (optional, str): Empa number, e.g. 700
            - smiles (optional, str): SMILES string, e.g. C or CCO
            - sum_formula (optional, str): Sum (chemical) formula, e.g. CH4
    Return:
        List[str]: Summary of simulations performed using the input molecule. In case there are more than one possible molecules,
        the function returns the names and permIDs with the molecules in order for the user to pick the one that the user wants to search about.
    """
    objects_data = []
    obj_type = "MOLECULE"
    if molecule.permId:
        obj = openbis_utils.get_openbis_object(molecule.permId)
        if obj is None:
            return ["No molecule was found."]
    else:
        query_parameters = {}
        if molecule.name:
            query_parameters["name"] = molecule.name
        if molecule.empa_number:
            query_parameters["empa_number"] = molecule.empa_number
        if molecule.smiles:
            query_parameters["smiles"] = molecule.smiles
        if molecule.sum_formula:
            query_parameters["sum_formula"] = molecule.sum_formula

        objects = openbis_utils.get_openbis_objects(
            type=obj_type, props=["name"], attrs=["children"], where=query_parameters
        )

        if len(objects) == 0:
            return ["No molecule was found."]
        elif len(objects) == 1:
            obj = objects[0]
        else:
            for obj in objects:
                objects_data.append(f"Molecule {obj.props['name']} ({obj.permId}).")
            return objects_data

    simulations_summary = []
    stack = [(obj, obj.props["name"], obj.permId)]

    while stack:
        current_obj, current_name, current_id = stack.pop()

        for child in current_obj.children:
            child_obj = openbis_utils.get_openbis_object(child)
            child_name = child_obj.props["name"] or "No name"
            child_id = child_obj.permId

            if child_obj.type.code in SIMULATION_TYPES:
                obj_type_label = auto_label(child_obj.type.code)
                simulations_summary.append(
                    f"- {obj_type_label}: {child_name} ({child_id}). It is child of {current_name} ({current_id})."
                )

            # push the child to stack so its children will also be explored
            stack.append((child_obj, child_name, child_id))

    return simulations_summary


@tool
def get_simulations_by_reacprod_concept(
    reacprod_concept: ReacProdConceptArgs,
) -> List[str]:
    """
    Get all the simulations that were done using the reaction product chosen by the user. Pay attention that
    reaction product are derived from molecules. The user may call them molecules. So if you dont find anything the user asked,
    ask the user if it is a molecule or a reaction product.

    Args:
        reacprod_concept (ReacProdConceptArgs): A data object describing the reaction product concept to search for. It may include:
            - permId(optional, str): PermID, e.g., 20250922145817954-468
            - name (optional, str): Name, e.g. 7AGNR
            - molecules (List[MoleculeArgs], optional): A list of one or more molecules used to create the reaction product concept.
              Each molecule may include:
                - smiles (str, optional): SMILES string, e.g. "CCO"
                - sum_formula (str, optional): Molecular sum formula, e.g. "CH4"
                - iupac_name (str, optional): IUPAC name, e.g. "benzene"
    Return:
        List[str]: Summary of simulations performed using the input reaction product concept. In case there are more than one
        possible reaction product concepts, the function returns the names and permIDs with the reaction product concepts
        in order for the user to pick the one that the user wants to search about.
    """
    objects_data = []
    obj_type = "REACTION_PRODUCT_CONCEPT"
    if reacprod_concept.permId:
        obj = openbis_utils.get_openbis_object(reacprod_concept.permId)
        if obj is None:
            return ["No reaction product concept was found."]
    else:
        objects = openbis_utils.get_openbis_objects(
            type=obj_type, props=["name"], attrs=["children"]
        )
        reacprod_concept_objects = []
        for obj in objects:
            load_obj_data = reacprod_concept_found(obj, reacprod_concept)
            if load_obj_data:
                reacprod_concept_objects.append(obj)

        if len(reacprod_concept_objects) == 0:
            return ["No reaction product concept was found."]
        elif len(reacprod_concept_objects) == 1:
            obj = reacprod_concept_objects[0]
        else:
            for obj in reacprod_concept_objects:
                objects_data.append(
                    f"Reaction product concept {obj.props['name']} ({obj.permId})."
                )
            return objects_data

    simulations_summary = []
    stack = [(obj, obj.props["name"], obj.permId)]

    while stack:
        current_obj, current_name, current_id = stack.pop()

        for child in current_obj.children:
            child_obj = openbis_utils.get_openbis_object(child)
            child_name = child_obj.props["name"] or "No name"
            child_id = child_obj.permId

            if child_obj.type.code in SIMULATION_TYPES:
                obj_type_label = auto_label(child_obj.type.code)
                simulations_summary.append(
                    f"- {obj_type_label}: {child_name} ({child_id}). It is child of {current_name} ({current_id})."
                )

            # push the child to stack so its children will also be explored
            stack.append((child_obj, child_name, child_id))

    return simulations_summary


@tool
def import_simulation_from_openbis(simulation_permid, human_response=False) -> str:
    """
    Import simulation from openBIS into AiiDAlab. For that, the function takes the simulation
    permID and downloads data from openBIS. This function returns a response that reports
    whether the import was successful or not.

    Args:
        simulation_permid (str): Permanent ID of the simulation that the user wants to import
        human_response (bool): Human response to import the simulation
    Returns:
        response (str): Response reporting the user if the import was successful
    """
    if human_response:
        if simulation_permid:
            simulation_obj = openbis_utils.get_openbis_object(simulation_permid)
            simulation_aiida_node = simulation_obj.props["aiida_node"]
            if simulation_aiida_node:
                aiida_node_datasets = simulation_aiida_node.get_datasets()
                for dataset in aiida_node_datasets:
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
                            response = "Simulation cannot be imported."
                        else:
                            response = "Simulation was imported successfully."

                        shutil.rmtree("aiida_nodes/")

                return response
            else:
                return "Simulation is not linked to any AiiDA node. It may mean that it was not made using AiiDA."
        else:
            return "Simulation was not found"
    else:
        return "Need human acceptance to import this."


# Experiments
@tool
def get_sample_provenance(sample: SampleArgs) -> str:
    """
    Return the summary of the processes performed during the sample preparation. It includes
    mainly the permIDs of the objects that are linked to the history of this sample.

    Args:
        sample (SampleArgs): Object of type Sample that contains the permID of the sample
    Return:
        sample_summary (str). Summary of the sample asked by the user

    Example:
    >>> get_sample_provenance(
    ...     Sample(
    ...         permId = '20250929123440615-4070'
    ...     )
    ... )
    Returns the history of the sample including all the connected process steps, samples,
    and first materials with some details about these as well.
    """
    sample_provenance = [f"Sample {sample.permId} provenance:"]
    openbis_obj = None
    if sample.permId:
        openbis_obj = openbis_utils.get_openbis_object(sample.permId)

    while openbis_obj:
        parents = openbis_obj.parents
        if parents:
            for parent in parents:
                parent_obj = openbis_utils.get_openbis_object(parent)
                if parent_obj.type.code == "SAMPLE":
                    parent_obj_permid = parent_obj.permId
                    openbis_obj_permid = openbis_obj.permId
                    sample_provenance.append(
                        f"- Sample: {parent_obj_permid} is parent of {openbis_obj_permid}."
                    )
                    openbis_obj = parent_obj
                    break

                elif parent_obj.type.code == "PROCESS_STEP":
                    openbis_obj_permid = openbis_obj.permId
                    parent_obj_permid = parent_obj.permId
                    parent_obj_props = parent_obj.props.all()
                    parent_obj_metadata = [
                        f"PermID: {parent_obj_permid}",
                        f"Name: {parent_obj_props['name']}",
                        f"Actions: {', '.join(parent_obj_props['actions'])}",
                        f"Observables: {', '.join(parent_obj_props['observables'])}",
                        f"Instrument: {parent_obj_props['instrument']}",
                    ]
                    parent_obj_metadata = ". ".join(parent_obj_metadata)
                    sample_provenance.append(
                        f"- Process Step: {parent_obj_metadata}. It is parent of {openbis_obj_permid}."
                    )
                    openbis_obj = parent_obj
                    break

                elif parent_obj.type.code in ["CRYSTAL", "2D_LAYER_MATERIAL"]:
                    parent_obj_metadata = parent_obj.permId
                    openbis_obj_metadata = openbis_obj.permId
                    sample_provenance.append(
                        f"- First material: {parent_obj_metadata} is parent of {openbis_obj_metadata}."
                    )
                    openbis_obj = parent_obj
                    break
        else:
            openbis_obj = None

    sample_summary = "\n".join(sample_provenance)

    return sample_summary


@tool
def get_samples_by_substance(input_substance: SubstanceArgs) -> List[str]:
    """
    Search for objects in openBIS of type SAMPLE that contains the input substance
    (was not removed from the surface yet). Only samples that are active or disposed are retrieved.

    Args:
        substance (SubstanceArgs): A data object describing the substance to search for. It may include:
            - permId (str, optional): Permanent ID of the substance in openBIS, e.g. 20250909093058356-304898.
            - name (str, optional): Name of the substance in openBIS, e.g., Pyrentetraon.
            - empa_number (str, optional): Empa number of the substance in openBIS, e.g., 704.
            - batch (str, optional): Batch of the substance in openBIS, e.g., a or b.
    Returns:
        List[str]: A list of strings, where each string contains the sample name and the sample permId from openBIS.
        In case there are more than one possible substance, the function returns the names and permIDs with the substances
        in order for the user to pick the one that the user wants to search about.
    """

    objects_data = []

    if input_substance.permId:
        input_substance_obj = openbis_utils.get_openbis_object(input_substance.permId)
        if input_substance_obj is None:
            return ["No substance was entered."]
    else:
        query_parameters = {}
        if input_substance.name:
            query_parameters["name"] = input_substance.name
        if input_substance.empa_number:
            query_parameters["empa_number"] = input_substance.empa_number
        if input_substance.batch:
            query_parameters["batch"] = input_substance.batch

        objects = openbis_utils.get_openbis_objects(
            type="SUBSTANCE", props=["name"], where=query_parameters
        )

        if len(objects) == 0:
            return ["No substance was entered."]
        elif len(objects) == 1:
            input_substance_obj = objects[0]
        else:
            for obj in objects:
                objects_data.append(f"Substance {obj.props['name']} ({obj.permId}).")
            return objects_data

    obj_type = "SAMPLE"
    samples_active = openbis_utils.get_openbis_objects(
        type=obj_type, attrs=["parents"], where={"object_status": "ACTIVE"}
    )

    samples_disposed = openbis_utils.get_openbis_objects(
        type=obj_type, attrs=["parents"], where={"object_status": "DISPOSED"}
    )

    # Merge both lists
    samples = list(samples_active) + list(samples_disposed)

    sample_found = False
    cleaned_sample = False
    for obj in samples:
        for parent in obj.parents:
            parent_obj = openbis_utils.get_openbis_object(parent)
            if parent_obj.type.code == "PROCESS_STEP":
                process_step_actions = parent_obj.props["actions"]
                for action in process_step_actions:
                    action_obj = openbis_utils.get_openbis_object(action)
                    if action_obj.type.code == "SPUTTERING":
                        cleaned_sample = True
                    elif action_obj.type.code == "DEPOSITION":
                        substance = action_obj.props["substance"]
                        if substance:
                            substance_obj = openbis_utils.get_openbis_object(substance)
                            if substance_obj.permId == input_substance_obj.permId:
                                sample_found = True

                    if sample_found:
                        break

                    if cleaned_sample:
                        break

            if sample_found:
                break

            if cleaned_sample:
                break

        if sample_found:
            objects_data.append(f"Sample {obj.props['name']} ({obj.permId})")

        cleaned_sample = False
        sample_found = False

    return objects_data


@tool
def get_samples_by_crystal(input_crystal: CrystalArgs) -> List[str]:
    """
    Search for samples in openBIS of (objects with type SAMPLE) that contains the input crystal.
    Only samples that are active or disposed are retrieved.

    Args:
        crystal (CrystalArgs): A data object describing the crystal to search for. It may include:
            - permId (str, optional): Permanent ID of the crystal in openBIS, e.g. 20250909093058356-304898.
            - name (str, optional): Name of the crystal in openBIS, e.g., Pyrentetraon.
            - face (optional, str): Face, e.g. 111 or 11001
            - material (optional, str): Material, e.g. Au, Ag, Pt, etc.
    Returns:
        List[str]: A list of strings, where each string contains the sample name and the sample permId from openBIS.
        In case there are more than one possible crystal, the function returns the names and permIDs with the crystals
        in order for the user to pick the one that the user wants to search about.
    """

    objects_data = []

    if input_crystal.permId:
        input_crystal_obj = openbis_utils.get_openbis_object(input_crystal.permId)
        if input_crystal_obj is None:
            return ["No crystal was entered."]
    else:
        query_parameters = {}
        if input_crystal.name:
            query_parameters["name"] = input_crystal.name
        if input_crystal.face:
            query_parameters["face"] = input_crystal.face
        if input_crystal.material:
            query_parameters["material"] = input_crystal.material

        objects = openbis_utils.get_openbis_objects(
            type="CRYSTAL", props=["name"], where=query_parameters
        )

        if len(objects) == 0:
            return ["No crystal was entered."]
        elif len(objects) == 1:
            input_crystal_obj = objects[0]
        else:
            for obj in objects:
                objects_data.append(f"Crystal {obj.props['name']} ({obj.permId}).")
            return objects_data

    obj_type = "SAMPLE"
    samples_active = openbis_utils.get_openbis_objects(
        type=obj_type, attrs=["parents"], where={"object_status": "ACTIVE"}
    )

    samples_disposed = openbis_utils.get_openbis_objects(
        type=obj_type, attrs=["parents"], where={"object_status": "DISPOSED"}
    )

    # Merge both lists
    samples = list(samples_active) + list(samples_disposed)

    objects_data = []
    for obj in samples:
        original_sample_permid = obj.permId
        original_sample_name = obj.props["name"]
        stack = [obj]

        while stack:
            current_obj = stack.pop()

            for parent in current_obj.parents:
                parent_obj = openbis_utils.get_openbis_object(parent)
                parent_name = parent_obj.props["name"] or "No name"
                parent_id = parent_obj.permId

                if parent_obj.type.code == "CRYSTAL":
                    if input_crystal_obj.permId == parent_obj.permId:
                        objects_data.append(
                            f"The sample {original_sample_name} ({original_sample_permid}) was made with the Crystal {parent_name} ({parent_id})."
                        )
                        stack = []
                        break
                else:
                    # push the parent to stack so its parents will also be explored
                    stack.append(parent_obj)

    return objects_data


@tool
def get_live_samples_by_properties() -> List[str]:
    """
    Search for samples (type: SAMPLE) in openBIS that still exist in the labs or that were already disposed (ACTIVE and DISPOSED).
    The ones used to store the sample provenance will not be returned because they have the object_status set to INACTIVE.

    Returns:
        List[Dict]: List of strings with the names and the permIDs in parenthesis of all the sample objects from openBIS
        that exists in the labs or that were disposed. The sample created during the sample preparation are not retrieved.

    Example:
        >>> get_live_samples_by_attributes()
        # Returns all samples with object_status ACTIVE and DISPOSED.
    """

    objects_data = []
    obj_type = "SAMPLE"

    # Active samples
    objects = openbis_utils.get_openbis_objects(
        type=obj_type, where={"object_status": "ACTIVE"}, props=["name"]
    )
    for obj in objects:
        objects_data.append(f"Sample {obj.props.name} ({obj.permId}).")

    # Disposed samples
    objects = openbis_utils.get_openbis_objects(
        type=obj_type, where={"object_status": "DISPOSED"}, props=["name"]
    )
    for obj in objects:
        objects_data.append(f"Sample {obj.props.name} ({obj.permId}).")

    return objects_data


@tool
def get_processes_documents(query):
    """
    Get all the descriptions from the processes available in openBIS and tell the user
    which one can be used for the experiment that the user wants to do.
    """
    openbis_type = "PROCESS"
    objects = openbis_utils.get_openbis_objects(
        type=openbis_type, props=["description"]
    )

    # Embedding model
    if os.environ["LLM_PROVIDER"] == "Google Gemini":
        embedding_model = GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001", google_api_key=os.environ["LLM_API_KEY"]
        )
    elif os.environ["LLM_PROVIDER"] == "OpenAI":
        embedding_model = OpenAIEmbeddings(
            model="text-embedding-3-small",
            openai_api_key=os.environ["LLM_API_KEY"],
        )
    else:
        raise ValueError("LLM provider not supported")

    # Text splitter to divide documents into smaller chunks
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500, chunk_overlap=10, length_function=len
    )

    docs = []
    for obj in objects:
        obj_name = obj.props.name or ""
        obj_description = obj.props.description or ""
        doc_content = f"Name: {obj_name}. Description: {obj_description}"
        docs.append(Document(page_content=doc_content, metadata={"permId": obj.permId}))

    chunks = text_splitter.split_documents(docs)

    vectordb = create_vectorDB("./chroma_db", embedding_model, chunks)

    retriever = vectordb.as_retriever()

    docs = retriever.invoke(query)

    objects_data = []
    for doc in docs:
        obj_permid = doc.metadata["permId"]
        obj = openbis_utils.get_openbis_object(obj_permid)
        obj_name = obj.props.name or ""
        obj_description = obj.props.description or ""
        objects_data.append(
            f"Process named {obj_name} described by {obj_description} ({obj_permid})"
        )

    return objects_data
