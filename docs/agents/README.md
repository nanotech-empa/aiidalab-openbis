# Shared openBIS assistant: laboratory and simulation workflows

The shared chat pilot adapts Fabio Lopes's domain-query semantics from
ai_agent/tools.py. The original chatbot remains at 4_openbis_chatbot_legacy.ipynb;
AIIDALAB_OPENBIS_CHAT=legacy selects its link. Do not describe this first migration
as full parity: legacy vector document retrieval and its automatic archive-import
tool have not migrated. Do not import ai_agent.tools to obtain shared tools:
that legacy module has a different credential/session/dependency lifecycle.

## Establish identity before following relationships

Use openbis_status and openbis_schema for the configured connection and current
schema. Never request or quote a token. openbis_search is the general paginated
record tool. openbis_search_materials adds typed molecules, product molecules,
substances, crystals/concepts, 2D materials and samples.

Use product_molecule for MOLECULE records in PRODUCT_COLLECTION. Their
MOLECULE parents describe precursors. Precursors live in PRECURSOR_COLLECTION.
Use substance for physical vials and batches. Their molecular identity can be
recorded as a MOLECULE parent or an object-valued MOLECULES property. Crystals
reference CRYSTAL_CONCEPT.

Direct filters use server search semantics. Linked-molecule constraints compare
stored properties exactly: equal SMILES text is not general chemical equivalence.
Use the existing chemical-structure-search GUI for chemistry-aware identity.
Multiple records with the same name are separate candidates. Choose the exact
permID/identifier before querying provenance. Follow next_offset even when a
post-filtered page has no matches; candidate_total is not the matched total.

openbis_relationships follows simulations, sample provenance, measurements or
samples with an explicit depth/node budget. It uses bulk records, tracks cycles
and returns missing links/truncation. An incomplete or permission-limited graph
must never be presented as proof that no related record exists. Sample provenance
can branch; retain all visible branches and their direction.

## Submission and export across apps

Use list_apps/open_app to reach the installed scientific app, continue the same
conversation and consult that app's guide. A guide grants no execution capability;
use only registered tools or actual GUI controls. First prepare/review inputs,
then submit, record the UUID, inspect completion and scientific diagnostics.

For stored results use openbis_open_gui with export_simulations. The existing
form selects project/collection, related material, result cards and archive.
Only **Export** publishes. ORCA's result workspace and PythTB/Model Hamiltonians
also offer **Prepare openBIS export**; local-model preparation records existing
results with honest provenance rather than claiming the solver ran in AiiDA.
Native PythTB localhost/remote results use their original AiiDA model CalcJob and
exact referenced orbital and Wannier jobs. They are not notebook-local snapshots. Inspect
original UUIDs, actual Code/computer, worker fingerprint, model inputs and saved
convergence; orbital evaluation and Wannier localization reuse MFH without another SCF.
Wannier exports include the native postprocessing identity, energy reference,
localization diagnostics, stored Hamiltonian arrays and ZIP. Sharing a formula
or geometry alone does not establish that two models belong to one export.
Unknown runtime software versions must not be replaced with notebook versions.
Preparation reads only stored repository data, never remote scratch, and never
publishes. The native input and effective model PBC retain their separate identity.

Reuse existing schema types/method vocabularies. DMRG already exists; abstract
models use MODEL_HAMILTONIAN, with MODEL naming the Hamiltonian subtype and ED/DMRG identifying the solver, without invented atoms/charge/spin. A sampled
band path cannot certify a global gap. Convergence must follow stored evidence.

One source UUID identifies the provenance root; repeating the same export should
reuse its archive/objects. Inspect the recovery result after partial upload before
retrying. Do not delete unrelated records or rewrite scientific AiiDA nodes.
For import, use Import simulations in the same GUI. Inspect the selected archive,
receiving profile and restored root UUID; do not execute imports from model text.

## Quantum-computer route

