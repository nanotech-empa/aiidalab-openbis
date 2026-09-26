"""Interactive review of CDXML generated from a planar 1D AiiDA structure."""

from __future__ import annotations

import base64
import html
from collections import Counter
from io import BytesIO

import bqplot as bq
import ipywidgets as ipw
import matplotlib.pyplot as plt
import numpy as np
from IPython.display import display

from .cdxml_generator import (
    PeriodicBond,
    assign_bond_orders,
    choose_graphic_boundary,
    choose_reference_crossing,
    load_atoms,
    perceive_graph,
    periodicize_layout,
    write_cdxml,
)
from .chemical_structures import representation_from_cdxml


def bond_key(bond: PeriodicBond) -> tuple[int, int, int]:
    return bond.begin, bond.end, bond.shift


def canonical_pair(
    first_atom: int, first_cell: int, second_atom: int, second_cell: int
) -> tuple[int, int, int]:
    direct = (first_atom, second_atom, second_cell - first_cell)
    reverse = (second_atom, first_atom, first_cell - second_cell)
    return min(direct, reverse)


def iter_bond_instances(bonds, cells=(-1, 0, 1)):
    for cell in cells:
        for bond in bonds:
            target_cell = cell + bond.shift
            if target_cell in cells:
                yield bond, cell, target_cell


def physical_layout(atoms, periodic_axis, heavy_indices, bonds):
    """Fallback layout that preserves the projected ASE geometry."""
    local_index = {atom_index: pos for pos, atom_index in enumerate(heavy_indices)}
    positions = atoms.positions[heavy_indices]
    centered = positions - np.mean(positions, axis=0)
    _, _, right_vectors = np.linalg.svd(centered, full_matrices=False)
    normal = right_vectors[-1]
    translation = np.asarray(atoms.cell[periodic_axis])
    x_axis = translation / np.linalg.norm(translation)
    y_axis = np.cross(normal, x_axis)
    y_axis /= np.linalg.norm(y_axis)
    base = np.column_stack((positions @ x_axis, positions @ y_axis))
    period = np.linalg.norm(translation)
    fractional = atoms.get_scaled_positions(wrap=True)[heavy_indices, periodic_axis]
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
    return local_index, base / scale, period / scale, list(bonds)


class _MemoryTextTarget:
    """Small path-like text sink used by the exporter."""

    def __init__(self, name):
        self.name = name
        self.value = ""

    def write_text(self, value, encoding="utf-8"):
        self.value = value
        return len(value.encode(encoding))


