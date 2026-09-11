# Simulation Object Types for openBIS ELN

## Common principles

Each simulation object type has its own openBIS object type.

Each simulation object must have:

```text
ELN_PREVIEW
```

Each simulation object must have one provenance path:

```text
AiiDA simulation exported from the local database:
    aiida_node → AIIDA_NODE object containing the .aiida archive

Simulation uploaded manually with an AiiDA archive:
    aiida_node → AIIDA_NODE object containing the uploaded .aiida archive

Simulation without an AiiDA archive:
    input_output_bundle dataset containing relevant input/output files
```

Simulation objects link to executables, not directly to codes or computers.

```text
SIMULATION_OBJECT → EXECUTABLE → CODE
SIMULATION_OBJECT → EXECUTABLE → COMPUTER
```

Therefore, `code` and `computer` should not be duplicated on simulation objects.

Physical quantities use openBIS `REAL` properties so they can be searched and
sorted numerically. The unit is fixed by the property code and label; exporters
must convert values before saving them. The canonical units are Hartree for total
energies, eV for electronic energies and barriers, Hartree/bohr for forces, Bohr
magnetons for magnetization, volts, angstrom, femtoseconds, kelvin, and bar.

### AiiDA result identity

Every AiiDA-generated simulation object records:

```text
AIIDA_SOURCE_UUID: UUID of the concrete WorkChain that produced the result
```

This is a conditional requirement for an AiiDA-generated object and is omitted
for a non-AiiDA simulation. It is assigned by the exporter and is not editable
by the user.

`AIIDA_SOURCE_UUID` identifies the concrete result-producing WorkChain, rather
than the AiiDA installation or the archive object. Importing an AiiDA archive on
another installation preserves this UUID.

The result role is already expressed by the simulation object type; an
additional `AIIDA_RESULT_ROLE` property would duplicate that information.
Within one openBIS space, the exporter therefore searches by object type and
`AIIDA_SOURCE_UUID`. If it finds a match, it reuses the existing object
instead of creating a duplicate. The same AiiDA result may still be published
as a distinct simulation object in another openBIS space.

This identity does not determine archive boundaries. The exporter
creates or reuses one `AIIDA_NODE` for each main AiiDA WorkChain selected by
the provenance traversal. Multiple result objects from that block share its
`AIIDA_NODE`. For example, `ENERGY_CALCULATION` and `CHARGE_ANALYSIS`
created from one `Cp2kScfWorkChain` share one archive, while a preceding
`Cp2kGeoOptWorkChain` has a separate archive. Shared inventory objects,
including `AIIDA_NODE`, remain globally reusable.

### Root processes in manually uploaded archives

A manually uploaded `.aiida` file always belongs to one automatically
created `AIIDA_NODE`; it is not attached directly to the simulation object.
Other uploaded input/output files remain datasets of the simulation object.

Before writing to openBIS, the app opens the archive through AiiDA's read-only
SQLite ZIP backend and identifies every `ProcessNode` without an incoming
`CALL_CALC` or `CALL_WORK` link. These are the archive root processes.

`AIIDA_ROOT_UUIDS` stores every identified root UUID. For one root,
`WFMS_UUID` also stores that UUID as the canonical archive root used by existing
viewer and duplicate-detection code. For zero or more than one root,
`WFMS_UUID` is left empty because it is a singular legacy property. Earlier
records that stored root UUID markers in `COMMENTS` remain readable, but new
records use the structured `AIIDA_ROOT_UUIDS` property.

Automatically generated archives contain one main/root WorkChain, so both
properties contain its UUID. UUIDs of result-producing descendants are not
added to `AIIDA_ROOT_UUIDS`; each simulation object records its concrete
producer in `AIIDA_SOURCE_UUID` instead.

On import, the archive is inspected again and all root UUIDs are reported. A
viewer link is offered independently for every root process type supported by
the receiving AiiDAlab installation. Importing still restores the complete
archive provenance graph and relies on AiiDA's UUID deduplication.

A manually uploaded archive can describe an unsupported or unclassified AiiDA
workflow. In that case the simulation may omit `AIIDA_SOURCE_UUID`, because
the app cannot reliably assign the simulation result to one concrete producing
process, but it must still link to its `AIIDA_NODE`.

## AiiDA export resolution

The exporter resolves provenance in three steps:

