#!/usr/bin/env python3
"""Add the simulation object schema to an openBIS instance safely.

The command is a dry run unless ``--apply`` is passed. Existing global property
types and vocabularies are never updated, except for the explicitly approved
``CHARGE`` and ``AIIDA_NODE`` corrections. Incompatible collisions abort before
any changes are made. Existing simulation object-type assignments are replaced
only when that object type has no instances.
"""

import argparse
import getpass
import json
import math
import time
from typing import Any

from pybis import Openbis

# openBIS does not allow changing these property attributes in place. CHARGE
# and AIIDA_NODE are the two explicitly approved corrections to pre-existing
# properties. The other four were created by this migration and must be
# recreated because pyBIS 6.6 strips multiValue for an openBIS 7 server.
IMMUTABLE_PROPERTY_MIGRATIONS = (
    "CHARGE",
    "AIIDA_NODE",
    "METHOD_MODIFIERS",
    "EXECUTABLES",
)

# Superseded empty types created before the canonical names were agreed.
OBSOLETE_OBJECT_TYPES = (
    "GEOMETRY_OPTIMIZATION",
    "SPM",
    # This pre-existing type uses "potential" where the scientific object is
    # a path. REACTION_BARRIER is intentionally left untouched until its
    # future scope (including free-energy/MD methods) is agreed.
    "MINIMUM_ENERGY_POTENTIAL",
)


VOCABULARIES = {
    "SIMULATION_METHOD_FAMILY_ENUM": [
        ("DFT", "DFT"),
        ("DFTB", "DFTB"),
        ("TB", "TB"),
        ("MFH_TB", "MFH-TB"),
        ("DMRG", "DMRG"),
        ("CAS", "CAS"),
        ("CASSCF", "CASSCF"),
        ("FORCEFIELD", "ForceField"),
        ("MLPOTENTIAL", "MLPotential"),
        ("OTHER", "other"),
    ],
    "SIMULATION_METHOD_MODIFIER_ENUM": [
        ("HYBRID", "hybrid"),
        ("VDW", "vdW"),
        ("DFT_U", "DFT+U"),
        ("SPIN_COLLINEAR", "spin_collinear"),
        ("SPIN_ORBIT", "spin_orbit"),
        ("SPIN_NON_COLLINEAR", "spin_non_collinear"),
    ],
    "ELECTRONIC_GAP_TYPE_ENUM": [
        ("DIRECT", "direct"),
        ("INDIRECT", "indirect"),
        ("UNKNOWN", "unknown"),
    ],
    "MEP_METHOD_ENUM": [
        ("NEB", "NEB"),
        ("REPLICA_CHAIN", "Replica chain"),
        ("OTHER", "Other"),
    ],
    "NEB_VARIANT_ENUM": [
        ("NEB", "NEB"),
        ("CI_NEB", "CI-NEB"),
    ],
    "SPM_MODE_ENUM": [
        ("STM", "STM"),
        ("STS", "STS"),
        ("NC_AFM", "nc-AFM"),
        ("OTHER", "other"),
    ],
    "VIBRATIONAL_MODE_ENUM": [
        ("PHONONS", "Phonons"),
        ("IR", "IR"),
        ("RAMAN", "Raman"),
        ("IR_RAMAN", "IR+Raman"),
    ],
    "MD_ENSEMBLE_ENUM": [
        ("NVE", "NVE"),
        ("NVT", "NVT"),
        ("NPT", "NPT"),
        ("OTHER", "other"),
    ],
}


def prop(
    code: str,
    label: str,
    data_type: str,
    description: str = "",
    multi_value: bool = False,
    vocabulary: str = "",
    sample_type: str = "",
) -> dict[str, Any]:
    result = {
        "code": code,
        "label": label,
        "description": description or label,
        "dataType": data_type,
        "multiValue": multi_value,
    }
    if vocabulary:
        result["vocabulary"] = vocabulary
    if sample_type:
        result["sampleType"] = sample_type
    return result


