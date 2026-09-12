from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import random
import re
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from aiida import orm
from aiida.common.exceptions import NotExistentAttributeError
from aiida.common.links import LinkType
from ase import Atoms
from ase.io.jsonio import encode
from ase.units import Bohr, Hartree

from . import utils

OPENBIS_CONFIG = utils.read_json("config/openbis_config.json")
OPENBIS_COLLECTIONS_PATHS = OPENBIS_CONFIG["Collections"]["Paths"]
OPENBIS_OBJECT_TYPES = OPENBIS_CONFIG["OpenBIS Types"]
OPENBIS_SIMULATION_TYPES = OPENBIS_CONFIG["Simulation Export Types"]
OPENBIS_SESSION, SESSION_DATA = utils.connect_openbis_aiida()
PREVIEW_MAX_SIDE_PX = 500

# AiiDA calculation entry points identify executables (pw.x, pp.x, dos.x,
# projwfc.x, and so on), while an openBIS CODE identifies the software suite.
# EXECUTABLE objects retain the distinction between the individual programs.
AIIDA_PLUGIN_FAMILY_TO_OPENBIS_SOFTWARE = {
    "cp2k": "CP2K",
    "gaussian": "GAUSSIAN",
    "lammps": "LAMMPS",
    "orca": "ORCA",
    "quantumespresso": "Quantum ESPRESSO",
}


utils.LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger(__name__)
logging.basicConfig(
    filename=utils.LOG_FILE_PATH,
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
            number_electrons = round(sum([sum(i) for i in occupations]) / num_kpoints)

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

        crosses_fermi = any(i[1] < fermi_energy < i[0] for i in max_mins)
        # This only identifies a semimetal when the Dirac point is computed.
        touches_fermi = any(i[0] == fermi_energy for i in max_mins) and any(
            i[1] == fermi_energy for i in max_mins
        )
        if crosses_fermi or touches_fermi:
            return False, 0.0, None, None
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
            # RETURN only exposes an existing data node from a WorkChain. It does
            # not identify the process that created the data, and following it can
            # incorrectly traverse into a later workflow that reused that node.
            if input_link.link_type == LinkType.RETURN:
                continue
            trace_back_main_workchains(input_link.node)

        # CP2K path continuations identify the previous path WorkChain through
        # a UUID-valued input rather than a provenance link. Include it so a
        # continued MEP exports/imports as a new block linked to its predecessor.
        if getattr(n, "process_label", "") in {
            "Cp2kNebWorkChain",
            "Cp2kReplicaWorkChain",
        }:
            try:
                restart_from = n.inputs.restart_from
                restart_uuid = _node_value(restart_from)
                if restart_uuid:
                    trace_back_main_workchains(orm.load_node(str(restart_uuid)))
            except (AttributeError, NotExistentAttributeError, TypeError, ValueError):
                pass

    # Start tracing back from the given node
    trace_back_main_workchains(node)

    # A set made the archive/export order unpredictable. Creation time gives
    # the predecessor-first order required by linked scientific results.
    ordered = sorted(
        main_workchains,
        key=lambda wc: (
            str(getattr(wc, "ctime", "")),
            int(getattr(wc, "pk", 0) or 0),
            str(wc.uuid),
        ),
    )
    return [wc.uuid for wc in ordered]


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


def _node_mapping(node):
    """Return mapping data from modern Dict or legacy pythonjob Dict nodes."""
    get_dict = getattr(node, "get_dict", None)
    if callable(get_dict):
        return get_dict()
    # Archives produced by older aiida-pythonjob versions can expose built-in
    # Dict nodes as generic Data. Their mapping survives in node attributes.
    try:
        return dict(node.base.attributes.all)
    except AttributeError as exception:
        raise TypeError(f"{node!r} does not expose mapping data") from exception


def _node_value(node):
    """Return a scalar from modern AiiDA data or legacy pythonjob Data."""
    value_marker = object()
    value = getattr(node, "value", value_marker)
    if value is not value_marker:
        return value
    # Old aiida-pythonjob Bool, Float, Int, and Str nodes may be loaded as
    # generic Data while retaining their scalar in the value attribute.
    try:
        return node.base.attributes.all.get("value", node)
    except AttributeError:
        return node


def _pw_relax_base(workchain):
    """Return the QE relax input namespace across aiida-quantumespresso versions."""
    try:
        return workchain.inputs.base
    except (AttributeError, NotExistentAttributeError):
        return workchain.inputs.base_relax


def get_dft_parameters_qe(inputs, outputs):
    """Retrieves from QE workchains the parameters needed to create the DFT object
    in input the inputs of QE workchain and the output_parameters. Will be simplified when QeAppWorkchain
    bugs for not exposing some of the outputs will be fixed
    """

    system = _node_mapping(inputs.pw.parameters).get("SYSTEM", {})
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
        "xc_functional": dft_para.get("xc_functional", dft_para.get("xc", "")),
        "plus_u": bool(dft_para.get("plus_u", False)),
        "spin_orbit_coupling": bool(dft_para.get("spin_orbit_coupling", False)),
        "non_collinear": bool(dft_para.get("non_collinear", False)),
        "uks": bool(dft_para.get("uks", False)),
        "charge": float(dft_para.get("charge", 0.0)),
        "multiplicity": dft_para.get("multiplicity"),
        "vdw_corr": dft_para.get("vdw", ""),
        "hfx_fraction": float(dft_para.get("hfx_fraction", 0.0)),
    }


def geo_to_png(ase_geo, filename="ase_geo.png"):
    ase_geo.write(filename)
    return filename


def guess_dimensionality(
    ase_geo: Atoms | None = None, thr_vacuum: float = 5
) -> tuple[int, tuple[bool, bool, bool]] | None:
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
            cell_free = _node_mapping(creator.inputs.sys_params)["cell_opt_constraint"]
        return geo_opt, cell_opt, cell_free
    if creator.process_label == "QeAppWorkChain":
        for wc in creator.called_descendants:
            if wc.process_label == "PwRelaxWorkChain":
                geo_opt = True
                cell_free = (
                    _node_mapping(wc.inputs.base.pw.parameters)
                    .get("CELL", {})
                    .get("cell_dofree", "")
                )
                if cell_free != "":
                    cell_opt = True
                break
        return geo_opt, cell_opt, cell_free


def _objects_by_property(
    openbis_session, object_type, property_name, value, collection=None
):
    """Return objects matching an openBIS property through a server query."""
    kwargs = {
        "type": object_type,
        "where": {property_name.upper(): str(value)},
    }
    if collection is not None:
        kwargs["collection"] = collection
    return list(openbis_session.get_objects(**kwargs) or [])


def get_uuids_from_oBIS(openbis_session):
    aiida_node_type = OPENBIS_OBJECT_TYPES["AiiDA Node"]
    atom_model_type = OPENBIS_OBJECT_TYPES["Atomistic Model"]
    aiida_nodes_oBIS = _objects_by_property(
        openbis_session, aiida_node_type, "WFMS_UUID", "*"
    )
    atom_mods_oBIS = _objects_by_property(
        openbis_session, atom_model_type, "WFMS_UUID", "*"
    )

    simulation_uuids_oBIS = {"wc_uuids": [], "structure_uuids": []}

    if aiida_nodes_oBIS:
        simulation_uuids_oBIS["wc_uuids"] = [
            _openbis_property(obj, "wfms_uuid") for obj in aiida_nodes_oBIS
        ]

    if atom_mods_oBIS:
        simulation_uuids_oBIS["structure_uuids"] = [
            _openbis_property(obj, "wfms_uuid") for obj in atom_mods_oBIS
        ]

    return simulation_uuids_oBIS


# Assuming 'data' is an AiiDA Data object
def aiida_data_to_json(data_uuid):
    """Exports AiiDA xxData object as .json. Does not work for StructureData"""
    data = orm.load_node(data_uuid)

    # temporary fix waiting for https://github.com/aiidateam/aiida-quantumespresso/pull/1188
    # projwfc creates BandsData with U8 instead of floats
    if data.__class__.__name__ == "BandsData" and data.get_bands().dtype != np.dtype(
        "float64"
    ):
        new = data.clone()
        new.set_bands(new.get_bands().astype(float))
        data = new.clone()
    # end temporary fix

    # Close the temporary file before AiiDA exports into the same path.
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".json", delete=False
    ) as temp_file:
        temp_name = temp_file.name
    try:
        data.export(temp_name, fileformat="json", overwrite=True)
        with open(temp_name) as handle:
            json_string = handle.read()
    finally:
        os.remove(temp_name)

    return json_string


ELN_ORIGIN_EXTRA = "eln"


def _structure_fingerprint(atoms):
    """Return a stable digest for exact structure-origin identity checks."""
    payload = {
        "symbols": atoms.get_chemical_symbols(),
        "positions": atoms.get_positions().round(12).tolist(),
        "cell": atoms.cell.array.round(12).tolist(),
        "pbc": [bool(value) for value in atoms.pbc],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_openbis_instance(value):
    value = str(value or "").strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value if "://" in value else f"https://{value}")
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _openbis_origin_object(openbis_session, structure, expected_type):
    origin = structure.base.extras.get(ELN_ORIGIN_EXTRA, None)
    if not isinstance(origin, Mapping):
        return None, None
    if str(origin.get("eln_type", "openbis")).lower() != "openbis":
        return None, None
    if str(origin.get("data_type", "")).upper() != expected_type:
        return origin, None

    source_instance = _normalize_openbis_instance(origin.get("eln_instance"))
    session_instance = _normalize_openbis_instance(getattr(openbis_session, "url", ""))
    if source_instance and session_instance and source_instance != session_instance:
        raise ValueError(
            "The input structure originates from a different openBIS instance "
            f"({origin.get('eln_instance')})."
        )

    permid = origin.get("sample_uuid")
    if not permid:
        raise ValueError(
            "The input structure has incomplete openBIS provenance: sample_uuid "
            "is missing."
        )
    try:
        openbis_object = openbis_session.get_object(str(permid))
    except Exception as error:
        raise ValueError(
            f"The referenced openBIS object {permid} is not available."
        ) from error
    if _openbis_type_code(openbis_object) != expected_type:
        raise ValueError(
            f"The referenced openBIS object {permid} is not a {expected_type}."
        )
    return origin, openbis_object


def _openbis_reference(value):
    return str(
        getattr(value, "permId", None) or getattr(value, "identifier", None) or value
    )


def _ensure_openbis_parent(openbis_object, parent):
    parent_id = _openbis_reference(parent)
    current = {
        _openbis_reference(item)
        for item in (getattr(openbis_object, "parents", []) or [])
    }
    if parent_id in current:
        return
    openbis_object.add_parents(parent)
    utils.update_openbis_object(openbis_object)


