"""Read services adapted from Fabio Lopes's ai_agent/tools.py semantics.

No LangChain, embeddings, global client, credential loading or import/upload.
The caller supplies a read-only client and plain bulk-record conversion.
"""

import json
import re
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
    identifiers = sorted(set(identifiers))
    if len(identifiers) > 500:
        raise ValueError("Too many linked objects; narrow the search.")

    def query(count, **criteria):
        return client.get_objects(
            **criteria,
            props=["*"],
            attrs=["parents", "children"],
            count=count,
            raw_response=True,
        )

    permids = [value for value in identifiers if not value.startswith("/")]
    paths = {value for value in identifiers if value.startswith("/")}
    rows = records(query(len(permids), permId=permids)) if permids else []
    if len(paths) == 1:
        return rows + records(query(1, identifier=next(iter(paths))))
    if paths:
        # pyBIS combines distinct identifier paths with AND. Code lists use OR.
        # Match the full identifiers client-side to disambiguate repeated codes.
        codes = sorted({path.rsplit("/", 1)[-1] for path in paths})
        found = query(500, code=codes)
        matches = [row for row in records(found) if row.get("identifier") in paths]
        rows.extend(matches)
        if found.get("totalCount", 0) > 500:
            for path in sorted(paths - {row["identifier"] for row in matches}):
                rows.extend(records(query(1, identifier=path)))
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


def _words(value):
    return " ".join(re.findall(r"[^\W_]+", str(value or "").casefold()))


def _matches_name(value, names):
    text = f" {_words(value)} "
    return any(f" {name} " in text for term in names if (name := _words(term)))


def search_spm_simulations(
    client,
    records,
    *,
    mode,
    name="",
    molecule="",
    molecule_aliases=(),
    surface="",
    limit=20,
    offset=0,
):
    """Find SPM records with a stored mode and explicit material relationships."""
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Unsupported simulation page.")
    found = client.get_objects(
        type="SPM_SIMULATION",
        props=["*"],
        attrs=["parents", "children"],
        count=limit,
        start_with=offset,
        raw_response=True,
    )
    candidates = records(found)

    def modes(row):
        return _references(_lower(row).get("spm_mode"))

    requested_molecules = (
        [molecule, *molecule_aliases] if molecule else list(molecule_aliases)
    )
    selected = [
        row
        for row in candidates
        if mode.upper() in (value.upper() for value in modes(row))
        and (not name or _matches_name(_lower(row).get("name"), [name]))
    ]
    parent_refs = {
        ref for row in selected for ref in _references(_lower(row).get("parents"))
    }
    linked = _index(_fetch(client, records, parent_refs))
    material_refs = {
        ref
        for row in linked.values()
        if row["type"] == "ATOMISTIC_MODEL"
        for ref in _references(_lower(row).get("parents"))
    }
    linked.update(_index(_fetch(client, records, material_refs)))

    def compact(value):
        return _words(value).replace(" ", "")

    def matches_surface(row):
        data = _lower(row)
        material_face = compact(data.get("material")) + compact(data.get("face"))
        return compact(surface) in {
            material_face if data.get("material") and data.get("face") else "",
            compact(data.get("name")),
        }

    def identity(row):
        return {
            key: _lower(row).get(key.lower())
            for key in ("type", "permId", "identifier", "name")
        }

    items = []
    for row in selected:
        data = _lower(row)
        material_groups = []
        direct = [linked[v] for v in _references(data.get("parents")) if v in linked]
        for model in (item for item in direct if item["type"] == "ATOMISTIC_MODEL"):
            materials = [
                linked[v]
                for v in _references(_lower(model).get("parents"))
                if v in linked
            ]
            material_groups.append((model, materials))
        material_groups.append((None, direct))
        for model, materials in material_groups:
            molecules = [
                identity(item)
                for item in materials
                if item["type"] == "MOLECULE"
                and (
                    not requested_molecules
                    or _matches_name(_lower(item).get("name"), requested_molecules)
                )
            ]
            surfaces = [
                identity(item)
                for item in materials
                if item["type"] in {"CRYSTAL_CONCEPT", "CRYSTAL", "2D_LAYER_MATERIAL"}
                and (not surface or matches_surface(item))
            ]
            if (requested_molecules and not molecules) or (surface and not surfaces):
                continue
            items.append(
                {
                    **identity(row),
                    "spm_modes": modes(row),
                    "experiment": data.get("experiment"),
                    "archive_permid": data.get("aiida_node"),
                    "model": identity(model) if model else None,
                    "molecules": molecules,
                    "surfaces": surfaces,
                }
            )
            break
    total = found.get("totalCount")
    end = offset + len(candidates)
    return {
        "items": items,
        "candidate_total": total,
        "candidates_examined": len(candidates),
        "next_offset": end
        if candidates and total is not None and end < total
        else None,
        "unresolved_links": sorted((parent_refs | material_refs) - linked.keys()),
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
        "openbis_search_spm_simulations",
        "Find saved SPM simulations by stored mode, name and linked molecule/surface. "
        "Supply molecule aliases from the user if given. Follow next_offset before "
        "concluding no match. Returns simulation and linked archive permIDs.",
        object_schema(
            {
                "mode": string,
                "name": string,
                "molecule": string,
                "molecule_aliases": {"type": "array", "maxItems": 8, "items": string},
                "surface": string,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                "offset": {"type": "integer", "minimum": 0},
            },
            ["mode"],
        ),
        wrap(search_spm_simulations),
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
