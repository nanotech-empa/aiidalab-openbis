"""Unit tests for the new src.ai_agent module with PydanticAI."""

import pytest
from src.ai_agent import openbis_client, tools


def test_openbis_url_generation():
    """Verify permID link generation formatting."""
    pid = "20251013130831334-385"
    url = openbis_client.generate_openbis_url(pid, "SAMPLE")
    assert pid in url
    assert "showViewSamplePageFromPermId" in url

    exp_url = openbis_client.generate_openbis_url("20260319141141722-6358", "EXPERIMENT")
    assert "showViewExperimentPageFromPermId" in exp_url

    ds_url = openbis_client.generate_openbis_url("20260402125234156-6478", "DATASET")
    assert "showViewDataSetPageFromPermId" in ds_url


def test_format_link():
    """Verify markdown link helper."""
    pid = "20251013130831334-385"
    link = openbis_client.format_link("THz-STM", pid, "SAMPLE")
    assert "THz-STM" in link
    assert pid in link
    assert "](" in link


def test_ensure_permid_links_does_not_double_wrap():
    """Verify that ensure_permid_links converts raw permIDs without corrupting existing links."""
    from src.ai_agent.agent import ensure_permid_links

    text = (
        "Here is [CreaTec THz-STM (20251013130831334-385)](https://openbis/test). "
        "And a raw permId: 20260423122215040-6565."
    )
    linked = ensure_permid_links(text)

    # Existing link must remain intact
    assert "[CreaTec THz-STM (20251013130831334-385)](https://openbis/test)" in linked
    # Raw permId must now be linked
    assert "[20260423122215040-6565](" in linked


def test_standardize_markdown():
    """Verify downscaling of # / ## headings, LaTeX math stripping, and table newline fixing."""
    from src.ai_agent.agent import standardize_markdown

    raw_text = (
        "# Substance Details\n"
        "- Name: Substance 400a\n"
        "- Formula: $\\text{C}_{64}\\text{H}_{51}\\text{Br}$\n"
        "## Parent Molecule Details\n"
        "| Name | Formula || Sub | C |\n"
    )
    cleaned = standardize_markdown(raw_text)

    # Heading downscaled from # and ## to ###
    assert "### Substance Details" in cleaned
    assert "### Parent Molecule Details" in cleaned
    import re
    assert not re.search(r'^#{1,2}\s+', cleaned, flags=re.MULTILINE)

    # LaTeX math stripped to clean chemical formula
    assert "C64H51Br" in cleaned
    assert "$\\text" not in cleaned
    assert "$" not in cleaned

    # Table rows separated
    assert "|\n|" in cleaned


def test_load_schema_documentation():
    """Verify that schema documentation is loaded from docs/openBIS_schema_documentation.md."""
    from src.ai_agent.agent import load_schema_documentation, load_system_prompt

    doc = load_schema_documentation()
    assert doc != ""
    assert "## 1. Object Types" in doc
    assert "SUBSTANCE" in doc

    prompt = load_system_prompt()
    assert "### OpenBIS Data Model & Schema Documentation" in prompt
    assert "Registrator" in prompt
    assert "Registration Date" in prompt


def test_get_schema_documentation_tool():
    """Verify schema lookup tool for specific object types."""
    from src.ai_agent import tools
    from unittest.mock import MagicMock

    ctx = MagicMock()
    # Query object type list
    res_list = tools.get_schema_documentation(ctx, "")
    assert "Object Types" in res_list

    # Query specific type
    res_sub = tools.get_schema_documentation(ctx, "SUBSTANCE")
    assert "SUBSTANCE" in res_sub
    assert "empa_number" in res_sub.lower()


def test_registration_metadata_in_sample_details():
    """Verify that sample details and inventory include registrator and registration_date."""
    from src.ai_agent import openbis_client

    # Test with Substance 400a
    details = openbis_client.get_sample_details("20251013132127009-2124")
    assert "registrator" in details
    assert "registration_date" in details
    assert details["registrator"] != ""
    assert "2025" in details["registration_date"]

