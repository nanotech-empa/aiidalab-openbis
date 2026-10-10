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
    bonds: tuple[tuple[int, int, int, float], ...]


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


def _bond_order(value: str | None) -> float:
    if not value:
        return 1.0
    aliases = {"1 1/2": 1.5, "aromatic": 1.5, "dative": 1.0}
    text = str(value).strip().lower()
    if text in aliases:
        return aliases[text]
    try:
        return float(text)
    except ValueError as exc:
        raise PeriodicStructureError(
            f"Unsupported CDXML bond order {value!r}"
        ) from exc


def _rdkit_bond_type(order: float):
    if math.isclose(order, 1.0):
        return Chem.BondType.SINGLE
    if math.isclose(order, 1.5):
        return Chem.BondType.AROMATIC
    if math.isclose(order, 2.0):
        return Chem.BondType.DOUBLE
    if math.isclose(order, 3.0):
        return Chem.BondType.TRIPLE
    raise PeriodicStructureError(f"Unsupported bond order {order}")


def _order_from_rdkit(bond) -> float:
    if bond.GetIsAromatic():
        return 1.5
    return float(bond.GetBondTypeAsDouble())


def _canonical_edge(begin: int, end: int, shift: int):
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
    """Parse one bracketed one-dimensional repeat unit in CDXML."""
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise PeriodicStructureError(f"Invalid CDXML: {exc}") from exc

    groups = _elements(root, "bracketedgroup")
    if not groups:
        return None
    if group_index is None:
        if len(groups) != 1:
            raise PeriodicStructureError(
                "Exactly one bracketed repeat unit is required for conversion"
            )
        group = groups[0]
    else:
        try:
            group = groups[int(group_index)]
        except (IndexError, ValueError) as exc:
            raise PeriodicStructureError(
                f"Bracketed repeat-unit index {group_index!r} is out of range"
            ) from exc
    central_ids = tuple(group.attrib.get("BracketedObjectIDs", "").split())
    if not central_ids:
        raise PeriodicStructureError("The bracketed group contains no atom IDs")
    if len(central_ids) != len(set(central_ids)):
        raise PeriodicStructureError("The bracketed group contains duplicate atom IDs")
    central_set = set(central_ids)

    nodes = {
        node.attrib["id"]: node
        for node in _elements(root, "n")
        if "id" in node.attrib
    }
    missing = central_set.difference(nodes)
    if missing:
        raise PeriodicStructureError(
            f"BracketedObjectIDs refer to missing nodes: {sorted(missing)}"
        )
    try:
        positions = {
            node_id: _xy(node.attrib["p"])
            for node_id, node in nodes.items()
        }
    except KeyError as exc:
        raise PeriodicStructureError(
            f"CDXML node {exc.args[0]!r} has no position"
        ) from exc

    graphics = {
        graphic.attrib["id"]: graphic
        for graphic in _elements(root, "graphic")
        if "id" in graphic.attrib
    }
    attachment_centres = []
    crossing = []
    attachments = [
        item
        for item in group.iter()
        if _local_name(item.tag) == "bracketattachment"
    ]
    for attachment in attachments:
        graphic = graphics.get(attachment.attrib.get("GraphicID", ""))
        if graphic is not None and graphic.attrib.get("BoundingBox"):
            values = [
                float(value) for value in graphic.attrib["BoundingBox"].split()
            ]
            if len(values) == 4:
                attachment_centres.append(
                    ((values[0] + values[2]) / 2, (values[1] + values[3]) / 2)
                )
        crossing.extend(
            item
            for item in attachment.iter()
            if _local_name(item.tag) == "crossingbond"
        )
    if len(attachment_centres) < 2 or not crossing:
        raise PeriodicStructureError(
            "The periodic bracket needs two attachments and crossing bonds"
        )

    pair = max(
        (
            (first, second)
            for index, first in enumerate(attachment_centres)
            for second in attachment_centres[index + 1 :]
        ),
        key=lambda item: (item[1][0] - item[0][0]) ** 2
        + (item[1][1] - item[0][1]) ** 2,
    )
    period = (pair[1][0] - pair[0][0], pair[1][1] - pair[0][1])
    period_length = math.hypot(*period)
    if period_length <= 1e-8:
        raise PeriodicStructureError("The two periodic brackets are coincident")

    def numeric_id(value):
        try:
            return (0, int(value))
        except ValueError:
            return (1, value)

    ordered_ids = tuple(sorted(central_ids, key=numeric_id))
    local_index = {node_id: index for index, node_id in enumerate(ordered_ids)}
    atom_specs = []
    for node_id in ordered_ids:
        attributes = nodes[node_id].attrib
        radical = str(attributes.get("Radical", "")).lower()
        radical_electrons = 1 if radical in {"doublet", "1"} else 0
        atom_specs.append(
            AtomSpec(
                atomic_number=int(attributes.get("Element", 6)),
                charge=int(attributes.get("Charge", 0)),
                isotope=int(attributes.get("Isotope", 0)),
                radical_electrons=radical_electrons,
                explicit_hydrogens=(
                    int(attributes["NumHydrogens"])
                    if "NumHydrogens" in attributes
                    else None
                ),
            )
        )

    bonds_by_id = {
        bond.attrib["id"]: bond
        for bond in _elements(root, "b")
        if "id" in bond.attrib
    }
    edge_orders: dict[tuple[int, int, int], float] = {}

    def add_edge(begin_id, end_id, shift, order):
        begin = local_index[begin_id]
        end = local_index[end_id]
        key = _canonical_edge(begin, end, int(shift))
        previous = edge_orders.get(key)
        if previous is not None and not math.isclose(previous, order):
            raise PeriodicStructureError(
                f"Conflicting orders for periodic edge {key}"
            )
        edge_orders[key] = order

    for bond in bonds_by_id.values():
        begin_id = bond.attrib.get("B")
        end_id = bond.attrib.get("E")
        if begin_id in central_set and end_id in central_set:
            add_edge(begin_id, end_id, 0, _bond_order(bond.attrib.get("Order")))

    central_positions = {node_id: positions[node_id] for node_id in ordered_ids}
    period_unit = (period[0] / period_length, period[1] / period_length)

    def chemical_signature(node_id):
        attributes = nodes[node_id].attrib
        return (
            int(attributes.get("Element", 6)),
            int(attributes.get("Charge", 0)),
            int(attributes.get("Isotope", 0)),
        )

    crossing_data = []
    for item in crossing:
        bond = bonds_by_id.get(item.attrib.get("BondID", ""))
        inner_id = item.attrib.get("InnerAtomID")
        if bond is None or inner_id not in central_set:
            raise PeriodicStructureError("Invalid crossing-bond reference")
        endpoints = (bond.attrib.get("B"), bond.attrib.get("E"))
        if inner_id not in endpoints:
            raise PeriodicStructureError(
                "InnerAtomID is not an endpoint of its crossing bond"
            )
        outer_id = endpoints[1] if endpoints[0] == inner_id else endpoints[0]
        if outer_id not in positions or outer_id not in nodes:
            raise PeriodicStructureError(f"Missing outer node {outer_id}")

        outer = positions[outer_id]
        candidates = []
        for shift in (-1, 1):
            for candidate_id, candidate in central_positions.items():
                if chemical_signature(candidate_id) != chemical_signature(outer_id):
                    continue
                implied = (
                    (outer[0] - candidate[0]) / shift,
                    (outer[1] - candidate[1]) / shift,
                )
                longitudinal = (
                    implied[0] * period_unit[0]
                    + implied[1] * period_unit[1]
                )
                perpendicular = abs(
                    implied[0] * period_unit[1]
                    - implied[1] * period_unit[0]
                )
                if not 0.5 * period_length <= longitudinal <= 1.5 * period_length:
                    continue
                if perpendicular > max(1.0, 0.15 * period_length):
                    continue
                annotation_error = math.hypot(
                    implied[0] - period[0], implied[1] - period[1]
                )
                candidates.append(
                    (annotation_error, candidate_id, shift, implied[0], implied[1])
                )
        if not candidates:
            raise PeriodicStructureError(
                f"Cannot map outer node {outer_id} into the bracketed repeat unit"
            )
        crossing_data.append((bond, inner_id, outer_id, candidates))

    # Bracket graphics are movable annotations, so their separation is only an
    # approximate period. Each copied outer atom implies an exact translation;
    # choose the mappings that agree on one common translation vector.
    hypotheses = {
        (round(candidate[3], 8), round(candidate[4], 8))
        for _bond, _inner, _outer, candidates in crossing_data
        for candidate in candidates
    }
    solutions = []
    for hypothesis in hypotheses:
        selected = []
        consistency = 0.0
        for _bond, _inner, _outer, candidates in crossing_data:
            candidate = min(
                candidates,
                key=lambda value: math.hypot(
                    value[3] - hypothesis[0], value[4] - hypothesis[1]
                ),
            )
            residual = math.hypot(
                candidate[3] - hypothesis[0], candidate[4] - hypothesis[1]
            )
            consistency += residual**2
            selected.append(candidate)
        annotation_error = math.hypot(
            hypothesis[0] - period[0], hypothesis[1] - period[1]
        )
        score = consistency + 1e-4 * annotation_error**2
        solutions.append((score, consistency, annotation_error, hypothesis, selected))
    solutions.sort(key=lambda value: value[:3])
    _score, consistency, annotation_error, inferred_period, selected = solutions[0]
    inferred_length = math.hypot(*inferred_period)
    consistency_tolerance = max(0.25, 0.03 * inferred_length)
    if len(crossing_data) == 1:
        if annotation_error > max(0.25, 0.08 * period_length):
            raise PeriodicStructureError(
                "A single crossing bond does not determine a reliable period"
            )
    elif math.sqrt(consistency / len(crossing_data)) > consistency_tolerance:
        raise PeriodicStructureError(
            "Crossing bonds do not imply one consistent translation vector"
        )

    for (bond, inner_id, _outer_id, _candidates), candidate in zip(
        crossing_data, selected, strict=True
    ):
        _error, target_id, shift, _period_x, _period_y = candidate
        add_edge(
            inner_id,
            target_id,
            shift,
            _bond_order(bond.attrib.get("Order")),
        )

    bonds = tuple(
        (begin, end, shift, order)
        for (begin, end, shift), order in sorted(edge_orders.items())
    )
    if not any(shift for _, _, shift, _ in bonds):
        raise PeriodicStructureError("The bracket has no periodic graph edge")
    return PeriodicGraph(tuple(atom_specs), bonds)


