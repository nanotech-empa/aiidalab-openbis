"""Read-only structural search for openBIS MOLECULE objects."""

from __future__ import annotations

import hashlib
import html
import json
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import ipywidgets as ipw
from rdkit import Chem, DataStructs, rdBase
from rdkit.Chem import rdMolDescriptors
from rdkit.Chem.MolStandardize import rdMolStandardize
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

from src.chemical_structures import (
    periodic_formula,
    periodic_graph_from_cxsmiles,
    periodic_graph_key,
    periodic_graphs_from_cdxml,
    representation_from_cdxml,
)

MOLECULE_TYPE = "MOLECULE"
DATASET_TYPES = {"ATTACHMENT", "RAW_DATA"}
CACHE_VERSION = 2
_MORGAN = GetMorganGenerator(radius=2, fpSize=2048)


@dataclass(frozen=True)
class SearchRepresentation:
    """Normalized molecular graph used for identity and similarity search."""

    source: str
    source_id: str
    strict_key: str
    parent_key: str
    search_smiles: str
    formula: str
    periodic: bool = False
    periodic_key: str = ""
    warning: str = ""


@dataclass
class MoleculeRecord:
    """Searchable metadata and graphs for one MOLECULE object."""

    permid: str
    identifier: str
    collection: str
    name: str
    empa_number: str
    formula: str
    smiles: str
    cxsmiles: str
    modification_date: str
    representations: list[SearchRepresentation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchHit:
    """Best structural match found for one MOLECULE object."""

    record: MoleculeRecord
    match_type: str
    similarity: float
    query_coverage: float
    target_coverage: float
    matched_source: str
    matched_smiles: str
    periodic: bool


def match_quality_to_tanimoto(quality: int | float) -> float:
    """Map the displayed 0–100 useful range onto Tanimoto 0.75–1.00."""
    clipped = min(100.0, max(0.0, float(quality)))
    return 0.75 + 0.25 * clipped / 100.0


def tanimoto_to_match_quality(similarity: float) -> int:
    """Map Tanimoto onto the clipped displayed useful range."""
    quality = 100.0 * (float(similarity) - 0.75) / 0.25
    return int(round(min(100.0, max(0.0, quality))))


def _strict_smiles(molecule: Chem.Mol) -> str:
    molecule = Chem.Mol(molecule)
    Chem.SanitizeMol(molecule)
    molecule = Chem.RemoveHs(molecule)
    Chem.AssignStereochemistry(molecule, cleanIt=True, force=True)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)


def _parent_smiles(molecule: Chem.Mol) -> str:
    molecule = rdMolStandardize.Cleanup(Chem.Mol(molecule))
    molecule = rdMolStandardize.FragmentParent(molecule)
    molecule = rdMolStandardize.Uncharger().uncharge(molecule)
    molecule = rdMolStandardize.TautomerEnumerator().Canonicalize(molecule)
    molecule = Chem.RemoveHs(molecule)
    return Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=False)


def _periodic_parent_key(periodic_key: str) -> str:
    covers = periodic_key.split("|")
    if len(covers) != 2:
        raise ValueError("Periodic graph key does not contain its 3- and 5-cell covers")
    parents = []
    for cover in covers:
        molecule = Chem.MolFromSmiles(cover)
        if molecule is None:
            raise ValueError("Periodic graph key contains an invalid cover SMILES")
        parents.append(_parent_smiles(molecule))
    return "periodic:" + "|".join(parents)


def search_representation_from_mol(
    molecule: Chem.Mol,
    source: str,
    source_id: str,
    warning: str = "",
) -> SearchRepresentation:
    """Normalize an RDKit molecule for exact, equivalent, and fuzzy search."""
    strict = _strict_smiles(molecule)
    canonical = Chem.MolFromSmiles(strict)
    if canonical is None:
        raise ValueError("RDKit could not recreate the canonical molecule")
    return SearchRepresentation(
        source=source,
        source_id=source_id,
        strict_key=strict,
        parent_key=_parent_smiles(canonical),
        search_smiles=strict,
        formula=rdMolDescriptors.CalcMolFormula(canonical),
        warning=warning,
    )


