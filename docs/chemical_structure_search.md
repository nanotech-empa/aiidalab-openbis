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

The generated CDXML and PNG stay in notebook memory. They are available as
downloads, and the CDXML is passed directly to the collection-scoped search
without emulating a browser upload or writing runtime files below the app. Its
periodic graph is validated through the same CDXML-to-CXSMILES round trip used
for stored molecular concepts.

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

Before automatic CXSMILES writes are enabled in production, a generated
multi-crossing example must also complete an independent ChemAxon/ChemDraw
round trip. RDKit 2025.09 writes standards-numbered SRU bond references for the
example but does not reliably read them back for ring-rich ladder polymers;
the app therefore uses its own narrow decoder for validation.
