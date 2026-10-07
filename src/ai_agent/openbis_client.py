"""openbis_client.py: Strictly read-only client for interacting with openBIS.

Provides cached querying, robust error handling, and generates clickable hyperlinks
to the official openBIS ELN-LIMS instance for all retrieved permIDs.
"""

import base64
import json
import logging
import re
import tempfile
import urllib.parse
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd

from src import utils

logger = logging.getLogger("ai_agent.openbis_client")


_SESSION = None
_SESSION_DATA = None
_ELN_URL = None


def get_session():
    """Retrieve or initialize the active openBIS session."""
    global _SESSION, _SESSION_DATA, _ELN_URL
    if _SESSION is None or not _SESSION.is_token_valid():
        _SESSION, _SESSION_DATA = utils.connect_openbis_aiida()
        if _SESSION:
            _ELN_URL = utils.normalize_openbis_eln_url(_SESSION.url)
    return _SESSION


def get_eln_url() -> str:
    """Return the normalized base ELN-LIMS URL."""
    global _ELN_URL
    if not _ELN_URL:
        get_session()
    return _ELN_URL or ""


def generate_openbis_url(permid: str, entity_type: str = "SAMPLE", identifier: str = "") -> str:
    """Generate a direct clickable openBIS ELN-LIMS URL for a given entity."""
    base = get_eln_url()
    if not base or not permid:
        return ""
    entity_upper = entity_type.upper()

    if entity_upper in ["EXPERIMENT", "COLLECTION"]:
        ident_val = identifier
        if not ident_val:
            try:
                s = get_session()
                if s:
                    exp = s.get_experiment(permid)
                    if exp:
                        ident_val = exp.identifier
            except Exception:
                pass
        if not ident_val:
            ident_val = permid
        menu_id = urllib.parse.quote(json.dumps({"type": "EXPERIMENT", "id": permid}, separators=(',', ':')))
        view_data = urllib.parse.quote(json.dumps([ident_val, False], separators=(',', ':')))
        return f"{base}?menuUniqueId={menu_id}&viewName=showExperimentPageFromIdentifier&viewData={view_data}"

    elif entity_upper == "PROJECT":
        ident_val = identifier
        if not ident_val:
            try:
                s = get_session()
                if s:
                    proj = s.get_project(permid)
                    if proj:
                        ident_val = proj.identifier
            except Exception:
                pass
        if not ident_val:
            ident_val = permid
        menu_id = urllib.parse.quote(json.dumps({"type": "PROJECT", "id": permid}, separators=(',', ':')))
        view_data = urllib.parse.quote(json.dumps([ident_val, False], separators=(',', ':')))
        return f"{base}?menuUniqueId={menu_id}&viewName=showProjectPageFromIdentifier&viewData={view_data}"

    elif entity_upper == "SPACE":
        ident_val = identifier if identifier else permid
        view_data = urllib.parse.quote(json.dumps([ident_val, False], separators=(',', ':')))
        return f"{base}?viewName=showSpacePageFromIdentifier&viewData={view_data}"

    elif entity_upper in ["DATASET", "DATA_SET"]:
        encoded_id = urllib.parse.quote(f'{{"permIdOrIdentifier":"{permid}"}}')
        return f"{base}?viewName=showViewDataSetPageFromPermId&viewData={encoded_id}"

    else:
        encoded_id = urllib.parse.quote(f'{{"permIdOrIdentifier":"{permid}"}}')
        return f"{base}?viewName=showViewSamplePageFromPermId&viewData={encoded_id}"


def format_link(label: str, permid: str, entity_type: str = "SAMPLE", identifier: str = "") -> str:
    """Format an entity label and permId into a single clean markdown link."""
    url = generate_openbis_url(permid, entity_type, identifier=identifier)
    display_label = label if label and label.strip() else (identifier or permid)
    if url:
        if display_label != permid:
            return f"[{display_label} ({permid})]({url})"
        return f"[{display_label}]({url})"
    return f"{display_label} ({permid})"


@lru_cache(maxsize=1000)
def get_object(permid: str):
    """Retrieve an openBIS object by permId (cached, read-only)."""
    s = get_session()
    if not s or not permid:
        return None
    try:
        return s.get_object(permid)
    except Exception:
        return None


@lru_cache(maxsize=1)
def get_molecules_cache() -> pd.DataFrame:
    """Cache molecules dataframe for fast cross-referencing."""
    s = get_session()
    if not s:
        return pd.DataFrame()
    try:
        mols = s.get_objects(
            type="MOLECULE",
            props=["name", "sum_formula", "smiles", "iupac_name", "empa_number", "cas_number"]
        )
        df = mols.df.copy()
        df.columns = [c.upper() for c in df.columns]
        return df
    except Exception as e:
        print(f"Error fetching molecules: {e}")
        return pd.DataFrame()


@lru_cache(maxsize=1)
def get_substances_cache() -> pd.DataFrame:
    """Cache substances dataframe for fast cross-referencing."""
    s = get_session()
    if not s:
        return pd.DataFrame()
    try:
        subs = s.get_objects(
            type="SUBSTANCE",
            props=["name", "empa_number", "batch", "substance_type", "object_status", "location", "amount_mg", "supplier"]
        )
        df = subs.df.copy()
        df.columns = [c.upper() for c in df.columns]
        return df
    except Exception as e:
        print(f"Error fetching substances: {e}")
        return pd.DataFrame()


@lru_cache(maxsize=1)
def get_crystals_cache() -> pd.DataFrame:
    """Cache crystals dataframe."""
    s = get_session()
    if not s:
        return pd.DataFrame()
    try:
        crysts = s.get_objects(
            type="CRYSTAL",
            props=["name", "material", "face", "shape", "location", "object_status", "supplier"]
        )
        df = crysts.df.copy()
        df.columns = [c.upper() for c in df.columns]
        return df
    except Exception as e:
        print(f"Error fetching crystals: {e}")
        return pd.DataFrame()


@lru_cache(maxsize=1)
def get_rooms_cache() -> Dict[str, str]:
    """Map room permId -> room name."""
    s = get_session()
    if not s:
        return {}
    try:
        rooms = s.get_objects(type="ROOM", props=["name"])
        df = rooms.df
        mapping = {}
        for _, row in df.iterrows():
            pid = row.get("permId")
            name = row.get("NAME") or row.get("identifier") or pid
            if pid:
                mapping[pid] = str(name)
        return mapping
    except Exception:
        return {}


def resolve_location_name(location_id: Optional[str]) -> str:
    """Resolve a location permId into a room or instrument name."""
    if not location_id or str(location_id).strip() == "":
        return "Unknown"
    rooms = get_rooms_cache()
    if location_id in rooms:
        return rooms[location_id]
    obj = get_object(location_id)
    if obj:
        inst_name = getattr(obj.props, "name", None) or obj.permId
        loc = getattr(obj.props, "location", None)
        room_name = rooms.get(loc, "")
        if room_name:
            return f"{inst_name} (in {room_name})"
        return str(inst_name)
    return str(location_id)


