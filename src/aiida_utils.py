import json
import logging
import os
import random
import re
import subprocess
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from aiida import orm
from aiida.common.exceptions import NotExistentAttributeError
from aiida.common.links import LinkType
from ase import Atoms
from ase.io.jsonio import encode
from ase.units import Bohr, Hartree

from . import utils

OPENBIS_COLLECTIONS_PATHS = utils.read_json("config/openbis_config.json")[
    "Collections"
]["Paths"]
OPENBIS_OBJECT_TYPES = utils.read_json("config/openbis_config.json")["OpenBIS Types"]
OPENBIS_SIMULATION_TYPES = utils.read_json("config/openbis_config.json")[
    "Simulation Export Types"
]
OPENBIS_SESSION, SESSION_DATA = utils.connect_openbis_aiida()


logger = logging.getLogger(__name__)
logging.basicConfig(
    filename="logs/aiidalab_openbis_interface.log",
    encoding="utf-8",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def creator_of_structure(struc_uuid):
    struc = orm.load_node(struc_uuid)
    the_creator = struc.creator
    if the_creator is None:
        return struc_uuid
    previous_wc = the_creator
    while previous_wc is not None:
        the_creator = previous_wc
        previous_wc = previous_wc.caller
    return the_creator.uuid


def original_structure(workchain_uuid):
    wc = orm.load_node(workchain_uuid)
    input_structure = wc.inputs.structure
    creator = creator_of_structure(input_structure.uuid)
    node_now = orm.load_node(creator)
    if not isinstance(node_now, orm.StructureData):
        return node_now.inputs.structure.uuid
    return creator


def find_bandgap(bandsdata_uuid, number_electrons=None, fermi_energy=None):
    """
    Tries to guess whether the bandsdata represent an insulator.
    This method is meant to be used only for electronic bands (not phonons)
    By default, it will try to use the occupations to guess the number of
    electrons and find the Fermi Energy, otherwise, it can be provided
    explicitely.
    Also, there is an implicit assumption that the kpoints grid is
    "sufficiently" dense, so that the bandsdata are not missing the
    intersection between valence and conduction band if present.
    Use this function with care!

    :param (float) number_electrons: (optional) number of electrons in the unit cell
    :param (float) fermi_energy: (optional) value of the fermi energy.

    :note: By default, the algorithm uses the occupations array
      to guess the number of electrons and the occupied bands. This is to be
      used with care, because the occupations could be smeared so at a
      non-zero temperature, with the unwanted effect that the conduction bands
      might be occupied in an insulator.
      Prefer to pass the number_of_electrons explicitly

    :note: Only one between number_electrons and fermi_energy can be specified at the
      same time.

    :return: (is_insulator, gap), where is_insulator is a boolean, and gap a
             float. The gap is None in case of a metal, zero when the homo is
             equal to the lumo (e.g. in semi-metals).
    """
    bandsdata = orm.load_node(bandsdata_uuid)

    def nint(num):
        """
        Stable rounding function
        """
        if num > 0:
            return int(num + 0.5)
        else:
            return int(num - 0.5)

    if fermi_energy and number_electrons:
        raise orm.EitherNumberOfElectronsOrFermiEnergyError()

    assert bandsdata.units == "eV"
    stored_bands = bandsdata.get_bands()

    if len(stored_bands.shape) == 3:
        # I write the algorithm for the generic case of having both the
        # spin up and spin down array

        # put all spins on one band per kpoint
        bands = np.concatenate(list(stored_bands), axis=1)
    else:
        bands = stored_bands

    # analysis on occupations:
    if fermi_energy is None:
        num_kpoints = len(bands)

        if number_electrons is None:
            try:
                _, stored_occupations = bandsdata.get_bands(also_occupations=True)
            except KeyError as exc:
                raise orm.FermiEnergyOrOccupationsNotPresentError() from exc

            # put the occupations in the same order of bands, also in case of multiple bands
            if len(stored_occupations.shape) == 3:
                # I write the algorithm for the generic case of having both the
                # spin up and spin down array

                # put all spins on one band per kpoint
                occupations = np.concatenate(list(stored_occupations), axis=1)
            else:
                occupations = stored_occupations

            # now sort the bands by energy
            # Note: I am sort of assuming that I have an electronic ground state

            # sort the bands by energy, and reorder the occupations accordingly
            # since after joining the two spins, I might have unsorted stuff
            bands, occupations = (
                np.array(y)
                for y in zip(
                    *[
                        zip(*j)
                        for j in [
                            sorted(
                                zip(i[0].tolist(), i[1].tolist()),
                                key=lambda x: x[0],
                            )
                            for i in zip(bands, occupations)
                        ]
                    ]
                )
            )
            number_electrons = int(
                round(sum([sum(i) for i in occupations]) / num_kpoints)
            )

            homo_indexes = [
                np.where(np.array([nint(_) for _ in x]) > 0)[0][-1] for x in occupations
            ]
            if (
                len(set(homo_indexes)) > 1
            ):  # there must be intersections of valence and conduction bands
                return False, None, None, None
            else:
                homo = [_[0][_[1]] for _ in zip(bands, homo_indexes)]
                try:
                    lumo = [_[0][_[1] + 1] for _ in zip(bands, homo_indexes)]
                except IndexError as exc:
                    raise orm.NeedMoreBandsError() from exc

        else:
            bands = np.sort(bands)
            number_electrons = int(number_electrons)

            # find the zero-temperature occupation per band (1 for spin-polarized
            # calculation, 2 otherwise)
            number_electrons_per_band = 4 - len(stored_bands.shape)  # 1 or 2
            # gather the energies of the homo band, for every kpoint
            homo = [
                i[int(number_electrons / number_electrons_per_band) - 1] for i in bands
            ]  # take the nth level
            try:
                # gather the energies of the lumo band, for every kpoint
                lumo = [
                    i[int(number_electrons / number_electrons_per_band)] for i in bands
                ]  # take the n+1th level
            except IndexError as exc:
                raise orm.NeedMoreBandsError() from exc

        if number_electrons % 2 == 1 and len(stored_bands.shape) == 2:
            # if #electrons is odd and we have a non spin polarized calculation
            # it must be a metal and I don't need further checks
            return False, None, None, None

        # if the nth band crosses the (n+1)th, it is an insulator
        gap = min(lumo) - max(homo)
        if gap == 0.0:
            return False, 0.0, None, None
        elif gap < 0.0:
            return False, gap, None, None
        else:
            return True, gap, max(homo), min(lumo)

    # analysis on the fermi energy
    else:
        # reorganize the bands, rather than per kpoint, per energy level

        # I need the bands sorted by energy
        bands.sort()

        levels = bands.transpose()
        max_mins = [(max(i), min(i)) for i in levels]

        if fermi_energy > bands.max():
            raise orm.FermiEnergyAndBandsEnergiesError(where="above")
        if fermi_energy < bands.min():
            raise orm.FermiEnergyAndBandsEnergiesError(where="below")

        # one band is crossed by the fermi energy
        if any(i[1] < fermi_energy and fermi_energy < i[0] for i in max_mins):
            return False, 0.0, None, None

        # case of semimetals, fermi energy at the crossing of two bands
        # this will only work if the dirac point is computed!
        elif any(i[0] == fermi_energy for i in max_mins) and any(
            i[1] == fermi_energy for i in max_mins
        ):
            return False, 0.0, None, None
        # insulating case
        else:
            # Take the max of the band maxima below the fermi energy.
            homo = max([i[0] for i in max_mins if i[0] < fermi_energy])
            # Take the min of the band minima above the fermi energy.x
            lumo = min([i[1] for i in max_mins if i[1] > fermi_energy])

            gap = lumo - homo
            if gap <= 0.0:
                raise orm.WrongCodeError()
            return True, gap, homo, lumo


# not used
def get_preceding_workchains(node_uuid):
    node = orm.load_node(node_uuid)
    preceding_workchains = set()

    def recursive_trace(node_uuid):
        node = orm.load_node(node_uuid)
        if isinstance(node, orm.WorkChainNode):
            preceding_workchains.add(node_uuid)
            # Recursively check incoming nodes for workchains
        for link in node.base.links.get_incoming().all():
            recursive_trace(link.node.uuid)

    # Start tracing from the provided node
    recursive_trace(node.uuid)

    return preceding_workchains


def get_all_preceding_main_workchains(node_uuid):
    """By MAIN workchain it is meant a workchain that is not called by a workchain"""
    node = orm.load_node(node_uuid)
    main_workchains = set()
    visited = set()  # Track visited nodes to avoid infinite recursion

    # Helper function to check if a node is a MAIN workchain
    def is_main_workchain(n):
        return (
            isinstance(n, orm.WorkChainNode)
            and not n.base.links.get_incoming(link_type=LinkType.CALL_WORK).all()
        )

    # Recursive function to trace back and find all preceding MAIN workchains
    def trace_back_main_workchains(n):
        if n.pk in visited:
            return  # Avoid processing the same node again
        visited.add(n.pk)

        # Check if the current node is a MAIN workchain
        if is_main_workchain(n):
            main_workchains.add(n)

        # Regardless of whether it's a MAIN workchain, continue tracing backward
        for input_link in n.base.links.get_incoming().all():
            trace_back_main_workchains(input_link.node)

    # Start tracing back from the given node
    trace_back_main_workchains(node)

    # Return the PKs of all unique MAIN workchains found
    return [wc.uuid for wc in main_workchains]


def get_qe_output_parameters(outputs):
    parameters = [
        "energy",
        "volume",
        "fft_grid",
        "energy_xc",
        "occupations",
        "total_force",
        "energy_ewald",
        "energy_units",
        "fermi_energy",
        "forces_units",
        "stress_units",
        "energy_hartree",
        "energy_accuracy",
        "energy_smearing",
        "energy_xc_units",
        "number_of_bands",
        "smooth_fft_grid",
        "symmetries",
        "symmetries_units",
        "total_force_units",
        "energy_ewald_units",
        "fermi_energy_units",
        "inversion_symmetry",
        "lattice_symmetries",
        "number_of_k_points",
        "energy_one_electron",
        "number_of_electrons",
        "energy_hartree_units",
        "magnetization_angle1",
        "magnetization_angle2",
        "number_of_atomic_wfc",
        "number_of_symmetries",
        "energy_accuracy_units",
        "no_time_rev_operations",
        "spin_orbit_calculation",
        "non_colinear_calculation",
        "energy_one_electron_units",
        "number_of_spin_components",
        "number_of_bravais_symmetries",
    ]
    return {
        parameter: outputs[parameter]
        for parameter in parameters
        if parameter in outputs
    }


def get_qe_input_parameters(outputs):
    parameters = [
        "lsda",
        "degauss",
        "rho_cutoff",
        "wfc_cutoff",
        "smearing_type",
        "constraint_mag",
        "number_of_atoms",
        "do_magnetization",
        "energy_threshold",
        "rho_cutoff_units",
        "spin_orbit_domag",
        "wfc_cutoff_units",
        "number_of_species",
        "has_electric_field",
        "time_reversal_flag",
        "monkhorst_pack_grid",
        "energy_accuracy_units",
        "energy_smearing_units",
        "has_dipole_correction",
        "monkhorst_pack_offset",
        "lda_plus_u_calculation",
        "spin_orbit_calculation",
        "starting_magnetization",
        "dft_exchange_correlation",
        "do_not_use_time_reversal",
        "non_colinear_calculation",
        "number_of_spin_components",
    ]
    return {
        parameter: outputs[parameter]
        for parameter in parameters
        if parameter in outputs
    }


def get_dft_parameters_qe(inputs, outputs):
    """Retrieves from QE workchains the parameters needed to create the DFT object
    in input the inputs of QE workchain and the output_parameters. Will be simplified when QeAppWorkchain
    bugs for not exposing some of the outputs will be fixed
    """

    system = inputs.pw.parameters.get_dict().get("SYSTEM", {})
    return {
        "xc_functional": outputs.get("dft_exchange_correlation", "unknown"),
        "plus_u": bool(outputs.get("lda_plus_u_calculation", False)),
        "spin_orbit_coupling": bool(outputs.get("spin_orbit_calculation", False)),
        "non_collinear": bool(outputs.get("non_colinear_calculation", False)),
        "uks": bool(outputs.get("lsda", False)),
        "charge": float(system.get("tot_charge", 0.0)),
        "vdw_corr": system.get("vdw_corr", ""),
    }


def get_dft_parameters_cp2k(code_description, dft_para):
    """Retrieves from CP2K workchains teh parameters to define the DFT object. Very preliminary"""

    return {
        "xc_functional": dft_para.get("xc_functional", dft_para.get("xc", "PBE")),
        "plus_u": bool(dft_para.get("plus_u", False)),
        "spin_orbit_coupling": bool(dft_para.get("spin_orbit_coupling", False)),
        "non_collinear": bool(dft_para.get("non_collinear", False)),
        "uks": bool(dft_para.get("uks", False)),
        "charge": float(dft_para.get("charge", 0.0)),
        "vdw_corr": dft_para.get("vdw", ""),
        "hfx_fraction": float(dft_para.get("hfx_fraction", 0.0)),
    }


def geo_to_png(ase_geo, filename="ase_geo.png"):
    ase_geo.write(filename)
    return filename


def guess_dimensionality(
    ase_geo: Optional[Atoms] = None, thr_vacuum: float = 5
) -> Optional[Tuple[int, Tuple[bool, bool, bool]]]:
    """Guess the dimensionality of a structure. thr_vacuum in Å.
    returns:
    -int dimensionality
    -(Bool,Bool,Bool) PBC
    """
    if (
        ase_geo is None
        or not hasattr(ase_geo, "positions")
        or not hasattr(ase_geo, "cell")
    ):
        return None

    sys_size = np.ptp(ase_geo.positions, axis=0)
    cell_lengths = np.diagonal(ase_geo.cell)

    # Check if the structure has no meaningful cell (cell lengths close to 0)
    if np.any(cell_lengths < 0.1):
        return 0, (False, False, False)

    # Determine vacuum presence in each direction
    has_vacuum = sys_size + thr_vacuum < cell_lengths
    # Invert vacuum to indicate bulk presence
    has_bulk = ~has_vacuum  # Logical NOT to invert (True where no vacuum)
    dimensionality = 3 - np.sum(has_vacuum)  # 3D: no vacuum, 2D: 1 vacuum, etc.

    return dimensionality, tuple(has_bulk)


def is_structure_optimized(structure_uuid):
    creator = creator_of_structure(structure_uuid)
    geo_opt = False
    cell_opt = False
    cell_free = ""
    if creator == structure_uuid:
        return geo_opt, cell_opt, cell_free
    creator = orm.load_node(creator)
    if creator.process_label == "Cp2kGeoOptWorkChain":
        geo_opt = True
        cell_opt = creator.label == "CP2K_CellOpt"
        if cell_opt:
            cell_free = creator.inputs.sys_params.get_dict()["cell_opt_constraint"]
        return geo_opt, cell_opt, cell_free
    if creator.process_label == "QeAppWorkChain":
        for wc in creator.called_descendants:
            if wc.process_label == "PwRelaxWorkChain":
                geo_opt = True
                cell_free = (
                    wc.inputs.base.pw.parameters.get_dict()
                    .get("CELL", {})
                    .get("cell_dofree", "")
                )
                if cell_free != "":
                    cell_opt = True
                break
        return geo_opt, cell_opt, cell_free


def get_uuids_from_oBIS(openbis_session):
    aiida_node_type = OPENBIS_OBJECT_TYPES["AiiDA Node"]
    atom_model_type = OPENBIS_OBJECT_TYPES["Atomistic Model"]
    aiida_nodes_oBIS = utils.get_openbis_objects(openbis_session, type=aiida_node_type)
    atom_mods_oBIS = utils.get_openbis_objects(openbis_session, type=atom_model_type)

    simulation_uuids_oBIS = {"wc_uuids": [], "structure_uuids": []}

    if aiida_nodes_oBIS:
        simulation_uuids_oBIS["wc_uuids"] = [
            obj.props["wfms_uuid"] for obj in aiida_nodes_oBIS
        ]

    if atom_mods_oBIS:
        simulation_uuids_oBIS["structure_uuids"] = [
            obj.props["wfms_uuid"] for obj in atom_mods_oBIS
        ]

    return simulation_uuids_oBIS


# Assuming 'data' is an AiiDA Data object
def aiida_data_to_json(data_uuid):
    """Exports AiiDA xxData object as .json. Does not work for StructureData"""
    data = orm.load_node(data_uuid)

    # temporary fix waiting for https://github.com/aiidateam/aiida-quantumespresso/pull/1188
    # projwfc creates BandsData with U8 instead of floats
    if data.__class__.__name__ == "BandsData":
        if data.get_bands().dtype != np.dtype("float64"):
            new = data.clone()
            new.set_bands(new.get_bands().astype(float))
            data = new.clone()
    # end temporary fix

    # Create a temporary file path
    temp_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".json", delete=False)
    try:
        temp_file.close()  # Close it to allow export to overwrite the file

        # Export the Data object to the temporary file in JSON format
        data.export(temp_file.name, fileformat="json", overwrite=True)

        # Read the contents of the temporary file
        with open(temp_file.name, "r") as f:
            json_string = f.read()
    finally:
        # Clean up the temporary file
        os.remove(temp_file.name)

    return json_string