def structure_to_atomistic_model(openbis_session, structure_uuid, uuids):
    """Return the matching atomistic model or create it with ELN provenance."""
    del uuids  # Kept for API compatibility with existing exporters.
    structure = orm.load_node(structure_uuid)
    atom_model_type = OPENBIS_OBJECT_TYPES["Atomistic Model"]
    ase_geo = structure.get_ase()

    molecule_origin, molecule = _openbis_origin_object(
        openbis_session, structure, "MOLECULE"
    )
    atomistic_origin, source_atomistic_model = _openbis_origin_object(
        openbis_session, structure, atom_model_type
    )

    # Atomistic models are shared inventory objects and are reused globally.
    atom_models_obis = _objects_by_property(
        openbis_session, atom_model_type, "WFMS_UUID", structure.uuid
    )
    if atom_models_obis:
        atomistic_model = atom_models_obis[0]
        if molecule is not None:
            _ensure_openbis_parent(atomistic_model, molecule)
        return atomistic_model

    if source_atomistic_model is not None:
        expected = str(atomistic_origin.get("structure_fingerprint") or "")
        current = _structure_fingerprint(ase_geo)
        if expected and expected == current:
            existing_uuid = str(
                _openbis_property(source_atomistic_model, "wfms_uuid") or ""
            )
            if existing_uuid and existing_uuid != str(structure.uuid):
                raise ValueError(
                    "The source ATOMISTIC_MODEL already references a different "
                    f"AiiDA StructureData UUID ({existing_uuid}); it was not overwritten."
                )
            if not existing_uuid:
                source_atomistic_model.props["wfms_uuid"] = str(structure.uuid)
                utils.update_openbis_object(source_atomistic_model)
            return source_atomistic_model
        # The imported geometry was edited: preserve the source object and create a
        # distinct atomistic model for the actual workflow input.

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

    parents = [molecule] if molecule is not None else None
    obobject = utils.create_openbis_object(
        openbis_session,
        type=atom_model_type,
        props=dictionary,
        collection=OPENBIS_COLLECTIONS_PATHS["Atomistic Model"],
        parents=parents,
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
    """Create one shared AiiDA archive object, or reuse the existing one."""
    aiida_node_type = OPENBIS_OBJECT_TYPES["AiiDA Node"]
    existing = _objects_by_property(openbis_session, aiida_node_type, "WFMS_UUID", uuid)
    if existing:
        return existing[0]

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
            props={
                "wfms_uuid": str(uuid),
                "aiida_root_uuids": [str(uuid)],
                "comments": "",
            },
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


OPENBIS_EXPORTS_EXTRA = "openbis_exports"


def _openbis_type_code(openbis_object):
    object_type = getattr(openbis_object, "type", "")
    return str(getattr(object_type, "code", object_type))


def _openbis_collection_id(openbis_object, fallback=""):
    collection = getattr(openbis_object, "collection", fallback)
    return str(
        getattr(collection, "identifier", getattr(collection, "code", collection))
        or fallback
    )


def _openbis_eln_url(openbis_object):
    try:
        return str(openbis_object.get_eln_url())
    except (AttributeError, TypeError, ValueError):
        return ""


def record_openbis_exports(openbis_session, openbis_objects, collection=""):
    """Cache verified openBIS result links on their concrete AiiDA source nodes."""
    server = str(getattr(openbis_session, "url", "") or "")
    for openbis_object in normalize_exported_objects(openbis_objects):
        source_uuid = getattr(openbis_object, "_aiidalab_source_uuid", None)
        if not source_uuid:
            source_uuid = _openbis_property(openbis_object, "aiida_source_uuid")
        role = getattr(openbis_object, "_aiidalab_result_role", None)
        if not role:
            role = _openbis_type_code(openbis_object).lower()
        if not source_uuid or not role:
            continue
        try:
            source = orm.load_node(str(source_uuid))
        except Exception:  # noqa: BLE001 - imported archive may omit a source plugin
            logger.warning(
                "Could not record openBIS export for unavailable AiiDA node %s",
                source_uuid,
            )
            continue
        record = {
            "server": server,
            "collection": _openbis_collection_id(openbis_object, collection),
            "object_type": _openbis_type_code(openbis_object),
            "result_role": str(role),
            "permid": str(openbis_object.permId),
            "url": _openbis_eln_url(openbis_object),
        }
        records = list(source.base.extras.get(OPENBIS_EXPORTS_EXTRA, []))
        identity = (
            record["server"],
            record["collection"],
            record["object_type"],
            record["result_role"],
        )
        records = [
            item
            for item in records
            if (
                item.get("server", ""),
                item.get("collection", ""),
                item.get("object_type", ""),
                item.get("result_role", ""),
            )
            != identity
        ]
        records.append(record)
        source.base.extras.set(OPENBIS_EXPORTS_EXTRA, records)


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
    """Return a property from a pyBIS object as exposed by ``props()``."""
    properties = openbis_object.props
    if callable(properties):
        properties = properties()
    return properties.get(property_name)


def _aiida_uuid_comment(kind, uuid):
    return f"AiiDA {kind} UUID: {uuid}"


def _find_object_by_comment(openbis_session, object_type, comment):
    """Find an object by a marker in COMMENTS using a server-side query."""
    matches = list(
        openbis_session.get_objects(
            type=object_type,
            where={"COMMENTS": f"*{comment}*"},
        )
        or []
    )
    return matches[0] if matches else None


def _find_object_by_permid(openbis_session, permid):
    """Resolve a permID directly instead of scanning an object inventory."""
    try:
        return openbis_session.get_object(str(permid))
    except ValueError:
        return None


def _openbis_object_options(objects):
    return tuple(
        (
            str(openbis_object.permId),
            str(_openbis_property(openbis_object, "name") or openbis_object.permId),
        )
        for openbis_object in objects
    )


def _selected_openbis_object(
    openbis_session, provenance_overrides, object_kind, aiida_uuid
):
    if not provenance_overrides:
        return None
    selected_permid = provenance_overrides.get(object_kind, {}).get(str(aiida_uuid))
    if not selected_permid:
        return None
    selected = _find_object_by_permid(openbis_session, selected_permid)
    if selected is None:
        raise ExecutableResolutionError(
            f"Selected openBIS {object_kind} object {selected_permid} no longer exists."
        )
    expected_type = OPENBIS_OBJECT_TYPES[object_kind]
    actual_type = str(getattr(getattr(selected, "type", None), "code", selected.type))
    if actual_type != expected_type:
        raise ExecutableResolutionError(
            f"Selected object {selected_permid} is {actual_type}, not {expected_type}."
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


def _software_search_names(aiida_code):
    """Return ordered openBIS software names for an AiiDA executable."""
    plugin = str(getattr(aiida_code, "default_calc_job_plugin", "") or "")
    plugin_family = plugin.partition(".")[0].lower()
    software_name = AIIDA_PLUGIN_FAMILY_TO_OPENBIS_SOFTWARE.get(plugin_family)
    executable_label = str(aiida_code.label or "")
    if software_name:
        return (software_name, executable_label)
    return (executable_label,)


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


def _reference_name(openbis_session, reference):
    permid = _object_reference_id(reference)
    if not permid:
        return "unlinked"
    referenced = _find_object_by_permid(openbis_session, permid)
    if referenced is None:
        return permid
    return str(_openbis_property(referenced, "name") or permid)


def _openbis_executable_options(openbis_session, executable_objects):
    options = []
    for executable in executable_objects:
        name = str(_openbis_property(executable, "name") or executable.permId)
        code = _reference_name(openbis_session, _openbis_property(executable, "code"))
        computer = _reference_name(
            openbis_session, _openbis_property(executable, "computer")
        )
        details = f"{name}; code {code}; computer {computer}"
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
            openbis_session,
            provenance_overrides,
            "Executable",
            aiida_code_uuid,
        )
        if executable is None:
            executable = _find_object_by_comment(
                openbis_session,
                executable_type,
                _aiida_uuid_comment("Code", aiida_code.uuid),
            )
        if executable is not None:
            resolved[aiida_code_uuid] = executable.permId
            continue

        software = _selected_openbis_object(
            openbis_session, provenance_overrides, "Code", aiida_code_uuid
        )
        if software is None:
            software_names = _software_search_names(aiida_code)
            try:
                software = _match_named_openbis_object(
                    software_names[0],
                    code_objects,
                    "Code",
                    additional_names=software_names[1:],
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
            openbis_session,
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
                        openbis_session, executable_objects
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
    return float(value_hartree)


def _method_modifiers(dft_parameters):
    modifiers = []
    xc = str(dft_parameters.get("xc_functional", "")).upper()
    if float(dft_parameters.get("hfx_fraction", 0.0)) > 0.0 or any(
        label in xc for label in ("PBE0", "HSE", "B3LYP", "HYBRID")
    ):
        modifiers.append("HYBRID")
    vdw = str(dft_parameters.get("vdw_corr", "")).strip().lower()
    if vdw not in {"", "0", "false", "no", "none"}:
        modifiers.append("VDW")
    if dft_parameters.get("plus_u"):
        modifiers.append("DFT_U")
    if dft_parameters.get("spin_orbit_coupling"):
        modifiers.append("SPIN_ORBIT")
    if dft_parameters.get("non_collinear"):
        modifiers.append("SPIN_NON_COLLINEAR")
    elif dft_parameters.get("uks"):
        modifiers.append("SPIN_COLLINEAR")
    return modifiers


def _workchain_description(workchain):
    """Return the user-authored description associated with a workflow."""
    description = getattr(workchain, "description", "")
    if not description:
        caller = getattr(workchain, "caller", None)
        description = getattr(caller, "description", "") if caller else ""
    return str(description or "").strip()


def _workchain_name(workchain, prefix):
    description = _workchain_description(workchain)
    suffix = description[:80] if description else str(workchain.uuid)[:8]
    formula = None
    try:
        structure = workchain.inputs.structure
        formula = structure.get_formula()
    except (AttributeError, NotExistentAttributeError):
        try:
            formula = structure.get_ase().get_chemical_formula()
        except (AttributeError, UnboundLocalError):
            pass
    if formula:
        return f"{prefix} {formula} - {suffix}"
    return f"{prefix} - {suffix}"


def _simulation_properties(
    workchain,
    prefix,
    dft_parameters,
    aiida_node_id,
    method_label=True,
    executable_ids=None,
    result_role=None,
):
    properties = {
        "name": _workchain_name(workchain, prefix),
        "method_family": "DFT",
        "method_modifiers": _method_modifiers(dft_parameters),
        "charge": float(dft_parameters.get("charge", 0.0)),
        "converged": bool(getattr(workchain, "is_finished_ok", True)),
        "aiida_node": aiida_node_id,
        "aiida_source_uuid": str(workchain.uuid),
        "_aiidalab_result_role": result_role
        or re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_"),
    }
    description = _workchain_description(workchain)
    if description:
        properties["comments"] = description
    if method_label:
        label = str(dft_parameters.get("xc_functional", "")).strip()
        if label.lower() not in {"", "unknown", "none", "n/a"}:
            properties["method_label"] = label
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
    return [float(value)]


def _namespace_value(namespace, label):
    """Return one value from an AiiDA namespace or a plain mapping."""
    if isinstance(namespace, dict):
        return namespace.get(label)
    return _get_optional_output(namespace, label)


def _nested_array_data(value, seen=None):
    """Yield array-data leaves from a nested AiiDA output namespace."""
    if value is None:
        return
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    if callable(getattr(value, "get_arraynames", None)):
        yield value
        return
    values = value.values if isinstance(value, dict) else getattr(value, "values", None)
    if callable(values):
        for child in values():
            yield from _nested_array_data(child, seen)


def _qe_vibrational_mode(workchain):
    """Classify all spectra represented by one QE VibroWorkChain object."""
    has_ir = False
    has_raman = False
    output_namespaces = []
    for branch_name in ("harmonic", "iraman"):
        branch = _namespace_value(workchain.outputs, branch_name)
        output_namespaces.append(_namespace_value(branch, "vibrational_data"))
    output_namespaces.append(_namespace_value(workchain.outputs, "vibrational_data"))

    for namespace in output_namespaces:
        for node in _nested_array_data(namespace):
            array_names = set(node.get_arraynames())
            try:
                attributes = node.base.attributes.all
            except AttributeError:
                attributes = {}
            has_ir = has_ir or (
                "born_charges" in array_names and "dielectric" in attributes
            )
            has_raman = has_raman or "raman_tensors" in array_names

    if has_ir and has_raman:
        return "PHONONS_IR_RAMAN"
    if has_ir:
        return "PHONONS_IR"
    if has_raman:
        return "PHONONS_RAMAN"
    return "PHONONS"


def _qe_relax_number_of_steps(workchain, output_parameters):
    """Return the total number of ionic steps across direct QE relax blocks."""
    steps = 0
    found = False
    for child in getattr(workchain, "called", ()) or ():
        if getattr(child, "process_label", "") != "PwBaseWorkChain":
            continue
        child_output = _get_optional_output(child.outputs, "output_parameters")
        if child_output is None:
            continue
        child_parameters = _node_mapping(child_output)
        child_steps = child_parameters.get("number_ionic_steps")
        if child_steps is None:
            child_steps = (
                child_parameters.get("convergence_info", {})
                .get("opt_conv", {})
                .get("n_opt_steps")
            )
        if child_steps is not None:
            steps += int(child_steps)
            found = True
    if found:
        return steps
    fallback = output_parameters.get("number_ionic_steps")
    return int(fallback) if fallback is not None else None


def _magnetization_properties(output_parameters):
    """Return QE magnetizations, preserving explicitly reported zero values."""
    properties = {}
    for source, target in (
        ("total_magnetization", "total_magnetization_bohr_magneton"),
        ("absolute_magnetization", "absolute_magnetization_bohr_magneton"),
    ):
        value = output_parameters.get(source)
        if value is not None:
            properties[target] = float(value)
    return properties


def _qe_relax_metadata(workchain, output_parameters):
    """Extract optional scientific metadata from a QE relaxation result."""
    metadata = {}
    trajectory = _get_optional_output(workchain.outputs, "output_trajectory")
    if trajectory is not None:
        try:
            forces = np.asarray(trajectory.get_array("forces"), dtype=float)
            final_forces = forces[-1]
            max_force = float(np.linalg.norm(final_forces, axis=-1).max())
            units = str(output_parameters.get("forces_units", "")).lower()
            normalized_units = re.sub(r"\s+", "", units)
            if normalized_units in {"ev/angstrom", "ev/ang", "ev/a"}:
                max_force *= Bohr / Hartree
            elif normalized_units in {"ry/bohr", "rydberg/bohr"}:
                max_force *= 0.5
            elif normalized_units not in {
                "ha/bohr",
                "hartree/bohr",
                "a.u.",
                "au",
            }:
                max_force = None
            if max_force is not None:
                metadata["final_max_force_hartree_per_bohr"] = max_force
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

    number_of_steps = _qe_relax_number_of_steps(workchain, output_parameters)
    if number_of_steps is not None:
        metadata["number_of_steps"] = number_of_steps

    fermi = _fermi_energy(output_parameters)
    if fermi is not None:
        metadata["fermi_energy_ev"] = fermi

    bands = _get_optional_output(workchain.outputs, "output_band")
    electron_count = output_parameters.get("number_of_electrons")
    if bands is not None and electron_count is not None:
        try:
            _is_insulator, gap, _homo, _lumo = find_bandgap(
                bands.uuid, number_electrons=electron_count
            )
        except (AttributeError, TypeError, ValueError):
            gap = None
        if gap is not None:
            metadata["electronic_gap_ev"] = [float(gap)]

    metadata.update(_magnetization_properties(output_parameters))
    return metadata


def _qe_relax_properties(workchain, aiida_node_id=None, executable_ids=None):
    """Build the shared openBIS properties for a QE relaxation."""
    base = _pw_relax_base(workchain)
    input_parameters = _node_mapping(base.pw.parameters)
    output_parameters = _node_mapping(workchain.outputs.output_parameters)
    dft_parameters = get_dft_parameters_qe(base, output_parameters)
    calculation = str(
        input_parameters.get("CONTROL", {}).get("calculation", "relax")
    ).lower()
    properties = _simulation_properties(
        workchain,
        "Geometry optimization",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties.update(
        {
            "constrained": False,
            "cell_optimization": calculation == "vc-relax",
            "final_energy_hartree": _energy_in_hartree(output_parameters),
        }
    )
    cell_constraints = input_parameters.get("CELL", {}).get("cell_dofree")
    if cell_constraints:
        properties["cell_constraints"] = str(cell_constraints)
    properties.update(_qe_relax_metadata(workchain, output_parameters))
    return properties


def _input_value(workchain, label, default=None):
    """Return the plain value of an optional AiiDA input."""
    try:
        value = getattr(workchain.inputs, label)
    except (AttributeError, NotExistentAttributeError):
        return default
    return _node_value(value)


def _repository_text(data_node, filename):
    """Read a UTF-8 text file from an AiiDA repository node."""
    with data_node.base.repository.open(filename, mode="r") as handle:
        return handle.read()


def _cp2k_scf_output_text(workchain):
    """Return the final CP2K stdout retained by a Cp2kScfWorkChain."""
    for label in ("retrieved", "ot_retrieved"):
        retrieved = _get_optional_output(workchain.outputs, label)
        if retrieved is None:
            continue
        try:
            return _repository_text(retrieved, "aiida.out")
        except (FileNotFoundError, OSError):
            continue
    return ""


def _cp2k_fermi_energies(output_parameters, output_text):
    """Extract the final printed CP2K Fermi energy for each spin channel."""
    values = []
    for line in output_text.splitlines():
        if "fermi energy" not in line.lower() or "ev" not in line.lower():
            continue
        match = re.search(
            r"Fermi\s+Energy.*?\[eV\]\s*[:=]\s*"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            values.append(float(match.group(1)))

    if values:
        number_of_spins = (
            2 if str(output_parameters.get("dft_type", "")).upper() == "UKS" else 1
        )
        return values[-number_of_spins:]
    return _fermi_energy(output_parameters)


def _cp2k_electronic_gaps(output_parameters):
    """Return one RKS gap or the two UKS gaps in eV when available."""
    is_uks = str(output_parameters.get("dft_type", "")).upper() == "UKS"
    spin_channels = (1, 2) if is_uks else (1,)
    gaps = []
    for spin in spin_channels:
        value = output_parameters.get(f"printed_bandgap_spin{spin}_ev")
        if value is None:
            value = output_parameters.get(f"bandgap_spin{spin}_au")
            if value is not None:
                value = float(value) * Hartree
        if value is not None:
            gaps.append(float(value))
    return gaps or None


def _cp2k_pdos_full_system_process(workchain):
    """Return the CP2K process that produced the full-system PDOS."""
    structure_uuid = str(workchain.inputs.structure.uuid)
    diag_workchains = [
        process
        for process in workchain.called_descendants
        if getattr(process, "process_label", "") == "Cp2kDiagWorkChain"
    ]
    exact_matches = []
    for process in diag_workchains:
        try:
            if str(process.inputs.structure.uuid) == structure_uuid:
                exact_matches.append(process)
        except (AttributeError, NotExistentAttributeError):
            continue
    candidates = exact_matches or diag_workchains
    if not candidates:
        candidates = [
            process
            for process in workchain.called_descendants
            if getattr(process, "label", "") == "slab_scf"
        ]
    if not candidates:
        raise ValueError("The CP2K PDOS workflow has no full-system calculation.")
    return min(
        candidates,
        key=lambda process: (
            str(getattr(process, "ctime", "")),
            int(getattr(process, "pk", 0) or 0),
        ),
    )


def _cp2k_pdos_retrieved(workchain):
    retrieved = _get_optional_output(workchain.outputs, "slab_retrieved")
    if retrieved is not None:
        return retrieved
    process = _cp2k_pdos_full_system_process(workchain)
    retrieved = _get_optional_output(process.outputs, "retrieved")
    if retrieved is None:
        raise ValueError("The CP2K PDOS workflow has no retrieved full-system data.")
    return retrieved


def _cp2k_pdos_output_parameters(workchain):
    process = _cp2k_pdos_full_system_process(workchain)
    output = _get_optional_output(process.outputs, "output_parameters")
    if output is None:
        raise ValueError("The CP2K PDOS workflow has no output parameters.")
    return _node_mapping(output)


def _cp2k_pdos_fermi_energies(workchain, output_parameters=None):
    """Return spin-resolved PDOS references in eV."""
    if output_parameters is None:
        output_parameters = _cp2k_pdos_output_parameters(workchain)
    retrieved = _cp2k_pdos_retrieved(workchain)
    try:
        output_text = _repository_text(retrieved, "aiida.out")
    except (FileNotFoundError, OSError):
        output_text = ""
    values = _cp2k_fermi_energies(output_parameters, output_text)
    if values is not None:
        return values

    # Legacy CP2K parsers retain occupied eigenvalues but may omit a dedicated
    # Fermi-energy field. The last occupied value is then the reliable reference.
    references = []
    for spin in (1, 2):
        eigenvalues = output_parameters.get(f"eigen_spin{spin}_au", [])
        if eigenvalues:
            references.append(float(eigenvalues[-1]) * Hartree)
    return references or None


def _cp2k_pdos_series(workchain, output_parameters=None):
    """Return total spin-resolved PDOS curves relative to their references."""
    if output_parameters is None:
        output_parameters = _cp2k_pdos_output_parameters(workchain)
    retrieved = _cp2k_pdos_retrieved(workchain)
    filenames = sorted(
        name
        for name in retrieved.base.repository.list_object_names()
        if name.lower().endswith(".pdos")
    )
    kind_filenames = [name for name in filenames if "list" not in name.lower()]
    filenames = kind_filenames or filenames
    if not filenames:
        raise ValueError("The CP2K PDOS workflow contains no .pdos files.")

    curves = {}
    for filename in filenames:
        with retrieved.base.repository.open(filename, mode="r") as handle:
            handle.readline()
            data = np.asarray(np.loadtxt(handle), dtype=float)
        if data.ndim == 1:
            data = data[np.newaxis, :]
        if data.shape[1] < 4:
            continue
        spin = 1 if "BETA" in filename.upper() else 0
        energies_ev = data[:, 1] * Hartree
        density = np.sum(data[:, 3:], axis=1)
        if spin not in curves:
            curves[spin] = [energies_ev, density]
            continue
        reference_energies, accumulated = curves[spin]
        if np.array_equal(reference_energies, energies_ev):
            accumulated += density
        else:
            accumulated += np.interp(reference_energies, energies_ev, density)

    if not curves:
        raise ValueError("The CP2K PDOS files contain no usable projected data.")
    references = _cp2k_pdos_fermi_energies(workchain, output_parameters) or []
    series = []
    spin_polarized = len(curves) > 1
    for spin, (energies_ev, density) in sorted(curves.items()):
        reference = references[min(spin, len(references) - 1)] if references else 0.0
        label = ("Alpha" if spin == 0 else "Beta") if spin_polarized else "Total"
        plotted_density = -density if spin == 1 and spin_polarized else density
        series.append((label, energies_ev - reference, plotted_density))
    return series


def _cp2k_pdos_projection_description(workchain):
    try:
        selections_node = workchain.inputs.pdos_lists
        get_list = getattr(selections_node, "get_list", None)
        selections = get_list() if callable(get_list) else list(selections_node)
    except (AttributeError, NotExistentAttributeError, TypeError):
        selections = []
    labels = []
    for selection in selections:
        if isinstance(selection, (list, tuple)) and len(selection) >= 2:
            labels.append(f"{selection[1]} ({selection[0]})")
        else:
            labels.append(str(selection))
    description = "CP2K atom- and kind-projected density of states"
    if labels:
        description += " for selections: " + "; ".join(labels)
    description += ". Full arrays are stored in the linked AiiDA archive."
    do_overlap = _input_value(workchain, "do_overlap", False)
    if bool(do_overlap):
        description += " Molecular-orbital overlap analysis is also included."
    return description


def _cp2k_pdos_property_definition(
    workchain,
    aiida_node_id=None,
    executable_ids=None,
):
    """Build the openBIS DOS result produced by a Cp2kPdosWorkChain."""
    process = _cp2k_pdos_full_system_process(workchain)
    dft_input = _get_optional_output(process.inputs, "dft_params")
    if dft_input is None:
        dft_input = workchain.inputs.dft_params
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.cp2k_code.description,
        _node_mapping(dft_input),
    )
    output_parameters = _cp2k_pdos_output_parameters(workchain)
    properties = _simulation_properties(
        workchain,
        "PDOS",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
        result_role="pdos",
    )
    properties.update(
        {
            "pdos": True,
            "projection_description": _cp2k_pdos_projection_description(workchain),
        }
    )
    fermi_energies = _cp2k_pdos_fermi_energies(workchain, output_parameters)
    if fermi_energies is not None:
        properties["fermi_energy_ev"] = fermi_energies
    electronic_gaps = _cp2k_electronic_gaps(output_parameters)
    if electronic_gaps is not None:
        properties["electronic_gap_ev"] = electronic_gaps
    series = _cp2k_pdos_series(workchain, output_parameters)
    properties["energy_min_ev"] = min(float(np.min(curve[1])) for curve in series)
    properties["energy_max_ev"] = max(float(np.max(curve[1])) for curve in series)
    return {
        "pdos": {
            "object_type": OPENBIS_SIMULATION_TYPES["DOS"],
            "properties": properties,
        }
    }


def _render_cp2k_pdos_preview(workchain, path):
    """Reuse the surfaces PDOS model for a compact frontier-state preview."""
    try:
        from matplotlib.figure import Figure
        from surfaces_tools.widgets.pdos import (
            PdosOverlapViewerWidget,
            load_overlap_npz,
        )

        viewer = PdosOverlapViewerWidget()
        viewer.uks = bool(_input_value(workchain, "do_overlap", False))
        viewer._projections.workchain = workchain
        projection_data = viewer._projections.data
        spin_count = len(projection_data["tdos"])
        viewer.uks = spin_count > 1

        # The normal viewer starts from total DOS only. Add the chemically useful
        # molecule projection to the ELN suggestion when the workflow produced it.
        if "molecule" in viewer._projections.options:
            for spin in range(spin_count):
                viewer._projections.add_item(None)
                item = viewer._projections.items[-1]
                item._data_selection.label = "molecule"
                item._spin_selector.value = spin

        viewer.do_overlap = bool(_input_value(workchain, "do_overlap", False))
        if viewer.do_overlap:
            overlap = next(
                (
                    process
                    for process in workchain.called_descendants
                    if getattr(process, "label", "") == "overlap"
                    or getattr(process, "process_label", "") == "OverlapCalculation"
                ),
                None,
            )
            if overlap is None:
                viewer.do_overlap = False
            else:
                retrieved = _get_optional_output(overlap.outputs, "retrieved")
                with retrieved.open("overlap.npz", mode="rb") as handle:
                    viewer._overlap.data = load_overlap_npz(handle.name)
                # A full interactive viewer may show many orbitals. The ELN image
                # keeps only the frontier HOMO/LUMO pair for every spin channel.
                viewer._overlap.items = tuple(
                    item
                    for item in viewer._overlap.items
                    if re.search(
                        r"-(?:HOMO|LUMO)\s+\(",
                        item._data_selection.label,
                    )
                )
                viewer.cumulative_plot.value = False

        energy_values = []
        for key, channels in projection_data.items():
            if str(key).startswith("_"):
                continue
            for channel in channels:
                values = np.asarray(channel, dtype=float)
                if values.ndim == 2 and values.shape[1] >= 1:
                    energy_values.extend(values[:, 0])
        if not energy_values:
            raise ValueError("The CP2K PDOS viewer contains no energy grid.")

        lower = float(np.min(energy_values))
        upper = float(np.max(energy_values))
        overlap_parameters = _get_optional_output(workchain.inputs, "overlap_params")
        if overlap_parameters is not None:
            overlap_parameters = _node_mapping(overlap_parameters)
            lower = float(overlap_parameters.get("--emin1", lower))
            upper = float(overlap_parameters.get("--emax1", upper))
        if upper <= lower:
            raise ValueError("The CP2K PDOS energy interval is empty.")

        slider = viewer._energy_range_slider
        slider.min = min(lower, 0.0)
        slider.max = max(upper, 0.0)
        slider.value = (lower, upper)
        slider.min = lower
        slider.max = upper

        delta_energy = min(viewer._fwhm_slider.value / 10.0, 0.005)
        energy_grid = np.arange(lower, upper, delta_energy)
        collected = np.reshape(energy_grid, (1, energy_grid.size))
        headers = ["energy [eV]"]
        limits = [None, None]

        figure = Figure(figsize=(9, 4.8), constrained_layout=True)
        axis = figure.subplots()
        headers, collected = viewer._plot_projections(
            axis, limits, energy_grid, collected, headers
        )
        if viewer.do_overlap and viewer._overlap.items:
            viewer._plot_overlaps(axis, limits, energy_grid, collected, headers)
        if spin_count == 1:
            limits[0] = 0.0
        axis.set_xlim(lower, upper)
        axis.set_ylim(limits)
        axis.axhline(0.0, color="black", lw=1.2, zorder=400)
        axis.set_xlabel(r"$E-E_{ref}$ (eV)")
        axis.set_ylabel("Density of states (a.u.)")
        axis.set_title("CP2K projected density of states")
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(
                handles,
                labels,
                ncol=2 if spin_count > 1 else 1,
                loc="center left",
                bbox_to_anchor=(1.01, 0.5),
                fontsize="small",
            )
        figure.savefig(path, dpi=160, bbox_inches="tight")
        return
    except Exception:
        # surfaces is optional for aiidalab-openbis. Keep a dependency-free
        # fallback for installations that can read the archive but lack the app.
        logger.warning(
            "Could not reuse the surfaces CP2K PDOS viewer; using total PDOS.",
            exc_info=True,
        )

    from matplotlib.figure import Figure

    figure = Figure(figsize=(7, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for label, energies_ev, density in _cp2k_pdos_series(workchain):
        axis.plot(energies_ev, density, label=label)
    axis.axvline(0.0, color="black", ls="--", lw=0.8)
    axis.axhline(0.0, color="black", lw=0.6)
    axis.set_xlabel("Energy relative to reference (eV)")
    axis.set_ylabel("Projected density of states (a.u.)")
    axis.set_title("CP2K projected density of states")
    if len(axis.lines) > 3:
        axis.legend(fontsize="small")
    figure.savefig(path, dpi=160)


_CP2K_CHARGE_ANALYSIS_MARKERS = (
    ("mulliken population analysis", "Mulliken"),
    ("hirshfeld charges", "Hirshfeld"),
    ("lowdin population analysis", "Löwdin"),
)

_BADER_RESULT_FILENAMES = ("ACF.dat", "AVF.dat", "BCF.dat")


def _cp2k_charge_analysis_methods(workchain, output_text=None):
    """Report only charge analyses that are demonstrably present in the archive."""
    output_text = (
        _cp2k_scf_output_text(workchain) if output_text is None else output_text
    )
    methods = []
    lower_text = output_text.lower()
    for marker, method in _CP2K_CHARGE_ANALYSIS_MARKERS:
        if marker in lower_text:
            methods.append(method)

    bader = _get_optional_output(workchain.outputs, "bader_retrieved")
    if bader is not None:
        try:
            names = bader.base.repository.list_object_names()
        except (AttributeError, OSError):
            names = []
        if "ACF.dat" in names:
            methods.append("Bader")
    return methods


def _cp2k_charge_analysis_extract(output_text):
    """Extract the final complete CP2K table for each population method."""
    lines = output_text.splitlines()
    lower_lines = [line.lower() for line in lines]
    separator = re.compile(r"^\s*!-{20,}!\s*$")
    sections = []

    for marker, _method in _CP2K_CHARGE_ANALYSIS_MARKERS:
        occurrences = [
            index for index, line in enumerate(lower_lines) if marker in line
        ]
        if not occurrences:
            continue
        marker_index = occurrences[-1]
        start = next(
            (
                index
                for index in range(marker_index - 1, -1, -1)
                if separator.match(lines[index])
            ),
            marker_index,
        )
        end = next(
            (
                index
                for index in range(marker_index + 1, len(lines))
                if separator.match(lines[index])
            ),
            len(lines) - 1,
        )
        sections.append((marker_index, "\n".join(lines[start : end + 1]).strip()))

    if not sections:
        return ""
    return "\n\n".join(section for _index, section in sorted(sections)) + "\n"


def _cp2k_charge_analysis_files(workchain, directory):
    """Materialize compact population tables and standard Bader result files."""
    paths = []
    extract = _cp2k_charge_analysis_extract(_cp2k_scf_output_text(workchain))
    if extract:
        output_path = directory / "cp2k_charge_analysis.txt"
        output_path.write_text(extract, encoding="utf-8")
        paths.append(output_path)

    bader = _get_optional_output(workchain.outputs, "bader_retrieved")
    if bader is None:
        return paths
    for filename in _BADER_RESULT_FILENAMES:
        try:
            with bader.base.repository.open(filename, mode="rb") as source:
                content = source.read()
        except (FileNotFoundError, OSError):
            continue
        output_path = directory / filename
        output_path.write_bytes(content)
        paths.append(output_path)
    return paths


def _attach_cp2k_charge_analysis_data(openbis_session, charge_object, workchain):
    """Attach compact charge tables only when a charge object was newly created."""
    if not getattr(charge_object, "_aiidalab_created", False):
        return
    with tempfile.TemporaryDirectory(
        prefix="aiidalab-openbis-charge-analysis-"
    ) as dirname:
        files = _cp2k_charge_analysis_files(workchain, Path(dirname))
        if files:
            utils.create_openbis_dataset(
                openbis_session,
                type="RAW_DATA",
                sample=charge_object,
                files=files,
            )


def _scf_executable_ids(workchain, executable_ids, purpose):
    """Select the executables participating in one SCF-derived result."""
    if executable_ids is None:
        return None
    executable_ids = list(executable_ids)
    pairs = list(zip(_workchain_codes(workchain), executable_ids))
    if not pairs:
        return executable_ids

    def code_name(code):
        return f"{getattr(code, 'label', '')} {getattr(code, 'full_label', '')}".lower()

    cp2k = [permid for code, permid in pairs if "cp2k" in code_name(code)]
    if purpose == "energy":
        return cp2k or executable_ids
    if purpose == "charge":
        bader = [permid for code, permid in pairs if "bader" in code_name(code)]
        return list(dict.fromkeys((cp2k or executable_ids) + bader))
    if purpose == "unfolding":
        unfolding = [
            permid
            for code, permid in pairs
            if "unfold" in code_name(code) or "bandup" in code_name(code)
        ]
        return list(dict.fromkeys((cp2k or executable_ids) + unfolding))
    return executable_ids


def _cp2k_charge_analysis_definition(
    workchain,
    dft_parameters,
    output_parameters,
    aiida_node_id=None,
    executable_ids=None,
    converged=None,
):
    """Build a charge-analysis result when CP2K retained final charge tables."""
    output_text = _cp2k_scf_output_text(workchain)
    charge_methods = _cp2k_charge_analysis_methods(workchain, output_text)
    if not charge_methods:
        return None

    process_label = getattr(workchain, "process_label", "")
    if process_label == "Cp2kGeoOptWorkChain":
        name_prefix = "Final geometry population analysis"
    elif "Bader" in charge_methods:
        name_prefix = "Post-SCF charge analysis with Bader"
    else:
        name_prefix = "Post-SCF population analysis"

    properties = _simulation_properties(
        workchain,
        name_prefix,
        dft_parameters,
        aiida_node_id,
        executable_ids=_scf_executable_ids(workchain, executable_ids, "charge"),
        result_role="charge_analysis",
    )
    properties.update(
        {
            "charge_analysis_method": "; ".join(charge_methods),
            "converged": (
                bool(getattr(workchain, "is_finished_ok", True))
                if converged is None
                else bool(converged)
            ),
        }
    )
    fermi_energies = _cp2k_fermi_energies(output_parameters, output_text)
    if fermi_energies is not None:
        properties["fermi_energy_ev"] = fermi_energies
    electronic_gaps = _cp2k_electronic_gaps(output_parameters)
    if electronic_gaps is not None:
        properties["electronic_gap_ev"] = electronic_gaps
    return {
        "object_type": OPENBIS_SIMULATION_TYPES["Charge Analysis"],
        "properties": properties,
    }


def _unfolding_archive_data(workchain):
    """Load the compact metadata and arrays retained by an unfolding workflow."""
    retrieved = _get_optional_output(workchain.outputs, "unfolding_retrieved")
    if retrieved is None:
        retrieved = _get_optional_output(workchain.outputs, "banduppy_retrieved")
    if retrieved is None:
        raise ValueError("The workflow does not contain unfolding output data.")
    with (
        retrieved.base.repository.open("unfolding_bands.npz", mode="rb") as handle,
        np.load(handle, allow_pickle=True) as archive,
    ):
        return {key: np.array(archive[key], copy=True) for key in archive.files}


def _unfolding_supercell_matrix(workchain, data):
    """Return the integer supercell matrix as JSON for openBIS."""
    matrix = data.get("supercell_matrix")
    parameters = _get_optional_output(workchain.inputs, "unfolding_parameters")
    if matrix is None and parameters is not None:
        matrix = _node_mapping(parameters).get("supercell_matrix")
    if matrix is None:
        raise ValueError("The unfolding result does not define a supercell matrix.")
    return json.dumps(np.asarray(matrix, dtype=int).tolist())


def _unfolding_k_path(workchain, data):
    """Return a compact high-symmetry path label for either implementation."""
    labels = None
    parameters = _get_optional_output(workchain.inputs, "unfolding_parameters")
    if parameters is not None:
        labels = _node_mapping(parameters).get("labels")
    if labels is None:
        labels = data.get("path_labels")
    if labels is None:
        labels = data.get("x_tick_labels")
    if labels is None:
        labels = _input_value(workchain, "unfolding_path")
    if isinstance(labels, np.ndarray):
        labels = labels.tolist()
    if isinstance(labels, (list, tuple)):
        return "-".join(str(label) for label in labels)
    if labels:
        return str(labels)
    raise ValueError("The unfolding result does not define a k-path.")


def _unfolding_energy_window(data):
    """Return the energy range relative to the stored reference energy."""
    if "unfolded_bandstructure" in data:
        bands = np.asarray(data["unfolded_bandstructure"], dtype=float)
        reference = float(np.asarray(data.get("fermi_energy", 0.0)).reshape(-1)[0])
        energies = bands[:, 2] - reference
    else:
        reference = float(np.asarray(data.get("ref_energy_ev", 0.0)).reshape(-1)[0])
        channels = [
            np.asarray(value, dtype=float).reshape(-1) - reference
            for key, value in data.items()
            if key.startswith("evals_ev_spin_")
        ]
        if not channels:
            return None
        energies = np.concatenate(channels)
    finite = energies[np.isfinite(energies)]
    if not finite.size:
        return None
    return float(np.min(finite)), float(np.max(finite))


def _qe_banduppy_property_definition(
    workchain, aiida_node_id=None, executable_ids=None
):
    """Build the common BAND_UNFOLDING metadata for QE/BandUPpy."""
    output_parameters_node = _get_optional_output(
        workchain.outputs, "reference_bands_parameters"
    )
    output_parameters = (
        _node_mapping(output_parameters_node)
        if output_parameters_node is not None
        else {}
    )
    system = _node_mapping(workchain.inputs.parameters).get("SYSTEM", {})
    dft_parameters = {
        "xc_functional": output_parameters.get("dft_exchange_correlation", "unknown"),
        "plus_u": bool(output_parameters.get("lda_plus_u_calculation", False)),
        "spin_orbit_coupling": bool(
            output_parameters.get("spin_orbit_calculation", False)
        ),
        "non_collinear": bool(output_parameters.get("non_colinear_calculation", False)),
        "uks": bool(output_parameters.get("lsda", False)),
        "charge": float(system.get("tot_charge", 0.0)),
        "vdw_corr": system.get("vdw_corr", ""),
    }
    data = _unfolding_archive_data(workchain)
    properties = _simulation_properties(
        workchain,
        "Band unfolding",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
        result_role="band_unfolding",
    )
    properties.update(
        {
            "unfolding_implementation": "BANDUPPY",
            "supercell_matrix": _unfolding_supercell_matrix(workchain, data),
            "k_path": _unfolding_k_path(workchain, data),
            "projection_description": (
                "BandUPpy spectral weights. Full unfolded arrays are stored in "
                "the linked AiiDA archive."
            ),
        }
    )
    if "fermi_energy" in data:
        properties["fermi_energy_ev"] = [
            float(np.asarray(data["fermi_energy"]).reshape(-1)[0])
        ]
    energy_window = _unfolding_energy_window(data)
    if energy_window is not None:
        properties["energy_min_ev"], properties["energy_max_ev"] = energy_window
    return {
        "band_unfolding": {
            "object_type": OPENBIS_SIMULATION_TYPES["Band Unfolding"],
            "properties": properties,
        }
    }


def _cp2k_scf_property_definitions(workchain, aiida_node_id=None, executable_ids=None):
    """Build schema properties for all scientific results of a CP2K SCF block."""
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.cp2k_code.description,
        _node_mapping(workchain.inputs.dft_params),
    )
    output_parameters = _node_mapping(workchain.outputs.output_parameters)
    output_text = _cp2k_scf_output_text(workchain)
    fermi_energies = _cp2k_fermi_energies(output_parameters, output_text)
    electronic_gaps = _cp2k_electronic_gaps(output_parameters)
    scf_steps = output_parameters.get("motion_step_info", {}).get("scf_converged", [])
    converged = bool(getattr(workchain, "is_finished_ok", True)) and (
        not scf_steps or bool(scf_steps[-1])
    )

    energy = _simulation_properties(
        workchain,
        "Energy calculation",
        dft_parameters,
        aiida_node_id,
        executable_ids=_scf_executable_ids(workchain, executable_ids, "energy"),
        result_role="energy_calculation",
    )
    energy.update(
        {
            "total_energy_hartree": _energy_in_hartree(output_parameters),
            "converged": converged,
        }
    )
    if fermi_energies is not None:
        energy["fermi_energy_ev"] = fermi_energies
    if electronic_gaps is not None:
        energy["electronic_gap_ev"] = electronic_gaps

    definitions = {
        "energy_calculation": {
            "object_type": OPENBIS_SIMULATION_TYPES["Energy Calculation"],
            "properties": energy,
        }
    }

    charge_definition = _cp2k_charge_analysis_definition(
        workchain,
        dft_parameters,
        output_parameters,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
        converged=converged,
    )
    if charge_definition is not None:
        definitions["charge_analysis"] = charge_definition

    unfolding = _get_optional_output(workchain.outputs, "unfolding_retrieved")
    if unfolding is not None:
        data = _unfolding_archive_data(workchain)
        band = _simulation_properties(
            workchain,
            "Band unfolding",
            dft_parameters,
            aiida_node_id,
            executable_ids=_scf_executable_ids(workchain, executable_ids, "unfolding"),
            result_role="band_unfolding",
        )
        band.update(
            {
                "unfolding_implementation": "CP2K_SPARSE_AO",
                "supercell_matrix": _unfolding_supercell_matrix(workchain, data),
                "k_path": _unfolding_k_path(workchain, data),
                "converged": converged,
                "projection_description": (
                    "Sparse atomic-orbital spectral weights generated by the CP2K "
                    "unfolding workflow. Full arrays are stored in the linked "
                    "AiiDA archive."
                ),
            }
        )
        if fermi_energies is not None:
            band["fermi_energy_ev"] = fermi_energies
        energy_window = _unfolding_energy_window(data)
        if energy_window is not None:
            band["energy_min_ev"], band["energy_max_ev"] = energy_window
        definitions["band_unfolding"] = {
            "object_type": OPENBIS_SIMULATION_TYPES["Band Unfolding"],
            "properties": band,
        }

    return definitions


def _namespace_items(namespace):
    """Return dynamic AiiDA namespace items, including simple test doubles."""
    if namespace is None:
        return []
    items = getattr(namespace, "items", None)
    if callable(items):
        return list(items())
    return list(vars(namespace).items())


def _ordered_namespace_nodes(namespace, prefixes=()):
    items = _namespace_items(namespace)
    if prefixes:
        items = [
            (label, node)
            for label, node in items
            if any(str(label).startswith(prefix) for prefix in prefixes)
        ]
    return [node for _label, node in sorted(items, key=lambda item: str(item[0]))]


def _replica_chain_profile(workchain):
    """Return path energies, CV values, and endpoint structures."""
    details = _get_optional_output(workchain.outputs, "details")
    detail_items = _namespace_items(details)
    detail_items.sort(
        key=lambda item: (
            0 if str(item[0]) == "initial_scf" else 1,
            str(item[0]),
        )
    )
    energies_hartree = []
    actual_values = []
    for _label, detail_node in detail_items:
        detail = _node_mapping(detail_node)
        parameters = detail.get("output_parameters", {})
        energy = parameters.get("energy_scf", parameters.get("energy"))
        if energy is None:
            raise ValueError("A replica-chain step has no electronic energy.")
        energies_hartree.append(
            _energy_in_hartree(
                {
                    "energy": energy,
                    "energy_units": parameters.get("energy_units", "a.u."),
                }
            )
        )
        actual_values.append(list(detail.get("cvs_actual", [])))

    structures = _ordered_namespace_nodes(
        _get_optional_output(workchain.outputs, "structures"),
        prefixes=("initial_scf", "step_"),
    )
    if len(energies_hartree) < 2 or len(structures) < 2:
        raise ValueError("A replica chain requires at least two path images.")
    relative_energies = (
        np.asarray(energies_hartree, dtype=float) - energies_hartree[0]
    ) * Hartree
    return relative_energies, actual_values, structures[0], structures[-1]


def _neb_input_endpoints(workchain):
    """Return the structures defining the initial and final NEB endpoints."""
    restart_uuid = _input_value(workchain, "restart_from")
    if restart_uuid:
        previous = orm.load_node(str(restart_uuid))
        replicas = _ordered_namespace_nodes(
            previous.outputs, prefixes=("opt_replica_",)
        )
        if len(replicas) >= 2:
            return replicas[0], replicas[-1]

    replicas = _ordered_namespace_nodes(
        _get_optional_output(workchain.inputs, "replicas"),
        prefixes=("replica_",),
    )
    if not replicas:
        raise ValueError("The NEB workflow has no final input endpoint.")
    return workchain.inputs.structure, replicas[-1]


def _neb_profile(workchain):
    """Return the last complete NEB energy profile and reaction coordinates."""
    energies = np.asarray(
        workchain.outputs.replica_energies.get_array("energies"), dtype=float
    )
    if energies.ndim == 2:
        energies = energies[-1]
    if energies.ndim != 1 or len(energies) < 2:
        raise ValueError("The NEB result has no complete energy profile.")
    relative_energies = (energies - energies[0]) * Hartree

    coordinates = None
    distances_node = _get_optional_output(workchain.outputs, "replica_distances")
    if distances_node is not None:
        distances = np.asarray(distances_node.get_array("distances"), dtype=float)
        if distances.ndim == 2:
            distances = distances[-1]
        if distances.ndim == 1 and len(distances) == len(energies):
            coordinates = np.cumsum(distances) * Bohr
    return relative_energies, coordinates


def _collective_variables_description(system_parameters, actual_values=None):
    definition = str(system_parameters.get("colvars", "") or "").strip()
    targets = system_parameters.get("colvars_targets")
    increments = system_parameters.get("colvars_increments")
    if not definition and targets is None and increments is None and not actual_values:
        return ""
    content = {}
    if definition:
        content["definitions"] = definition
    if targets is not None:
        content["targets"] = list(targets)
    if increments is not None:
        content["increments"] = list(increments)
    if actual_values:
        content["actual_values"] = actual_values
    return json.dumps(content, indent=2)


def _cp2k_mep_property_definition(workchain, aiida_node_id=None, executable_ids=None):
    """Build MINIMUM_ENERGY_PATH properties for CP2K path workflows."""
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.code.description,
        _node_mapping(workchain.inputs.dft_params),
    )
    system_parameters = _node_mapping(workchain.inputs.sys_params)
    properties = _simulation_properties(
        workchain,
        "Minimum energy path",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
        result_role="minimum_energy_path",
    )

    if workchain.process_label == "Cp2kReplicaWorkChain":
        energies, actual_values, _start, _end = _replica_chain_profile(workchain)
        properties["mep_method"] = "REPLICA_CHAIN"
        collective_variables = _collective_variables_description(
            system_parameters, actual_values
        )
        if collective_variables:
            properties["collective_variables"] = collective_variables
            properties["reaction_coordinate_description"] = str(
                system_parameters.get("colvars", "")
            ).strip()
    elif workchain.process_label == "Cp2kNebWorkChain":
        energies, _coordinates = _neb_profile(workchain)
        properties["mep_method"] = "NEB"
        band_type = str(
            _node_mapping(workchain.inputs.neb_params).get("band_type", "NEB")
        )
        normalized = re.sub(r"[^A-Z0-9]+", "_", band_type.upper()).strip("_")
        properties["neb_variant"] = "CI_NEB" if normalized == "CI_NEB" else "NEB"
        collective_variables = _collective_variables_description(system_parameters)
        if collective_variables:
            properties["collective_variables"] = collective_variables
    else:
        raise ValueError(
            f"Unsupported minimum-energy-path workflow: {workchain.process_label}"
        )

    maximum = float(np.max(energies))
    properties.update(
        {
            "relative_energies_ev": [float(value) for value in energies],
            "forward_barrier_ev": maximum - float(energies[0]),
            "backward_barrier_ev": maximum - float(energies[-1]),
            "number_of_images": len(energies),
            # Some accepted CP2K NEB runs currently terminate externally after
            # writing a usable final profile. Preserve the WorkChain decision.
            "converged": bool(getattr(workchain, "is_finished_ok", True)),
        }
    )
    constraints = str(system_parameters.get("constraints", "") or "").strip()
    if constraints:
        properties["constraints_description"] = constraints
    return {
        "minimum_energy_path": {
            "object_type": OPENBIS_SIMULATION_TYPES["Minimum Energy Path"],
            "properties": properties,
        }
    }


def _attach_parent(openbis_object, parent):
    openbis_object.add_parents(parent)
    utils.update_openbis_object(openbis_object)


def _resample_preview_content(
    content, filename="preview.png", max_side=PREVIEW_MAX_SIDE_PX
):
    """Return proportionally resampled image bytes and their display metadata."""
    from PIL import Image, UnidentifiedImageError

    content = bytes(content)
    suffix = Path(filename).suffix.lower()
    output_format = "JPEG" if suffix in {".jpg", ".jpeg"} else "PNG"
    try:
        with Image.open(io.BytesIO(content)) as opened:
            image = opened.copy()
    except (OSError, UnidentifiedImageError):
        # Unit-test doubles and legacy callers may provide opaque bytes. The
        # openBIS upload path retains them, while real UI uploads are images.
        return content, output_format.lower(), None

    max_side = int(max_side)
    if max_side <= 0:
        raise ValueError("Preview maximum side must be positive.")
    if max(image.size) > max_side:
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image.thumbnail((max_side, max_side), resampling)
    if output_format == "JPEG" and image.mode not in {"L", "RGB"}:
        image = image.convert("RGB")

    output = io.BytesIO()
    image.save(output, format=output_format, optimize=True)
    return output.getvalue(), output_format.lower(), image.size


def _resample_preview_path(path, max_side=PREVIEW_MAX_SIDE_PX):
    content, _format, size = _resample_preview_content(
        path.read_bytes(), path.name, max_side=max_side
    )
    path.write_bytes(content)
    return size


def _upload_preview(openbis_session, openbis_object, renderer, stem):
    with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-preview-") as dirname:
        path = Path(dirname) / f"{stem}.png"
        renderer(path)
        if not path.is_file():
            raise RuntimeError(f"Preview renderer did not create {path.name}.")
        _resample_preview_path(path)
        utils.create_openbis_dataset(
            openbis_session,
            type="ELN_PREVIEW",
            sample=openbis_object,
            files=[path],
        )


def _upload_preview_content(
    openbis_session, openbis_object, renderer, stem, preview_override=None
):
    """Upload either the generated suggestion or a user-selected replacement."""
    if preview_override is None:
        _upload_preview(openbis_session, openbis_object, renderer, stem)
        return

    filename = str(preview_override.get("name", "preview.png"))
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png"}:
        suffix = ".png"
    with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-preview-") as dirname:
        path = Path(dirname) / f"{stem}{suffix}"
        path.write_bytes(bytes(preview_override["content"]))
        _resample_preview_path(path)
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


def _cached_preview_renderer(renderer):
    """Reuse one rendered image for result objects that share a preview."""
    content = []

    def render(path):
        if not content:
            renderer(path)
            content.append(path.read_bytes())
        else:
            path.write_bytes(content[0])

    return render


def _render_simple_bands_dos_preview(
    bands_node, dos_node, path, fermi_energy=None, title=None
):
    """Render a dependency-free combined bands/DOS fallback preview."""
    from matplotlib.figure import Figure

    bands = np.asarray(bands_node.get_bands(), dtype=float)
    if bands.ndim == 2:
        bands = bands[np.newaxis, ...]
    if bands.ndim != 3:
        raise ValueError(f"Unsupported band array shape: {bands.shape}.")

    figure = Figure(figsize=(9, 5.5), constrained_layout=True)
    grid = figure.add_gridspec(1, 2, width_ratios=(0.7, 0.3))
    bands_axis = figure.add_subplot(grid[0, 0])
    dos_axis = figure.add_subplot(grid[0, 1], sharey=bands_axis)
    for spin_bands in bands:
        bands_axis.plot(
            np.arange(spin_bands.shape[0]), spin_bands, color="black", lw=0.8
        )
    if fermi_energy is not None:
        bands_axis.axhline(float(fermi_energy), color="gray", ls="--", lw=0.9)
    bands_axis.set_xlabel("k-point index")
    bands_axis.set_ylabel(f"Energy ({getattr(bands_node, 'units', 'eV')})")
    bands_axis.set_title(title or "Electronic bands and density of states")

    x_name, x_values, x_unit = dos_node.get_x()
    curves = dos_node.get_y()
    for curve_name, values, _unit in curves:
        dos_axis.plot(np.asarray(values), np.asarray(x_values), label=curve_name)
    dos_axis.set_xlabel("Density of states")
    dos_axis.set_ylabel(f"{x_name} ({x_unit})")
    dos_axis.tick_params(labelleft=False)
    if len(curves) > 1:
        dos_axis.legend(fontsize="x-small")
    figure.savefig(path, dpi=180)


def _matplotlib_trace_color(value, default):
    """Convert common Plotly color strings into Matplotlib-compatible colors."""
    if value in (None, ""):
        return default
    value = str(value)
    match = re.fullmatch(
        r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
        r"(?:\s*,\s*([\d.]+))?\s*\)",
        value,
    )
    if match is None:
        return value
    red, green, blue = (float(component) / 255.0 for component in match.groups()[:3])
    alpha = float(match.group(4)) if match.group(4) is not None else 1.0
    return red, green, blue, alpha


def _numeric_plot_values(values):
    """Return Plotly values as floats while preserving trace breaks."""
    return np.asarray(
        [np.nan if value is None else float(value) for value in values], dtype=float
    )


def _plain_axis_title(axis, fallback):
    """Return a plain-text title from a Plotly axis description."""
    try:
        title = axis.title.text
    except AttributeError:
        title = None
    if not title:
        return fallback
    return re.sub(r"<[^>]+>", "", str(title)).replace("−", "-")


def _draw_plotly_bands_pdos(plot, bands_axis, dos_axis, title):
    """Draw the data and defaults from a QE Results Plotly figure in Matplotlib."""
    bands_traces = [trace for trace in plot.data if trace.xaxis != "x2"]
    dos_traces = [trace for trace in plot.data if trace.xaxis == "x2"]
    for index, trace in enumerate(bands_traces):
        bands_axis.plot(
            _numeric_plot_values(trace.x),
            _numeric_plot_values(trace.y),
            color=_matplotlib_trace_color(trace.line.color, f"C{index}"),
            lw=float(trace.line.width or 1.0),
            label=str(trace.name or ""),
        )
    bands_axis.axhline(0.0, color="#555555", ls="--", lw=0.8)
    bands_axis.set_title(title)
    bands_axis.set_xlabel(_plain_axis_title(plot.layout.xaxis, "k-points"))
    bands_axis.set_ylabel(
        _plain_axis_title(plot.layout.yaxis, "Energy - Fermi energy (eV)")
    )
    tick_values = plot.layout.xaxis.tickvals
    tick_labels = plot.layout.xaxis.ticktext
    if tick_values is not None and tick_labels is not None:
        bands_axis.set_xticks(list(tick_values), list(tick_labels))
        for value in tick_values:
            bands_axis.axvline(float(value), color="#777777", lw=0.5)
    y_range = plot.layout.yaxis.range
    if y_range is not None:
        bands_axis.set_ylim(float(y_range[0]), float(y_range[1]))

    for index, trace in enumerate(dos_traces):
        x_values = _numeric_plot_values(trace.x)
        y_values = _numeric_plot_values(trace.y)
        color = _matplotlib_trace_color(trace.line.color, f"C{index}")
        dos_axis.plot(x_values, y_values, color=color, lw=1.0, label=trace.name)
        if trace.fill == "tozerox":
            dos_axis.fill_betweenx(y_values, 0.0, x_values, color=color, alpha=0.18)
    dos_axis.axhline(0.0, color="#555555", ls="--", lw=0.8)
    dos_axis.set_xlabel(_plain_axis_title(plot.layout.xaxis2, "Density of states"))
    dos_axis.tick_params(labelleft=False)
    if dos_traces:
        dos_axis.legend(fontsize="x-small", loc="best")


def _render_plotly_bands_pdos_preview(plot, path, title):
    """Render a QE Results bands/PDOS figure without requiring Chrome/Kaleido."""
    from matplotlib.figure import Figure

    has_dos = any(trace.xaxis == "x2" for trace in plot.data)
    if not has_dos:
        figure = Figure(figsize=(8, 5), constrained_layout=True)
        axis = figure.subplots()
        for index, trace in enumerate(plot.data):
            axis.plot(
                _numeric_plot_values(trace.x),
                _numeric_plot_values(trace.y),
                color=_matplotlib_trace_color(trace.line.color, f"C{index}"),
                label=trace.name,
            )
        axis.set_title(title)
        axis.set_xlabel(_plain_axis_title(plot.layout.xaxis, "Energy (eV)"))
        axis.set_ylabel(_plain_axis_title(plot.layout.yaxis, "Intensity"))
        if len(plot.data) > 1:
            axis.legend(fontsize="x-small")
        figure.savefig(path, dpi=180)
        return

    figure = Figure(figsize=(9, 5.5), constrained_layout=True)
    grid = figure.add_gridspec(1, 2, width_ratios=(0.7, 0.3))
    bands_axis = figure.add_subplot(grid[0, 0])
    dos_axis = figure.add_subplot(grid[0, 1], sharey=bands_axis)
    _draw_plotly_bands_pdos(plot, bands_axis, dos_axis, title)
    figure.savefig(path, dpi=180)


def _qe_app_root(workchain):
    """Return the enclosing QE app workchain, if this result has one."""
    current = workchain
    seen = set()
    while current is not None and str(current.uuid) not in seen:
        seen.add(str(current.uuid))
        if current.process_label == "QeAppWorkChain":
            return current
        current = getattr(current, "caller", None)
    return None


def _render_qe_electronic_preview(workchain, path):
    """Reuse the QE app Results plot for bands and (P)DOS previews."""
    try:
        from aiidalab_qe.common.bands_pdos.model import BandsPdosModel

        root = _qe_app_root(workchain)
        if root is not None:
            model = BandsPdosModel.from_nodes(root=root)
        elif workchain.process_label == "BandsWorkChain":
            model = BandsPdosModel.from_nodes(bands=workchain)
        else:
            model = BandsPdosModel.from_nodes(pdos=workchain)
        model.fetch_data()
        model.create_plot()
        _render_plotly_bands_pdos_preview(
            model.plot, path, "Electronic bands and density of states"
        )
        return
    except Exception:  # noqa: BLE001 - optional app integration has a safe fallback
        logger.warning(
            "Could not reuse the QE Results plot; using the generic preview.",
            exc_info=True,
        )

    if workchain.process_label == "BandsWorkChain":
        try:
            root_out = workchain.outputs.bands
        except NotExistentAttributeError:
            root_out = workchain.outputs.bands_projwfc
        output_parameters = _node_mapping(root_out.scf_parameters)
        dos_node = _bands_dos_node(root_out)
        if dos_node is not None:
            _render_simple_bands_dos_preview(
                root_out.band_structure,
                dos_node,
                path,
                output_parameters.get("fermi_energy"),
            )
        else:
            _render_bands_preview(
                root_out.band_structure,
                path,
                output_parameters.get("fermi_energy"),
            )
        return
    _render_xy_preview(
        workchain.outputs.projwfc.Dos, path, "Projected density of states"
    )


def _render_nanoribbon_bands_pdos_preview(workchain, path):
    """Reuse the nanoribbon viewer's default combined bands/PDOS figure."""
    try:
        from matplotlib import pyplot as plt
        from nanoribbon.viewers.pdos_computed import NanoribbonPDOSWidget

        viewer = NanoribbonPDOSWidget(workchain)
        figure = viewer.create_figure()
        figure.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(figure)
        return
    except Exception:  # noqa: BLE001 - optional app integration has a safe fallback
        logger.warning(
            "Could not reuse the nanoribbon Results plot; using the generic preview.",
            exc_info=True,
        )

    calculations = _find_nanoribbon_calculations(workchain)
    output_parameters = _node_mapping(calculations["scf"].outputs.output_parameters)
    dos_node = _get_optional_output(calculations["export_pdos"].outputs, "Dos")
    if dos_node is None:
        raise ValueError("The export_pdos calculation does not contain a Dos output.")
    _render_simple_bands_dos_preview(
        calculations["bands"].outputs.output_band,
        dos_node,
        path,
        output_parameters.get("fermi_energy"),
    )


def _vibroscopy_output_namespace(workchain):
    """Build the output mapping expected by the QE vibroscopy Results models."""
    from aiida.common.extendeddicts import AttributeDict

    return AttributeDict(
        {name: getattr(workchain.outputs, name) for name in workchain.outputs}
    )


def _render_qe_vibrational_preview(workchain, path):
    """Reuse the default QE phonon, IR, and Raman result data in one preview."""
    try:
        from matplotlib.figure import Figure
        from aiidalab_qe.common.bands_pdos.bandpdosplotly import BandsPdosPlotly
        from aiidalab_qe_vibroscopy.app.widgets.phononmodel import PhononModel
        from aiidalab_qe_vibroscopy.app.widgets.ramanmodel import RamanModel

        phonon_model = PhononModel(vibro=workchain)
        phonon_model.fetch_data()
        phonon_plot = BandsPdosPlotly(
            bands_data=phonon_model.bands_data,
            pdos_data=phonon_model.pdos_data,
        ).bandspdosfigure
        y_values = _numeric_plot_values(phonon_plot.data[0].y)
        phonon_plot.update_layout(
            xaxis={"title": "q-points"},
            yaxis={
                "title": "THz",
                "range": [
                    float(np.nanmin(y_values)) - 0.1,
                    float(np.nanmax(y_values)) + 0.1,
                ],
            },
        )

        output_namespace = _vibroscopy_output_namespace(workchain)
        input_structure = workchain.inputs.structure.get_ase()
        spectra = []
        for spectrum_type in ("IR", "Raman"):
            model = RamanModel(
                vibro=output_namespace,
                input_structure=input_structure,
                spectrum_type=spectrum_type,
            )
            model.fetch_data()
            if len(model.raw_frequencies) == 0:
                continue
            model.update_data()
            if len(model.frequencies) == 0:
                continue
            spectra.append(
                (
                    spectrum_type,
                    np.asarray(model.frequencies, dtype=float),
                    np.asarray(model.intensities, dtype=float),
                )
            )

        row_count = 1 + len(spectra)
        figure = Figure(figsize=(9, 5.5 + 2.6 * len(spectra)), constrained_layout=True)
        grid = figure.add_gridspec(
            row_count,
            2,
            width_ratios=(0.7, 0.3),
            height_ratios=(2.0,) + (1.0,) * len(spectra),
        )
        bands_axis = figure.add_subplot(grid[0, 0])
        dos_axis = figure.add_subplot(grid[0, 1], sharey=bands_axis)
        _draw_plotly_bands_pdos(
            phonon_plot,
            bands_axis,
            dos_axis,
            "Phonon bands and density of states",
        )
        for row, (spectrum_type, frequencies, intensities) in enumerate(
            spectra, start=1
        ):
            axis = figure.add_subplot(grid[row, :])
            axis.plot(frequencies, intensities, color="#1f77b4")
            axis.fill_between(
                frequencies, 0.0, intensities, color="#1f77b4", alpha=0.15
            )
            axis.set_title(f"Powder {spectrum_type} spectrum")
            axis.set_xlabel("Frequency (cm$^{-1}$)")
            axis.set_ylabel("Normalized intensity")
        figure.savefig(path, dpi=180)
        return
    except Exception:  # noqa: BLE001 - optional app integration has a safe fallback
        logger.warning(
            "Could not reuse the QE vibroscopy Results plots; using the generic preview.",
            exc_info=True,
        )

    _render_xy_preview(
        workchain.outputs.phonon_pdos,
        path,
        "Vibrational density of states",
    )


def _render_mep_preview(workchain, path):
    """Render the final minimum-energy path suggested for the ELN preview."""
    from matplotlib.figure import Figure

    if workchain.process_label == "Cp2kReplicaWorkChain":
        energies, actual_values, _start, _end = _replica_chain_profile(workchain)
        if actual_values and all(len(values) == 1 for values in actual_values):
            coordinates = np.asarray([values[0] for values in actual_values])
            x_label = "Collective variable"
        else:
            coordinates = np.arange(len(energies))
            x_label = "Path image"
    else:
        energies, coordinates = _neb_profile(workchain)
        if coordinates is None or not np.any(np.diff(coordinates)):
            coordinates = np.arange(len(energies))
            x_label = "Path image"
        else:
            x_label = "Cumulative path distance (angstrom)"

    figure = Figure(figsize=(7, 4.5), constrained_layout=True)
    axis = figure.subplots()
    axis.plot(coordinates, energies, "o-", color="#1f77b4")
    maximum_index = int(np.argmax(energies))
    axis.scatter(
        [coordinates[maximum_index]],
        [energies[maximum_index]],
        color="#d62728",
        zorder=3,
        label="Maximum",
    )
    axis.set_xlabel(x_label)
    axis.set_ylabel("Relative energy (eV)")
    axis.set_title("Minimum energy path")
    axis.legend()
    figure.savefig(path, dpi=160)


def _render_unfolding_preview(workchain, path):
    """Render either QE/BandUPpy or CP2K sparse-AO unfolding data."""
    from matplotlib.figure import Figure

    data = _unfolding_archive_data(workchain)
    figure = Figure(figsize=(7, 4.5), constrained_layout=True)
    axis = figure.subplots()
    plotted_energies = []

    if "unfolded_bandstructure" in data:
        bands = np.asarray(data["unfolded_bandstructure"], dtype=float)
        reference = float(np.asarray(data.get("fermi_energy", 0.0)).reshape(-1)[0])
        x_values = bands[:, 1]
        energies = bands[:, 2] - reference
        weights = np.maximum(bands[:, 3], 0.0)
        mask = weights > 1.0e-8
        axis.scatter(
            x_values[mask],
            energies[mask],
            s=80.0 * weights[mask],
            alpha=0.65,
            color="black",
        )
        plotted_energies.extend(energies[mask].tolist())
        raw_labels = data.get("special_labels")
        if isinstance(raw_labels, np.ndarray) and raw_labels.shape == ():
            raw_labels = raw_labels.item()
        if isinstance(raw_labels, bytes):
            raw_labels = raw_labels.decode()
        if isinstance(raw_labels, str):
            try:
                raw_labels = json.loads(raw_labels)
            except json.JSONDecodeError:
                raw_labels = None
        if isinstance(raw_labels, dict):
            kline = np.asarray(data.get("kline", []), dtype=float)
            labels = sorted(
                (int(index), str(label)) for index, label in raw_labels.items()
            )
            labels = [item for item in labels if item[0] < len(kline)]
            x_ticks = np.asarray([kline[index] for index, _label in labels])
            x_labels = [label for _index, label in labels]
        else:
            x_ticks = np.asarray([np.min(x_values), np.max(x_values)])
            x_labels = ["", ""]
        ylabel = "Energy - Fermi level (eV)"
    else:
        path_indices = np.asarray(data["path_k_indices"], dtype=int)
        path_x = np.asarray(data["path_x"], dtype=float)
        reference = float(np.asarray(data["ref_energy_ev"]).reshape(-1)[0])
        spin_indices = sorted(
            int(key.rsplit("_", 1)[-1])
            for key in data
            if key.startswith("weights_spin_")
        )
        if not spin_indices:
            raise ValueError("The unfolding archive contains no spectral weights.")
        for spin in spin_indices:
            energies = (
                np.asarray(data[f"evals_ev_spin_{spin}"], dtype=float) - reference
            )
            weights = np.asarray(data[f"weights_spin_{spin}"], dtype=float)
            for k_index, x_value in zip(path_indices, path_x):
                sizes = 150.0 * np.maximum(weights[k_index], 0.0)
                mask = sizes > 1.0e-8
                axis.scatter(
                    np.full(np.count_nonzero(mask), x_value),
                    energies[mask],
                    s=sizes[mask],
                    alpha=0.65,
                    color="black",
                )
                plotted_energies.extend(energies[mask].tolist())
        x_ticks = np.asarray(data["x_ticks"], dtype=float)
        x_labels = [str(label) for label in data["x_tick_labels"]]
        ylabel = "Energy - reference (eV)"

    for x_tick in x_ticks:
        axis.axvline(x_tick, linewidth=0.8, alpha=0.35)
    axis.axhline(0.0, linestyle="--", linewidth=1.0)
    axis.set_xticks(x_ticks)
    axis.set_xticklabels(x_labels)
    if len(x_ticks) > 1:
        axis.set_xlim(x_ticks[0], x_ticks[-1])
    if plotted_energies:
        low, high = np.percentile(plotted_energies, [2.0, 98.0])
        low = max(float(low), -15.0)
        high = min(float(high), 15.0)
        if low < high:
            axis.set_ylim(low, high)
    axis.set_xlabel("Primitive-cell k-path")
    axis.set_ylabel(ylabel)
    axis.set_title("Unfolded band structure")
    figure.savefig(path, dpi=160)


def _retrieved_npz_data(workchain, filename):
    """Load one small metadata/result NPZ from a workflow descendant."""
    for node in (workchain, *tuple(workchain.called_descendants)):
        retrieved = _get_optional_output(getattr(node, "outputs", {}), "retrieved")
        if retrieved is None:
            continue
        repository = retrieved.base.repository
        try:
            names = repository.list_object_names()
        except (AttributeError, OSError):
            continue
        if filename not in names:
            continue
        with (
            repository.open(filename, mode="rb") as handle,
            np.load(handle, allow_pickle=True) as archive,
        ):
            return {name: archive[name] for name in archive.files}
    raise ValueError(
        f"The {workchain.process_label} workflow does not contain a retrieved "
        f"{filename} file."
    )


def _dictionary_array(values):
    """Convert an object array containing dictionaries into plain dictionaries."""
    result = []
    for value in values:
        if isinstance(value, np.ndarray) and value.shape == ():
            value = value.item()
        elif hasattr(value, "item"):
            try:
                value = value.item()
            except ValueError:
                pass
        if isinstance(value, dict):
            result.append(value)
    return result


def _sorted_unique_numbers(values):
    numbers = []
    for value in values:
        number = round(float(value), 12)
        numbers.append(0.0 if abs(number) < 1.0e-12 else number)
    return sorted(set(numbers))


def _spm_area_from_cell_vectors(general_info):
    """Return the in-plane area; cp2k-spm-tools stores vectors in Bohr."""
    vectors = np.asarray(general_info.get("cell_vectors", []), dtype=float)
    if vectors.shape != (3, 3):
        return None
    return float(np.linalg.norm(np.cross(vectors[0], vectors[1])) * Bohr**2)


def _stm_archive_metadata(workchain):
    data = _retrieved_npz_data(workchain, "stm.npz")
    general_info = data["stm_general_info"].item()
    series = _dictionary_array(data["stm_series_info"])
    return general_info, series, data["stm_series_data"]


def _orbital_archive_metadata(workchain):
    data = _retrieved_npz_data(workchain, "orb.npz")
    blocks = []
    for key in sorted(data):
        if not key.endswith("_orb_general_info"):
            continue
        prefix = key[: -len("_general_info")]
        blocks.append(
            (
                data[key].item(),
                _dictionary_array(data[f"{prefix}_series_info"]),
                data[f"{prefix}_series_data"],
            )
        )
    if not blocks:
        raise ValueError("The orbital archive contains no orbital metadata blocks.")
    return blocks


def _tip_model_summary(p_tip_ratios):
    """Describe each s/p tip mixture using the stored p-orbital fraction."""
    descriptions = []
    for ratio in p_tip_ratios:
        p_percent = 100.0 * float(ratio)
        s_percent = 100.0 - p_percent

        def percentage(value):
            return f"{value:.12g}"

        if np.isclose(p_percent, 0.0):
            descriptions.append("100% s")
        elif np.isclose(p_percent, 100.0):
            descriptions.append("100% p")
        else:
            descriptions.append(
                f"{percentage(s_percent)}% s + {percentage(p_percent)}% p"
            )
    return "; ".join(descriptions)


def _series_summary(general_infos, series, include_bias_voltages):
    types = [str(item.get("type", "")).lower() for item in series]
    modes = set()
    if any("orbital" in value for value in types):
        modes.add("ORBITALS")
    if any(value.endswith("stm") for value in types):
        modes.add("STM")
    if any(value.endswith("sts") for value in types):
        modes.add("STS")

    image_modes = set()
    if any("const-height" in value for value in types):
        image_modes.add("CONSTANT_HEIGHT")
    if any("const-isovalue" in value for value in types):
        image_modes.add("CONSTANT_ISOVALUE")

    properties = {
        "spm_mode": sorted(modes),
        "image_modes": sorted(image_modes),
    }
    heights = _sorted_unique_numbers(
        item["height"] for item in series if item.get("height") is not None
    )
    isovalues = _sorted_unique_numbers(
        item["isovalue"] for item in series if item.get("isovalue") is not None
    )
    p_tip_ratios = _sorted_unique_numbers(
        item["p_tip_ratio"] for item in series if item.get("p_tip_ratio") is not None
    )
    if heights:
        properties["heights_angstrom"] = heights
    if isovalues:
        properties["isovalues_au"] = isovalues
    if p_tip_ratios:
        properties["p_tip_ratios"] = p_tip_ratios
        properties["tip_model"] = _tip_model_summary(p_tip_ratios)

    first_info = general_infos[0]
    area = _spm_area_from_cell_vectors(first_info)
    if area is not None:
        properties["scan_area_angstrom2"] = area
    if include_bias_voltages:
        energies = []
        for info in general_infos:
            energies.extend(np.asarray(info.get("energies", []), dtype=float).ravel())
        if energies:
            properties["bias_voltages_v"] = _sorted_unique_numbers(energies)
    return properties


def _cp2k_spm_result_metadata(workchain):
    """Derive searchable SPM summaries without duplicating NPZ arrays."""
    if workchain.process_label == "Cp2kStmWorkChain":
        general_info, series, _series_data = _stm_archive_metadata(workchain)
        return _series_summary([general_info], series, include_bias_voltages=True)

    if workchain.process_label == "Cp2kOrbitalsWorkChain":
        blocks = _orbital_archive_metadata(workchain)
        general_infos = [block[0] for block in blocks]
        series = [item for block in blocks for item in block[1]]
        properties = _series_summary(general_infos, series, include_bias_voltages=False)
        orbital_energies = []
        for info in general_infos:
            orbital_energies.extend(
                np.asarray(info.get("energies", []), dtype=float).ravel()
            )
        if orbital_energies:
            properties["orbital_energies_ev"] = _sorted_unique_numbers(orbital_energies)
        return properties

    if workchain.process_label == "Cp2kAfmWorkChain":
        parameters = _node_mapping(workchain.inputs.ppafm_params)
        grid_a = np.asarray(parameters.get("gridA", []), dtype=float)
        grid_b = np.asarray(parameters.get("gridB", []), dtype=float)
        properties = {
            "spm_mode": ["AFM"],
            "image_modes": ["THREE_DIMENSIONAL_GRID"],
        }
        if grid_a.shape == (3,) and grid_b.shape == (3,):
            properties["scan_area_angstrom2"] = float(
                np.linalg.norm(np.cross(grid_a, grid_b))
            )
        optional = {
            "afm_amplitude_angstrom": parameters.get("Amplitude"),
            "afm_probe_type": parameters.get("probeType"),
            "afm_tip_charge_e": parameters.get("charge"),
        }
        properties.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        scan_min = parameters.get("scanMin")
        scan_max = parameters.get("scanMax")
        scan_step = parameters.get("scanStep")
        if scan_min is not None and len(scan_min) >= 3:
            properties["afm_scan_z_min_angstrom"] = float(scan_min[2])
        if scan_max is not None and len(scan_max) >= 3:
            properties["afm_scan_z_max_angstrom"] = float(scan_max[2])
        if scan_step is not None and len(scan_step) >= 3:
            properties["afm_scan_z_step_angstrom"] = float(scan_step[2])
        tip = str(parameters.get("tip", "")).strip()
        probe = str(parameters.get("probeType", "")).strip()
        details = ["Probe-particle AFM"]
        if tip:
            details.append(f"{tip} tip")
        if probe:
            details.append(f"{probe} probe")
        properties["tip_model"] = "; ".join(details)
        return properties

    raise ValueError(f"Unsupported SPM workflow: {workchain.process_label}")


def _cp2k_spm_property_definition(workchain, aiida_node_id=None, executable_ids=None):
    inputs = workchain.inputs
    cp2k_code = getattr(inputs, "cp2k_code", None)
    if cp2k_code is None:
        cp2k_code = inputs.spm_code
    dft_parameters = get_dft_parameters_cp2k(
        cp2k_code.description, _node_mapping(inputs.dft_params)
    )
    prefix = {
        "Cp2kStmWorkChain": "SPM",
        "Cp2kOrbitalsWorkChain": "SPM orbitals",
        "Cp2kAfmWorkChain": "AFM",
    }[workchain.process_label]
    properties = _simulation_properties(
        workchain,
        prefix,
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
        result_role="spm",
    )
    properties.update(_cp2k_spm_result_metadata(workchain))
    return {
        "spm": {
            "object_type": OPENBIS_SIMULATION_TYPES["SPM Simulation"],
            "properties": properties,
        }
    }


def _nearest_available_index(values, target, require_in_range=False):
    """Return the index nearest a target, optionally only inside the data range."""
    values = np.asarray(values, dtype=float).ravel()
    if values.size == 0:
        return None
    if require_in_range and not float(np.min(values)) <= target <= float(
        np.max(values)
    ):
        return None
    return int(np.argmin(np.abs(values - target)))


def _spm_series_details(info):
    details = []
    if info.get("height") is not None:
        details.append(f"height {float(info['height']):.2f} Å")
    if info.get("isovalue") is not None:
        details.append(f"isovalue {float(info['isovalue']):.2g} a.u.")
    if info.get("p_tip_ratio") is not None:
        details.append(_tip_model_summary([info["p_tip_ratio"]]))
    return ", ".join(details)


def _highest_contrast_image(candidates):
    def contrast(candidate):
        finite = np.asarray(candidate[0])[np.isfinite(candidate[0])]
        return float(np.ptp(finite)) if finite.size else -1.0

    return max(candidates, key=contrast)


def _spm_preview_panels(workchain):
    """Select scientifically recognizable panels from one SPM result archive."""
    if workchain.process_label == "Cp2kAfmWorkChain":
        archive = _retrieved_npz_data(workchain, "df.npz")
        grid = np.asarray(archive["data"], dtype=float)
        planes = grid.reshape((-1,) + grid.shape[-2:])
        parameters = _node_mapping(workchain.inputs.ppafm_params)
        scan_min = parameters.get("scanMin", [0.0, 0.0, 0.0])
        scan_max = parameters.get(
            "scanMax", [float(planes.shape[-1]), float(planes.shape[-2]), 0.0]
        )
        step = parameters.get("scanStep", [0.0, 0.0, 1.0])
        amplitude = float(parameters.get("Amplitude", 0.0))
        first_tip_z = float(scan_min[2]) + amplitude / 2.0
        tip_z = first_tip_z + np.arange(len(planes)) * float(step[2])
        index = _nearest_available_index(tip_z, 15.0)
        return [
            {
                "image": planes[index],
                "title": f"Probe-particle AFM, tip z = {tip_z[index]:.2f} Å",
                "extent": [scan_min[0], scan_max[0], scan_min[1], scan_max[1]],
                "cmap": "gray",
                "center_zero": False,
                "general_info": None,
            }
        ]

    if workchain.process_label == "Cp2kOrbitalsWorkChain":
        panels = []
        for general_info, series_info, series_data in _orbital_archive_metadata(
            workchain
        ):
            energies = np.asarray(general_info.get("energies", []), dtype=float)
            orbital_indexes = np.asarray(general_info.get("orb_indexes", []), dtype=int)
            homo = general_info.get("homo")
            if homo is None:
                continue
            spin = int(general_info.get("spin", 0))
            spin_label = "alpha" if spin == 0 else "beta"
            for frontier_label, frontier_index in (
                ("HOMO", int(homo)),
                ("LUMO", int(homo) + 1),
            ):
                positions = np.flatnonzero(orbital_indexes == frontier_index)
                if not len(positions):
                    continue
                energy_index = int(positions[0])
                candidates = []
                for series_index, info in enumerate(series_info):
                    series_type = str(info.get("type", "")).lower()
                    if series_type != "const-height orbital":
                        continue
                    data = np.asarray(series_data[series_index], dtype=float)
                    if energy_index < data.shape[0]:
                        candidates.append((data[energy_index], info))
                if not candidates:
                    continue
                image, info = _highest_contrast_image(candidates)
                details = _spm_series_details(info)
                title = f"{spin_label} {frontier_label}, E = {energies[energy_index]:.2f} eV"
                if details:
                    title += f"; {details}"
                panels.append(
                    {
                        "image": image,
                        "title": title,
                        "extent": None,
                        "cmap": "seismic",
                        "center_zero": True,
                        "general_info": general_info,
                    }
                )
        if panels:
            return panels
        raise ValueError("The orbital archive contains no explicit HOMO/LUMO maps.")

    general_info, series_info, series_data = _stm_archive_metadata(workchain)
    energies = np.asarray(general_info.get("energies", []), dtype=float)
    panels = []
    selected = set()
    for target in (-0.5, 0.5):
        energy_index = _nearest_available_index(energies, target, require_in_range=True)
        if energy_index is None:
            continue
        candidates = []
        for series_index, info in enumerate(series_info):
            if not str(info.get("type", "")).lower().endswith("stm"):
                continue
            data = np.asarray(series_data[series_index], dtype=float)
            if energy_index < data.shape[0]:
                candidates.append((data[energy_index], info, series_index))
        if not candidates:
            continue
        image, info, series_index = _highest_contrast_image(candidates)
        identity = (series_index, energy_index)
        if identity in selected:
            continue
        selected.add(identity)
        details = _spm_series_details(info)
        title = f"STM at {energies[energy_index]:+.2f} V"
        if details:
            title += f"; {details}"
        panels.append(
            {
                "image": image,
                "title": title,
                "extent": None,
                # This is the yellow heat-map option exposed by the surfaces app.
                "cmap": "gist_heat",
                "center_zero": False,
                "general_info": general_info,
            }
        )
    if panels:
        return panels
    raise ValueError("The STM archive has no map near the requested biases.")


def _render_spm_preview(workchain, path):
    from matplotlib.figure import Figure

    panels = _spm_preview_panels(workchain)
    columns = min(2, len(panels))
    rows = int(np.ceil(len(panels) / columns))
    figure = Figure(
        figsize=(5.2 * columns, 4.4 * rows),
        constrained_layout=True,
    )
    axes = np.atleast_1d(figure.subplots(rows, columns)).ravel()

    for axis, panel in zip(axes, panels):
        image = np.asarray(panel["image"], dtype=float)
        finite = image[np.isfinite(image)]
        if not finite.size or np.ptp(finite) <= 0.0:
            axis.axis("off")
            axis.text(0.5, 0.5, "No finite image contrast", ha="center", va="center")
            continue

        general_info = panel["general_info"]
        if general_info is not None:
            try:
                # Reuse the surfaces viewer geometry handling so skewed cells are
                # plotted in physical coordinates rather than as square arrays.
                from surfaces_tools.widgets.series_plotter import (
                    _grid_geometry,
                    make_plot,
                )

                extent, _ratio, geometry = _grid_geometry(general_info, image.shape)
                make_plot(
                    figure,
                    axis,
                    image,
                    extent,
                    grid_geometry=geometry,
                    title=panel["title"],
                    center0=panel["center_zero"],
                    cmap=panel["cmap"],
                )
                continue
            except Exception:
                logger.warning(
                    "Could not reuse the surfaces SPM geometry renderer.",
                    exc_info=True,
                )

        limits = None
        if panel["center_zero"]:
            maximum = float(np.max(np.abs(finite)))
            limits = (-maximum, maximum)
        plotted = axis.imshow(
            image,
            origin="lower",
            interpolation="bicubic",
            extent=panel["extent"],
            cmap=panel["cmap"],
            vmin=limits[0] if limits else None,
            vmax=limits[1] if limits else None,
        )
        axis.set_xlabel("x (Å)")
        axis.set_ylabel("y (Å)")
        axis.set_title(panel["title"])
        axis.axis("scaled")
        figure.colorbar(plotted, ax=axis)

    for axis in axes[len(panels) :]:
        axis.remove()
    figure.savefig(path, dpi=160, bbox_inches="tight")


def _preview_override(preview_overrides, workchain, result_role):
    if not preview_overrides:
        return None
    return preview_overrides.get(f"{workchain.uuid}:{result_role}")


def _apply_property_overrides(properties, property_overrides, workchain, result_role):
    """Apply reviewed user values without allowing provenance fields to change."""
    if not property_overrides:
        return properties
    reviewed = property_overrides.get(f"{workchain.uuid}:{result_role}", {})
    protected = {
        "aiida_node",
        "aiida_source_uuid",
        "_aiidalab_result_role",
        "executables",
    }
    properties = dict(properties)
    for code, value in reviewed.items():
        code = str(code).lower()
        if code in protected:
            continue
        if value is None:
            properties.pop(code, None)
        else:
            properties[code] = value
    return properties


def _mark_export_result(
    openbis_object,
    created,
    source_uuid=None,
    result_role=None,
):
    # pyBIS entities treat normal attribute assignment as a server-attribute
    # update and reject private names. Bypassing pyBIS __setattr__ stores this
    # transient UI marker only on the local Python object.
    object.__setattr__(openbis_object, "_aiidalab_created", bool(created))
    if source_uuid:
        object.__setattr__(openbis_object, "_aiidalab_source_uuid", str(source_uuid))
    if result_role:
        object.__setattr__(openbis_object, "_aiidalab_result_role", str(result_role))
    return openbis_object


def _collection_space_code(openbis_session, collection_id):
    # Accept either the collection identifier used by the API or its UI permID.
    collection_id = str(collection_id)
    if collection_id.startswith("/"):
        return collection_id.strip("/").split("/", 1)[0]

    collection = openbis_session.get_collection(collection_id)
    space = getattr(getattr(collection, "project", None), "space", None)
    space_code = getattr(space, "code", None)
    if space_code:
        return str(space_code)

    identifier = str(getattr(collection, "identifier", "") or "")
    if identifier.startswith("/"):
        return identifier.strip("/").split("/", 1)[0]
    raise ValueError(f"Could not determine the openBIS space for {collection_id}.")


def find_existing_simulation_result(
    openbis_session,
    experiment_id,
    object_type,
    source_uuid,
):
    """Return an existing result with the same identity in the target space."""
    if not source_uuid or experiment_id in (None, "", "-1"):
        return None
    target_space = _collection_space_code(openbis_session, experiment_id)
    existing = list(
        openbis_session.get_objects(
            type=object_type,
            space=target_space,
            where={"AIIDA_SOURCE_UUID": str(source_uuid)},
        )
        or []
    )
    return existing[0] if existing else None


def _create_simulation_object(
    openbis_session,
    experiment_id,
    object_type,
    properties,
    parents,
    renderer,
    preview_stem,
    preview_override=None,
):
    properties = dict(properties)
    result_role = properties.pop("_aiidalab_result_role", None)
    source_uuid = properties.get("aiida_source_uuid")
    existing = find_existing_simulation_result(
        openbis_session,
        experiment_id,
        object_type,
        source_uuid,
    )
    if existing is not None:
        return _mark_export_result(
            existing,
            created=False,
            source_uuid=source_uuid,
            result_role=result_role,
        )

    openbis_object = utils.create_openbis_object(
        openbis_session,
        type=object_type,
        props=properties,
        collection=experiment_id,
        parents=parents,
    )
    _mark_export_result(
        openbis_object,
        created=True,
        source_uuid=source_uuid,
        result_role=result_role,
    )
    _upload_preview_content(
        openbis_session,
        openbis_object,
        renderer,
        preview_stem,
        preview_override=preview_override,
    )
    return openbis_object


def _qe_dft_from_calculation(calculation):
    outputs = _node_mapping(calculation.outputs.output_parameters)
    system = _node_mapping(calculation.inputs.parameters).get("SYSTEM", {})
    return {
        "xc_functional": outputs.get("dft_exchange_correlation", "unknown"),
        "plus_u": bool(outputs.get("lda_plus_u_calculation", False)),
        "spin_orbit_coupling": bool(outputs.get("spin_orbit_calculation", False)),
        "non_collinear": bool(outputs.get("non_colinear_calculation", False)),
        "uks": bool(outputs.get("lsda", False)),
        "charge": float(system.get("tot_charge", 0.0)),
        "vdw_corr": system.get("vdw_corr", ""),
    }


def _bands_dos_node(root_output):
    """Return an optional projwfc DOS from combined or bands-only workflows."""
    projwfc = _get_optional_output(root_output, "projwfc")
    return _get_optional_output(projwfc, "Dos")


def _band_and_dos_properties(
    workchain,
    dft_parameters,
    output_parameters,
    bands_node,
    aiida_node_id,
    executable_ids,
    projection_description,
):
    """Build the shared BAND_STRUCTURE and DOS property dictionaries."""
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
    band_properties["band_gap_ev"] = float(0.0 if gap is None else gap)

    dos_properties = _simulation_properties(
        workchain,
        "PDOS",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    dos_properties.update(
        {"pdos": True, "projection_description": projection_description}
    )
    fermi = _fermi_energy(output_parameters)
    if fermi is not None:
        band_properties["fermi_energy_ev"] = fermi
        dos_properties["fermi_energy_ev"] = fermi
    magnetization = _magnetization_properties(output_parameters)
    band_properties.update(magnetization)
    dos_properties.update(magnetization)
    return band_properties, dos_properties


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
    preview_overrides=None,
    property_overrides=None,
    preview_renderer=None,
):
    shared_preview_renderer = (
        _cached_preview_renderer(preview_renderer)
        if preview_renderer is not None
        else None
    )
    band_properties, dos_properties = _band_and_dos_properties(
        workchain,
        dft_parameters,
        output_parameters,
        bands_node,
        aiida_node_id,
        executable_ids,
        "Orbital-projected density of states generated from the AiiDA workflow. "
        "Full arrays are stored in the linked AiiDA archive.",
    )

    band_properties = _apply_property_overrides(
        band_properties, property_overrides, workchain, "bands"
    )
    bands_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Band Structure"],
        band_properties,
        [structure_object],
        shared_preview_renderer
        or (
            lambda path: _render_bands_preview(
                bands_node, path, output_parameters.get("fermi_energy")
            )
        ),
        "band_structure",
        preview_override=_preview_override(preview_overrides, workchain, "bands"),
    )

    if dos_node is None:
        return (bands_object,)

    dos_properties = _apply_property_overrides(
        dos_properties, property_overrides, workchain, "pdos"
    )
    dos_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["DOS"],
        dos_properties,
        [structure_object],
        shared_preview_renderer
        or (
            lambda path: _render_xy_preview(
                dos_node, path, "Projected density of states"
            )
        ),
        "pdos",
        preview_override=_preview_override(preview_overrides, workchain, "pdos"),
    )
    return bands_object, dos_object


def NanoribbonWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
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

    output_parameters = _node_mapping(scf.outputs.output_parameters)
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
        preview_overrides=preview_overrides,
        property_overrides=property_overrides,
        preview_renderer=lambda path: _render_nanoribbon_bands_pdos_preview(
            workchain, path
        ),
    )

    geometry_object = None
    if cell_opt is not None:
        cell_output = _node_mapping(cell_opt.outputs.output_parameters)
        properties = _simulation_properties(
            workchain,
            "Geometry optimization",
            dft_parameters,
            aiida_node_id,
            executable_ids=executable_ids,
        )
        properties.update(
            {
                "constrained": False,
                "cell_optimization": True,
                "final_energy_hartree": _energy_in_hartree(cell_output),
            }
        )
        properties.update(_magnetization_properties(cell_output))
        cell_dofree = (
            _node_mapping(cell_opt.inputs.parameters).get("CELL", {}).get("cell_dofree")
        )
        if cell_dofree:
            properties["cell_constraints"] = str(cell_dofree)
        properties = _apply_property_overrides(
            properties, property_overrides, workchain, "geometry_optimization"
        )
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
            preview_override=_preview_override(
                preview_overrides, workchain, "geometry_optimization"
            ),
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
    preview_overrides=None,
    property_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    properties = _qe_relax_properties(
        workchain, aiida_node_id, executable_ids=executable_ids
    )

    properties = _apply_property_overrides(
        properties, property_overrides, workchain, "geometry_optimization"
    )
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
        preview_override=_preview_override(
            preview_overrides, workchain, "geometry_optimization"
        ),
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
    preview_overrides=None,
    property_overrides=None,
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

    output_parameters = _node_mapping(root_out.scf_parameters)
    dft_parameters = get_dft_parameters_qe(root_in.bands, output_parameters)
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    dos_node = _bands_dos_node(root_out)
    return _create_band_and_dos_objects(
        openbis_session,
        experiment_id,
        workchain,
        dft_parameters,
        output_parameters,
        root_out.band_structure,
        dos_node,
        structure_object,
        aiida_node_id,
        executable_ids,
        preview_overrides=preview_overrides,
        property_overrides=property_overrides,
        preview_renderer=lambda path: _render_qe_electronic_preview(workchain, path),
    )


def PdosWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    output_parameters = _node_mapping(workchain.outputs.nscf.output_parameters)
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
        properties["fermi_energy_ev"] = fermi
    properties.update(_magnetization_properties(output_parameters))
    properties = _apply_property_overrides(
        properties, property_overrides, workchain, "pdos"
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["DOS"],
        properties,
        [structure_object],
        lambda path: _render_qe_electronic_preview(workchain, path),
        "pdos",
        preview_override=_preview_override(preview_overrides, workchain, "pdos"),
    )


def Cp2kPdosWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definition = _cp2k_pdos_property_definition(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )["pdos"]
    properties = _apply_property_overrides(
        definition["properties"], property_overrides, workchain, "pdos"
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        definition["object_type"],
        properties,
        [structure_object],
        lambda path: _render_cp2k_pdos_preview(workchain, path),
        "cp2k_pdos",
        preview_override=_preview_override(preview_overrides, workchain, "pdos"),
    )


def VibroWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
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
    output_parameters = _node_mapping(pw_base.outputs.output_parameters)
    dft_parameters = get_dft_parameters_qe(pw_base.inputs, output_parameters)
    properties = _simulation_properties(
        workchain,
        "Vibrational spectroscopy",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties["vibrational_mode"] = _qe_vibrational_mode(workchain)
    properties.update(_magnetization_properties(output_parameters))
    properties = _apply_property_overrides(
        properties, property_overrides, workchain, "vibrational_spectroscopy"
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Vibrational Spectroscopy"],
        properties,
        [structure_object],
        lambda path: _render_qe_vibrational_preview(workchain, path),
        "vibrational_spectrum",
        preview_override=_preview_override(
            preview_overrides, workchain, "vibrational_spectroscopy"
        ),
    )


def _cp2k_output_parameters(workchain):
    output = _get_optional_output(workchain.outputs, "dft_output_parameters")
    if output is None:
        output = workchain.outputs.output_parameters
    return _node_mapping(output)


def _cp2k_geo_opt_property_definitions(
    workchain,
    aiida_node_id=None,
    executable_ids=None,
):
    """Build geometry and optional final charge-analysis result definitions."""
    system_parameters = _node_mapping(workchain.inputs.sys_params)
    dft_parameters = get_dft_parameters_cp2k(
        workchain.inputs.code.description,
        _node_mapping(workchain.inputs.dft_params),
    )
    output_parameters = _cp2k_output_parameters(workchain)
    motion = output_parameters.get("motion_step_info", {})
    cell_optimization = workchain.label == "CP2K_CellOpt"

    properties = _simulation_properties(
        workchain,
        "Geometry optimization",
        dft_parameters,
        aiida_node_id,
        executable_ids=executable_ids,
    )
    properties.update(
        {
            "constrained": bool(system_parameters.get("constraints")),
            "cell_optimization": cell_optimization,
            "final_energy_hartree": _energy_in_hartree(output_parameters),
        }
    )
    if system_parameters.get("constraints"):
        properties["constraints_description"] = str(system_parameters["constraints"])
    if cell_optimization and system_parameters.get("cell_opt_constraint"):
        properties["cell_constraints"] = str(system_parameters["cell_opt_constraint"])
    if motion.get("max_grad_au"):
        properties["final_max_force_hartree_per_bohr"] = float(
            motion["max_grad_au"][-1]
        )
    if motion.get("step"):
        properties["number_of_steps"] = int(motion["step"][-1])

    definitions = {
        "geometry_optimization": {
            "object_type": OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
            "properties": properties,
        }
    }
    charge_definition = _cp2k_charge_analysis_definition(
        workchain,
        dft_parameters,
        output_parameters,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )
    if charge_definition is not None:
        definitions["charge_analysis"] = charge_definition
    return definitions


def Cp2kGeoOptWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definitions = _cp2k_geo_opt_property_definitions(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )

    geometry_properties = _apply_property_overrides(
        definitions["geometry_optimization"]["properties"],
        property_overrides,
        workchain,
        "geometry_optimization",
    )
    input_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    output_structure = workchain.outputs.output_structure
    geometry_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
        geometry_properties,
        [input_object],
        lambda path: _render_structure_preview(output_structure, path),
        "optimized_geometry",
        preview_override=_preview_override(
            preview_overrides, workchain, "geometry_optimization"
        ),
    )
    output_object = structure_to_atomistic_model(
        openbis_session, output_structure.uuid, uuids
    )
    output_object.add_parents(geometry_object)
    utils.update_openbis_object(output_object)
    geometry_object.add_children(output_object)
    utils.update_openbis_object(geometry_object)

    exported_objects = [geometry_object]
    if "charge_analysis" in definitions:
        charge_properties = _apply_property_overrides(
            definitions["charge_analysis"]["properties"],
            property_overrides,
            workchain,
            "charge_analysis",
        )
        charge_object = _create_simulation_object(
            openbis_session,
            experiment_id,
            OPENBIS_SIMULATION_TYPES["Charge Analysis"],
            charge_properties,
            [output_object, geometry_object],
            lambda path: _render_structure_preview(output_structure, path),
            "charge_analysis",
            preview_override=_preview_override(
                preview_overrides, workchain, "charge_analysis"
            ),
        )
        _attach_cp2k_charge_analysis_data(
            openbis_session,
            charge_object,
            workchain,
        )
        exported_objects.append(charge_object)
    return tuple(exported_objects)


def QeBanduppyUnfoldingWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    """Export QE/BandUPpy output as a dedicated band-unfolding result."""
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definition = _qe_banduppy_property_definition(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )["band_unfolding"]
    properties = _apply_property_overrides(
        definition["properties"], property_overrides, workchain, "band_unfolding"
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Band Unfolding"],
        properties,
        [structure_object],
        lambda path: _render_unfolding_preview(workchain, path),
        "band_unfolding",
        preview_override=_preview_override(
            preview_overrides, workchain, "band_unfolding"
        ),
    )


def Cp2kScfWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    """Export an SCF block and its optional charge/unfolding scientific results."""
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definitions = _cp2k_scf_property_definitions(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )

    energy_properties = _apply_property_overrides(
        definitions["energy_calculation"]["properties"],
        property_overrides,
        workchain,
        "energy_calculation",
    )
    energy_object = _create_simulation_object(
        openbis_session,
        experiment_id,
        OPENBIS_SIMULATION_TYPES["Energy Calculation"],
        energy_properties,
        [structure_object],
        lambda path: _render_structure_preview(workchain.inputs.structure, path),
        "energy_calculation",
        preview_override=_preview_override(
            preview_overrides, workchain, "energy_calculation"
        ),
    )
    exported_objects = [energy_object]

    if "charge_analysis" in definitions:
        charge_properties = _apply_property_overrides(
            definitions["charge_analysis"]["properties"],
            property_overrides,
            workchain,
            "charge_analysis",
        )
        charge_object = _create_simulation_object(
            openbis_session,
            experiment_id,
            OPENBIS_SIMULATION_TYPES["Charge Analysis"],
            charge_properties,
            [structure_object, energy_object],
            lambda path: _render_structure_preview(workchain.inputs.structure, path),
            "charge_analysis",
            preview_override=_preview_override(
                preview_overrides, workchain, "charge_analysis"
            ),
        )
        _attach_cp2k_charge_analysis_data(
            openbis_session,
            charge_object,
            workchain,
        )
        exported_objects.append(charge_object)

    if "band_unfolding" in definitions:
        band_properties = _apply_property_overrides(
            definitions["band_unfolding"]["properties"],
            property_overrides,
            workchain,
            "band_unfolding",
        )
        band_object = _create_simulation_object(
            openbis_session,
            experiment_id,
            OPENBIS_SIMULATION_TYPES["Band Unfolding"],
            band_properties,
            [structure_object],
            lambda path: _render_unfolding_preview(workchain, path),
            "band_unfolding",
            preview_override=_preview_override(
                preview_overrides, workchain, "band_unfolding"
            ),
        )
        exported_objects.append(band_object)

    return tuple(exported_objects)