def search_representation_from_smiles(
    smiles: str,
    source: str = "SMILES",
    source_id: str = "property:SMILES",
) -> SearchRepresentation:
    """Parse a finite SMILES query or property."""
    molecule = Chem.MolFromSmiles(str(smiles))
    if molecule is None:
        raise ValueError("Invalid SMILES")
    return search_representation_from_mol(molecule, source, source_id)


def _periodic_search_representation(
    periodic_key: str,
    formula: str,
    source: str,
    source_id: str,
    warning: str = "",
) -> SearchRepresentation:
    search_smiles = periodic_key.split("|", maxsplit=1)[0]
    if not search_smiles or Chem.MolFromSmiles(search_smiles) is None:
        raise ValueError("The periodic graph has no valid search cover")
    return SearchRepresentation(
        source=source,
        source_id=source_id,
        strict_key=f"periodic:{periodic_key}",
        parent_key=_periodic_parent_key(periodic_key),
        search_smiles=search_smiles,
        formula=formula,
        periodic=True,
        periodic_key=periodic_key,
        warning=warning,
    )


def search_representation_from_cxsmiles(
    cxsmiles: str,
    formula: str = "",
    source_id: str = "property:CXSMILES",
) -> SearchRepresentation:
    """Decode the application's validated periodic CXSMILES convention."""
    graph = periodic_graph_from_cxsmiles(cxsmiles)
    key = periodic_graph_key(graph)
    return _periodic_search_representation(
        key,
        formula,
        source="CXSMILES",
        source_id=source_id,
    )


def search_representations_from_cdxml(
    content: bytes | str,
    source_id: str = "query.cdxml",
) -> tuple[SearchRepresentation, ...]:
    """Parse every finite or periodic representation in a CDXML file."""
    periodic_graphs = periodic_graphs_from_cdxml(content)
    if periodic_graphs:
        count = len(periodic_graphs)
        return tuple(
            _periodic_search_representation(
                periodic_graph_key(graph),
                periodic_formula(graph),
                source="periodic CDXML",
                source_id=(
                    source_id
                    if count == 1
                    else f"{source_id}#repeat-{index + 1}"
                ),
            )
            for index, graph in enumerate(periodic_graphs)
        )

    representation = representation_from_cdxml(content)
    molecule = Chem.MolFromSmiles(representation.smiles)
    if molecule is None:
        raise ValueError("CDXML produced an invalid canonical SMILES")
    return (
        search_representation_from_mol(
            molecule,
            source="CDXML",
            source_id=source_id,
            warning=representation.warning,
        ),
    )


def search_representation_from_cdxml(
    content: bytes | str,
    source_id: str = "query.cdxml",
) -> SearchRepresentation:
    """Parse an unambiguous finite or single-repeat CDXML query."""
    representations = search_representations_from_cdxml(content, source_id)
    if len(representations) != 1:
        raise ValueError(
            "The CDXML query contains multiple bracketed repeat units; "
            "search them separately"
        )
    return representations[0]


def _properties(openbis_object) -> dict:
    return {
        str(key).lower(): value
        for key, value in openbis_object.props.all().items()
    }


def _type_code(value) -> str:
    return str(getattr(value, "code", value))


def _reference(value) -> str:
    return str(
        getattr(value, "permId", None)
        or getattr(value, "identifier", None)
        or value
        or ""
    )


def _session_identity(session) -> str:
    for attribute in ("url", "api_url", "host", "hostname", "_url"):
        value = getattr(session, attribute, "")
        if value:
            return str(value).rstrip("/")
    return "openbis"


def default_cache_path(session, collection: str) -> Path:
    """Return a stable, collection-specific local cache path."""
    identity = f"{_session_identity(session)}|{collection}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return Path.home() / ".cache" / "aiidalab-openbis" / f"molecules-{digest}.json"