For an ORCA quantum-assisted request, open ORCA and read orca.quantum-energy.
Confirm geometry, common orbitals and active space, then use the existing
Hamiltonian export, circuit generation, sampling and sampled-space solve stages.
The QPU supplies samples; the classical worker solves the projected Hamiltonian.
Ideal simulator validation is not hardware execution. Real hardware needs the
actual configured account/backend and an explicitly reviewed circuit/shot/budget
submission. Keep credentials in the worker account setup, never chat or AiiDA
inputs. Recover an uncertain request using its ledger before considering retry.
Export the resulting saved stage with its actual method/status; do not label
hardware preparation or simulator counts as a real QPU run.


Known automatic exports are classified: MODEL_HAMILTONIAN for spin/Hubbard and
finite/Wannier TB models; ELECTRONIC_STRUCTURE with an explicit result subtype
for ORCA state families, optical/Dyson spectra, Kondo exchange, orbital preparation,
native molecular DMRG and quantum/classical computing stages. Existing Energy,
Geometry, Band, DOS, Charge, SPM and Vibrational types remain in use. Unclassified
is a manual unknown-archive option, not a fallback for these supported apps.
Previously published Unclassified records require explicit reviewed migration;
re-export must not silently duplicate them under a new type.

## Direct app destinations

Read `workflow_pages` from `list_apps` and pass the requested key to `open_app`.
Use the returned link directly; do not substitute the default notebook for
another task. A source calculation remains separate from the chosen page.

- `chat`: `4_openbis_chatbot.ipynb`.
- `samples`: `1_sample_preparation.ipynb`.
- `measurements`: `2_sample_measurement.ipynb`.
- `simulations`: `3_import_export_simulations.ipynb`.
- `laboratory`: `0_home.ipynb`.

Only the `chat` destination has the shared conversation. The other pages use
the existing laboratory GUI; return to Home/chat for assistant help.

### STM microscopy export

Use the Surfaces `view_stm.ipynb` host's `app_prepare_export` and existing shared
review for the standard SPM simulation and AiiDA archive. Use **Keep to export**
to add the displayed series/bias and any current point or line curves. Repeat
for each desired map. Review only the kept entries. Confirm the project/experiment/material
references and the exact `export_stm_microscopy` action before publication.
The shared exporter preserves the AiiDA simulation/archive identity and creates
linked microscopy datasets; do not implement a second direct-write path in chat.
Inspect final dataset IDs and preview status. On interruption retry the existing
export, keeping partial server records. See
[STM microscopy format and recovery](../stm_microscopy_export.md).

For SXM area changes, use the visible width/height/centre controls in Å and
`stm.reset_image_area` for the native-cell rectangle. Inspect
`microscopy_image_area` and `microscopy_source_geometry` (native CP2K PBC).
Periodic filling follows lattice vectors, never artificial independent image
edge repetition. State area/PBC and map/curve counts in the export review;
changed controls invalidate it. Local point/line sampling uses physical original-grid coordinates,
independent of the SXM crop. Do not infer an experimental current calibration.

For local curves, choose `stm.analysis_series`, then the draft action
`stm.open_sampling_map`. STS supports points and all stored energies; STM
supports two-endpoint lines and the chosen `stm.analysis_bias`. Set
`stm.coordinate_x_angstrom`/`stm.coordinate_y_angstrom`, then invoke
`stm.add_coordinate` once per point or twice per line. Inspect
`microscopy_sampling` for labels, colours, coordinates, pending line endpoints
and validation. `stm.remove_marker`, `stm.clear_markers`, and
`stm.download_dat` operate on that same visible panel. Do not invent a global
average or treat STM distance profiles as STS spectra. Prepare/review the common
export only after the sampling state is valid; marker changes invalidate it.

### STM/STS ELN preview and molecule-name filter

The common export review includes **Choose a calculated STM/STS image**.
Select **Map series**, enter **Bias [V]**, inspect the reported stored bias and
click **Use this map as ELN preview**. Verify the updated thumbnail and **Image
in use**. Draft selector changes alone do not apply a new image. This action is
local and does not publish or change the SXM/DAT selections. File replacement
remains available. Use the existing confirmed export action for server writes.

**Find molecule** filters names, EMPA numbers and permIDs in the selected
collection without changing the linked molecule. Select a result explicitly.
A number-only record has no inferred chemical name; use the existing SMILES or
CDXML search when the requested name is absent.
