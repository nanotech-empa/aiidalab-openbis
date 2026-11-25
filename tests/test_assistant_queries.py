from aiida_openbis.assistant_queries import (
    register_tools,
    relationships,
    search_materials,
)
import pytest


class Client:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def get_objects(self, **kw):
        self.calls.append(kw)
        rows = list(self.rows)
        for key in ("permId", "identifier", "type"):
            if key in kw:
                values = kw[key] if isinstance(kw[key], list) else [kw[key]]
                rows = [r for r in rows if r.get(key) in values]
        for k, v in kw.get("where", {}).items():
            rows = [r for r in rows if r.get(k.upper()) == v]
        if "collection" in kw:
            rows = [r for r in rows if r.get("experiment") == kw["collection"]]
        total = len(rows)
        start = kw.get("start_with", 0) or 0
        rows = rows[start : start + kw.get("count", 100)]
        return {"objects": rows, "totalCount": total}


def records(found):
    return found["objects"]


def row(pid, code, **values):
    return dict(permId=pid, identifier="/SPACE/" + pid, type=code, **values)


def test_substance_molecular_matching_is_bulk_and_paginates_candidate_pages():
    client = Client(
        [
            row("s1", "SUBSTANCE", MOLECULES=["m1"]),
            row("s2", "SUBSTANCE", MOLECULES=["m2", "m3"]),
            row("m1", "MOLECULE", SMILES="CO"),
            row("m2", "MOLECULE", SMILES="CC"),
            row("m3", "MOLECULE", SUM_FORMULA="H2O"),
        ]
    )
    first = search_materials(
        client, records, kind="substance", molecules=[{"smiles": "CC"}], limit=1
    )
    assert first["items"] == [] and first["next_offset"] == 1
    assert len(client.calls) == 2
    second = search_materials(
        client,
        records,
        kind="substance",
        molecules=[{"smiles": "CC"}, {"sum_formula": "H2O"}],
        offset=1,
    )
    assert [r["permId"] for r in second["items"]] == ["s2"]
    assert second["next_offset"] is None


def test_product_molecule_uses_configured_collection_and_molecule_parents():
    import json
    from pathlib import Path

    import aiida_openbis.assistant_queries as module

    config = json.loads(
        (Path(module.__file__).parents[1] / "config/openbis_config.json").read_text()
    )
    collection = config["Collections"]["Paths"]["Product Molecule"]
    client = Client(
        [
            row(
                "p",
                "MOLECULE",
                parents=["/SPACE/m"],
                experiment=collection,
                CXSMILES="periodic-fixture",
            ),
            row("other", "MOLECULE", parents=["/SPACE/m"], experiment="/OTHER"),
            row("m", "MOLECULE", SMILES="CC"),
        ]
    )
    found = search_materials(
        client,
        records,
        kind="product_molecule",
        filters={"cxsmiles": "periodic-fixture"},
        molecules=[{"smiles": "CC"}],
    )
    assert [r["permId"] for r in found["items"]] == ["p"]
    assert client.calls[0]["collection"] == collection
    assert client.calls[0]["type"] == "MOLECULE"
    assert (
        search_materials(client, records, kind="product_molecule", identifier="m")[
            "items"
        ]
        == []
    )


def test_substance_parent_matches_physical_vial_and_retired_kind_is_rejected():
    client = Client(
        [
            row("vial", "SUBSTANCE", parents=["concept"], EMPA_NUMBER="777"),
            row("concept", "MOLECULE", SMILES="CC"),
        ]
    )
    result = search_materials(
        client,
        records,
        kind="substance",
        filters={"empa_number": "777"},
        molecules=[{"smiles": "CC"}],
    )
    assert [r["permId"] for r in result["items"]] == ["vial"]
    calls = list(client.calls)
    with pytest.raises(ValueError, match="Unsupported material kind"):
        search_materials(client, records, kind="reaction_product")
    assert client.calls == calls


def test_crystal_concept_and_unresolved_permission_links():
    client = Client(
        [
            row("c1", "CRYSTAL", CRYSTAL_CONCEPT="cc"),
            row("c2", "CRYSTAL", CRYSTAL_CONCEPT="hidden"),
            row("cc", "CRYSTAL_CONCEPT", MATERIAL="Au", FACE="111"),
        ]
    )
    found = search_materials(
        client,
        records,
        kind="crystal",
        crystal_concept={"face": "111", "material": "Au"},
    )
    assert [r["permId"] for r in found["items"]] == ["c1"]
    assert found["unresolved_links"] == ["hidden"]


def test_relationship_cycles_branching_truncation_and_new_simulation_types():
    client = Client(
        [
            row("m", "MOLECULE", children=["/SPACE/s", "/SPACE/c"]),
            row("s", "UNCLASSIFIED_SIMULATION", children=["/SPACE/m"]),
            row("c", "CHARGE_ANALYSIS", children=["/SPACE/missing"]),
        ]
    )
    found = relationships(client, records, identifier="m")
    assert {r["permId"] for r in found["items"]} == {"s", "c"}
    assert found["visited"] == 3 and found["unresolved_links"] == ["/SPACE/missing"]
    assert not found["complete"] and len(client.calls) == 3
    limited = relationships(client, records, identifier="m", max_nodes=1)
    assert limited["truncated"] and not limited["complete"]


def test_domain_registry_uses_shared_redacted_read_boundary(monkeypatch):
    from aiidalab_ai_assistant import openbis as bridge
    from aiidalab_ai_assistant.tools import ToolRegistry

    monkeypatch.setattr(
        bridge, "connect", lambda: (_ for _ in ()).throw(RuntimeError("private-token"))
    )
    registry = ToolRegistry()
    register_tools(registry)
    result = registry.call("openbis_relationships", {"identifier": "test"})
    assert result["error_type"] == "RuntimeError" and "private-token" not in str(result)
    assert all(not t.action for t in registry.tools.values())
