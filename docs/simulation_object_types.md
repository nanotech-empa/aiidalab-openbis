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

## Global method families

Controlled vocabulary:

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
other
```

The three method fields have different roles:

```text
method_family: broad controlled category
method_label: family-scoped method or model name
method_modifiers: zero or more compatible method qualifiers
```

`method_label` must be validated against `method_family`. For example, `PBE` is valid for `DFT`, but not for `TB`. Method-specific parameter files, basis sets, pseudopotentials, active spaces, trained-model versions, and similar detailed inputs remain in the provenance bundle or AiiDA archive.

### Candidate method labels by family

This is a curated vocabulary for review. Each family also permits `other`; the supplied value should then be recorded verbatim.

| `method_family` | Candidate `method_label` values |
| :--- | :--- |
| `DFT` | `LDA`, `PZ81`, `PW92`, `PBE`, `PBEsol`, `revPBE`, `RPBE`, `PW91`, `BLYP`, `TPSS`, `revTPSS`, `SCAN`, `r2SCAN`, `M06-L`, `PBE0`, `HSE03`, `HSE06`, `B3LYP`, `TPSSh`, `M06-2X`, `CAM-B3LYP`, `wB97X`, `wB97X-D`, `B2PLYP`, `r2SCAN-3c`, `PBEh-3c`, `B97-3c`, `other` |
| `DFTB` | `DFTB0`, `DFTB1`, `SCC-DFTB` (`DFTB2`), `DFTB3`, `LC-DFTB`, `TD-DFTB`, `GFN0-xTB`, `GFN1-xTB`, `GFN2-xTB`, `IPEA-xTB`, `other` |
| `TB` | `Slater-Koster TB`, `empirical TB`, `extended Huckel`, `Wannier TB`, `NRL-TB`, `second-moment TB`, `other` |
| `MFH-TB` | `mean-field Hubbard`, `extended Hubbard`, `PPP`, `Kane-Mele-Hubbard`, `other` |
| `DMRG` | `DMRG`, `iDMRG`, `tDMRG`, `finite-temperature DMRG`, `DMRG-SCF`, `DMRG-CASPT2`, `DMRG-NEVPT2`, `other` |
| `CAS` | `CASCI`, `RASCI`, `GASCI`, `other` |
| `CASSCF` | `CASSCF`, `SA-CASSCF`, `RASSCF`, `GASSCF`, `DMRG-SCF`, `other` |
| `ForceField` | `AMBER`, `CHARMM`, `GROMOS`, `OPLS-AA`, `GAFF`, `UFF`, `MMFF`, `COMPASS`, `DREIDING`, `MARTINI`, `EAM`, `MEAM`, `Finnis-Sinclair`, `Stillinger-Weber`, `Tersoff`, `REBO`, `AIREBO`, `EDIP`, `COMB`, `ReaxFF`, `other` |
| `MLPotential` | `Behler-Parrinello`, `GAP`, `SNAP`, `MTP`, `ACE`, `POD`, `ANI`, `DeepPot`, `SchNet`, `PaiNN`, `NequIP`, `Allegro`, `MACE`, `CHGNet`, `M3GNet`, `ALIGNN-FF`, `other` |
| `other` | Free-text method label |

Several important families do not fit the current vocabulary and should be considered separately: Hartree-Fock, semi-empirical quantum chemistry (`AM1`, `PM3`, `PM6`, `PM7`, `OM2`), Moller-Plesset perturbation theory, coupled cluster, general configuration interaction, multireference perturbation theory (`CASPT2`, `NEVPT2`), `GW`/`BSE`, and quantum Monte Carlo.

Reference lists: [Libxc functionals](https://libxc.gitlab.io/functionals/), [DFTB+ documentation](https://www.dftbplus.org/documentation.html), [xTB methods](https://xtb-docs.readthedocs.io/en/latest/basics.html), [OpenMolcas methods](https://molcas.gitlab.io/OpenMolcas/sphinx/users.guide/programs/rasscf.html), [block2 DMRG methods](https://block2.readthedocs.io/en/latest/), [GROMACS force fields](https://manual.gromacs.org/current/user-guide/force-fields.html), [LAMMPS interaction models](https://docs.lammps.org/pair_style.html), [NequIP](https://nequip.readthedocs.io/en/latest/), and [MACE models](https://mace-docs.readthedocs.io/en/latest/guide/foundation_models.html).

## Global method modifiers

`method_modifiers` is a multi-value field. Values are family-scoped rather than universally valid.

| Compatible family | Candidate modifier values |
| :--- | :--- |
| `DFT` | `hybrid`, `range_separated`, `double_hybrid`, `DFT+U`, `D2`, `D3`, `D3(BJ)`, `D4`, `TS`, `MBD`, `vdW-DF`, `vdW-DF2`, `rVV10`, `spin_collinear`, `spin_non_collinear`, `spin_orbit` |
| `DFTB` | `SCC`, `third_order`, `DFTB+U`, `long_range_corrected`, `D3`, `D4`, `spin_collinear`, `spin_non_collinear`, `spin_orbit` |
| `TB` | `orthogonal`, `non_orthogonal`, `spin_collinear`, `spin_non_collinear`, `spin_orbit` |
| `MFH-TB` | `restricted`, `unrestricted`, `spin_collinear`, `spin_non_collinear`, `spin_orbit` |
| `DMRG` | `finite_system`, `infinite_system`, `time_dependent`, `finite_temperature`, `spin_adapted`, `state_averaged`, `spin_orbit` |
| `CAS`, `CASSCF` | `state_specific`, `state_averaged`, `restricted_active_space`, `generalized_active_space`, `spin_orbit` |
| `ForceField` | `all_atom`, `united_atom`, `coarse_grained`, `reactive`, `polarizable` |
| `MLPotential` | `equivariant`, `message_passing`, `local`, `long_range`, `charge_aware`, `foundation_model` |
| `other` | Free-text modifier |

Examples:

```text
method_family: DFT
method_label: PBE
method_modifiers: [D3, spin_collinear]

