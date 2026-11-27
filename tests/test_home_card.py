"""Keep the installed Home card independent of remote image requests."""

from html.parser import HTMLParser
import runpy
from pathlib import Path
from urllib.parse import urljoin

import pytest


class Card(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.src = dict(attrs)["src"]
        if tag == "a":
            self.href = dict(attrs)["href"]


@pytest.mark.parametrize(
    "prefix,app", [("", "aiidalab-openbis"), ("/user/example", "openbis-renamed")]
)
def test_home_card_uses_jupyter_file_route(prefix, app):
    root = Path(__file__).resolve().parents[1]
    launcher = runpy.run_path(root / "start.py")["get_start_widget"]
    home = f"https://lab.example{prefix}/apps/apps/home/start.ipynb"
    widget = launcher(f"../{app}", "../../..", f"../../../notebooks/apps/{app}")
    try:
        card = Card()
        card.feed(widget.value)
        assert urljoin(home, card.src) == (
            f"https://lab.example{prefix}/files/apps/{app}/aiidalab_openbis_logo.png"
        )
        assert urljoin(home, card.href) == (
            f"https://lab.example{prefix}/apps/apps/{app}/0_home.ipynb"
        )
        logo = (root / "aiidalab_openbis_logo.png").read_bytes()
        assert logo.startswith(b"\x89PNG\r\n\x1a\n")
        assert logo == (root / "aiidalab_openbis_logo.jpg").read_bytes()
    finally:
        widget.close()
