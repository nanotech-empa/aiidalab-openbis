"""ORCA result adapters. Read stored AiiDA data only; never open a transport.

No ORCA import is required to export an archive imported on another instance.
The generic publisher supplies matching, archives, review and retry semantics.
"""

import json
from pathlib import Path

import numpy as np
from aiida import orm


WORKFLOWS = {
    "nto_cubes": "NtoCubesWorkChain",
    "geometry": "GeometryWorkChain",
    "reference": "ReferenceWorkChain",
    "common_orbitals": "CommonOrbitalsWorkChain",
    "casscf": "CasscfWorkChain",
    "casci": "CasciWorkChain",
    "orbitals": "OrbitalsWorkChain",
    "common_orbital_cubes": "CommonOrbitalCubesWorkChain",
    "dyson": "DysonWorkChain",
    "dyson_cubes": "DysonCubesWorkChain",
    "kondo": "KondoWorkChain",
    "kondo_cubes": "KondoCubesWorkChain",
    "vibrations": "VibrationsWorkChain",
}
CALCULATIONS = {
    "optical": "OpticalCalculation",
    "correlation": "CorrelationCalculation",
    "dyson_maps": "DysonMapsCalculation",
    "kondo_maps": "KondoMapsCalculation",
    "map_figure": "MapFigureCalculation",
}
PROCESS_TYPES = {
    **{"aiida.workflows:empa_orca." + key: value for key, value in WORKFLOWS.items()},
    **{
        "aiida.calculations:empa_orca." + key: value
        for key, value in CALCULATIONS.items()
    },
}
LABELS = set(PROCESS_TYPES.values())
RESULT_TITLES = {
    "optical": "Optical excitations / NTO analysis",
    "nto_cubes": "NTO hole / particle cubes",
    "correlation": "Correlation energies",
    "geometry": "Geometry / SCF",
    "reference": "SCF",
    "common_orbitals": "QRO / UNO reference",
    "casscf": "CASSCF optimized reference and states",
    "casci": "CASCI states",
    "orbitals": "Orbitals / density cubes",
    "common_orbital_cubes": "Spatial orbital cubes",
    "dyson": "Dyson transitions",
    "dyson_cubes": "Dyson cubes",
    "kondo": "Kondo exchange",
    "kondo_cubes": "Kondo cubes",
    "vibrations": "IR / Raman",
    "dyson_maps": "Dyson maps",
    "kondo_maps": "Kondo maps",
    "map_figure": "Saved map figure",
}
SPATIAL = {
    "nto_cubes",
    "orbitals",
    "common_orbital_cubes",
    "dyson_cubes",
    "kondo_cubes",
    "dyson_maps",
    "kondo_maps",
    "map_figure",
}


def operation(node):
    if getattr(node, "process_type", "") not in PROCESS_TYPES:
        raise ValueError("This is not a supported ORCA result process.")
    return node.process_type.rsplit(".", 1)[1]


def supported(node):
    return getattr(node, "process_type", "") in PROCESS_TYPES


def mapping(namespace, name):
    return namespace[name].get_dict() if name in namespace else {}


def data_nodes(namespace):
    for key in namespace:
        value = namespace[key]
        if isinstance(value, orm.Data):
            yield value
        elif not isinstance(value, orm.Node):
            yield from data_nodes(value)


def structure_uuid(node):
    """Resolve explicit structure identity, including fixed-orbital analyses."""
    op = operation(node)
    if op in {"geometry", "reference"} and "structure" in node.outputs:
        return str(node.outputs.structure.uuid)
    if "structure" in node.inputs:
        return str(node.inputs.structure.uuid)
    pending = list(data_nodes(node.inputs))
    seen, identities = set(), set()
    while pending:
        item = pending.pop()
        if str(item.uuid) in seen:
            continue
        seen.add(str(item.uuid))
        if isinstance(item, orm.Dict):
            values = item.get_dict()
            if values.get("structure_uuid"):
                identities.add(str(values["structure_uuid"]))
                continue
            for key in ("orbital_reference_uuid", "initial_state_uuid"):
                if values.get(key):
                    pending.append(orm.load_node(values[key]))
        creator = item.creator
        if creator is not None:
            pending.extend(data_nodes(creator.inputs))
    if len(identities) != 1:
        raise ValueError("The stored result does not identify one unique geometry.")
    result = identities.pop()
    if not isinstance(orm.load_node(result), orm.StructureData):
        raise ValueError("The recorded geometry UUID is not StructureData.")
    return result