def periodic_graphs_from_cdxml(content: bytes | str) -> tuple[PeriodicGraph, ...]:
    """Parse every bracketed repeat unit for read-only search indexing."""
    decoded = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise PeriodicStructureError(f"Invalid CDXML: {exc}") from exc
    count = len(_elements(root, "bracketedgroup"))
    return tuple(
        periodic_graph_from_cdxml(decoded, group_index=index)
        for index in range(count)
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
        Chem.SanitizeMol(molecule)
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
    """Return an atom-order and repeat-origin independent periodic key."""
    key3 = _strict_smiles(_periodic_cover(graph, 3))
    key5 = _strict_smiles(_periodic_cover(graph, 5))
    return f"{key3}|{key5}"


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
        Chem.SanitizeMol(molecule)
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
    base_smiles = Chem.MolToSmiles(
        molecule, canonical=False, isomericSmiles=True
    )
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
    rewritten = Chem.MolToSmiles(
        molecule, canonical=False, isomericSmiles=True
    )
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

    ordered_atoms = tuple(sorted(_csv_indices(repeat_field, "repeat atom")))
    if ordered_atoms[-1] >= molecule.GetNumAtoms() or ordered_atoms[0] < 0:
        raise PeriodicStructureError("The SRU refers to an out-of-range atom")
    repeat_atoms = set(ordered_atoms)
    local_index = {
        atom_index: index for index, atom_index in enumerate(ordered_atoms)
    }
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
        key = _canonical_edge(begin, end, shift)
        previous = edge_orders.get(key)
        if previous is not None and not math.isclose(previous, order):
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
        if not math.isclose(head_order, tail_order):
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
    if periodic_graph_key(decoded) != expected_key or _encode_cxsmiles(decoded) != cxsmiles:
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
    canonical = Chem.MolToSmiles(
        molecule, canonical=True, isomericSmiles=True
    )
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

    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    try:
        molecules = tuple(
            Chem.MolsFromCDXML(content, sanitize=True, removeHs=False)
        )
    except Exception as exc:
        raise ValueError(f"Invalid molecular CDXML: {exc}") from exc
    if not molecules:
        raise ValueError("RDKit found no molecule in the CDXML")
    molecule = max(molecules, key=lambda item: item.GetNumHeavyAtoms())
    warning = ""
    if len(molecules) > 1:
        warning = f"Selected the largest of {len(molecules)} CDXML fragments"
    finite = representation_from_smiles(
        Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    )
    return ChemicalRepresentation(
        formula=finite.formula,
        smiles=finite.smiles,
        warning=warning,
    )
