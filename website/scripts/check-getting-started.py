#!/usr/bin/env python3
"""Check the published onboarding entry point and its same-site targets."""
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET

SITE = Path(__file__).resolve().parents[2] / ".mkdocs-site"


class Journey(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = 0
        self.links = set()
        self.image = False
        self.diagram_link = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        self.cards += "ok-feature-card" in classes
        if tag == "a":
            href = attrs.get("href", "")
            self.links.add(href)
            self.diagram_link |= href.endswith("learning-journey.svg")
        if tag == "img" and attrs.get("src", "").endswith("learning-journey.svg"):
            self.image = bool(attrs.get("alt"))


def main():
    html = (SITE / "getting-started/index.html").read_text(encoding="utf-8")
    parser = Journey()
    parser.feed(html)
    if parser.cards != 11 or not parser.image or not parser.diagram_link:
        raise SystemExit("Getting Started cards or accessible diagram incomplete")
    for marker in ("Choose your path", "Your learning journey", "Understand before you operate", "openkubes-research-lightbox.js"):
        if marker not in html:
            raise SystemExit(f"Getting Started missing {marker}")
    for route in ("/features/", "/architecture/", "/tutorials/", "/tutorials/capd-local-dev-environment/", "/tutorials/ok-cli-v1.0.1-getting-started/", "/docs/byoh/advanced-guide/", "/docs/byoh/advanced-guide/12-validation-limitations/", "/console/", "/ai/", "/developer-workspace/tutorial/", "/observability/", "/architecture/security-first/", "/community/how-to-update-docs/"):
        if route not in parser.links or not (SITE / route.lstrip("/") / "index.html").is_file():
            raise SystemExit(f"Getting Started missing link or output: {route}")
    for route in ("/docs/ok-local/tutorial-prerequisites/", "/docs/ok-cluster/registry-trust/"):
        if route in parser.links:
            raise SystemExit(f"Retired onboarding link: {route}")
    root = ET.parse(SITE / "getting-started/learning-journey.svg").getroot()
    ns = {"s": "http://www.w3.org/2000/svg"}
    if root.find("s:title", ns) is None or root.find("s:desc", ns) is None or root.findall(".//s:image", ns):
        raise SystemExit("Expected accessible native journey SVG")
    print("Getting Started: 6 paths, 2 environments, 3 principles, native SVG and links PASS")


if __name__ == "__main__":
    main()
