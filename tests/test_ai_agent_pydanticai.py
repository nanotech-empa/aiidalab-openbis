"""Unit tests for the new src.ai_agent module with PydanticAI."""

import pytest
from src.ai_agent import openbis_client, tools


def test_openbis_url_generation():
    """Verify permID link generation formatting."""
    pid = "20251013130831334-385"
    url = openbis_client.generate_openbis_url(pid, "SAMPLE")
    assert pid in url
    assert "showViewSamplePageFromPermId" in url

    exp_url = openbis_client.generate_openbis_url("20260319141141722-6358", "EXPERIMENT", identifier="/DEFAULT/DEFAULT/EXP1")
    assert "showExperimentPageFromIdentifier" in exp_url
    assert "menuUniqueId" in exp_url

    proj_url = openbis_client.generate_openbis_url("20220816104445380-1", "PROJECT", identifier="/DEFAULT/DEFAULT")
    assert "showProjectPageFromIdentifier" in proj_url
    assert "menuUniqueId" in proj_url

    sp_url = openbis_client.generate_openbis_url("DEFAULT", "SPACE")
    assert "showSpacePageFromIdentifier" in sp_url

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


def test_get_current_user_and_tool():
    """Verify that current user info is retrieved correctly from session."""
    user = openbis_client.get_current_user()
    assert "username" in user
    assert user["username"] != ""
    assert "home_space" in user
    assert user["home_space"] != ""

    from unittest.mock import MagicMock
    ctx = MagicMock()
    user_str = tools.get_current_user_info(ctx)
    assert user["username"] in user_str
    assert user["home_space"] in user_str


def test_list_spaces_and_projects_tools():
    """Verify that spaces and projects can be listed and searched."""
    spaces = openbis_client.list_spaces()
    assert len(spaces) > 0
    assert any("LAB205" in s["code"] for s in spaces)

    from unittest.mock import MagicMock
    ctx = MagicMock()
    spaces_str = tools.list_spaces(ctx, "LAB205")
    assert "OpenBIS Spaces" in spaces_str
    assert "LAB205" in spaces_str

    projs = openbis_client.list_projects()
    assert len(projs) > 0

    projs_str = tools.list_projects(ctx, query="TEST_PROJECT")
    assert "TEST_PROJECT" in projs_str


def test_get_experiments_by_project_filtering_and_safe_slicing():
    """Verify that get_experiments_by_project filters collections and does not crash on slicing."""
    # 1. Non-existent project search must safely report error without 'slice' object has no attribute 'upper'
    res_not_found = openbis_client.get_experiments_by_project("NonExistentProject12345")
    assert "error" in res_not_found
    assert "available_projects" in res_not_found
    assert isinstance(res_not_found["available_projects"], list)

    # 2. Query 'Test Project' (with space) should match TEST_PROJECT
    res = openbis_client.get_experiments_by_project("Test Project")
    assert "error" not in res
    assert "TEST_PROJECT" in res["project_identifier"]
    assert res["total_experiments"] > 0
    # Must NOT contain collections by default
    for exp in res["experiments"]:
        assert "COLLECTION" not in exp["type"].upper()

    assert res["collections_count"] > 0

    # 3. Via tool
    from unittest.mock import MagicMock
    ctx = MagicMock()
    tool_output = tools.get_experiments_in_project(ctx, "Test Project")
    assert "TEST_PROJECT" in tool_output
    assert "Collections in Project" in tool_output


def test_get_experiment_details_and_tool():
    """Verify get_experiment_details extracts preparations, measurement sessions, and datasets."""
    res = openbis_client.get_experiment_details("Tiptime3_012026")
    assert "error" not in res
    assert res["code"] == "EXPERIMENT_7"
    assert "SPE_HBN" in res["identifier"]
    assert len(res["preparations"]) == 3
    assert len(res["measurement_sessions"]) == 11
    assert res["total_datasets"] > 0

    from unittest.mock import MagicMock
    ctx = MagicMock()
    out = tools.get_experiment_details(ctx, "Tiptime3_012026")
    assert "Tiptime3_012026" in out
    assert "Preparations (3)" in out
    assert "Measurement Sessions (11)" in out
    assert "Total Datasets Attached" in out


def test_preparations_and_measurements_by_experiment_and_project():
    """Verify preparations and measurements can be found via experiment or project queries."""
    from unittest.mock import MagicMock
    ctx = MagicMock()

    # Query preparations with experiment name
    preps_exp = tools.get_sample_preparation(ctx, "Tiptime3_012026")
    assert "PREP_20260108125337_Ag111" in preps_exp or "Preparation" in preps_exp
    assert "Step" in preps_exp

    # Query measurements with experiment name
    meas_exp = tools.get_sample_measurements(ctx, "Tiptime3_012026")
    assert "Measurement Session on Sample" in meas_exp
    assert "Datasets Count" in meas_exp

    # Query preparations with project name
    preps_proj = tools.get_sample_preparation(ctx, "SPE_HBN")
    assert "Preparation" in preps_proj

    # Query measurements with project name
    meas_proj = tools.get_sample_measurements(ctx, "SPE_HBN")
    assert "Measurement Session" in meas_proj



