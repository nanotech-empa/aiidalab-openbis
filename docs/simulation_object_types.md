# Simulation Object Types for openBIS ELN

## Common principles

Each simulation object type has its own openBIS object type.

Each simulation object must have:

```text
ELN_PREVIEW
```

Each simulation object must have one provenance path:

```text
AiiDA simulation:
    aiida_node → AIIDA_NODE object containing the .aiida archive

Non-AiiDA simulation:
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

Every AiiDA-generated result also records:

```text
aiida_source_uuid: UUID of the concrete WorkChain that produced the result
aiida_result_role: stable role within that WorkChain, for example bands or pdos
```

Together with object type and target collection, these fields prevent duplicate
results while allowing the same calculation to be published in another space.
The linked `AIIDA_NODE` archive remains shared across spaces.

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

# REACTION_BARRIER

## Object type

`REACTION_BARRIER`

## Definition

Simulation that computes the energy barrier between two or more `ATOMISTIC_MODEL` objects along a reaction path.

## Suggested method families

```text
DFT
TB
MFH-TB
CASSCF
ForceField
MLPotential
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
ATOMISTIC_MODEL
```

Relations:

```text
reactant ATOMISTIC_MODEL → REACTION_BARRIER
product ATOMISTIC_MODEL → REACTION_BARRIER
```

Optional:

```text
intermediate/input-path ATOMISTIC_MODEL[]
```

## Child objects

Optional:

```text
transition_state ATOMISTIC_MODEL
optimized_path ATOMISTIC_MODEL[]
```

Relations:

```text
REACTION_BARRIER → transition_state ATOMISTIC_MODEL
REACTION_BARRIER → optimized_path ATOMISTIC_MODEL[]
```

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
path_method: enum
forward_barrier_ev: float (eV)
converged: boolean
```

## Optional properties

```text
backward_barrier_ev: float (eV)
number_of_images: integer
reaction_coordinate_description: text
spin_multiplicity: integer
total_magnetization_bohr_magneton: float (Bohr magnetons)
comments: text
```

## `path_method` vocabulary

```text
CI-NEB
dimer
TS_search
Constrained
```

## Required linked content

```text
parents: reactant ATOMISTIC_MODEL, product ATOMISTIC_MODEL
optional children: transition_state ATOMISTIC_MODEL, optimized_path ATOMISTIC_MODEL[]
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
full path arrays
full trajectory
all intermediate geometries
all force arrays
```

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
CHARGE_ANALYSIS
DOS
REACTION_BARRIER
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
CHARGE_ANALYSIS
DOS
REACTION_BARRIER
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

A simulation result is identified by `AIIDA_SOURCE_UUID` together with
`AIIDA_RESULT_ROLE`. It is created at most once within an openBIS space. If the
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