method_family: DFT
method_label: PBE0
method_modifiers: [hybrid]

method_family: TB
method_label: Wannier TB
method_modifiers: [spin_orbit]
```

`spin_collinear` and `spin_non_collinear` are mutually exclusive. A specific correction belongs in `method_modifiers`; for example, use `method_label: PBE` with modifier `D3`, not `method_label: PBE-D3`.

### Allowed families by simulation object

| Simulation object | Allowed `method_family` values |
| :--- | :--- |
| `ENERGY_CALCULATION` | `DFT`, `DFTB`, `TB`, `MFH-TB`, `DMRG`, `CAS`, `CASSCF`, `ForceField`, `MLPotential` |
| `GEOMETRY_OPTIMIZATION` | `DFT`, `DFTB`, `CASSCF`, `ForceField`, `MLPotential` |
| `BAND_STRUCTURE` | `DFT`, `TB`, `MFH-TB` |
| `CHARGE_ANALYSIS` | `DFT`, `TB`, `MFH-TB`, `CAS`, `CASSCF` |
| `DOS` | `DFT`, `TB`, `MFH-TB` |
| `REACTION_BARRIER` | `DFT`, `DFTB`, `CASSCF`, `ForceField`, `MLPotential` |
| `SPM` | `DFT`, `TB`, `MFH-TB`, `DMRG`, `CASSCF` |
| `VIBRATIONAL_SPECTROSCOPY` | `DFT`, `DFTB`, `ForceField`, `MLPotential` |
| `MOLECULAR_DYNAMICS` | `DFT`, `DFTB`, `ForceField`, `MLPotential` |
| `UNCLASSIFIED_SIMULATION` | Any global method family |

---

# ENERGY_CALCULATION

## Object type

`ENERGY_CALCULATION`

## Definition

Simulation that computes the energy of a fixed `ATOMISTIC_MODEL` without intentionally modifying its geometry.

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

Required:

```text
ATOMISTIC_MODEL [] list
Molecule concept [list] e.g. TB calculations
```

Relation:

```text
ATOMISTIC_MODEL → ENERGY_CALCULATION
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
image of the input ATOMISTIC_MODEL
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
charge: float (atomic units)
total_energy: float (Hartree)
converged: boolean
```

## Optional properties

```text
method_label: string
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
fermi_energy: float[] (eV)
electronic_gap: float[] (eV)
comments: text
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
```

---

# GEOMETRY_OPTIMIZATION

## Object type

`GEOMETRY_OPTIMIZATION`

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
ATOMISTIC_MODEL → GEOMETRY_OPTIMIZATION
```

