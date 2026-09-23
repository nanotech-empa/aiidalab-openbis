"""Safety checks for tests running from a deployed AiiDAlab app checkout."""

from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
APP_DISCOVERY_ROOT = APP_ROOT.parent
STRAY_LOG_DIR = APP_DISCOVERY_ROOT / "logs"


def _is_deployed_aiidalab_app():
    """Return whether this checkout lives directly in an AiiDAlab apps root."""
    return (APP_DISCOVERY_ROOT / "home").is_dir()


def _reject_stray_log_app(stage):
    """Fail before a stray log directory can break the AiiDAlab home page."""
    if _is_deployed_aiidalab_app() and STRAY_LOG_DIR.exists():
        raise pytest.UsageError(
            f"{stage} created or found forbidden AiiDAlab app directory "
            f"{STRAY_LOG_DIR}. Runtime and test paths must be anchored to {APP_ROOT}."
        )


def pytest_sessionstart(session):
    """Reject pollution already present before test collection."""
    _reject_stray_log_app("pytest session start")


def pytest_collection_finish(session):
    """Catch filesystem writes performed while importing test modules."""
    _reject_stray_log_app("pytest collection")


def pytest_sessionfinish(session, exitstatus):
    """Catch filesystem writes performed during test execution."""
    _reject_stray_log_app("pytest execution")