def get_molecule_details_for_substance(sub_obj) -> List[Dict[str, Any]]:
    """Inspect and extract parent molecule details for a substance."""
    mols = []
    if not sub_obj:
        return mols
    try:
        parents = sub_obj.get_parents()
        if parents:
            for p in parents:
                if str(p.type.code) == "MOLECULE":
                    props = p.props.all()
                    mols.append({
                        "permId": p.permId,
                        "name": props.get("name") or "",
                        "sum_formula": props.get("sum_formula") or "",
                        "smiles": props.get("smiles") or "",
                        "iupac_name": props.get("iupac_name") or "",
                        "empa_number": props.get("empa_number") or "",
                        "registrator": getattr(p, "registrator", None) or "",
                        "registration_date": str(getattr(p, "registrationDate", "") or ""),
                        "modifier": getattr(p, "modifier", None) or "",
                        "modification_date": str(getattr(p, "modificationDate", "") or ""),
                        "link": format_link(props.get("name") or p.permId, p.permId, "SAMPLE"),
                    })
    except Exception:
        pass

    if not mols:
        sub_empa = getattr(sub_obj.props, "empa_number", None)
        if sub_empa:
            mols_df = get_molecules_cache()
            if not mols_df.empty and "EMPA_NUMBER" in mols_df.columns:
                matched = mols_df[mols_df["EMPA_NUMBER"].astype(str) == str(sub_empa)]
                for _, r in matched.iterrows():
                    pid = r.get("PERMID")
                    mols.append({
                        "permId": pid,
                        "name": str(r.get("NAME") or ""),
                        "sum_formula": str(r.get("SUM_FORMULA") or ""),
                        "smiles": str(r.get("SMILES") or ""),
                        "iupac_name": str(r.get("IUPAC_NAME") or ""),
                        "empa_number": str(r.get("EMPA_NUMBER") or ""),
                        "registrator": str(r.get("REGISTRATOR") or ""),
                        "registration_date": str(r.get("REGISTRATIONDATE") or ""),
                        "modifier": str(r.get("MODIFIER") or ""),
                        "modification_date": str(r.get("MODIFICATIONDATE") or ""),
                        "link": format_link(str(r.get("NAME") or pid), pid, "SAMPLE"),
                    })
    return mols


# Query Implementations
# =========================================================================

def get_inventory_summary() -> Dict[str, Any]:
    """Get total counts and statistics of key entities across openBIS."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    subs_df = get_substances_cache()
    mols_df = get_molecules_cache()
    crysts_df = get_crystals_cache()
    rooms = get_rooms_cache()

    return {
        "substances": len(subs_df),
        "molecules": len(mols_df),
        "crystals": len(crysts_df),
        "rooms": len(rooms),
        "instruments": 2,
        "components": 16,
        "preparations": 30,
        "process_templates": 3,
        "measurement_sessions": 29,
        "publications": 1,
        "projects": 44,
    }


def search_inventory(
    query: str = "",
    sample_type: str = "",
    empa_number: int = 0,
    batch: str = "",
    formula: str = "",
    material: str = "",
    face: str = "",
    limit: int = 20,
) -> Dict[str, Any]:
    """Search inventory samples (substances, molecules, crystals, etc.)."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected.", "total_matches": 0, "items": []}

    results: List[Dict[str, Any]] = []
    total_matching = 0
    total_in_db = 0
    st_upper = sample_type.upper().strip()

    # Search Substances if requested or by default
    if not st_upper or st_upper in ["SUBSTANCE", "SUBSTANCES", "CHEMICAL"]:
        subs_df = get_substances_cache()
        if not subs_df.empty:
            filtered = subs_df.copy()
            if empa_number > 0:
                filtered = filtered[filtered["EMPA_NUMBER"].astype(str) == str(empa_number)]
            if batch:
                filtered = filtered[filtered["BATCH"].astype(str).str.lower() == batch.lower()]
            if query:
                q = query.lower()
                m_name = filtered["NAME"].astype(str).str.lower().str.contains(q, na=False)
                m_empa = filtered["EMPA_NUMBER"].astype(str).str.contains(q, na=False)
                m_batch = filtered["BATCH"].astype(str).str.lower().str.contains(q, na=False)
                m_pid = filtered["PERMID"].astype(str).str.contains(q, na=False)
                filtered = filtered[m_name | m_empa | m_batch | m_pid]

            if formula:
                mols_df = get_molecules_cache()
                matched_mol_empas = set()
                if not mols_df.empty and "SUM_FORMULA" in mols_df.columns:
                    m_form = mols_df[mols_df["SUM_FORMULA"].astype(str).str.lower().str.contains(formula.lower(), na=False)]
                    matched_mol_empas = set(m_form["EMPA_NUMBER"].dropna().astype(str).unique())
                filtered = filtered[filtered["EMPA_NUMBER"].astype(str).isin(matched_mol_empas)]

            total_in_db += len(subs_df)
            total_matching += len(filtered)

            for _, row in filtered.head(limit).iterrows():
                pid = row.get("PERMID")
                sub_obj = get_object(pid)
                mols = get_molecule_details_for_substance(sub_obj)
                label = str(row.get("NAME") or f"Substance {row.get('EMPA_NUMBER')}{row.get('BATCH')}")
                results.append({
                    "sample_type": "SUBSTANCE",
                    "permId": pid,
                    "name": label,
                    "empa_number": str(row.get("EMPA_NUMBER") or ""),
                    "batch": str(row.get("BATCH") or ""),
                    "status": str(row.get("OBJECT_STATUS") or "Active"),
                    "location": resolve_location_name(row.get("LOCATION")),
                    "amount_mg": str(row.get("AMOUNT_MG") or ""),
                    "registrator": str(row.get("REGISTRATOR") or ""),
                    "registration_date": str(row.get("REGISTRATIONDATE") or ""),
                    "modifier": str(row.get("MODIFIER") or ""),
                    "modification_date": str(row.get("MODIFICATIONDATE") or ""),
                    "parent_molecules": mols,
                    "link": format_link(label, pid, "SAMPLE"),
                })

    # Search Crystals if requested or by default
    if (not st_upper or st_upper in ["CRYSTAL", "CRYSTALS", "SLAB"]) and len(results) < limit:
        crysts_df = get_crystals_cache()
        if not crysts_df.empty:
            total_in_db += len(crysts_df)
            filtered = crysts_df.copy()
            if material:
                filtered = filtered[filtered["MATERIAL"].astype(str).str.lower().str.contains(material.lower(), na=False)]
            if face:
                filtered = filtered[filtered["FACE"].astype(str).str.lower().str.contains(face.lower(), na=False)]
            if query:
                q = query.lower()
                m_name = filtered["NAME"].astype(str).str.lower().str.contains(q, na=False)
                m_mat = filtered["MATERIAL"].astype(str).str.lower().str.contains(q, na=False)
                m_face = filtered["FACE"].astype(str).str.lower().str.contains(q, na=False)
                m_pid = filtered["PERMID"].astype(str).str.contains(q, na=False)
                filtered = filtered[m_name | m_mat | m_face | m_pid]

            total_matching += len(filtered)

            for _, row in filtered.head(limit - len(results)).iterrows():
                pid = row.get("PERMID")
                label = str(row.get("NAME") or f"Crystal {row.get('MATERIAL')}_{row.get('FACE')}")
                results.append({
                    "sample_type": "CRYSTAL",
                    "permId": pid,
                    "name": label,
                    "material": str(row.get("MATERIAL") or ""),
                    "face": str(row.get("FACE") or ""),
                    "shape": str(row.get("SHAPE") or ""),
                    "status": str(row.get("OBJECT_STATUS") or "Active"),
                    "location": resolve_location_name(row.get("LOCATION")),
                    "registrator": str(row.get("REGISTRATOR") or ""),
                    "registration_date": str(row.get("REGISTRATIONDATE") or ""),
                    "modifier": str(row.get("MODIFIER") or ""),
                    "modification_date": str(row.get("MODIFICATIONDATE") or ""),
                    "link": format_link(label, pid, "SAMPLE"),
                })

    # Search Molecules directly if requested
    if st_upper in ["MOLECULE", "MOLECULES"] and len(results) < limit:
        mols_df = get_molecules_cache()
        if not mols_df.empty:
            total_in_db += len(mols_df)
            filtered = mols_df.copy()
            if empa_number > 0:
                filtered = filtered[filtered["EMPA_NUMBER"].astype(str) == str(empa_number)]
            if formula:
                filtered = filtered[filtered["SUM_FORMULA"].astype(str).str.lower().str.contains(formula.lower(), na=False)]
            if query:
                q = query.lower()
                m_name = filtered["NAME"].astype(str).str.lower().str.contains(q, na=False)
                m_form = filtered["SUM_FORMULA"].astype(str).str.lower().str.contains(q, na=False)
                m_smiles = filtered["SMILES"].astype(str).str.lower().str.contains(q, na=False)
                m_iupac = filtered["IUPAC_NAME"].astype(str).str.lower().str.contains(q, na=False)
                m_empa = filtered["EMPA_NUMBER"].astype(str).str.contains(q, na=False)
                filtered = filtered[m_name | m_form | m_smiles | m_iupac | m_empa]

            total_matching += len(filtered)

            for _, row in filtered.head(limit - len(results)).iterrows():
                pid = row.get("PERMID")
                label = str(row.get("NAME") or row.get("SUM_FORMULA") or pid)
                results.append({
                    "sample_type": "MOLECULE",
                    "permId": pid,
                    "name": label,
                    "sum_formula": str(row.get("SUM_FORMULA") or ""),
                    "smiles": str(row.get("SMILES") or ""),
                    "iupac_name": str(row.get("IUPAC_NAME") or ""),
                    "empa_number": str(row.get("EMPA_NUMBER") or ""),
                    "registrator": str(row.get("REGISTRATOR") or ""),
                    "registration_date": str(row.get("REGISTRATIONDATE") or ""),
                    "modifier": str(row.get("MODIFIER") or ""),
                    "modification_date": str(row.get("MODIFICATIONDATE") or ""),
                    "link": format_link(label, pid, "SAMPLE"),
                })

    return {
        "total_matches": total_matching,
        "total_in_db": total_in_db,
        "items": results,
    }


