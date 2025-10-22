import json
from pathlib import Path
from pybis import Openbis
import yaml
import datetime
import os
import ipywidgets as ipw
import io
import contextlib

string_io = io.StringIO()

# OpenBIS-AiiDAlab functions


def get_openbis_collections(openbis_session, **kwargs):
    return openbis_session.get_collections(**kwargs)


def get_openbis_projects(openbis_session, **kwargs):
    return openbis_session.get_projects(**kwargs)


def get_openbis_objects(openbis_session, **kwargs):
    return openbis_session.get_objects(**kwargs)


def get_openbis_object(openbis_session, **kwargs):
    return openbis_session.get_object(**kwargs)


def get_openbis_collection(openbis_session, **kwargs):
    return openbis_session.get_collection(**kwargs)


def get_openbis_property_type(openbis_session, **kwargs):
    return openbis_session.get_property_type(**kwargs)


def find_first_atomistic_model(openbis_session, openbis_object, openbis_type):
    if openbis_type == "ATOMISTIC_MODEL":
        first_object = openbis_object

    object_parents_identifiers = openbis_object.parents
    for parent_identifier in object_parents_identifiers:
        parent_object = openbis_session.get_object(parent_identifier)
        if (
            parent_object.type == "GEOMETRY_OPTIMISATION"
            or parent_object.type == "ATOMISTIC_MODEL"
        ):
            first_object = find_first_atomistic_model(
                openbis_session, parent_object, parent_object.type
            )

    return first_object


def find_openbis_simulations(ob_session, root_obj, simulation_types):
    simulation_objects = set()
    stack = [root_obj]  # start with the root object

    while stack:
        current_obj = stack.pop()  # get the next object to process
        children = current_obj.children
        if children is not None:
            for child_ident in children:
                child_object = get_openbis_object(ob_session, sample_ident=child_ident)
                if child_object.type in simulation_types.values():
                    simulation_objects.add(child_object)
                stack.append(child_object)

    return simulation_objects


def upload_datasets(ob_session, ob_object, files_widget, dataset_type):
    with contextlib.redirect_stdout(string_io):
        for filename in files_widget.value:
            file_info = files_widget.value[filename]
            write_file(file_info["content"], filename)
            create_openbis_dataset(
                ob_session, type=dataset_type, sample=ob_object, files=[filename]
            )
            os.remove(filename)


def connect_openbis_aiida(eln_url=None):
    try:
        eln_config = Path.home() / ".aiidalab" / "aiidalab-eln-config.json"
        eln_config.parent.mkdir(
            parents=True, exist_ok=True
        )  # making sure that the folder exists.
        config = read_json(eln_config)
        if not eln_url:
            eln_url = config["default"]
        eln_token = config[eln_url]["token"]
        openbis_session, session_data = connect_openbis(eln_url, eln_token)
    except KeyError:
        eln_token = ""
        openbis_session, session_data = None, None
    return openbis_session, session_data


def connect_openbis(eln_url, eln_token):
    try:
        session_data = {"url": eln_url, "token": eln_token}
        openbis_session = Openbis(eln_url, verify_certificates=False)
        openbis_session.set_token(eln_token)
    except ValueError:
        print("Session is no longer valid. Please check if the token is still valid.")
        openbis_session = None
        session_data = {}

    return openbis_session, session_data


def get_next_collection_code(openbis_session, collection_type):
    collections = openbis_session.get_experiments(type=collection_type)
    collection_number = 1
    if collections:
        collection_number = (
            max(int(collection.code.rsplit("_")[-1]) for collection in collections) + 1
        )
    return f"{collection_type}_{collection_number}"


def create_openbis_dataset(openbis_session, **kwargs):
    with contextlib.redirect_stdout(string_io):
        openbis_ds = openbis_session.new_dataset(**kwargs)
        openbis_ds.save()


def update_openbis_object(openbis_object):
    with contextlib.redirect_stdout(string_io):
        openbis_object.save()


def create_openbis_object(openbis_session, **kwargs):
    with contextlib.redirect_stdout(string_io):
        openbis_object = openbis_session.new_object(**kwargs)
        openbis_object.save()
        return openbis_object


def create_openbis_collection(openbis_session, **kwargs):
    with contextlib.redirect_stdout(string_io):
        collection_type = kwargs.get("type", "")
        collection_code = kwargs.get("code", "")
        if collection_code == "":
            collection_code = get_next_collection_code(openbis_session, collection_type)
            kwargs["code"] = collection_code

        collection = openbis_session.new_collection(**kwargs)
        collection.save()
        return collection


# General functions
def clone_widgets_empty(widgets):
    new_widgets = []
    for w in widgets:
        cls = w.__class__
        kwargs = {}

        kwargs["layout"] = w.layout

        if isinstance(w, ipw.Dropdown):
            kwargs["options"] = w.options

        new_widgets.append(cls(**kwargs))
    return new_widgets


def full_listdir(path):
    return [f"{path}{os.sep}{filepath}" for filepath in os.listdir(path)]


def is_quantity_value(d):
    d_keys = set(d.keys())
    if d_keys == {"value", "unit"}:
        return True
    else:
        return False


def is_valid_json(string):
    try:
        obj = json.loads(string)
        if isinstance(obj, dict):
            return True  # Accept JSON objects
        if isinstance(obj, list) and all(isinstance(item, dict) for item in obj):
            return True  # Accept lists of JSON objects
        return False  # Reject lists and other types
    except (ValueError, TypeError):
        return False


def read_json(filename):
    with open(filename, "r") as file:
        return json.load(file)


def read_yaml(filepath: str):
    return yaml.safe_load(open(filepath, "r"))


def write_json(json_content, filename):
    with open(filename, "w") as file:
        json.dump(json_content, file, indent=4)


def read_file(filename):
    return open(filename, "rb").read()


def write_file(file_content, filename):
    with open(filename, "wb") as f:  # Save file content
        f.write(file_content)


def get_current_datetime():
    return datetime.datetime.now()


def convert_datetime_to_string(dt):
    return dt.strftime("%Y%m%d%H%M%S")


def remove_digits_from_string(string):
    return "".join([i for i in string if not i.isdigit()])


def is_nan(var):
    """Function to verify whether it is a NaN."""
    return var != var


def is_numeric(s):
    try:
        float(s)  # Attempt conversion to float
        return True
    except ValueError:
        return False


def stringify_quantity_value(json_obj, unit_type):
    if isinstance(json_obj, str):
        json_obj = json.loads(json_obj)

    value = json_obj["value"]
    unit = json_obj[unit_type]
    quantity_value_str = ""
    if value:
        quantity_value_str = f"{value} {unit}"

    return quantity_value_str