PROPERTY_TYPES = {
    item["code"]: item
    for item in [
        prop("NAME", "Name", "VARCHAR"),
        prop("COMMENTS", "Comments", "MULTILINE_VARCHAR"),
        prop("CONSTRAINED", "Constrained", "BOOLEAN"),
        prop("BAND_GAP_EV", "Band gap (eV)", "REAL"),
        prop(
            "METHOD_FAMILY",
            "Method family",
            "CONTROLLEDVOCABULARY",
            vocabulary="SIMULATION_METHOD_FAMILY_ENUM",
        ),
        prop(
            "METHOD_MODIFIERS",
            "Method modifiers",
            "CONTROLLEDVOCABULARY",
            multi_value=True,
            vocabulary="SIMULATION_METHOD_MODIFIER_ENUM",
        ),
        prop("METHOD_LABEL", "Method label", "VARCHAR"),
        prop("CHARGE", "Charge", "REAL"),
        prop("TOTAL_ENERGY_HARTREE", "Total energy (Hartree)", "REAL"),
        prop("CONVERGED", "Converged", "BOOLEAN"),
        prop("SPIN_MULTIPLICITY", "Spin multiplicity", "INTEGER"),
        prop(
            "TOTAL_MAGNETIZATION_BOHR_MAGNETON",
            "Total magnetization (Bohr magneton)",
            "REAL",
        ),
        # These are multivalued globally to support spin-resolved values.
        prop("FERMI_ENERGY_EV", "Fermi energy (eV)", "REAL", multi_value=True),
        prop("ELECTRONIC_GAP_EV", "Electronic gap (eV)", "REAL", multi_value=True),
        prop(
            "EXECUTABLES",
            "Executables",
            "SAMPLE",
            multi_value=True,
            sample_type="EXECUTABLE",
        ),
        prop(
            "AIIDA_NODE",
            "AiiDA node",
            "SAMPLE",
            sample_type="AIIDA_NODE",
        ),
        prop("AIIDA_SOURCE_UUID", "AiiDA source UUID", "VARCHAR"),
        prop("CELL_OPTIMIZATION", "Cell optimization", "BOOLEAN"),
        prop("FINAL_ENERGY_HARTREE", "Final energy (Hartree)", "REAL"),
        prop(
            "CONSTRAINTS_DESCRIPTION",
            "Constraints description",
            "MULTILINE_VARCHAR",
        ),
        prop("CELL_CONSTRAINTS", "Cell constraints", "VARCHAR"),
        prop(
            "FINAL_MAX_FORCE_HARTREE_PER_BOHR",
            "Final maximum force (Hartree/bohr)",
            "REAL",
        ),
        prop("NUMBER_OF_STEPS", "Number of steps", "INTEGER"),
        prop("K_PATH", "k-path", "VARCHAR"),
        prop(
            "ELECTRONIC_GAP_TYPE",
            "Electronic gap type",
            "CONTROLLEDVOCABULARY",
            vocabulary="ELECTRONIC_GAP_TYPE_ENUM",
        ),
        prop("CHARGE_ANALYSIS_METHOD", "Charge analysis method", "VARCHAR"),
        prop("PDOS", "Projected density of states", "BOOLEAN"),
        prop(
            "PROJECTION_DESCRIPTION",
            "Projection description",
            "MULTILINE_VARCHAR",
        ),
        prop("ENERGY_MIN_EV", "Minimum energy (eV)", "REAL"),
        prop("ENERGY_MAX_EV", "Maximum energy (eV)", "REAL"),
        prop(
            "MEP_METHOD",
            "MEP method",
            "CONTROLLEDVOCABULARY",
            vocabulary="MEP_METHOD_ENUM",
        ),
        prop(
            "NEB_VARIANT",
            "NEB variant",
            "CONTROLLEDVOCABULARY",
            vocabulary="NEB_VARIANT_ENUM",
        ),
        prop(
            "OTHER_METHOD_DESCRIPTION",
            "Other MEP method description",
            "MULTILINE_VARCHAR",
        ),
        prop(
            "RELATIVE_ENERGIES_EV",
            "Relative energies (eV)",
            "REAL",
            multi_value=True,
        ),
        prop("FORWARD_BARRIER_EV", "Forward barrier (eV)", "REAL"),
        prop("BACKWARD_BARRIER_EV", "Backward barrier (eV)", "REAL"),
        prop("NUMBER_OF_IMAGES", "Number of images", "INTEGER"),
        prop(
            "COLLECTIVE_VARIABLES",
            "Collective variables",
            "MULTILINE_VARCHAR",
        ),
        prop(
            "REACTION_COORDINATE_DESCRIPTION",
            "Reaction coordinate description",
            "MULTILINE_VARCHAR",
        ),
        prop(
            "SPM_MODE",
            "SPM mode",
            "CONTROLLEDVOCABULARY",
            vocabulary="SPM_MODE_ENUM",
        ),
        prop("BIAS_VOLTAGE_V", "Bias voltage (V)", "REAL"),
        prop("HEIGHT_ANGSTROM", "Height (angstrom)", "REAL"),
        prop("ISOVALUE_AU", "Isovalue (a.u.)", "REAL"),
        prop("TIP_MODEL", "Tip model", "VARCHAR"),
        prop("SCAN_AREA", "Scan area", "VARCHAR"),
        prop("IMAGE_MODE", "Image mode", "VARCHAR"),
        prop(
            "VIBRATIONAL_MODE",
            "Vibrational mode",
            "CONTROLLEDVOCABULARY",
            vocabulary="VIBRATIONAL_MODE_ENUM",
        ),
        prop("TIME_STEP_FS", "Time step (fs)", "REAL"),
        prop("TOTAL_TIME_FS", "Total time (fs)", "REAL"),
        prop("COMPLETED", "Completed", "BOOLEAN"),
        prop(
            "ENSEMBLE",
            "Ensemble",
            "CONTROLLEDVOCABULARY",
            vocabulary="MD_ENSEMBLE_ENUM",
        ),
        prop("TEMPERATURE_K", "Temperature (K)", "REAL"),
        prop("PRESSURE_BAR", "Pressure (bar)", "REAL"),
        prop("THERMOSTAT", "Thermostat", "VARCHAR"),
        prop("BAROSTAT", "Barostat", "VARCHAR"),
        prop(
            "SIMULATION_DESCRIPTION",
            "Simulation description",
            "MULTILINE_VARCHAR",
        ),
        prop(
            "MAIN_RESULT_DESCRIPTION",
            "Main result description",
            "MULTILINE_VARCHAR",
        ),
        prop("MAIN_RESULT_VALUE_NUMERIC", "Main result value", "REAL"),
        prop("MAIN_RESULT_UNIT", "Main result unit", "VARCHAR"),
    ]
}


