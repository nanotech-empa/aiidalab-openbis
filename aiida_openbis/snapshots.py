"""Record existing local results, without claiming AiiDA ran their solver.

Only this recording operation is an AiiDA calculation. The supplied numerical
results are immutable inputs, with their original solver metadata and units.
No scientific calculation, remote retrieval or openBIS write occurs here.
"""

import hashlib
import asyncio
import io
import json
import re

import numpy as np
from aiida import orm
from aiida.engine import calcfunction, run_get_node


def run_recording_callback(callback):
    """Run a widget callback on the notebook thread with AiiDA's async bridge.

    Widget messages do not inherit the portal established for notebook cells.
    Return the task to its widget owner; do not move ORM work to another thread.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return callback()
    from plumpy.greenback_bridge import run_with_portal

    return loop.create_task(run_with_portal(callback))


@calcfunction
def record_model_result(payload, data, structure=None):
    """Preserve a local result bundle as a single, importable provenance root."""
    return {"metadata": payload.clone(), "result": data.clone()}


def save_snapshot(payload, arrays=None, files=None, atoms=None):
    """Return a UUID, reusing an identical recorded result in this profile.

    Call on the notebook thread. Arguments contain plain data, never live ORM
    objects. File values are bytes, not paths to files that might be remote.
    """
    from aiida import load_profile

    load_profile()
    payload = json.loads(json.dumps(payload, allow_nan=False))
    if payload.get("kind") not in {"pythtb", "spin_graph", "hubbard"}:
        raise ValueError("Unsupported local model result.")
    payload.update(
        snapshot_schema=1,
        provenance="Recorded existing local result; solver ran outside AiiDA.",
    )
    arrays = {key: np.asarray(value) for key, value in (arrays or {}).items()}
    files = dict(files or {})
    for key, value in arrays.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
            raise ValueError("Invalid array name.")
        if value.dtype.kind not in "biufc" or not np.isfinite(value).all():
            raise ValueError("Result arrays must be finite numerical arrays.")
    for key, value in files.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", key) or not isinstance(
            value, bytes
        ):
            raise ValueError("Attachments require a simple filename and bytes.")
        if key == "arrays.npz":
            raise ValueError(
                "The filename arrays.npz is reserved for numerical results."
            )
    if atoms is not None:
        # No geometry inference: record the exact structure used by the app.
        payload["structure"] = {
            "symbols": atoms.get_chemical_symbols(),
            "positions": atoms.positions.tolist(),
            "cell": atoms.cell.array.tolist(),
            "pbc": atoms.pbc.tolist(),
        }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    )
    for key, value in sorted(arrays.items()):
        stream = io.BytesIO()
        np.save(stream, value, allow_pickle=False)
        digest.update(key.encode() + b"\0" + stream.getvalue())
    for key, value in sorted(files.items()):
        digest.update(key.encode() + b"\0" + value)
    payload["snapshot_sha256"] = digest.hexdigest()
    matches = (
        orm.QueryBuilder()
        .append(
            orm.CalcFunctionNode,
            filters={
                "process_type": "aiida_openbis.snapshots.record_model_result",
                "attributes.process_state": "finished",
                "attributes.exit_status": 0,
            },
            tag="record",
            project="uuid",
        )
        .append(
            orm.Dict,
            with_incoming="record",
            edge_filters={"label": "metadata"},
            filters={"attributes.snapshot_sha256": payload["snapshot_sha256"]},
            project=[],
        )
        .all(flat=True)
    )
    if matches:
        return str(sorted(matches)[0])
    bundle = orm.FolderData()
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    bundle.put_object_from_filelike(io.BytesIO(buffer.getvalue()), "arrays.npz")
    for name, content in files.items():
        bundle.put_object_from_filelike(io.BytesIO(content), name)
    kwargs = {"payload": orm.Dict(dict=payload), "data": bundle}
    if atoms is not None:
        kwargs["structure"] = orm.StructureData(ase=atoms)
    _, process = run_get_node(record_model_result, **kwargs)
    return str(process.uuid)