def structure_to_atomistic_model(openbis_session, structure_uuid, uuids):
    """Check if this atomistic model is already in OBIS otherwise create.
    Output: uuid of the oBIS object for linking
    """
    uuid = structure_uuid
    structure = orm.load_node(uuid)

    atom_model_type = OPENBIS_OBJECT_TYPES["Atomistic Model"]

    # check if the atomistic model is already in oBIS
    if uuid in uuids:
        atom_models_obis = utils.get_openbis_objects(
            openbis_session, type=atom_model_type
        )
        for atom_model in atom_models_obis:
            if atom_model.props["wfms_uuid"] == uuid:
                return atom_model

    # check if the geometry is optimized
    ase_geo = structure.get_ase()
    dimensionality = guess_dimensionality(ase_geo)
    dictionary = {
        "name": ase_geo.get_chemical_formula(),
        "wfms_uuid": structure.uuid,
        "volume": structure.get_cell_volume(),
        "cell": json.dumps({"cell": structure.cell}),
    }

    if dimensionality:
        dictionary["dimensionality"] = int(dimensionality[0])
        dictionary["periodic_boundary_conditions"] = [
            bool(i) for i in dimensionality[1]
        ]

    obobject = utils.create_openbis_object(
        openbis_session,
        type=atom_model_type,
        props=dictionary,
        collection=OPENBIS_COLLECTIONS_PATHS["Atomistic Model"],
    )

    geo_png_filename = geo_to_png(ase_geo)

    utils.create_openbis_dataset(
        openbis_session,
        type="ELN_PREVIEW",
        sample=obobject,
        files=[geo_png_filename],
    )

    os.remove(geo_png_filename)

    structure_json = encode(ase_geo)
    utils.write_json(structure_json, "structure_json.json")
    utils.create_openbis_dataset(
        openbis_session, type="RAW_DATA", sample=obobject, files=["structure_json.json"]
    )
    os.remove("structure_json.json")

    return obobject


