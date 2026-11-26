"""Keep the maintained LinkML view and normative result tables consistent."""

from pathlib import Path
import re

import yaml

from schema.generate_simulation_schema import document, serialize_document
from src.simulation_schema import OBJECT_TYPES, PROPERTY_TYPES, VOCABULARIES

ROOT = Path(__file__).resolve().parents[1]


def test_linkml_view_matches_provisioner():
    assert (
        ROOT / "schema/simulation_objects_schema.yaml"
    ).read_text() == serialize_document()
    assert (
        yaml.safe_load((ROOT / "schema/simulation_objects_schema.yaml").read_text())
        == document()
    )


def test_ordered_numeric_simulation_fields_are_openbis_arrays():
    codes = {
        "BIAS_VOLTAGES_V",
        "ELECTRONIC_GAP_EV",
        "FERMI_ENERGY_EV",
        "HEIGHTS_ANGSTROM",
        "ISOVALUES_AU",
        "ORBITAL_ENERGIES_EV",
        "P_TIP_RATIOS",
        "RELATIVE_ENERGIES_EV",
    }
    slots = document()["slots"]
    for code in codes:
        assert PROPERTY_TYPES[code]["dataType"] == "ARRAY_REAL"
        assert not PROPERTY_TYPES[code]["multiValue"]
        slot = slots[code.lower()]
        assert slot["range"] == "float"
        assert slot["multivalued"]
        assert slot["annotations"]["openbis_multi_value"] is False


def test_normative_document_matches_required_result_properties():
    text = (ROOT / "docs/openBIS_schema_documentation.md").read_text()
    for code, obj in OBJECT_TYPES.items():
        # Match the body carrying the object code, independent of display title.
        sections = [
            section
            for section in re.split(r"(?m)^### ", text)
            if re.search(r"\*\*Code:\*\*\s*`?" + code + r"`?(?:\s|$)", section)
        ]
        assert len(sections) == 1, code
        rows = {}
        for line in sections[0].splitlines():
            if line.startswith("| `"):
                cells = [cell.strip().strip("`") for cell in line.split("|")[1:-1]]
                if len(cells) >= 5:
                    rows[cells[0]] = cells
        for assignment in obj["assignments"]:
            prop = PROPERTY_TYPES[assignment["code"]]
            row = rows[assignment["code"].lower()]
            assert row[4] == str(assignment["mandatory"]), (
                code,
                assignment["code"],
            )
            datatype = prop["dataType"]
            if datatype == "SAMPLE":
                datatype = f"OBJECT ({prop.get('sampleType', 'All')})"
            elif datatype == "CONTROLLEDVOCABULARY":
                datatype += f" ({prop['vocabulary']})"
            assert row[3] == datatype, (code, assignment["code"])
            assert row[5] == str(prop["multiValue"]), (code, assignment["code"])


def test_fabio_quick_reference_and_vocabulary_sections_are_current():
    text = (ROOT / "docs/openBIS_schema_documentation.md").read_text()
    quick = text.split("#### 1.7 ")[1].split("#### 1.8 ")[0]
    for code, obj in OBJECT_TYPES.items():
        assert f"`{code}` | `{obj['prefix']}`" in quick
    vocabulary_section = text.split("## 3. Vocabulary Types")[1].split(
        "## 4. Collection Types"
    )[0]
    for code, terms in VOCABULARIES.items():
        sections = [
            section
            for section in re.split(r"(?m)^### ", vocabulary_section)
            if f"**Code:** `{code}`" in section
        ]
        assert len(sections) == 1, code
        rows = {
            line.split("|")[1].strip().strip("`")
            for line in sections[0].splitlines()
            if line.startswith("| ")
        }
        assert {term[0] for term in terms} <= rows, code