def _preceding_mep_objects(openbis_session, experiment_id, workchain):
    """Return already exported MEP blocks represented in this provenance chain."""
    target_space = _collection_space_code(openbis_session, experiment_id)
    objects = []
    seen = set()
    for preceding_uuid in get_all_preceding_main_workchains(workchain.uuid):
        if str(preceding_uuid) == str(workchain.uuid):
            continue
        preceding = orm.load_node(preceding_uuid)
        if preceding.process_label not in {
            "Cp2kReplicaWorkChain",
            "Cp2kNebWorkChain",
        }:
            continue
        matches = list(
            openbis_session.get_objects(
                type=OPENBIS_SIMULATION_TYPES["Minimum Energy Path"],
                space=target_space,
                where={
                    "AIIDA_SOURCE_UUID": str(preceding.uuid),
                },
            )
            or []
        )
        for match in matches:
            permid = str(match.permId)
            if permid not in seen:
                objects.append(match)
                seen.add(permid)
    return objects


def Cp2kMepWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    """Export a replica-chain or NEB WorkChain as one minimum-energy path."""
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definition = _cp2k_mep_property_definition(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )["minimum_energy_path"]
    properties = _apply_property_overrides(
        definition["properties"],
        property_overrides,
        workchain,
        "minimum_energy_path",
    )
    if workchain.process_label == "Cp2kReplicaWorkChain":
        _energies, _values, start_structure, end_structure = _replica_chain_profile(
            workchain
        )
    else:
        start_structure, end_structure = _neb_input_endpoints(workchain)

    parents = [
        structure_to_atomistic_model(openbis_session, start_structure.uuid, uuids),
        structure_to_atomistic_model(openbis_session, end_structure.uuid, uuids),
    ]
    parents.extend(_preceding_mep_objects(openbis_session, experiment_id, workchain))
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        definition["object_type"],
        properties,
        parents,
        lambda path: _render_mep_preview(workchain, path),
        "minimum_energy_path",
        preview_override=_preview_override(
            preview_overrides,
            workchain,
            "minimum_energy_path",
        ),
    )


