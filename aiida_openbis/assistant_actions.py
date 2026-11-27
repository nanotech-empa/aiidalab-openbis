"""Reviewed writes for comparison results and publication drafts."""

from functools import wraps

from .assistant_queries import _fetch, _lower, _references


class ActionError(ValueError):
    """A validation problem safe to display in the conversation."""


def _rows(client, bridge, **query):
    found = client.get_objects(
        **query,
        count=250,
        attrs=["parents", "children"],
        props=["*"],
        raw_response=True,
    )
    records = bridge._records(found)
    if found.get("totalCount") != len(records):
        raise ActionError("The openBIS selection is incomplete. Narrow the query.")
    return records


def _unique(rows, label):
    if len(rows) > 1:
        raise ActionError(
            f"More than one openBIS record matches {label}. Select an exact record."
        )
    return rows[0] if rows else None


def _record(client, bridge, permid, type_code):
    rows = _fetch(client, bridge._records, [permid])
    record = _unique(rows, permid)
    if not record or (record.get("permId"), record.get("type")) != (permid, type_code):
        raise ActionError(f"{permid} is not a visible {type_code} on this ELN.")
    return record


def _identity(row):
    return {
        key: _lower(row).get(key.lower())
        for key in ("permId", "identifier", "type", "name")
    }


def _collection(client, row):
    path = row.get("experiment")
    if not path or client.get_experiment(path).type != "EXPERIMENT":
        raise ActionError("The source record must belong to an accessible EXPERIMENT.")
    return path


def _text(value, field):
    if not value.strip():
        raise ActionError(f"Enter a {field}.")
    return value


def _author_schema(client):
    draft = client.get_object_type("DRAFT", use_cache=False).data
    assigned = any(
        a["propertyType"]["code"] == "AUTHORS" for a in draft["propertyAssignments"]
    )
    if not assigned:
        raise ActionError("DRAFT.AUTHORS is missing from the active ELN schema.")
    prop = client.get_property_type("AUTHORS", only_data=True, use_cache=False)
    if (
        prop.get("dataType") != "SAMPLE"
        or prop.get("multiValue") is not True
        or (prop.get("sampleType") or {}).get("code") != "AUTHOR"
    ):
        raise ActionError(
            "DRAFT.AUTHORS must be a multivalued object reference to AUTHOR."
        )


def _author_details(client, bridge, author):
    props = _lower(author)
    person = _record(client, bridge, props["person"], "PERSON")
    affils = _fetch(client, bridge._records, _references(props.get("affiliations")))
    ids = {
        str(row[k]) for row in affils for k in ("permId", "identifier") if row.get(k)
    }
    if not affils or set(_references(props.get("affiliations"))) - ids:
        raise ActionError("An author's affiliation is missing or not visible.")
    return {
        "author": _identity(author),
        "person": _identity(person),
        "affiliations": [_identity(row) for row in affils],
    }


def resolve_draft_authors(client, bridge, author_names, affiliation_permid):
    org = _record(client, bridge, affiliation_permid, "ORGANISATION")
    org_refs = {org["permId"], org["identifier"]}
    wanted = {name.strip().casefold() for name in author_names}
    if "" in wanted or len(wanted) != len(author_names):
        raise ActionError("Supply distinct author names in publication order.")
    # Reuse Fabio's typed inventory and linked-object semantics without loading
    # the separate chatbot's global ELN connection or model.
    people = _rows(client, bridge, type="PERSON")
    authors = _rows(client, bridge, type="AUTHOR")
    result = []
    for name in author_names:
        person = _unique([row for row in people if _person_names(row, name)], name)
        if not person:
            raise ActionError(f"No exact PERSON named {name} is visible.")
        person_refs = {person["permId"], person["identifier"]}
        author = _unique(
            [
                row
                for row in authors
                if _lower(row).get("person") in person_refs
                and org_refs.intersection(_references(_lower(row).get("affiliations")))
            ],
            f"the author {name} with the requested affiliation",
        )
        if not author:
            raise ActionError(f"No AUTHOR links {name} to the requested affiliation.")
        result.append(_author_details(client, bridge, author))
    return {
        "authors": result,
        "author_permids": [a["author"]["permId"] for a in result],
    }