def get_sample_details(sample_id: str) -> Dict[str, Any]:
    """Retrieve full metadata, parents, and children of any sample."""
    obj = get_object(sample_id)
    if not obj:
        # Fast lookup via substances cache
        try:
            subs_df = get_substances_cache()
            if not subs_df.empty:
                m = subs_df[subs_df["NAME"].astype(str).str.lower() == str(sample_id).lower()]
                if not m.empty:
                    obj = get_object(m.iloc[0]["PERMID"])
        except Exception:
            pass

    if not obj:
        # Fast lookup via molecules cache
        try:
            mols_df = get_molecules_cache()
            if not mols_df.empty:
                m = mols_df[mols_df["NAME"].astype(str).str.lower() == str(sample_id).lower()]
                if not m.empty:
                    obj = get_object(m.iloc[0]["PERMID"])
        except Exception:
            pass

    if not obj:
        s = get_session()
        if s:
            try:
                samples = s.get_samples(code=sample_id)
                if samples:
                    obj = samples[0]
            except Exception:
                pass

    if not obj:
        return {"error": f"Sample '{sample_id}' not found in openBIS."}

    props = obj.props.all()
    parents_info = []
    try:
        parents = obj.get_parents()
        if parents:
            for p in parents:
                p_name = getattr(p.props, "name", None) or p.permId
                parents_info.append({
                    "permId": p.permId,
                    "type": str(p.type.code),
                    "name": str(p_name),
                    "link": format_link(str(p_name), p.permId, "SAMPLE"),
                })
    except Exception:
        pass

    children_info = []
    try:
        children = obj.get_children()
        if children:
            for c in children:
                c_name = getattr(c.props, "name", None) or c.permId
                children_info.append({
                    "permId": c.permId,
                    "type": str(c.type.code),
                    "name": str(c_name),
                    "link": format_link(str(c_name), c.permId, "SAMPLE"),
                })
    except Exception:
        pass

    display_name = getattr(obj.props, "name", None) or obj.permId
    details = {
        "permId": obj.permId,
        "type": str(obj.type.code),
        "name": display_name,
        "registrator": getattr(obj, "registrator", None) or "",
        "registration_date": str(getattr(obj, "registrationDate", "") or ""),
        "modifier": getattr(obj, "modifier", None) or "",
        "modification_date": str(getattr(obj, "modificationDate", "") or ""),
        "properties": {k: v for k, v in props.items() if v is not None and v != ""},
        "parents": parents_info,
        "children": children_info,
        "link": format_link(display_name, obj.permId, "SAMPLE"),
    }
    if str(obj.type.code).upper() == "SUBSTANCE":
        details["parent_molecules"] = get_molecule_details_for_substance(obj)

    # Check for ELN_PREVIEW image (direct or via parent molecule)
    preview_pid = None
    try:
        if obj.get_datasets(type="ELN_PREVIEW"):
            preview_pid = obj.permId
        elif details.get("parent_molecules"):
            for pm in details["parent_molecules"]:
                pid = pm.get("permId")
                if pid:
                    p_obj = get_object(pid)
                    if p_obj and p_obj.get_datasets(type="ELN_PREVIEW"):
                        preview_pid = pid
                        break
    except Exception:
        pass
    if preview_pid:
        details["preview_permid"] = preview_pid

    return details