def create_obis_object(obtype=None, parameters=None):
    """Function to create oBIS object given parameters"""
    obisuuid = "".join(
        random.choice("abcdefghijklmnopqrstuvwxyz1234567890") for _ in range(8)
    )
    print(
        f"oBIS object {obtype} {obisuuid} created with parameters: {parameters.keys()}"
    )
    return obisuuid


def create_and_export_AiiDA_archive(openbis_session, uuid):
    """Create and upload the AiiDA archive for a main workchain."""
    aiida_node_type = OPENBIS_OBJECT_TYPES["AiiDA Node"]
    with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-archive-") as dirname:
        output_file = Path(dirname) / "archive.aiida"
        command = [
            "verdi",
            "archive",
            "create",
            str(output_file),
            "--no-call-calc-backward",
            "--no-call-work-backward",
            "--no-create-backward",
            "-N",
            str(uuid),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"Could not create the AiiDA archive for {uuid}: {result.stderr.strip()}"
            )

        openbis_object = utils.create_openbis_object(
            openbis_session,
            type=aiida_node_type,
            props={"wfms_uuid": str(uuid), "comments": ""},
            collection=OPENBIS_COLLECTIONS_PATHS["AiiDA Node"],
        )
        utils.create_openbis_dataset(
            openbis_session,
            type="RAW_DATA",
            sample=openbis_object,
            files=[output_file],
        )
        return openbis_object


