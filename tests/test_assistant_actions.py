from types import SimpleNamespace

import pytest
from aiidalab_ai_assistant import openbis as bridge
from aiidalab_ai_assistant.tools import ToolRegistry

from aiida_openbis.assistant_actions import register_actions

URL = "https://fixture.example/openbis"
EXPERIMENT = "/DISPOSABLE/PROJ/EXPERIMENT"
RESULT_TOOL = "openbis_create_stm_result"
DRAFT_TOOL = "openbis_create_publication_draft"


def row(ident, type_code, **fields):
    return {
        "permId": ident,
        "type": type_code,
        "identifier": f"/DISPOSABLE/PROJ/{type_code}-{ident}",
        "experiment": EXPERIMENT,
        "parents": [],
        **fields,
    }


class Server:
    url = URL
    user = "lab-user"
    schema_assigned = True
    lose_response = False
    reorder = False

    def __init__(self):
        self.writes = []
        self.rows = [
            row("10-1", "MEASUREMENT_SESSION", NAME="Microscopy"),
            row("10-2", "SPM_SIMULATION", SPM_MODE=["STS", "STM"]),
            row("10-3", "SPM_SIMULATION", SPM_MODE="STM"),
            row("10-4", "SPM_SIMULATION", SPM_MODE="AFM"),
            row("20-2", "PERSON", NAME="Second Person"),
            row("20-1", "PERSON", NAME="First Person"),
            row("20-3", "ORGANISATION", NAME="Institute"),
            row("20-4", "AUTHOR", PERSON="20-2", AFFILIATIONS="20-3"),
            row("20-5", "AUTHOR", PERSON="20-1", AFFILIATIONS=["20-3"]),
        ]

    def get_objects(self, **query):
        rows = self.rows
        for key in ("type", "permId", "identifier"):
            if key in query:
                values = query[key] if isinstance(query[key], list) else [query[key]]
                rows = [r for r in rows if r[key] in values]
        for key, value in query.get("where", {}).items():
            rows = [r for r in rows if r.get(key.upper()) == value]
        return {"objects": rows, "totalCount": len(rows)}

    def get_experiment(self, path):
        assert path == EXPERIMENT
        return SimpleNamespace(type="EXPERIMENT")

    def get_object_type(self, code, **kwargs):
        assert code == "DRAFT"
        assignments = (
            [{"propertyType": {"code": "AUTHORS"}}] if self.schema_assigned else []
        )
        return SimpleNamespace(data={"propertyAssignments": assignments})

    def get_property_type(self, code, **kwargs):
        assert code == "AUTHORS"
        return {
            "dataType": "SAMPLE",
            "multiValue": True,
            "sampleType": {"code": "AUTHOR"},
        }

    def new_object(self, type, collection, parents, props):
        assert collection == EXPERIMENT
        permid = f"30-{len(self.writes) + 1}"

        def save():
            self.writes.append(type)
            actual = {k.upper(): v for k, v in props.items()}
            if self.reorder and type == "DRAFT":
                actual["AUTHORS"] = list(reversed(actual["AUTHORS"]))
            self.rows.append(row(permid, type, parents=parents, **actual))
            if self.lose_response:
                raise TimeoutError("mock request contained a credential")

        return SimpleNamespace(permId=permid, save=save)


@pytest.fixture
def demo(monkeypatch):
    server = Server()
    registry = ToolRegistry()
    monkeypatch.setattr(bridge, "connect", lambda **kw: server)
    monkeypatch.setattr(bridge, "session_user", lambda c: c.user)
    monkeypatch.setattr(bridge, "_records", lambda r: r["objects"])
    register_actions(registry)
    return registry, server


def call_args(**args):
    return {"openbis_instance": URL, "openbis_user": "lab-user", **args}


def result_args(**overrides):
    return call_args(
        **(
            {
                "measurement_permid": "10-1",
                "simulation_permids": ["10-2", "10-3"],
                "description": "Exact requested description.",
            }
            | overrides
        )
    )


def run(registry, tool, args):
    preview = registry.call(tool, args)
    assert preview["status"] == "awaiting_confirmation", preview
    return registry.approve(preview["action_id"])


