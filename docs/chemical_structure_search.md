# Molecular concepts and structural search

Both finite precursor molecules and periodic reaction products use the openBIS
`MOLECULE` object type. Their role is determined by collection:

- `/LAB205_MATERIALS/MOLECULES/PRECURSOR_COLLECTION`
- `/LAB205_MATERIALS/MOLECULES/PRODUCT_COLLECTION`

This does not change `ATOMISTIC_MODEL` objects or their relationships. A
simulation can link a molecular concept from either collection as a parent in
the same way as before.

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

The molecule selector searches only its configured collection. Queries may be
SMILES or CDXML. Existing records are indexed from `SMILES`, `CXSMILES`, and all
CDXML files in attachment or raw-data datasets. Finite and periodic structures
are compared separately. Results are ranked as exact graph identity,
standardized equivalence, substructure containment for finite molecules, then
Morgan-fingerprint similarity.

The displayed match-quality scale maps 0 to Tanimoto 0.75 and 100 to Tanimoto
1.00. A result must be selected explicitly before it becomes the linked
molecule. Index construction is read-only, suppresses RDKit diagnostic output,
and stores a collection-specific local cache. The **Update index** button is
used when openBIS records change.

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
