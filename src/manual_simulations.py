"""Export one manually described simulation per AiiDA archive root.

The server is authoritative for reuse and recovery. No local AiiDA nodes or
extras are created or updated by this export path.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

from . import aiida_archives
from . import export_recovery as recovery


def simulation_name(base, root):
    label = root.get("label") or root["process_label"]
    return f"{base} — {label} [{root['uuid'][:8]}]"


def attachment_names(files):
    names = tuple(Path(item["name"]).name for item in files)
    if any(name in ("", ".", "..") for name in names) or len(set(names)) != len(names):
        raise ValueError("Upload files with distinct, non-empty filenames.")
    return names


def _upload_files(session, obj, files, dataset_type):
    from . import utils

    for item, name in zip(files, attachment_names(files)):
        with TemporaryDirectory(prefix="aiidalab-openbis-attachment-") as directory:
            path = Path(directory) / name

            # The upload and read-back are synchronous, so this file remains
            # available until both have completed (including an error recovery).
            def upload(path=path, item=item):
                path.write_bytes(item["content"])
                utils.create_openbis_dataset(
                    session,
                    type=dataset_type,
                    sample=obj,
                    files=[path],
                )

            recovery.ensure_upload(
                lambda name=name: not recovery.missing_files(obj, dataset_type, [name]),
                upload,
            )


def export_root(
    session,
    collection,
    object_type,
    properties,
    parents,
    source,
    root,
    previews,
    raw_files,
):
    from . import aiida_utils as au
    from . import utils

    uuid = aiida_archives.workflow_uuid(root["uuid"])
    attachment_names(previews)
    attachment_names(raw_files)
    existing = au.find_existing_simulation_result(
        session, collection, object_type, uuid
    )
    archive = au.find_aiida_archive(session, uuid)
    linked_archive = au._openbis_property(existing, "aiida_node") if existing else None
    if linked_archive and (
        archive is None or str(linked_archive) != str(archive.permId)
    ):
        raise recovery.ExportVerificationError(
            f"The existing simulation for {uuid} links a different AIIDA_NODE. "
            "Resolve that reference before exporting."
        )
    if archive is None or not recovery.has_archive(archive):
        with aiida_archives.single_root_archive(source, uuid) as path:
            archive = au.upload_aiida_archive(session, uuid, path)

    if existing is None:
        props = dict(properties, aiida_node=str(archive.permId), aiida_source_uuid=uuid)
        result = utils.create_openbis_object(
            session,
            type=object_type,
            collection=collection,
            parents=parents,
            props=props,
        )
    else:
        result = existing
        for parent in parents:
            au._ensure_openbis_parent(result, parent)
        if not linked_archive:
            result.props["aiida_node"] = str(archive.permId)
            utils.update_openbis_object(result)
        # Keep properties that have already been reviewed on openBIS.
    au._mark_export_result(result, created=existing is None, source_uuid=uuid)
    _upload_files(session, result, previews, "ELN_PREVIEW")
    _upload_files(session, result, raw_files, "RAW_DATA")
    return result


def inspect_export(
    session, collection, object_type, roots, previews, raw_files, parents=()
):
    from . import aiida_utils as au

    report = recovery.ExportReport()
    results = []
    for root in roots:
        uuid = root["uuid"]
        label = root.get("label") or root["process_label"]
        label = f"{label} [{uuid[:8]}]"
        try:
            archive = au.find_aiida_archive(session, uuid)
            report.add(
                f"{uuid}:archive",
                f"{label}: AiiDA archive",
                archive is not None and recovery.has_archive(archive),
            )
            result = au.find_existing_simulation_result(
                session, collection, object_type, uuid
            )
            report.add(f"{uuid}:simulation", f"{label}: simulation", result is not None)
            if result is None:
                continue
            results.append(result)
            report.add(
                f"{uuid}:link",
                f"{label}: archive link",
                archive is not None
                and str(au._openbis_property(result, "aiida_node"))
                == str(archive.permId),
            )
            actual_parents = {
                au._openbis_reference(parent)
                for parent in au._relationship_items(result.parents)
            }
            report.add(
                f"{uuid}:parents",
                f"{label}: selected parents",
                set(map(str, parents)) <= actual_parents,
            )
            for dataset_type, files in (
                ("ELN_PREVIEW", previews),
                ("RAW_DATA", raw_files),
            ):
                names = attachment_names(files)
                missing = recovery.missing_files(result, dataset_type, names)
                for name in names:
                    report.add(
                        f"{uuid}:{dataset_type}:{name}",
                        f"{label}: {name}",
                        name not in missing,
                    )
        except Exception as error:  # noqa: BLE001 - preserve unknown remote state in the report
            report.checks.append(
                recovery.ExportCheck(
                    uuid,
                    label,
                    "unknown",
                    str(error),
                )
            )
    return report, tuple(results)
