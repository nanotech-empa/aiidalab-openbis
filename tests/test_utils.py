from types import SimpleNamespace

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