def Cp2kSpmWorkChain_export(
    openbis_session,
    experiment_id,
    workchain_uuid,
    uuids,
    aiida_node_id,
    executable_ids=None,
    preview_overrides=None,
    property_overrides=None,
):
    """Export STM, orbital, or AFM results as one SPM simulation block."""
    workchain = orm.load_node(workchain_uuid)
    if executable_ids is None:
        executable_ids = _ensure_executables(openbis_session, workchain)
    definition = _cp2k_spm_property_definition(
        workchain,
        aiida_node_id=aiida_node_id,
        executable_ids=executable_ids,
    )["spm"]
    properties = _apply_property_overrides(
        definition["properties"], property_overrides, workchain, "spm"
    )
    structure_object = structure_to_atomistic_model(
        openbis_session, workchain.inputs.structure.uuid, uuids
    )
    return _create_simulation_object(
        openbis_session,
        experiment_id,
        definition["object_type"],
        properties,
        [structure_object],
        lambda path: _render_spm_preview(workchain, path),
        "spm",
        preview_override=_preview_override(preview_overrides, workchain, "spm"),
    )


# Retain the public name used by downstream notebooks while sharing the generic
# implementation with orbital and AFM workflows.
Cp2kStmWorkChain_export = Cp2kSpmWorkChain_export