def _dataset_cdxml_files(dataset) -> tuple[str, ...]:
    return tuple(
        str(filename)
        for filename in tuple(dataset.file_list)
        if Path(str(filename)).suffix.lower() == ".cdxml"
    )


def download_dataset_file(dataset, filename: str) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        dataset.download(files=[filename], destination=directory)
        expected = Path(filename).name
        candidates = [
            path
            for path in Path(directory).rglob("*")
            if path.is_file() and path.name == expected
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"Expected one downloaded {filename!r} in dataset "
                f"{_reference(dataset)}, found {len(candidates)}"
            )
        return candidates[0].read_bytes()


class OpenbisChemicalIndex:
    """Build and query a read-only, collection-scoped molecular index."""

    def __init__(self, session, collection: str, cache_path: str | Path | None = None):
        self.session = session
        self.collection = str(collection)
        self.session_identity = _session_identity(session)
        self.cache_path = Path(
            cache_path or default_cache_path(session, self.collection)
        ).expanduser()
        self.records: list[MoleculeRecord] = []
        self.generated_at = ""
        self.summary: dict = {}
        self.manifest: dict = {}
        self._mol_cache: dict[str, Chem.Mol] = {}
        self._fp_cache = {}

    def load(self):
        """Load a cache only when it belongs to this server and collection."""
        payload = json.loads(self.cache_path.read_text())
        if payload.get("version") != CACHE_VERSION:
            raise ValueError("The cached chemical index has an incompatible version")
        if payload.get("session") != self.session_identity:
            raise ValueError("The cached chemical index belongs to another openBIS server")
        if payload.get("collection") != self.collection:
            raise ValueError("The cached chemical index belongs to another collection")
        self.generated_at = str(payload.get("generated_at", ""))
        self.summary = dict(payload.get("summary", {}))
        self.manifest = dict(payload.get("manifest", {}))
        self.records = []
        for raw in payload.get("records", []):
            values = dict(raw)
            representations = [
                SearchRepresentation(**item)
                for item in values.pop("representations", [])
            ]
            self.records.append(
                MoleculeRecord(**values, representations=representations)
            )
        self._mol_cache.clear()
        self._fp_cache.clear()
        return self

    def save(self):
        """Persist the read-only index for later notebook sessions."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CACHE_VERSION,
            "session": self.session_identity,
            "collection": self.collection,
            "generated_at": self.generated_at,
            "summary": self.summary,
            "manifest": self.manifest,
            "records": [asdict(record) for record in self.records],
        }
        self.cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    @staticmethod
    def _summarize_records(records) -> dict:
        sources = Counter(
            representation.source
            for record in records
            for representation in record.representations
        )
        parsed_cdxml = {
            representation.source_id.split("#repeat-", maxsplit=1)[0]
            for record in records
            for representation in record.representations
            if "CDXML" in representation.source.upper()
        }
        return {
            "molecules": len(records),
            "with_smiles": sum(bool(record.smiles) for record in records),
            "with_cxsmiles": sum(bool(record.cxsmiles) for record in records),
            "with_any_representation": sum(
                bool(record.representations) for record in records
            ),
            "representations": dict(sorted(sources.items())),
            "cdxml_parsed": len(parsed_cdxml),
            "cdxml_failures": sum(
                error.startswith("CDXML ")
                for record in records
                for error in record.errors
            ),
            "objects_with_errors": sum(bool(record.errors) for record in records),
        }

    @staticmethod
    def _build_manifest(objects, datasets) -> dict:
        object_rows = []
        for openbis_object in objects:
            props = _properties(openbis_object)
            object_rows.append(
                {
                    "permid": str(openbis_object.permId),
                    "identifier": str(getattr(openbis_object, "identifier", "")),
                    "modification_date": str(
                        getattr(openbis_object, "modificationDate", "")
                    ),
                    "name": str(props.get("name") or ""),
                    "chemdraw_name": str(props.get("chemdraw_name") or ""),
                    "empa_number": str(props.get("empa_number") or ""),
                    "formula": str(props.get("sum_formula") or ""),
                    "smiles": str(props.get("smiles") or ""),
                    "cxsmiles": str(props.get("cxsmiles") or ""),
                }
            )
        dataset_rows = [
            {
                "permid": _reference(dataset),
                "sample": _reference(getattr(dataset, "sample", "")),
                "type": _type_code(dataset.type),
                "modification_date": str(
                    getattr(dataset, "modificationDate", "")
                ),
                "files": sorted(_dataset_cdxml_files(dataset)),
            }
            for dataset in datasets
        ]
        return {
            "objects": sorted(object_rows, key=lambda item: item["permid"]),
            "datasets": sorted(dataset_rows, key=lambda item: item["permid"]),
        }

    def _live_snapshot(self):
        objects = list(
            self.session.get_objects(
                type=MOLECULE_TYPE,
                collection=self.collection,
            )
            or []
        )
        permids = [str(openbis_object.permId) for openbis_object in objects]
        datasets = (
            list(self.session.get_datasets(sample=permids) or []) if permids else []
        )
        datasets = [
            dataset
            for dataset in datasets
            if _type_code(dataset.type) in DATASET_TYPES
            and _dataset_cdxml_files(dataset)
        ]
        return objects, datasets

    def synchronize(self, progress=None) -> str:
        """Compare a cheap live manifest and rebuild only when it changed."""
        progress = progress or (lambda _message: None)
        progress("Checking the openBIS molecule manifest …")
        objects, datasets = self._live_snapshot()
        remote_manifest = self._build_manifest(objects, datasets)
        if remote_manifest == self.manifest:
            return "current"

        previous_objects = {
            item["permid"]: item for item in self.manifest.get("objects", [])
        }
        remote_objects = {
            item["permid"]: item for item in remote_manifest["objects"]
        }
        remote_references = set(remote_objects) | {
            item["identifier"]
            for item in remote_objects.values()
            if item.get("identifier")
        }
        previous_datasets = [
            item
            for item in self.manifest.get("datasets", [])
            if item.get("sample") in remote_references
        ]
        only_deleted_objects = (
            bool(set(previous_objects) - set(remote_objects))
            and set(remote_objects).issubset(previous_objects)
            and all(
                item == previous_objects[permid]
                for permid, item in remote_objects.items()
            )
            and remote_manifest["datasets"] == previous_datasets
        )
        if only_deleted_objects:
            active_permids = set(remote_objects)
            removed = len(self.records)
            self.records = [
                record for record in self.records if record.permid in active_permids
            ]
            removed -= len(self.records)
            self.manifest = remote_manifest
            self.summary = self._summarize_records(self.records)
            self.generated_at = datetime.now(timezone.utc).isoformat()
            self._mol_cache.clear()
            self._fp_cache.clear()
            self.save()
            progress(f"Removed {removed} inactive cached molecule(s).")
            return f"pruned:{removed}"

        progress("openBIS changed; rebuilding the structural index …")
        self.refresh(
            progress=progress,
            _objects=objects,
            _datasets=datasets,
        )
        return "rebuilt"

    def refresh(
        self,
        include_cdxml: bool = True,
        progress=None,
        max_workers: int = 8,
        _objects=None,
        _datasets=None,
    ):
        """Rebuild the index from openBIS without modifying openBIS."""
        blocker = rdBase.BlockLogs()
        try:
            return self._refresh_impl(
                include_cdxml,
                progress,
                max_workers,
                objects=_objects,
                datasets=_datasets,
            )
        finally:
            del blocker

    def _refresh_impl(
        self,
        include_cdxml: bool,
        progress,
        max_workers: int,
        objects=None,
        datasets=None,
    ):
        progress = progress or (lambda _message: None)
        progress("Reading MOLECULE objects from openBIS …")
        if objects is None:
            objects = list(
                self.session.get_objects(
                    type=MOLECULE_TYPE,
                    collection=self.collection,
                )
                or []
            )
        else:
            objects = list(objects)
        records_by_reference: dict[str, MoleculeRecord] = {}
        for openbis_object in objects:
            props = _properties(openbis_object)
            record = MoleculeRecord(
                permid=str(openbis_object.permId),
                identifier=str(getattr(openbis_object, "identifier", "")),
                collection=self.collection,
                name=str(props.get("name") or props.get("chemdraw_name") or ""),
                empa_number=str(props.get("empa_number") or ""),
                formula=str(props.get("sum_formula") or ""),
                smiles=str(props.get("smiles") or ""),
                cxsmiles=str(props.get("cxsmiles") or ""),
                modification_date=str(
                    getattr(openbis_object, "modificationDate", "")
                ),
            )
            if record.smiles:
                try:
                    record.representations.append(
                        search_representation_from_smiles(record.smiles)
                    )
                except Exception as exc:
                    record.errors.append(f"SMILES: {type(exc).__name__}: {exc}")
            if record.cxsmiles:
                try:
                    record.representations.append(
                        search_representation_from_cxsmiles(
                            record.cxsmiles,
                            formula=record.formula,
                        )
                    )
                except Exception as exc:
                    record.errors.append(f"CXSMILES: {type(exc).__name__}: {exc}")
            records_by_reference[record.permid] = record
            if record.identifier:
                records_by_reference[record.identifier] = record

        unique_records = {
            record.permid: record for record in records_by_reference.values()
        }
        relevant_datasets = []
        if include_cdxml and unique_records:
            permids = list(unique_records)
            progress(
                f"Inspecting attachments for all {len(permids)} molecules …"
            )
            if datasets is None:
                datasets = list(self.session.get_datasets(sample=permids) or [])
            relevant_datasets = [
                dataset
                for dataset in datasets
                if _type_code(dataset.type) in DATASET_TYPES
                and _dataset_cdxml_files(dataset)
            ]
            sources = [
                (dataset, filename)
                for dataset in relevant_datasets
                for filename in _dataset_cdxml_files(dataset)
            ]
            progress(f"Parsing {len(sources)} CDXML attachments …")

            def download_and_parse(source):
                dataset, filename = source
                content = download_dataset_file(dataset, filename)
                representations = search_representations_from_cdxml(
                    content,
                    source_id=f"{_reference(dataset)}::{filename}",
                )
                return dataset, filename, representations

            with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
                futures = {
                    pool.submit(download_and_parse, source): source
                    for source in sources
                }
                for completed, future in enumerate(as_completed(futures), start=1):
                    dataset, filename = futures[future]
                    sample_ref = _reference(getattr(dataset, "sample", ""))
                    record = records_by_reference.get(sample_ref)
                    try:
                        _, _, representations = future.result()
                        if record is None:
                            raise RuntimeError(
                                f"Dataset sample {sample_ref!r} is not a MOLECULE "
                                "in the selected collection"
                            )
                        record.representations.extend(representations)
                    except Exception as exc:
                        if record is not None:
                            record.errors.append(
                                f"CDXML {filename}: {type(exc).__name__}: {exc}"
                            )
                    if completed % 50 == 0:
                        progress(
                            f"Parsed {completed}/{len(sources)} CDXML attachments …"
                        )

        self.records = sorted(unique_records.values(), key=lambda item: item.permid)
        self.manifest = self._build_manifest(objects, relevant_datasets)
        self.generated_at = datetime.now(timezone.utc).isoformat()
        self.summary = self._summarize_records(self.records)
        self.save()
        self._mol_cache.clear()
        self._fp_cache.clear()
        progress(f"Indexed {len(self.records)} molecules.")
        return self

    def _mol(self, smiles: str) -> Chem.Mol:
        if smiles not in self._mol_cache:
            molecule = Chem.MolFromSmiles(smiles)
            if molecule is None:
                raise ValueError("Cached canonical SMILES is invalid")
            self._mol_cache[smiles] = molecule
        return self._mol_cache[smiles]

    def _fingerprint(self, smiles: str):
        if smiles not in self._fp_cache:
            self._fp_cache[smiles] = _MORGAN.GetFingerprint(self._mol(smiles))
        return self._fp_cache[smiles]

    def search(
        self,
        query: SearchRepresentation,
        min_similarity: float = 0.75,
        limit: int = 20,
    ) -> list[SearchHit]:
        """Search within this index, keeping finite and periodic classes separate."""
        # Queries are one-use inputs, not part of the collection's working set.
        query_mol = Chem.MolFromSmiles(query.search_smiles)
        if query_mol is None:
            raise ValueError("Query SMILES is invalid")
        query_fp = _MORGAN.GetFingerprint(query_mol)
        query_heavy = max(1, query_mol.GetNumHeavyAtoms())
        hits = []

        for record in self.records:
            best = None
            for representation in record.representations:
                if query.periodic != representation.periodic:
                    continue
                try:
                    target_mol = self._mol(representation.search_smiles)
                    similarity = float(
                        DataStructs.TanimotoSimilarity(
                            query_fp,
                            self._fingerprint(representation.search_smiles),
                        )
                    )
                except Exception:
                    continue

                match_type = "similar"
                rank = 4
                query_coverage = 0.0
                target_coverage = 0.0
                if query.strict_key == representation.strict_key:
                    match_type, rank, similarity = "exact", 0, 1.0
                    query_coverage = target_coverage = 1.0
                elif query.parent_key == representation.parent_key:
                    match_type, rank, similarity = "equivalent", 1, 1.0
                    query_coverage = target_coverage = 1.0
                elif not query.periodic:
                    target_heavy = max(1, target_mol.GetNumHeavyAtoms())
                    if target_mol.HasSubstructMatch(query_mol):
                        match_type, rank = "query contained in target", 2
                        query_coverage = 1.0
                        target_coverage = min(1.0, query_heavy / target_heavy)
                    elif query_mol.HasSubstructMatch(target_mol):
                        match_type, rank = "target contained in query", 3
                        target_coverage = 1.0
                        query_coverage = min(1.0, target_heavy / query_heavy)

                if rank == 4 and similarity < min_similarity:
                    continue
                candidate = (
                    rank,
                    -similarity,
                    -query_coverage,
                    SearchHit(
                        record=record,
                        match_type=match_type,
                        similarity=similarity,
                        query_coverage=query_coverage,
                        target_coverage=target_coverage,
                        matched_source=representation.source,
                        matched_smiles=representation.search_smiles,
                        periodic=representation.periodic,
                    ),
                )
                if best is None or candidate[:3] < best[:3]:
                    best = candidate
            if best is not None:
                hits.append(best)

        hits.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3].record.name.casefold(),
            )
        )
        return [item[3] for item in hits[: int(limit)]]


def _upload_content(upload_widget) -> tuple[str | None, bytes | None]:
    value = upload_widget.value
    if not value:
        return None, None
    if isinstance(value, dict):
        name, payload = next(iter(value.items()))
        return str(name), bytes(payload["content"])
    payload = value[0]
    return str(payload.get("name", "query.cdxml")), bytes(payload["content"])


class MoleculeStructureSearchWidget(ipw.VBox):
    """Embedded SMILES/CDXML lookup for one MOLECULE collection."""

    def __init__(
        self,
        session,
        collection: str,
        on_select=None,
        cache_path: str | Path | None = None,
        on_search_complete=None,
        on_query_change=None,
    ):
        self.index = OpenbisChemicalIndex(session, collection, cache_path)
        self.on_select = on_select
        self.on_search_complete = on_search_complete
        self.on_query_change = on_query_change
        self.input_kind = ipw.ToggleButtons(
            options=[("SMILES", "smiles"), ("CDXML", "cdxml")],
            value="smiles",
            description="Input",
        )
        self.smiles = ipw.Textarea(
            placeholder="Paste a SMILES string",
            layout=ipw.Layout(width="100%", height="55px"),
        )
        self.cdxml = ipw.FileUpload(
            accept=".cdxml",
            multiple=False,
            description="Upload CDXML",
        )
        self.cdxml.layout.display = "none"
        self.active_source = ipw.HTML()
        self.quality = ipw.IntSlider(
            value=0,
            min=0,
            max=100,
            step=1,
            description="Min quality",
            continuous_update=False,
            style={"description_width": "90px"},
            layout=ipw.Layout(width="390px"),
        )
        self.limit = ipw.IntSlider(
            value=10,
            min=5,
            max=30,
            step=5,
            description="Max results",
            continuous_update=False,
            style={"description_width": "90px"},
            layout=ipw.Layout(width="320px"),
        )
        self.update_button = ipw.Button(
            description="Update index",
            tooltip="Read SMILES, CXSMILES, and CDXML attachments from this collection",
        )
        self.search_button = ipw.Button(
            description="Search",
            button_style="primary",
        )
        self.status = ipw.HTML()
        self.results = ipw.Select(
            options=[("Select a match...", "")],
            rows=6,
            description="Matches",
            style={"description_width": "70px"},
            layout=ipw.Layout(width="100%"),
        )
        self.details = ipw.HTML()
        self._hits_by_permid: dict[str, SearchHit] = {}
        self._generated_cdxml: tuple[str, bytes] | None = None
        self.last_query: SearchRepresentation | None = None
        self.last_hits: tuple[SearchHit, ...] = ()

        self.input_kind.observe(self._switch_input, names="value")
        self.smiles.observe(self._smiles_changed, names="value")
        self.cdxml.observe(self._uploaded_cdxml_changed, names="value")
        self.update_button.on_click(self._update)
        self.search_button.on_click(self._search)
        self.results.observe(self._select, names="value")

        super().__init__(
            [
                ipw.HTML(
                    "Find an existing record by SMILES or CDXML. The quality scale "
                    "starts at Tanimoto 75%."
                ),
                self.input_kind,
                self.smiles,
                self.cdxml,
                self.active_source,
                ipw.HBox([self.quality, self.limit]),
                ipw.HBox([self.update_button, self.search_button]),
                self.status,
                self.results,
                self.details,
            ]
        )
        if self.index.cache_path.is_file():
            try:
                self.index.load()
                self._set_status(
                    f"Loaded {len(self.index.records)} cached molecules.", "ok"
                )
            except Exception:
                self._set_status("The local index needs to be updated.")

    def _set_status(self, message: str, kind: str = "info"):
        colors = {"info": "#1f5a94", "ok": "#187b35", "error": "#b00020"}
        self.status.value = (
            f"<span style='color:{colors[kind]}'>{html.escape(str(message))}</span>"
        )

    def _switch_input(self, change):
        use_smiles = change["new"] == "smiles"
        self.smiles.layout.display = "" if use_smiles else "none"
        self.cdxml.layout.display = "none" if use_smiles else ""
        if use_smiles:
            self.active_source.value = ""
        elif self._generated_cdxml is not None:
            filename, _content = self._generated_cdxml
            self.active_source.value = (
                "<b>Active CDXML:</b> generated and reviewed in this form · "
                f"{html.escape(filename)}"
            )
        self._clear_search_state()

    def _smiles_changed(self, change):
        if change.get("new") != change.get("old"):
            self._clear_search_state()

    def _uploaded_cdxml_changed(self, change):
        if change.get("new"):
            self._generated_cdxml = None
            filename, _content = _upload_content(self.cdxml)
            self.active_source.value = (
                "<b>Active CDXML:</b> browser upload "
                f"{html.escape(filename or 'query.cdxml')}"
            )
            self._clear_search_state()

    def _clear_search_state(self):
        self.last_query = None
        self.last_hits = ()
        self._hits_by_permid = {}
        self.results.options = [("Select a match...", "")]
        self.details.value = ""
        if self.on_query_change is not None:
            self.on_query_change()

    def set_cdxml_query(self, content: bytes, filename="generated.cdxml"):
        """Load generated CDXML without emulating a browser file upload."""
        self._generated_cdxml = (str(filename), bytes(content))
        self.input_kind.value = "cdxml"
        self.active_source.value = (
            "<b>Active CDXML:</b> generated and reviewed in this form · "
            f"{html.escape(str(filename))}"
        )
        self._clear_search_state()
        self._set_status(
            f"Generated CDXML ready for search: {filename}.",
            "ok",
        )

    def _update(self, _=None):
        self.update_button.disabled = True
        self.search_button.disabled = True
        try:
            self.index.refresh(progress=self._set_status)
            self._set_status(
                f"Index ready: {len(self.index.records)} molecules.", "ok"
            )
        except Exception as exc:
            self._set_status(
                f"Index update failed: {type(exc).__name__}: {exc}", "error"
            )
        finally:
            self.update_button.disabled = False
            self.search_button.disabled = False

    def _query(self) -> SearchRepresentation:
        if self.input_kind.value == "smiles":
            value = self.smiles.value.strip()
            if not value:
                raise ValueError("Enter a SMILES query")
            return search_representation_from_smiles(
                value,
                source="SMILES query",
                source_id="query:SMILES",
            )
        if self._generated_cdxml is not None:
            filename, content = self._generated_cdxml
        else:
            filename, content = _upload_content(self.cdxml)
        if content is None:
            raise ValueError("Upload or generate a CDXML query")
        return search_representation_from_cdxml(content, filename or "query.cdxml")

    def _search(self, _=None):
        self.search_button.disabled = True
        self.results.options = [("Select a match...", "")]
        self.details.value = ""
        try:
            synchronization = ""
            if not self.index.records:
                try:
                    self.index.load()
                except Exception:
                    self.index.refresh(progress=self._set_status)
                    synchronization = "rebuilt"
            if not synchronization:
                synchronization = self.index.synchronize(progress=self._set_status)
            blocker = rdBase.BlockLogs()
            try:
                query = self._query()
                hits = self.index.search(
                    query,
                    min_similarity=match_quality_to_tanimoto(self.quality.value),
                    limit=self.limit.value,
                )
            finally:
                del blocker
            self.last_query = query
            self.last_hits = tuple(hits)
            self._hits_by_permid = {hit.record.permid: hit for hit in hits}
            self.results.options = [("Select a match...", "")] + [
                (
                    f"{hit.match_type} · Q{tanimoto_to_match_quality(hit.similarity)} "
                    f"(T={100 * hit.similarity:.1f}%) · "
                    f"{hit.record.empa_number or hit.record.name or hit.record.permid}",
                    hit.record.permid,
                )
                for hit in hits
            ]
            periodic = "periodic" if query.periodic else "finite"
            sync_message = {
                "current": " Local index already current.",
                "rebuilt": " Local index refreshed from openBIS.",
            }.get(synchronization, " Inactive cached records removed.")
            self._set_status(
                f"Found {len(hits)} {periodic} matches in this collection."
                f"{sync_message}",
                "ok" if hits else "info",
            )
            if self.on_search_complete is not None:
                self.on_search_complete(query, tuple(hits))
        except Exception as exc:
            self.last_query = None
            self.last_hits = ()
            self._set_status(
                f"Search failed: {type(exc).__name__}: {exc}", "error"
            )
        finally:
            self.search_button.disabled = False

    def _select(self, change):
        permid = change.get("new")
        hit = self._hits_by_permid.get(str(permid))
        if hit is None:
            self.details.value = ""
            return
        record = hit.record
        self.details.value = (
            f"<b>{html.escape(record.name or 'Unnamed molecule')}</b> · "
            f"{html.escape(record.formula or 'formula unavailable')} · "
            f"{html.escape(hit.matched_source)} · {html.escape(record.permid)}"
        )
        if self.on_select is not None:
            self.on_select(record.permid)