def assignment(code: str, mandatory: bool, section: str) -> dict[str, Any]:
    return {"code": code, "mandatory": mandatory, "section": section}


METHOD = [
    assignment("METHOD_FAMILY", True, "Method"),
    # Empty modifier lists are valid, so this cannot be mandatory in openBIS.
    assignment("METHOD_MODIFIERS", False, "Method"),
    assignment("CHARGE", True, "Method"),
]
PROVENANCE = [
    assignment("EXECUTABLES", False, "Provenance"),
    assignment("AIIDA_NODE", False, "Provenance"),
    assignment("AIIDA_SOURCE_UUID", False, "Provenance"),
]
SPIN = [
    assignment("SPIN_MULTIPLICITY", False, "Electronic properties"),
    assignment("TOTAL_MAGNETIZATION_BOHR_MAGNETON", False, "Electronic properties"),
]


def object_type(
    prefix: str, description: str, assignments: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "prefix": prefix,
        "description": description,
        "assignments": assignments,
    }


OBJECT_TYPES = {
    "ENERGY_CALCULATION": object_type(
        "ENERGY",
        "Fixed-geometry energy calculation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("TOTAL_ENERGY_HARTREE", True, "Results"),
            assignment("CONVERGED", True, "Results"),
            assignment("FERMI_ENERGY_EV", False, "Electronic properties"),
            assignment("ELECTRONIC_GAP_EV", False, "Electronic properties"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "GEOMETRY_OPTIMISATION": object_type(
        "GEOP",
        "Geometry and optional cell optimization.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("CONSTRAINED", True, "Optimization"),
            assignment("CELL_OPTIMIZATION", True, "Optimization"),
            assignment("FINAL_ENERGY_HARTREE", True, "Results"),
            assignment("CONVERGED", True, "Results"),
            assignment("CONSTRAINTS_DESCRIPTION", False, "Optimization"),
            assignment("CELL_CONSTRAINTS", False, "Optimization"),
            assignment("FINAL_MAX_FORCE_HARTREE_PER_BOHR", False, "Results"),
            assignment("NUMBER_OF_STEPS", False, "Results"),
            assignment("FERMI_ENERGY_EV", False, "Electronic properties"),
            assignment("ELECTRONIC_GAP_EV", False, "Electronic properties"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "BAND_STRUCTURE": object_type(
        "BAND",
        "Electronic band-structure calculation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("BAND_GAP_EV", True, "Results"),
            assignment("CONVERGED", True, "Results"),
            assignment("FERMI_ENERGY_EV", False, "Electronic properties"),
            assignment("K_PATH", False, "Results"),
            assignment("ELECTRONIC_GAP_TYPE", False, "Results"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "CHARGE_ANALYSIS": object_type(
        "CHARGE",
        "Atomic, orbital, fragment, or spatial charge analysis.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("CHARGE_ANALYSIS_METHOD", True, "Method"),
            assignment("CONVERGED", True, "Results"),
            assignment("FERMI_ENERGY_EV", False, "Electronic properties"),
            assignment("ELECTRONIC_GAP_EV", False, "Electronic properties"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "DOS": object_type(
        "DOS",
        "Electronic density-of-states calculation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("PDOS", True, "Results"),
            assignment("PROJECTION_DESCRIPTION", False, "Results"),
            assignment("CONVERGED", True, "Results"),
            assignment("FERMI_ENERGY_EV", False, "Electronic properties"),
            assignment("ENERGY_MIN_EV", False, "Results"),
            assignment("ENERGY_MAX_EV", False, "Results"),
            assignment("ELECTRONIC_GAP_EV", False, "Electronic properties"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "MINIMUM_ENERGY_PATH": object_type(
        "MEP",
        "Minimum-energy path from NEB, a replica chain, or another specified method.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("MEP_METHOD", True, "Method"),
            assignment("NEB_VARIANT", False, "Method"),
            assignment("OTHER_METHOD_DESCRIPTION", False, "Method"),
            assignment("RELATIVE_ENERGIES_EV", True, "Results"),
            assignment("FORWARD_BARRIER_EV", True, "Results"),
            assignment("BACKWARD_BARRIER_EV", True, "Results"),
            assignment("CONVERGED", True, "Results"),
            assignment("NUMBER_OF_IMAGES", True, "Results"),
            assignment("COLLECTIVE_VARIABLES", False, "Path definition"),
            assignment("CONSTRAINTS_DESCRIPTION", False, "Path definition"),
            assignment("REACTION_COORDINATE_DESCRIPTION", False, "General information"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "SPM_SIMULATION": object_type(
        "SPMS",
        "Scanning-probe-microscopy simulation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("SPM_MODE", True, "Method"),
            assignment("CONVERGED", True, "Results"),
            assignment("BIAS_VOLTAGE_V", False, "Simulation settings"),
            assignment("HEIGHT_ANGSTROM", False, "Simulation settings"),
            assignment("ISOVALUE_AU", False, "Simulation settings"),
            assignment("TIP_MODEL", False, "Simulation settings"),
            assignment("SCAN_AREA", False, "Simulation settings"),
            assignment("IMAGE_MODE", False, "Simulation settings"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "VIBRATIONAL_SPECTROSCOPY": object_type(
        "VBSP",
        "Vibrational, phonon, IR, or Raman calculation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("VIBRATIONAL_MODE", True, "Method"),
            assignment("CONVERGED", True, "Results"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "MOLECULAR_DYNAMICS": object_type(
        "MD",
        "Molecular-dynamics simulation.",
        [assignment("NAME", True, "General information")]
        + METHOD
        + [
            assignment("METHOD_LABEL", True, "Method"),
            assignment("TIME_STEP_FS", True, "Simulation settings"),
            assignment("TOTAL_TIME_FS", True, "Simulation settings"),
            assignment("COMPLETED", True, "Results"),
            assignment("ENSEMBLE", False, "Simulation settings"),
            assignment("TEMPERATURE_K", False, "Simulation settings"),
            assignment("PRESSURE_BAR", False, "Simulation settings"),
            assignment("THERMOSTAT", False, "Simulation settings"),
            assignment("BAROSTAT", False, "Simulation settings"),
        ]
        + SPIN
        + [assignment("COMMENTS", False, "General information")]
        + PROVENANCE,
    ),
    "UNCLASSIFIED_SIMULATION": object_type(
        "UNSM",
        "Fallback for computational results without a dedicated type.",
        [
            assignment("NAME", True, "General information"),
            assignment("SIMULATION_DESCRIPTION", True, "General information"),
            assignment("CONVERGED", True, "Results"),
            assignment("METHOD_FAMILY", False, "Method"),
            assignment("METHOD_MODIFIERS", False, "Method"),
            assignment("METHOD_LABEL", False, "Method"),
            assignment("CHARGE", False, "Method"),
            assignment("MAIN_RESULT_DESCRIPTION", False, "Results"),
            assignment("MAIN_RESULT_VALUE_NUMERIC", False, "Results"),
            assignment("MAIN_RESULT_UNIT", False, "Results"),
            assignment("COMMENTS", False, "General information"),
        ]
        + PROVENANCE,
    ),
}


def normalize_reference(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "code", value) or "")


def existing_or_none(getter, code: str):
    try:
        return getter(code, use_cache=False)
    except TypeError:
        try:
            return getter(code)
        except ValueError:
            return None
    except ValueError:
        return None


def validate_vocabulary(vocabulary, expected_terms) -> list[str]:
    if vocabulary is None:
        return []
    actual = {
        str(row["code"]): str(row.get("label") or row["code"])
        for row in vocabulary.get_terms().df.to_dict("records")
    }
    expected = dict(expected_terms)
    return [] if actual == expected else [f"terms {actual!r} != {expected!r}"]


def validate_property(existing, expected: dict[str, Any]) -> list[str]:
    if existing is None:
        return []
    differences = []
    checks = {
        "dataType": str(existing.dataType),
        "multiValue": bool(existing.multiValue),
    }
    if expected.get("vocabulary"):
        checks["vocabulary"] = normalize_reference(existing.vocabulary)
    if expected.get("sampleType"):
        checks["sampleType"] = normalize_reference(existing.sampleType)
    for key, actual in checks.items():
        wanted = expected.get(key, False if key == "multiValue" else "")
        if actual != wanted:
            differences.append(f"{key}={actual!r}, expected {wanted!r}")
    return differences


def assignment_state(object_type) -> dict[str, dict[str, Any]]:
    return {
        str(row["code"]): row
        for row in object_type.get_property_assignments().df.to_dict("records")
    }


def property_assignments(session, property_code: str) -> list[dict[str, Any]]:
    """Return every assignment of a global property type."""
    assignments = []
    for row in session.get_object_types().df.to_dict("records"):
        object_code = str(row["code"])
        assignment_row = assignment_state(
            session.get_object_type(object_code, use_cache=False)
        ).get(property_code)
        if assignment_row is not None:
            assignments.append(
                {"object_type": object_code, "assignment": assignment_row}
            )
    return assignments


def clean_assignment_value(value: Any):
    """Turn pandas NaN values into None without importing pandas."""
    if value is None:
        return None
    try:
        return None if math.isnan(value) else value
    except TypeError:
        return value


def unsafe_assignment_owners(session, property_code: str) -> list[str]:
    """Find assigned object types containing instances."""
    return [
        item["object_type"]
        for item in property_assignments(session, property_code)
        if session.get_objects(type=item["object_type"]).totalCount
    ]


def assignment_matches(
    row: dict[str, Any], expected: dict[str, Any], ordinal: int
) -> bool:
    return (
        bool(row.get("mandatory")) == bool(expected["mandatory"])
        and clean_assignment_value(row.get("section")) == expected["section"]
        and int(row["ordinal"]) == ordinal
    )


def audit(session) -> dict[str, Any]:
    errors = []
    vocabulary_actions = []
    property_actions = []
    object_actions = []

    for code, terms in VOCABULARIES.items():
        existing = existing_or_none(session.get_vocabulary, code)
        differences = validate_vocabulary(existing, terms)
        if differences:
            errors.append(f"Vocabulary {code}: {'; '.join(differences)}")
        vocabulary_actions.append((code, "reuse" if existing else "create"))

    for code, expected in PROPERTY_TYPES.items():
        existing = existing_or_none(session.get_property_type, code)
        differences = validate_property(existing, expected)
        action = "reuse" if existing else "create"
        if differences and code in IMMUTABLE_PROPERTY_MIGRATIONS:
            owners = unsafe_assignment_owners(session, code)
            if owners:
                errors.append(
                    f"Property type {code} cannot be recreated because these "
                    f"assigned object types contain instances: {owners!r}"
                )
            else:
                action = "recreate"
        elif differences:
            errors.append(f"Property type {code}: {'; '.join(differences)}")
        property_actions.append((code, action))

    for code, expected in OBJECT_TYPES.items():
        existing = existing_or_none(session.get_object_type, code)
        if existing is None:
            object_actions.append((code, "create"))
            continue
        current = assignment_state(existing)
        desired = {item["code"]: item for item in expected["assignments"]}
        changed = set(current) != set(desired) or any(
            not assignment_matches(current[item["code"]], item, ordinal)
            for ordinal, item in enumerate(expected["assignments"], start=1)
            if item["code"] in current
        )
        if changed:
            count = session.get_objects(type=code).totalCount
            if count:
                errors.append(
                    f"Object type {code} has {count} instances; assignments cannot "
                    "be replaced safely."
                )
            object_actions.append((code, "replace assignments"))
        else:
            object_actions.append((code, "reuse"))

    obsolete_actions = []
    for code in OBSOLETE_OBJECT_TYPES:
        existing = existing_or_none(session.get_object_type, code)
        if existing is None:
            obsolete_actions.append((code, "absent"))
            continue
        count = session.get_objects(type=code).totalCount
        if count:
            errors.append(
                f"Obsolete object type {code} has {count} instances; it cannot "
                "be removed safely."
            )
        obsolete_actions.append((code, "delete"))

    return {
        "errors": errors,
        "vocabularies": vocabulary_actions,
        "property_types": property_actions,
        "object_types": object_actions,
        "obsolete_object_types": obsolete_actions,
    }


def create_vocabulary(session, code: str, terms):
    vocabulary = existing_or_none(session.get_vocabulary, code)
    if vocabulary is None:
        vocabulary = session.new_vocabulary(
            code=code,
            description=code.replace("_", " ").title(),
            terms=[
                {"code": term_code, "label": label, "description": label}
                for term_code, label in terms
            ],
        )
        vocabulary.save()
    return vocabulary


def create_property_type(session, expected: dict[str, Any]):
    existing = existing_or_none(session.get_property_type, expected["code"])
    if existing is not None:
        return existing
    kwargs = dict(expected)
    if kwargs.get("vocabulary"):
        kwargs["vocabulary"] = session.get_vocabulary(kwargs["vocabulary"])
    property_type = session.new_property_type(**kwargs)
    for attempt in range(10):
        try:
            if expected.get("multiValue"):
                # pyBIS 6.6 removes multiValue from createPropertyTypes for
                # server versions other than 6, although openBIS 7 supports it.
                request = property_type._new_attrs()
                session._post_request(session.as_v3, request)
            else:
                property_type.save()
            break
        except ValueError as error:
            if "already exists" not in str(error) or attempt == 9:
                raise
            # Property deletion is immediately visible to reads, but its code
            # can remain reserved briefly by the write service.
            time.sleep(1)
    return session.get_property_type(expected["code"], use_cache=False)


def recreate_property_type(session, expected: dict[str, Any]):
    """Recreate an immutable property definition and preserve its assignments."""
    code = expected["code"]
    snapshots = property_assignments(session, code)
    owners = [
        item["object_type"]
        for item in snapshots
        if session.get_objects(type=item["object_type"]).totalCount
    ]
    if owners:
        raise RuntimeError(
            f"Refusing to recreate {code}; assigned types contain instances: {owners!r}"
        )

    for item in snapshots:
        session.get_object_type(item["object_type"], use_cache=False).revoke_property(
            code, force=True
        )

    old_property = session.get_property_type(code, use_cache=False)
    # Property-type deletion is immediate in this openBIS version and returns
    # no deletion ID; unlike object deletion, it must not be confirmed.
    old_property.delete(
        reason=f"Correct immutable definition of {code}",
        permanently=False,
    )
    new_property = create_property_type(session, expected)

    for item in snapshots:
        row = item["assignment"]
        kwargs = {
            "section": clean_assignment_value(row.get("section")),
            "ordinal": int(row["ordinal"]),
            "mandatory": bool(row.get("mandatory")),
            "showInEditView": bool(row.get("showInEditView", True)),
            "showRawValueInForms": bool(row.get("showRawValueInForms", True)),
            "unique": bool(row.get("unique", False)),
        }
        optional = {
            "initialValueForExistingEntities": clean_assignment_value(
                row.get("initialValueForExistingEntities")
            ),
            "plugin": clean_assignment_value(row.get("plugin")),
            "patternType": clean_assignment_value(row.get("patternType")),
            "pattern": clean_assignment_value(row.get("pattern")),
        }
        kwargs.update({key: value for key, value in optional.items() if value})
        session.get_object_type(item["object_type"], use_cache=False).assign_property(
            new_property, **kwargs
        )


def create_object_type(session, code: str, expected: dict[str, Any]):
    existing = existing_or_none(session.get_object_type, code)
    if existing is not None:
        return existing
    object_type = session.new_object_type(
        code=code,
        generatedCodePrefix=expected["prefix"],
        autoGeneratedCode=True,
        subcodeUnique=False,
        listable=True,
        showContainer=False,
        showParents=True,
        showParentMetadata=False,
        description=expected["description"],
    )
    object_type.save()
    return session.get_object_type(code, use_cache=False)


def delete_obsolete_object_type(session, code: str):
    object_type = existing_or_none(session.get_object_type, code)
    if object_type is None:
        return
    count = session.get_objects(type=code).totalCount
    if count:
        raise RuntimeError(f"Refusing to delete populated object type {code}")
    for property_code in assignment_state(object_type):
        object_type.revoke_property(property_code, force=True)
    object_type.delete(
        reason=f"Replace obsolete simulation object type {code}",
        permanently=False,
    )


def apply_object_type_assignments(session, code: str, expected: dict[str, Any]):
    """Make one empty object type's property assignments exact and idempotent."""
    object_type = create_object_type(session, code, expected)
    current = assignment_state(object_type)
    changed = set(current) != {item["code"] for item in expected["assignments"]} or any(
        not assignment_matches(current[item["code"]], item, ordinal)
        for ordinal, item in enumerate(expected["assignments"], start=1)
        if item["code"] in current
    )
    if changed:
        count = session.get_objects(type=code).totalCount
        if count:
            raise RuntimeError(
                f"Refusing to replace assignments for populated object type {code}"
            )
        # Revoke the complete set so openBIS cannot preserve ordinal gaps.
        for property_code in current:
            object_type.revoke_property(property_code, force=True)

    current = assignment_state(object_type)
    for ordinal, item in enumerate(expected["assignments"], start=1):
        if item["code"] in current:
            continue
        object_type.assign_property(
            session.get_property_type(item["code"], use_cache=False),
            section=item["section"],
            ordinal=ordinal,
            mandatory=item["mandatory"],
        )


def apply_schema(session):
    for code, terms in VOCABULARIES.items():
        create_vocabulary(session, code, terms)

    for code in IMMUTABLE_PROPERTY_MIGRATIONS:
        expected = PROPERTY_TYPES[code]
        existing = existing_or_none(session.get_property_type, code)
        if validate_property(existing, expected):
            recreate_property_type(session, expected)

    for expected in PROPERTY_TYPES.values():
        create_property_type(session, expected)

    for code, expected in OBJECT_TYPES.items():
        apply_object_type_assignments(session, code, expected)

    for code in OBSOLETE_OBJECT_TYPES:
        delete_obsolete_object_type(session, code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="openBIS base URL")
    parser.add_argument(
        "--apply", action="store_true", help="Apply the additive schema migration"
    )
    args = parser.parse_args()

    token = getpass.getpass("openBIS token: ")
    session = Openbis(args.url, verify_certificates=False)
    session.set_token(token)
    report = audit(session)
    print(json.dumps(report, indent=2))
    if report["errors"]:
        raise SystemExit("Preflight failed; no changes were applied.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to create the schema.")
        return

    apply_schema(session)
    verification = audit(session)
    print(json.dumps({"verification": verification}, indent=2))
    if verification["errors"]:
        raise SystemExit("Schema creation completed, but verification failed.")


if __name__ == "__main__":
    main()
