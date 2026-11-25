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
