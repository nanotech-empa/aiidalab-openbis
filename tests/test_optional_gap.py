from copy import deepcopy
from types import SimpleNamespace

import pandas as pd

from src import simulation_schema as schema


def test_optional_gap_preserves_all_assignment_settings_and_is_idempotent():
    rows = {
        "NAME": {
            "code": "NAME",
            "mandatory": True,
            "ordinal": 1,
            "section": "General",
            "showInEditView": True,
            "unique": False,
        },
        "BAND_GAP_EV": {
            "code": "BAND_GAP_EV",
            "mandatory": True,
            "ordinal": 5,
            "section": "Results",
            "showInEditView": True,
            "showRawValueInForms": False,
            "unique": False,
            "patternType": "RANGE",
            "pattern": "0:",
            "plugin": "",
        },
    }
    before = deepcopy(rows)
    calls = []

    def request(item, action, force):
        assert action == "Set" and force is False
        return {
            "params": [
                "token",
                [{"propertyAssignments": {"actions": [{"items": [item]}]}}],
            ]
        }

    def post(url, payload):
        calls.append(payload)
        for creation in payload["params"][1][0]["propertyAssignments"]["actions"][0][
            "items"
        ]:
            code = creation["propertyTypeId"]["permId"]
            for key in rows[code]:
                if key in creation:
                    rows[code][key] = creation[key]

    obj = SimpleNamespace(
        get_property_assignments=lambda: SimpleNamespace(
            df=pd.DataFrame(rows.values())
        ),
        _get_request_for_pa=request,
    )
    session = SimpleNamespace(
        get_object_type=lambda code, **kwargs: obj, _post_request=post, as_v3="dev"
    )
    schema.apply_optional_assignments(session)
    schema.apply_optional_assignments(session)
    assert len(calls) == 1
    assert rows["NAME"] == before["NAME"]
    for key, value in before["BAND_GAP_EV"].items():
        assert rows["BAND_GAP_EV"][key] == (
            False if key == "mandatory" else "" if key == "plugin" else value
        )


def test_add_ed_preserves_populated_method_vocabulary_and_is_idempotent():
    expected = schema.VOCABULARIES["SIMULATION_METHOD_FAMILY_ENUM"]
    rows = [{"code": code, "label": label} for code, label in expected if code != "ED"]
    old = deepcopy(rows)
    vocab = SimpleNamespace(get_terms=lambda: SimpleNamespace(df=pd.DataFrame(rows)))
    calls = []

    def new_term(**kwargs):
        assert kwargs["vocabularyCode"] == "SIMULATION_METHOD_FAMILY_ENUM"
        calls.append(kwargs)
        return SimpleNamespace(
            save=lambda: rows.append({"code": kwargs["code"], "label": kwargs["label"]})
        )

    session = SimpleNamespace(get_vocabulary=lambda *a, **k: vocab, new_term=new_term)
    schema.synchronize_vocabulary(session, "SIMULATION_METHOD_FAMILY_ENUM", expected)
    schema.synchronize_vocabulary(session, "SIMULATION_METHOD_FAMILY_ENUM", expected)
    assert rows[:-1] == old and len(calls) == 1
    assert rows[-1]["code"] == "ED"
