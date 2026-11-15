"""Preview actual saved results, without re-solving or changing units/layout."""

import matplotlib.pyplot as plt
import numpy as np
import pytest

from src.model_previews import figure


@pytest.mark.parametrize("kind", ["spin_graph", "hubbard"])
def test_graph_and_stored_levels_keep_sites_positions_and_units(kind):
    positions = [[0, 0], [1, 0], [0.5, 1]]
    if kind == "spin_graph":
        graph = {
            "site_spins": [0.5, 1, 0.5],
            "exchange_edges": [{"i": 1, "j": 3, "J_meV": 1}],
            "site_positions": positions,
        }
        row = {"graph": graph, "energies_meV": [-1.2, 0.4]}
        unit = "meV"
    else:
        graph = {
            "sites": [{"U_eV": 2}] * 3,
            "hoppings": [{"i": 1, "j": 3, "t_eV": 1}],
            "site_positions": positions,
        }
        row = {"model": graph, "energies_eV": [-1.2, 0.4]}
        unit = "eV"
    fig = figure({"kind": kind, "results": [row], "units": {"energy": unit}})
    try:
        ax, energy = fig.axes
        np.testing.assert_allclose(ax.collections[0].get_offsets(), positions)
        assert len(ax.lines) == 1
        np.testing.assert_allclose(
            ax.lines[0].get_xydata(), [positions[0], positions[2]]
        )
        assert energy.get_ylabel() == f"Energy ({unit})"
        np.testing.assert_allclose(
            [line[0][1] for line in energy.collections[0].get_segments()], [-1.2, 0.4]
        )
        if kind == "spin_graph":
            assert "2  S=1" in [t.get_text() for t in ax.texts]
    finally:
        plt.close(fig)


def test_missing_graph_uses_stored_sector_energy_without_inventing_sites():
    fig = figure(
        {"kind": "hubbard", "results": [{"energy_eV": -3.2}, {"energy_eV": -2.0}]}
    )
    try:
        assert len(fig.axes) == 1
        assert len(fig.axes[0].collections) == 2
        assert fig.axes[0].get_ylabel() == "Energy (eV)"
    finally:
        plt.close(fig)


def test_hubbard_preview_includes_interaction_only_edges():
    fig = figure(
        {
            "kind": "hubbard",
            "results": [
                {
                    "model": {
                        "sites": [{}, {}, {}],
                        "hoppings": [{"i": 1, "j": 2}],
                        "interactions": [{"i": 1, "j": 2}, {"i": 2, "j": 3}],
                    }
                }
            ],
        }
    )
    try:
        assert len(fig.axes[0].lines) == 2
    finally:
        plt.close(fig)
