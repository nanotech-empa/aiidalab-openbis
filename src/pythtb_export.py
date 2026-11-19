"""Export native PythTB results already stored in AiiDA, without a solver or transport.

The app/worker is not needed to read an archive. Orbital jobs belong to one
model only when both immutable reference inputs match that model's outputs.
"""

import hashlib
import json
import shutil
import tempfile

import numpy as np
from aiida import orm

PROCESS_TYPE = "aiida.calculations:empa_tb.calculate"
PROCESS_TYPES = {PROCESS_TYPE: "PythtbCalculation"}
LABELS = set(PROCESS_TYPES.values())
PROTOCOL = "empa-pythtb/v1"


def supported(node):
    return getattr(node, "process_type", "") == PROCESS_TYPE


def export_ready(node):
    return (supported(node) and node.is_terminated
            and node.process_state.value == "finished" and node.exit_status in (0, 302))


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _stored(node, with_arrays=False):
    if not export_ready(node):
        raise ValueError("Select a finished native PythTB result with stored output.")
    request = node.inputs.request.get_dict()
    summary = node.outputs.summary.get_dict()
    if (request.get("protocol") != PROTOCOL or summary.get("protocol") != PROTOCOL
            or summary.get("request_sha256") != _digest(request)
            or summary.get("engine_sha256") != request.get("engine_sha256")):
        raise ValueError("The stored PythTB output does not match its native request.")
    operation = request.get("operation", "solve")
    if operation not in {"solve", "orbital", "wannier"} or summary.get("operation", "solve") != operation:
        raise ValueError("Unsupported or inconsistent stored PythTB operation.")
    if operation == "orbital" and (
            summary.get("reference_uuid") != request.get("reference_uuid")
            or summary.get("orbital_selection") != {"band_index": request["band_index"], "k_index": request["k_index"]}
            or summary.get("reused_mean_field") is not True):
        raise ValueError("The stored orbital selection/reference does not match its request.")
    mf = summary.get("mf")
    mf_converged = mf is None or bool(mf.get("converged", False))
    converged = mf_converged
    if operation == "wannier":
        info = summary.get("wannier", {})
        if (summary.get("reference_uuid") != request.get("reference_uuid")
                or summary.get("reused_mean_field") is not True
                or summary.get("postprocess_engine_sha256") != request.get("postprocess_engine_sha256")
                or info.get("settings") != request.get("wannier_settings")
                or not info.get("channels") or not mf_converged):
            raise ValueError("The stored Wannier result does not match its frozen model/settings.")
        converged = all(channel.get("localization_converged") is True
                        and channel.get("disentanglement_converged") is not False
                        for channel in info["channels"].values())
        if converged != info.get("converged"):
            raise ValueError("The stored Wannier convergence diagnostics disagree.")
    if ((summary.get("status") == "completed") != converged
            or node.exit_status != (0 if converged else 302)):
        raise ValueError("The native status and convergence evidence disagree.")
    if mf is not None:
        residual, tolerance = float(mf["density_change"]), float(mf["tolerance"])
        if not np.isfinite([residual, tolerance]).all() or residual < 0 or tolerance <= 0:
            raise ValueError("Missing or nonfinite native SCF convergence diagnostics.")
        if mf_converged and residual >= tolerance:
            raise ValueError("The native SCF residual does not meet its stored tolerance.")
    arrays = None
    # Repository handles can be packed/non-seekable. Copy to a bounded disk stream;
    # never access the remote work directory or evaluate a Hamiltonian.
    with tempfile.TemporaryFile() as target:
        with node.outputs.retrieved.base.repository.open("result.npz", "rb") as stream:
            shutil.copyfileobj(stream, target, length=1024 * 1024)
        target.seek(0)
        with np.load(target, allow_pickle=False) as stored:
            native = json.loads(str(stored["summary"]))
            for key in ("protocol", "request_sha256", "engine_sha256", "status", "operation", "reference_uuid", "postprocess_engine_sha256"):
                if native.get(key) != summary.get(key):
                    raise ValueError("The retrieved PythTB manifest does not match its parsed output.")
            if operation == "wannier":
                # AiiDA normalizes attribute floats; the immutable NPZ retains
                # the original precision. Compare exact identity/decisions,
                # rather than rejecting harmless numeric serialization changes.
                raw_info = native["wannier"]
                if (raw_info["settings"] != request["wannier_settings"]
                        or raw_info["converged"] != summary["wannier"]["converged"]
                        or set(raw_info["channels"]) != set(summary["wannier"]["channels"])
                        or any(raw_info["channels"][spin].get(key) != parsed.get(key)
                               for spin, parsed in summary["wannier"]["channels"].items()
                               for key in ("localization_converged", "disentanglement_converged"))):
                    raise ValueError("The retrieved Wannier settings/convergence differ from the parsed result.")
            summary = native
            if with_arrays:
                arrays = {key: stored[key].copy() for key in stored.files if key != "summary"}
                if any(value.dtype.kind not in "biufc" or not np.isfinite(value).all()
                       for value in arrays.values()):
                    raise ValueError("Native result arrays must be finite numerical data.")
    return request, summary, arrays