def normalize_exported_objects(export):
    """Return exporter results as a tuple of non-null openBIS objects."""
    if export is None:
        return ()
    if isinstance(export, (list, tuple)):
        return tuple(obj for obj in export if obj is not None)
    return (export,)


class ExecutableResolutionError(ValueError):
    """Base error raised while mapping AiiDA codes to openBIS objects."""


class OpenbisNameMatchError(ExecutableResolutionError):
    """Raised when an AiiDA label cannot identify one openBIS object."""


class MissingExecutablesError(ExecutableResolutionError):
    """Raised when exporting would require new EXECUTABLE objects."""

    def __init__(self, requirements):
        self.requirements = tuple(requirements)
        labels = ", ".join(item["full_label"] for item in self.requirements)
        super().__init__(f"Missing openBIS EXECUTABLE objects for: {labels}")


def _openbis_property(openbis_object, property_name):
    """Return a scalar property across pyBIS 6/openBIS 7 representations."""
    value = openbis_object.props.get(property_name)
    if isinstance(value, dict):
        if property_name in value:
            return value[property_name]
        if "value" in value:
            return value["value"]
    return value


def _aiida_uuid_comment(kind, uuid):
    return f"AiiDA {kind} UUID: {uuid}"


def _find_object_by_comment(objects, comment):
    for openbis_object in objects:
        if comment in str(_openbis_property(openbis_object, "comments") or ""):
            return openbis_object
    return None


def _find_object_by_permid(objects, permid):
    for openbis_object in objects:
        if str(openbis_object.permId) == str(permid):
            return openbis_object
    return None


def _openbis_object_options(objects):
    return tuple(
        (
            str(openbis_object.permId),
            str(_openbis_property(openbis_object, "name") or openbis_object.permId),
        )
        for openbis_object in objects
    )


def _selected_openbis_object(objects, provenance_overrides, object_kind, aiida_uuid):
    if not provenance_overrides:
        return None
    selected_permid = provenance_overrides.get(object_kind, {}).get(str(aiida_uuid))
    if not selected_permid:
        return None
    selected = _find_object_by_permid(objects, selected_permid)
    if selected is None:
        raise ExecutableResolutionError(
            f"Selected openBIS {object_kind} object {selected_permid} no longer exists."
        )
    return selected


def _add_resolution_context(
    error, object_kind, aiida_uuid, aiida_label, aiida_description, objects
):
    error.object_kind = object_kind
    error.aiida_uuid = str(aiida_uuid)
    error.aiida_label = str(aiida_label or "")
    error.aiida_description = str(aiida_description or "")
    error.openbis_options = _openbis_object_options(objects)
    return error


