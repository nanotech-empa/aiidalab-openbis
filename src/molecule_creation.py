"""Validated creation of finite and periodic openBIS MOLECULE records."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src import utils
from src.chemical_structures import ChemicalRepresentation, representation_from_cdxml

MOLECULE_TYPE = "MOLECULE"


class MoleculeCreationError(RuntimeError):
    """Raised when a validated molecular concept cannot be created safely."""


class PartialMoleculeCreationError(MoleculeCreationError):
    """Raised when the object exists but one or more datasets failed to upload."""

    def __init__(
        self, permid: str, completed_datasets: tuple[str, ...], error: Exception
    ):
        self.permid = str(permid)
        self.completed_datasets = completed_datasets
        completed = ", ".join(completed_datasets) or "none"
        super().__init__(
            f"MOLECULE {self.permid} was created, but its dataset upload failed "
            f"after: {completed}. Do not create another object; repair this record. "
            f"{type(error).__name__}: {error}"
        )


def _object_type(session):
    try:
        return session.get_object_type(MOLECULE_TYPE, use_cache=False)
    except TypeError:
        return session.get_object_type(MOLECULE_TYPE)


def assigned_property_codes(session) -> set[str]:
    """Return upper-case property codes assigned to MOLECULE."""
    assignments = _object_type(session).get_property_assignments()
    frame = getattr(assignments, "df", None)
    if frame is not None:
        records = frame.to_dict(orient="records")
    else:
        records = assignments
    return {
        str(
            record.get("code")
            or record.get("propertyTypeCode")
            or record.get("propertyType")
        ).upper()
        for record in records
    }


def validate_molecule_schema(session, periodic: bool) -> None:
    """Fail before writing if the live MOLECULE schema lacks required fields."""
    representation_code = "CXSMILES" if periodic else "SMILES"
    required = {"NAME", "SUM_FORMULA", representation_code}
    missing = sorted(required - assigned_property_codes(session))
    if missing:
        raise MoleculeCreationError(
            "The live MOLECULE type is missing required property assignment(s): "
            + ", ".join(missing)
        )


def _validated_representation(
    cdxml: bytes,
    expected: ChemicalRepresentation | None,
) -> ChemicalRepresentation:
    representation = representation_from_cdxml(cdxml)
    if expected is not None:
        actual_identity = (
            representation.periodic,
            representation.periodic_key,
            representation.smiles,
            representation.cxsmiles,
            representation.formula,
        )
        expected_identity = (
            expected.periodic,
            expected.periodic_key,
            expected.smiles,
            expected.cxsmiles,
            expected.formula,
        )
        if actual_identity != expected_identity:
            raise MoleculeCreationError(
                "The CDXML no longer matches the reviewed molecular representation"
            )
    return representation


def create_molecule_from_cdxml(
    session,
    *,
    collection: str,
    name: str,
    cdxml: bytes,
    png: bytes,
    filename: str = "generated.cdxml",
    description: str = "",
    comments: str = "",
    expected_representation: ChemicalRepresentation | None = None,
):
    """Create one MOLECULE and attach the exact reviewed CDXML and PNG.

    Schema and representation validation happen before the first remote write.
    A failure after object creation reports the permanent ID so callers cannot
    accidentally create a duplicate while repairing an attachment.
    """
    clean_name = str(name).strip()
    if not clean_name:
        raise MoleculeCreationError("Name is required")
    cdxml_bytes = bytes(cdxml)
    png_bytes = bytes(png)
    if not cdxml_bytes:
        raise MoleculeCreationError("CDXML content is required")
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MoleculeCreationError("The generated sketch is not a valid PNG")

    representation = _validated_representation(cdxml_bytes, expected_representation)
    validate_molecule_schema(session, representation.periodic)

    props = {
        "name": clean_name,
        "sum_formula": representation.formula,
    }
    if description.strip():
        props["description"] = description.strip()
    if comments.strip():
        props["comments"] = comments.strip()
    if representation.periodic:
        props["cxsmiles"] = representation.cxsmiles
    else:
        props["smiles"] = representation.smiles

    molecule = utils.create_openbis_object(
        session,
        type=MOLECULE_TYPE,
        collection=collection,
        props=props,
    )
    permid = str(getattr(molecule, "permId", "unknown"))
    completed: list[str] = []
    safe_cdxml_name = Path(filename).name or "generated.cdxml"
    if Path(safe_cdxml_name).suffix.lower() != ".cdxml":
        safe_cdxml_name += ".cdxml"
    safe_png_name = f"{Path(safe_cdxml_name).stem}.png"

    try:
        with tempfile.TemporaryDirectory(prefix="aiidalab-openbis-molecule-") as folder:
            cdxml_path = Path(folder) / safe_cdxml_name
            png_path = Path(folder) / safe_png_name
            cdxml_path.write_bytes(cdxml_bytes)
            png_path.write_bytes(png_bytes)
            utils.create_openbis_dataset(
                session,
                sample=molecule,
                type="ATTACHMENT",
                files=[str(cdxml_path)],
                props={"name": "Chemical structure (CDXML)"},
            )
            completed.append("ATTACHMENT")
            utils.create_openbis_dataset(
                session,
                sample=molecule,
                type="ELN_PREVIEW",
                files=[str(png_path)],
                props={"name": "Chemical sketch"},
            )
            completed.append("ELN_PREVIEW")
    except Exception as exc:
        raise PartialMoleculeCreationError(permid, tuple(completed), exc) from exc

    return molecule
