"""Read services adapted from Fabio Lopes's ai_agent/tools.py semantics.

No LangChain, embeddings, global client, credential loading or import/upload.
The caller supplies a read-only client and plain bulk-record conversion.
"""

import json
from pathlib import Path

MATERIALS = {
    "molecule": (
        "MOLECULE",
        {"name", "empa_number", "smiles", "cxsmiles", "sum_formula", "iupac_name"},
    ),
    "product_molecule": (
        "MOLECULE",
        {"name", "smiles", "cxsmiles", "sum_formula", "iupac_name"},
    ),
    "substance": ("SUBSTANCE", {"name", "empa_number", "batch"}),
    "crystal_concept": ("CRYSTAL_CONCEPT", {"name", "face", "material"}),
    "crystal": ("CRYSTAL", {"name"}),
    "2d_material": (
        "2D_LAYER_MATERIAL",
        {"name", "top_layer_material", "layer_count", "substrate", "growth_method"},
    ),
    "sample": ("SAMPLE", {"name", "object_status"}),
}


def _references(value):
    if value in (None, ""):
        return []
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else [str(value)]


def _lower(row):
    return {str(k).lower(): v for k, v in row.items()}


def _fetch(client, records, identifiers):
    """One bulk request per identifier kind, never lazy entity traversal."""
    rows = []
    identifiers = sorted(set(identifiers))
    if len(identifiers) > 500:
        raise ValueError("Too many linked objects; narrow the search.")
    for path_kind in (True, False):
        group = [v for v in identifiers if v.startswith("/") == path_kind]
        if group:
            rows.extend(
                records(
                    client.get_objects(
                        **{"identifier" if path_kind else "permId": group},
                        props=["*"],
                        attrs=["parents", "children"],
                        count=len(group),
                        raw_response=True,
                    )
                )
            )
    return rows


def _index(rows):
    return {
        str(row[key]): row
        for row in rows
        for key in ("permId", "identifier")
        if row.get(key)
    }


def search_materials(
    client,
    records,
    *,
    kind,
    filters=None,
    identifier="",
    molecules=None,
    crystal_concept=None,
    limit=20,
    offset=0,
):
    """Paginate candidate records; linked chemistry is matched within that page."""
    if kind not in MATERIALS:
        raise ValueError("Unsupported material kind.")
    code, allowed = MATERIALS[kind]
    filters, molecules = filters or {}, molecules or []
    if set(filters) - allowed or not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Unsupported material filters or page.")
    if molecules and kind not in {"substance", "product_molecule"}:
        raise ValueError(
            "Linked molecule filters need a substance or product molecule."
        )
    if crystal_concept and kind != "crystal":
        raise ValueError("Crystal-concept filters apply to crystals.")
    kwargs = {
        "type": code,
        "where": filters,
        "props": ["*"],
        "attrs": ["parents", "children"],
        "start_with": offset,
        "count": limit,
        "raw_response": True,
    }
    if kind == "product_molecule":
        config = json.loads(
            (Path(__file__).parents[1] / "config/openbis_config.json").read_text()
        )
        kwargs["collection"] = config["Collections"]["Paths"]["Product Molecule"]
    if identifier:
        kwargs["identifier" if identifier.startswith("/") else "permId"] = identifier
    found = client.get_objects(**kwargs)
    candidates = records(found)
    links = set()
    for row in candidates:
        data = _lower(row)
        for key in ("parents", "molecules", "crystal_concept"):
            links.update(_references(data.get(key)))
    linked = (
        _index(_fetch(client, records, links)) if (molecules or crystal_concept) else {}
    )

    def matches(row, criteria):
        values = _lower(row)
        return all(
            str(values.get(k.lower(), "")) == str(v)
            for k, v in criteria.items()
            if v not in (None, "")
        )

    result = []
    unresolved = set()
    for row in candidates:
        data = _lower(row)
        if crystal_concept:
            refs = _references(data.get("crystal_concept"))
            unresolved.update(v for v in refs if v not in linked)
            if not any(
                v in linked and matches(linked[v], crystal_concept) for v in refs
            ):
                continue
        if molecules:
            refs = _references(data.get("parents"))
            if kind == "substance":
                refs.extend(_references(data.get("molecules")))
            unresolved.update(v for v in refs if v not in linked)
            targets = [
                linked[v]
                for v in refs
                if v in linked and linked[v].get("type") == "MOLECULE"
            ]
            if not all(
                any(matches(target, wanted) for target in targets)
                for wanted in molecules
            ):
                continue
        result.append(row)
    end = offset + len(candidates)
    total = found["totalCount"]
    return {
        "items": result,
        "candidate_total": total,
        "candidates_examined": len(candidates),
        "offset": offset,
        "next_offset": end if total is not None and end < total else None,
        "unresolved_links": sorted(unresolved),
        "matching": "Direct properties use openBIS filtering. Linked molecular properties use exact stored-text equality, not chemical equivalence. Matches cover this candidate page only.",
    }


