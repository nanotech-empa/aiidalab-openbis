# Simulated CP2K STM/STS in microscopy

The Surfaces STM viewer opens the standard SPM and AiiDA archive export. Use the
sampling panel to select a series and bias, add any points or profiles, then
click **Keep to export**. Each entry stores one map and any selected curves.
The editor resets so you can choose the next map. **Remove** and **Clear all**
edit the kept list. An empty list prepares the simulation and archive alone.
Public entry points are
`aiida_openbis.export.review_stm_imaging(source_uuid, selections)` (read-only)
and `make_export_widget(source_uuid, microscopy_review=review)` (prepare UI).
`selections` contains original integer `series_index`/`energy_index` pairs.
The existing **Export to openBIS** confirmation performs publication.

No schema extension is needed: the calculation uses `SPM_SIMULATION`, with
`IMAGING_DATA` datasets linked to it through the established DSS/Nanonis
SXM/DAT route. No fake measurement session, experimental instrument or
calibration is created. Do not classify a simulation as a real acquisition.

Constant-current STM is the z(x,y) isosurface of the simulated 3D field.
Its simulation parameters are bias and isovalue, corresponding to experimental
bias and current; no pA equivalence is inferred.

Each SXM retains bias and energy relative to EF, series parameters (height or isovalue,
broadening, tip settings), source/workflow/retrieved/structure UUIDs and the
original `stm.npz` SHA256. Each openBIS image dataset contains one SXM file.
The linked AiiDA archive retains the original arrays and XY grids, and Imaging
metadata stores the conversion parameters. A height map uses Å above the
highest atom natively and SI metres in SXM. Constant-height STM channels represent simulated current in native arbitrary
units. STS maps represent simulated dI/dV in native arbitrary units, whether
sampled at constant height or on a constant-current surface. Constant-current
STM (constant isovalue in the simulation) exports a height map. An STS map on
that surface remains dI/dV, not height. Existing experimental channel scaling is unchanged.

The SXM image area has explicit width, height and XY centre in Å. By default
it is the smallest Cartesian rectangle containing the native simulation cell's
A/B parallelogram. `describe_stm_imaging(source_uuid)` supplies this plain
geometry; `review_stm_imaging(..., image_area={"width_angstrom": ...,
"height_angstrom": ..., "center_angstrom": [x, y]})` freezes a chosen area.

Native CP2K `CELL.PERIODIC` from the STM's SCF producer controls lattice tiling,
independently of source-node PBC flags. Inverse-grid linear interpolation
samples Cartesian pixel centres and crosses periodic seams, filling the
corner regions of an oblique cell's bounding rectangle. Nonperiodic regions
outside the computed map remain NaN; incomplete periodic domains are rejected
rather than extrapolated. Cell/PBC, exact raster size, spacing and interpolation
revision are recorded. The raw selected map and full native grid metadata are
not modified or recentered. Optional DATs are explicitly selected **STS point
spectra** or **STM distance profiles**, using the same native-grid interpolation.
Global image averages are not offered.
The compatibility backward SXM buffer is a reversed copy of the same field,
explicitly annotated, because the deployed reader expects two buffers.
The setpoint records the actual 3D-field isovalue (native units) or height
(Å), with its simulation role explicit. Timing/gain zeros are format placeholders,
not physical measurements.

## Choose the ELN thumbnail

In the common export review, open **Choose a calculated STM/STS image**.
Select the map series, enter a bias and click **Use this map as ELN preview**.
The nearest stored bias is shown explicitly, and the image in use updates below.
You can choose STM current, STM isovalue topography or an STS dI/dV map.
A deliberately selected uniform map is allowed and labelled as uniform;
out-of-range biases and maps without finite values are rejected.

This selects only the simulation object's ELN thumbnail. It does not change the
SXM maps, DAT curves or their native values. **Replace preview** still accepts
your own PNG/JPEG; choosing a map afterwards replaces that upload. The last
applied image is the one used at the normal export confirmation.
The initial suggestion avoids uniform maps at the nominal ±0.5 V biases,
which can occur in an energy gap, and labels the actual stored bias used.

