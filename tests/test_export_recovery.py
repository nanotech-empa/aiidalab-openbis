"""Offline retry contracts for the supported Python runtime."""

import unittest
from types import SimpleNamespace

from src.export_recovery import (
    ExportCheck,
    ExportIncompleteError,
    ExportReport,
    ExportVerificationError,
    LocalExportMetadataError,
    ensure_upload,
    has_archive,
    missing_files,
    report_html,
)


class RecoveryContracts(unittest.TestCase):
    def test_retry_only_uploads_missing_files(self):
        stored = set()
        attempts = []

        def upload():
            attempts.append(True)
            stored.add("archive.aiida")

        for _ in range(3):
            ensure_upload(lambda: "archive.aiida" in stored, upload)
        self.assertEqual(len(attempts), 1)

    def test_lost_response_is_resolved_without_duplicate_upload(self):
        stored = []

        def upload():
            stored.append("archive.aiida")
            raise TimeoutError("response lost after successful upload")

        self.assertTrue(ensure_upload(lambda: bool(stored), upload))
        self.assertEqual(stored, ["archive.aiida"])

    def test_unknown_inventory_never_triggers_a_write(self):
        def present():
            raise ExportVerificationError("server unavailable")

        with self.assertRaises(ExportVerificationError):
            ensure_upload(present, lambda: self.fail("must not write"))

    def test_failed_readback_leaves_status_unknown(self):
        calls = []

        def present():
            calls.append(True)
            if len(calls) > 1:
                raise ExportVerificationError("read-back failed")
            return False

        with self.assertRaises(ExportVerificationError):
            ensure_upload(present, lambda: None)

    def test_success_response_without_published_file_is_incomplete(self):
        with self.assertRaises(ExportIncompleteError):
            ensure_upload(lambda: False, lambda: None)

    def test_missing_files_are_checked_individually(self):
        dataset = SimpleNamespace(
            type="RAW_DATA", permId="d", file_list=["nested/ACF.dat"]
        )
        obj = SimpleNamespace(permId="charge", get_datasets=lambda: [dataset])
        self.assertEqual(
            missing_files(obj, "RAW_DATA", ["ACF.dat", "AVF.dat", "BCF.dat"]),
            ("AVF.dat", "BCF.dat"),
        )

    def test_multiple_archives_are_ambiguous_not_missing(self):
        dataset = SimpleNamespace(
            type="RAW_DATA", permId="d", file_list=["a.aiida", "b.aiida"]
        )
        obj = SimpleNamespace(permId="archive", get_datasets=lambda: [dataset])
        with self.assertRaises(ExportVerificationError):
            has_archive(obj)

    def test_persistent_report_distinguishes_unknown_missing_and_optional(self):
        report = ExportReport(
            [
                ExportCheck("a", "Archive", "complete"),
                ExportCheck("p", "Preview <unsafe>", "missing", blocking=False),
            ]
        )
        message = report_html(report, attempted=True, error=RuntimeError("<script>"))
        self.assertIn("Export incomplete", message)
        self.assertIn("does not block AiiDA import", message)
        self.assertIn("&lt;unsafe&gt;", message)
        self.assertIn("RuntimeError", message)
        self.assertNotIn("&lt;script&gt;", message)
        self.assertNotIn("<script>", message)
        report.checks.append(ExportCheck("u", "Read-back", "unknown"))
        self.assertIn("could not be verified", report_html(report))

    def test_local_metadata_failure_does_not_claim_remote_upload_failed(self):
        report = ExportReport([ExportCheck("a", "Archive", "complete")])
        message = report_html(report, error=LocalExportMetadataError("extras failed"))
        self.assertIn("Export completed — local metadata update failed", message)
        self.assertNotIn("Export incomplete", message)


if __name__ == "__main__":
    unittest.main()