def _parent(node, request):
    """Load for this operation only; never cache or share the ORM node."""
    if (node.inputs.reference_request.get_dict() != request.get("base_request")
            or request.get("base_request_sha256") != _digest(request["base_request"])):
        raise ValueError("The orbital reference request identity does not match.")
    with tempfile.TemporaryFile() as target:
        with node.inputs.reference_result.base.repository.open("result.npz", "rb") as stream:
            shutil.copyfileobj(stream, target, length=1024 * 1024)
        target.seek(0)
        with np.load(target, allow_pickle=False) as stored:
            reference = json.loads(str(stored["summary"]))
    if (reference.get("request_sha256") != request["base_request_sha256"]
            or reference.get("engine_sha256") != request["engine_sha256"]
            or reference.get("protocol") != PROTOCOL):
        raise ValueError("The stored orbital reference result identity does not match.")
    matches = (orm.QueryBuilder(backend=node.backend).append(
        orm.CalcJobNode, filters={"uuid": request["reference_uuid"]}).all(flat=True))
    if not matches:
        # Single-root orbital archives retain frozen request/result inputs,
        # not another main process. Preserve the recorded reference UUID;
        # never fetch or invent its missing process/link.
        return None
    parent = matches[0]
    if (not export_ready(parent)
            or parent.inputs.request.get_dict().get("operation", "solve") != "solve"
            or node.inputs.reference_result.uuid != parent.outputs.retrieved.uuid
            or node.inputs.reference_request.uuid != parent.inputs.request.uuid
            or request.get("base_request") != parent.inputs.request.get_dict()
            or request.get("base_request_sha256") != _digest(request["base_request"])):
        raise ValueError("The orbital has no exact stored model/reference provenance.")
    return parent


def _context(node):
    request, summary, _ = _stored(node)
    if request.get("operation", "solve") in {"orbital", "wannier"}:
        parent = _parent(node, request)
        base = _stored(parent)[0] if parent is not None else request["base_request"]
        model_uuid = request["reference_uuid"]
        parent_present = parent is not None
    else:
        base, model_uuid, parent_present = request, str(node.uuid), True
    return request, base, summary, model_uuid, parent_present


def structures(node, role):
    request, base, _, _, _ = _context(node)
    source = node.inputs.source_structure if "source_structure" in node.inputs else None
    if source is not None:
        if not isinstance(source, orm.StructureData) or str(source.uuid) != base.get("source_structure_uuid"):
            raise ValueError("The native structure input does not match its recorded identity.")
        return [str(source.uuid)], []
    if base.get("source_structure_uuid"):
        raise ValueError("The recorded source structure has no matching native input link.")
    # Unsaved input geometry is still fully recorded in request.atoms. Do not
    # invent a StructureData or retrofit a provenance link during export.
    return [], []


