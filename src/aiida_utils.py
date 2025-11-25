from aiida.common.links import LinkType
import tempfile
import os
import subprocess
from aiida import orm
from pathlib import Path
from typing import Optional, Tuple
import numpy as np
from ase import Atoms
import json
from ase.io.jsonio import encode
from aiida.common.exceptions import NotExistentAttributeError
import random
from . import utils
import logging

OPENBIS_COLLECTIONS_PATHS = utils.read_json("metadata/collection_paths.json")
OPENBIS_OBJECT_TYPES = utils.read_json("metadata/object_types.json")
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

    parameters = {}
    parameters["xc_functional"] = outputs["dft_exchange_correlation"]
    parameters["plus_u"] = outputs["lda_plus_u_calculation"]
    parameters["spin_orbit_coupling"] = outputs["spin_orbit_calculation"]
    parameters["uks"] = outputs["lsda"]
    parameters["charge"] = float(inputs.pw.parameters["SYSTEM"]["tot_charge"])
    parameters["vdw_corr"] = inputs.pw.parameters["SYSTEM"].get("vdw_corr", "")

    return parameters


def get_dft_parameters_cp2k(code_description, dft_para):
    """Retrieves from CP2K workchains teh parameters to define the DFT object. Very preliminary"""

    parameters = {}
    parameters["xc_functional"] = "PBE"
    parameters["plus_u"] = False
    parameters["spin_orbit_coupling"] = False
    parameters["uks"] = dft_para.get("uks", False)
    parameters["charge"] = dft_para.get("charge", 0)
    parameters["vdw_corr"] = dft_para.get("vdw", "")

    return parameters


def geo_to_png(ase_geo):
    ase_geo.write("ase_geo.png")
    return "ase_geo.png"


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
    """Create archive.aiida as temporary file, with nodes only from a MAIN workchain.
    To be sent to AiiDA_nodes object"""

    # Define the output file path
    output_file = "archive.aiida"

    # Define the command, converting the integer `pk` to a string
    command = [
        "verdi",
        "archive",
        "create",
        output_file,
        "--no-call-calc-backward",
        "--no-call-work-backward",
        "--no-create-backward",
        "-N",
        uuid,
    ]

    aiida_node_type = OPENBIS_OBJECT_TYPES["AiiDA Node"]

    try:
        # Execute the command
        result = subprocess.run(command, capture_output=True, text=True)

        # Check for errors
        if result.returncode != 0:
            logging.info(f"An error occurred: {result.stderr}")
        else:
            # Capture the absolute path to the created file
            created_file_path = Path(output_file).resolve()

            # Create the AiiDA_nodes object in openBIS
            object_props = {"wfms_uuid": uuid, "comments": ""}
            obobject = utils.create_openbis_object(
                openbis_session,
                type=aiida_node_type,
                props=object_props,
                collection=OPENBIS_COLLECTIONS_PATHS["AiiDA Node"],
            )

            utils.create_openbis_dataset(
                openbis_session,
                type="RAW_DATA",
                sample=obobject,
                files=[created_file_path],
            )

    finally:
        # Ensure the file is deleted
        file_to_delete = Path(output_file)
        if file_to_delete.exists():
            file_to_delete.unlink()  # Delete the file
            logging.info(f"File {file_to_delete} has been deleted.")
        else:
            logging.info(f"File {file_to_delete} does not exist, nothing to delete.")
    return obobject


def NanoribbonsWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # is SUB of QeAppWorkChain
    workchain = orm.load_node(workchain_uuid)
    targets = {
        "cell_opt2": None,
        "scf": None,
        "bands": None,
        "export_pdos": None,
    }

    for node in workchain.called_descendants:
        if node.label in targets and targets[node.label] is None:
            targets[node.label] = node

    cell_op2 = targets["cell_op2"]
    scf = targets["scf"]
    bands = targets["bands"]
    export_pdos = targets["export_pdos"]

    output_parameters = get_qe_output_parameters(
        scf.outputs.output_parameters.get_dict()
    )
    input_parameters = get_qe_input_parameters(scf.outputs.output_parameters.get_dict())

    dft_object_parameters = {
        "xc_functional": "PBE",
        "plus_u": "False",
        "spin_orbit_coupling": "False",
        "uks": output_parameters["lsda"],
        "charge": float(scf.inputs.parameters["SYSTEM"]["tot_charge"]),
        "vdw_corr": "",
    }
    bands_type = OPENBIS_OBJECT_TYPES["Band Structure"]

    dictionary = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "output_parameters": json.dumps(output_parameters),
        "input_parameters": json.dumps(input_parameters),
        "band_gap": find_bandgap(
            bands.outputs.output_band.uuid,
            number_electrons=output_parameters["number_of_electrons"],
        )[1],
    }

    if workchain.description:
        workchain_name = workchain.caller.description[:30]
        dictionary["name"] = f"BANDS - {workchain_name}"

    # Create BANDSTRUCURE object
    bands_obobject = utils.create_openbis_object(
        openbis_session, type=bands_type, props=dictionary, collection=experiment_id
    )

    bands_obobject = set_simulation_codes(
        openbis_session, bands_obobject, workchain_uuid
    )

    # Create datasets in openbis and link them to the openBIS object
    pdos_json = aiida_data_to_json(root_out.projwfc.Dos.uuid)
    pbands_json = aiida_data_to_json(root_out.projwfc.bands.uuid)
    projections_json = aiida_data_to_json(root_out.projwfc.projections.uuid)
    band_structure_json = aiida_data_to_json(root_out.band_structure.uuid)
    utils.write_json(pdos_json, "pdos_json.json")
    utils.write_json(pbands_json, "pbands_json.json")
    utils.write_json(projections_json, "projections_json.json")
    utils.write_json(band_structure_json, "band_structure_json.json")

    utils.create_openbis_dataset(
        openbis_session,
        type="RAW_DATA",
        sample=bands_obobject,
        files=[
            "pdos_json.json",
            "pbands_json.json",
            "projections_json.json",
            "band_structure_json.json",
        ],
    )

    os.remove("pdos_json.json")
    os.remove("pbands_json.json")
    os.remove("projections_json.json")
    os.remove("band_structure_json.json")

    input_structure = workchain.inputs.structure
    # if missing create oBIS object and obtain uuid
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    bands_obobject.add_parents(input_structure)
    utils.update_openbis_object(bands_obobject)

    ## section geo opt
    geoopt_obobject = None
    if cell_opt2 is not None:
        force_conv_threshold_json = json.dumps(
            {
                "value": cell_opt2.inputs.parameters.get_dict()["CONTROL"][
                    "forc_conv_thr"
                ],
                "unit": "eV/Bohr**3",
            }
        )

        geo_opt_type = OPENBIS_OBJECT_TYPES["Geometry Optimisation"]
        output_parameters = get_qe_output_parameters(
            cell_opt2.outputs.output_parameters.get_dict()
        )
        input_parameters = get_qe_input_parameters(
            cell_opt2.outputs.output_parameters.get_dict()
        )

        dft_object_parameters = {
            "xc_functional": "PBE",
            "plus_u": "False",
            "spin_orbit_coupling": "False",
            "uks": output_parameters["lsda"],
            "charge": float(scf.inputs.parameters["SYSTEM"]["tot_charge"]),
            "vdw_corr": "",
        }
        geoopt_object_parameters = {
            "wfms_uuid": workchain_uuid,
            "level_theory_method": "dft",
            "level_theory_parameters": json.dumps(
                dft_object_parameters
            ),  # link/incorporate DFT object
            "force_convergence_threshold": force_conv_threshold_json,
            "constrained": False,
            "input_parameters": json.dumps(input_parameters),
        }

        geoopt_object_parameters["cell_opt_constraints"] = "free x"
        geoopt_object_parameters["cell_optimised"] = True

        if workchain.description:
            workchain_name = workchain.description[:30]
            geoopt_object_parameters["name"] = f"GeoOpt - {workchain_name}"

        # create oBIS GEO_OPT object
        geoopt_obobject = utils.create_openbis_object(
            openbis_session,
            type=geo_opt_type,
            props=geoopt_object_parameters,
            collection=experiment_id,
        )

        geoopt_obobject = set_simulation_codes(
            openbis_session, geoopt_obobject, workchain_uuid
        )

        # if missing create oBIS object and obtain uuid
        input_structure = workchain.inputs.structure
        input_structure = structure_to_atomistic_model(
            openbis_session, input_structure.uuid, uuids
        )
        geoopt_obobject.add_parents(input_structure)
        utils.update_openbis_object(geoopt_obobject)

        # if missing create oBIS object and obtain uuid
        output_structure = cell_opt2.outputs.output_structure
        output_structure = structure_to_atomistic_model(
            openbis_session, output_structure.uuid, uuids
        )
        output_structure.add_parents(geoopt_obobject)
        utils.update_openbis_object(output_structure)
        geoopt_obobject.add_children(output_structure)

    ## end section geo opt

    return geoopt_obobject, bands_obobject


def PwRelaxWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # is SUB of QeAppWorkChain
    workchain = orm.load_node(workchain_uuid)
    pw_input_parameters = workchain.inputs.base.pw.parameters.get_dict()
    output_parameters_dict = workchain.outputs.output_parameters.get_dict()

    dft_object_parameters = get_dft_parameters_qe(
        workchain.inputs.base, output_parameters_dict
    )

    force_conv_threshold_json = json.dumps(
        {"value": pw_input_parameters["CONTROL"]["forc_conv_thr"], "unit": "eV/Bohr**3"}
    )

    geo_opt_type = OPENBIS_OBJECT_TYPES["Geometry Optimisation"]

    geoopt_object_parameters = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "force_convergence_threshold": force_conv_threshold_json,
        "constrained": False,
        "output_parameters": json.dumps(
            get_qe_output_parameters(workchain.outputs.output_parameters.get_dict())
        ),
        "input_parameters": json.dumps(
            get_qe_input_parameters(workchain.outputs.output_parameters.get_dict())
        ),
    }

    geoopt_object_parameters["cell_optimised"] = (
        pw_input_parameters["CONTROL"]["calculation"] == "vc-relax"
    )
    if geoopt_object_parameters["cell_optimised"]:
        geoopt_object_parameters["cell_opt_constraints"] = pw_input_parameters.get(
            "CELL", {}
        ).get("cell_dofree", "")

    if workchain.caller.description:
        workchain_name = workchain.caller.description[:30]
        geoopt_object_parameters["name"] = f"GeoOpt - {workchain_name}"

    # create oBIS GEO_OPT object
    geoopt_obobject = utils.create_openbis_object(
        openbis_session,
        type=geo_opt_type,
        props=geoopt_object_parameters,
        collection=experiment_id,
    )

    geoopt_obobject = set_simulation_codes(
        openbis_session, geoopt_obobject, workchain_uuid
    )

    # if missing create oBIS object and obtain uuid
    input_structure = workchain.inputs.structure
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    geoopt_obobject.add_parents(input_structure)
    utils.update_openbis_object(geoopt_obobject)

    # if missing create oBIS object and obtain uuid
    output_structure = workchain.outputs.output_structure
    output_structure = structure_to_atomistic_model(
        openbis_session, output_structure.uuid, uuids
    )
    output_structure.add_parents(geoopt_obobject)
    utils.update_openbis_object(output_structure)
    geoopt_obobject.add_children(output_structure)

    return geoopt_obobject


def BandsWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # is SUB of QeAppWorkChain
    workchain = orm.load_node(workchain_uuid)
    try:
        root_in = workchain.inputs.bands
        root_out = workchain.outputs.bands
    except NotExistentAttributeError:
        root_in = workchain.inputs.bands_projwfc
        root_out = workchain.outputs.bands_projwfc

    dft_object_parameters = get_dft_parameters_qe(
        root_in.bands, root_out.scf_parameters.get_dict()
    )

    bands_type = OPENBIS_OBJECT_TYPES["Band Structure"]

    output_parameters = get_qe_output_parameters(root_out.scf_parameters.get_dict())
    input_parameters = get_qe_input_parameters(root_out.scf_parameters.get_dict())
    dictionary = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "output_parameters": json.dumps(output_parameters),
        "input_parameters": json.dumps(input_parameters),
        "band_gap": find_bandgap(
            root_out.band_structure.uuid,
            number_electrons=output_parameters["number_of_electrons"],
        )[1],
    }

    if workchain.caller.description:
        workchain_name = workchain.caller.description[:30]
        dictionary["name"] = f"BANDS - {workchain_name}"

    # Create BANDSTRUCURE object
    bands_obobject = utils.create_openbis_object(
        openbis_session, type=bands_type, props=dictionary, collection=experiment_id
    )

    bands_obobject = set_simulation_codes(
        openbis_session, bands_obobject, workchain_uuid
    )

    # Create datasets in openbis and link them to the openBIS object
    pdos_json = aiida_data_to_json(root_out.projwfc.Dos.uuid)
    pbands_json = aiida_data_to_json(root_out.projwfc.bands.uuid)
    projections_json = aiida_data_to_json(root_out.projwfc.projections.uuid)
    band_structure_json = aiida_data_to_json(root_out.band_structure.uuid)
    utils.write_json(pdos_json, "pdos_json.json")
    utils.write_json(pbands_json, "pbands_json.json")
    utils.write_json(projections_json, "projections_json.json")
    utils.write_json(band_structure_json, "band_structure_json.json")

    utils.create_openbis_dataset(
        openbis_session,
        type="RAW_DATA",
        sample=bands_obobject,
        files=[
            "pdos_json.json",
            "pbands_json.json",
            "projections_json.json",
            "band_structure_json.json",
        ],
    )

    os.remove("pdos_json.json")
    os.remove("pbands_json.json")
    os.remove("projections_json.json")
    os.remove("band_structure_json.json")

    input_structure = workchain.inputs.structure
    # if missing create oBIS object and obtain uuid
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    bands_obobject.add_parents(input_structure)
    utils.update_openbis_object(bands_obobject)

    return bands_obobject


def PdosWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # is SUB of QeAppWorkChain
    workchain = orm.load_node(workchain_uuid)
    root_in = workchain.inputs
    root_out = workchain.outputs

    dft_object_parameters = get_dft_parameters_qe(
        root_in.scf, root_out.nscf.output_parameters.get_dict()
    )

    pdos_type = OPENBIS_OBJECT_TYPES["PDOS"]

    dictionary = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "output_parameters": json.dumps(
            get_qe_output_parameters(root_out.nscf.output_parameters.get_dict())
        ),
        "input_parameters": json.dumps(
            get_qe_input_parameters(root_out.nscf.output_parameters.get_dict())
        ),
    }

    if workchain.caller.description:
        workchain_name = workchain.caller.description[:30]
        dictionary["name"] = f"PDOS - {workchain_name}"

    # Create PDOS object
    pdos_obobject = utils.create_openbis_object(
        openbis_session, type=pdos_type, props=dictionary, collection=experiment_id
    )

    pdos_obobject = set_simulation_codes(openbis_session, pdos_obobject, workchain_uuid)

    # Create datasets in openbis and link them to the openBIS object
    dos_json = aiida_data_to_json(workchain.outputs.dos.output_dos.uuid)
    pdos_json = aiida_data_to_json(workchain.outputs.projwfc.Dos.uuid)
    utils.write_json(dos_json, "dos_json.json")
    utils.write_json(pdos_json, "pdos_json.json")

    utils.create_openbis_dataset(
        openbis_session,
        type="RAW_DATA",
        sample=pdos_obobject,
        files=["pdos_json.json", "dos_json.json"],
    )

    os.remove("pdos_json.json")
    os.remove("dos_json.json")

    # if missing create oBIS object and obtain uuid
    input_structure = workchain.inputs.structure
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    pdos_obobject.add_parents(input_structure)
    utils.update_openbis_object(pdos_obobject)

    return pdos_obobject


def VibroWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # is SUB of QeAppWorkChain
    # outputs are not exported so we look for a PwBaseWorkChain
    workchain = orm.load_node(workchain_uuid)
    for wkc in workchain.called_descendants:
        if wkc.process_label == "PwBaseWorkChain":
            root_in = wkc.inputs
            root_out = wkc.outputs
            break

    dft_object_parameters = get_dft_parameters_qe(
        root_in, root_out.output_parameters.get_dict()
    )

    vibro_spec_type = OPENBIS_OBJECT_TYPES["Vibrational Spectroscopy"]

    dictionary = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
    }

    if workchain.caller.description:
        workchain_name = workchain.caller.description[:30]
        dictionary["name"] = f"VibroSpec - {workchain_name}"

    # Create VIBSPEC object
    vibro_spec_obobject = utils.create_openbis_object(
        openbis_session,
        type=vibro_spec_type,
        props=dictionary,
        collection=experiment_id,
    )

    vibro_spec_obobject = set_simulation_codes(
        openbis_session, vibro_spec_obobject, workchain_uuid
    )

    # Create datasets in openbis and link them to the openBIS object
    phonon_bands_json = aiida_data_to_json(workchain.outputs.phonon_bands.uuid)
    phonon_pdos_json = aiida_data_to_json(workchain.outputs.phonon_pdos.uuid)
    phonon_thermo_json = aiida_data_to_json(workchain.outputs.phonon_thermo.uuid)
    utils.write_json(phonon_bands_json, "phonon_bands_json.json")
    utils.write_json(phonon_pdos_json, "phonon_pdos_json.json")
    utils.write_json(phonon_thermo_json, "phonon_thermo_json.json")

    utils.create_openbis_dataset(
        openbis_session,
        type="RAW_DATA",
        sample=vibro_spec_obobject,
        files=[
            "phonon_bands_json.json",
            "phonon_pdos_json.json",
            "phonon_thermo_json.json",
        ],
    )

    os.remove("phonon_bands_json.json")
    os.remove("phonon_pdos_json.json")
    os.remove("phonon_thermo_json.json")

    input_structure = workchain.inputs.structure
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    vibro_spec_obobject.add_parents(input_structure)
    utils.update_openbis_object(vibro_spec_obobject)

    return vibro_spec_obobject


def Cp2kGeoOptWorkChain_export(
    openbis_session, experiment_id, workchain_uuid, uuids
):  # Can be both MAIN and SUB. Do not export in case is SUB
    workchain = orm.load_node(workchain_uuid)
    sys_params = workchain.inputs.sys_params.get_dict()
    dft_params = workchain.inputs.dft_params.get_dict()
    code = workchain.inputs.code.description

    properties = [
        "energy",
        "energy_scf",
        "energy_units",
        "bandgap_spin1_au",
        "bandgap_spin2_au",
    ]
    if hasattr(workchain.outputs, "dft_output_parameters"):
        all_output_parameters = workchain.outputs.dft_output_parameters.get_dict()
    else:
        all_output_parameters = workchain.outputs.output_parameters.get_dict()
    output_parameters = {
        key: all_output_parameters[key]
        for key in properties
        if key in all_output_parameters
    }
    step_info = {
        key: values[-1]
        for key, values in all_output_parameters["motion_step_info"].items()
    }
    output_parameters.update(step_info)

    input_parameters = {}
    try:
        input_parameters = workchain.outputs.final_input_parameters.get_dict()
    except NotExistentAttributeError:
        pass
    input_structure = workchain.inputs.structure

    dft_object_parameters = get_dft_parameters_cp2k(code, dft_params)
    if dft_object_parameters["vdw_corr"]:
        dft_object_parameters["vdw_corr"] = "DFT-D3"

    geo_opt_type = OPENBIS_OBJECT_TYPES["Geometry Optimisation"]

    geoopt_object_parameters = {
        "wfms_uuid": workchain_uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "constrained": sys_params["constraints"] != "",
        "output_parameters": json.dumps(output_parameters),
        "input_parameters": json.dumps(input_parameters),
    }

    geoopt_object_parameters["cell_optimised"] = workchain.label == "CP2K_CellOpt"
    if geoopt_object_parameters["cell_optimised"]:
        geoopt_object_parameters["cell_opt_constraints"] = sys_params[
            "cell_opt_constraint"
        ]

    if workchain.description:
        workchain_name = workchain.description[:30]
        geoopt_object_parameters["name"] = f"GeoOpt - {workchain_name}"

    # create oBIS GEO_OPT object
    geoopt_obobject = utils.create_openbis_object(
        openbis_session,
        type=geo_opt_type,
        props=geoopt_object_parameters,
        collection=experiment_id,
    )

    geoopt_obobject = set_simulation_codes(
        openbis_session, geoopt_obobject, workchain_uuid
    )

    # if missing create oBIS object and obtain uuid
    input_structure = workchain.inputs.structure
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )
    geoopt_obobject.add_parents(input_structure)
    utils.update_openbis_object(geoopt_obobject)

    # if missing create oBIS object and obtain uuid
    output_structure = workchain.outputs.output_structure
    output_structure = structure_to_atomistic_model(
        openbis_session, output_structure.uuid, uuids
    )
    output_structure.add_parents(geoopt_obobject)
    utils.update_openbis_object(output_structure)

    geoopt_obobject.add_children(output_structure)

    # TBD output trajectory....
    # output_trajectory = aiida_data_to_json(workchain.outputs.output_trajectory)

    return geoopt_obobject