def structures(node, role):
    final = structure_uuid(node)
    if role == "geometry_optimization":
        return [str(node.inputs.structure.uuid)], [final]
    return [final], []


def _finite(value, label):
    value = float(value)
    if not np.isfinite(value):
        raise ValueError("Missing or nonfinite stored " + label)
    return value


def electronic_context(node):
    """Read the nearest explicit charge/spin context from stored input data."""
    for namespace in (node.outputs, node.inputs):
        for key in ("initial", "transitions", "channels"):
            if key not in namespace:
                continue
            values = namespace[key].get_dict()
            state = values.get("initial_state") or (values.get("states") or [{}])[0]
            if "charge" in state:
                return int(state["charge"]), state.get("multiplicity")
    pending = list(data_nodes(node.inputs))
    seen = set()
    while pending:
        next_level, found = [], []
        for item in pending:
            if str(item.uuid) in seen:
                continue
            seen.add(str(item.uuid))
            if isinstance(item, orm.Dict):
                values = item.get_dict()
                state = values.get("initial_state", {})
                if not state and values.get("states"):
                    state = values["states"][0]
                state = state or values
                if "charge" in state:
                    found.append(
                        (
                            int(state["charge"]),
                            state.get("multiplicity", state.get("source_multiplicity")),
                        )
                    )
            creator = item.creator
            if creator is not None:
                next_level.extend(data_nodes(creator.inputs))
        if found:
            if len({q for q, _ in found}) != 1:
                raise ValueError("The result has ambiguous charge provenance.")
            return found[0]
        pending = next_level
    raise ValueError("The result has no stored electronic charge context.")