def definitions(node):
    request, base, summary, model_uuid, parent_present = _context(node)
    orbital = request.get("operation", "solve") == "orbital"
    wannier = request.get("operation") == "wannier"
    mf = summary.get("mf")
    computer = node.inputs.code.computer
    comments = {
        "result_kind": "pythtb_native",
        "provenance": "Native AiiDA CalcJob; results read from stored retrieved data.",
        "model_source_uuid": model_uuid,
        "model_process_present": parent_present,
        "request_sha256": summary["request_sha256"],
        "worker_engine_sha256": summary["engine_sha256"],
        "worker_protocol": summary["protocol"],
        "code_uuid": str(node.inputs.code.uuid),
        "computer_uuid": str(computer.uuid) if computer else None,
        "computer_label": computer.label if computer else None,
        "units": {"energies": "eV", "positions": "angstrom"},
        "energy_reference": "Raw Hamiltonian eigenvalues; not an ab-initio total energy. Display offsets are separate.",
        "effective_model_geometry": base["atoms"],
        "input_structure_uuid": base.get("source_structure_uuid"),
        "model": {key: base.get(key) for key in
                  ("hoppings", "U", "shell_tol", "distance_tol", "scf_tol", "scf_max_iter", "k_path", "n_kpts")},
        "mean_field": mf,
        "native_exit_status": node.exit_status,
    }
    if orbital:
        comments.update(orbital_selection=summary["orbital_selection"],
                        frozen_model_reused=bool(summary.get("reused_mean_field")))
    if wannier:
        comments.update(wannier=summary["wannier"],
                        postprocess_engine_sha256=summary["postprocess_engine_sha256"],
                        frozen_model_reused=True,
                        energy_reference=summary["wannier"]["settings"]["energy_label"])
    common = {
        "name": node.label or ("PythTB orbital" if orbital else "PythTB model"),
        "aiida_source_uuid": str(node.uuid),
        "method_family": "MFH_TB" if base.get("U") is not None else "TB",
        "method_label": "PythTB pi-orbital model / native AiiDA",
        # The protocol implements neutral half filling; this is the charge
        # relative to that pi model, not an inferred ionic/ab-initio charge.
        "charge": 0,
        "converged": summary["status"] == "completed",
        "comments": json.dumps(comments, sort_keys=True, allow_nan=False),
    }
    result = {}

    def add(role, type_code, title, **properties):
        result[role] = {"object_type": type_code, "title": title,
                        "properties": dict(common, **properties)}

    if orbital:
        add("orbitals", "MODEL_HAMILTONIAN", "Frozen-model orbital coefficients",
            model="Hubbard Hamiltonian" if base.get("U") is not None else "Tight-binding Hamiltonian",
            simulation_description="Selected zero-based band/k-point coefficients from the saved TB/MFH model; no repeated SCF. These are site amplitudes, not volumetric cube data.")
    elif wannier:
        add("wannier", "MODEL_HAMILTONIAN", "Native Wannier reduced Hamiltonian",
            model="Wannier Hamiltonian",
            simulation_description="Native localization of the frozen TB/MFH model; stored coefficients, centers, hopping matrices, validation bands and ZIP. No repeated mean-field calculation.")
    elif any(base["atoms"]["pbc"]):
        add("bands", "BAND_STRUCTURE", "Native tight-binding bands", k_path=base.get("k_path", ""))
    else:
        add("levels", "MODEL_HAMILTONIAN", "Native finite tight-binding levels",
            model="Hubbard Hamiltonian" if base.get("U") is not None else "Tight-binding Hamiltonian",
            simulation_description="Stored one-electron levels, hopping graph, model inputs and diagnostics. Eigenvalues and the mean-field energy proxy are not ab-initio total energies.")
    if mf is not None and not orbital and not wannier:
        add("charge", "CHARGE_ANALYSIS", "Native mean-field site charge and spin",
            charge_analysis_method="Pi-orbital occupations from the saved native mean-field solution")
    return result