def _normalize_object_name(value):
    """Normalize an AiiDA/openBIS name for punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _match_named_openbis_object(aiida_name, objects, object_kind, additional_names=()):
    """Match an openBIS name within ordered AiiDA identifiers."""
    search_names = (str(aiida_name or ""),) + tuple(
        str(value or "") for value in additional_names
    )
    candidates = []
    for search_priority, search_name in enumerate(search_names):
        normalized_search_name = _normalize_object_name(search_name)
        for openbis_object in objects:
            openbis_name = str(_openbis_property(openbis_object, "name") or "")
            normalized_openbis_name = _normalize_object_name(openbis_name)
            if (
                normalized_openbis_name
                and normalized_openbis_name in normalized_search_name
            ):
                candidates.append(
                    (search_priority, normalized_openbis_name, openbis_object)
                )

    if not candidates:
        available = sorted(
            str(_openbis_property(obj, "name"))
            for obj in objects
            if _openbis_property(obj, "name")
        )
        available_text = ", ".join(available) if available else "none"
        identifiers = ", ".join(repr(value) for value in search_names if value)
        raise OpenbisNameMatchError(
            f"AiiDA {object_kind} identifiers {identifiers} do not contain the "
            f"name of an openBIS {object_kind} object. Available names: "
            f"{available_text}."
        )

    best_priority = min(priority for priority, _name, _obj in candidates)
    prioritized = [
        (name, obj) for priority, name, obj in candidates if priority == best_priority
    ]
    longest_name_length = max(len(name) for name, _obj in prioritized)
    best_matches = [
        obj for name, obj in prioritized if len(name) == longest_name_length
    ]
    if len(best_matches) != 1:
        names = sorted(str(_openbis_property(obj, "name")) for obj in best_matches)
        raise OpenbisNameMatchError(
            f"AiiDA {object_kind} identifier '{search_names[best_priority]}' "
            f"ambiguously matches openBIS {object_kind} objects: "
            f"{', '.join(names)}."
        )
    return best_matches[0]


def _aiida_code_version(aiida_code):
    """Return a version inferred from an AiiDA Code description or label."""
    description = str(getattr(aiida_code, "description", "") or "")
    version_match = re.search(r"\((?:v)?([0-9]+(?:\.[0-9]+)+)\)", description)
    if version_match is None:
        version_match = re.search(
            r"[-_]v?([0-9]+(?:\.[0-9]+)+)$", str(aiida_code.label)
        )
    return version_match.group(1) if version_match is not None else ""


def _executable_comments(aiida_code):
    computer = aiida_code.computer
    plugin = str(getattr(aiida_code, "default_calc_job_plugin", "") or "")
    return "\n".join(
        (
            _aiida_uuid_comment("Code", aiida_code.uuid),
            _aiida_uuid_comment("Computer", computer.uuid),
            f"AiiDA full label: {aiida_code.full_label}",
            f"AiiDA executable path: {aiida_code.filepath_executable}",
            f"AiiDA plugin: {plugin}",
        )
    )


def _executable_description(aiida_code):
    details = [
        f"AiiDA code {aiida_code.full_label}",
        f"executable {aiida_code.filepath_executable}",
    ]
    plugin = str(getattr(aiida_code, "default_calc_job_plugin", "") or "")
    version = _aiida_code_version(aiida_code)
    if plugin:
        details.append(f"plugin {plugin}")
    if version:
        details.append(f"version {version}")
    return "; ".join(details)


def _object_reference_id(value):
    """Return a comparable permId from a pyBIS object-reference property."""
    if hasattr(value, "permId"):
        return str(value.permId)
    if isinstance(value, dict):
        return str(value.get("permId", value.get("identifier", "")))
    return str(value or "")


def _openbis_executable_options(executable_objects):
    options = []
    for executable in executable_objects:
        name = str(_openbis_property(executable, "name") or executable.permId)
        code = _object_reference_id(_openbis_property(executable, "code"))
        computer = _object_reference_id(_openbis_property(executable, "computer"))
        details = (
            f"{name}; CODE {code or 'unlinked'}; COMPUTER {computer or 'unlinked'}"
        )
        options.append((str(executable.permId), details))
    return tuple(options)


def _find_executable(executable_objects, aiida_code, software, computer):
    normalized_label = _normalize_object_name(aiida_code.label)
    signature_matches = []
    for candidate in executable_objects:
        if (
            _normalize_object_name(_openbis_property(candidate, "name"))
            != normalized_label
        ):
            continue
        if _object_reference_id(_openbis_property(candidate, "code")) != str(
            software.permId
        ):
            continue
        if _object_reference_id(_openbis_property(candidate, "computer")) != str(
            computer.permId
        ):
            continue
        signature_matches.append(candidate)

    if len(signature_matches) > 1:
        raise ExecutableResolutionError(
            f"Multiple openBIS EXECUTABLE objects match '{aiida_code.full_label}'."
        )
    return signature_matches[0] if signature_matches else None


def _workchain_codes(workchain):
    codes = {}
    for node in workchain.called_descendants:
        if not isinstance(node, orm.CalcJobNode):
            continue
        try:
            code = node.inputs.code
        except (AttributeError, NotExistentAttributeError):
            continue
        codes[str(code.uuid)] = code
    return sorted(codes.values(), key=lambda code: code.full_label)


def _unique_workchain_codes(workchains):
    codes = {}
    for workchain in workchains:
        for code in _workchain_codes(workchain):
            codes[str(code.uuid)] = code
    return sorted(codes.values(), key=lambda code: code.full_label)


def _ensure_executables_for_workchains(
    openbis_session,
    workchains: Iterable,
    create_missing=False,
    provenance_overrides=None,
):
    """Resolve workflow executables, optionally creating confirmed missing ones."""
    code_type = OPENBIS_OBJECT_TYPES["Code"]
    computer_type = OPENBIS_OBJECT_TYPES["Computer"]
    executable_type = OPENBIS_OBJECT_TYPES["Executable"]
    executable_collection = OPENBIS_COLLECTIONS_PATHS["Executable"]

    code_objects = list(
        utils.get_openbis_objects(openbis_session, type=code_type) or []
    )
    computer_objects = list(
        utils.get_openbis_objects(openbis_session, type=computer_type) or []
    )
    executable_objects = list(
        utils.get_openbis_objects(openbis_session, type=executable_type) or []
    )

    resolved = {}
    missing = []
    for aiida_code in _unique_workchain_codes(workchains):
        aiida_code_uuid = str(aiida_code.uuid)
        executable = _selected_openbis_object(
            executable_objects,
            provenance_overrides,
            "Executable",
            aiida_code_uuid,
        )
        if executable is None:
            executable = _find_object_by_comment(
                executable_objects,
                _aiida_uuid_comment("Code", aiida_code.uuid),
            )
        if executable is not None:
            resolved[aiida_code_uuid] = executable.permId
            continue

        software = _selected_openbis_object(
            code_objects, provenance_overrides, "Code", aiida_code_uuid
        )
        if software is None:
            try:
                software = _match_named_openbis_object(
                    aiida_code.label, code_objects, "Code"
                )
            except OpenbisNameMatchError as error:
                raise _add_resolution_context(
                    error,
                    "Code",
                    aiida_code_uuid,
                    aiida_code.label,
                    aiida_code.description,
                    code_objects,
                )

        computer = aiida_code.computer
        computer_uuid = str(computer.uuid)
        computer_object = _selected_openbis_object(
            computer_objects,
            provenance_overrides,
            "Computer",
            computer_uuid,
        )
        if computer_object is None:
            try:
                computer_object = _match_named_openbis_object(
                    computer.label,
                    computer_objects,
                    "Computer",
                    additional_names=(computer.description,),
                )
            except OpenbisNameMatchError as error:
                raise _add_resolution_context(
                    error,
                    "Computer",
                    computer_uuid,
                    computer.label,
                    computer.description,
                    computer_objects,
                )

        executable = _find_executable(
            executable_objects, aiida_code, software, computer_object
        )
        if executable is None:
            properties = {
                "name": aiida_code.label,
                "description": _executable_description(aiida_code),
                "comments": _executable_comments(aiida_code),
                "code": software.permId,
                "computer": computer_object.permId,
            }
            missing.append(
                {
                    "aiida_code_uuid": aiida_code_uuid,
                    "full_label": aiida_code.full_label,
                    "code_name": _openbis_property(software, "name") or "",
                    "computer_name": (_openbis_property(computer_object, "name") or ""),
                    "version": _aiida_code_version(aiida_code),
                    "executable_path": aiida_code.filepath_executable,
                    "plugin": str(
                        getattr(aiida_code, "default_calc_job_plugin", "") or ""
                    ),
                    "executable_options": _openbis_executable_options(
                        executable_objects
                    ),
                    "properties": properties,
                }
            )
            continue
        resolved[aiida_code_uuid] = executable.permId

    if missing and not create_missing:
        raise MissingExecutablesError(missing)

    for requirement in missing:
        executable = utils.create_openbis_object(
            openbis_session,
            type=executable_type,
            props=requirement["properties"],
            collection=executable_collection,
        )
        resolved[requirement["aiida_code_uuid"]] = executable.permId

    return resolved


def _ensure_executables(
    openbis_session,
    workchain,
    create_missing=False,
    provenance_overrides=None,
):
    """Resolve a workflow's executables without silently creating records."""
    codes = _workchain_codes(workchain)
    resolved = _ensure_executables_for_workchains(
        openbis_session,
        [workchain],
        create_missing=create_missing,
        provenance_overrides=provenance_overrides,
    )
    return [resolved[str(code.uuid)] for code in codes]


def _find_nanoribbon_calculations(workchain):
    """Find the calculations needed to export a NanoribbonWorkChain."""
    calculations = {
        "cell_opt2": None,
        "scf": None,
        "bands": None,
        "export_pdos": None,
    }
    for node in workchain.called_descendants:
        if node.label in calculations and calculations[node.label] is None:
            calculations[node.label] = node

    missing = [
        label
        for label in ("scf", "bands", "export_pdos")
        if calculations[label] is None
    ]
    if missing:
        raise ValueError(
            f"Cannot export NanoribbonWorkChain {workchain.uuid}: missing required "
            f"calculation(s): {', '.join(missing)}."
        )
    return calculations


def _get_optional_output(outputs, label):
    """Return an optional AiiDA output without leaking namespace exceptions."""
    try:
        return getattr(outputs, label)
    except (AttributeError, NotExistentAttributeError):
        return None


def _quantity(value, unit):
    return {"value": float(value), "unit": unit}


def _energy_in_hartree(output_parameters):
    """Return the final energy using the unit required by the openBIS schema."""
    if "energy" in output_parameters:
        value = output_parameters["energy"]
        unit = str(output_parameters.get("energy_units", "eV")).strip().lower()
    else:
        motion = output_parameters.get("motion_step_info", {})
        energies = motion.get("energy_au", [])
        if not energies:
            raise ValueError("The workflow output does not contain a final energy.")
        value = energies[-1]
        unit = "a.u."

    if unit in {"ha", "hartree", "a.u.", "au", "atomic units"}:
        value_hartree = value
    elif unit in {"ev", "electronvolt", "electronvolts"}:
        value_hartree = float(value) / Hartree
    elif unit in {"ry", "rydberg", "rydbergs"}:
        value_hartree = float(value) / 2.0
    else:
        raise ValueError(f"Unsupported energy unit for openBIS export: {unit!r}.")
    return _quantity(value_hartree, "Hartree")


