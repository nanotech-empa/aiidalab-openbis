"""Choose an ELN thumbnail from stored STM/STS maps, without exporting data."""

import html
import tempfile
from pathlib import Path

import ipywidgets as ipw
import numpy as np

from . import aiida_utils
from .widget_lifecycle import close_owned_widgets

_KINDS = {
    "const-height stm": "STM · constant height",
    "const-isovalue stm": "STM · constant isovalue",
    "const-height sts": "STS dI/dV · constant height",
    "const-isovalue sts": "STS dI/dV · constant isovalue",
}


def _load_archive(source_uuid):
    from aiida.orm import load_node

    # Return plain arrays/metadata; never keep an ORM node in a widget callback.
    return aiida_utils._stm_archive_metadata(load_node(source_uuid))


class StmPreviewPicker(ipw.Accordion):
    def __init__(self, source_uuid, on_use):
        self.source_uuid = str(source_uuid)
        self._on_use = on_use
        self._archive = None
        self._picker_closed = False
        self.series = ipw.Dropdown(
            description="Map series",
            style={"description_width": "initial"},
            layout=ipw.Layout(width="98%"),
        )
        self.bias = ipw.FloatText(description="Bias [V]", continuous_update=False)
        self.use_button = ipw.Button(
            description="Use this map as ELN preview",
            disabled=True,
            button_style="info",
            layout=ipw.Layout(width="auto"),
        )
        self.status = ipw.HTML()
        self.body = ipw.VBox(
            [
                ipw.HTML(
                    "<p>Choose a stored map and bias for the thumbnail. "
                    "This does not change the maps or curves selected for export.</p>"
                ),
                self.series,
                self.bias,
                self.status,
                self.use_button,
            ]
        )
        super().__init__(children=[self.body], selected_index=None)
        self.set_title(0, "Choose a calculated STM/STS image")
        self.observe(self._open, names="selected_index")
        self.series.observe(self._draft_changed, names="value")
        self.bias.observe(self._draft_changed, names="value")
        self.use_button.on_click(self._use)

    def _open(self, change):
        if change["new"] is None or self._archive is not None:
            return
        try:
            archive = _load_archive(self.source_uuid)
            general, infos, arrays = archive
            energies = np.asarray(general.get("energies", []), dtype=float)
            if not len(energies) or not np.all(np.isfinite(energies)):
                raise ValueError("The archive has no finite stored biases.")
            options = []
            for index, info in enumerate(infos):
                kind = str(info.get("type", "")).lower()
                if kind in _KINDS and len(arrays[index]) == len(energies):
                    label = _KINDS[kind]
                    details = aiida_utils._spm_series_details(info)
                    options.append((f"{label}; {details}" if details else label, index))
            if not options:
                raise ValueError("The archive has no stored STM/STS map series.")
            self._archive = archive
            self.series.options = options
            try:
                first = aiida_utils._stm_preview_panels_from_archive(*archive)[0]
                self.series.value = first["series_index"]
                index = first["energy_index"]
            except ValueError:
                index = aiida_utils._nearest_available_index(energies, 0.0)
            self.bias.value = float(energies[index])
            self._draft_changed()
        except Exception as error:  # noqa: BLE001 - keep file replacement available
            self._archive = None
            self.use_button.disabled = True
            self.status.value = (
                f"<p style='color:#b00020'>{html.escape(str(error))}</p>"
            )

    def _selected_index(self):
        if self._archive is None or self.series.value is None:
            raise ValueError("Open the selector to load the stored maps.")
        energies = np.asarray(self._archive[0]["energies"], dtype=float)
        if not np.isfinite(self.bias.value):
            raise ValueError("Enter a finite bias.")
        index = aiida_utils._nearest_available_index(
            energies, self.bias.value, require_in_range=True
        )
        if index is None:
            raise ValueError(
                f"Enter a bias between {energies.min():g} and {energies.max():g} V."
            )
        return index

    def _draft_changed(self, _change=None):
        if self._archive is None:
            return
        try:
            index = self._selected_index()
            image = self._archive[2][self.series.value][index]
            contrast = aiida_utils._finite_image_contrast(image)
            if contrast < 0:
                raise ValueError("This stored map has no finite image values.")
            energy = float(self._archive[0]["energies"][index])
            note = " This map is uniform." if contrast == 0 else ""
            self.status.value = (
                f"<p>Stored bias: <b>{energy:+.2f} V</b>.{note} "
                "Click Use to apply it to the ELN preview.</p>"
            )
            self.use_button.disabled = False
        except ValueError as error:
            self.use_button.disabled = True
            self.status.value = (
                f"<p style='color:#b00020'>{html.escape(str(error))}</p>"
            )

    def _use(self, _button=None):
        self.use_button.disabled = True
        try:
            index = self._selected_index()
            series = int(self.series.value)
            energy = float(self._archive[0]["energies"][index])
            label = f"{self.series.label}; bias {energy:+.2f} V"
            with tempfile.TemporaryDirectory(prefix="stm-eln-preview-") as directory:
                path = Path(directory) / f"stm-s{series}-e{index}.png"
                aiida_utils._render_stm_selected_preview(
                    self._archive, series, index, path
                )
                aiida_utils._resample_preview_path(path)
                preview = {
                    "name": path.name,
                    "content": path.read_bytes(),
                    "label": label,
                }
            self._on_use(preview)
            self.status.value = (
                "<p style='color:#237804'>Selected map is now the ELN preview.</p>"
            )
        except Exception as error:  # noqa: BLE001 - preserve the last working choice
            self.status.value = (
                f"<p style='color:#b00020'>{html.escape(str(error))}</p>"
            )
        finally:
            self.use_button.disabled = False

    def close(self):
        if getattr(self, "_picker_closed", True):
            return
        self._picker_closed = True
        self.unobserve(self._open, names="selected_index")
        self.series.unobserve(self._draft_changed, names="value")
        self.bias.unobserve(self._draft_changed, names="value")
        self.use_button.on_click(self._use, remove=True)
        self._archive = None
        self._on_use = None
        close_owned_widgets(self.body)
        self.children = ()
        super().close()