def _person_names(row, name):
    data = _lower(row)
    legal = " ".join(
        str(data.get(key) or "") for key in ("person.given_name", "person.family_name")
    )
    return name.strip().casefold() in {
        str(data.get("name") or "").strip().casefold(),
        legal.strip().casefold(),
    }


def _result_plan(
    client, bridge, measurement_permid, simulation_permids, description, name=""
):
    measurement = _record(client, bridge, measurement_permid, "MEASUREMENT_SESSION")
    simulations = [
        _record(client, bridge, pid, "SPM_SIMULATION") for pid in simulation_permids
    ]
    if not simulations or any(
        "STM" not in _references(_lower(row).get("spm_mode")) for row in simulations
    ):
        raise ActionError(
            "Select at least one simulation whose stored SPM_MODE includes STM."
        )
    return {
        "type": "RESULT",
        "collection": _collection(client, measurement),
        "parents": [_identity(row) for row in (measurement, *simulations)],
        "props": {
            "name": _text(name, "name")
            if name
            else f"STM comparison for {_lower(measurement).get('name') or measurement['permId']}",
            "description": _text(description, "description"),
        },
    }


def _draft_plan(
    client, bridge, result_permid, author_permids, name="", grant_permids=None
):
    _author_schema(client)
    result = _record(client, bridge, result_permid, "RESULT")
    grants = [
        _identity(_record(client, bridge, pid, "GRANT"))
        for pid in (grant_permids or ())
    ]
    authors = [
        _author_details(client, bridge, _record(client, bridge, pid, "AUTHOR"))
        for pid in author_permids
    ]
    if len({item["person"]["permId"] for item in authors}) != len(authors):
        raise ActionError(
            "The publication draft requires distinct people in author order."
        )
    return {
        "type": "DRAFT",
        "collection": _collection(client, result),
        "parents": [_identity(result), *grants],
        "props": {
            "name": _text(name, "name")
            if name
            else f"Publication draft for {_lower(result).get('name') or result_permid}",
            "authors": author_permids,
        },
        "authors": authors,
        "grants": grants,
    }


def _has_expected_parents(row, plan):
    if row.get("type") != plan["type"] or row.get("experiment") != plan["collection"]:
        return False
    parents = set(_references(row.get("parents")))
    return len(parents) == len(plan["parents"]) and all(
        parents.intersection((parent["identifier"], parent["permId"]))
        for parent in plan["parents"]
    )


def _matches(row, plan):
    if not _has_expected_parents(row, plan):
        return False
    data = _lower(row)
    for key, value in plan["props"].items():
        if key == "authors":
            if _references(data.get(key)) != value:
                return False
        elif data.get(key) != value:
            return False
    return True


def _persist(client, bridge, plan):
    def exact_match():
        rows = _rows(
            client,
            bridge,
            type=plan["type"],
            collection=plan["collection"],
            where={"name": plan["props"]["name"]},
        )
        exact = _unique([row for row in rows if _matches(row, plan)], plan["type"])
        if exact:
            return exact
        conflict = next(
            (
                row
                for row in rows
                if _lower(row).get("name") == plan["props"]["name"]
                and _has_expected_parents(row, plan)
            ),
            None,
        )
        if conflict:
            raise ActionError(
                f"An existing {plan['type']} ({conflict['permId']}) has this name and "
                "these parents but different fields. Review it before creating another."
            )
        return None

    found = exact_match()
    if found:
        return "reused", found
    try:
        entry = client.new_object(
            type=plan["type"],
            collection=plan["collection"],
            parents=[parent["identifier"] for parent in plan["parents"]],
            props=plan["props"],
        )
        entry.save()
    except Exception as exc:
        found = exact_match()
        if found:
            return "reused", found
        raise ActionError(
            "openBIS did not confirm the write. Check the collection before retrying."
        ) from exc

    found = _record(client, bridge, entry.permId, plan["type"])
    if not _matches(found, plan):
        raise ActionError(
            f"openBIS created {entry.permId}, but its links or properties differ "
            "from the review. Inspect this record before retrying."
        )
    return "created", found


