"""Generate idealized CDXML from a planar 1D-periodic AiiDA structure."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, replace

import numpy as np
from aiida import orm
from ase.neighborlist import natural_cutoffs, neighbor_list
from scipy.optimize import Bounds, LinearConstraint, least_squares, milp

VALENCE = {"C": 4}
REFERENCE_LENGTHS = {("C", "C", 1): 1.47, ("C", "C", 2): 1.34}


@dataclass(frozen=True)
class PeriodicBond:
    """An undirected bond in the quotient graph."""

    begin: int
    end: int
    shift: int
    distance: float
    order: int = 1


def load_atoms(identifier: str):
    """Load a StructureData node, or the structure input of a process node."""
    node = orm.load_node(int(identifier) if identifier.isdecimal() else identifier)
    structure = node if isinstance(node, orm.StructureData) else node.inputs.structure
    return structure, structure.get_ase()


def canonical_edge(begin: int, end: int, shift: tuple[int, ...]):
    direct = (begin, end, shift)
    reverse = (end, begin, tuple(-value for value in shift))
    return min(direct, reverse)


def perceive_graph(atoms):
    """Infer the periodic graph from covalent radii and explicit H atoms."""
    cutoffs = natural_cutoffs(atoms, mult=1.15)
    begins, ends, distances, shifts = neighbor_list("ijdS", atoms, cutoffs)

    raw_edges = []
    seen = set()
    for begin, end, distance, shift in zip(begins, ends, distances, shifts):
        key = canonical_edge(int(begin), int(end), tuple(map(int, shift)))
        if key in seen:
            continue
        seen.add(key)
        raw_edges.append((*key, float(distance)))

    nonzero_axes = {
        axis
        for _, _, shift, _ in raw_edges
        for axis, value in enumerate(shift)
        if value
    }
    if len(nonzero_axes) != 1:
        raise ValueError(
            "The CDXML generator requires exactly one bonded periodic direction; "
            f"found axes {sorted(nonzero_axes)}."
        )
    periodic_axis = nonzero_axes.pop()

    heavy_indices = [index for index, atom in enumerate(atoms) if atom.symbol != "H"]
    if {atoms[index].symbol for index in heavy_indices} != {"C"}:
        raise ValueError("The CDXML generator currently supports C/H structures only.")

    explicit_h = Counter()
    bonds = []
    for begin, end, shift, distance in raw_edges:
        symbols = {atoms[begin].symbol, atoms[end].symbol}
        if symbols == {"C"}:
            off_axis = tuple(
                value for axis, value in enumerate(shift) if axis != periodic_axis
            )
            if any(off_axis):
                raise ValueError("A bond crosses a second periodic direction.")
            bonds.append(
                PeriodicBond(begin, end, shift[periodic_axis], distance)
            )
        elif symbols == {"C", "H"}:
            carbon = begin if atoms[begin].symbol == "C" else end
            explicit_h[carbon] += 1
        else:
            raise ValueError(
                f"Unsupported bond {atoms[begin].symbol}-{atoms[end].symbol}."
            )

    # Look beyond the strict covalent cutoff only for mutually unique pairs of
    # carbon atoms that both lack an H and a third heavy-atom neighbour.  Such
    # bonds are reported separately because a production UI should ask for
    # confirmation whenever more than one candidate exists.
    degree = Counter()
    for bond in bonds:
        degree[bond.begin] += 1
        degree[bond.end] += 1
    existing = {(bond.begin, bond.end, bond.shift) for bond in bonds}
    wide_begins, wide_ends, wide_distances, wide_shifts = neighbor_list(
        "ijdS", atoms, 2.25
    )
    candidate_seen = set()
    candidates = []
    for begin, end, distance, shift in zip(
        wide_begins, wide_ends, wide_distances, wide_shifts
    ):
        key = canonical_edge(int(begin), int(end), tuple(map(int, shift)))
        if key in candidate_seen:
            continue
        candidate_seen.add(key)
        begin, end, shift = key
        if atoms[begin].symbol != "C" or atoms[end].symbol != "C":
            continue
        off_axis = tuple(
            value for axis, value in enumerate(shift) if axis != periodic_axis
        )
        if any(off_axis):
            continue
        scalar_key = (begin, end, shift[periodic_axis])
        if scalar_key in existing:
            continue
        if degree[begin] + explicit_h[begin] >= 3:
            continue
        if degree[end] + explicit_h[end] >= 3:
            continue
        candidates.append(
            PeriodicBond(begin, end, shift[periodic_axis], float(distance))
        )

    by_atom = defaultdict(list)
    for candidate in candidates:
        by_atom[candidate.begin].append(candidate)
        by_atom[candidate.end].append(candidate)
    inferred_long_bonds = []
    for candidate in candidates:
        if len(by_atom[candidate.begin]) != 1 or len(by_atom[candidate.end]) != 1:
            continue
        if degree[candidate.begin] >= 3 or degree[candidate.end] >= 3:
            continue
        bonds.append(candidate)
        inferred_long_bonds.append(candidate)
        degree[candidate.begin] += 1
        degree[candidate.end] += 1

    return (
        periodic_axis,
        heavy_indices,
        explicit_h,
        bonds,
        inferred_long_bonds,
        candidates,
    )


def assign_bond_orders(
    atoms, heavy_indices, explicit_h, bonds, radical_electrons=None
):
    """Find a deterministic single/double assignment satisfying carbon valence."""
    radical_electrons = radical_electrons or {}
    orders = (1, 2)
    n_variables = len(bonds) * len(orders)
    objective = np.zeros(n_variables)
    rows = []
    lower = []
    upper = []

    for edge_index, bond in enumerate(bonds):
        row = np.zeros(n_variables)
        pair = tuple(sorted((atoms[bond.begin].symbol, atoms[bond.end].symbol)))
        for order_index, order in enumerate(orders):
            variable = edge_index * len(orders) + order_index
            row[variable] = 1
            reference = REFERENCE_LENGTHS[(*pair, order)]
            objective[variable] = (bond.distance - reference) ** 2
            objective[variable] += variable * 1.0e-10
        rows.append(row)
        lower.append(1)
        upper.append(1)

    for atom_index in heavy_indices:
        row = np.zeros(n_variables)
        for edge_index, bond in enumerate(bonds):
            if atom_index not in (bond.begin, bond.end):
                continue
            for order_index, order in enumerate(orders):
                row[edge_index * len(orders) + order_index] = order
        target = (
            VALENCE[atoms[atom_index].symbol]
            - explicit_h[atom_index]
            - radical_electrons.get(atom_index, 0)
        )
        rows.append(row)
        lower.append(target)
        upper.append(target)

    result = milp(
        objective,
        integrality=np.ones(n_variables),
        bounds=Bounds(0, 1),
        constraints=LinearConstraint(np.asarray(rows), lower, upper),
        options={"time_limit": 30},
    )
    if not result.success:
        raise ValueError(f"No single/double valence solution: {result.message}")

    assigned = []
    for edge_index, bond in enumerate(bonds):
        start = edge_index * len(orders)
        order = orders[int(np.argmax(result.x[start : start + len(orders)]))]
        assigned.append(replace(bond, order=order))
    return assigned


def periodicize_layout(atoms, periodic_axis, heavy_indices, bonds):
    """Regularize the planar ASE embedding under exact periodic constraints."""
    local_index = {atom_index: pos for pos, atom_index in enumerate(heavy_indices)}
    positions = atoms.positions[heavy_indices]
    centered = positions - np.mean(positions, axis=0)
    _, _, right_vectors = np.linalg.svd(centered, full_matrices=False)
    normal = right_vectors[-1]
    translation_3d = np.asarray(atoms.cell[periodic_axis])
    x_axis = translation_3d / np.linalg.norm(translation_3d)
    y_axis = np.cross(normal, x_axis)
    y_axis /= np.linalg.norm(y_axis)
    base = np.column_stack((positions @ x_axis, positions @ y_axis))
    fractional = atoms.get_scaled_positions(wrap=True)[heavy_indices, periodic_axis]
    period = np.linalg.norm(translation_3d)
    base[:, 0] = fractional * period
    base[:, 1] -= np.mean(base[:, 1])

    lengths = []
    for bond in bonds:
        delta = (
            base[local_index[bond.end]]
            + np.array([bond.shift * period, 0.0])
            - base[local_index[bond.begin]]
        )
        lengths.append(np.linalg.norm(delta))
    scale = np.median(lengths)
    base /= scale
    period /= scale
    gauged_bonds = list(bonds)

    # Enumerate bounded faces in five cells and retain one representative of
    # each periodic ring, selected by its centroid in the central cell.
    cells = range(-2, 3)
    node_positions = {
        (atom_index, cell): base[local_index[atom_index]]
        + np.array([cell * period, 0.0])
        for cell in cells
        for atom_index in heavy_indices
    }
    adjacency = {node: [] for node in node_positions}
    for cell in cells:
        for bond in gauged_bonds:
            first = (bond.begin, cell)
            second = (bond.end, cell + bond.shift)
            if first in adjacency and second in adjacency:
                adjacency[first].append(second)
                adjacency[second].append(first)
    ordered_neighbors = {
        node: sorted(
            neighbors,
            key=lambda neighbor: np.arctan2(
                *(node_positions[neighbor] - node_positions[node])[::-1]
            ),
        )
        for node, neighbors in adjacency.items()
    }
    visited = set()
    faces = []
    for first in node_positions:
        for second in adjacency[first]:
            if (first, second) in visited:
                continue
            face = []
            current_first, current_second = first, second
            for _ in range(1000):
                visited.add((current_first, current_second))
                face.append(current_first)
                neighbors = ordered_neighbors[current_second]
                index = neighbors.index(current_first)
                following = neighbors[(index - 1) % len(neighbors)]
                current_first, current_second = current_second, following
                if (current_first, current_second) == (first, second):
                    break
            polygon = np.asarray([node_positions[node] for node in face])
            area = 0.5 * np.sum(
                polygon[:, 0] * np.roll(polygon[:, 1], -1)
                - polygon[:, 1] * np.roll(polygon[:, 0], -1)
            )
            centroid_x = float(np.mean(polygon[:, 0]))
            if area > 0 and -1.0e-8 <= centroid_x < period - 1.0e-8:
                faces.append(face)

    unsupported_faces = sorted(
        size for size in {len(face) for face in faces} if size < 3 or size > 12
    )
    if unsupported_faces:
        raise ValueError(f"Unsupported ring sizes in the CDXML generator: {unsupported_faces}")

    anchor = base.copy()
    anchor_period = period

    def periodic_position(current, current_period, node):
        atom_index, cell = node
        return current[local_index[atom_index]] + np.array(
            [cell * current_period, 0.0]
        )

    def residual(vector):
        current = vector[:-1].reshape((-1, 2))
        current_period = vector[-1]
        result = []
        for bond in gauged_bonds:
            delta = (
                current[local_index[bond.end]]
                + np.array([bond.shift * current_period, 0.0])
                - current[local_index[bond.begin]]
            )
            result.append(200.0 * (np.linalg.norm(delta) - 1.0))
        for face in faces:
            target_cosine = np.cos((len(face) - 2) * np.pi / len(face))
            for index, center in enumerate(face):
                previous = face[index - 1]
                following = face[(index + 1) % len(face)]
                center_position = periodic_position(current, current_period, center)
                first_vector = (
                    periodic_position(current, current_period, previous)
                    - center_position
                )
                second_vector = (
                    periodic_position(current, current_period, following)
                    - center_position
                )
                cosine = (
                    np.dot(first_vector, second_vector)
                    / np.linalg.norm(first_vector)
                    / np.linalg.norm(second_vector)
                )
                result.append(8.0 * (cosine - target_cosine))
        result.extend((0.03 * (current - anchor)).ravel())
        result.append(0.03 * (current_period - anchor_period))
        return np.asarray(result)

    initial = np.concatenate([base.ravel(), [period]])
    optimized = least_squares(
        residual, initial, max_nfev=10000, xtol=1e-12, ftol=1e-12, gtol=1e-12
    )
    base = optimized.x[:-1].reshape((-1, 2))
    period = optimized.x[-1]

    # Rewrap after optimization and update the quotient-graph shifts.
    gauge = np.floor(base[:, 0] / period).astype(int)
    base[:, 0] -= gauge * period
    gauged_bonds = [
        replace(
            bond,
            shift=bond.shift
            + gauge[local_index[bond.end]]
            - gauge[local_index[bond.begin]],
        )
        for bond in gauged_bonds
    ]
    base[:, 1] -= np.mean(base[:, 1])
    return local_index, base, period, gauged_bonds


def choose_reference_crossing(local_index, base, period, bonds):
    """Choose a crossing midpoint that encloses exactly the base-cell atoms."""
    candidates = []
    for edge_index, bond in enumerate(bonds):
        if not bond.shift:
            continue
        begin = base[local_index[bond.begin]]
        end = base[local_index[bond.end]] + np.array([bond.shift * period, 0.0])
        midpoint = (begin + end) / 2
        if midpoint[0] > period / 2:
            midpoint[0] -= period
        elif midpoint[0] <= -period / 2:
            midpoint[0] += period
        inside = np.count_nonzero(
            (base[:, 0] > midpoint[0] - 1.0e-6)
            & (base[:, 0] <= midpoint[0] + period + 1.0e-6)
        )
        candidates.append((inside, -abs(midpoint[0]), edge_index, midpoint[0]))
    if not candidates:
        raise ValueError("No periodic crossing bond found.")
    _, _, edge_index, left_boundary = max(candidates)
    return edge_index, left_boundary


def choose_graphic_boundary(local_index, base, period, bonds):
    """Place a vertical bracket through every crossing bond, away from atoms."""
    intervals = []
    for bond in bonds:
        if bond.shift > 0:
            begin = base[local_index[bond.begin]] - np.array([period, 0.0])
            end = base[local_index[bond.end]]
        elif bond.shift < 0:
            begin = base[local_index[bond.begin]]
            end = base[local_index[bond.end]] - np.array([period, 0.0])
        else:
            continue
        intervals.append((min(begin[0], end[0]), max(begin[0], end[0])))
    lower = max(interval[0] for interval in intervals)
    upper = min(interval[1] for interval in intervals)
    if lower >= upper:
        raise ValueError("No vertical line crosses all periodic boundary bonds.")
    return (lower + upper) / 2


def indent_xml(element, level=0):
    """Indent an ElementTree in-place for readable CDXML output."""
    indentation = "\n" + level * "  "
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indentation + "  "
        for child in element:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indentation
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indentation


def write_cdxml(
    output_path,
    atoms,
    heavy_indices,
    explicit_h,
    local_index,
    base,
    period,
    bonds,
    reference_edge,
    left_boundary,
    graphic_boundary,
    radicals=None,
):
    """Write three displayed cells with brackets around the central cell."""
    radicals = radicals or {}
    scale = 14.4
    display_cells = (-1, 0, 1)
    y_min = float(np.min(base[:, 1]) - 1.2)
    y_max = float(np.max(base[:, 1]) + 1.2)
    x_min = left_boundary - period - 1.0
    x_max = left_boundary + 2 * period + 1.0
    offset = np.array([-x_min * scale + 20.0, -y_min * scale + 20.0])

    def point(value):
        converted = value * scale + offset
        return f"{converted[0]:.4f} {converted[1]:.4f}"

    root = ET.Element(
        "CDXML",
        {
            "CreationProgram": "AiiDAlab openBIS",
            "Name": output_path.name,
            "BoundingBox": f"0 0 {(x_max-x_min)*scale+40:.2f} {(y_max-y_min)*scale+40:.2f}",
            "BondLength": "14.40",
            "BondSpacing": "18",
            "ChainAngle": "120",
            "InterpretChemically": "yes",
            "HideImplicitHydrogens": "no",
            "ShowTerminalCarbonLabels": "no",
            "ShowNonTerminalCarbonLabels": "no",
        },
    )
    page = ET.SubElement(root, "page", {"id": "1"})
    fragment = ET.SubElement(page, "fragment", {"id": "2"})

    next_id = 10
    node_ids = {}
    for cell in display_cells:
        for atom_index in heavy_indices:
            node_id = str(next_id)
            next_id += 1
            node_ids[(atom_index, cell)] = node_id
            position = base[local_index[atom_index]] + np.array([cell * period, 0.0])
            attributes = {"id": node_id, "p": point(position)}
            if cell == 0:
                attributes["NumHydrogens"] = str(explicit_h[atom_index])
            if radicals.get(atom_index):
                attributes["Radical"] = "Doublet"
            ET.SubElement(fragment, "n", attributes)

    bond_instances = {}
    for cell in display_cells:
        for edge_index, bond in enumerate(bonds):
            target_cell = cell + bond.shift
            if target_cell not in display_cells:
                continue
            bond_id = str(next_id)
            next_id += 1
            attributes = {
                "id": bond_id,
                "B": node_ids[(bond.begin, cell)],
                "E": node_ids[(bond.end, target_cell)],
            }
            if bond.order != 1:
                attributes["Order"] = str(bond.order)
            ET.SubElement(fragment, "b", attributes)
            bond_instances[(edge_index, cell)] = bond_id

    bracket_y0 = np.array([0.0, y_min + 0.25])
    bracket_y1 = np.array([0.0, y_max - 0.25])
    left_graphic_id = str(next_id)
    next_id += 1
    right_graphic_id = str(next_id)
    next_id += 1
    for side, graphic_id, x_position in (
        ("left", left_graphic_id, graphic_boundary),
        ("right", right_graphic_id, graphic_boundary + period),
    ):
        lower = point(np.array([x_position, bracket_y0[1]]))
        upper = point(np.array([x_position, bracket_y1[1]]))
        bounding_box = f"{upper} {lower}" if side == "left" else f"{lower} {upper}"
        ET.SubElement(
            page,
            "graphic",
            {
                "id": graphic_id,
                "BoundingBox": bounding_box,
                "GraphicType": "Bracket",
                "BracketType": "Square",
                "LipSize": "12",
            },
        )

    group = ET.SubElement(
        page,
        "bracketedgroup",
        {
            "id": str(next_id),
            "BracketedObjectIDs": " ".join(
                node_ids[(atom_index, 0)] for atom_index in heavy_indices
            ),
        },
    )
    next_id += 1

    crossings = {"left": [], "right": []}
    for edge_index, bond in enumerate(bonds):
        if not bond.shift:
            continue
        if bond.shift > 0:
            left_cell = -1
            right_cell = 0
            left_inner = bond.end
            right_inner = bond.begin
        else:
            left_cell = 0
            right_cell = 1
            left_inner = bond.begin
            right_inner = bond.end
        crossings["left"].append(
            (edge_index, bond_instances[(edge_index, left_cell)], left_inner)
        )
        crossings["right"].append(
            (edge_index, bond_instances[(edge_index, right_cell)], right_inner)
        )

    for side, graphic_id in (
        ("left", left_graphic_id),
        ("right", right_graphic_id),
    ):
        attachment = ET.SubElement(
            group, "bracketattachment", {"id": str(next_id), "GraphicID": graphic_id}
        )
        next_id += 1
        ordered = sorted(crossings[side], key=lambda item: (item[0] != reference_edge, item[0]))
        for _, bond_id, inner_atom in ordered:
            ET.SubElement(
                attachment,
                "crossingbond",
                {
                    "id": str(next_id),
                    "BondID": bond_id,
                    "InnerAtomID": node_ids[(inner_atom, 0)],
                },
            )
            next_id += 1

    indent_xml(root)
    xml_body = ET.tostring(root, encoding="unicode")
    output_path.write_text(
        '<?xml version="1.0" encoding="UTF-8" ?>\n'
        '<!DOCTYPE CDXML SYSTEM "https://static.chemistry.revvitycloud.com/cdxml/CDXML.dtd" >\n'
        + xml_body
        + "\n",
        encoding="utf-8",
    )