def _method_modifiers(dft_parameters):
    modifiers = []
    xc = str(dft_parameters.get("xc_functional", "")).upper()
    if float(dft_parameters.get("hfx_fraction", 0.0)) > 0.0 or any(
        label in xc for label in ("PBE0", "HSE", "B3LYP", "HYBRID")
    ):
        modifiers.append("hybrid")
    vdw = str(dft_parameters.get("vdw_corr", "")).strip().lower()
    if vdw not in {"", "0", "false", "no", "none"}:
        modifiers.append("vdW")
    if dft_parameters.get("plus_u"):
        modifiers.append("DFT+U")
    if dft_parameters.get("spin_orbit_coupling"):
        modifiers.append("spin_orbit")
    if dft_parameters.get("non_collinear"):
        modifiers.append("spin_non_collinear")
    elif dft_parameters.get("uks"):
        modifiers.append("spin_collinear")
    return modifiers


def _workchain_name(workchain, prefix):
    description = getattr(workchain, "description", "")
    if not description:
        caller = getattr(workchain, "caller", None)
        description = getattr(caller, "description", "") if caller else ""
    suffix = description[:80] if description else str(workchain.uuid)[:8]
    return f"{prefix} - {suffix}"


def _simulation_properties(
    workchain,
    prefix,
    dft_parameters,
    aiida_node_id,
    method_label=True,
    executable_ids=None,
):
    properties = {
        "name": _workchain_name(workchain, prefix),
        "method_family": "DFT",
        "method_modifiers": _method_modifiers(dft_parameters),
        "charge": float(dft_parameters.get("charge", 0.0)),
        "converged": bool(getattr(workchain, "is_finished_ok", True)),
        "aiida_node": aiida_node_id,
    }
    if method_label:
        properties["method_label"] = str(dft_parameters.get("xc_functional", "unknown"))
    if executable_ids is not None:
        properties["executables"] = list(executable_ids)
    multiplicity = dft_parameters.get("multiplicity")
    if multiplicity is not None:
        properties["spin_multiplicity"] = int(multiplicity)
    return properties


def _fermi_energy(output_parameters):
    value = output_parameters.get("fermi_energy")
    if value is None:
        return None
    return [_quantity(value, "eV")]


def _attach_parent(openbis_object, parent):
    openbis_object.add_parents(parent)
    utils.update_openbis_object(openbis_object)


def _upload_preview(openbis_session, openbis_object, renderer, stem):
    with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-preview-") as dirname:
        path = Path(dirname) / f"{stem}.png"
        renderer(path)
        if not path.is_file():
            raise RuntimeError(f"Preview renderer did not create {path.name}.")
        utils.create_openbis_dataset(
            openbis_session,
            type="ELN_PREVIEW",
            sample=openbis_object,
            files=[path],
        )


def _render_structure_preview(structure, path):
    geo_to_png(structure.get_ase(), path)