def _protected(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ActionError:
            raise
        except Exception as exc:
            raise ActionError(
                "openBIS could not verify this operation. Check the ELN and inspect the collection."
            ) from exc

    return call


def register_actions(registry):
    from aiidalab_ai_assistant import openbis as bridge
    from aiidalab_ai_assistant.tools import object_schema

    identity = {"type": "string", "pattern": r"^[0-9]+-[0-9]+$", "maxLength": 64}
    identities = {
        "type": "array",
        "items": identity,
        "minItems": 1,
        "maxItems": 20,
        "uniqueItems": True,
    }
    name = {"type": "string", "minLength": 1, "maxLength": 240}
    session_fields = {
        "openbis_instance": {"type": "string", "maxLength": 500},
        "openbis_user": {"type": "string", "maxLength": 200},
    }

    @_protected
    def find_authors(author_names, affiliation_permid):
        client = bridge.connect()
        return bridge._evidence(
            client,
            **resolve_draft_authors(client, bridge, author_names, affiliation_permid),
        )

    registry.add(
        "openbis_resolve_draft_authors",
        "Find existing ordered AUTHOR references by full PERSON names and organisation permID. "
        "Keep author_permids in the returned order.",
        object_schema(
            {
                "author_names": {
                    "type": "array",
                    "items": name,
                    "minItems": 1,
                    "maxItems": 20,
                    "uniqueItems": True,
                },
                "affiliation_permid": identity,
            },
            ["author_names", "affiliation_permid"],
        ),
        find_authors,
    )

    def register(tool, type_code, description, planner, properties, required):
        def operation(write):
            @_protected
            def handle(openbis_instance, openbis_user, **args):
                client = (
                    bridge.connect(creation_type=type_code)
                    if write
                    else bridge.connect()
                )
                actor = bridge.session_user(client)
                if (
                    client.url.rstrip("/") != openbis_instance.rstrip("/")
                    or actor != openbis_user
                ):
                    raise ActionError(
                        "The openBIS connection or account changed. Review the action again."
                    )
                plan = planner(client, bridge, **args)
                if not write:
                    return bridge._evidence(client, openbis_user=actor, **plan)
                status, row = _persist(client, bridge, plan)
                record = bridge._links(client, [_identity(row)], "objects")[0]
                evidence = {
                    "status": status,
                    "record": record,
                    "openbis_user": actor,
                    "collection": row["experiment"],
                    "parents": row["parents"],
                }
                if type_code == "DRAFT":
                    evidence["author_permids"] = _references(_lower(row).get("authors"))
                    evidence["authors"] = plan["authors"]
                    evidence["grants"] = plan["grants"]
                else:
                    evidence["description"] = _lower(row)["description"]
                return bridge._evidence(client, **evidence)

            return handle

        registry.add(
            tool,
            description,
            object_schema(
                {**session_fields, "name": name, **properties},
                [*session_fields, *required],
            ),
            operation(True),
            action=True,
            describe=operation(False),
        )

    register(
        "openbis_create_stm_result",
        "RESULT",
        "Review a new RESULT under the measurement's existing experiment. "
        "Link the exact STM measurement and all selected STM simulations as parents.",
        _result_plan,
        {
            "measurement_permid": identity,
            "simulation_permids": identities,
            "description": {"type": "string", "minLength": 1, "maxLength": 4000},
        },
        ["measurement_permid", "simulation_permids", "description"],
    )
    register(
        "openbis_create_publication_draft",
        "DRAFT",
        "Review a DRAFT in the result's experiment. Link the RESULT and any explicitly "
        "requested existing GRANT records as parents. Keep AUTHOR references in order.",
        _draft_plan,
        {
            "result_permid": identity,
            "author_permids": identities,
            "grant_permids": identities,
        },
        ["result_permid", "author_permids"],
    )
