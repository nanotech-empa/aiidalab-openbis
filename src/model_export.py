"""Adapters for stored tight-binding, spin and Hubbard results.

Abstract graph models have no fabricated atomistic geometry or ionic charge.
Magnetic spectra and Wannier Hamiltonians are not electronic DOS or cube grids.
"""

import io
import json

import numpy as np
from aiida import orm


SNAPSHOT_TYPE = "aiida_openbis.snapshots.record_model_result"
PROCESS_TYPES = {
    SNAPSHOT_TYPE: "record_model_result",
    "aiida.workflows:itensor_spin.full": "SpinChainWorkChain",
    "aiida.workflows:itensor_spin.sector_ensemble": "SpinSectorEnsembleWorkChain",
    "aiida.workflows:itensor_spin.spectra": "SpinSpectraWorkChain",
    "aiida.workflows:itensor_spin.spectra_adaptive": "AdaptiveSpinSpectraWorkChain",
    "aiida.workflows:itensor_spin.spectra_restart": "SpinSpectraRestartWorkChain",
    "aiida.calculations:itensor_spin.ground_state": "GroundStateCalculation",
}
LABELS = set(PROCESS_TYPES.values())


def supported(node):
    return getattr(node, "process_type", "") in PROCESS_TYPES


def structures(node, role):
    structure = node.inputs.structure if "structure" in node.inputs else None
    return (
        [str(structure.uuid)] if isinstance(structure, orm.StructureData) else []
    ), []


def definitions(node):
    if not supported(node) or not node.is_finished_ok:
        raise ValueError("Select a completed supported model result.")
    common = {
        "name": node.label or node.process_label,
        "aiida_source_uuid": str(node.uuid),
    }
    result = {}

    def add(role, type_code, title, **props):
        result[role] = {
            "object_type": type_code,
            "title": title,
            "properties": dict(common, **props),
        }

    if node.process_type != SNAPSHOT_TYPE:
        if not list(node.outputs):
            raise ValueError("The model workflow has no stored results.")
        # Completion is not a proof of DMRG or dynamical-response convergence.
        add(
            "model_results",
            "MODEL_HAMILTONIAN",
            "Spin Hamiltonian energies and spectra",
            model="Spin Hamiltonian",
            method_family="DMRG",
            method_label="ITensor DMRG / dynamical spin response",
            converged=False,
            simulation_description="Stored spin-model inputs, sector-resolved energies, response spectra and diagnostics. Energies/frequencies in meV. Fixed Sz is not total S; completion does not establish convergence.",
            comments=json.dumps(
                {
                    "result_kind": "itensor_spin",
                    "energy_unit": "meV",
                    "geometry": "Abstract spin model; no atomistic model inferred.",
                    "outputs": sorted(node.outputs),
                    "external_files": "References only; no checkpoint retrieval.",
                },
                sort_keys=True,
            ),
        )
        return result

    payload = node.outputs.metadata.get_dict()
    if payload.get("snapshot_schema") != 1:
        raise ValueError("Unsupported recorded-result format.")
    kind = payload["kind"]
    common["name"] = payload.get("title", common["name"])
    common["comments"] = json.dumps(
        {
            "provenance": payload["provenance"],
            "result_kind": kind,
            "snapshot_sha256": payload["snapshot_sha256"],
            "units": payload.get("units", {}),
            "energy_reference": payload.get("energy_reference"),
            "software": payload.get("software", {}),
        },
        sort_keys=True,
    )
    if kind == "pythtb":
        family = "MFH_TB" if payload["hubbard_u_ev"] is not None else "TB"
        common.update(
            method_family=family,
            method_label="PythTB pi-orbital model",
            converged=payload["converged"],
            charge=0,
        )
        if payload["periodic"]:
            add(
                "bands",
                "BAND_STRUCTURE",
                "Tight-binding bands",
                k_path=payload.get("k_path", ""),
            )
        else:
            add(
                "levels",
                "MODEL_HAMILTONIAN",
                "Finite tight-binding levels",
                model="Hubbard Hamiltonian"
                if family == "MFH_TB"
                else "Tight-binding Hamiltonian",
                simulation_description="Stored one-electron levels and eigenvectors; these eigenvalues are not a total many-electron energy.",
            )
        if family == "MFH_TB":
            add(
                "charge",
                "CHARGE_ANALYSIS",
                "Mean-field site charge and spin",
                charge_analysis_method="Pi-orbital occupations from the stored mean-field solution",
            )
        if payload.get("wannier") and payload["periodic"]:
            add(
                "wannier",
                "MODEL_HAMILTONIAN",
                "Wannier Hamiltonians and orbitals",
                model="Wannier Hamiltonian",
                simulation_description="Full and simplified Wannier Hamiltonians, complex orbital coefficients, centers, spreads and validation. Both R and -R are retained; no effective Hubbard interaction is inferred.",
            )
        elif payload.get("wannier"):
            result["levels"]["properties"]["simulation_description"] += (
                " Includes full and simplified Wannier Hamiltonians, orbitals, centers, spreads and validation."
            )
    elif kind in {"spin_graph", "hubbard"}:
        family = "DMRG" if payload["solver"] == "DMRG" else "ED"
        common.update(
            method_family=family,
            method_label=payload["solver"] + " / " + kind,
            converged=payload["converged"],
        )
        add(
            "model_results",
            "MODEL_HAMILTONIAN",
            payload["title"],
            model="Spin Hamiltonian" if kind == "spin_graph" else "Hubbard Hamiltonian",
            simulation_description="Complete stored model and results, including all selected sectors and diagnostics. ED ground-manifold averages and single DMRG candidates retain their original meaning; fixed Sz is not total S.",
        )
    else:
        raise ValueError("Unsupported recorded model kind.")
    return result


