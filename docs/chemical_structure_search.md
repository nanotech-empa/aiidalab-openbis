# Molecular concepts and structural search

Both finite precursor molecules and periodic reaction products use the openBIS
`MOLECULE` object type. Their role is determined by collection:

- `/LAB205_MATERIALS/MOLECULES/PRECURSOR_COLLECTION`
- `/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION`

This does not change `ATOMISTIC_MODEL` objects or their relationships. A
simulation can link a molecular concept from either collection as a parent in
the same way as before.

**Find molecule** filters the local list by EMPA number, permID, recorded name
or ChemDraw name, ignoring case. Use **Find by SMILES or CDXML** to identify
a molecule by structure (benzene: `c1ccccc1`). An empty name filter result
offers **Update from openBIS**. The current selection stays linked until you
choose another record.

A finite molecule stores canonical `SMILES`. A one-dimensional periodic
molecular concept stores `CXSMILES` and leaves `SMILES` empty. The periodic
value uses one head-to-tail SRU group and preserves every independent crossing
bond. CDXML remains the human-editable sketch and is stored as an attachment.

The app validates generated periodic CXSMILES before it may be written:

1. Parse the bracketed CDXML repeat unit as a periodic quotient graph.
2. Generate a capped CXSMILES SRU representation.
3. Decode that CXSMILES with the app's strict SRU decoder.
4. Compare canonical three-cell and five-cell graph covers.
5. Regenerate the value and require a stable second encoding.

Automatic conversion requires exactly one bracketed repeat unit. A CDXML file
with several bracketed units can contribute several read-only search
representations, but it is not converted automatically into one CXSMILES
property.

The parser shares atom types, H/charge/isotope/radical validation and repeat
identification with the EMPA CDXML importer. Bracket placement is graphical;
membership and period follow annotated atoms and all crossing bonds. An
ambiguous source is diagnosed rather than silently dropping H. Single N/O-metal
lines are interpreted as coordination with a warning, retaining the source.
Multiple drawings use the same nearby-caption selector as the importer; the
query preview and search use the selected drawing. Read-only indexing retains
separate representations for different drawings.

Periodic identity uses two canonical chemical graph encodings (three and five
cyclic repeats). These are opaque keys, not molecules to render or parse as
search SMILES. This avoids repeating RDKit's kekulization search on artificial
closed covers of fused 5/7-membered systems. Fingerprints instead use an open
capped three-repeat fragment. If that larger fragment cannot be re-kekulized,
one capped repeat is used with a warning; exact identity still checks both graph
covers. Normalized-parent equivalence uses a capped repeat and is diagnosed
when unavailable. The chemical index format is version 3; older caches are
rebuilt from openBIS. Stored CDXML/CXSMILES and concept relationships are unchanged.

After an AiiDA workflow has been checked in the simulation export form, each
new precursor or product molecule selector receives a **Generate CDXML from
AiiDA structure** option. The current generator accepts planar C/H structures
with exactly one bonded periodic direction. It infers a conservative graph,
uses explicit hydrogen counts to solve single/double bond orders, and exposes
long-bond candidates, bond addition/removal, and carbon radicals for review.
Export remains disabled until carbon valence has a valid solution.

The generated CDXML and PNG initially stay in notebook memory. They are
available as downloads, and the CDXML is passed directly to the
collection-scoped search without emulating a browser upload or writing runtime
files below the app. The search panel labels this generated file as the active
query even though the browser upload control correctly still shows zero files.
Its periodic graph is validated through the same CDXML-to-CXSMILES round trip
used for stored molecular concepts.

The molecule selector searches only its configured collection. At connection,
a background worker prepares or refreshes the private, per-user and per-server
index. It stores name and code metadata, canonical structures and fingerprints.
SMILES and CXSMILES are used first. CDXML attachments supply structures when
neither field can be indexed. A molecule that cannot be processed within the
per-structure time limit remains available by name or code. SQLite is used
when available, with atomic JSON snapshots as a fallback.

**Search** canonicalizes the query and compares it with the local index.
Finite and periodic structures are compared separately. Exact identity,
standardized equivalence, substructure and fingerprint similarity remain
separate result types. **Min quality** applies the Tanimoto threshold to all
displayed matches. It defaults to 50 (Tanimoto 0.875) on a scale from Tanimoto
0.75 to 1.00. Selecting a result shows its formula and a link to its openBIS
record. The pre-creation identity check also considers equivalent structures
below the display threshold.

The search shows the index timestamp and how many molecules are searchable
by structure. **Update from openBIS** refreshes the index and repeats the query.
Connection-time refreshes read changes since the previous timestamp with an
overlap, and periodically reconcile deletions. The index contains no login
credentials. OpenBIS remains authoritative, including the fresh check before
creating a molecule.

After searching a generated CDXML, an exact or standardized-equivalent match
blocks creation and the existing result must be selected. If no identity match
exists, the selector offers creation in its configured precursor or product
collection. Non-identity matches must be reviewed explicitly. Clicking
**Create MOLECULE** refreshes the live collection and repeats the identity check
before any write. It then validates the current `MOLECULE` property assignments,
creates one object with `SMILES` or `CXSMILES` as appropriate, and attaches the
exact reviewed CDXML as `ATTACHMENT` and PNG as `ELN_PREVIEW`. Upload files are
written only to an operating-system temporary directory and removed
immediately. Stored PNG dimensions are preserved; the selector constrains only
the longest displayed side to 300 pixels and scales the other side
proportionally. The new object is re-indexed, verified as an exact match, added
to the selector, and selected for the simulation.

Object creation and dataset upload are separate openBIS operations. If an
attachment fails after the object has been saved, the interface reports the
new permanent ID and instructs the user to repair that object rather than retry
and create a duplicate.

`schema/add_molecule_cxsmiles.py` audits the optional `CXSMILES` property and
assignment without changing any existing `MOLECULE` metadata. The command is a
dry run unless `--apply` is given; production must run and verify this additive
migration before periodic creation is enabled there.

Before automatic CXSMILES writes are enabled in production, a generated
multi-crossing example must also complete an independent ChemAxon/ChemDraw
round trip. RDKit 2025.09 writes standards-numbered SRU bond references for the
example but does not reliably read them back for ring-rich ladder polymers;
the app therefore uses its own narrow decoder for validation.

## Shared chemical-sketch previews

Uploaded and generated CDXML queries show a PNG before searching. The generator's
review preview and exported PNG use the same `aiidalab_widgets_empa.cdxml_rendering`
renderer as the Surface CDXML editor. The exported PNG is rendered from the exact
CDXML bytes attached to the molecular concept. Pending bond suggestions appear
orange and dashed in the review image and are omitted from the exported files.

The renderer preserves drawing coordinates and aspect ratio, respects explicit
`DoublePosition` choices, and places unspecified ring double bonds inward. Shared
image sizing caps the longest displayed side at 300 pixels without changing the
PNG bytes or enlarging small images. Existing stored openBIS previews are displayed
from their stored bytes.

The qualification dependency selects canonical EMPA widgets `8a97ed1a`, which
contains the shared renderer API and the subsequently merged fixes. Final app
publication must consume its corresponding official release. This source pin
is a recorded qualification candidate, not a permanent release requirement.
