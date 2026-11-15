"""Preview saved model graphs and energy levels without running a solver."""

import numpy as np


def figure(payload):
    import matplotlib.pyplot as plt

    rows = payload.get("results", [])
    row = rows[0] if rows else {}
    graph = row.get("graph", row.get("model", {}))
    spins = graph.get("site_spins", [])
    size = len(spins) or len(graph.get("sites", []))
    energy_key = (
        "energies_meV" if payload.get("kind") == "spin_graph" else "energies_eV"
    )
    unit = payload.get("units", {}).get("energy", "meV" if spins else "eV")
    energies = []
    for item in rows:
        values = item.get(energy_key)
        if values is None:
            value = item.get("energy_meV" if unit == "meV" else "energy_eV")
            values = [] if value is None else [value]
        energies.append(np.asarray(values, dtype=float).ravel())
    has_energies = any(values.size for values in energies)
    fig, axes = plt.subplots(1, 2 if size and has_energies else 1, figsize=(8, 4.8))
    axes = np.atleast_1d(axes)
    if size:
        ax = axes[0]
        positions = np.asarray(graph.get("site_positions", []), dtype=float)
        if positions.shape != (size, 2) or not np.isfinite(positions).all():
            angle = np.linspace(0, 2 * np.pi, size, endpoint=False)
            positions = np.column_stack((np.cos(angle), np.sin(angle)))
        edges = graph.get("exchange_edges", []) or (
            graph.get("hoppings", []) + graph.get("interactions", [])
        )
        seen = set()
        for edge in edges:
            identity = tuple(sorted((edge["i"], edge["j"])))
            if identity in seen:
                continue
            seen.add(identity)
            pair = np.asarray([edge["i"], edge["j"]], dtype=int) - 1
            if (pair < 0).any() or (pair >= size).any():
                raise ValueError("Invalid stored graph edge.")
            ax.plot(*positions[pair].T, color="#6a7d90", linewidth=2, zorder=1)
        ax.scatter(*positions.T, s=180, color="#1479ac", zorder=2)
        for index, point in enumerate(positions):
            label = f"{index + 1}" + (f"  S={spins[index]:g}" if spins else "")
            ax.annotate(
                label,
                point,
                xytext=(0, 12),
                textcoords="offset points",
                ha="center",
                fontsize=10,
            )
        ax.set_title(f"Saved model graph · {size} sites", fontsize=12)
        ax.margins(0.25)
        ax.set_aspect("equal")
        ax.set_axis_off()
    if has_energies:
        ax = axes[-1]
        for index, values in enumerate(energies):
            if not values.size:
                continue
            shown = np.sort(values)[:80]
            ax.hlines(shown, index + 0.15, index + 0.85, color="#1479ac")
        ax.set(xlabel="Stored result / sector", ylabel=f"Energy ({unit})")
        ax.set_xticks(
            np.arange(len(rows)) + 0.5, [str(i + 1) for i in range(len(rows))]
        )
        ax.set_title(
            "Stored energies"
            + (" · lowest 80 per sector" if any(v.size > 80 for v in energies) else ""),
            fontsize=12,
        )
        ax.grid(axis="y", alpha=0.2)
    elif not size:
        axes[0].text(
            0.5,
            0.5,
            "Graph and energy preview unavailable\nfor this stored result",
            ha="center",
            va="center",
            transform=axes[0].transAxes,
        )
        axes[0].set_axis_off()
    fig.suptitle(payload.get("title", "Model Hamiltonian"), fontsize=15)
    fig.tight_layout()
    return fig
