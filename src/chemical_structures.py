"""Validated representations for finite and periodic chemical structures."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors


class PeriodicStructureError(ValueError):
    """Raised when a periodic chemical representation is incomplete or invalid."""


@dataclass(frozen=True)
class AtomSpec:
    """Chemical attributes needed to reproduce an atom in a periodic graph."""

    atomic_number: int
    charge: int = 0
    isotope: int = 0
    radical_electrons: int = 0
    explicit_hydrogens: int | None = None


@dataclass(frozen=True)
class PeriodicGraph:
    """One-dimensional quotient graph for a bracketed repeat unit."""

    atoms: tuple[AtomSpec, ...]
    bonds: tuple[tuple[int, int, int, float | str], ...]


@dataclass(frozen=True)
class PeriodicCxsmiles:
    """A generated CXSMILES value and its round-trip validation evidence."""

    cxsmiles: str
    periodic_key: str
    formula: str
    atoms_per_repeat: int
    crossing_bond_pairs: int


@dataclass(frozen=True)
class ChemicalRepresentation:
    """One validated representation suitable for a MOLECULE object."""

    formula: str
    smiles: str = ""
    cxsmiles: str = ""
    periodic: bool = False
    periodic_key: str = ""
    warning: str = ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _elements(root, name):
    return [element for element in root.iter() if _local_name(element.tag) == name]


def _xy(value: str) -> tuple[float, float]:
    parts = str(value).replace(",", " ").split()
    if len(parts) < 2:
        raise PeriodicStructureError(f"Invalid CDXML coordinate: {value!r}")
    return float(parts[0]), float(parts[1])


def _rdkit_bond_type(order: float | str):
    if order == "dative":
        return Chem.BondType.DATIVE
    if math.isclose(order, 1.0):
        return Chem.BondType.SINGLE
    if math.isclose(order, 1.5):
        return Chem.BondType.AROMATIC
    if math.isclose(order, 2.0):
        return Chem.BondType.DOUBLE
    if math.isclose(order, 3.0):
        return Chem.BondType.TRIPLE
    raise PeriodicStructureError(f"Unsupported bond order {order}")


def _order_from_rdkit(bond) -> float | str:
    if bond.GetBondType() == Chem.BondType.DATIVE:
        return "dative"
    if bond.GetIsAromatic():
        return 1.5
    return float(bond.GetBondTypeAsDouble())


def _canonical_edge(begin: int, end: int, shift: int, order=None):
    if order == "dative":
        return begin, end, shift
    if begin > end:
        return end, begin, -shift
    if begin == end and shift < 0:
        return begin, end, -shift
    return begin, end, shift


def _atom_from_spec(spec: AtomSpec):
    atom = Chem.Atom(spec.atomic_number)
    atom.SetFormalCharge(spec.charge)
    if spec.isotope:
        atom.SetIsotope(spec.isotope)
    if spec.radical_electrons:
        atom.SetNumRadicalElectrons(spec.radical_electrons)
    if spec.explicit_hydrogens is not None:
        atom.SetNumExplicitHs(spec.explicit_hydrogens)
        atom.SetNoImplicit(True)
    return atom


def _atom_spec(atom) -> AtomSpec:
    explicit_hydrogens = None
    if atom.GetNoImplicit() or atom.GetNumExplicitHs():
        explicit_hydrogens = int(atom.GetNumExplicitHs())
    return AtomSpec(
        atomic_number=atom.GetAtomicNum(),
        charge=atom.GetFormalCharge(),
        isotope=atom.GetIsotope(),
        radical_electrons=atom.GetNumRadicalElectrons(),
        explicit_hydrogens=explicit_hydrogens,
    )


def periodic_graph_from_cdxml(
    content: bytes | str,
    group_index: int | None = None,
) -> PeriodicGraph | None:
    """Use the same validated repeat topology as the atomistic CDXML importer."""
    from aiidalab_widgets_empa.cdxml import CdxmlUploadWidget
    from aiidalab_widgets_empa.cdxml_graph import cdxml_root, read_cdxml_graph
    from aiidalab_widgets_empa.cdxml_periodic import identify_repeat

    try:
        root = cdxml_root(content)
        groups = _elements(root, "bracketedgroup")
        if group_index is not None:
            if not 0 <= int(group_index) < len(groups):
                raise PeriodicStructureError(
                    "Bracketed repeat-unit index is out of range"
                )
            selected = groups[int(group_index)]
            selected_ids = set(selected.get("BracketedObjectIDs", "").split())
            options = CdxmlUploadWidget._cdxml_structure_options(content)
            for _, index in options:
                candidate = CdxmlUploadWidget._select_cdxml_structure(content, index)
                candidate_root = cdxml_root(candidate)
                if selected_ids.intersection(
                    node.get("id") for node in candidate_root.iter("n")
                ):
                    root = candidate_root
                    break
            parents = {child: parent for parent in root.iter() for child in parent}
            for group in list(root.iter("bracketedgroup")):
                if group.get("id") != selected.get("id"):
                    parents[group].remove(group)
            content = ET.tostring(root)
        elif len(groups) > 1:
            raise PeriodicStructureError(
                "Exactly one bracketed repeat unit is required for conversion"
            )
        graph = read_cdxml_graph(content)
        repeat = identify_repeat(content, graph)
        if repeat is None:
            return None
        if graph.stereochemistry:
            raise PeriodicStructureError(
                "Encoded periodic stereochemistry is not supported by the SRU graph decoder"
            )
        local = {identifier: index for index, identifier in enumerate(repeat.atom_ids)}
        molecule = graph.rdkit_molecule()
        atoms = tuple(
            _atom_spec(molecule.GetAtomWithIdx(graph.index[identifier]))
            for identifier in repeat.atom_ids
        )
        bonds = tuple(
            (
                *_canonical_edge(
                    local[edge.begin], local[edge.end], edge.shift, edge.type
                ),
                "dative" if edge.type == "dative" else float(edge.type),
            )
            for edge in repeat.edges
        )
        return PeriodicGraph(atoms, bonds)
    except ValueError as exc:
        raise PeriodicStructureError(str(exc)) from exc


def periodic_graphs_from_cdxml(content: bytes | str) -> tuple[PeriodicGraph, ...]:
    """Parse each annotated repeat with shared chemical and crossing validation."""
    from aiidalab_widgets_empa.cdxml_graph import cdxml_root

    root = cdxml_root(content)
    groups = _elements(root, "bracketedgroup")
    if not groups:
        graph = periodic_graph_from_cdxml(content)
        return (graph,) if graph is not None else ()
    return tuple(
        graph
        for index in range(len(groups))
        if (graph := periodic_graph_from_cdxml(content, index)) is not None
    )


def _periodic_cover(graph: PeriodicGraph, repeats: int):
    rw_mol = Chem.RWMol()
    for _cell in range(repeats):
        for spec in graph.atoms:
            rw_mol.AddAtom(_atom_from_spec(spec))

    atoms_per_cell = len(graph.atoms)
    for cell in range(repeats):
        for begin, end, shift, order in graph.bonds:
            first = cell * atoms_per_cell + begin
            second = ((cell + shift) % repeats) * atoms_per_cell + end
            if first == second:
                raise PeriodicStructureError("Periodic cover produced a self bond")
            bond_type = _rdkit_bond_type(order)
            existing = rw_mol.GetBondBetweenAtoms(first, second)
            if existing is None:
                rw_mol.AddBond(first, second, bond_type)
                if bond_type == Chem.BondType.AROMATIC:
                    rw_mol.GetAtomWithIdx(first).SetIsAromatic(True)
                    rw_mol.GetAtomWithIdx(second).SetIsAromatic(True)
            elif existing.GetBondType() != bond_type:
                raise PeriodicStructureError(
                    "Periodic cover produced conflicting duplicate bonds"
                )

    molecule = rw_mol.GetMol()
    try:
        Chem.SanitizeMol(
            molecule,
            sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL
            & ~Chem.SanitizeFlags.SANITIZE_CLEANUP
            & ~getattr(Chem.SanitizeFlags, "SANITIZE_CLEANUP_ORGANOMETALLICS", 0),
        )
    except Exception as exc:
        raise PeriodicStructureError(
            f"The periodic graph has invalid valence: {exc}"
        ) from exc
    return molecule


def _strict_smiles(molecule) -> str:
    molecule = Chem.Mol(molecule)
    Chem.SanitizeMol(molecule)
    molecule = Chem.RemoveHs(molecule)
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def periodic_graph_key(graph: PeriodicGraph) -> str:
    """Canonical chemical graph keys for two covers, without re-kekulization.

    These are opaque graph encodings, not molecular SMILES for rendering or
    fingerprinting. Aromatic edges remain graph labels; explicit H,
    charge, isotope, radicals and directed coordination remain atom/bond labels.
    A cyclic cover can pass valence validation yet exceed RDKit's aromatic
    kekulization search on a second sanitization (fused 5/7-membered systems).
    """
    keys = []
    for repeats in (3, 5):
        molecule = _periodic_cover(graph, repeats)
        encoding = Chem.RWMol()
        for source in molecule.GetAtoms():
            atom = Chem.Atom(source.GetAtomicNum())
            atom.SetFormalCharge(source.GetFormalCharge())
            atom.SetIsotope(source.GetIsotope())
            atom.SetNumRadicalElectrons(source.GetNumRadicalElectrons())
            atom.SetAtomMapNum(source.GetNumRadicalElectrons() + 1)
            atom.SetNumExplicitHs(source.GetNumImplicitHs() + source.GetNumExplicitHs())
            atom.SetNoImplicit(True)
            atom.SetIsAromatic(source.GetIsAromatic())
            encoding.AddAtom(atom)
        for bond in molecule.GetBonds():
            encoding.AddBond(
                bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond.GetBondType()
            )
        keys.append(
            Chem.MolToSmiles(encoding.GetMol(), canonical=True, isomericSmiles=True)
        )
    return "graph-v2:" + "|".join(keys)


def periodic_search_molecule(graph: PeriodicGraph, repeats=3):
    """An open, capped cover for fingerprints; never draw a cyclic cover."""
    size = len(graph.atoms)
    expanded = PeriodicGraph(
        graph.atoms * repeats,
        tuple(
            (
                cell * size + begin,
                ((cell + shift) % repeats) * size + end,
                (cell + shift) // repeats,
                order,
            )
            for cell in range(repeats)
            for begin, end, shift, order in graph.bonds
        ),
    )
    return _capped_repeat_fragment(expanded)[0]


def _formula_per_repeat(graph: PeriodicGraph) -> str:
    repeats = 3
    formula = rdMolDescriptors.CalcMolFormula(_periodic_cover(graph, repeats))
    tokens = re.findall(r"([A-Z][a-z]?)(\d*)", formula)
    if not tokens or "".join(element + count for element, count in tokens) != formula:
        return f"{formula} / {repeats} repeats"
    divided = []
    for element, raw_count in tokens:
        count = int(raw_count or 1)
        if count % repeats:
            return f"{formula} / {repeats} repeats"
        per_repeat = count // repeats
        divided.append(element + (str(per_repeat) if per_repeat != 1 else ""))
    return "".join(divided)


def periodic_formula(graph: PeriodicGraph) -> str:
    """Return the molecular formula per periodic repeat."""
    return _formula_per_repeat(graph)


def _capped_repeat_fragment(graph: PeriodicGraph):
    rw_mol = Chem.RWMol()
    for spec in graph.atoms:
        rw_mol.AddAtom(_atom_from_spec(spec))

    for begin, end, shift, order in graph.bonds:
        if shift == 0:
            rw_mol.AddBond(begin, end, _rdkit_bond_type(order))

    crossing_pairs = []
    for begin, end, shift, order in graph.bonds:
        if shift == 0:
            continue
        if order == "dative":
            raise PeriodicStructureError(
                "CXSMILES encoding of dative bonds across a repeat boundary is not supported"
            )
        if shift not in {-1, 1}:
            raise PeriodicStructureError(
                "Only nearest-neighbour one-dimensional repeats are supported"
            )
        head_atom, tail_atom = (begin, end) if shift == 1 else (end, begin)
        head_dummy = Chem.Atom(0)
        head_dummy.SetNoImplicit(True)
        head_dummy_index = rw_mol.AddAtom(head_dummy)
        rw_mol.AddBond(head_atom, head_dummy_index, _rdkit_bond_type(order))
        head_bond = rw_mol.GetNumBonds() - 1

        tail_dummy = Chem.Atom(0)
        tail_dummy.SetNoImplicit(True)
        tail_dummy_index = rw_mol.AddAtom(tail_dummy)
        rw_mol.AddBond(tail_atom, tail_dummy_index, _rdkit_bond_type(order))
        tail_bond = rw_mol.GetNumBonds() - 1
        crossing_pairs.append((head_bond, tail_bond))

    molecule = rw_mol.GetMol()
    try:
        Chem.SanitizeMol(
            molecule,
            sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL
            & ~Chem.SanitizeFlags.SANITIZE_CLEANUP
            & ~getattr(Chem.SanitizeFlags, "SANITIZE_CLEANUP_ORGANOMETALLICS", 0),
        )
    except Exception as exc:
        raise PeriodicStructureError(
            f"The capped repeat unit has invalid valence: {exc}"
        ) from exc
    return molecule, tuple(crossing_pairs)


def _smiles_parser_params():
    params = Chem.SmilesParserParams()
    params.allowCXSMILES = False
    params.parseName = False
    params.removeHs = False
    return params


def _encode_cxsmiles(graph: PeriodicGraph) -> str:
    molecule, crossing_pairs = _capped_repeat_fragment(graph)
    base_smiles = Chem.MolToSmiles(molecule, canonical=False, isomericSmiles=True)
    output_properties = molecule.GetPropsAsDict(
        includePrivate=True, includeComputed=True
    )
    atom_output_order = list(output_properties["_smilesAtomOutputOrder"])
    bond_output_order = list(output_properties["_smilesBondOutputOrder"])
    atom_position = {
        atom_index: output_index
        for output_index, atom_index in enumerate(atom_output_order)
    }
    bond_position = {
        bond_index: output_index
        for output_index, bond_index in enumerate(bond_output_order)
    }
    repeat_atoms = ",".join(
        str(atom_position[index]) for index in range(len(graph.atoms))
    )
    heads = ",".join(str(bond_position[pair[0]]) for pair in crossing_pairs)
    tails = ",".join(str(bond_position[pair[1]]) for pair in crossing_pairs)
    return f"{base_smiles} |Sg:n:{repeat_atoms}:n:ht:{heads}:{tails}:|"


def _crossing_internal_atom(molecule, bond_index: int, repeat_atoms: set[int]):
    bond = molecule.GetBondWithIdx(int(bond_index))
    begin = bond.GetBeginAtomIdx()
    end = bond.GetEndAtomIdx()
    begin_inside = begin in repeat_atoms
    end_inside = end in repeat_atoms
    if begin_inside == end_inside:
        raise PeriodicStructureError(
            f"S-group bond {bond_index} does not cross the repeat boundary"
        )
    inner = begin if begin_inside else end
    outer = end if begin_inside else begin
    outer_atom = molecule.GetAtomWithIdx(outer)
    if outer_atom.GetAtomicNum() != 0 or outer_atom.GetDegree() != 1:
        raise PeriodicStructureError(
            "Generated periodic CXSMILES requires one terminal '*' cap per crossing bond"
        )
    return inner, _order_from_rdkit(bond)


def _csv_indices(value: str, field: str) -> tuple[int, ...]:
    if not value:
        raise PeriodicStructureError(f"The CXSMILES {field} field is empty")
    try:
        indices = tuple(int(item) for item in value.split(","))
    except ValueError as exc:
        raise PeriodicStructureError(
            f"The CXSMILES {field} field contains a non-integer index"
        ) from exc
    if len(indices) != len(set(indices)):
        raise PeriodicStructureError(
            f"The CXSMILES {field} field contains duplicate indices"
        )
    return indices


def periodic_graph_from_cxsmiles(cxsmiles: str) -> PeriodicGraph:
    """Decode the capped SRU convention generated by this application.

    RDKit 2025.09 writes ChemAxon bond indexes for polymer S-groups but reads
    some ring-closure indexes as internal RDKit bond indexes. Parsing the
    narrow generated extension here avoids silently losing ladder pairings.
    """
    text = str(cxsmiles).strip()
    base_smiles, separator, extension = text.partition(" |")
    if not separator or not extension.endswith("|"):
        raise PeriodicStructureError("CXSMILES lacks an extended SRU field")
    fields = extension[:-1].split(":")
    if len(fields) != 8 or fields[0:2] != ["Sg", "n"] or fields[-1]:
        raise PeriodicStructureError(
            "Only one generated CXSMILES SRU extension is supported"
        )
    repeat_field, label, connectivity, head_field, tail_field = fields[2:7]
    if label not in {"", "n"}:
        raise PeriodicStructureError("The SRU label must be 'n'")
    if connectivity.lower() != "ht":
        raise PeriodicStructureError("The SRU must use head-to-tail connectivity")

    molecule = Chem.MolFromSmiles(base_smiles, _smiles_parser_params())
    if molecule is None:
        raise PeriodicStructureError("Invalid CXSMILES molecular graph")
    if any(
        atom.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
        for atom in molecule.GetAtoms()
    ) or any(
        bond.GetStereo() != Chem.BondStereo.STEREONONE for bond in molecule.GetBonds()
    ):
        raise PeriodicStructureError(
            "Encoded periodic stereochemistry is not supported by the SRU graph decoder"
        )
    rewritten = Chem.MolToSmiles(molecule, canonical=False, isomericSmiles=True)
    if rewritten != base_smiles:
        raise PeriodicStructureError(
            "The CXSMILES base graph is not stable in the installed RDKit"
        )
    output_properties = molecule.GetPropsAsDict(
        includePrivate=True, includeComputed=True
    )
    bond_output_order = tuple(
        int(index) for index in output_properties["_smilesBondOutputOrder"]
    )
    # The finite capped fragment's aromatic subset is not the bulk aromatic
    # subset. Recover its explicit valid orders before building periodic covers.
    Chem.Kekulize(molecule, clearAromaticFlags=True)

    ordered_atoms = tuple(sorted(_csv_indices(repeat_field, "repeat atom")))
    if ordered_atoms[-1] >= molecule.GetNumAtoms() or ordered_atoms[0] < 0:
        raise PeriodicStructureError("The SRU refers to an out-of-range atom")
    repeat_atoms = set(ordered_atoms)
    local_index = {atom_index: index for index, atom_index in enumerate(ordered_atoms)}
    atom_specs = tuple(
        _atom_spec(molecule.GetAtomWithIdx(index)) for index in ordered_atoms
    )

    head_indices = _csv_indices(head_field, "head crossing bond")
    tail_indices = _csv_indices(tail_field, "tail crossing bond")
    if len(head_indices) != len(tail_indices):
        raise PeriodicStructureError(
            "The SRU has different numbers of head and tail crossing bonds"
        )
    cx_bond_indices = head_indices + tail_indices
    if min(cx_bond_indices) < 0 or max(cx_bond_indices) >= len(bond_output_order):
        raise PeriodicStructureError("The SRU refers to an out-of-range bond")
    crossing_pairs = tuple(
        (bond_output_order[head], bond_output_order[tail])
        for head, tail in zip(head_indices, tail_indices, strict=True)
    )

    edge_orders: dict[tuple[int, int, int], float] = {}

    def add_edge(begin, end, shift, order):
        key = _canonical_edge(begin, end, shift, order)
        previous = edge_orders.get(key)
        if previous is not None and previous != order:
            raise PeriodicStructureError(f"Conflicting orders for periodic edge {key}")
        edge_orders[key] = order

    all_crossing_bonds = set()
    for bond in molecule.GetBonds():
        begin = bond.GetBeginAtomIdx()
        end = bond.GetEndAtomIdx()
        if begin in repeat_atoms and end in repeat_atoms:
            add_edge(
                local_index[begin],
                local_index[end],
                0,
                _order_from_rdkit(bond),
            )
        elif (begin in repeat_atoms) != (end in repeat_atoms):
            all_crossing_bonds.add(bond.GetIdx())

    paired_bonds = set()
    for head_bond, tail_bond in crossing_pairs:
        head_atom, head_order = _crossing_internal_atom(
            molecule, head_bond, repeat_atoms
        )
        tail_atom, tail_order = _crossing_internal_atom(
            molecule, tail_bond, repeat_atoms
        )
        if head_order != tail_order:
            raise PeriodicStructureError(
                "The two caps of a periodic bond have different bond orders"
            )
        add_edge(
            local_index[head_atom],
            local_index[tail_atom],
            1,
            head_order,
        )
        paired_bonds.update((head_bond, tail_bond))

    if len(paired_bonds) != 2 * len(crossing_pairs):
        raise PeriodicStructureError("A crossing bond is paired more than once")
    if all_crossing_bonds != paired_bonds:
        raise PeriodicStructureError(
            "The SRU contains unpaired or unrelated crossing bonds"
        )
    bonds = tuple(
        (begin, end, shift, order)
        for (begin, end, shift), order in sorted(edge_orders.items())
    )
    return PeriodicGraph(atom_specs, bonds)


def generate_periodic_cxsmiles(content: bytes | str) -> PeriodicCxsmiles:
    """Generate CXSMILES and prove that it retains the CDXML periodic graph."""
    graph = periodic_graph_from_cdxml(content)
    if graph is None:
        raise PeriodicStructureError("The CDXML has no bracketed repeat unit")
    expected_key = periodic_graph_key(graph)
    first_encoding = _encode_cxsmiles(graph)
    first_decoded = periodic_graph_from_cxsmiles(first_encoding)
    if periodic_graph_key(first_decoded) != expected_key:
        raise PeriodicStructureError(
            "Generated CXSMILES failed periodic graph round-trip validation"
        )

    # Normalize the atom list and head/tail pair order in the generated SRU.
    cxsmiles = _encode_cxsmiles(first_decoded)
    decoded = periodic_graph_from_cxsmiles(cxsmiles)
    if (
        periodic_graph_key(decoded) != expected_key
        or _encode_cxsmiles(decoded) != cxsmiles
    ):
        raise PeriodicStructureError(
            "Generated CXSMILES is not stable after validated SRU round trip"
        )
    crossings = sum(shift != 0 for _, _, shift, _ in graph.bonds)
    return PeriodicCxsmiles(
        cxsmiles=cxsmiles,
        periodic_key=expected_key,
        formula=_formula_per_repeat(graph),
        atoms_per_repeat=len(graph.atoms),
        crossing_bond_pairs=crossings,
    )


def representation_from_smiles(smiles: str) -> ChemicalRepresentation:
    """Validate and canonicalize a finite-molecule SMILES value."""
    molecule = Chem.MolFromSmiles(str(smiles))
    if molecule is None:
        raise ValueError("Invalid SMILES")
    molecule = Chem.RemoveHs(molecule)
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    return ChemicalRepresentation(
        formula=rdMolDescriptors.CalcMolFormula(molecule),
        smiles=canonical,
    )


def representation_from_cdxml(content: bytes | str) -> ChemicalRepresentation:
    """Return either finite SMILES or validated periodic CXSMILES from CDXML."""
    periodic_graph = periodic_graph_from_cdxml(content)
    if periodic_graph is not None:
        generated = generate_periodic_cxsmiles(content)
        return ChemicalRepresentation(
            formula=generated.formula,
            cxsmiles=generated.cxsmiles,
            periodic=True,
            periodic_key=generated.periodic_key,
        )

    from aiidalab_widgets_empa.cdxml import CdxmlUploadWidget
    from aiidalab_widgets_empa.cdxml_graph import read_cdxml_graph

    options = CdxmlUploadWidget._cdxml_structure_options(content)
    if len(options) > 1:
        raise ValueError(
            "The CDXML contains multiple structures; select one drawing first"
        )
    graph = read_cdxml_graph(content)
    molecule = graph.rdkit_molecule()
    # Native CDXML stereochemistry is useful for search, although the atomistic
    # importer deliberately does not reconstruct a stereospecific 3D conformer.
    if graph.stereochemistry:
        decoded = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        native = tuple(Chem.MolsFromCDXML(decoded, sanitize=True, removeHs=False))
        if len(native) != 1:
            raise ValueError(
                "The encoded CDXML stereochemistry cannot be read unambiguously"
            )
        if rdMolDescriptors.CalcMolFormula(
            native[0]
        ) != rdMolDescriptors.CalcMolFormula(molecule):
            raise ValueError(
                "Native stereochemistry reader disagrees with the validated atom/H graph"
            )
        molecule = native[0]
    warning = ""
    if graph.coordination_interpretations():
        warning = "Single N/O-metal lines interpreted as coordination; original drawing and declared H retained"
    finite = representation_from_smiles(
        Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    )
    return ChemicalRepresentation(
        formula=finite.formula, smiles=finite.smiles, warning=warning
    )
