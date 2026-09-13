"""Read-only completion checks for AiiDA simulation export results.

Completion is reconstructed from server objects and published dataset inventories,
not from local extras or a new openBIS schema flag. These checks do not compare
archived extras with live extras: older annotations never invalidate an archive.
"""

import tempfile
from pathlib import Path

from .export_recovery import (
    ExportCheck,
    ExportReport,
    has_archive,
    has_preview,
    missing_files,
)


def _structures(workchain, role, au):
    """Describe structure links already created by the existing exporters."""
    label = workchain.process_label
    if role == "minimum_energy_path":
        if label == "Cp2kReplicaWorkChain":
            _, _, start, end = au._replica_chain_profile(workchain)
        else:
            start, end = au._neb_input_endpoints(workchain)
        return [start, end], []
    output = None
    if label == "NanoribbonWorkChain":
        cell_opt = au._find_nanoribbon_calculations(workchain)["cell_opt2"]
        if cell_opt is not None:
            output = cell_opt.outputs.output_structure
    elif role == "geometry_optimization" or (
        role == "charge_analysis" and label == "Cp2kGeoOptWorkChain"
    ):
        output = workchain.outputs.output_structure
    if role == "geometry_optimization":
        return [workchain.inputs.structure], [output] if output is not None else []
    return [output if output is not None else workchain.inputs.structure], []


def _linked_ids(session, obj, direction):
    # Use fresh relationship queries, not the potentially cached parent list.
    getter = getattr(obj, "get_" + direction)
    return {
        str(item.permId if hasattr(item, "permId") else session.get_object(item).permId)
        for item in getter()
    }


def inspect_result(session, workchain, role, obj, definitions, au=None):
    """Check one result, including archive, models, links and compact attachments."""
    if au is None:
        from . import aiida_utils as au
    report = ExportReport()
    key = f"{workchain.uuid}:{role}"
    label = role.replace("_", " ").capitalize()
    report.add(key + "/object", label, obj is not None)
    if obj is None:
        return report
    try:
        archive_ref = au._object_reference_id(au._openbis_property(obj, "aiida_node"))
        archive = session.get_object(archive_ref) if archive_ref else None
        report.add(
            key + "/archive",
            label + ": AiiDA archive",
            archive is not None and has_archive(archive),
            "A valid archive remains reusable even when its extras are older.",
        )
        report.add(
            key + "/preview", label + ": ELN preview", has_preview(obj), blocking=False
        )
        parents = _linked_ids(session, obj, "parents")
        children = _linked_ids(session, obj, "children")
        model_type = au.OPENBIS_OBJECT_TYPES["Atomistic Model"]
        parent_structures, child_structures = _structures(workchain, role, au)
        for direction, structures in (
            ("parents", parent_structures),
            ("children", child_structures),
        ):
            for structure in structures:
                model_key = key + "/" + direction + "/" + str(structure.uuid)
                models = au._objects_by_property(
                    session, model_type, "WFMS_UUID", structure.uuid
                )
                if len(models) > 1:
                    raise ValueError(
                        f"Multiple atomistic models reference {structure.uuid}."
                    )
                model = models[0] if models else None
                linked = parents if direction == "parents" else children
                report.add(
                    model_key,
                    label + ": " + direction.rstrip("s") + " structure",
                    model is not None and str(model.permId) in linked,
                )
                if model is not None:
                    report.add(
                        model_key + "/data",
                        "Atomistic model: structure data",
                        au._has_structure_data(model),
                    )
                    report.add(
                        model_key + "/preview",
                        "Atomistic model: ELN preview",
                        has_preview(model),
                        blocking=False,
                    )

        parent_role = None
        if role == "charge_analysis":
            parent_role = (
                "geometry_optimization"
                if workchain.process_label == "Cp2kGeoOptWorkChain"
                else "energy_calculation"
            )

        if parent_role is not None:
            parent = au.find_existing_simulation_result(
                session,
                obj.collection,
                definitions[parent_role]["object_type"],
                workchain.uuid,
            )
            report.add(
                key + "/source-result",
                label + ": source result link",
                parent is not None and str(parent.permId) in parents,
            )

        if role == "minimum_energy_path":
            for parent in au._preceding_mep_objects(session, obj.collection, workchain):
                report.add(
                    key + "/preceding/" + str(parent.permId),
                    label + ": preceding path link",
                    str(parent.permId) in parents,
                )

        if role == "charge_analysis":
            with tempfile.TemporaryDirectory(
                prefix="aiidalab-openbis-verify-charge-"
            ) as dirname:
                names = [
                    path.name
                    for path in au._cp2k_charge_analysis_files(workchain, Path(dirname))
                ]
            # A declared Bader analysis requires all three standard files, even
            # when a damaged source repository cannot currently supply one.
            methods = str(au._openbis_property(obj, "charge_analysis_method") or "")
            if "bader" in methods.lower():
                names = list(dict.fromkeys([*names, *au._BADER_RESULT_FILENAMES]))
            missing = missing_files(obj, "RAW_DATA", names)
            for name in names:
                report.add(
                    key + "/file/" + name, label + ": " + name, name not in missing
                )
    except Exception as error:  # noqa: BLE001 - failed inspection is unknown, never empty
        report.checks.append(
            ExportCheck(key + "/verification", label, "unknown", str(error))
        )
    return report


def inspect_workchain_export(session, experiment_id, workchain_uuid):
    """Reconstruct state after a retry, a new kernel, or a lost response."""
    from . import aiida_utils as au

    report = ExportReport()
    try:
        workchain = au.orm.load_node(workchain_uuid)
        for uuid in au.get_all_preceding_main_workchains(workchain.uuid):
            main = au.orm.load_node(uuid)
            if not main.is_finished_ok:
                continue
            archives = au._objects_by_property(
                session, au.OPENBIS_OBJECT_TYPES["AiiDA Node"], "WFMS_UUID", uuid
            )
            if len(archives) > 1:
                raise ValueError(f"Multiple AIIDA_NODE objects reference {uuid}.")
            report.add(
                "archive/" + str(uuid),
                main.process_label + ": shared AiiDA archive",
                bool(archives) and has_archive(archives[0]),
            )
        for target in au._exportable_workchains(workchain):
            definitions = au._result_property_definitions(target)
            for role, definition in definitions.items():
                obj = au.find_existing_simulation_result(
                    session, experiment_id, definition["object_type"], target.uuid
                )
                report.checks.extend(
                    inspect_result(session, target, role, obj, definitions, au).checks
                )
    except Exception as error:  # noqa: BLE001 - persist diagnostics instead of claiming success
        report.checks.append(
            ExportCheck("verification", "Export verification", "unknown", str(error))
        )
    return report