def render_preview(source_uuid, role, path):
    import matplotlib.pyplot as plt

    node = orm.load_node(source_uuid)
    if node.process_type == SNAPSHOT_TYPE:
        payload = node.outputs.metadata.get_dict()
        if payload.get("kind") in {"spin_graph", "hubbard"}:
            from .model_previews import figure

            fig = figure(payload)
            try:
                fig.savefig(path, dpi=150)
            finally:
                plt.close(fig)
                del node
            return
    if node.process_type != SNAPSHOT_TYPE:
        from .model_previews import figure

        metadata = {}
        for namespace, name in (
            (node.inputs, "parameters"),
            (node.inputs, "ground_state_metadata"),
            (node.outputs, "ground_state_metadata"),
        ):
            if name in namespace and isinstance(namespace[name], orm.Dict):
                metadata.update(namespace[name].get_dict())
        graph = metadata.get("spin_graph", {})
        if not graph and metadata.get("site_spins"):
            spins = metadata["site_spins"]
            couplings = metadata.get("couplings_meV", [])
            # Only the named open-chain contract permits sequential edges.
            if (
                metadata.get("model") == "mixed_spin_heisenberg_chain_v1"
                and len(couplings) == len(spins) - 1
            ):
                graph = {
                    "site_spins": spins,
                    "exchange_edges": [
                        {"i": i, "j": i + 1, "J_meV": value}
                        for i, value in enumerate(couplings, 1)
                    ],
                    "site_positions": [[i, 0] for i in range(len(spins))],
                }
        payload = {
            "kind": "spin_graph",
            "title": "Stored spin Hamiltonian / DMRG",
            "units": {"energy": "meV"},
            "results": [
                {"graph": graph, "energy_meV": metadata.get("ground_energy_meV")}
            ],
        }
        fig = figure(payload)
        try:
            fig.savefig(path, dpi=150)
        finally:
            plt.close(fig)
            del node
        return
    fig, ax = plt.subplots(figsize=(6, 4))
    try:
        if node.process_type == SNAPSHOT_TYPE:
            payload = node.outputs.metadata.get_dict()
            with node.outputs.result.base.repository.open("arrays.npz", "rb") as handle:
                arrays = np.load(io.BytesIO(handle.read()), allow_pickle=False)
            with arrays:
                if role in {"bands", "levels", "wannier"}:
                    for key in sorted(arrays.files):
                        if key.startswith("energies_"):
                            values = arrays[key]
                            if role in {"bands", "wannier"}:
                                ax.plot(arrays["k_distance"], values)
                            else:
                                ax.scatter(np.arange(values.size), values.ravel())
                    ax.set(
                        xlabel="Path distance"
                        if role in {"bands", "wannier"}
                        else "Level index",
                        ylabel="Raw energy (eV)",
                    )
                elif role == "charge":
                    ax.plot(arrays["n_up"], "o-", label="up")
                    ax.plot(arrays["n_dn"], "o-", label="down")
                    ax.set(xlabel="Carbon model site", ylabel="Occupation")
                    ax.legend()
                else:
                    ax.text(
                        0.5,
                        0.5,
                        "Stored model, numerical results\nand diagnostics in the AiiDA archive",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                    ax.set_axis_off()
            ax.set_title(payload["title"])
        else:
            ax.text(
                0.5,
                0.5,
                "Spin Hamiltonian energies / spectra\nStored sector results and diagnostics\nEnergy and frequency: meV",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
    finally:
        plt.close(fig)