def relationships(
    client, records, *, identifier, relation="simulations", max_depth=6, max_nodes=200
):
    """Bounded breadth-first relationship traversal with cycle/permission evidence."""
    if relation not in {"simulations", "provenance", "measurements", "samples"}:
        raise ValueError("Unknown relationship query")
    if not 1 <= max_depth <= 12 or not 1 <= max_nodes <= 500:
        raise ValueError("Invalid traversal budget")
    from .export import _app_module

    simulation_types = set(_app_module("simulation_schema").OBJECT_TYPES)
    # Legacy records remain searchable, without reviving their schema definitions.
    simulation_types.update(
        {
            "SIMULATION",
            "MINIMUM_ENERGY_POTENTIAL",
            "POTENTIAL_ENERGY_CALCULATION",
            "GEOMETRY_OPTIMIZATION",
        }
    )
    direction = "parents" if relation == "provenance" else "children"
    frontier, seen, nodes, edges, missing = [identifier], set(), {}, [], set()
    limited = False
    for depth in range(max_depth + 1):
        requested = sorted(set(frontier) - seen)
        if not requested:
            break
        remaining = max_nodes - len(nodes)
        if remaining <= 0:
            limited = True
            break
        if len(requested) > remaining:
            requested = requested[:remaining]
            limited = True
        rows = _fetch(client, records, requested)
        index = _index(rows)
        missing.update(v for v in requested if v not in index)
        seen.update(requested)
        frontier = []
        for row in rows:
            identity = row.get("permId") or row["identifier"]
            if identity in nodes:
                continue
            nodes[identity] = row
            seen.update(str(row[k]) for k in ("permId", "identifier") if row.get(k))
            refs = _references(_lower(row).get(direction))
            for ref in refs:
                edges.append({"from": identity, "to": ref, "relation": direction})
            # Fabio's measurement route follows measurement sessions only.
            if (
                relation == "measurements"
                and depth
                and row.get("type") != "MEASUREMENT_SESSION"
            ):
                continue
            frontier.extend(ref for ref in refs if ref not in seen)
        if depth == max_depth and frontier:
            limited = True
    selected = {
        "simulations": simulation_types,
        "measurements": {"MEASUREMENT_SESSION"},
        "samples": {"SAMPLE"},
    }.get(relation)
    items = [
        row for row in nodes.values() if selected is None or row.get("type") in selected
    ]
    return {
        "items": items,
        "edges": edges,
        "visited": len(nodes),
        "truncated": limited,
        "unresolved_links": sorted(missing),
        "complete": not limited and not missing,
        "scope": "Explicit object relationships visible to this account; missing links may be inaccessible, not absent.",
    }


def register_tools(registry):
    from aiidalab_ai_assistant import openbis as bridge
    from aiidalab_ai_assistant.tools import object_schema

    string = {"type": "string", "maxLength": 1000}
    molecular = object_schema(
        {
            key: string
            for key in (
                "permId",
                "name",
                "empa_number",
                "smiles",
                "cxsmiles",
                "sum_formula",
                "iupac_name",
            )
        }
    )

    def wrap(function):
        @bridge._guard
        def call(**arguments):
            client = bridge.connect()
            result = function(client, bridge._records, **arguments)
            result["items"] = bridge._links(client, result["items"], "objects")
            return bridge._evidence(client, **result)

        return call

    registry.add(
        "openbis_search_materials",
        "Search Fabio's typed lab materials, preserving product-molecule collection and linked molecule/crystal semantics. Paginate candidates; duplicate names are not identities.",
        object_schema(
            {
                "kind": {"enum": list(MATERIALS)},
                "identifier": string,
                "filters": {
                    "type": "object",
                    "maxProperties": 12,
                    "additionalProperties": string,
                },
                "molecules": {"type": "array", "maxItems": 8, "items": molecular},
                "crystal_concept": object_schema(
                    {k: string for k in ("permId", "name", "face", "material")}
                ),
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            ["kind"],
        ),
        wrap(search_materials),
    )
    registry.add(
        "openbis_relationships",
        "Follow a selected permID/identifier to related simulations, measurements, samples or preparation provenance. Bounded, cycle-safe, read-only; reports missing links and truncation.",
        object_schema(
            {
                "identifier": string,
                "relation": {
                    "enum": ["simulations", "measurements", "samples", "provenance"]
                },
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 12},
                "max_nodes": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ["identifier"],
        ),
        wrap(relationships),
    )
