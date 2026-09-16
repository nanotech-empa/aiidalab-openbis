"""Single-root archive operations, without importing into the user's database."""

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from aiida import orm
from aiida.storage.sqlite_zip.backend import SqliteZipBackend
from aiida.tools.archive import create_archive


def workflow_uuid(value):
    """Validate the scalar identity contract; never interpret lists or delimiters."""
    if not isinstance(value, str):
        raise ValueError("WFMS_UUID must contain exactly one UUID.")  # noqa: TRY004 - invalid property value from openBIS
    try:
        return str(UUID(value.strip()))
    except ValueError as error:
        raise ValueError("WFMS_UUID must contain exactly one valid UUID.") from error


@contextmanager
def archive_backend(path):
    storage = SqliteZipBackend(SqliteZipBackend.create_profile(str(path)))
    try:
        yield storage
    finally:
        storage.close()


def _root_nodes(storage):
    processes = (
        orm.QueryBuilder(backend=storage)
        .append(orm.ProcessNode, project="*")
        .all(flat=True)
    )
    return sorted(
        (node for node in processes if node.caller is None), key=lambda node: node.uuid
    )


def root_processes(path):
    """Use call roots in this archive, not every process or a data-flow traversal."""
    with archive_backend(path) as storage:
        return tuple(
            {
                "uuid": str(node.uuid),
                "label": str(node.label or ""),
                "process_label": str(node.process_label or node.node_type),
            }
            for node in _root_nodes(storage)
        )


def validate_root(path, expected_uuid):
    """Reject mismatched archives before importing anything into the local DB."""
    expected_uuid = workflow_uuid(expected_uuid)
    roots = root_processes(path)
    if tuple(root["uuid"] for root in roots) != (expected_uuid,):
        raise ValueError(
            "The archive must have exactly one main process matching WFMS_UUID. "
            "Upload a multi-root archive through the manual split workflow."
        )
    return expected_uuid


@contextmanager
def single_root_archive(source, root_uuid):
    """Keep the selected call tree and its data, without crossing to other roots.

    Shared inputs retain their original UUIDs in each archive. Do not follow
    their creators or callers backwards into unrelated workflows. These are the
    same boundaries used by automatic simulation exports.
    """
    root_uuid = workflow_uuid(root_uuid)
    with (
        archive_backend(source) as storage,
        TemporaryDirectory(prefix="aiidalab-openbis-single-root-") as directory,
    ):
        roots = {str(node.uuid): node for node in _root_nodes(storage)}
        if root_uuid not in roots:
            raise ValueError(f"{root_uuid} is not a main process in this archive.")
        destination = Path(directory) / f"{root_uuid}.aiida"
        create_archive(
            [roots[root_uuid]],
            filename=destination,
            backend=storage,
            include_authinfos=False,
            call_calc_backward=False,
            call_work_backward=False,
            create_backward=False,
        )
        validate_root(destination, root_uuid)
        yield destination
