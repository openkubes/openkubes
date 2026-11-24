#!/usr/bin/env python3
"""Validate the Features projection in the generated site."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

SITE = Path(__file__).resolve().parents[2] / ".mkdocs-site"


class Features(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = self.models = 0
        self.links = []
        self.diagram = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        self.cards += "ok-feature-card" in classes
        self.models += "ok-feature-model" in classes
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "img" and attrs.get("src", "").endswith("platform-capabilities.svg"):
            self.diagram = bool(attrs.get("alt"))


def main():
    html = (SITE / "features/index.html").read_text(encoding="utf-8")
    parser = Features()
    parser.feed(html)
    if (parser.cards, parser.models, parser.diagram) != (8, 4, True):
        raise SystemExit("Features inventory or diagram alt text incomplete")
    for marker in ("Capability maturity", "NO-GO", "openkubes-research-lightbox.js"):
        if marker not in html:
            raise SystemExit(f"Features missing {marker}")
    for retired in ("/docs/ok-local/tutorial-prerequisites/", "/docs/ok-cluster/registry-trust/"):
        # Sidebar may still list legacy pages until navigation cleanup is merged.
        source = Path(__file__).resolve().parents[1] / "pages/features/index.md"
        if retired in source.read_text(encoding="utf-8"):
            raise SystemExit(f"Retired feature link: {retired}")
    diagram = SITE / "features/platform-capabilities.svg"
    root = ET.parse(diagram).getroot()
    ns = {"s": "http://www.w3.org/2000/svg"}
    if root.find("s:title", ns) is None or root.find("s:desc", ns) is None or root.findall(".//s:image", ns):
        raise SystemExit("Expected accessible native Features SVG")
    if not any(urlsplit(link).path.endswith("platform-capabilities.svg") for link in parser.links):
        raise SystemExit("Features diagram must have a native full-size link")
    for route in ("/architecture/", "/architecture/capi/", "/tutorials/", "/tutorials/ok-cli-v1.0.1-getting-started/", "/console/", "/ai/", "/observability/", "/observability/contract/", "/developer-workspace/", "/developer-workspace/status/", "/architecture/security-first/", "/kubeception-v2/", "/docs/byoh/advanced-guide/", "/docs/byoh/advanced-guide/12-validation-limitations/", "/docs/byoh/advanced-guide/11-cluster-lifecycle/", "/ai/agentic-operations/", "/architecture/capi/blueprint/", "/open-universe/family/", "/tutorials/capd-local-dev-environment/"):
        if route not in parser.links or not (SITE / route.lstrip("/") / "index.html").is_file():
            raise SystemExit(f"Features missing link or output: {route}")
    print("Features: 8 capability cards, 4 models, native diagram, maturity and links PASS")


if __name__ == "__main__":
    main()