workchain_exporters = {
    "NanoribbonWorkChain": NanoribbonWorkChain_export,
    "PwRelaxWorkChain": PwRelaxWorkChain_export,
    "BandsWorkChain": BandsWorkChain_export,
    "PdosWorkChain": PdosWorkChain_export,
    "VibroWorkChain": VibroWorkChain_export,
    "Cp2kGeoOptWorkChain": Cp2kGeoOptWorkChain_export,
    "Cp2kScfWorkChain": Cp2kScfWorkChain_export,
    "Cp2kPdosWorkChain": Cp2kPdosWorkChain_export,
    "QeBanduppyUnfoldingWorkChain": QeBanduppyUnfoldingWorkChain_export,
    "Cp2kStmWorkChain": Cp2kSpmWorkChain_export,
    "Cp2kOrbitalsWorkChain": Cp2kSpmWorkChain_export,
    "Cp2kAfmWorkChain": Cp2kSpmWorkChain_export,
    "Cp2kReplicaWorkChain": Cp2kMepWorkChain_export,
    "Cp2kNebWorkChain": Cp2kMepWorkChain_export,
}


def _result_property_definitions(workchain):
    """Return schema-valid automatic properties for each exported result role."""
    process_label = workchain.process_label
    definitions = {}

    if process_label == "NanoribbonWorkChain":
        calculations = _find_nanoribbon_calculations(workchain)
        scf = calculations["scf"]
        output_parameters = _node_mapping(scf.outputs.output_parameters)
        dft_parameters = _qe_dft_from_calculation(scf)
        band_properties, dos_properties = _band_and_dos_properties(
            workchain,
            dft_parameters,
            output_parameters,
            calculations["bands"].outputs.output_band,
            None,
            None,
            "Orbital-projected density of states generated from the AiiDA workflow. "
            "Full arrays are stored in the linked AiiDA archive.",
        )
        definitions["bands"] = {
            "object_type": OPENBIS_SIMULATION_TYPES["Band Structure"],
            "properties": band_properties,
        }
        definitions["pdos"] = {
            "object_type": OPENBIS_SIMULATION_TYPES["DOS"],
            "properties": dos_properties,
        }
        cell_opt = calculations["cell_opt2"]
        if cell_opt is not None:
            cell_output = _node_mapping(cell_opt.outputs.output_parameters)
            properties = _simulation_properties(
                workchain,
                "Geometry optimization",
                dft_parameters,
                None,
            )
            properties.update(
                {
                    "constrained": False,
                    "cell_optimization": True,
                    "final_energy_hartree": _energy_in_hartree(cell_output),
                }
            )
            properties.update(_magnetization_properties(cell_output))
            cell_dofree = (
                _node_mapping(cell_opt.inputs.parameters)
                .get("CELL", {})
                .get("cell_dofree")
            )
            if cell_dofree:
                properties["cell_constraints"] = str(cell_dofree)
            definitions["geometry_optimization"] = {
                "object_type": OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
                "properties": properties,
            }
        return definitions

    if process_label == "PwRelaxWorkChain":
        properties = _qe_relax_properties(workchain)
        return {
            "geometry_optimization": {
                "object_type": OPENBIS_SIMULATION_TYPES["Geometry Optimisation"],
                "properties": properties,
            }
        }

    if process_label == "BandsWorkChain":
        try:
            root_in = workchain.inputs.bands
            root_out = workchain.outputs.bands
        except NotExistentAttributeError:
            root_in = workchain.inputs.bands_projwfc
            root_out = workchain.outputs.bands_projwfc
        output_parameters = _node_mapping(root_out.scf_parameters)
        dft_parameters = get_dft_parameters_qe(root_in.bands, output_parameters)
        band_properties, dos_properties = _band_and_dos_properties(
            workchain,
            dft_parameters,
            output_parameters,
            root_out.band_structure,
            None,
            None,
            "Orbital-projected density of states generated from the AiiDA workflow. "
            "Full arrays are stored in the linked AiiDA archive.",
        )
        definitions = {
            "bands": {
                "object_type": OPENBIS_SIMULATION_TYPES["Band Structure"],
                "properties": band_properties,
            }
        }
        if _bands_dos_node(root_out) is not None:
            definitions["pdos"] = {
                "object_type": OPENBIS_SIMULATION_TYPES["DOS"],
                "properties": dos_properties,
            }
        return definitions

    if process_label == "PdosWorkChain":
        output_parameters = _node_mapping(workchain.outputs.nscf.output_parameters)
        dft_parameters = get_dft_parameters_qe(workchain.inputs.scf, output_parameters)
        properties = _simulation_properties(workchain, "PDOS", dft_parameters, None)
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
            properties["fermi_energy_ev"] = fermi
        properties.update(_magnetization_properties(output_parameters))
        return {
            "pdos": {
                "object_type": OPENBIS_SIMULATION_TYPES["DOS"],
                "properties": properties,
            }
        }

    if process_label == "VibroWorkChain":
        pw_base = next(
            (
                node
                for node in workchain.called_descendants
                if node.process_label == "PwBaseWorkChain"
            ),
            None,
        )
        if pw_base is None:
            raise ValueError(
                "The vibrational workflow does not contain a PwBaseWorkChain."
            )
        output_parameters = _node_mapping(pw_base.outputs.output_parameters)
        dft_parameters = get_dft_parameters_qe(pw_base.inputs, output_parameters)
        properties = _simulation_properties(
            workchain, "Vibrational spectroscopy", dft_parameters, None
        )
        properties["vibrational_mode"] = _qe_vibrational_mode(workchain)
        properties.update(_magnetization_properties(output_parameters))
        return {
            "vibrational_spectroscopy": {
                "object_type": OPENBIS_SIMULATION_TYPES["Vibrational Spectroscopy"],
                "properties": properties,
            }
        }

    if process_label == "Cp2kPdosWorkChain":
        return _cp2k_pdos_property_definition(workchain)

    if process_label == "Cp2kGeoOptWorkChain":
        return _cp2k_geo_opt_property_definitions(workchain)

    if process_label == "QeBanduppyUnfoldingWorkChain":
        return _qe_banduppy_property_definition(workchain)

    if process_label == "Cp2kScfWorkChain":
        return _cp2k_scf_property_definitions(workchain)

    if process_label in {
        "Cp2kStmWorkChain",
        "Cp2kOrbitalsWorkChain",
        "Cp2kAfmWorkChain",
    }:
        return _cp2k_spm_property_definition(workchain)

    if process_label in {"Cp2kReplicaWorkChain", "Cp2kNebWorkChain"}:
        return _cp2k_mep_property_definition(workchain)

    return definitions