class PeriodicCdxmlEditor(ipw.VBox):
    """Review connectivity, radicals, and CDXML output for a planar 1D structure."""

    def __init__(
        self,
        structure=None,
        on_export=None,
        filename=None,
        default_pk="",
    ):
        self._source_structure = structure
        self.on_export = on_export
        self.filename = filename or self._default_filename(structure)
        self.pk_input = ipw.Text(
            value=str(default_pk), description="PK / UUID", layout={"width": "260px"}
        )
        self.auto_accept = ipw.Checkbox(
            value=True,
            description="Accept unique long-bond suggestions",
            indent=False,
            layout={"width": "300px"},
        )
        self.load_button = ipw.Button(description="Load structure", button_style="primary")
        self.reset_button = ipw.Button(description="Reset edits")
        self.status = ipw.HTML(
            "Review the detected connectivity before generating the CDXML."
            if structure is not None
            else "Enter a StructureData or process PK/UUID, then load it."
        )

        self.selection = ipw.HTML("Selected atoms: none")
        self.add_button = ipw.Button(description="Add bond", button_style="success", disabled=True)
        self.remove_button = ipw.Button(description="Remove bond", button_style="warning", disabled=True)
        self.clear_button = ipw.Button(description="Clear selection", disabled=True)

        self.radical_atom = ipw.Dropdown(description="Atom", options=[], disabled=True)
        self.radical_state = ipw.ToggleButtons(
            description="Radical",
            options=[("None", 0), ("Doublet •", 1)],
            value=0,
            disabled=True,
        )
        self.apply_radical_button = ipw.Button(
            description="Apply radical", disabled=True
        )

        self.accept_pending_button = ipw.Button(
            description="Accept suggestions", disabled=True
        )
        self.reject_pending_button = ipw.Button(
            description="Reject suggestions", disabled=True
        )
        self.export_button = ipw.Button(
            description="Use CDXML for search", button_style="primary", disabled=True
        )
        self.summary = ipw.HTML()
        self.suggestions = ipw.HTML()
        self.export_result = ipw.HTML()
        self.png_preview = ipw.Image(
            format="png", layout={"width": "430px", "max_height": "780px"}
        )

        self.x_scale = bq.LinearScale(allow_padding=False)
        self.y_scale = bq.LinearScale(allow_padding=False)
        self.figure = bq.Figure(
            axes=[],
            marks=[],
            fig_margin={"top": 10, "bottom": 10, "left": 10, "right": 10},
            layout={"width": "520px", "height": "780px"},
            background_style={"fill": "white"},
        )

        self.load_controls = ipw.HBox(
            [self.pk_input, self.load_button, self.reset_button]
        )
        if structure is not None:
            self.load_controls.layout.display = "none"
        controls = ipw.VBox(
            [
                self.load_controls,
                self.auto_accept,
                self.status,
                ipw.HTML("<b>Bond editing</b> — click two atoms in the canvas."),
                self.selection,
                ipw.HBox([self.add_button, self.remove_button, self.clear_button]),
                ipw.HTML("<b>Atom state</b>"),
                ipw.HBox([self.radical_atom, self.radical_state, self.apply_radical_button]),
                ipw.HBox([self.accept_pending_button, self.reject_pending_button]),
                self.summary,
                self.suggestions,
                self.export_button,
                self.export_result,
            ],
            layout={"width": "520px"},
        )
        preview_box = ipw.VBox(
            [ipw.HTML("<b>PNG chemical sketch</b>"), self.png_preview],
            layout={"width": "450px"},
        )
        editor_box = ipw.VBox(
            [ipw.HTML("<b>Interactive connectivity editor</b>"), self.figure],
            layout={"width": "540px"},
        )
        super().__init__([controls, ipw.HBox([editor_box, preview_box])])

        self.load_button.on_click(self._load_clicked)
        self.reset_button.on_click(self._load_clicked)
        self.add_button.on_click(self._add_clicked)
        self.remove_button.on_click(self._remove_clicked)
        self.clear_button.on_click(self._clear_clicked)
        self.apply_radical_button.on_click(self._apply_radical_clicked)
        self.accept_pending_button.on_click(self._accept_pending_clicked)
        self.reject_pending_button.on_click(self._reject_pending_clicked)
        self.export_button.on_click(self._export_clicked)
        self.radical_atom.observe(self._radical_atom_changed, names="value")

        self.structure = None
        self.atoms = None
        self.periodic_axis = None
        self.heavy_indices = []
        self.explicit_h = Counter()
        self.strict_bonds = {}
        self.added_bonds = {}
        self.removed_bonds = set()
        self.candidates = {}
        self.rejected_candidates = set()
        self.radicals = {}
        self.selected_atoms = []
        self._display_points = []
        self._atom_mark = None
        self._valid = False
        self.last_cdxml = b""
        self.last_png = b""
        self.last_representation = None

        if structure is not None:
            self.load_structure(structure)

    @staticmethod
    def _default_filename(structure):
        identifier = getattr(structure, "uuid", None) or getattr(structure, "pk", None)
        return f"aiida-structure-{identifier or 'generated'}.cdxml"

    def load_structure(self, structure):
        """Load an AiiDA StructureData or an ASE Atoms instance."""
        self._source_structure = structure
        self.filename = self._default_filename(structure)
        self._load_clicked(None)
        return self

    def load(self, identifier=None):
        """Load a structure programmatically; used by the notebook and tests."""
        if identifier is not None:
            self.pk_input.value = str(identifier)
        self._load_clicked(None)
        return self

    def _load_clicked(self, _):
        try:
            if self._source_structure is None:
                self.structure, self.atoms = load_atoms(self.pk_input.value.strip())
            else:
                self.structure = self._source_structure
                get_ase = getattr(self.structure, "get_ase", None)
                self.atoms = get_ase() if get_ase is not None else self.structure.copy()
            (
                self.periodic_axis,
                self.heavy_indices,
                self.explicit_h,
                all_bonds,
                inferred,
                candidates,
            ) = perceive_graph(self.atoms)
            inferred_keys = {bond_key(bond) for bond in inferred}
            self.strict_bonds = {
                bond_key(bond): bond for bond in all_bonds if bond_key(bond) not in inferred_keys
            }
            self.added_bonds = (
                {bond_key(bond): bond for bond in inferred}
                if self.auto_accept.value
                else {}
            )
            self.candidates = {bond_key(bond): bond for bond in candidates}
            self.removed_bonds = set()
            self.rejected_candidates = set()
            self.radicals = {}
            self.selected_atoms = []
            self.radical_atom.options = [
                (f"C {atom_index}", atom_index) for atom_index in self.heavy_indices
            ]
            self.radical_atom.disabled = False
            self.radical_state.disabled = False
            self.apply_radical_button.disabled = False
            self.clear_button.disabled = False
            identity = getattr(self.structure, "uuid", None)
            if identity is None:
                identity = getattr(self.structure, "pk", "in-memory structure")
            self.status.value = (
                f"<b>Loaded:</b> {html.escape(str(identity))}; formula "
                f"{html.escape(self.atoms.get_chemical_formula())}."
            )
            self.export_result.value = ""
            self._recompute()
        except Exception as exc:
            self._valid = False
            self.export_button.disabled = True
            self.status.value = f"<span style='color:#b00020'><b>Error:</b> {exc}</span>"

    def _current_bonds(self):
        current = {
            key: bond
            for key, bond in self.strict_bonds.items()
            if key not in self.removed_bonds
        }
        current.update(self.added_bonds)
        return list(current.values())

    def _bond_from_selection(self):
        if len(self.selected_atoms) != 2:
            return None, None
        (first_atom, first_cell), (second_atom, second_cell) = self.selected_atoms
        if (first_atom, first_cell) == (second_atom, second_cell):
            return None, None
        key = canonical_pair(first_atom, first_cell, second_atom, second_cell)
        begin, end, shift = key
        displacement = (
            self.atoms.positions[end]
            + shift * np.asarray(self.atoms.cell[self.periodic_axis])
            - self.atoms.positions[begin]
        )
        return key, PeriodicBond(begin, end, shift, float(np.linalg.norm(displacement)))

    def _add_clicked(self, _):
        key, bond = self._bond_from_selection()
        if key is None:
            return
        if key in self.strict_bonds:
            self.removed_bonds.discard(key)
        else:
            self.added_bonds[key] = bond
        self.rejected_candidates.discard(key)
        self._clear_selection()
        self._recompute()

    def _remove_clicked(self, _):
        key, _ = self._bond_from_selection()
        if key is None:
            return
        if key in self.strict_bonds:
            self.removed_bonds.add(key)
        else:
            self.added_bonds.pop(key, None)
        if key in self.candidates:
            self.rejected_candidates.add(key)
        self._clear_selection()
        self._recompute()

    def _apply_radical_clicked(self, _):
        atom_index = self.radical_atom.value
        if atom_index is None:
            return
        if self.radical_state.value:
            self.radicals[atom_index] = 1
        else:
            self.radicals.pop(atom_index, None)
        self._recompute()

    def _radical_atom_changed(self, change):
        atom_index = change["new"]
        if atom_index is not None:
            self.radical_state.value = self.radicals.get(atom_index, 0)

    def _accept_pending_clicked(self, _):
        for key, bond in self.candidates.items():
            if key not in self.rejected_candidates:
                self.added_bonds[key] = bond
        self._recompute()

    def _reject_pending_clicked(self, _):
        for key in self.candidates:
            if key not in self.added_bonds:
                self.rejected_candidates.add(key)
        self._recompute()

    def _clear_clicked(self, _):
        self._clear_selection()
        self._refresh_selection()

    def _clear_selection(self):
        self.selected_atoms = []
        if self._atom_mark is not None:
            self._atom_mark.selected = []

    def _atom_clicked(self, _, event):
        point_index = event.get("data", {}).get("index")
        if point_index is None or point_index >= len(self._display_points):
            return
        selected = self._display_points[point_index]
        if selected in self.selected_atoms:
            self.selected_atoms.remove(selected)
        else:
            if len(self.selected_atoms) == 2:
                self.selected_atoms = []
            self.selected_atoms.append(selected)
        self.radical_atom.value = selected[0]
        self._refresh_selection()

    def _refresh_selection(self):
        if self._atom_mark is not None:
            selected_indices = [
                index
                for index, (atom_index, _) in enumerate(self._display_points)
                if any(atom_index == chosen[0] for chosen in self.selected_atoms)
            ]
            self._atom_mark.selected = selected_indices
        if not self.selected_atoms:
            label = "none"
        else:
            label = ", ".join(
                f"C{atom} (cell {cell:+d})" for atom, cell in self.selected_atoms
            )
        self.selection.value = f"Selected atoms: <b>{label}</b>"
        two_selected = len(self.selected_atoms) == 2
        self.add_button.disabled = not two_selected
        self.remove_button.disabled = not two_selected

    def _recompute(self):
        topology = self._current_bonds()
        error = None
        try:
            assigned = assign_bond_orders(
                self.atoms,
                self.heavy_indices,
                self.explicit_h,
                topology,
                radical_electrons=self.radicals,
            )
            local_index, base, period, assigned = periodicize_layout(
                self.atoms,
                self.periodic_axis,
                self.heavy_indices,
                assigned,
            )
            reference_edge, reference_boundary = choose_reference_crossing(
                local_index, base, period, assigned
            )
            graphic_boundary = choose_graphic_boundary(
                local_index, base, period, assigned
            )
            self._valid = True
        except Exception as exc:
            error = str(exc)
            assigned = topology
            local_index, base, period, assigned = physical_layout(
                self.atoms, self.periodic_axis, self.heavy_indices, assigned
            )
            try:
                reference_edge, reference_boundary = choose_reference_crossing(
                    local_index, base, period, assigned
                )
                graphic_boundary = choose_graphic_boundary(
                    local_index, base, period, assigned
                )
            except Exception:
                reference_edge = 0
                reference_boundary = 0.0
                graphic_boundary = 0.0
            self._valid = False

        self.assigned_bonds = assigned
        self.local_index = local_index
        self.base = base
        self.period = period
        self.reference_edge = reference_edge
        self.reference_boundary = reference_boundary
        self.graphic_boundary = graphic_boundary
        self._draw_interactive()
        self.png_preview.value = self._render_png(show_suggestions=True)
        self._update_summary(error)
        self.export_button.disabled = not self._valid

    def _segments_for_bonds(self, bonds, double_lines=True):
        x_values = []
        y_values = []
        for bond, cell, target_cell in iter_bond_instances(bonds):
            first = self.base[self.local_index[bond.begin]] + np.array(
                [cell * self.period, 0.0]
            )
            second = self.base[self.local_index[bond.end]] + np.array(
                [target_cell * self.period, 0.0]
            )
            direction = second - first
            normal = np.array([-direction[1], direction[0]]) / np.linalg.norm(direction)
            offsets = [0.0]
            if double_lines and bond.order == 2:
                offsets = [-0.045, 0.045]
            for offset in offsets:
                shifted = offset * normal
                x_values.extend([first[0] + shifted[0], second[0] + shifted[0], np.nan])
                y_values.extend([first[1] + shifted[1], second[1] + shifted[1], np.nan])
        return x_values, y_values

    def _draw_interactive(self):
        x_bonds, y_bonds = self._segments_for_bonds(self.assigned_bonds)
        bond_mark = bq.Lines(
            x=x_bonds,
            y=y_bonds,
            scales={"x": self.x_scale, "y": self.y_scale},
            colors=["#333333"],
            stroke_width=1.5,
        )

        current_keys = {bond_key(bond) for bond in self._current_bonds()}
        pending = [
            bond
            for key, bond in self.candidates.items()
            if key not in current_keys and key not in self.rejected_candidates
        ]
        marks = [bond_mark]
        if pending:
            x_pending, y_pending = self._segments_for_bonds(pending, double_lines=False)
            marks.append(
                bq.Lines(
                    x=x_pending,
                    y=y_pending,
                    scales={"x": self.x_scale, "y": self.y_scale},
                    colors=["#e58e26"],
                    stroke_width=2.5,
                    line_style="dashed",
                )
            )

        self._display_points = []
        x_atoms = []
        y_atoms = []
        point_colors = []
        for cell in (-1, 0, 1):
            for atom_index in self.heavy_indices:
                position = self.base[self.local_index[atom_index]] + np.array(
                    [cell * self.period, 0.0]
                )
                self._display_points.append((atom_index, cell))
                x_atoms.append(position[0])
                y_atoms.append(position[1])
                point_colors.append("#202020" if cell == 0 else "#9a9a9a")
        self._atom_mark = bq.Scatter(
            x=x_atoms,
            y=y_atoms,
            scales={"x": self.x_scale, "y": self.y_scale},
            colors=point_colors,
            marker="circle",
            default_size=32,
            selected_style={"fill": "#d62728", "stroke": "#d62728", "opacity": 1.0},
            unselected_style={"opacity": 0.8},
            interactions={"click": "select"},
        )
        self._atom_mark.on_element_click(self._atom_clicked)
        marks.append(self._atom_mark)

        central_x = [self.base[self.local_index[index], 0] for index in self.heavy_indices]
        central_y = [self.base[self.local_index[index], 1] for index in self.heavy_indices]
        marks.append(
            bq.Label(
                x=central_x,
                y=central_y,
                text=[str(index) for index in self.heavy_indices],
                scales={"x": self.x_scale, "y": self.y_scale},
                colors=["#1f5a94"],
                x_offset=5,
                y_offset=-5,
            )
        )

        if self.radicals:
            radical_x = []
            radical_y = []
            for cell in (-1, 0, 1):
                for atom_index in self.radicals:
                    position = self.base[self.local_index[atom_index]] + np.array(
                        [cell * self.period + 0.12, 0.12]
                    )
                    radical_x.append(position[0])
                    radical_y.append(position[1])
            marks.append(
                bq.Scatter(
                    x=radical_x,
                    y=radical_y,
                    scales={"x": self.x_scale, "y": self.y_scale},
                    colors=["#d62728"],
                    marker="circle",
                    default_size=12,
                )
            )

        low = float(np.min(self.base[:, 1]) - 0.6)
        high = float(np.max(self.base[:, 1]) + 0.6)
        bracket_x = []
        bracket_y = []
        for x_position, direction in (
            (self.graphic_boundary, 1),
            (self.graphic_boundary + self.period, -1),
        ):
            lip = 0.28 * direction
            bracket_x.extend(
                [x_position, x_position, np.nan, x_position, x_position + lip, np.nan,
                 x_position, x_position + lip, np.nan]
            )
            bracket_y.extend(
                [low, high, np.nan, low, low, np.nan, high, high, np.nan]
            )
        marks.append(
            bq.Lines(
                x=bracket_x,
                y=bracket_y,
                scales={"x": self.x_scale, "y": self.y_scale},
                colors=["#111111"],
                stroke_width=1.6,
            )
        )
        self.figure.marks = marks
        self.x_scale.min = self.graphic_boundary - 0.75 * self.period
        self.x_scale.max = self.graphic_boundary + 1.75 * self.period
        self.y_scale.min = low - 0.2
        self.y_scale.max = high + 0.2
        self._refresh_selection()

    def _render_png(self, show_suggestions=False):
        fig, axis = plt.subplots(figsize=(4.2, 7.8))
        for bond, cell, target_cell in iter_bond_instances(self.assigned_bonds):
            first = self.base[self.local_index[bond.begin]] + np.array(
                [cell * self.period, 0.0]
            )
            second = self.base[self.local_index[bond.end]] + np.array(
                [target_cell * self.period, 0.0]
            )
            direction = second - first
            normal = np.array([-direction[1], direction[0]]) / np.linalg.norm(direction)
            offsets = [0.0] if bond.order == 1 else [-0.05, 0.05]
            for offset in offsets:
                shifted = normal * offset
                axis.plot(
                    [first[0] + shifted[0], second[0] + shifted[0]],
                    [first[1] + shifted[1], second[1] + shifted[1]],
                    color="#303030",
                    linewidth=1.35,
                    solid_capstyle="round",
                    zorder=1,
                )
        if show_suggestions:
            current_keys = {bond_key(bond) for bond in self._current_bonds()}
            pending = [
                bond for key, bond in self.candidates.items()
                if key not in current_keys and key not in self.rejected_candidates
            ]
            for bond, cell, target_cell in iter_bond_instances(pending):
                first = self.base[self.local_index[bond.begin]] + np.array(
                    [cell * self.period, 0.0]
                )
                second = self.base[self.local_index[bond.end]] + np.array(
                    [target_cell * self.period, 0.0]
                )
                axis.plot(
                    [first[0], second[0]], [first[1], second[1]],
                    color="#e58e26", linewidth=2.0, linestyle="--", zorder=1,
                )
        for cell in (-1, 0, 1):
            positions = np.asarray(
                [
                    self.base[self.local_index[index]]
                    + np.array([cell * self.period, 0.0])
                    for index in self.heavy_indices
                ]
            )
            axis.scatter(positions[:, 0], positions[:, 1], s=7, color="#303030", zorder=2)
            for atom_index in self.radicals:
                position = self.base[self.local_index[atom_index]] + np.array(
                    [cell * self.period + 0.12, 0.12]
                )
                axis.scatter(*position, s=7, color="#111111", zorder=3)
        low = float(np.min(self.base[:, 1]) - 0.6)
        high = float(np.max(self.base[:, 1]) + 0.6)
        for x_position, direction in (
            (self.graphic_boundary, 1),
            (self.graphic_boundary + self.period, -1),
        ):
            lip = 0.28 * direction
            axis.plot([x_position, x_position], [low, high], color="#111111", linewidth=1.3)
            axis.plot([x_position, x_position + lip], [low, low], color="#111111", linewidth=1.3)
            axis.plot([x_position, x_position + lip], [high, high], color="#111111", linewidth=1.3)
        axis.set_aspect("equal")
        axis.set_xlim(self.graphic_boundary - 0.75 * self.period, self.graphic_boundary + 1.75 * self.period)
        axis.set_ylim(low - 0.2, high + 0.2)
        axis.axis("off")
        fig.tight_layout(pad=0.1)
        buffer = BytesIO()
        fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return buffer.getvalue()

    def _update_summary(self, error=None):
        order_counts = Counter(getattr(bond, "order", 1) for bond in self.assigned_bonds)
        pending = [
            key for key in self.candidates
            if key not in self.added_bonds and key not in self.rejected_candidates
        ]
        radical_text = ", ".join(f"C{index}" for index in sorted(self.radicals)) or "none"
        if error:
            validity = f"<span style='color:#b00020'><b>Invalid valence:</b> {error}</span>"
        else:
            validity = "<span style='color:#187b35'><b>Valence solution valid.</b></span>"
        self.summary.value = (
            f"{validity}<br>Single bonds: {order_counts.get(1, 0)}; "
            f"double bonds: {order_counts.get(2, 0)}; radicals: {radical_text}; "
            f"pending suggestions: {len(pending)}."
        )
        rows = []
        for key, bond in sorted(self.candidates.items()):
            if key in self.added_bonds:
                state = "accepted"
                color = "#187b35"
            elif key in self.rejected_candidates:
                state = "rejected"
                color = "#777777"
            else:
                state = "pending"
                color = "#c66a00"
            rows.append(
                f"<li><span style='color:{color}'>C{bond.begin}–C{bond.end} "
                f"(shift {bond.shift:+d}, {bond.distance:.3f} Å): {state}</span></li>"
            )
        self.suggestions.value = (
            "<b>Long-bond suggestions</b><ul>" + "".join(rows) + "</ul>"
            if rows else "<b>Long-bond suggestions:</b> none"
        )
        self.accept_pending_button.disabled = not bool(pending)
        self.reject_pending_button.disabled = not bool(pending)

    def _export_clicked(self, _):
        if not self._valid:
            return
        target = _MemoryTextTarget(self.filename)
        write_cdxml(
            target,
            self.atoms,
            self.heavy_indices,
            self.explicit_h,
            self.local_index,
            self.base,
            self.period,
            self.assigned_bonds,
            self.reference_edge,
            self.reference_boundary,
            self.graphic_boundary,
            radicals=self.radicals,
        )
        self.last_cdxml = target.value.encode("utf-8")
        self.last_png = self._render_png(show_suggestions=False)
        self.last_representation = representation_from_cdxml(self.last_cdxml)
        cdxml_data = base64.b64encode(self.last_cdxml).decode("ascii")
        png_data = base64.b64encode(self.last_png).decode("ascii")
        representation_name = (
            "CXSMILES" if self.last_representation.periodic else "SMILES"
        )
        representation_value = (
            self.last_representation.cxsmiles
            if self.last_representation.periodic
            else self.last_representation.smiles
        )
        safe_filename = html.escape(self.filename, quote=True)
        png_filename = html.escape(self.filename.rsplit(".", 1)[0] + ".png", quote=True)
        self.export_result.value = (
            "<span style='color:#187b35'><b>CDXML validated and loaded into "
            "the structural search.</b></span><br>"
            f"Formula: {html.escape(self.last_representation.formula)}<br>"
            f"{representation_name}: <code>{html.escape(representation_value)}</code><br>"
            f"<a download='{safe_filename}' href='data:chemical/x-cdxml;base64,{cdxml_data}'>"
            "Download CDXML</a> &middot; "
            f"<a download='{png_filename}' href='data:image/png;base64,{png_data}'>"
            "Download PNG</a>"
        )
        if self.on_export is not None:
            self.on_export(
                self.last_cdxml,
                self.filename,
                self.last_png,
                self.last_representation,
            )


def show_editor(default_pk=""):
    """Create, display, and return a ready-to-use editor."""
    editor = PeriodicCdxmlEditor(default_pk=default_pk)
    display(editor)
    return editor