1. A CODE name in openBIS must occur in the AiiDA Code label after converting
   both values to lowercase and removing punctuation and whitespace. The AiiDA
   Code description is not used for CODE matching.
2. A COMPUTER name in openBIS must occur in either the AiiDA Computer label or
   its description after the same normalization. The label is checked first.
3. An EXECUTABLE is identified by the AiiDA Code UUID when available, with its
   CODE, COMPUTER, executable path, plugin entry point, full label, and inferred
   version recorded as provenance.

If more than one equally specific object matches, automatic resolution stops.
When automatic matching fails, the export widget allows the user to select an
existing CODE or COMPUTER explicitly, or create a new one in the appropriate
collection. New COMPUTER objects require an ORGANISATION location. Exact-name
duplicates are refused.

A missing EXECUTABLE can likewise be mapped to an existing object or explicitly
confirmed for creation. User selections are keyed by AiiDA UUID, and newly
created EXECUTABLE objects record those UUIDs for automatic reuse. This preflight
finishes before any AiiDA archive or simulation object is uploaded.

## Global method families

Controlled vocabulary:

```text
DFT
TB
MFH-TB
DMRG
CAS
CASSCF
ForceField
MLPotential
other
```

## Global method modifiers

Controlled vocabulary:

```text
hybrid
vdW
DFT+U
spin_collinear
spin_orbit
spin_non_collinear
```

`method_modifiers` is a multi-value field.

Examples:

```text
[]
["vdW"]
["hybrid", "vdW"]
["hybrid", "spin_orbit"]
["DFT+U", "spin_collinear"]
```

`spin_collinear` and `spin_non_collinear` should not be used together.

---

# ENERGY_CALCULATION

## Object type

`ENERGY_CALCULATION`

## Definition

Simulation that computes the energy of a fixed `ATOMISTIC_MODEL`,
`MOLECULE_CONCEPT`, or `CRYSTAL_CONCEPT` without intentionally modifying its
geometry.

## Suggested method families

```text
DFT
DFTB
TB
MFH-TB
DMRG
CAS
CASSCF
ForceField
MLPotential
```

## Parent objects

Required (one or more of):

```text
ATOMISTIC_MODEL[]
MOLECULE_CONCEPT[]
CRYSTAL_CONCEPT[]
```

Relations:

```text
ATOMISTIC_MODEL → ENERGY_CALCULATION
MOLECULE_CONCEPT → ENERGY_CALCULATION
CRYSTAL_CONCEPT → ENERGY_CALCULATION
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
image of the input ATOMISTIC_MODEL, MOLECULE_CONCEPT, or CRYSTAL_CONCEPT
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
charge: float
total_energy_hartree: float (Hartree)
converged: boolean
```

## Optional properties

```text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
fermi_energy_ev: float[] (eV)
electronic_gap_ev: float[] (eV)
comments: text
```

## Required linked content

```text
parents: ATOMISTIC_MODEL[], MOLECULE_CONCEPT[], and/or CRYSTAL_CONCEPT[]
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
```

---

# GEOMETRY_OPTIMISATION

## Object type

`GEOMETRY_OPTIMISATION`

## Definition

Simulation that optimizes the geometry of an `ATOMISTIC_MODEL`, optionally including optimization of the simulation cell.

## Suggested method families

```text
DFT
DFTB
CASSCF
ForceField
MLPotential
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → GEOMETRY_OPTIMISATION
```

## Child objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
GEOMETRY_OPTIMISATION → ATOMISTIC_MODEL
```

The child `ATOMISTIC_MODEL` represents the optimized geometry.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
image of the optimized ATOMISTIC_MODEL
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
charge: number
constrained: boolean
cell_optimization: boolean
final_energy_hartree: float (Hartree)
converged: boolean
```

## Optional properties

```text
constraints_description: text
cell_constraints: string
final_max_force_hartree_per_bohr: float (Hartree/bohr)
number_of_steps: integer
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
fermi_energy_ev: float[] (eV)
electronic_gap_ev: float[] (eV)
comments: text
```

## Required linked content

```text
parent: input ATOMISTIC_MODEL
child: optimized ATOMISTIC_MODEL
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
trajectory
intermediate geometries
forces on all atoms
```

---

# BAND_STRUCTURE

## Object type

`BAND_STRUCTURE`

## Definition