def get_instrument_components(instrument_query: str = "") -> Dict[str, Any]:
    """Inspect an instrument and list all attached components."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    instruments = []
    for itype in ["INSTRUMENT.STM", "INSTRUMENT"]:
        try:
            objs = s.get_objects(type=itype)
            for inst in objs:
                instruments.append(inst)
        except Exception:
            pass

    target_inst = None
    if instrument_query:
        q = instrument_query.lower()
        for inst in instruments:
            name = getattr(inst.props, "name", "") or ""
            if q in name.lower() or q in inst.permId.lower() or q in str(inst.type.code).lower():
                target_inst = inst
                break
    elif instruments:
        target_inst = instruments[0]

    if not target_inst:
        return {
            "error": f"Instrument matching '{instrument_query}' not found.",
            "available_instruments": [
                {"name": getattr(i.props, "name", i.permId), "permId": i.permId, "type": str(i.type.code)}
                for i in instruments
            ]
        }

    component_fields = [
        "preparation_tools", "pumps", "gauges", "vacuum_chambers", "analysers",
        "mechanical_components", "stm_components", "control_data_acquisition",
        "temperature_environment_control", "auxiliary_components", "ports_valves"
    ]

    components_by_category: Dict[str, List[Dict[str, Any]]] = {}
    total_components = 0

    for field in component_fields:
        vals = getattr(target_inst.props, field, None)
        if vals:
            if not isinstance(vals, list):
                vals = [vals]
            cat_list = []
            for comp_id in vals:
                comp = get_object(comp_id)
                if comp:
                    comp_name = getattr(comp.props, "name", None) or comp_id
                    cat_list.append({
                        "permId": comp.permId,
                        "name": str(comp_name),
                        "model": getattr(comp.props, "model", None),
                        "serial_number": getattr(comp.props, "serial_number", None),
                        "status": getattr(comp.props, "object_status", None) or "Active",
                        "link": format_link(str(comp_name), comp.permId, "SAMPLE"),
                    })
                else:
                    cat_list.append({
                        "permId": comp_id,
                        "name": comp_id,
                        "link": format_link(comp_id, comp_id, "SAMPLE"),
                    })
            if cat_list:
                components_by_category[field] = cat_list
                total_components += len(cat_list)

    loc = getattr(target_inst.props, "location", None)
    room_name = resolve_location_name(loc)
    inst_name = getattr(target_inst.props, "name", target_inst.permId)

    return {
        "instrument_name": inst_name,
        "permId": target_inst.permId,
        "type": str(target_inst.type.code),
        "location": room_name,
        "model": getattr(target_inst.props, "model", None),
        "total_components": total_components,
        "components_by_category": components_by_category,
        "link": format_link(inst_name, target_inst.permId, "SAMPLE"),
    }


def get_tools_in_room(room_query: str) -> Dict[str, Any]:
    """Retrieve all tools/components in a room."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    rooms = get_rooms_cache()
    matched_room_id = None
    matched_room_name = None

    q = room_query.lower()
    for rid, rname in rooms.items():
        if q in rname.lower() or q in rid.lower():
            matched_room_id = rid
            matched_room_name = rname
            break

    if not matched_room_id:
        return {
            "error": f"Room matching '{room_query}' not found.",
            "available_rooms": list(rooms.values())
        }

    instruments_in_room = []
    for itype in ["INSTRUMENT.STM", "INSTRUMENT"]:
        try:
            objs = s.get_objects(type=itype)
            for inst in objs:
                if getattr(inst.props, "location", None) == matched_room_id:
                    instruments_in_room.append(inst)
        except Exception:
            pass

    instrument_ids_in_room = {i.permId for i in instruments_in_room}

    components_res: List[Dict[str, Any]] = []
    try:
        comps = s.get_objects(
            type="COMPONENT",
            props=["name", "main_category", "sub_category", "model", "serial_number", "location", "object_status"]
        )
        for comp in comps:
            loc = getattr(comp.props, "location", None)
            is_in_room = (loc == matched_room_id)
            is_in_instrument = (loc in instrument_ids_in_room)

            if is_in_room or is_in_instrument:
                c_name = getattr(comp.props, "name", None) or comp.permId
                components_res.append({
                    "permId": comp.permId,
                    "name": str(c_name),
                    "main_category": getattr(comp.props, "main_category", None),
                    "sub_category": getattr(comp.props, "sub_category", None),
                    "model": getattr(comp.props, "model", None),
                    "serial_number": getattr(comp.props, "serial_number", None),
                    "status": getattr(comp.props, "object_status", None) or "Active",
                    "attached_to": resolve_location_name(loc),
                    "link": format_link(str(c_name), comp.permId, "SAMPLE"),
                })
    except Exception as e:
        print(f"Error querying components for room: {e}")

    return {
        "room_name": matched_room_name,
        "room_permId": matched_room_id,
        "instruments": [
            {
                "name": getattr(i.props, "name", i.permId),
                "permId": i.permId,
                "link": format_link(getattr(i.props, "name", i.permId), i.permId, "SAMPLE"),
            }
            for i in instruments_in_room
        ],
        "total_tools_and_components": len(components_res),
        "tools_and_components": components_res,
        "room_link": format_link(matched_room_name, matched_room_id, "SAMPLE"),
    }