## Child objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
GEOMETRY_OPTIMIZATION → ATOMISTIC_MODEL
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
charge: float (atomic units)
constrained: boolean
cell_optimization: boolean
final_energy: float (Hartree)
converged: boolean
```

## Optional properties

```text
method_label: string
constraints_description: text
cell_constraints: string
final_max_force: float (Hartree/bohr)
number_of_steps: integer
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
fermi_energy: float[] (eV)
electronic_gap: float[] (eV)
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

Simulation that computes the electronic band structure of an `ATOMISTIC_MODEL`.

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
ATOMISTIC_MODEL → BAND_STRUCTURE
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
charge: float (atomic units)
electronic_gap: float[] (eV)
converged: boolean
```

## Optional properties

```text
method_label: string
fermi_energy: float[] (eV)
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
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
charge: float (atomic units)
charge_analysis_method: string
converged: boolean
```

## Optional properties

```text
method_label: string
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
fermi_energy: float[] (eV)
electronic_gap: float[] (eV)
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

Simulation or post-processing analysis that computes the electronic density of states of an `ATOMISTIC_MODEL`.

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

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → DOS
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
charge: float (atomic units)
PDOS: boolean
converged: boolean
```

## Required if `PDOS = true`

```text
projection_description: text
```

## Optional properties

```text
method_label: string
fermi_energy: float[] (eV)
energy_min: float (eV)
energy_max: float (eV)
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
electronic_gap: float[] (eV)
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
charge: float (atomic units)
path_method: enum
forward_barrier: float (eV)
converged: boolean
```

## Optional properties

```text
method_label: string
backward_barrier: float (eV)
number_of_images: integer
reaction_coordinate_description: text
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
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

# SPM

## Object type

`SPM`

## Definition

Simulation that computes a scanning probe microscopy observable for an `ATOMISTIC_MODEL`.

## Suggested method families

```text
DFT
TB
MFH-TB
DMRG
CASSCF
```

## Parent objects

Required:

```text
ATOMISTIC_MODEL
```

Relation:

```text
ATOMISTIC_MODEL → SPM
```

Optional, if the SPM simulation derives from a previous electronic-structure calculation:

```text
ENERGY_CALCULATION
```

Relation:

```text
ENERGY_CALCULATION → SPM
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
charge: float (atomic units)
spm_mode: enum
converged: boolean
```

## Optional properties

```text
method_label: string
bias_voltage: float
height: float
isovalue: float
tip_model: string
scan_area: string
image_mode: string
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
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

Optional, if the vibrational calculation derives from a previous electronic-structure calculation:

```text
ENERGY_CALCULATION
GEOMETRY_OPTIMIZATION
```

Relations:

```text
ENERGY_CALCULATION → VIBRATIONAL_SPECTROSCOPY
GEOMETRY_OPTIMIZATION → VIBRATIONAL_SPECTROSCOPY
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
charge: float (atomic units)
vibrational_mode: enum
converged: boolean
```

## Optional properties

```text
method_label: string
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
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
optional parent: ENERGY_CALCULATION
optional parent: GEOMETRY_OPTIMIZATION
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
GEOMETRY_OPTIMIZATION
```

Relation:

```text
GEOMETRY_OPTIMIZATION → MOLECULAR_DYNAMICS
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
charge: float (atomic units)
time_step: float (fs)
total_time: float (ns)
number_of_steps: integer
completed: boolean
```

## Optional properties

```text
method_label: string
ensemble: enum
temperature: float
pressure: float
thermostat: string
barostat: string
spin_multiplicity: integer
total_magnetization: float (Bohr magnetons)
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
optional parent: GEOMETRY_OPTIMIZATION
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
GEOMETRY_OPTIMIZATION
BAND_STRUCTURE
CHARGE_ANALYSIS
DOS
REACTION_BARRIER
SPM
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

Required if applicable:

```text
ATOMISTIC_MODEL[]
```

Relation:

```text
ATOMISTIC_MODEL → UNCLASSIFIED_SIMULATION
```

Optional, if the unclassified simulation derives from another simulation:

```text
ENERGY_CALCULATION
GEOMETRY_OPTIMIZATION
BAND_STRUCTURE
CHARGE_ANALYSIS
DOS
REACTION_BARRIER
SPM
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
charge: float (atomic units)
main_result_description: text
main_result_value: float
comments: text
```

## Required linked content

```text
parent: ATOMISTIC_MODEL[], if applicable
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