Simulation that computes the electronic band structure of an `ATOMISTIC_MODEL`
or `CRYSTAL_CONCEPT`.

## Suggested method families

```text
DFT
TB
MFH-TB
```

## Parent objects

Required (one or more of):

```text
ATOMISTIC_MODEL
CRYSTAL_CONCEPT
```

Relations:

```text
ATOMISTIC_MODEL → BAND_STRUCTURE
CRYSTAL_CONCEPT → BAND_STRUCTURE
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
band-structure plot
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
band_gap_ev: float (eV)
converged: boolean
```

## Optional properties

```text
fermi_energy_ev: float[] (eV)
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
k_path: string
electronic_gap_type: enum
comments: text
```

## `electronic_gap_type` vocabulary

```text
direct
indirect
unknown
```

## Required linked content

```text
parent: ATOMISTIC_MODEL and/or CRYSTAL_CONCEPT
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full band arrays
full k-point arrays
full eigenvalue arrays
full projected-band arrays
```

---

# BAND_UNFOLDING

## Object type

`BAND_UNFOLDING`

## Definition

Electronic spectral weights unfolded from a supercell calculation onto a
primitive-cell k-path. This is distinct from `BAND_STRUCTURE`: the latter is a
direct band calculation, while this object records an unfolding result.

The same object type is used for QE/BandUPpy and CP2K sparse-atomic-orbital
unfolding. The implementation is recorded explicitly.

## Suggested method families

```text
DFT
TB
MFH-TB
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

The parent is the supercell structure used as input to the unfolding workflow.
Reference-cell structures generated internally remain in the AiiDA archive and
are not created as extra openBIS objects solely for unfolding.

Relation:

```text
ATOMISTIC_MODEL → BAND_UNFOLDING
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

For QE this includes `pw.x` and BandUPpy; for CP2K it includes CP2K and the
unfolding executable when it is represented by a distinct AiiDA Code.

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
unfolded-band spectral-weight plot
```

Required if non-AiiDA:

```text
input_output_bundle
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
unfolding_implementation: enum
supercell_matrix: text containing a JSON matrix
k_path: string
converged: boolean
```

## Optional properties

```text
fermi_energy_ev: float[] (eV)
energy_min_ev: float (eV relative to the stored reference)
energy_max_ev: float (eV relative to the stored reference)
projection_description: text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `unfolding_implementation` vocabulary

```text
BANDUPPY
CP2K_SPARSE_AO
OTHER
```

## AiiDA mapping

- `QeBanduppyUnfoldingWorkChain` maps to `BANDUPPY`.
- A `Cp2kScfWorkChain` with `unfolding_retrieved` maps to `CP2K_SPARSE_AO`.
- Charge, spin, exchange-correlation method, hybrid/vdW modifiers, supercell
  matrix, k-path, reference/Fermi level, and plotted energy window are extracted
  automatically when available.
- `AIIDA_SOURCE_UUID` is the UUID of the concrete unfolding-producing WorkChain.

## Required linked content

```text
parent: input supercell ATOMISTIC_MODEL
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full unfolded-band arrays
full spectral-weight arrays
full k-point arrays
full eigenvalue arrays
projection matrices and sparse-overlap data
input and output files
restart files
stdout/stderr
```

---


# CHARGE_ANALYSIS

## Object type

`CHARGE_ANALYSIS`

## Definition

Simulation or post-processing analysis that computes atomic, orbital, fragment, or spatial charge information for a fixed `ATOMISTIC_MODEL`.

## Suggested method families

```text
DFT
TB
MFH-TB
CAS
CASSCF
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → CHARGE_ANALYSIS
```

Optional, if the charge analysis derives from a previous calculation:

```text
ENERGY_CALCULATION
```

Relation:

```text
ENERGY_CALCULATION → CHARGE_ANALYSIS
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

The list may include both the executable used for the underlying electronic-structure calculation and the executable used for the charge analysis.

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
image of the input ATOMISTIC_MODEL, preferably coloured or annotated by charge if available
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including a file containing the computed charges
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
charge_analysis_method: string
converged: boolean
```

## Optional properties

```text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
fermi_energy_ev: float[] (eV)
electronic_gap_ev: float[] (eV)
comments: text
```

## Required linked content

```text
parent: ATOMISTIC_MODEL
optional parent: ENERGY_CALCULATION
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full charge tables
full volumetric charge files
```