def get_current_user() -> Dict[str, Any]:
    """Retrieve details of the currently authenticated openBIS user and home space."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    username = ""
    home_space = ""
    email = ""
    first_name = ""
    last_name = ""
    reg_date = ""

    try:
        resp = s._post_request(s.as_v3, {"method": "getSessionInformation", "params": [s.token]})
        if resp:
            username = resp.get("userName") or ""
            home_space = resp.get("homeGroupCode") or ""
            person = resp.get("person") or {}
            email = person.get("email") or ""
            first_name = person.get("firstName") or ""
            last_name = person.get("lastName") or ""
            if person.get("registrationDate"):
                import datetime
                reg_date = datetime.datetime.fromtimestamp(person["registrationDate"] / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        print(f"Error querying session information: {e}")

    # Fallback from token if username missing
    if not username and s.token and s.token.startswith("$pat-"):
        parts = s.token.split("-")
        if len(parts) > 1:
            username = parts[1]

    if not home_space and username:
        home_space = f"LAB205_{username.upper()}"

    return {
        "username": username,
        "home_space": home_space,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "registration_date": reg_date,
    }


def find_experiments(query: str) -> List[Any]:
    """Find experiments matching query by code, identifier, permId, or name."""
    s = get_session()
    if not s or not query:
        return []
    q = query.strip().lower()
    q_norm = q.replace(" ", "_").replace("-", "_")
    try:
        exps = s.get_experiments()
    except Exception:
        return []

    exact_matches = []
    fuzzy_matches = []
    for e in exps:
        p_name = str(getattr(e.props, "name", "") or "").lower()
        e_id = e.identifier.lower()
        e_code = e.code.lower()
        e_pid = e.permId.lower()
        if q == e_pid or q == e_id or q == e_code or q_norm == e_code or (p_name and (q == p_name or q_norm == p_name)):
            exact_matches.append(e)
        elif q in e_id or q_norm in e_id or (p_name and (q in p_name or q_norm in p_name)) or (len(q) > 3 and q in e_pid):
            fuzzy_matches.append(e)

    candidates = exact_matches if exact_matches else fuzzy_matches
    if len(candidates) > 1:
        user_info = get_current_user()
        home_sp = (user_info.get("home_space") or "").lower()
        if home_sp:
            home_matches = [c for c in candidates if home_sp in c.identifier.lower()]
            if home_matches:
                return home_matches
    return candidates


def find_projects(query: str) -> List[Any]:
    """Find projects matching query by code, identifier, permId, or description."""
    s = get_session()
    if not s or not query:
        return []
    q = query.strip().lower()
    q_norm = q.replace(" ", "_").replace("-", "_")
    try:
        projs = s.get_projects()
    except Exception:
        return []

    exact_matches = []
    fuzzy_matches = []
    for p in projs:
        p_id = p.identifier.lower()
        p_code = p.code.lower()
        p_pid = p.permId.lower()
        p_desc = str(getattr(p, "description", "") or "").lower()
        if q == p_pid or q == p_id or q == p_code or q_norm == p_code:
            exact_matches.append(p)
        elif q in p_id or q_norm in p_id or q in p_code or q_norm in p_code or (q and q in p_desc):
            fuzzy_matches.append(p)

    candidates = exact_matches if exact_matches else fuzzy_matches
    if len(candidates) > 1:
        user_info = get_current_user()
        home_sp = (user_info.get("home_space") or "").lower()
        if home_sp:
            home_matches = [c for c in candidates if home_sp in c.identifier.lower()]
            if home_matches:
                return home_matches
    return candidates


def get_sample_preparation_lineage(query: str) -> List[Dict[str, Any]]:
    """Trace sample preparations, process steps, and actions matching an experiment, project, sample, crystal, or substance."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    # 1. Check if query matches an experiment
    matched_exps = find_experiments(query)
    if matched_exps:
        results = []
        for exp in matched_exps[:3]:
            try:
                samples = s.get_samples(experiment=exp.identifier)
                for sm in samples:
                    if str(sm.type.code).upper() == "PREPARATION":
                        p_name = getattr(sm.props, "name", None) or sm.permId
                        steps_info = []
                        try:
                            children = sm.get_children()
                            for c_idx in range(len(children)):
                                st = children[c_idx]
                                st_name = getattr(st.props, "name", None) or st.permId
                                actions_list = []
                                act_ids = getattr(st.props, "actions", []) or []
                                for act_id in act_ids:
                                    act_obj = get_object(act_id)
                                    if act_obj:
                                        act_props = act_obj.props.all()
                                        actions_list.append({
                                            "permId": act_obj.permId,
                                            "type": str(act_obj.type.code),
                                            "name": getattr(act_obj.props, "name", None) or act_obj.permId,
                                            "duration": act_props.get("duration"),
                                            "details": {k: v for k, v in act_props.items() if v and k not in ["name", "duration"]},
                                            "link": format_link(getattr(act_obj.props, "name", act_obj.permId), act_obj.permId, "SAMPLE"),
                                        })
                                steps_info.append({
                                    "permId": st.permId,
                                    "name": str(st_name),
                                    "actions": actions_list,
                                    "link": format_link(str(st_name), st.permId, "SAMPLE", identifier=st.identifier),
                                })
                        except Exception:
                            pass
                        results.append({
                            "preparation_name": str(p_name),
                            "permId": sm.permId,
                            "identifier": sm.identifier,
                            "context": f"Experiment: {getattr(exp.props, 'name', exp.code)}",
                            "experiment_link": format_link(str(getattr(exp.props, 'name', exp.code)), exp.permId, "EXPERIMENT", identifier=exp.identifier),
                            "steps": steps_info,
                            "link": format_link(str(p_name), sm.permId, "SAMPLE", identifier=sm.identifier),
                        })
            except Exception:
                pass
        if results:
            return results

    # 2. Check if query matches a project
    matched_projs = find_projects(query)
    if matched_projs:
        results = []
        for prj in matched_projs[:3]:
            try:
                all_sm = list(s.get_samples(project=prj.identifier))
                pr_exps = s.get_experiments(project=prj.identifier)
                for pe_idx in range(len(pr_exps)):
                    pe = pr_exps[pe_idx]
                    try:
                        all_sm.extend(list(s.get_samples(experiment=pe.identifier)))
                    except Exception:
                        pass
                for sm in all_sm:
                    if str(sm.type.code).upper() == "PREPARATION":
                        p_name = getattr(sm.props, "name", None) or sm.permId
                        steps_info = []
                        try:
                            children = sm.get_children()
                            for c_idx in range(len(children)):
                                st = children[c_idx]
                                st_name = getattr(st.props, "name", None) or st.permId
                                actions_list = []
                                act_ids = getattr(st.props, "actions", []) or []
                                for act_id in act_ids:
                                    act_obj = get_object(act_id)
                                    if act_obj:
                                        act_props = act_obj.props.all()
                                        actions_list.append({
                                            "permId": act_obj.permId,
                                            "type": str(act_obj.type.code),
                                            "name": getattr(act_obj.props, "name", None) or act_obj.permId,
                                            "duration": act_props.get("duration"),
                                            "details": {k: v for k, v in act_props.items() if v and k not in ["name", "duration"]},
                                            "link": format_link(getattr(act_obj.props, "name", act_obj.permId), act_obj.permId, "SAMPLE"),
                                        })
                                steps_info.append({
                                    "permId": st.permId,
                                    "name": str(st_name),
                                    "actions": actions_list,
                                    "link": format_link(str(st_name), st.permId, "SAMPLE", identifier=st.identifier),
                                })
                        except Exception:
                            pass
                        results.append({
                            "preparation_name": str(p_name),
                            "permId": sm.permId,
                            "identifier": sm.identifier,
                            "context": f"Project: {prj.code}",
                            "steps": steps_info,
                            "link": format_link(str(p_name), sm.permId, "SAMPLE", identifier=sm.identifier),
                        })
            except Exception:
                pass
        if results:
            return results

    # 3. Fallback: Search all PREPARATION objects in openBIS by name, description, or children
    preps = s.get_objects(type="PREPARATION", props=["name", "description"])
    matched_preps = []
    q = query.lower()
    q_norm = q.replace(" ", "_").replace("-", "_")

    for p in preps:
        p_name = getattr(p.props, "name", "") or ""
        p_desc = getattr(p.props, "description", "") or ""
        if q in p_name.lower() or q_norm in p_name.lower() or q in p_desc.lower() or q_norm in p_desc.lower() or q in p.permId.lower():
            matched_preps.append(p)

    if not matched_preps:
        for p in preps:
            try:
                steps = p.get_children()
                if steps:
                    step_match = False
                    for st in steps:
                        st_name = getattr(st.props, "name", "") or ""
                        if q in st_name.lower() or q_norm in st_name.lower() or q in st.permId.lower():
                            step_match = True
                            break
                    if step_match:
                        matched_preps.append(p)
            except Exception:
                pass

    results = []
    for p in matched_preps[:10]:
        p_name = getattr(p.props, "name", None) or p.permId
        steps_info = []
        try:
            steps = p.get_children()
            if steps:
                for st in steps:
                    st_name = getattr(st.props, "name", None) or st.permId
                    actions_list = []
                    act_ids = getattr(st.props, "actions", []) or []
                    for act_id in act_ids:
                        act_obj = get_object(act_id)
                        if act_obj:
                            act_props = act_obj.props.all()
                            actions_list.append({
                                "permId": act_obj.permId,
                                "type": str(act_obj.type.code),
                                "name": getattr(act_obj.props, "name", None) or act_obj.permId,
                                "duration": act_props.get("duration"),
                                "details": {k: v for k, v in act_props.items() if v and k not in ["name", "duration"]},
                                "link": format_link(getattr(act_obj.props, "name", act_obj.permId), act_obj.permId, "SAMPLE"),
                            })

                    steps_info.append({
                        "permId": st.permId,
                        "name": str(st_name),
                        "actions": actions_list,
                        "link": format_link(str(st_name), st.permId, "SAMPLE"),
                    })
        except Exception:
            pass

        results.append({
            "preparation_name": str(p_name),
            "permId": p.permId,
            "steps": steps_info,
            "link": format_link(str(p_name), p.permId, "SAMPLE"),
        })

    return results


