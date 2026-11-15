#!/usr/bin/env python3
"""Add the optional CXSMILES property to MOLECULE without replacing its schema."""

from __future__ import annotations

import argparse

from src import utils

CODE = "CXSMILES"
LABEL = "CXSMILES"
DESCRIPTION = "Round-trip validated CXSMILES representation of a periodic repeat unit"
OBJECT_TYPE = "MOLECULE"


def _property_or_none(session):
    try:
        return session.get_property_type(CODE, use_cache=False)
    except (TypeError, ValueError):
        try:
            return session.get_property_type(CODE)
        except ValueError:
            return None


def _object_type(session):
    try:
        return session.get_object_type(OBJECT_TYPE, use_cache=False)
    except TypeError:
        return session.get_object_type(OBJECT_TYPE)


def _assignments(object_type):
    rows = object_type.get_property_assignments().df.to_dict(orient="records")
    return {str(row["code"]).upper(): row for row in rows}


def audit(session) -> dict[str, object]:
    """Describe the one global property and one assignment managed here."""
    property_type = _property_or_none(session)
    object_type = _object_type(session)
    assignments = _assignments(object_type)
    if property_type is not None:
        data_type = str(property_type.dataType)
        multi_value = bool(property_type.multiValue)
        if data_type != "VARCHAR" or multi_value:
            raise RuntimeError(
                f"Existing {CODE} is incompatible: dataType={data_type}, "
                f"multiValue={multi_value}"
            )
    return {
        "property_exists": property_type is not None,
        "assignment_exists": CODE in assignments,
        "next_ordinal": max(
            (int(row["ordinal"]) for row in assignments.values()),
            default=0,
        )
        + 1,
    }


def apply(session) -> dict[str, object]:
    """Create only missing metadata; existing MOLECULE assignments stay intact."""
    state = audit(session)
    property_type = _property_or_none(session)
    if property_type is None:
        property_type = session.new_property_type(
            code=CODE,
            label=LABEL,
            description=DESCRIPTION,
            dataType="VARCHAR",
            multiValue=False,
        )
        property_type.save()
    if not state["assignment_exists"]:
        _object_type(session).assign_property(
            property_type,
            section=None,
            ordinal=int(state["next_ordinal"]),
            mandatory=False,
        )
    result = audit(session)
    if not result["property_exists"] or not result["assignment_exists"]:
        raise RuntimeError("CXSMILES migration did not verify after applying it")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the additive change; without this option the command is read-only.",
    )
    args = parser.parse_args()
    session, _ = utils.connect_openbis_aiida()
    if session is None:
        raise SystemExit("openBIS connection unavailable")
    before = audit(session)
    print(f"before: {before}")
    if args.apply:
        print(f"after: {apply(session)}")


if __name__ == "__main__":
    main()