---

# DOS

## Object type

`DOS`

## Definition

Simulation or post-processing analysis that computes the electronic density of
states of an `ATOMISTIC_MODEL`, `MOLECULE_CONCEPT`, or `CRYSTAL_CONCEPT`.

If projected density of states is included, set:

```text
PDOS = true
```

## Suggested method families

```text
DFT
TB
MFH-TB
```

## Parent objects

Required (one or more of):

```text
ATOMISTIC_MODEL
MOLECULE_CONCEPT
CRYSTAL_CONCEPT
```

Relations:

```text
ATOMISTIC_MODEL → DOS
MOLECULE_CONCEPT → DOS
CRYSTAL_CONCEPT → DOS
```

Optional, if the DOS derives from a previous calculation:

```text
ENERGY_CALCULATION
```

Relation:

```text
ENERGY_CALCULATION → DOS
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
DOS or PDOS plot
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including a file containing the DOS/PDOS data
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
PDOS: boolean
converged: boolean
```

## Required if `PDOS = true`

```text
projection_description: text
```

## Optional properties

```text
fermi_energy_ev: float[] (eV)
energy_min_ev: float (eV)
energy_max_ev: float (eV)
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
electronic_gap_ev: float[] (eV)
comments: text
```

## Required linked content

```text
parents: ATOMISTIC_MODEL, MOLECULE_CONCEPT, and/or CRYSTAL_CONCEPT
optional parent: ENERGY_CALCULATION
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full DOS arrays
full PDOS arrays
full projection arrays
```

---

# MINIMUM_ENERGY_PATH

## Object type

`MINIMUM_ENERGY_PATH`

## Definition

One computed path between two endpoint `ATOMISTIC_MODEL` objects. It may be
obtained from a nudged-elastic-band calculation, a constrained replica chain,
or another explicitly described path method.

`REACTION_BARRIER` is deliberately not redefined here. Its eventual scope
(for example free-energy barriers obtained from molecular dynamics, umbrella
sampling, or metadynamics) must be agreed separately. A MEP nevertheless
contains its forward and backward barrier values as compact summaries of the
stored energy profile.

## Suggested method families

```text
DFT
TB
MFH-TB
ForceField
MLPotential
```

## Parent objects

Required:

```text
initial ATOMISTIC_MODEL
final ATOMISTIC_MODEL
```

Relations:

```text
initial ATOMISTIC_MODEL → MINIMUM_ENERGY_PATH
final ATOMISTIC_MODEL → MINIMUM_ENERGY_PATH
```

Optional:

```text
preceding MINIMUM_ENERGY_PATH
```

The optional preceding path records scientific-block provenance, for example
replica chain → NEB or NEB → continued NEB. Each block keeps its own
`AIIDA_NODE` and therefore its own minimally scoped `.aiida` archive.

Intermediate images are intentionally not registered as additional
`ATOMISTIC_MODEL` objects. They remain available from the linked AiiDA archive
or, for a non-AiiDA result, from the input/output bundle.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
energy profile plot along the reaction coordinate
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including a file containing the reaction-path energies
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
mep_method: enum
relative_energies_ev: float[] (eV, relative to the initial endpoint)
forward_barrier_ev: float (eV)
backward_barrier_ev: float (eV)
converged: boolean
number_of_images: integer
```

## Optional properties

```text
neb_variant: enum
other_method_description: text
collective_variables: text
constraints_description: text
reaction_coordinate_description: text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `mep_method` vocabulary

```text
NEB
REPLICA_CHAIN
OTHER
```

`neb_variant` is required when `mep_method = NEB`:

```text
NEB
CI_NEB
```

`collective_variables` is required for `REPLICA_CHAIN` and records the
definitions, targets, increments, and actual values when available.
`other_method_description` is required for `OTHER`. Constraints are stored
for both NEB and replica-chain calculations when present.

## Required linked content

```text
parents: initial ATOMISTIC_MODEL, final ATOMISTIC_MODEL
optional parent: preceding MINIMUM_ENERGY_PATH
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

The `ELN_PREVIEW` is the final energy-profile plot. For an AiiDA-generated
result it is proposed automatically and may be replaced by the user before
export.

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full path arrays
all intermediate geometries
all force arrays
```

## AiiDA mapping