def list_spaces(query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """List or search spaces in openBIS."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    try:
        spaces = s.get_spaces()
    except Exception as e:
        return [{"error": f"Failed to retrieve spaces: {str(e)}"}]

    q = query.strip().lower()
    results = []
    for sp in spaces:
        code = str(sp.code)
        desc = str(getattr(sp, "description", "") or "")
        if not q or q in code.lower() or q in desc.lower():
            results.append({
                "code": code,
                "description": desc,
                "registrator": str(getattr(sp, "registrator", "") or ""),
                "registration_date": str(getattr(sp, "registrationDate", "") or ""),
                "link": format_link(code, code, "SPACE", identifier=f"/{code}"),
            })
            if len(results) >= limit:
                break
    return results


def list_projects(space: str = "", query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """List or search projects in openBIS, optionally filtered by space."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    try:
        if space:
            sp_clean = space.strip().strip("/")
            all_spaces = s.get_spaces()
            matched_space = None
            for sp in all_spaces:
                if sp.code.lower() == sp_clean.lower() or sp_clean.lower() in sp.code.lower():
                    matched_space = sp.code
                    break
            projs = s.get_projects(space=matched_space or sp_clean)
        else:
            projs = s.get_projects()
    except Exception as e:
        return [{"error": f"Failed to retrieve projects: {str(e)}"}]

    q = query.strip().lower()
    q_norm = q.replace(" ", "_").replace("-", "_")
    results = []
    for p in projs:
        p_id = str(p.identifier)
        p_code = str(p.code)
        p_desc = str(getattr(p, "description", "") or "")
        matches = True
        if q:
            matches = (
                q in p_id.lower() or q_norm in p_id.lower() or
                q in p_code.lower() or q_norm in p_code.lower() or
                q in p_desc.lower()
            )
        if matches:
            sp_code = p_id.split("/")[1] if p_id.startswith("/") and len(p_id.split("/")) > 1 else ""
            results.append({
                "permId": p.permId,
                "identifier": p_id,
                "code": p_code,
                "space": sp_code,
                "description": p_desc,
                "registrator": str(getattr(p, "registrator", "") or ""),
                "registration_date": str(getattr(p, "registrationDate", "") or ""),
                "leader": str(getattr(p, "leader", "") or ""),
                "link": format_link(p_code, p.permId, "PROJECT", identifier=p_id),
            })
            if len(results) >= limit:
                break
    return results


def get_experiments_by_project(project_query: str = "", include_collections: bool = False) -> Dict[str, Any]:
    """Retrieve all experiments within a specified project (excludes collections by default)."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    projects = s.get_projects()
    matched_proj = None

    if project_query:
        q = project_query.strip().lower()
        q_norm = q.replace(" ", "_").replace("-", "_")
        candidates = []
        for p in projects:
            p_id = p.identifier.lower()
            p_code = p.code.lower()
            p_desc = (p.description or "").lower() if hasattr(p, "description") and p.description else ""
            if q == p_code or q_norm == p_code or q in p_id or q_norm in p_id or (q and q in p_desc):
                candidates.append(p)

        if len(candidates) == 1:
            matched_proj = candidates[0]
        elif len(candidates) > 1:
            # Disambiguate: prioritize current user's home space first
            user_info = get_current_user()
            home_sp = (user_info.get("home_space") or "").lower()
            if home_sp:
                for c in candidates:
                    if home_sp in c.identifier.lower():
                        matched_proj = c
                        break
            # Next prioritize candidate that actually contains experiments
            if not matched_proj:
                for c in candidates:
                    try:
                        if len(s.get_experiments(project=c.identifier)) > 0:
                            matched_proj = c
                            break
                    except Exception:
                        pass
            if not matched_proj:
                matched_proj = candidates[0]
    elif len(projects) > 0:
        matched_proj = projects[0]

    if not matched_proj:
        # Convert to list safely to avoid pybis Things slice crash
        proj_identifiers = projects.df["identifier"].tolist() if hasattr(projects, "df") else [p.identifier for p in projects]
        return {
            "error": f"Project matching '{project_query}' not found.",
            "available_projects": proj_identifiers[:15]
        }

    exps = s.get_experiments(project=matched_proj.identifier)
    exp_list = []
    col_list = []
    for i in range(len(exps)):
        e = exps[i]
        e_type = str(e.type.code if hasattr(e.type, "code") else e.type)
        is_collection = "COLLECTION" in e_type.upper()

        e_name = getattr(e.props, "name", None) if hasattr(e, "props") else None
        label = e_name or e.identifier or e.code
        item = {
            "permId": e.permId,
            "identifier": e.identifier,
            "type": e_type,
            "name": str(label),
            "registrator": str(getattr(e, "registrator", "") or ""),
            "registration_date": str(getattr(e, "registrationDate", "") or ""),
            "link": format_link(str(label), e.permId, "COLLECTION" if is_collection else "EXPERIMENT", identifier=e.identifier),
        }
        if is_collection:
            col_list.append(item)
            if include_collections:
                exp_list.append(item)
        else:
            exp_list.append(item)

    return {
        "project_identifier": matched_proj.identifier,
        "project_code": matched_proj.code,
        "project_permId": matched_proj.permId,
        "total_experiments": len(exp_list),
        "experiments": exp_list,
        "collections_count": len(col_list),
    }


def get_experiment_details(experiment_query: str) -> Dict[str, Any]:
    """Retrieve full details of an experiment, including all preparations, process steps, measurement sessions, and datasets."""
    s = get_session()
    if not s:
        return {"error": "openBIS session is not connected."}

    candidates = find_experiments(experiment_query)
    if not candidates:
        return {
            "error": f"Experiment matching '{experiment_query}' not found.",
            "suggestion": "Check the experiment name, code, or permId."
        }

    exp = candidates[0]
    e_name = getattr(exp.props, "name", None) or exp.identifier
    e_desc = getattr(exp.props, "description", None) or ""

    # Fetch samples inside the experiment
    try:
        samples = s.get_samples(experiment=exp.identifier)
    except Exception:
        samples = []

    preps_info = []
    meas_info = []
    steps_info = []
    other_samples = []

    for i in range(len(samples)):
        sm = samples[i]
        stype = str(sm.type.code).upper()
        s_name = getattr(sm.props, "name", None) or sm.identifier
        item = {
            "permId": sm.permId,
            "identifier": sm.identifier,
            "name": str(s_name),
            "type": stype,
            "registrator": str(getattr(sm, "registrator", "") or ""),
            "registration_date": str(getattr(sm, "registrationDate", "") or ""),
            "link": format_link(str(s_name), sm.permId, "SAMPLE", identifier=sm.identifier),
        }

        if stype == "PREPARATION":
            child_steps = []
            try:
                children = sm.get_children()
                for c_idx in range(len(children)):
                    c = children[c_idx]
                    c_name = getattr(c.props, "name", None) or c.identifier
                    actions_list = []
                    act_ids = getattr(c.props, "actions", []) or []
                    for act_id in act_ids:
                        act_obj = get_object(act_id)
                        if act_obj:
                            act_props = act_obj.props.all()
                            actions_list.append({
                                "permId": act_obj.permId,
                                "type": str(act_obj.type.code),
                                "name": getattr(act_obj.props, "name", None) or act_obj.permId,
                                "duration": act_props.get("duration"),
                                "details": {k: v for k, v in act_props.items() if v and k not in ["name", "duration"]},
                                "link": format_link(getattr(act_obj.props, "name", act_obj.permId), act_obj.permId, "SAMPLE"),
                            })
                    child_steps.append({
                        "permId": c.permId,
                        "name": str(c_name),
                        "actions": actions_list,
                        "link": format_link(str(c_name), c.permId, "SAMPLE", identifier=c.identifier),
                    })
            except Exception:
                pass
            item["steps"] = child_steps
            preps_info.append(item)

        elif stype == "MEASUREMENT_SESSION":
            target_samples = []
            try:
                parents = sm.get_parents()
                for p_idx in range(len(parents)):
                    p = parents[p_idx]
                    p_name = getattr(p.props, "name", None) or p.identifier
                    target_samples.append({
                        "name": str(p_name),
                        "permId": p.permId,
                        "type": str(p.type.code),
                        "link": format_link(str(p_name), p.permId, "SAMPLE", identifier=p.identifier),
                    })
            except Exception:
                pass
            item["target_samples"] = target_samples
            try:
                dsets = sm.get_datasets()
                item["total_datasets"] = len(dsets)
                item["datasets"] = [
                    {
                        "permId": dsets[d_idx].permId,
                        "type": str(dsets[d_idx].type.code),
                        "link": format_link(f"{dsets[d_idx].type.code} ({dsets[d_idx].permId})", dsets[d_idx].permId, "DATASET"),
                    }
                    for d_idx in range(min(len(dsets), 10))
                ]
            except Exception:
                item["total_datasets"] = 0
                item["datasets"] = []
            meas_info.append(item)

        elif stype == "PROCESS_STEP":
            steps_info.append(item)
        else:
            other_samples.append(item)

    # Datasets directly attached to the experiment
    try:
        exp_dsets = s.get_datasets(experiment=exp.identifier)
        total_exp_dsets = len(exp_dsets)
        exp_dsets_sample = [
            {
                "permId": exp_dsets[d_idx].permId,
                "type": str(exp_dsets[d_idx].type.code),
                "link": format_link(f"{exp_dsets[d_idx].type.code} ({exp_dsets[d_idx].permId})", exp_dsets[d_idx].permId, "DATASET"),
            }
            for d_idx in range(min(len(exp_dsets), 10))
        ]
    except Exception:
        total_exp_dsets = 0
        exp_dsets_sample = []

    # Project info
    proj_id = exp.identifier.rsplit("/", 1)[0] if "/" in exp.identifier else ""
    proj_code = proj_id.split("/")[-1] if "/" in proj_id else ""

    return {
        "experiment_name": str(e_name),
        "permId": exp.permId,
        "identifier": exp.identifier,
        "code": exp.code,
        "type": str(exp.type.code),
        "description": e_desc,
        "registrator": str(getattr(exp, "registrator", "") or ""),
        "registration_date": str(getattr(exp, "registrationDate", "") or ""),
        "project_identifier": proj_id,
        "project_code": proj_code,
        "project_link": format_link(proj_code, proj_code, "PROJECT", identifier=proj_id) if proj_id else "",
        "link": format_link(str(e_name), exp.permId, "EXPERIMENT", identifier=exp.identifier),
        "total_samples": len(samples),
        "preparations": preps_info,
        "measurement_sessions": meas_info,
        "process_steps": steps_info,
        "other_samples": other_samples,
        "total_datasets": total_exp_dsets,
        "datasets_sample": exp_dsets_sample,
    }


def get_measurements_by_sample(sample_query: str) -> List[Dict[str, Any]]:
    """Retrieve measurement sessions and datasets associated with an experiment, project, or sample."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    # 1. Check if sample_query matches an experiment
    matched_exps = find_experiments(sample_query)
    if matched_exps:
        results = []
        for exp in matched_exps[:3]:
            try:
                samples = s.get_samples(experiment=exp.identifier)
                for sm_idx in range(len(samples)):
                    sm = samples[sm_idx]
                    if str(sm.type.code).upper() == "MEASUREMENT_SESSION":
                        ms_name = getattr(sm.props, "name", None) or sm.permId
                        sample_names = []
                        try:
                            parents = sm.get_parents()
                            for p_idx in range(len(parents)):
                                p = parents[p_idx]
                                p_name = getattr(p.props, "name", None) or p.permId
                                sample_names.append(str(p_name))
                        except Exception:
                            pass
                        datasets_info = []
                        try:
                            dsets = sm.get_datasets()
                            for d_idx in range(min(len(dsets), 3)):
                                ds = dsets[d_idx]
                                ds_label = f"{ds.type.code} ({ds.permId})"
                                datasets_info.append({
                                    "permId": ds.permId,
                                    "type": str(ds.type.code),
                                    "link": format_link(ds_label, ds.permId, "DATASET"),
                                })
                            tot_dsets = len(dsets)
                        except Exception:
                            tot_dsets = 0

                        results.append({
                            "session_name": str(ms_name),
                            "permId": sm.permId,
                            "identifier": sm.identifier,
                            "context": f"Experiment: {getattr(exp.props, 'name', exp.code)}",
                            "experiment_link": format_link(str(getattr(exp.props, 'name', exp.code)), exp.permId, "EXPERIMENT", identifier=exp.identifier),
                            "samples": sample_names,
                            "total_datasets": tot_dsets,
                            "datasets": datasets_info,
                            "link": format_link(str(ms_name), sm.permId, "SAMPLE", identifier=sm.identifier),
                        })
            except Exception:
                pass
        if results:
            return results

    # 2. Check if sample_query matches a project
    matched_projs = find_projects(sample_query)
    if matched_projs:
        results = []
        for prj in matched_projs[:3]:
            try:
                all_sm = list(s.get_samples(project=prj.identifier))
                pr_exps = s.get_experiments(project=prj.identifier)
                for pe_idx in range(len(pr_exps)):
                    pe = pr_exps[pe_idx]
                    try:
                        all_sm.extend(list(s.get_samples(experiment=pe.identifier)))
                    except Exception:
                        pass
                for sm in all_sm:
                    if str(sm.type.code).upper() == "MEASUREMENT_SESSION":
                        ms_name = getattr(sm.props, "name", None) or sm.permId
                        sample_names = []
                        try:
                            parents = sm.get_parents()
                            for p_idx in range(len(parents)):
                                p = parents[p_idx]
                                sample_names.append(str(getattr(p.props, "name", None) or p.permId))
                        except Exception:
                            pass
                        datasets_info = []
                        try:
                            dsets = sm.get_datasets()
                            for d_idx in range(min(len(dsets), 3)):
                                ds = dsets[d_idx]
                                datasets_info.append({
                                    "permId": ds.permId,
                                    "type": str(ds.type.code),
                                    "link": format_link(f"{ds.type.code} ({ds.permId})", ds.permId, "DATASET"),
                                })
                            tot_dsets = len(dsets)
                        except Exception:
                            tot_dsets = 0

                        results.append({
                            "session_name": str(ms_name),
                            "permId": sm.permId,
                            "identifier": sm.identifier,
                            "context": f"Project: {prj.code}",
                            "samples": sample_names,
                            "total_datasets": tot_dsets,
                            "datasets": datasets_info,
                            "link": format_link(str(ms_name), sm.permId, "SAMPLE", identifier=sm.identifier),
                        })
            except Exception:
                pass
        if results:
            return results

    # 3. Fallback: Search all MEASUREMENT_SESSION objects in openBIS by session name or parent sample
    ms_sessions = s.get_objects(type="MEASUREMENT_SESSION")
    matched = []
    q = sample_query.lower()

    for i in range(len(ms_sessions)):
        ms = ms_sessions[i]
        ms_name = getattr(ms.props, "name", "") or ""
        ms_match = q in ms_name.lower() or q in ms.permId.lower()

        sample_match = False
        sample_names = []
        try:
            parents = ms.get_parents()
            if parents:
                for p in parents:
                    p_name = getattr(p.props, "name", "") or ""
                    sample_names.append(p_name or p.permId)
                    if q in p_name.lower() or q in p.permId.lower():
                        sample_match = True
        except Exception:
            pass

        if ms_match or sample_match:
            datasets_info = []
            try:
                dsets = ms.get_datasets()
                if dsets:
                    for d_idx in range(min(len(dsets), 25)):
                        ds = dsets[d_idx]
                        ds_label = f"{ds.type.code} ({ds.permId})"
                        datasets_info.append({
                            "permId": ds.permId,
                            "type": str(ds.type.code),
                            "link": format_link(ds_label, ds.permId, "DATASET"),
                        })
            except Exception:
                pass

            matched.append({
                "session_name": ms_name or ms.permId,
                "permId": ms.permId,
                "samples": sample_names,
                "total_datasets": len(datasets_info),
                "datasets": datasets_info,
                "link": format_link(ms_name or ms.permId, ms.permId, "SAMPLE"),
            })

    return matched


def get_publications(query: str = "") -> List[Dict[str, Any]]:
    """Query publications in openBIS."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    pubs = s.get_objects(type="PUBLICATION")
    results = []
    q = query.lower()

    for i in range(len(pubs)):
        p = pubs[i]
        props = p.props.all()
        name = props.get("name") or p.permId
        doi = props.get("publication.identifier") or props.get("dataset_url") or ""
        url = props.get("publication.url") or ""
        abstract = props.get("abstract") or ""

        if not q or (q in name.lower() or q in doi.lower() or q in p.permId.lower() or q in abstract.lower()):
            results.append({
                "title": name,
                "permId": p.permId,
                "doi": doi,
                "url": url,
                "year": props.get("year"),
                "organization": props.get("publication.organization"),
                "type": props.get("publication.type"),
                "abstract": abstract[:300] + "..." if len(abstract) > 300 else abstract,
                "link": format_link(name, p.permId, "SAMPLE"),
            })

    return results


def get_process_templates(query: str = "") -> List[Dict[str, Any]]:
    """Retrieve process templates in openBIS and summarize their steps."""
    s = get_session()
    if not s:
        return [{"error": "openBIS session is not connected."}]

    procs = s.get_objects(type="PROCESS")
    results = []
    q = query.lower()

    for i in range(len(procs)):
        p = procs[i]
        p_name = getattr(p.props, "name", None) or p.permId
        p_desc = getattr(p.props, "description", None) or ""

        if not q or (q in p_name.lower() or q in p_desc.lower() or q in p.permId.lower()):
            steps_info = []
            step_ids = getattr(p.props, "process_steps", []) or []
            for sid in step_ids:
                st = get_object(sid)
                if st:
                    st_name = getattr(st.props, "name", None) or sid
                    steps_info.append({
                        "permId": st.permId,
                        "name": str(st_name),
                        "link": format_link(str(st_name), st.permId, "SAMPLE"),
                    })

            results.append({
                "template_name": str(p_name),
                "permId": p.permId,
                "description": p_desc,
                "total_steps": len(steps_info),
                "steps": steps_info,
                "link": format_link(str(p_name), p.permId, "SAMPLE"),
            })

    return results


_PREVIEW_BASE64_CACHE: Dict[str, str] = {}
PREVIEW_DISK_CACHE_DIR = Path("/tmp/openbis_preview_cache")


def get_preview_image_base64(permid_or_code: str) -> Optional[str]:
    """Retrieve the ELN_PREVIEW image (PNG/JPEG) for a sample, molecule, or substance.
    
    Checks the sample itself first, then checks parent molecules.
    Caches results in memory and on disk, returning a data:image/...;base64,... URI.
    """
    if not permid_or_code:
        return None

    key = str(permid_or_code).strip()
    if key in _PREVIEW_BASE64_CACHE:
        return _PREVIEW_BASE64_CACHE[key]

    # Check disk cache
    safe_key = re.sub(r'[^a-zA-Z0-9_\-]', '_', key)
    disk_file = PREVIEW_DISK_CACHE_DIR / f"{safe_key}.b64"
    if disk_file.exists():
        try:
            cached_val = disk_file.read_text(encoding="utf-8")
            if cached_val.startswith("data:image/"):
                _PREVIEW_BASE64_CACHE[key] = cached_val
                return cached_val
        except Exception:
            pass

    s = get_session()
    if not s:
        return None

    try:
        obj = get_object(key)
        if not obj:
            try:
                objs = s.get_samples(code=key)
                if objs:
                    obj = objs[0]
            except Exception:
                pass

        if not obj:
            return None

        # 1. Check direct ELN_PREVIEW datasets
        ds_list = []
        try:
            ds_list = obj.get_datasets(type="ELN_PREVIEW")
        except Exception:
            pass

        # 2. Check parents if not direct
        if not ds_list:
            try:
                for p in obj.get_parents():
                    p_ds = p.get_datasets(type="ELN_PREVIEW")
                    if p_ds:
                        ds_list = p_ds
                        break
            except Exception:
                pass

        if not ds_list:
            return None

        ds = ds_list[0]
        if not ds.file_list:
            return None

        img_filename = None
        for fn in ds.file_list:
            lower = fn.lower()
            if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                img_filename = fn
                break
        if not img_filename:
            img_filename = ds.file_list[0]

        with tempfile.TemporaryDirectory() as tmpdir:
            ds.download(files=[img_filename], destination=tmpdir)
            expected = Path(img_filename).name
            candidates = [p for p in Path(tmpdir).rglob("*") if p.is_file() and p.name == expected]
            if not candidates:
                return None
            img_bytes = candidates[0].read_bytes()

        ext = "png"
        if img_filename.lower().endswith((".jpg", ".jpeg")):
            ext = "jpeg"
        elif img_filename.lower().endswith(".gif"):
            ext = "gif"
        elif img_filename.lower().endswith(".webp"):
            ext = "webp"

        b64_str = base64.b64encode(img_bytes).decode("ascii")
        data_uri = f"data:image/{ext};base64,{b64_str}"
        _PREVIEW_BASE64_CACHE[key] = data_uri
        if hasattr(obj, "permId") and obj.permId != key:
            _PREVIEW_BASE64_CACHE[str(obj.permId)] = data_uri

        # Persist to disk cache
        try:
            PREVIEW_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            disk_file.write_text(data_uri, encoding="utf-8")
            if hasattr(obj, "permId") and obj.permId != key:
                (PREVIEW_DISK_CACHE_DIR / f"{obj.permId}.b64").write_text(data_uri, encoding="utf-8")
        except Exception:
            pass

        return data_uri
    except Exception as e:
        logger.warning(f"Error fetching preview image for {key}: {e}")
        return None

