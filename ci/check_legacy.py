"""Run the existing legacy regressions without live ELN/openBIS services."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check_runtime():
    import aiida
    from aiida.manage.configuration.settings import AIIDA_CONFIG_FOLDER

    assert sys.version_info[:2] == (3, 9), sys.version
    assert aiida.__version__ == "2.6.3", aiida.__version__
    root = Path(os.environ["AIIDA_PATH"]).resolve()
    assert root != Path.home()
    config = AIIDA_CONFIG_FOLDER.resolve()
    assert config == root or root in config.parents, config
    print(f"Isolated AiiDA config: {config}", flush=True)


class ElnFixtures:
    @pytest.fixture(autouse=True)
    def offline_eln(self, monkeypatch, tmp_path):
        from aiidalab_eln import cheminfo, elns

        monkeypatch.setattr(elns, "ELN_CONFIG", tmp_path / "eln.json")
        monkeypatch.setattr(cheminfo, "User", MagicMock())

    @pytest.fixture
    def structure_data_object(self, aiida_profile):
        from aiida import orm

        node = orm.StructureData(cell=[[10, 0, 0], [0, 10, 0], [0, 0, 10]])
        node.append_atom(position=(0, 0, 0), symbols="H")
        node.base.extras.set(
            "eln", {"sample_uuid": "12345abcde", "file_name": "file.xyz"}
        )
        return node


def main():
    check_runtime()
    if len(sys.argv) > 1 and sys.argv[1] == "eln":
        return pytest.main(
            [
                "-q",
                "--disable-socket",
                "-p",
                "aiida.tools.pytest_fixtures",
                str(ROOT / ".legacy-eln/tests"),
            ],
            plugins=[ElnFixtures()],
        )

    subprocess.run([sys.executable, __file__, "eln"], check=True)

    # Configure logging before the importer initializes its production log path.
    import logging

    logging.basicConfig(level=logging.WARNING)
    from src import utils

    sys.modules["utils"] = utils
    original_read_json = utils.read_json

    def read_test_config(path):
        if str(path).startswith("/home/jovyan/apps/aiidalab-openbis/config/"):
            return {"AFS": {}}
        return original_read_json(path)

    # The log uploader connects at import time. Only replace that external boundary.
    with patch.object(utils, "connect_openbis_aiida", return_value=(None, {})):
        with patch.object(utils, "read_json", side_effect=read_test_config):
            from src import upload_logs_to_afs  # noqa: F401

    return pytest.main(
        [
            "-q",
            "--disable-socket",
            "tests/test_synchronisation.py",
            "tests/test_nanonis_importer.py",
            "tests/test_upload_logs_to_afs.py",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
