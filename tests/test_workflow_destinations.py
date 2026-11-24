"""App-owned handoff destinations resolve to the existing maintained pages."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "assistant.json").read_text())
PAGES = MANIFEST["workflow_pages"]


@pytest.mark.parametrize("workflow", list(PAGES))
def test_workflow_destination_exists(workflow):
    page = ROOT / PAGES[workflow]["notebook"]
    assert page.parent == ROOT and page.is_file()
    data = json.loads(page.read_text())
    assert data["nbformat"] == 4 and data["cells"]


def test_aliases_do_not_resolve_to_different_pages():
    seen = {}
    for key, route in PAGES.items():
        for alias in [key, *route.get("aliases", [])]:
            normalized = alias.casefold().replace("-", "_")
            assert normalized not in seen
            seen[normalized] = route["notebook"]


def test_non_chat_pages_do_not_promise_an_embedded_conversation():
    assert PAGES["chat"]["notebook"] == "4_openbis_chatbot.ipynb"
    assert PAGES["chat"]["assistant"]["embedded"]
    for workflow in ("samples", "measurements", "simulations", "laboratory"):
        assert not PAGES[workflow]["assistant"]["embedded"]