def definitions(node):
    """One record per result role/type; multi-root tables stay intact."""
    op = operation(node)
    if not node.is_finished_ok:
        raise ValueError("Only successfully completed ORCA results can be exported.")
    settings = mapping(node.inputs, "settings") or mapping(
        node.inputs, "reference_settings"
    )
    reference = mapping(node.inputs, "orbital_reference")
    if op == "optical":
        electronic = mapping(node.inputs, "electronic_settings")
    elif op == "nto_cubes":
        electronic = mapping(node.inputs, "excitations").get("electronic_settings", {})
    else:
        electronic = reference.get("settings", settings)
    common = {
        "name": node.label or ("ORCA " + op.replace("_", " ")),
        "converged": True,
        "aiida_source_uuid": str(node.uuid),
        "method_family": "OTHER"
        if electronic.get("method", "").upper() in {"HF", "RHF", "UHF", "ROHF"}
        else "DFT",
        "method_label": "/".join(
            str(electronic[k]) for k in ("method", "basis") if electronic.get(k)
        ),
    }
    for source, target in (("charge", "charge"), ("multiplicity", "spin_multiplicity")):
        if source in settings:
            common[target] = settings[source]
        elif source in reference:
            common[target] = reference[source]
    result = {}

    def add(role, type_code, title, **properties):
        result[role] = {
            "object_type": type_code,
            "title": title,
            "properties": dict(common, **properties),
        }

    if op in {"geometry", "reference"}:
        optimized = op == "geometry" and node.inputs.optimize.value
        summary = mapping(
            node.outputs,
            "optimization_summary" if op == "geometry" else "reference_summary",
        )
        if not summary.get("converged"):
            raise ValueError("The stored electronic result is not converged.")
        energy = _finite(summary.get("energy_hartree"), "total energy")
        if optimized:
            add(
                "geometry_optimization",
                "GEOMETRY_OPTIMISATION",
                "Optimized geometry",
                constrained=bool(settings.get("constraints")),
                cell_optimization=False,
                final_energy_hartree=energy,
                constraints_description=json.dumps(settings["constraints"])
                if settings.get("constraints")
                else None,
                number_of_steps=summary.get("optimization_steps"),
            )
        else:
            add(
                "energy_calculation",
                "ENERGY_CALCULATION",
                "SCF energy",
                total_energy_hartree=energy,
            )
        if "pdos" in node.outputs and "scf" in node.outputs.pdos:
            meta = node.outputs.pdos.scf.metadata.get_dict()
            if meta.get("kind", "").upper() != "SCF":
                raise ValueError("Only SCF eigenvalues form this orbital DOS.")
            add(
                "pdos",
                "DOS",
                "SCF projected orbital DOS",
                pdos=True,
                projection_description="Symmetric Lowdin atomic/angular orbital weights. Spin channels are separate; occupations do not weight the orbital DOS. Full compact arrays are in the AiiDA archive.",
            )
    elif op == "correlation":
        table = mapping(node.outputs, "correlation_energies")
        method = table.get("method")
        states = table.get("states", [])
        if (
            method
            not in {"RI-MP2", "SC-NEVPT2", "FIC-NEVPT2", "DLPNO-NEVPT2", "CASPT2"}
            or not states
            or table.get("dyson_compatible") is not False
        ):
            raise ValueError("Missing or unsupported stored correlation-energy result.")
        charges = {r["charge"] for r in states}
        if len(charges) != 1:
            raise ValueError("Correlation states do not share one charge.")
        common["charge"] = next(iter(charges))
        metadata = {
            "result_kind": "correlation",
            "method": method,
            "model": table.get("model", {}),
            "checks": table.get("checks", {}),
            "correlation_energies_uuid": str(node.outputs.correlation_energies.uuid),
            "energy_only": True,
        }
        if method == "RI-MP2":
            if len(states) != 1:
                raise ValueError("RI-MP2 exports one energy result.")
            add(
                "energy_calculation",
                "ENERGY_CALCULATION",
                "RI-MP2 correlation energy",
                method_family="OTHER",
                method_label=method,
                spin_multiplicity=states[0]["multiplicity"],
                total_energy_hartree=_finite(
                    states[0]["energy_hartree"], "MP2 total energy"
                ),
                comments=json.dumps(metadata, sort_keys=True),
            )
        else:
            add(
                "unclassified",
                "UNCLASSIFIED_SIMULATION",
                method + " corrected state energies",
                method_family="CAS",
                method_label=method,
                simulation_description="Complete CASSCF reference, correction and total state energies in the linked AiiDA archive.",
            )
    elif op == "optical":
        table = mapping(node.outputs, "excitations")
        if (
            table.get("method") not in {"TDA", "TDDFT"}
            or not table.get("states")
            or table.get("dyson_compatible") is not False
        ):
            raise ValueError("Missing or unsupported stored optical state family.")
        for state in table["states"]:
            if (
                _finite(state["energy_ev"], "excitation energy") <= 0
                or _finite(state["oscillator_strength"], "oscillator strength") < 0
            ):
                raise ValueError("Invalid stored optical state.")
        add(
            "unclassified",
            "UNCLASSIFIED_SIMULATION",
            "Vertical optical excitations and NTO analysis",
            method_family="DFT",
            method_label=table["method"] + " / " + common["method_label"],
            simulation_description="Complete vertical excitation energies, native length-gauge strengths, spin labels and unmodified NTO weights in the linked AiiDA archive.",
        )
    elif op == "vibrations":
        summary = mapping(node.outputs, "summary")
        add(
            "vibrational_spectroscopy",
            "VIBRATIONAL_SPECTROSCOPY",
            "IR / Raman spectrum",
            vibrational_mode="PHONONS_IR_RAMAN"
            if summary.get("raman")
            else "PHONONS_IR",
        )
    elif op in SPATIAL:
        kind = (
            "NTO"
            if op == "nto_cubes"
            else "Kondo"
            if "kondo" in op
            else "Dyson"
            if "dyson" in op
            else reference.get("kind", "SCF")
        )
        meta = mapping(node.outputs, "map_metadata") or mapping(
            node.inputs, "map_metadata"
        )
        if op == "map_figure":
            parameters = meta.get("parameters", {})
            kind = (
                "Kondo"
                if "channel_ids" in parameters
                else "Dyson"
                if "transition_ids" in parameters
                else "Stored orbital"
            )
        comments = {
            "orbital_kind": kind,
            "selection": mapping(node.inputs, "selection"),
            "settings": mapping(node.inputs, "parameters"),
            "map_metadata": meta,
            "figure_settings": mapping(node.inputs, "settings")
            if op == "map_figure"
            else {},
            "storage": "AiiDA repository only; external file contents excluded",
            "source_data_uuids": {
                key: str(node.inputs[key].uuid)
                for key in node.inputs
                if isinstance(node.inputs[key], orm.Data)
            },
        }
        add(
            "spm",
            "SPM_SIMULATION",
            kind + " orbitals / spatial maps",
            spm_mode=["ORBITALS"],
            method_family="CAS" if kind in {"CASSCF", "Dyson", "Kondo"} else "DFT",
            method_label=kind + " orbitals / spatial maps",
            comments=json.dumps(comments, sort_keys=True),
            image_modes=["CONSTANT_HEIGHT"]
            if "maps" in op or op == "map_figure"
            else ["THREE_DIMENSIONAL_GRID"],
        )
    else:
        title = {
            "common_orbitals": "QRO / UNO orbital reference",
            "casscf": "CASSCF optimized orbitals and state energies",
            "casci": "CASCI many-electron states",
            "dyson": "Dyson transition spectrum",
            "kondo": "Kondo exchange channels",
        }[op]
        add(
            "unclassified",
            "UNCLASSIFIED_SIMULATION",
            title,
            method_family="DFT" if op == "common_orbitals" else "CAS",
            method_label=title,
            simulation_description=title
            + ". Structured numerical results and source identities are preserved in the linked AiiDA archive.",
        )
    # A spatial result derives its physical state from stored reference tables.
    # Never assume a neutral singlet merely because the postprocessor has no SCF settings.
    if "charge" not in common:
        charge, mult = electronic_context(node)
        for definition in result.values():
            definition["properties"].update(charge=charge, spin_multiplicity=mult)
    for definition in result.values():
        props = definition["properties"]
        if props.get("method_family") == "DFT" and (
            props.get("spin_multiplicity", 1) > 1
            or electronic.get("reference", "").lower() == "uks"
        ):
            props["method_modifiers"] = ["SPIN_COLLINEAR"]
        if definition["object_type"] == "UNCLASSIFIED_SIMULATION":
            mult = props.pop("spin_multiplicity", None)
            context = {
                "result_kind": op,
                "spin_multiplicity": mult,
                "active_space": mapping(node.inputs, "active_space"),
                "source_data_uuids": {
                    key: str(node.inputs[key].uuid)
                    for key in node.inputs
                    if isinstance(node.inputs[key], orm.Data)
                },
            }
            if op == "casscf":
                table = mapping(node.outputs, "state_energies")
                if table.get("method") != "CASSCF" or not table.get("states"):
                    raise ValueError("Missing stored CASSCF state family.")
                error = _finite(
                    table.get("readback_max_error_hartree"), "CASSCF readback error"
                )
                if not 0 <= error <= 1e-7:
                    raise ValueError("The stored CASSCF readback did not pass.")
                context.update(
                    optimization_mode=settings["mode"],
                    state_objective=settings["states"],
                    readback_max_error_hartree=error,
                    state_energies_uuid=str(node.outputs.state_energies.uuid),
                    optimized_orbital_reference_uuid=str(
                        node.outputs.orbital_reference.uuid
                    ),
                )
            elif op == "optical":
                context.update(
                    method=table["method"],
                    reference_type=table.get("reference_type"),
                    ground_energy_hartree=table.get("ground_energy_hartree"),
                    checks=table.get("checks", {}),
                    excitations_uuid=str(node.outputs.excitations.uuid),
                    nto_weight_convention="Native pseudodensity eigenvalues, not renormalized; full-TDDFT values may exceed one.",
                )
            elif op == "correlation":
                context.update(metadata)
                context["source_orbital_reference_uuid"] = table.get(
                    "source_orbital_reference_uuid"
                )
                context["source_state_energies_uuid"] = table.get(
                    "source_state_energies_uuid"
                )
            props["comments"] = json.dumps(context, sort_keys=True)
        definition["properties"] = {k: v for k, v in props.items() if v is not None}
    return result