def Cp2kStmWorkChain_export(openbis_session, experiment_id, workchain_uuid, uuids):
    workchain = orm.load_node(workchain_uuid)
    dft_params = workchain.inputs.dft_params.get_dict()
    spm_params = workchain.inputs.spm_params.get_dict()
    # cp2k_code = workchain.inputs.cp2k_code.description
    spm_code = workchain.inputs.spm_code.description

    properties = [
        "energy",
        "energy_scf",
        "energy_units",
        "bandgap_spin1_au",
        "bandgap_spin2_au",
    ]
    if hasattr(workchain.outputs, "dft_output_parameters"):
        all_output_parameters = workchain.outputs.dft_output_parameters.get_dict()
    else:
        all_output_parameters = workchain.outputs.output_parameters.get_dict()
    output_parameters = {
        key: all_output_parameters[key]
        for key in properties
        if key in all_output_parameters
    }
    step_info = {
        key: values[-1]
        for key, values in all_output_parameters["motion_step_info"].items()
    }
    output_parameters.update(step_info)

    input_parameters = {}

    dft_object_parameters = get_dft_parameters_cp2k(spm_code, dft_params)
    if dft_object_parameters["vdw_corr"]:
        dft_object_parameters["vdw_corr"] = "DFT-D3"

    bias_voltages_json = [
        json.dumps({"value": float(i), "unit": "unit:V"})
        for i in spm_params["--energy_range"]
    ]
    isovalues_json = [
        json.dumps({"value": float(i), "unit": "eV/Bohr**3"})
        for i in spm_params["--isovalues"]
    ]
    heights_json = [
        json.dumps({"value": float(i), "unit": "unit:ANGSTROM"})
        for i in spm_params["--heights"]
    ]

    measurement_type = OPENBIS_OBJECT_TYPES["STM Simulation"]

    dictionary = {
        "wfms_uuid": workchain.uuid,
        "level_theory_method": "dft",
        "level_theory_parameters": json.dumps(
            dft_object_parameters
        ),  # link/incorporate DFT object
        "bias_voltages": json.dumps(bias_voltages_json),
        "isovalues": json.dumps(isovalues_json),
        "heights": json.dumps(heights_json),
        # TODO: Uncomment this as long as I reset openBIS schema
        # "p_tip": spm_params["--p_tip_ratios"],
        "output_parameters": json.dumps(output_parameters),
        "input_parameters": json.dumps(input_parameters),
    }

    if workchain.description:
        workchain_name = workchain.description[:30]
        dictionary["name"] = f"STM - {workchain_name}"

    dictionary["default_object_view"] = "IMAGING_GALLERY_VIEW"
    # create oBIS 2D_MEASUREMENT object (how to knwo if it is 2D or 1D???)
    obobject = utils.create_openbis_object(
        openbis_session,
        type=measurement_type,
        props=dictionary,
        collection=experiment_id,
    )

    obobject = set_simulation_codes(openbis_session, obobject, workchain_uuid)

    workchain.base.extras.set(
        "eln", {"url": OPENBIS_SESSION.url, "object_uuid": obobject.permId}
    )

    input_structure = workchain.inputs.structure
    input_structure = structure_to_atomistic_model(
        openbis_session, input_structure.uuid, uuids
    )

    obobject.add_parents(input_structure)
    utils.update_openbis_object(obobject)

    return obobject


