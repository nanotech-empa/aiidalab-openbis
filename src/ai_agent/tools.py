"""tools.py: Strictly read-only tools designed for PydanticAI.

All tools are engineered with flat, primitive parameters (str, int) and clear,
forgiving defaults to ensure robust tool execution with smaller or open-source
models like Google Gemma 4.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic_ai import RunContext

from . import openbis_client


def get_inventory_summary(ctx: RunContext[None]) -> str:
    """Get the true total counts and statistics of all items, samples, and workflows registered in openBIS.

    ALWAYS call this tool when the user asks 'how many substances do we have?', 'how many crystals?',
    'how many molecules?', or asks for a general summary or overview of what is in the openBIS database.
    """
    counts = openbis_client.get_inventory_summary()
    if "error" in counts:
        return counts["error"]

    return (
        f"### openBIS Inventory & Database Summary:\n"
        f"- **Substances**: {counts.get('substances', 0):,} registered physical substances / precursors\n"
        f"- **Molecules**: {counts.get('molecules', 0):,} chemical structures\n"
        f"- **Crystals**: {counts.get('crystals', 0):,} substrate crystals / slabs\n"
        f"- **Instruments**: {counts.get('instruments', 0)} (e.g. CreaTec THz-STM)\n"
        f"- **Hardware Tools & Components**: {counts.get('components', 0)} attached components\n"
        f"- **Laboratory Rooms**: {counts.get('rooms', 0)}\n"
        f"- **Preparations**: {counts.get('preparations', 0)} sample preparation runs\n"
        f"- **Process Templates (SOPs)**: {counts.get('process_templates', 0)}\n"
        f"- **Measurement Sessions**: {counts.get('measurement_sessions', 0)} sessions with imaging datasets\n"
        f"- **Publications**: {counts.get('publications', 0)}\n"
        f"- **Projects**: {counts.get('projects', 0)}\n"
    )


def search_inventory(
    ctx: RunContext[None],
    query: str = "",
    sample_type: str = "",
    empa_number: int = 0,
    batch: str = "",
    formula: str = "",
    material: str = "",
    face: str = "",
) -> str:
    """Search for laboratory samples, substances, molecules, or crystals in openBIS.

    Args:
        query: Free-text search across names, EMPA IDs, batches, or permIDs (e.g. '704', 'Au111').
        sample_type: Type filter: 'SUBSTANCE', 'CRYSTAL', or 'MOLECULE'. Leave blank to search all.
        empa_number: Specific EMPA number (e.g. 704 or 563).
        batch: Substance batch letter (e.g. 'a', 'b', 'c').
        formula: Chemical sum formula (e.g. 'C38H28Br2', 'CH4').
        material: Crystal substrate material (e.g. 'Au', 'Ag', 'PdGa').
        face: Crystal surface face (e.g. '111', '110').

    Returns:
        Structured list of matching items with openBIS permID hyperlinks, status, location,
        and parent molecule formulas.
    """
    res = openbis_client.search_inventory(
        query=query,
        sample_type=sample_type,
        empa_number=empa_number,
        batch=batch,
        formula=formula,
        material=material,
        face=face,
        limit=15,
    )

    if isinstance(res, dict):
        total_matches = res.get("total_matches", 0)
        items = res.get("items", [])
    else:
        items = res
        total_matches = len(items)

    if not items:
        return f"No inventory items found matching your criteria (query='{query}', empa={empa_number}, formula='{formula}')."

    formatted = [f"Found {total_matches:,} matching items in openBIS (displaying first {len(items)}):"]
    for item in items:
        stype = item.get("sample_type", "SAMPLE")
        link = item.get("link", item.get("permId"))
        status = item.get("status", "Active")
        location = item.get("location", "Unknown")

        if stype == "SUBSTANCE":
            mols = item.get("parent_molecules", [])
            mol_str = ""
            if mols:
                mol_descs = [f"{m.get('link', m.get('name'))} (Formula: {m.get('sum_formula')})" for m in mols]
                mol_str = f"\n  - **Parent Molecule(s)**: {'; '.join(mol_descs)}"
            reg_info = f"\n  - **Registrator**: `{item.get('registrator')}` | **Registration Date**: `{item.get('registration_date')}`"
            formatted.append(
                f"- **Substance**: {link}\n"
                f"  - **EMPA ID**: {item.get('empa_number')}{item.get('batch')}\n"
                f"  - **Status**: {status} | **Location**: {location}{mol_str}{reg_info}"
            )
        elif stype == "CRYSTAL":
            reg_info = f"\n  - **Registrator**: `{item.get('registrator')}` | **Registration Date**: `{item.get('registration_date')}`"
            formatted.append(
                f"- **Crystal**: {link}\n"
                f"  - **Material**: {item.get('material')} | **Face**: {item.get('face')} | **Shape**: {item.get('shape')}\n"
                f"  - **Status**: {status} | **Location**: {location}{reg_info}"
            )
        elif stype == "MOLECULE":
            reg_info = f"\n  - **Registrator**: `{item.get('registrator')}` | **Registration Date**: `{item.get('registration_date')}`"
            formatted.append(
                f"- **Molecule**: {link}\n"
                f"  - **Sum Formula**: {item.get('sum_formula')}\n"
                f"  - **SMILES**: `{item.get('smiles')}` | **EMPA #**: {item.get('empa_number')}{reg_info}"
            )
        else:
            formatted.append(f"- **{stype}**: {link} ({status})")

    return "\n".join(formatted)


def get_sample_details(ctx: RunContext[None], sample_id: str) -> str:
    """Get full properties, parent lineage, and child relations for any sample, substance, or crystal.

    Args:
        sample_id: openBIS permId or exact sample name (e.g. '20251028133528461-4051' or 'Au111_Bubble').

    Returns:
        Full metadata including properties, parent items, and derived child items with links.
    """
    details = openbis_client.get_sample_details(sample_id)
    if "error" in details:
        return details["error"]

    props_lines = [f"  - **{k}**: {v}" for k, v in details.get("properties", {}).items()]
    parents = [p["link"] for p in details.get("parents", [])]
    children = [c["link"] for c in details.get("children", [])]

    out = [
        f"### Sample Details: {details.get('link')}",
        f"- **Type**: `{details.get('type')}`",
        f"- **PermId**: `{details.get('permId')}`",
        f"- **Registrator (Created by)**: `{details.get('registrator') or 'N/A'}`",
        f"- **Registration Date**: `{details.get('registration_date') or 'N/A'}`",
        f"- **Modifier**: `{details.get('modifier') or 'N/A'}`",
        f"- **Modification Date**: `{details.get('modification_date') or 'N/A'}`",
        "- **Properties**:",
        "\n".join(props_lines) if props_lines else "  *(None)*",
    ]
    if details.get("parent_molecules"):
        mol_items = []
        for m in details["parent_molecules"]:
            mol_items.append(
                f"  - {m.get('link')} | Formula: {m.get('sum_formula')} | Registrator: `{m.get('registrator')}` | Reg. Date: `{m.get('registration_date')}`"
            )
        out.append("- **Parent Molecule(s)**:\n" + "\n".join(mol_items))

    out.append(f"- **Parents ({len(parents)})**: {', '.join(parents) if parents else 'None'}")
    out.append(f"- **Children ({len(children)})**: {', '.join(children) if children else 'None'}")
    return "\n".join(out)


def get_instrument_components(ctx: RunContext[None], instrument_name: str = "") -> str:
    """Inspect an instrument and list all attached components (pumps, gauges, tools, analysers).

    Args:
        instrument_name: Name, permId, or model of the instrument (e.g. 'CreaTec THz-STM' or 'STM').
                         Leave blank to inspect the primary laboratory instrument.

    Returns:
        Structured breakdown of all attached components categorized by their function.
    """
    res = openbis_client.get_instrument_components(instrument_name)
    if "error" in res:
        err = res["error"]
        if "available_instruments" in res:
            avail = [f"- {i['name']} (`{i['permId']}`)" for i in res["available_instruments"]]
            err += "\nAvailable instruments:\n" + "\n".join(avail)
        return err

    out = [
        f"### Instrument: {res.get('link')}",
        f"- **Model**: {res.get('model', 'N/A')}",
        f"- **Location**: {res.get('location', 'N/A')}",
        f"- **Total Components Attached**: {res.get('total_components')}",
        "",
        "#### Attached Components by Category:",
    ]

    for cat, comps in res.get("components_by_category", {}).items():
        cat_title = cat.replace("_", " ").title()
        out.append(f"**{cat_title} ({len(comps)})**:")
        for c in comps:
            sn = f" (S/N: {c.get('serial_number')})" if c.get("serial_number") else ""
            out.append(f"- {c.get('link')}{sn} — Status: {c.get('status')}")
        out.append("")

    return "\n".join(out)


def get_tools_in_room(ctx: RunContext[None], room_name: str) -> str:
    """Find all laboratory tools, preparation tools, and hardware components located in a room.

    Checks both components placed directly in the room and components attached to
    instruments situated in that room.

    Args:
        room_name: Name or permId of the laboratory room (e.g. 'THz-STM Lab', 'Chemistry Lab', 'Preparation Lab').

    Returns:
        Listing of instruments and tools/components situated in the room with links.
    """
    res = openbis_client.get_tools_in_room(room_name)
    if "error" in res:
        err = res["error"]
        if "available_rooms" in res:
            err += "\nAvailable rooms: " + ", ".join(res["available_rooms"])
        return err

    out = [
        f"### Room: {res.get('room_link')}",
        f"- **Total Tools / Components**: {res.get('total_tools_and_components')}",
    ]

    insts = res.get("instruments", [])
    if insts:
        out.append(f"- **Instruments Present ({len(insts)})**: " + ", ".join(i["link"] for i in insts))
    out.append("")

    tools = res.get("tools_and_components", [])
    if not tools:
        out.append("*(No components or tools found in this room)*")
    else:
        out.append("#### Components & Tools:")
        for t in tools:
            cat = f" [{t.get('sub_category') or t.get('main_category') or 'Tool'}]"
            attached = f" *(attached to {t.get('attached_to')})*" if t.get("attached_to") else ""
            out.append(f"- {t.get('link')}{cat}{attached} — Status: {t.get('status')}")

    return "\n".join(out)


def get_sample_preparation(ctx: RunContext[None], query: str) -> str:
    """Trace preparation history, process steps, and actions performed on or using a sample/crystal/substance.

    Args:
        query: Sample, crystal, or substance name/identifier (e.g. 'Au111_Bubble', 'Ag110_VT', '704a').

    Returns:
        Sequence of preparation process steps and actions (deposition, annealing, sputtering) with parameters.
    """
    preps = openbis_client.get_sample_preparation_lineage(query)
    if not preps or "error" in preps[0]:
        return f"No preparation history found matching '{query}'."

    out = [f"### Sample Preparation Lineage for '{query}':"]
    for p in preps:
        out.append(f"\n#### Preparation: {p.get('link')}")
        steps = p.get("steps", [])
        if not steps:
            out.append("*(No registered process steps)*")
        for idx, st in enumerate(steps, 1):
            out.append(f"**Step {idx}: {st.get('link')}**")
            actions = st.get("actions", [])
            for a in actions:
                dur = f" (Duration: {a.get('duration')})" if a.get("duration") else ""
                details = [f"{k}={v}" for k, v in a.get("details", {}).items() if v]
                detail_str = f" [{', '.join(details)}]" if details else ""
                out.append(f"  - Action `{a.get('type')}`: {a.get('link')}{dur}{detail_str}")

    return "\n".join(out)


def get_experiments_in_project(ctx: RunContext[None], project_name: str = "") -> str:
    """List experiments and collections performed within a specified openBIS project.

    Args:
        project_name: Project identifier or code (e.g. '/DEFAULT/DEFAULT' or 'DEFAULT').
                      Leave blank to view the default project.

    Returns:
        List of experiments and collections with their types and openBIS links.
    """
    res = openbis_client.get_experiments_by_project(project_name)
    if "error" in res:
        err = res["error"]
        if "available_projects" in res:
            err += "\nAvailable projects: " + ", ".join(res["available_projects"])
        return err

    out = [
        f"### Project: `{res.get('project_identifier')}`",
        f"- **PermId**: `{res.get('project_permId')}`",
        f"- **Total Experiments**: {res.get('total_experiments')}",
        "",
        "#### Experiments & Collections:",
    ]
    for exp in res.get("experiments", []):
        out.append(f"- {exp.get('link')} (`{exp.get('type')}`)")

    return "\n".join(out)


def get_sample_measurements(ctx: RunContext[None], sample_name_or_id: str) -> str:
    """Retrieve measurement sessions (STM, AFM, STS) and datasets acquired on a given sample.

    Args:
        sample_name_or_id: Name or permId of the sample (e.g. '20260402074626332-6475' or sample name).

    Returns:
        Measurement sessions, date/instruments, and attached raw/imaging datasets with links.
    """
    sessions = openbis_client.get_measurements_by_sample(sample_name_or_id)
    if not sessions or "error" in sessions[0]:
        return f"No measurement sessions found for sample '{sample_name_or_id}'."

    out = [f"### Measurements for '{sample_name_or_id}':"]
    for s in sessions:
        out.append(f"\n- **Session**: {s.get('link')}")
        samples_str = ", ".join(s.get("samples", []))
        if samples_str:
            out.append(f"  - **Target Sample(s)**: {samples_str}")
        out.append(f"  - **Datasets Count**: {s.get('total_datasets')}")
        for ds in s.get("datasets", []):
            out.append(f"    - {ds.get('link')}")

    return "\n".join(out)


def get_publications(ctx: RunContext[None], query: str = "") -> str:
    """Search scientific publications registered in openBIS.

    Args:
        query: Search keywords in title, DOI, abstract, or permId. Leave blank to list all publications.

    Returns:
        List of publications with title, DOI, journal link, year, and abstract summary.
    """
    pubs = openbis_client.get_publications(query)
    if not pubs or "error" in pubs[0]:
        return f"No publications found matching '{query}'."

    out = [f"### Publications ({len(pubs)} found):"]
    for p in pubs:
        doi_str = f" | [DOI]({p.get('doi')})" if p.get("doi") else ""
        year_str = f" ({p.get('year')})" if p.get("year") else ""
        out.append(f"- **{p.get('link')}**{year_str}{doi_str}")
        if p.get("abstract"):
            out.append(f"  - *Abstract*: {p.get('abstract')}")

    return "\n".join(out)


def get_process_templates(ctx: RunContext[None], query: str = "") -> str:
    """List and summarize standard process templates (SOPs) currently in openBIS.

    Args:
        query: Optional search keyword in template name or description. Leave blank to list all templates.

    Returns:
        Summaries of process templates and their registered process steps.
    """
    procs = openbis_client.get_process_templates(query)
    if not procs or "error" in procs[0]:
        return f"No process templates found matching '{query}'."

    out = [f"### openBIS Process Templates ({len(procs)} available):"]
    for p in procs:
        out.append(f"\n#### {p.get('link')}")
        if p.get("description"):
            # Clean HTML tags if present
            clean_desc = p.get("description").replace("<p>", "").replace("</p>", "\n").replace("&nbsp;", " ")
            out.append(f"- **Description**: {clean_desc.strip()}")
        steps = p.get("steps", [])
        out.append(f"- **Process Steps ({len(steps)})**:")
        for idx, st in enumerate(steps, 1):
            out.append(f"  {idx}. {st.get('link')}")

    return "\n".join(out)


def get_openbis_object(ctx: RunContext[None], permid: str) -> str:
    """Universal read-only lookup tool for any openBIS entity by permId or identifier.

    Args:
        permid: The permId of the entity (e.g. '20251013130831334-385').

    Returns:
        Details, properties, and direct openBIS link for the entity.
    """
    obj = openbis_client.get_object(permid)
    if not obj:
        return f"Entity with permId '{permid}' was not found in openBIS."

    p_name = getattr(obj.props, "name", None) or obj.permId
    link = openbis_client.format_link(str(p_name), obj.permId, str(obj.type.code))
    props = {k: v for k, v in obj.props.all().items() if v}
    reg = getattr(obj, "registrator", None) or "N/A"
    reg_date = getattr(obj, "registrationDate", None) or "N/A"
    mod = getattr(obj, "modifier", None) or "N/A"
    mod_date = getattr(obj, "modificationDate", None) or "N/A"

    out = [
        f"### Entity: {link}",
        f"- **Type**: `{obj.type.code}`",
        f"- **PermId**: `{obj.permId}`",
        f"- **Registrator (Created by)**: `{reg}`",
        f"- **Registration Date**: `{reg_date}`",
        f"- **Modifier**: `{mod}`",
        f"- **Modification Date**: `{mod_date}`",
        "- **Properties**:",
    ]
    for k, v in props.items():
        out.append(f"  - **{k}**: {v}")

    return "\n".join(out)


def get_schema_documentation(ctx: RunContext[None], object_type: str = "") -> str:
    """Look up openBIS schema definitions, properties, and sections directly from docs/openBIS_schema_documentation.md.

    Args:
        object_type: The object type code or name to look up (e.g. 'SUBSTANCE', 'CRYSTAL', 'INSTRUMENT.STM', '2D_LAYER_MATERIAL').
                     Leave empty to inspect the full list of object types defined in the openBIS schema.

    Returns:
        The markdown schema documentation for the specified object type, or the summary index of types.
    """
    from pathlib import Path
    possible_paths = [
        Path("docs/openBIS_schema_documentation.md"),
        Path("/home/jovyan/apps/aiidalab-openbis/docs/openBIS_schema_documentation.md"),
        Path("../docs/openBIS_schema_documentation.md"),
    ]
    doc_path = None
    for p in possible_paths:
        if p.exists():
            doc_path = p
            break

    if not doc_path:
        return "Schema documentation file 'docs/openBIS_schema_documentation.md' was not found."

    text = doc_path.read_text(encoding="utf-8")
    if not object_type.strip():
        # Return Section 1 list of object types
        m = re.search(r'## 1\. Object Types.*?(?=## 2\. Data Set Types|\Z)', text, re.DOTALL)
        if m:
            return m.group(0)[:4000]
        return text[:4000]

    ot = object_type.strip().upper()
    # Search for section corresponding to this object type
    pattern = rf'###\s+[^\n]+\n\* \*\*Code:\*\*\s+`?{re.escape(ot)}`?.*?(?=\n###\s+|\n## |\Z)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(0).strip()

    pattern2 = rf'###\s+([^\n]*{re.escape(object_type)}[^\n]*).*?(?=\n###\s+|\n## |\Z)'
    match2 = re.search(pattern2, text, re.IGNORECASE | re.DOTALL)
    if match2:
        return match2.group(0).strip()

    return f"Object type '{object_type}' was not found in docs/openBIS_schema_documentation.md."