def render_preview(source_uuid, role, path):
    """Render only stored arrays or a geometry; never compute a cube or state."""
    import matplotlib.pyplot as plt

    node = orm.load_node(source_uuid)
    op = operation(node)
    if op == "map_figure" and "png" in node.outputs:
        Path(path).write_bytes(
            node.outputs.png.base.repository.get_object_content(
                node.outputs.png.filename, mode="rb"
            )
        )
        return
    figure, axes = plt.subplots(figsize=(6, 4))
    try:
        if role == "pdos":
            arrays = node.outputs.pdos.scf.character
            energies, spin = arrays.get_array("energies_ev"), arrays.get_array("spin")
            for channel in np.unique(spin):
                selected = np.asarray(energies)[spin == channel]
                axes.vlines(
                    selected,
                    0,
                    1,
                    color="#2563b7" if channel == 0 else "#c83e4d",
                    label="alpha" if channel == 0 else "beta",
                )
            axes.set(xlabel="SCF orbital energy (eV)", ylabel="Orbital levels")
            axes.legend()
        elif op == "correlation":
            table = node.outputs.correlation_energies.get_dict()
            states = table["states"]
            if table["method"] == "RI-MP2":
                axes.plot(
                    [0, 1],
                    [0, states[0]["correction_hartree"] * 27.211386245988],
                    "o-",
                    color="#2563b7",
                )
                axes.set_xticks([0, 1], ["HF reference", "RI-MP2"])
                axes.set(
                    ylabel="Energy relative to HF (eV)",
                    title="RI-MP2 energy correction",
                )
            else:
                minimum = min(r["energy_hartree"] for r in states)
                for i, row in enumerate(states):
                    value = (row["energy_hartree"] - minimum) * 27.211386245988
                    axes.hlines(value, i - 0.3, i + 0.3)
                axes.set_xticks(
                    range(len(states)),
                    [f"M={r['multiplicity']} r{r['root']}" for r in states],
                    rotation=30,
                )
                axes.set(
                    ylabel="Energy above lowest computed state (eV)",
                    title=table["method"] + " state energies",
                )
        elif op == "casscf":
            states = node.outputs.state_energies.get_dict()["states"]
            minimum = min(s["energy_hartree"] for s in states)
            multiplicities = sorted({s["multiplicity"] for s in states})
            for state in states:
                index = multiplicities.index(state["multiplicity"])
                energy = (state["energy_hartree"] - minimum) * 27.211386245988
                axes.hlines(energy, index - 0.25, index + 0.25, color=f"C{index % 10}")
            axes.set_xticks(range(len(multiplicities)), multiplicities)
            axes.set(
                xlabel="Multiplicity (2S+1)",
                ylabel="Energy above lowest computed state (eV)",
                title="CASSCF state energies",
            )
        elif op == "casci":
            states = node.outputs.state_energies.get_dict()["states"]
            values = np.array([s["energy_hartree"] for s in states])
            for i, value in enumerate((values - values.min()) * 27.211386245988):
                axes.hlines(value, i - 0.3, i + 0.3)
            axes.set(
                xlabel="Root index", ylabel="Energy above lowest computed root (eV)"
            )
        elif (
            op == "common_orbitals"
            and "pdos" in node.outputs
            and "uno" in node.outputs.pdos
        ):
            arrays = node.outputs.pdos.uno.character
            axes.scatter(arrays.get_array("indices"), arrays.get_array("occupations"))
            axes.set(
                xlabel="ORCA orbital index (starts at 0)",
                ylabel="UNO occupation",
                title="Stored unrestricted natural-orbital occupations",
            )
        elif op == "dyson":
            table = node.outputs.transitions.get_dict()
            for side, color in (("removal", "#2563b7"), ("addition", "#c83e4d")):
                rows = [row for row in table["transitions"] if row["side"] == side]
                axes.vlines(
                    [row["energy_ev"] for row in rows],
                    0,
                    [row["strength"] for row in rows],
                    color=color,
                    label=side,
                )
            axes.legend()
            axes.set(
                xlabel="Stored transition energy (eV)",
                ylabel="Stored transition strength",
                title="Dyson transitions · stored spin convention",
            )
        elif op in {"dyson_maps", "kondo_maps"}:
            data = node.outputs.maps
            intensity = data.get_array("intensity")
            if intensity.ndim != 4:
                raise ValueError("Unexpected stored map dimensions.")
            image = axes.imshow(
                intensity[0, 0],
                origin="lower",
                cmap="magma",
                vmin=0,
                vmax=float(intensity.max()),
            )
            figure.colorbar(image, ax=axes, label="Stored intensity")
            axes.set_title(
                "First stored map · height "
                + str(data.get_array("heights_angstrom")[0])
                + " Å"
            )
            axes.set(xlabel="Plane grid index u", ylabel="Plane grid index v")
        elif op == "optical":
            states = node.outputs.excitations.get_dict()["states"]
            for family in sorted({r["family"] for r in states}):
                rows = [r for r in states if r["family"] == family]
                axes.vlines(
                    [r["energy_ev"] for r in rows],
                    0,
                    [r["oscillator_strength"] for r in rows],
                    label=family,
                )
                axes.scatter([r["energy_ev"] for r in rows], [0] * len(rows), s=10)
            axes.set(
                xlabel="Vertical excitation energy (eV)",
                ylabel="Oscillator strength · length gauge",
                title="Stored optical states · dark roots retained",
            )
            axes.legend()
        elif op == "vibrations":
            arrays = node.outputs.vibrational_data
            axes.vlines(
                arrays.get_array("frequencies"),
                0,
                arrays.get_array("ir_intensities"),
                color="#2563b7",
            )
            axes.set(
                xlabel="Wavenumber (cm⁻¹)",
                ylabel="IR intensity (km/mol)",
                title="Stored harmonic IR modes",
            )
        elif op == "kondo":
            channels = node.outputs.channels.get_dict()["channels"]
            axes.bar(
                [row["id"] for row in channels],
                [row["exchange_over_v2_inv_ev"] for row in channels],
            )
            axes.set(ylabel="J/V² (eV⁻¹)", title="Stored Kondo exchange channels")
        else:
            from ase.visualize.plot import plot_atoms

            plot_atoms(
                orm.load_node(structure_uuid(node)).get_ase(),
                ax=axes,
                rotation="15x,15y",
            )
            axes.set_axis_off()
            axes.set_title(
                "Geometry preview"
                if op in {"geometry", "reference"}
                else "Geometry preview · numerical results in archive"
            )
        figure.tight_layout()
        figure.savefig(path, dpi=120)
    finally:
        plt.close(figure)