## Recovery and provenance

The `aiidalab_simulated_stm` key in `$IMAGING_DATA_CONFIG` metadata identifies a
dataset by workflow UUID, original archive SHA256, selected series/energy and
format revision, SXM area and sampling policy. Area changes distinguish map
datasets; point/profile coordinates and the profile bias determine their own
area-independent DAT identity. Retry discovers this identity from the server, not AiiDA
extras. Multiple matches or an unreadable inventory stop publication; absent
preview state is repaired on the existing dataset. All local files are
validated before the standard exporter writes simulation/archive objects.
Microscopy publication reuses that standard result and never creates a second
AIIDA_NODE archive. A failed microscopy step is an incomplete export, even if
the simulation archive is already present.

This client-side key is not a server uniqueness constraint. Avoid concurrent
publication of the same source/selection from separate clients. A normal
reimport retaining UUIDs/raw content can reuse the existing dataset; a changed
UUID or archive content is a different identity and must be reviewed.

## Tests / deployment boundary

Run `pytest -q tests/test_simulated_nanonis.py tests/test_stm_imaging.py
 tests/test_export_bridge.py` with isolated AiiDA state. Tests use synthetic
arrays and an isolated real provenance graph; simulated server tests cover
partial-preview retry and ambiguous identity. No private experimental file is
included as a fixture. Actual server previews require its Nanonis adaptors/DSS
service and are a separate qualification step. Older server Spm bundles may
render an unknown simulated channel unit as `N/A`; preserve the explicit native
unit in metadata/control configuration and verify the real rendering. Do not
substitute a fabricated ampere channel.

The current public adaptor imports a top-level `spmpy` package. An offline
check of the copy bundled alongside it found an incompatible `scan_range`
access in its plotting code; this does not identify the package deployed by
a particular server. Qualify the actual server renderer, including channel
units and DAT axes, before deployment.

## Channels

The established uploader derives its channel selectors from the file; it does
not require an experimental Current/Z combination. Simulation SXM uses either
`Z [m]` for constant-current topography, `Simulated_STM_au` for constant-height
current, or `Simulated_dIdV_au` for STS at height/on a constant-current surface.
Only the established Z-to-nm display conversion is applied. Point-spectrum DAT
uses Bias [V] versus native dI/dV; profile DAT uses Distance [angstrom] versus
height [angstrom] or native simulated current. Simulation metadata bypasses
experimental setpoint/lock-in formatting; an isovalue is never labelled pA.
The microscopy viewer controls its own colormap/contrast independently.

The common review counts SXM map datasets, grouped DAT datasets and individual
curves. Each map series/bias pair is one SXM. Each local-sampling group is one
DAT dataset, with one file per named point or line and a sampling JSON sidecar.
Existing matching identities are reused. The review freezes the current
selection, not previously rendered figures.

## Local sampling API

`review_stm_imaging(source_uuid, selections, image_area=..., sampling=requests)`
uses plain requests, for example:

```python
requests = [{
    "kind": "sts_points", "series_index": 2,
    "points": [{"id": "P1", "color": "#1f77b4", "position_angstrom": [3.0, 4.0]}],
}]
# Or one STM map at the chosen stored energy index:
requests = [{
    "kind": "stm_lines", "series_index": 1, "energy_index": 50,
    "lines": [{"id": "L1", "color": "#1f77b4",
               "start_angstrom": [2.0, 3.0], "end_angstrom": [5.0, 4.0]}],
}]
```

STS evaluates every stored energy at each fixed XY point. STM evaluates each
line at its one selected bias, with an explicit distance axis and both endpoints.
Point spectra require STS, and distance profiles require STM. Missing values
remain missing; a marker with no available data is rejected before writes.
`download_stm_sampling(source_uuid, requests)` returns a DAT/metadata ZIP without
server writes. Colours identify points/lines locally and are recorded in metadata;
the server retains its existing grouping/colormap controls.
