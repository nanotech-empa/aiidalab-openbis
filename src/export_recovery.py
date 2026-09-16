"""Inspect resumable simulation exports without storing status in scientific data.

An openBIS object can exist before its dataset upload has completed. Always read
the server inventory before retrying: a timeout may mean that the write succeeded
but its response was lost. Unknown inventory must never be treated as empty.
"""

import html
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from . import upload_diagnostics


class ExportVerificationError(RuntimeError):
    """The remote state is unknown; retrying a write could duplicate data."""


class ExportIncompleteError(RuntimeError):
    """The export did not produce all expected objects or attachments."""


class LocalExportMetadataError(RuntimeError):
    """Remote data were exported, but the local extra cache could not be updated."""


def report_html(report, *, attempted=False, error=None):
    """Render persistent, escaped user feedback, including technical details."""
    if report.unknown:
        title = "Export status could not be verified"
        color = "#8a6d3b"
    elif report.complete and isinstance(error, LocalExportMetadataError):
        title = "Export completed — local metadata update failed"
        color = "#8a6d3b"
    elif report.complete:
        title = "Export completed" if attempted else "Export already complete"
        color = "#237804"
    else:
        title = (
            "Export incomplete — needs completion"
            if attempted
            else "Export has missing components"
        )
        color = "#8a6d3b"
    items = []
    for check in report.checks:
        symbol = {"complete": "✓", "missing": "⚠", "unknown": "?"}[check.state]
        suffix = ""
        if check.state == "missing":
            suffix = " — missing" + (
                " (does not block AiiDA import)" if not check.blocking else ""
            )
        elif check.state == "unknown":
            suffix = " — could not verify"
        items.append(f"<li>{symbol} {html.escape(check.label + suffix)}</li>")
    details = [
        check.detail
        for check in report.checks
        if check.state == "unknown" and check.detail
    ]
    if error is not None:
        details.append(upload_diagnostics.error_summary(error))
    detail_html = (
        (
            "<details><summary>Technical details</summary><pre>"
            + html.escape("\n".join(details))
            + "</pre></details>"
        )
        if details
        else ""
    )
    return (
        f"<div role='status' style='border-left:4px solid {color};padding:10px'>"
        f"<b>{title}</b><ul>{''.join(items)}</ul>{detail_html}</div>"
    )


@dataclass
class ExportCheck:
    key: str
    label: str
    state: str
    detail: str = ""
    blocking: bool = True


@dataclass
class ExportReport:
    checks: list = field(default_factory=list)

    @property
    def complete(self):
        return bool(self.checks) and all(
            check.state == "complete" for check in self.checks
        )

    @property
    def unknown(self):
        return any(check.state == "unknown" for check in self.checks)

    def add(self, key, label, present, detail="", blocking=True):
        self.checks.append(
            ExportCheck(
                key, label, "complete" if present else "missing", detail, blocking
            )
        )


def dataset_files(openbis_object, dataset_type):
    """Read published file names, including their dataset identity, from openBIS."""
    files = []
    try:
        for dataset in openbis_object.get_datasets():
            if str(getattr(dataset.type, "code", dataset.type)) != dataset_type:
                continue
            for name in dataset.file_list:
                files.append((str(dataset.permId), str(name)))
    except Exception as error:
        raise ExportVerificationError(
            f"Could not verify datasets for {openbis_object.permId}."
        ) from error
    return tuple(files)


def has_preview(openbis_object):
    return any(
        PurePosixPath(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".svg"}
        for _, name in dataset_files(openbis_object, "ELN_PREVIEW")
    )


def has_archive(openbis_object):
    archives = [
        item
        for item in dataset_files(openbis_object, "RAW_DATA")
        if PurePosixPath(item[1]).suffix.lower() == ".aiida"
    ]
    if len(archives) > 1:
        raise ExportVerificationError(
            f"AIIDA_NODE {openbis_object.permId} has multiple archives; "
            "the correct archive must be resolved before retrying."
        )
    return bool(archives)


def missing_files(openbis_object, dataset_type, names):
    present = {
        PurePosixPath(name).name
        for _, name in dataset_files(openbis_object, dataset_type)
    }
    return tuple(name for name in names if name not in present)


def ensure_upload(present, upload):
    """Upload only missing data and resolve a lost response by reading it back.

    There is no automatic second upload in this function. A failed read-back leaves
    the state unknown, while a confirmed incomplete upload can be retried explicitly.
    """

    def verified_present():
        with upload_diagnostics.phase("remote_inventory"):
            found = present()
            trace = upload_diagnostics.CURRENT.get()
            if trace is not None:
                trace.event("remote_inventory_result", present=bool(found))
            return found

    if verified_present():
        return False
    try:
        upload()
    except Exception:
        if verified_present():
            return True
        raise
    if not verified_present():
        raise ExportIncompleteError(
            "The upload returned, but its expected files are not visible on openBIS. "
            "Verify the export before retrying."
        )
    return True