def inventory(source_uuid):
    """JSON-safe local inventory, including call-tree data and external references."""
    root = orm.load_node(source_uuid)
    operation(root)
    processes = [str(root.uuid), *[str(n.uuid) for n in root.called_descendants]]
    stored, external, seen = [], [], set()
    for uid in processes:
        node = orm.load_node(uid)
        for item in [node, *data_nodes(node.inputs), *data_nodes(node.outputs)]:
            identity = str(item.uuid)
            if identity in seen:
                continue
            seen.add(identity)
            if isinstance(item, (orm.RemoteData, orm.RemoteStashData)):
                external.append(
                    {
                        "uuid": identity,
                        "type": item.node_type,
                        "contents_included": False,
                    }
                )
                continue
            for directory, _, files in item.base.repository.walk():
                for name in files:
                    filename = str(Path(directory) / name)
                    stored.append({"uuid": identity, "filename": filename})
    return {
        "source_uuid": str(root.uuid),
        "structure_uuid": structure_uuid(root),
        "results": definitions(root),
        "stored_files": stored,
        "external_references": external,
        "policy": "Only data already stored in AiiDA; no remote retrieval, stashing or calculation.",
    }


def related_results(source_uuid):
    """Follow stored forward links at the selected geometry; return plain IDs."""
    target = structure_uuid(orm.load_node(source_uuid))
    pending, seen, results = [str(source_uuid)], set(), []
    while pending:
        uid = pending.pop()
        if uid in seen:
            continue
        seen.add(uid)
        node = orm.load_node(uid)
        if supported(node) and node.is_finished_ok:
            try:
                if structure_uuid(node) != target:
                    continue
            except ValueError:
                continue
            results.append(
                {
                    "uuid": str(node.uuid),
                    "label": node.label or node.process_label,
                    "process_label": node.process_label,
                    "title": RESULT_TITLES[operation(node)],
                    "created": node.ctime.isoformat(),
                }
            )
        if isinstance(node, orm.ProcessNode):
            pending.extend(str(n.uuid) for n in data_nodes(node.outputs))
            pending.extend(str(n.uuid) for n in node.called)
        elif isinstance(node, orm.Data):
            pending.extend(
                str(link.node.uuid)
                for link in node.base.links.get_outgoing().all()
                if isinstance(link.node, orm.ProcessNode)
            )
    return sorted(results, key=lambda row: (row["created"], row["uuid"]))