def _render_bands_preview(bands_node, path, fermi_energy=None):
    from matplotlib.figure import Figure

    bands = np.asarray(bands_node.get_bands(), dtype=float)
    if bands.ndim == 2:
        bands = bands[np.newaxis, ...]
    if bands.ndim != 3:
        raise ValueError(f"Unsupported band array shape: {bands.shape}.")

    figure = Figure(figsize=(7, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for spin_bands in bands:
        axis.plot(np.arange(spin_bands.shape[0]), spin_bands, color="C0", lw=0.8)
    if fermi_energy is not None:
        axis.axhline(float(fermi_energy), color="black", ls="--", lw=0.8)
    axis.set_xlabel("k-point index")
    axis.set_ylabel(f"Energy ({getattr(bands_node, 'units', 'eV')})")
    axis.set_title("Electronic band structure")
    figure.savefig(path, dpi=160)


def _render_xy_preview(xy_node, path, title, x_label=None, y_label=None):
    from matplotlib.figure import Figure

    x_name, x_values, x_unit = xy_node.get_x()
    curves = xy_node.get_y()
    figure = Figure(figsize=(7, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for curve_name, values, _unit in curves:
        axis.plot(np.asarray(x_values), np.asarray(values), label=curve_name)
    axis.set_xlabel(x_label or f"{x_name} ({x_unit})")
    axis.set_ylabel(y_label or "Intensity")
    axis.set_title(title)
    if len(curves) > 1:
        axis.legend(fontsize="small")
    figure.savefig(path, dpi=160)


def _render_spm_preview(workchain, path):
    from matplotlib.figure import Figure

    stm_calculation = None
    for node in workchain.called_descendants:
        label = str(getattr(node, "label", "")).lower()
        process_label = str(getattr(node, "process_label", "")).lower()
        if label == "stm" or "stm" in process_label:
            retrieved = _get_optional_output(node.outputs, "retrieved")
            if retrieved is not None:
                stm_calculation = node
                break
    if stm_calculation is None:
        raise ValueError("The STM workflow does not contain a retrieved stm.npz file.")

    retrieved = stm_calculation.outputs.retrieved
    with retrieved.base.repository.open("stm.npz", mode="rb") as handle:
        archive = np.load(handle, allow_pickle=True)
        series_info = archive["stm_series_info"]
        series_data = archive["stm_series_data"]
        general_info = archive["stm_general_info"].item()

        index = 0
        for candidate, info in enumerate(series_info):
            info = info.item() if hasattr(info, "item") else info
            if str(info.get("type", "")).lower().endswith("stm"):
                index = candidate
                break
        image = np.asarray(series_data[index])
        while image.ndim > 2:
            image = image[-1]
        x_values = np.asarray(general_info.get("x_arr", np.arange(image.shape[-1])))
        y_values = np.asarray(general_info.get("y_arr", np.arange(image.shape[-2])))

    figure = Figure(figsize=(6, 5), constrained_layout=True)
    axis = figure.subplots()
    plotted = axis.imshow(
        image,
        origin="lower",
        aspect="auto",
        extent=[
            x_values.min() * Bohr,
            x_values.max() * Bohr,
            y_values.min() * Bohr,
            y_values.max() * Bohr,
        ],
        cmap="viridis",
    )
    axis.set_xlabel("x (Å)")
    axis.set_ylabel("y (Å)")
    axis.set_title("Representative STM map")
    figure.colorbar(plotted, ax=axis)
    figure.savefig(path, dpi=160)


def _create_simulation_object(
    openbis_session,
    experiment_id,
    object_type,
    properties,
    parents,
    renderer,
    preview_stem,
):
    openbis_object = utils.create_openbis_object(
        openbis_session,
        type=object_type,
        props=properties,
        collection=experiment_id,
    )
    for parent in parents:
        openbis_object.add_parents(parent)
    if parents:
        utils.update_openbis_object(openbis_object)
    _upload_preview(openbis_session, openbis_object, renderer, preview_stem)
    return openbis_object


def _qe_dft_from_calculation(calculation):
    outputs = calculation.outputs.output_parameters.get_dict()
    system = calculation.inputs.parameters.get_dict().get("SYSTEM", {})
    return {
        "xc_functional": outputs.get("dft_exchange_correlation", "unknown"),
        "plus_u": bool(outputs.get("lda_plus_u_calculation", False)),
        "spin_orbit_coupling": bool(outputs.get("spin_orbit_calculation", False)),
        "non_collinear": bool(outputs.get("non_colinear_calculation", False)),
        "uks": bool(outputs.get("lsda", False)),
        "charge": float(system.get("tot_charge", 0.0)),
        "vdw_corr": system.get("vdw_corr", ""),
    }


def _create_band_and_dos_objects(
    openbis_session,
    experiment_id,
    workchain,
    dft_parameters,
    output_parameters,
    bands_node,
    dos_node,
    structure_object,
    aiida_node_id,
    executable_ids,
):
    electron_count = output_parameters.get("number_of_electrons")
    if electron_count is None:
        raise ValueError("The workflow output does not contain number_of_electrons.")
    _, gap, _, _ = find_bandgap(bands_node.uuid, number_electrons=electron_count)
    band_properties = _simulation_properties(
        workchain,
        "Bands",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    band_properties["band_gap"] = _quantity(0.0 if gap is None else gap, "eV")
    fermi = _fermi_energy(output_parameters)
    if fermi is not None:
        band_properties["fermi_energy"] = fermi

    bands_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Band Structure"],
        band_properties,
        [structure_object],
        lambda path: _render_bands_preview(
            bands_node, path, output_parameters.get("fermi_energy")
        ),
        "band_structure",
    )

    dos_properties = _simulation_properties(
        workchain,
        "PDOS",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    dos_properties.update(
        {
            "pdos": True,
            "projection_description": (
                "Orbital-projected density of states generated from the AiiDA "
                "workflow. Full arrays are stored in the linked AiiDA archive."
            ),
        }
    )
    if fermi is not None:
        dos_properties["fermi_energy"] = fermi
    dos_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["DOS"],
        dos_properties,
        [structure_object],
        lambda path: _render_xy_preview(dos_node, path, "Projected density of states"),
        "pdos",
    )
    return bands_object, dos_object


def NanoribbonWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    """Export a nanoribbon workflow using the simplified simulation schema."""
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    calculations = _find_nanoribbon_calculations(workchain)
    cell_opt = calculations["cell_opt2"]
    scf = calculations["scf"]
    bands = calculations["bands"]
    export_pdos = calculations["export_pdos"]

    output_parameters = scf.outputs.output_parameters.get_dict()
    dft_parameters = _qe_dft_from_calculation(scf)
    final_structure = (
        cell_opt.outputs.output_structure
        if cell_opt is not None
        else workchain.inputs.structure
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, final_structure.uuid, uuids
    )
    dos_node = _get_optional_output(export_pdos.outputs, "Dos")
    if dos_node is None:
        raise ValueError("The export_pdos calculation does not contain a Dos output.")

    bands_object, dos_object = _create_band_and_dos_objects(
        openbis_session,
        experiment_id,
        workchain,
        dft_parameters,
        output_parameters,
        bands.outputs.output_band,
        dos_node,
        structure_object,
        aiida_node_id,
        executable_ids,
    )

    geometry_object = None
    if cell_opt is not None:
        cell_output = cell_opt.outputs.output_parameters.get_dict()
        properties = _simulation_properties(
            workchain,
            "Geometry optimization",
            dft_parameters,
            aiida_node_id,
            method_label=False,
            executable_ids=executable_ids,
        )
        properties.update(
            {
                "constrained": False,
                "cell_optimization": True,
                "final_energy": _energy_in_hartree(cell_output),
            }
        )
        cell_dofree = (
            cell_opt.inputs.parameters.get_dict().get("CELL", {}).get("cell_dofree")
        )
        if cell_dofree:
            properties["cell_constraints"] = str(cell_dofree)
        input_structure_object = structure_to_atomistic_model(
            openbis_session, workchain.inputs.structure.uuid, uuids
        )
        geometry_object = _create_simulation_object(
            openbis_session,
            experiment_id,
            OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
            properties,
            [input_structure_object],
            lambda path: _render_structure_preview(final_structure, path),
            "optimized_geometry",
        )
        structure_object.add_parents(geometry_object)
        utils.update_openbis_object(structure_object)
        geometry_object.add_children(structure_object)
        utils.update_openbis_object(geometry_object)

    return geometry_object, bands_object, dos_object


def PwRelaxWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    input_parameters = workchain.inputs.base.pw.parameters.get_dict()
    output_parameters = workchain.outputs.output_parameters.get_dict()
    dft_parameters = get_dft_parameters_qe(workchain.inputs.base, output_parameters)
    control = input_parameters.get("CONTROL", {})
    calculation = str(control.get("calculation", "relax")).lower()
    cell_optimization = calculation == "vc-relax"

    properties = _simulation_properties(
        workchain,
        "Geometry optimization",
        dft_parameters,
        aiida_node_id,
        method_label=False,
        executable_ids=executable_ids,
    )
    properties.update(
        {
            "constrained": False,
            "cell_optimization": cell_optimization,
            "final_energy": _energy_in_hartree(output_parameters),
        }
    )
    cell_constraints = input_parameters.get("CELL", {}).get("cell_dofree")
    if cell_constraints:
        properties["cell_constraints"] = str(cell_constraints)

    input_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    output_structure = workchain.outputs.output_structure
    geometry_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
        properties,
        [input_object],
        lambda path: _render_structure_preview(output_structure, path),
        "optimized_geometry",
    )
    output_object = structure_to_atomistic_model(
        openbis_session, output_structure.uuid, uuids
    )
    output_object.add_parents(geometry_object)
    utils.update_openbis_object(output_object)
    geometry_object.add_children(output_object)
    utils.update_openbis_object(geometry_object)
    return geometry_object


def BandsWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    try:
        root_in = workchain.inputs.bands
        root_out = workchain.outputs.bands
    except NotExistentAttributeError:
        root_in = workchain.inputs.bands_projwfc
        root_out = workchain.outputs.bands_projwfc

    output_parameters = root_out.scf_parameters.get_dict()
    dft_parameters = get_dft_parameters_qe(root_in.bands, output_parameters)
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_band_and_dos_objects(
        openbis_session,
        experiment_id,
        workchain,
        dft_parameters,
        output_parameters,
        root_out.band_structure,
        root_out.projwfc.Dos,
        structure_object,
        aiida_node_id,
        executable_ids,
    )


def PdosWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    output_parameters = workchain.outputs.nscf.output_parameters.get_dict()
    dft_parameters = get_dft_parameters_qe(workchain.inputs.scf, output_parameters)
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    properties = _simulation_properties(
        workchain,
        "PDOS",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties.update(
        {
            "pdos": True,
            "projection_description": (
                "Orbital-projected density of states generated by projwfc.x. "
                "Full arrays are stored in the linked AiiDA archive."
            ),
        }
    )
    fermi = _fermi_energy(output_parameters)
    if fermi is not None:
        properties["fermi_energy"] = fermi
    pdos_node = workchain.outputs.projwfc.Dos
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["DOS"],
        properties,
        [structure_object],
        lambda path: _render_xy_preview(pdos_node, path, "Projected density of states"),
        "pdos",
    )


def VibroWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    pw_base = next(
        (
            node
            for node in workchain.called_descendants
            if node.process_label == "PwBaseWorkChain"
        ),
        None,
    )
    if pw_base is None:
        raise ValueError("The vibrational workflow does not contain a PwBaseWorkChain.")
    output_parameters = pw_base.outputs.output_parameters.get_dict()
    dft_parameters = get_dft_parameters_qe(pw_base.inputs, output_parameters)
    properties = _simulation_properties(
        workchain,
        "Vibrational spectroscopy",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties["vibrational_mode"] = "Phonons"
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    phonon_pdos = workchain.outputs.phonon_pdos
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Vibrational Spectroscopy"],
        properties,
        [structure_object],
        lambda path: _render_xy_preview(
            phonon_pdos, path, "Vibrational density of states"
        ),
        "vibrational_spectrum",
    )


def _cp2k_output_parameters(workchain):
    output = _get_optional_output(workchain.outputs, "dft_output_parameters")
    if output is None:
        output = workchain.outputs.output_parameters
    return output.get_dict()


def Cp2kGeoOptWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    system_parameters = workchain.inputs.sys_params.get_dict()
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.code.description, workchain.inputs.dft_params.get_dict()
    )
    output_parameters = _cp2k_output_parameters(workchain)
    motion = output_parameters.get("motion_step_info", {})
    cell_optimization = workchain.label == "CP2K_CellOpt"

    properties = _simulation_properties(
        workchain,
        "Geometry optimization",
        dft_parameters,
        aiida_node_id,
        method_label=False,
        executable_ids=executable_ids,
    )
    properties.update(
        {
            "constrained": bool(system_parameters.get("constraints")),
            "cell_optimization": cell_optimization,
            "final_energy": _energy_in_hartree(output_parameters),
        }
    )
    if system_parameters.get("constraints"):
        properties["constraints_description"] = str(system_parameters["constraints"])
    if cell_optimization and system_parameters.get("cell_opt_constraint"):
        properties["cell_constraints"] = str(system_parameters["cell_opt_constraint"])
    if motion.get("max_grad_au"):
        properties["final_max_force"] = _quantity(
            motion["max_grad_au"][-1], "Hartree/bohr"
        )
    if motion.get("step"):
        properties["number_of_steps"] = int(motion["step"][-1])

    input_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    output_structure = workchain.outputs.output_structure
    geometry_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
        properties,
        [input_object],
        lambda path: _render_structure_preview(output_structure, path),
        "optimized_geometry",
    )
    output_object = structure_to_atomistic_model(
        openbis_session, output_structure.uuid, uuids
    )
    output_object.add_parents(geometry_object)
    utils.update_openbis_object(output_object)
    geometry_object.add_children(output_object)
    utils.update_openbis_object(geometry_object)
    return geometry_object


def Cp2kStmWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.spm_code.description, workchain.inputs.dft_params.get_dict()
    )
    properties = _simulation_properties(
        workchain,
        "STM",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties["spm_mode"] = "STM"
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["SPM Simulation"],
        properties,
        [structure_object],
        lambda path: _render_spm_preview(workchain, path),
        "stm_map",
    )