def _preview_definitions(workchain):
    """Return the suggested preview renderers for one exportable workchain."""
    process_label = workchain.process_label
    if process_label == "NanoribbonWorkChain":
        calculations = _find_nanoribbon_calculations(workchain)
        cell_opt = calculations["cell_opt2"]
        shared_renderer = _cached_preview_renderer(
            lambda path: _render_nanoribbon_bands_pdos_preview(workchain, path)
        )
        definitions = [
            (
                "bands",
                "Electronic band structure",
                "band_structure",
                shared_renderer,
            ),
            (
                "pdos",
                "Projected density of states",
                "pdos",
                shared_renderer,
            ),
        ]
        if cell_opt is not None:
            definitions.append(
                (
                    "geometry_optimization",
                    "Optimized geometry",
                    "optimized_geometry",
                    lambda path: _render_structure_preview(
                        cell_opt.outputs.output_structure, path
                    ),
                )
            )
        return definitions

    if process_label == "PwRelaxWorkChain":
        return [
            (
                "geometry_optimization",
                "Optimized geometry",
                "optimized_geometry",
                lambda path: _render_structure_preview(
                    workchain.outputs.output_structure, path
                ),
            )
        ]

    if process_label == "Cp2kGeoOptWorkChain":
        definitions = [
            (
                "geometry_optimization",
                "Optimized geometry",
                "optimized_geometry",
                lambda path: _render_structure_preview(
                    workchain.outputs.output_structure, path
                ),
            )
        ]
        properties = _cp2k_geo_opt_property_definitions(workchain)
        if "charge_analysis" in properties:
            definitions.append(
                (
                    "charge_analysis",
                    "Charge analysis",
                    "charge_analysis",
                    lambda path: _render_structure_preview(
                        workchain.outputs.output_structure, path
                    ),
                )
            )
        return definitions

    if process_label == "QeBanduppyUnfoldingWorkChain":
        return [
            (
                "band_unfolding",
                "Unfolded band structure",
                "band_unfolding",
                lambda path: _render_unfolding_preview(workchain, path),
            )
        ]
    if process_label == "Cp2kScfWorkChain":
        definitions = [
            (
                "energy_calculation",
                "Energy calculation",
                "energy_calculation",
                lambda path: _render_structure_preview(
                    workchain.inputs.structure, path
                ),
            )
        ]
        properties = _cp2k_scf_property_definitions(workchain)
        if "charge_analysis" in properties:
            definitions.append(
                (
                    "charge_analysis",
                    "Charge analysis",
                    "charge_analysis",
                    lambda path: _render_structure_preview(
                        workchain.inputs.structure, path
                    ),
                )
            )
        if "band_unfolding" in properties:
            definitions.append(
                (
                    "band_unfolding",
                    "Unfolded band structure",
                    "band_unfolding",
                    lambda path: _render_unfolding_preview(workchain, path),
                )
            )
        return definitions

    if process_label == "Cp2kPdosWorkChain":
        return [
            (
                "pdos",
                "Projected density of states",
                "cp2k_pdos",
                lambda path: _render_cp2k_pdos_preview(workchain, path),
            )
        ]

    if process_label == "BandsWorkChain":
        try:
            root_out = workchain.outputs.bands
        except NotExistentAttributeError:
            root_out = workchain.outputs.bands_projwfc
        shared_renderer = _cached_preview_renderer(
            lambda path: _render_qe_electronic_preview(workchain, path)
        )
        definitions = [
            (
                "bands",
                "Electronic band structure",
                "band_structure",
                shared_renderer,
            )
        ]
        dos_node = _bands_dos_node(root_out)
        if dos_node is not None:
            definitions.append(
                (
                    "pdos",
                    "Projected density of states",
                    "pdos",
                    shared_renderer,
                )
            )
        return definitions

    if process_label == "PdosWorkChain":
        return [
            (
                "pdos",
                "Projected density of states",
                "pdos",
                lambda path: _render_qe_electronic_preview(workchain, path),
            )
        ]

    if process_label == "VibroWorkChain":
        return [
            (
                "vibrational_spectroscopy",
                "Vibrational spectrum",
                "vibrational_spectrum",
                lambda path: _render_qe_vibrational_preview(workchain, path),
            )
        ]

    if process_label in {"Cp2kReplicaWorkChain", "Cp2kNebWorkChain"}:
        return [
            (
                "minimum_energy_path",
                "Minimum energy path",
                "minimum_energy_path",
                lambda path: _render_mep_preview(workchain, path),
            )
        ]

    if process_label in {
        "Cp2kStmWorkChain",
        "Cp2kOrbitalsWorkChain",
        "Cp2kAfmWorkChain",
    }:
        title = {
            "Cp2kStmWorkChain": "STM/STS map",
            "Cp2kOrbitalsWorkChain": "Orbital/SPM map",
            "Cp2kAfmWorkChain": "AFM map",
        }[process_label]
        return [
            (
                "spm",
                title,
                "spm",
                lambda path: _render_spm_preview(workchain, path),
            )
        ]
    return []


def _exportable_workchains(workchain):
    """Collect supported finished workchains represented by an export action."""
    targets = []
    seen = set()
    for main_workchain_uuid in get_all_preceding_main_workchains(workchain.uuid):
        main_workchain = orm.load_node(main_workchain_uuid)
        if not main_workchain.is_finished_ok:
            continue
        candidates = (
            [main_workchain]
            if main_workchain.process_label in workchain_exporters
            else [
                child
                for child in main_workchain.called_descendants
                if child.process_label in workchain_exporters
            ]
        )
        for candidate in candidates:
            candidate_uuid = str(candidate.uuid)
            if candidate_uuid not in seen:
                targets.append(candidate)
                seen.add(candidate_uuid)
    return targets


def render_workchain_preview_suggestions(
    workchain_uuid,
    openbis_session=None,
    experiment_id=None,
):
    """Prepare result reviews and identify results already present in openBIS."""
    workchain = orm.load_node(workchain_uuid)
    check_existing = openbis_session is not None and experiment_id not in (
        None,
        "",
        "-1",
    )
    suggestions = []
    with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-suggestions-") as dirname:
        directory = Path(dirname)
        for target in _exportable_workchains(workchain):
            property_definitions = _result_property_definitions(target)
            for role, title, stem, renderer in _preview_definitions(target):
                definition = property_definitions[role]
                existing_object = (
                    find_existing_simulation_result(
                        openbis_session,
                        experiment_id,
                        definition["object_type"],
                        target.uuid,
                    )
                    if check_existing
                    else None
                )
                existing = None
                if existing_object is not None:
                    existing = {
                        "permid": str(existing_object.permId),
                        "name": str(
                            _openbis_property(existing_object, "name")
                            or existing_object.permId
                        ),
                        "url": _openbis_eln_url(existing_object),
                    }
                    content = None
                    error = None
                else:
                    path = directory / f"{target.uuid}-{stem}.png"
                    error = None
                    try:
                        renderer(path)
                        if not path.is_file():
                            raise RuntimeError(
                                f"Preview renderer did not create {path.name}."
                            )
                        _resample_preview_path(path)
                        content = path.read_bytes()
                    except Exception as exception:  # noqa: BLE001 - allow UI replacement
                        content = None
                        error = str(exception)
                suggestion = {
                    "key": f"{target.uuid}:{role}",
                    "source_uuid": str(target.uuid),
                    "result_role": role,
                    "title": title,
                    "object_type": definition["object_type"],
                    "properties": definition["properties"],
                    "name": f"{stem}.png",
                    "content": content,
                    "error": error,
                }
                if check_existing:
                    suggestion["existing"] = existing
                suggestions.append(suggestion)
    return suggestions


def _run_exporter(
    openbis_session,
    experiment_id,
    workchain,
    structure_uuids,
    aiida_archive,
    resolved_executables,
    preview_overrides=None,
    property_overrides=None,
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
        preview_overrides=preview_overrides,
        property_overrides=property_overrides,
    )


def export_workchain(
    openbis_session,
    experiment_id,
    workchain_uuid,
    create_missing_executables=False,
    provenance_overrides=None,
    preview_overrides=None,
    property_overrides=None,
):
    workchain = orm.load_node(workchain_uuid)
    workchains_to_export = get_all_preceding_main_workchains(workchain.uuid)
    simulation_uuids_openbis = get_uuids_from_oBIS(openbis_session)

    pending_workchains = []
    for main_workchain_uuid in workchains_to_export:
        main_workchain = orm.load_node(main_workchain_uuid)
        if not main_workchain.is_finished_ok:
            continue
        pending_workchains.append(main_workchain)

    # Resolve every name before creating any archive or simulation object.
    resolved_executables = _ensure_executables_for_workchains(
        openbis_session,
        pending_workchains,
        create_missing=create_missing_executables,
        provenance_overrides=provenance_overrides,
    )

    exported_objects = []
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
                preview_overrides=preview_overrides,
                property_overrides=property_overrides,
            )
            exported_objects.extend(normalize_exported_objects(export))
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
                preview_overrides=preview_overrides,
                property_overrides=property_overrides,
            )
            exported_objects.extend(normalize_exported_objects(export))

    exported_objects = tuple(exported_objects)
    record_openbis_exports(openbis_session, exported_objects, collection=experiment_id)
    return exported_objects