- `Cp2kReplicaWorkChain` → `mep_method = REPLICA_CHAIN`
- `Cp2kNebWorkChain` → `mep_method = NEB`
- A continuation is a new `MINIMUM_ENERGY_PATH`, linked to the preceding MEP.
- A preceding geometry optimization remains a separate simulation/archive block.

---

# SPM_SIMULATION

## Object type

`SPM_SIMULATION`

## Definition

Simulation that computes a scanning probe microscopy observable for an `ATOMISTIC_MODEL`.

## Suggested method families

```text
DFT
TB
MFH-TB
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → SPM_SIMULATION
```

Optional, if the SPM simulation derives from a previous electronic-structure calculation:

```text
ENERGY_CALCULATION
```

Relation:

```text
ENERGY_CALCULATION → SPM_SIMULATION
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
simulated SPM image or representative SPM map
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including the simulated SPM image/map data
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
spm_mode: enum
converged: boolean
```

## Optional properties

```text
bias_voltage_v: float (V)
height_angstrom: float (angstrom)
isovalue_au: float (a.u.)
tip_model: string
scan_area: string
image_mode: string
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `spm_mode` vocabulary

```text
STM
STS
nc-AFM
other
```

## Required linked content

```text
parent: ATOMISTIC_MODEL
optional parent: ENERGY_CALCULATION
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full volumetric grids
full cube files
full raw SPM arrays
```

---

# VIBRATIONAL_SPECTROSCOPY

## Object type

`VIBRATIONAL_SPECTROSCOPY`

## Definition

Simulation that computes vibrational properties of an `ATOMISTIC_MODEL`.

## Suggested method families

```text
DFT
TB
ForceField
MLPotential
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → VIBRATIONAL_SPECTROSCOPY
```

## Child objects

None required.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
vibrational spectrum, phonon band structure, phonon DOS, IR spectrum, Raman spectrum, or representative vibrational plot
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including vibrational frequencies, spectra, or phonon data
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
vibrational_mode: enum
converged: boolean
```

## Optional properties

```text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `vibrational_mode` vocabulary

```text
Phonons
IR
Raman
IR+Raman
```

## Required linked content

```text
parent: ATOMISTIC_MODEL
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full force-constant matrices
full dynamical matrices
full normal-mode eigenvectors
full phonon arrays
full spectra arrays
```

---

# MOLECULAR_DYNAMICS

## Object type

`MOLECULAR_DYNAMICS`

## Definition

Simulation that propagates an `ATOMISTIC_MODEL` in time to generate a molecular dynamics trajectory.

## Suggested method families

```text
DFT
TB
ForceField
MLPotential
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → MOLECULAR_DYNAMICS
```

Optional, if the MD starts from a previously optimized geometry:

```text
GEOMETRY_OPTIMISATION
```

Relation:

```text
GEOMETRY_OPTIMISATION → MOLECULAR_DYNAMICS
```

## Child objects

Optional:

```text
ATOMISTIC_MODEL
```

Relation:

```text
MOLECULAR_DYNAMICS → ATOMISTIC_MODEL
```

The child `ATOMISTIC_MODEL` may represent the final structure or a representative snapshot from the trajectory.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
representative MD snapshot, trajectory snapshot, or time-series plot
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files, including the trajectory or trajectory reference
```

## Required properties

```text
name: string
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
time_step_fs: float (fs)
total_time_fs: float (fs)
completed: boolean
```

## Optional properties