workchain_exporters = {
    "NanoribbonWorkChain": NanoribbonWorkChain_export,
    "PwRelaxWorkChain": PwRelaxWorkChain_export,
    "BandsWorkChain": BandsWorkChain_export,
    "PdosWorkChain": PdosWorkChain_export,
    "VibroWorkChain": VibroWorkChain_export,
    "Cp2kGeoOptWorkChain": Cp2kGeoOptWorkChain_export,
    "Cp2kStmWorkChain": Cp2kStmWorkChain_export,
}


def _run_exporter(
    openbis_session,
    experiment_id,
    workchain,
    structure_uuids,
    aiida_archive,
    resolved_executables,
):
    exporter = workchain_exporters[workchain.process_label]
    executable_ids = [
        resolved_executables[str(code.uuid)] for code in _workchain_codes(workchain)
    ]
    return exporter(
        openbis_session,
        experiment_id,
        workchain.uuid,
        structure_uuids,
        aiida_archive.permId,
        executable_ids=executable_ids,
    )


def export_workchain(
    openbis_session,
    experiment_id,
    workchain_uuid,
    create_missing_executables=False,
    provenance_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    workchains_to_export = get_all_preceding_main_workchains(workchain.uuid)
    export = None
    simulation_uuids_openbis = get_uuids_from_oBIS(openbis_session)

    pending_workchains = []
    for main_workchain_uuid in workchains_to_export:
        main_workchain = orm.load_node(main_workchain_uuid)
        if not main_workchain.is_finished_ok:
            continue
        if main_workchain_uuid in simulation_uuids_openbis["wc_uuids"]:
            continue
        pending_workchains.append(main_workchain)

    # Resolve every name before creating any archive or simulation object.
    resolved_executables = _ensure_executables_for_workchains(
        openbis_session,
        pending_workchains,
        create_missing=create_missing_executables,
        provenance_overrides=provenance_overrides,
    )

    for main_workchain in pending_workchains:
        main_workchain_uuid = main_workchain.uuid
        logger.info("dealing with main WC %s", main_workchain.pk)
        aiida_archive = create_and_export_AiiDA_archive(
            openbis_session, main_workchain_uuid
        )
        if main_workchain.process_label in workchain_exporters:
            export = _run_exporter(
                openbis_session,
                experiment_id,
                main_workchain,
                simulation_uuids_openbis["structure_uuids"],
                aiida_archive,
                resolved_executables,
            )
            simulation_uuids_openbis = get_uuids_from_oBIS(openbis_session)
            continue

        logger.info("%s checking sub_workchains", main_workchain.process_label)
        for child in main_workchain.called_descendants:
            if child.process_label not in workchain_exporters:
                continue
            export = _run_exporter(
                openbis_session,
                experiment_id,
                child,
                simulation_uuids_openbis["structure_uuids"],
                aiida_archive,
                resolved_executables,
            )
            simulation_uuids_openbis = get_uuids_from_oBIS(openbis_session)

    return export