def set_simulation_codes(openbis_session, obis_object, workchain_uuid):
    code_type = OPENBIS_OBJECT_TYPES["Code"]
    openbis_codes_filepaths = {
        code_object.props["filepath_executable"]: code_object
        for code_object in utils.get_openbis_objects(openbis_session, type=code_type)
    }
    workchain_codes = get_codes_info(workchain_uuid)

    simulations_codes = []
    for code_info in workchain_codes:
        code_filepath = code_info["filepath_executable"]
        if code_filepath in openbis_codes_filepaths.keys():
            code_object = openbis_codes_filepaths[code_filepath]
        else:
            code_object = utils.create_openbis_object(
                openbis_session,
                type=code_type,
                props=code_info,
                collection=OPENBIS_COLLECTIONS_PATHS["Open Source Code"],
            )

        simulations_codes.append(code_object.permId)

    obis_object.props["codes"] = simulations_codes

    return obis_object


def get_codes_info(workchain_uuid):
    codesinfo_list = []
    workchain = orm.load_node(workchain_uuid)
    codes = set(
        [
            node.inputs.code
            for node in workchain.called_descendants
            if isinstance(node, orm.CalcJobNode)
        ]
    )
    for code in codes:
        codesinfo = {
            "name": code.filepath_executable.name,
            "description": code.description,
            "filepath_executable": code.filepath_executable.as_posix(),
        }
        codesinfo_list.append(codesinfo)
    return codesinfo_list


workchain_exporters = {
    "NanoribbonsWorkChain_export": NanoribbonsWorkChain_export,
    "PwRelaxWorkChain": PwRelaxWorkChain_export,
    "BandsWorkChain": BandsWorkChain_export,
    "PdosWorkChain": PdosWorkChain_export,
    "VibroWorkChain": VibroWorkChain_export,
    "Cp2kGeoOptWorkChain": Cp2kGeoOptWorkChain_export,
    "Cp2kStmWorkChain": Cp2kStmWorkChain_export,
}


def export_workchain(openbis_session, experiment_id, workchain_uuid):
    workchain = orm.load_node(workchain_uuid)
    workchains_to_export = get_all_preceding_main_workchains(workchain.uuid)
    export = None
    simulation_uuids_oBIS = get_uuids_from_oBIS(openbis_session)

    # create individual oBIS objects
    for main_wc_uuid in workchains_to_export:
        main_wc = orm.load_node(main_wc_uuid)

        if (
            main_wc.is_finished_ok
        ):  # if not we do not parse it but it will still be in the AiiDA archive
            if main_wc_uuid not in simulation_uuids_oBIS["wc_uuids"]:
                logging.info(f"dealing with main WC {main_wc.pk}")

                # create global .aiida for main_wc and AiiDA_nodes openBIS object with the archive as dataset
                AiiDA_archive = create_and_export_AiiDA_archive(
                    openbis_session, main_wc_uuid
                )

                if main_wc.process_label in workchain_exporters:
                    # check if wc.uuid already in openBIS
                    # if not in openbis create pertinent oBIS object and populate it
                    export = workchain_exporters[main_wc.process_label](
                        openbis_session,
                        experiment_id,
                        main_wc_uuid,
                        simulation_uuids_oBIS["structure_uuids"],
                    )
                    export.props["aiida_node"] = AiiDA_archive.permId
                    # In teh case of NanoribonsWorkChain we have to link both geoopt and bands
                    if isinstance(export, tuple):
                        for obj in export:
                            if obj is not None:
                                obj.props["aiida_node"] = AiiDA_archive.permId
                                utils.update_openbis_object(obj)
                    else:
                        utils.update_openbis_object(export)

                    # Update current status of openBIS simulations
                    simulation_uuids_oBIS = get_uuids_from_oBIS(openbis_session)
                else:
                    logging.info(main_wc.process_label, " checking sub_workchains")
                    # all workchains called by the main workchain
                    wc_tree = main_wc.called_descendants
                    for wc in wc_tree:
                        # we export only properties related workchains: geo_opt, bands,...
                        if wc.process_label in workchain_exporters:
                            # check if wc.uuid already in openBIS
                            # if not in openbis create pertinent oBIS object and populate it
                            export = workchain_exporters[wc.process_label](
                                openbis_session,
                                experiment_id,
                                wc.uuid,
                                simulation_uuids_oBIS["structure_uuids"],
                            )

                            export.props["aiida_node"] = AiiDA_archive.permId
                            utils.update_openbis_object(export)

                            # Update current status of openBIS simulations
                            simulation_uuids_oBIS = get_uuids_from_oBIS(openbis_session)
                        # else:
                        #    print(wc.process_label,' should not be exported')

    return export