```text
ensemble: enum
temperature_k: float (K)
pressure_bar: float (bar)
thermostat: string
barostat: string
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `ensemble` vocabulary

```text
NVE
NVT
NPT
other
```

## Required linked content

```text
parent: initial ATOMISTIC_MODEL
optional parent: GEOMETRY_OPTIMISATION
optional child: final or representative ATOMISTIC_MODEL
executables: EXECUTABLE[]
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
full trajectory
all trajectory frames
velocities
forces on all atoms
large time-series arrays
```

---

# UNCLASSIFIED_SIMULATION

## Object type

`UNCLASSIFIED_SIMULATION`

## Definition

Fallback simulation object for computational results that do not yet fit one of the defined simulation object types.

Use only when the simulation cannot be cleanly classified as:

```text
ENERGY_CALCULATION
GEOMETRY_OPTIMISATION
BAND_STRUCTURE
BAND_UNFOLDING
CHARGE_ANALYSIS
DOS
MINIMUM_ENERGY_PATH
SPM_SIMULATION
VIBRATIONAL_SPECTROSCOPY
MOLECULAR_DYNAMICS
```

## Suggested method families

```text
DFT
TB
MFH-TB
DMRG
CAS
CASSCF
ForceField
MLPotential
other
```

## Parent objects

Required if applicable (one or more of):

```text
ATOMISTIC_MODEL[]
MOLECULE_CONCEPT[]
CRYSTAL_CONCEPT[]
```

When no `ATOMISTIC_MODEL` is available as input, link the simulation directly to
the applicable molecule concept, crystal concept, or both.

Relations:

```text
ATOMISTIC_MODEL → UNCLASSIFIED_SIMULATION
MOLECULE_CONCEPT → UNCLASSIFIED_SIMULATION
CRYSTAL_CONCEPT → UNCLASSIFIED_SIMULATION
```

Optional, if the unclassified simulation derives from another simulation:

```text
ENERGY_CALCULATION
GEOMETRY_OPTIMISATION
BAND_STRUCTURE
BAND_UNFOLDING
CHARGE_ANALYSIS
DOS
MINIMUM_ENERGY_PATH
SPM_SIMULATION
VIBRATIONAL_SPECTROSCOPY
MOLECULAR_DYNAMICS
UNCLASSIFIED_SIMULATION
```

## Child objects

Optional:

```text
ATOMISTIC_MODEL[]
```

Relation:

```text
UNCLASSIFIED_SIMULATION → ATOMISTIC_MODEL
```

Use only if the simulation produces new atomistic models.

## Object references

Required if known:

```text
executables: EXECUTABLE[]
```

Required if AiiDA-generated:

```text
aiida_node: AIIDA_NODE
```

## Required datasets

```text
ELN_PREVIEW
```

Content:

```text
representative image, plot, structure snapshot, or workflow summary image
```

Required if non-AiiDA:

```text
input_output_bundle
```

Content:

```text
tar.gz or zip with relevant input/output files
```

## Required properties

```text
name: string
simulation_description: text
converged: boolean
```

## Optional properties

```text
method_family: enum
method_modifiers: enum[]
method_label: string
charge: number
main_result_description: text
main_result_value_numeric: float
main_result_unit: string
comments: text
```

## Required linked content

```text
parents: ATOMISTIC_MODEL[], MOLECULE_CONCEPT[], and/or CRYSTAL_CONCEPT[], if applicable
children: ATOMISTIC_MODEL[], if produced
executables: EXECUTABLE[], if known
ELN_PREVIEW: image dataset
aiida_node: AIIDA_NODE, if AiiDA
input_output_bundle: dataset, if non-AiiDA
```

## Do not duplicate if `aiida_node` exists

```text
full input files
full output files
full input dictionaries
full output dictionaries
basis-set details
pseudopotential details
cutoff details
k-point mesh
SCF iteration history
occupations
restart files
stdout/stderr
raw numerical arrays
large intermediate files
```

# AiiDAlab export behavior

For AiiDA-backed exports, the app renders an ELN preview suggestion for every
simulation result that will be represented in openBIS. The user can review each
suggestion and replace it with a dropped PNG or JPEG image before the export.
The generated suggestion is used when no replacement is supplied.

A simulation result is identified by its object type together with
`AIIDA_SOURCE_UUID`. It is created at most once within an openBIS space. If the
same result already exists elsewhere in the selected space, the app reuses it
and links to its existing collection. Exporting the same AiiDA result to a
different user space creates a separate simulation object there. Shared
inventory objects, including `ATOMISTIC_MODEL`, `AIIDA_NODE`, `CODE`,
`COMPUTER`, and `EXECUTABLE`, continue to be reused globally.

New `COMPUTER` records are placed according to their scope:

- local Empa desktops and laptops:
  `/LAB205_EQUIPMENT/COMPUTING_EQUIPMENT/COMPUTING_EQUIPMENT_LOCAL_IT_HARDWARE`
- external computers and HPC resources:
  `/LAB205_EQUIPMENT/COMPUTING_EQUIPMENT/COMPUTING_EQUIPMENT_EXTERNAL_AND_HPC_RESOURCES`

Existing computer records are never moved by the exporter.