def test_result_exact_parents_and_retry_reuse(demo):
    registry, server = demo
    prepared = registry.call(RESULT_TOOL, result_args())
    assert prepared["status"] == "awaiting_confirmation"
    assert prepared["review"]["openbis_user"] == server.user and not server.writes
    receipt = registry.approve(prepared["action_id"])
    assert (
        receipt["status"] == "created"
        and receipt["description"] == result_args()["description"]
    )
    assert set(receipt["parents"]) == {r["identifier"] for r in server.rows[:3]}
    assert (
        receipt["record"]["url"].startswith(URL) and "30-1" in receipt["record"]["url"]
    )
    assert run(registry, RESULT_TOOL, result_args())["status"] == "reused"
    assert server.writes == ["RESULT"]


def test_wrong_mode_and_account_change_stop_before_creation(demo):
    registry, server = demo
    assert (
        "SPM_MODE"
        in registry.call(RESULT_TOOL, result_args(simulation_permids=["10-4"]))["error"]
    )
    preview = registry.call(RESULT_TOOL, result_args())
    server.user = "second-account"
    assert "account changed" in registry.approve(preview["action_id"])["error"]
    assert not server.writes


def test_timeout_reconciles_visible_exact_record(demo):
    registry, server = demo
    server.lose_response = True
    assert run(registry, RESULT_TOOL, result_args())["status"] == "reused"
    assert server.writes == ["RESULT"]


def test_draft_order_and_both_affiliation_shapes(demo):
    registry, server = demo
    result = run(registry, RESULT_TOOL, result_args())["record"]
    authors = registry.call(
        "openbis_resolve_draft_authors",
        {
            "author_names": ["First Person", "Second Person"],
            "affiliation_permid": "20-3",
        },
    )
    assert authors["author_permids"] == ["20-5", "20-4"]
    args = call_args(
        result_permid=result["permId"], author_permids=authors["author_permids"]
    )
    draft = run(registry, DRAFT_TOOL, args)
    assert draft["status"] == "created"
    assert draft["parents"] == [result["identifier"]]
    assert draft["author_permids"] == ["20-5", "20-4"]
    assert "DRAFT_TYPE" not in server.rows[-1]
    assert run(registry, DRAFT_TOOL, args)["status"] == "reused"
    assert server.writes == ["RESULT", "DRAFT"]


def test_wrong_server_order_is_reported_and_retry_cannot_duplicate(demo):
    registry, server = demo
    result = run(registry, RESULT_TOOL, result_args())["record"]
    server.reorder = True
    args = call_args(result_permid=result["permId"], author_permids=["20-5", "20-4"])
    assert "differ from the review" in run(registry, DRAFT_TOOL, args)["error"]
    assert "existing DRAFT" in run(registry, DRAFT_TOOL, args)["error"]
    assert server.writes == ["RESULT", "DRAFT"]


def test_draft_funding_is_a_typed_graph_parent(demo):
    registry, server = demo
    grant = row("40-1", "GRANT", NAME="Funding record")
    server.rows.append(grant)
    result = run(registry, RESULT_TOOL, result_args())["record"]
    args = call_args(result_permid=result["permId"], author_permids=["20-5", "20-4"])
    invalid = registry.call(DRAFT_TOOL, {**args, "grant_permids": ["20-3"]})
    assert "GRANT" in invalid["error"] and server.writes == ["RESULT"]
    funded = {**args, "grant_permids": [grant["permId"]]}
    draft = run(registry, DRAFT_TOOL, funded)
    assert set(draft["parents"]) == {result["identifier"], grant["identifier"]}
    assert draft["author_permids"] == ["20-5", "20-4"]
    assert draft["grants"][0]["permId"] == grant["permId"]
    assert run(registry, DRAFT_TOOL, funded)["status"] == "reused"
    assert server.writes == ["RESULT", "DRAFT"]


def test_missing_schema_blocks_only_the_draft(demo):
    registry, server = demo
    server.schema_assigned = False
    result = run(registry, RESULT_TOOL, result_args())["record"]
    assert (
        "DRAFT.AUTHORS is missing"
        in registry.call(
            DRAFT_TOOL,
            call_args(result_permid=result["permId"], author_permids=["20-5"]),
        )["error"]
    )
    assert server.writes == ["RESULT"]
