from pathlib import Path

import yaml

from schema.openbis_objects import Molecule


def test_molecule_accepts_optional_multiple_molecule_parents():
    first_parent = Molecule(name="first parent")
    second_parent = Molecule(name="second parent")

    standalone = Molecule(name="standalone")
    derived = Molecule(
        name="derived",
        molecules=[first_parent, second_parent],
    )

    assert standalone.molecules == []
    assert derived.molecules == [first_parent, second_parent]
    assert (
        Molecule.model_fields["molecules"].json_schema_extra["metadata"]["type"]
        == "PARENT"
    )


def test_linkml_molecule_parent_slot_is_multivalued_and_optional():
    schema_path = Path(__file__).parents[1] / "schema" / "openBIS_objects_schema.yaml"
    schema = yaml.safe_load(schema_path.read_text())

    assert "molecules" in schema["classes"]["Molecule"]["slots"]
    slot = schema["slots"]["molecules"]
    assert slot["range"] == "Molecule"
    assert slot["multivalued"] is True
    assert slot.get("required", False) is False
    assert slot["annotations"]["openbis_type"] == "OBJECT (PARENT)"


def test_product_concept_uses_molecule_type_and_collection():
    import json

    from schema.openbis_objects import AtomisticModel, ReactionProductConcept

    config_path = Path(__file__).parents[1] / "config" / "openbis_config.json"
    config = json.loads(config_path.read_text())

    assert ReactionProductConcept is Molecule
    assert "reaction_product_concepts" not in AtomisticModel.model_fields
    schema_path = Path(__file__).parents[1] / "schema" / "openBIS_objects_schema.yaml"
    schema = yaml.safe_load(schema_path.read_text())
    assert "ReactionProductConcept" not in schema["classes"]
    assert schema["slots"]["reaction_product_concept"]["range"] == "Molecule"
    assert (
        schema["slots"]["reaction_product_concept"]["annotations"]["openbis_type"]
        == "OBJECT (PARENT)"
    )
    assert config["OpenBIS Types"]["Reaction Product Concept"] == "MOLECULE"
    assert config["Collections"]["Paths"]["Precursor Molecule"].endswith(
        "/PRECURSOR_COLLECTION"
    )
    assert config["Collections"]["Paths"]["Product Molecule"].endswith(
        "/PRODUCT_COLLECTION"
    )


def test_target_schema_documentation_covers_molecular_and_simulation_decisions():
    from src.simulation_schema import OBJECT_TYPES, VOCABULARIES

    repository = Path(__file__).parents[1]
    documentation = (repository / "docs" / "openBIS_schema_documentation.md").read_text()
    simulation_spec = (repository / "docs" / "simulation_object_types.md").read_text()

    assert "This is the normative target schema" in documentation
    assert "`cxsmiles` | CXSMILES" in documentation
    assert "| MOLECULE | 0 | - |" in documentation
    for obsolete_code in (
        "GEOMETRY_OPTIMIZATION",
        "MINIMUM_ENERGY_POTENTIAL",
        "PDOS",
        "POTENTIAL_ENERGY_CALCULATION",
        "SPM",
        "STM_SIMULATION",
    ):
        assert f"* **Code:** `{obsolete_code}`" not in documentation
    assert "MOLECULE_CONCEPT" not in simulation_spec

    for code, definition in OBJECT_TYPES.items():
        assert f"* **Code:** `{code}`" in documentation
        for assignment in definition["assignments"]:
            assert f"`{assignment['code'].lower()}`" in documentation

    for code, terms in VOCABULARIES.items():
        assert f"* **Code:** `{code}`" in documentation
        for term_code, label in terms:
            assert f"| {term_code} | {label} |" in documentation


def test_cxsmiles_migration_is_additive_and_idempotent():
    import pandas as pd

    from schema import add_molecule_cxsmiles

    class PropertyType:
        code = "CXSMILES"
        dataType = "VARCHAR"
        multiValue = False

        def __init__(self, session):
            self.session = session

        def save(self):
            self.session.property_type = self

    class ObjectType:
        def __init__(self):
            self.rows = [
                {
                    "code": "NAME",
                    "section": None,
                    "ordinal": 16,
                    "mandatory": False,
                }
            ]

        def get_property_assignments(self):
            return type("Assignments", (), {"df": pd.DataFrame(self.rows)})()

        def assign_property(self, property_type, **kwargs):
            self.rows.append({"code": property_type.code, **kwargs})

    class Session:
        def __init__(self):
            self.property_type = None
            self.object_type = ObjectType()
            self.created = 0

        def get_property_type(self, code, use_cache=False):
            assert code == "CXSMILES"
            if self.property_type is None:
                raise ValueError("missing")
            return self.property_type

        def new_property_type(self, **kwargs):
            assert kwargs == {
                "code": "CXSMILES",
                "label": "CXSMILES",
                "description": (
                    "Round-trip validated CXSMILES representation of a "
                    "periodic repeat unit"
                ),
                "dataType": "VARCHAR",
                "multiValue": False,
            }
            self.created += 1
            return PropertyType(self)

        def get_object_type(self, code, use_cache=False):
            assert code == "MOLECULE"
            return self.object_type

    session = Session()

    first = add_molecule_cxsmiles.apply(session)
    second = add_molecule_cxsmiles.apply(session)

    assert first["property_exists"] is True
    assert first["assignment_exists"] is True
    assert second["assignment_exists"] is True
    assert session.created == 1
    assert [row["code"] for row in session.object_type.rows] == ["NAME", "CXSMILES"]
    assert session.object_type.rows[0]["ordinal"] == 16
    assert session.object_type.rows[1]["ordinal"] == 17
    assert session.object_type.rows[1]["mandatory"] is False