def related_results(source_uuid):
    """One native model plus its exact referenced orbital jobs, never same-formula matches."""
    node = orm.load_node(source_uuid)
    request, _, _ = _stored(node)
    if request.get("operation", "solve") in {"orbital", "wannier"}:
        parent = _parent(node, request)
        if parent is None:
            return [{"uuid": str(node.uuid), "label": node.label or node.process_label,
                     "process_label": node.process_label, "title": "PythTB derived result; frozen model inputs retained",
                     "created": node.ctime.isoformat()}]
        node = parent
    model_uuid, retrieved_uuid = str(node.uuid), str(node.outputs.retrieved.uuid)
    result = [{"uuid": model_uuid, "label": node.label or node.process_label,
               "process_label": node.process_label, "title": "PythTB model and bands",
               "created": node.ctime.isoformat()}]
    candidates = (orm.QueryBuilder(backend=node.backend)
        .append(orm.FolderData, filters={"uuid": retrieved_uuid}, tag="reference")
        .append(orm.CalcJobNode, with_incoming="reference", edge_filters={"label": "reference_result"},
                filters={"process_type": PROCESS_TYPE}))
    for (child,) in candidates.all():
        if not export_ready(child):
            continue
        child_request, _, _ = _stored(child)
        parent = _parent(child, child_request)
        if str(parent.uuid) != model_uuid:
            raise ValueError("Ambiguous native orbital model identity.")
        result.append({"uuid": str(child.uuid), "label": child.label or child.process_label,
                       "process_label": child.process_label, "title": "PythTB Wannier model" if child_request.get("operation") == "wannier" else "PythTB frozen-model orbital",
                       "created": child.ctime.isoformat()})
    return sorted({item["uuid"]: item for item in result}.values(), key=lambda item: (item["created"], item["uuid"]))


def render_preview(source_uuid, role, path):
    import matplotlib.pyplot as plt

    node = orm.load_node(source_uuid)
    request, summary, arrays = _stored(node, with_arrays=True)
    base = request.get("base_request", request)
    figure, ax = plt.subplots(figsize=(6, 4))
    try:
        if role in {"bands", "levels"}:
            channels = [("up", arrays["energies_up"]), ("down", arrays["energies_down"])] if summary.get("spinful") else [("TB", arrays["band_energies"])]
            for name, values in channels:
                if role == "bands":
                    values = np.asarray(values)
                    x = arrays["k_dist"]
                    if values.shape[0] != len(x):
                        raise ValueError("Stored band path/array dimensions disagree.")
                    for index in range(values.shape[1]):
                        ax.plot(x, values[:, index], label=name if index == 0 else None)
                else:
                    values = np.ravel(values)
                    ax.scatter(np.arange(len(values)), values, label=name)
            ax.set(xlabel="Stored path distance" if role == "bands" else "Level index", ylabel="Raw energy (eV)")
            if role == "bands":
                for x in arrays["k_node"]:
                    ax.axvline(x, color="0.8", linewidth=0.8)
                ax.set_xticks(arrays["k_node"], summary["k_labels"])
            ax.legend()
        elif role == "wannier":
            info = summary["wannier"]
            for spin in info["channels"]:
                prefix = "wannier_" + spin + "_"
                x = arrays[prefix + "check_k"].ravel()
                for index, band in enumerate(arrays[prefix + "simplified_bands"].T):
                    ax.plot(x, band, label=spin if index == 0 else None)
            ax.set(xlabel="Reduced k", ylabel=info["settings"]["energy_label"],
                   title="Stored Wannier model · cutoff " + str(info["settings"]["cutoff_ev"]) + " eV")
            ax.legend()
        elif role == "charge":
            ax.plot(arrays["mf_n_up"], "o-", label="up")
            ax.plot(arrays["mf_n_dn"], "o-", label="down")
            ax.set(xlabel="Carbon model site", ylabel="Occupation")
            ax.legend()
        elif role == "orbitals":
            vector = arrays["orbital_vector"]
            weights = np.abs(vector) ** 2
            if weights.ndim == 2:
                ax.plot(weights[:, 0], "o-", label="up")
                ax.plot(weights[:, 1], "o-", label="down")
                ax.legend()
            else:
                ax.plot(weights, "o-")
            ax.set(xlabel="Carbon model site", ylabel="Site probability")
            selection = summary["orbital_selection"]
            ax.set_title(f"Orbital {selection['band_index']} · k index {selection['k_index']}")
        else:
            raise ValueError("Unknown native PythTB result role.")
        if not (summary.get("mf") is None or summary["mf"]["converged"]):
            figure.suptitle("Unconverged MFH · provisional result")
        figure.tight_layout()
        figure.savefig(path, dpi=150)
    finally:
        plt.close(figure)
