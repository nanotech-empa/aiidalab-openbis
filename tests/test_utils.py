from types import SimpleNamespace

import pandas as pd

from src import utils


def test_connection_refusal_returns_unavailable_session(monkeypatch):
    class RefusedOpenbis:
        def __init__(self, *_args, **_kwargs):
            raise ConnectionRefusedError("server offline")

    monkeypatch.setattr(utils, "Openbis", RefusedOpenbis)

    assert utils.connect_openbis("https://openbis.example/openbis", "token") == (
        None,
        {},
    )


def test_interface_config_is_empty_when_schema_request_fails(monkeypatch):
    class OfflineSession:
        def get_object_types(self):
            raise ConnectionRefusedError("server offline")

    utils.get_interface_config_info.cache_clear()
    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (OfflineSession(), {}))

    info = utils.get_interface_config_info()

    assert info["object_types"] == {}
    assert info["actions_types"] == {}
    utils.get_interface_config_info.cache_clear()


def test_interface_config_uses_bulk_object_type_metadata(monkeypatch):
    class BulkObjectTypes:
        df = pd.DataFrame(
            [
                {
                    "description": "Atomistic Model",
                    "code": "ATOMISTIC_MODEL",
                    "generatedCodePrefix": "ATMO",
                    "metaData": {"type": "slab_concept"},
                },
                {
                    "description": "Annealing",
                    "code": "ANNEALING",
                    "generatedCodePrefix": "ANN",
                    "metaData": {"type": "action", "icon": "fire"},
                },
            ]
        )

        def __iter__(self):
            raise AssertionError("bulk object types must not be iterated")

    session = SimpleNamespace(get_object_types=lambda: BulkObjectTypes())
    utils.get_interface_config_info.cache_clear()
    monkeypatch.setattr(utils, "connect_openbis_aiida", lambda: (session, {}))

    info = utils.get_interface_config_info()

    assert info["object_types"]["Atomistic Model"] == "ATOMISTIC_MODEL"
    assert info["slabs_concepts_types"]["Atomistic Model"] == "ATOMISTIC_MODEL"
    assert info["actions_types"]["Annealing"] == "ANNEALING"
    assert info["actions_types_icons"]["ANNEALING"] == "fire"
    utils.get_interface_config_info.cache_clear()


def test_openbis_eln_url_has_exactly_one_context_segment():
    expected = "https://openbis.example/openbis/webapp/eln-lims/"
    assert utils.normalize_openbis_eln_url("https://openbis.example") == expected
    assert (
        utils.normalize_openbis_eln_url("https://openbis.example/openbis") == expected
    )
    assert (
        utils.normalize_openbis_eln_url("https://openbis.example/openbis/openbis")
        == expected
    )
    assert (
        utils.normalize_openbis_eln_url(
            "https://openbis.example/webapp/eln-lims/?viewName=example"
        )
        == expected + "?viewName=example"
    )
    assert (
        utils.normalize_openbis_eln_url(
            "https://openbis.example/openbis/webapp/eln-lims/?viewName=example"
        )
        == expected + "?viewName=example"
    )
    assert (
        utils.normalize_openbis_eln_url(
            "https://openbis.example/openbis/openbis/webapp/eln-lims/"
        )
        == expected
    )


def test_generated_links_do_not_duplicate_openbis_context():
    session = SimpleNamespace(url="https://openbis.example/openbis")
    obj = SimpleNamespace(permId="object-permid")

    url = utils.generate_openbis_object_url(session, obj)

    assert "/openbis/webapp/eln-lims/" in url
    assert "/openbis/openbis/" not in url
