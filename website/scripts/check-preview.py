#!/usr/bin/env python3
"""Minimal preview acceptance checks for existing homepage URLs and assets."""
from html.parser import HTMLParser
from pathlib import Path
import re

from retired_widgets import check_retired_widgets

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"
LEGACY = ROOT / "docs" / "index.html"
ARTICLES = [
    "if-we-built-kubernetes-today",
    "developer-workspace-blog-post",
    "agentic-operations-reference-architecture",
    "vault-secret-contract-blog-post",
    "the-contract-is-the-guardrail-blog-post",
    "openkubes-self-healing-blog-post",
    "openkubes-blog-post",
]
class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "href", "poster"):
            if attrs.get(key):
                self.refs.append(attrs[key])

def main():
    index = SITE / "index.html"
    html = index.read_text(encoding="utf-8")
    original = LEGACY.read_text(encoding="utf-8")
    check_retired_widgets(SITE)
    if "ok-global-nav" not in html or "OpenKubes primary navigation" not in html:
        raise SystemExit("Missing shared homepage navigation")
    if 'class="ok-global-nav__brand ok-global-nav__brand--text"' not in html:
        raise SystemExit("Missing homepage wordmark link")
    if '<img src="/openkubes-logo.png"' in html.split('ok-global-nav__links',1)[0]:
        raise SystemExit("Unexpected logo image in shared homepage navigation")
    wordmark = (ROOT / "website/overrides/partials/openkubes-wordmark.html").read_text(encoding="utf-8").strip()
    if wordmark not in html or 'aria-label="OpenKubes Home"' not in html:
        raise SystemExit("Missing accessible multicolor navigation wordmark")
    if html.count('id="ok-mkdocs-philosophy"') != 1:
        raise SystemExit("Expected exactly one homepage philosophy component")
    if html.index('id="ok-mkdocs-philosophy"') > html.index('<header>'):
        raise SystemExit("Philosophy must precede the existing homepage hero")
    for asset in ("openkubes-branding.css", "openkubes-branding.js"):
        if not (SITE / "assets" / asset).is_file() or f'/assets/{asset}' not in html:
            raise SystemExit(f"Missing homepage branding asset: {asset}")
    console_start = html.index('id="ok-home-console-en"')
    if not html.index('class="console-launch"') < console_start < html.index('class="platform-hero"'):
        raise SystemExit("Console gallery must appear between installer announcement and hero animation")
    for name in ("agent-catalog", "cluster-inventory", "ai-diagnostics-preview"):
        relative = f"assets/images/console/ok-console-{name}.webp"
        if not (SITE / relative).is_file() or f'src="{relative}"' not in html:
            raise SystemExit(f"Missing Console screenshot: {relative}")
    for name in ("openkubes-console-gallery.css", "openkubes-console-carousel.js"):
        if not (SITE / "assets" / name).is_file() or f'assets/{name}' not in html:
            raise SystemExit(f"Missing Console gallery asset: {name}")
    if "Open Code. Public Repositories. Transparent Decisions." not in html:
        raise SystemExit("Console Open Source panel is missing")
    for href in ("/", "/features/", "/architecture/", "/research/", "/blog/", "/tutorials/", "/docs/", "/community/"):
        if f'href="{href}"' not in html:
            raise SystemExit(f"Navigation link missing: {href}")
    for asset in ("media/openkubes-hero-light.webm", "media/openkubes-hero-light.mp4", "media/openkubes-hero-light-poster.webp"):
        if asset not in html or asset not in original:
            raise SystemExit(f"Hero media reference lost: {asset}")
    if not (SITE / "assets" / "openkubes-navigation.css").is_file():
        raise SystemExit("Shared brand stylesheet missing")
    nav_css = (SITE / "assets" / "openkubes-navigation.css").read_text(encoding="utf-8")
    if ".ok-global-nav{" not in nav_css or "position:sticky;top:0;z-index:1000" not in nav_css:
        raise SystemExit("Homepage global navigation is not configured as sticky")
    if ".ok-global-nav--material" not in nav_css or "position:sticky" not in nav_css:
        raise SystemExit("Material global navigation is not configured as sticky")
    for section in ("features", "architecture", "research", "blog", "community", "docs"):
        output = SITE / section / "index.html"
        if output.is_file():
            page_html = output.read_text(encoding="utf-8")
            if section == "features" and 'ok-global-nav__brand--text' not in page_html:
                raise SystemExit("OpenKubes text brand missing from Material navigation")
            if wordmark not in page_html:
                raise SystemExit(f"Multicolor navigation wordmark missing on {section}")
            if 'id="ok-mkdocs-philosophy"' in page_html:
                raise SystemExit(f"Homepage philosophy unexpectedly rendered on {section}")
            if "OpenKubes primary navigation" not in page_html:
                raise SystemExit(f"Shared navigation missing on {section}")
    if not (SITE / "assets" / "openkubes-theme.css").is_file():
        raise SystemExit("Shared Material theme asset missing")
    guide_path = SITE / "community" / "how-to-update-docs" / "index.html"
    if not guide_path.is_file():
        raise SystemExit("Missing community documentation contribution guide")
    if "How to update the docs" not in guide_path.read_text(encoding="utf-8"):
        raise SystemExit("Incomplete community contribution guide")
    # Guard the OK AI navigation and generated capability entry points.
    for ai_path in ("ai/index.html", "ai/open-webui/index.html",
                    "ai/openclaw/index.html", "ai/kagent-platform-diagnostics/index.html",
                    "ai/agentic-operations/index.html", "ai/ai-glossary-newbies/index.html",
                    "ai/ai-roadmap/index.html"):
        if not (SITE / ai_path).is_file():
            raise SystemExit(f"Missing OK AI page: {ai_path}")
    roadmap_html = (SITE / "ai" / "ai-roadmap" / "index.html").read_text(encoding="utf-8")
    for required in ("Documentation Assistant", "Read-only Diagnostics",
                     "Agentic Operations", "ok-ai-roadmap__card"):
        if required not in roadmap_html:
            raise SystemExit(f"OK AI roadmap missing required content: {required}")
    if roadmap_html.count('class="ok-ai-roadmap__card ') != 3:
        raise SystemExit("OK AI roadmap must render exactly three cards")
    glossary_html = (SITE / "ai" / "ai-glossary-newbies" / "index.html")
    if not glossary_html.is_file():
        raise SystemExit("Missing AI Glossary rendered page")
    glossary_text = glossary_html.read_text(encoding="utf-8")
    for heading in ("Stage 1", "Stage 2", "Stage 3", "Stage 4"):
        if heading not in glossary_text:
            raise SystemExit(f"AI Glossary incomplete: {heading}")
    ai_html = (SITE / "ai" / "index.html").read_text(encoding="utf-8")
    if "Open WebUI" not in ai_html or "OpenClaw" not in ai_html:
        raise SystemExit("OK AI overview incomplete")
    # Require all OK Observability pages in the generated preview.
    for observability_path in (
        "observability/index.html",
        "observability/stack/index.html",
        "observability/contract/index.html",
        "observability/installation/index.html",
    ):
        if not (SITE / observability_path).is_file():
            raise SystemExit(f"Missing OK Observability page: {observability_path}")
    observability_html = (SITE / "observability" / "index.html").read_text(encoding="utf-8")
    if "Observability Capability" not in observability_html or "Capability Contract" not in observability_html:
        raise SystemExit("OK Observability overview incomplete")
    console_html = SITE / "console" / "index.html"
    if not console_html.is_file():
        raise SystemExit("Missing OK Console generated page")
    if "Local Kind installation" not in console_html.read_text(encoding="utf-8"):
        raise SystemExit("OK Console documentation incomplete")
    # Ensure the contributor Tutorials section and CAPD diagram are generated.
    for tutorial_path in (
        "tutorials/index.html",
        "tutorials/capd-local-dev-environment/index.html",
        "tutorials/capd-local-network.svg",
        "tutorials/capi-controller-hierarchy.svg",
        "tutorials/capd-vs-byoh-infrastructure.svg",
    ):
        if not (SITE / tutorial_path).is_file():
            raise SystemExit(f"Missing Tutorials output: {tutorial_path}")
    tutorials_html = (SITE / "tutorials" / "index.html").read_text(encoding="utf-8")
    capd_html = (SITE / "tutorials" / "capd-local-dev-environment" / "index.html").read_text(encoding="utf-8")
    if "Build a Local OpenKubes BYOH Development Environment with CAPD" not in tutorials_html:
        raise SystemExit("Tutorials landing page is missing the CAPD contributor tutorial")
    if "capd-local-network.svg" not in capd_html:
        raise SystemExit("CAPD tutorial is missing its network diagram reference")
    for diagram in ("capi-controller-hierarchy.svg", "capd-vs-byoh-infrastructure.svg"):
        if diagram not in capd_html:
            raise SystemExit(f"CAPD tutorial is missing diagram reference: {diagram}")
    if '<a href="/tutorials/">Tutorials</a>' not in capd_html:
        raise SystemExit("Shared Material page navigation is missing Tutorials")
    # Security First must be first in Architecture nav, with a real vector asset.
    security_page = SITE / "architecture" / "security-first" / "index.html"
    security_svg = SITE / "architecture" / "security-first.svg"
    if not security_page.is_file() or not security_svg.is_file():
        raise SystemExit("Missing Security First article or SVG")
    security_html = security_page.read_text(encoding="utf-8")
    if "Security First: Why OpenKubes Starts with Security" not in security_html or "security-first.svg" not in security_html:
        raise SystemExit("Security First article not rendered with diagram")
    svg_source = security_svg.read_text(encoding="utf-8")
    if "<svg" not in svg_source or "<image" in svg_source or "data:image/" in svg_source:
        raise SystemExit("Security First must be native SVG, not embedded raster")
    if "ADR-Platform-000" not in svg_source or "SECURITY FIRST" not in svg_source:
        raise SystemExit("Security First SVG missing foundation labels")
    models_svg = SITE / "architecture" / "kubernetes-models-simple.svg"
    if not models_svg.is_file():
        raise SystemExit("Missing simplified Kubernetes models SVG")
    models_source = models_svg.read_text(encoding="utf-8")
    if "<svg" not in models_source or "<image" in models_source or "data:image/" in models_source:
        raise SystemExit("Kubernetes models diagram must be native vector SVG")
    for label in ("Classic / BYOH", "vCluster", "VNC / KubeVirt", "HCP"):
        if label not in models_source:
            raise SystemExit(f"Kubernetes models diagram missing label: {label}")
    if "kubernetes-models-simple.svg" not in security_html:
        raise SystemExit("Security First article is missing model diagram")
    if "ok-security-models-figure" not in security_html:
        raise SystemExit("Security First model diagram link and responsive wrapper absent")
    if 'href="/architecture/kubernetes-models-simple.svg"' not in security_html:
        raise SystemExit("Kubernetes models diagram does not link to the correct full-size SVG URL")
    if 'src="/architecture/kubernetes-models-simple.svg"' not in security_html:
        raise SystemExit("Kubernetes models image does not use its published root-relative SVG URL")
    if 'href="kubernetes-models-simple.svg"' in security_html or 'src="kubernetes-models-simple.svg"' in security_html:
        raise SystemExit("Relative models SVG links break under /architecture/security-first/")
    styles = (SITE / "assets" / "openkubes-theme.css").read_text(encoding="utf-8")
    if ".ok-security-models-figure" not in styles or "max-width: 768px" not in styles:
        raise SystemExit("Kubernetes models mobile layout CSS missing")
    navigation = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    if navigation.index("- Security First: architecture/security-first.md") > navigation.index("- CAPI Overview: architecture/capi/index.md"):
        raise SystemExit("Security First must precede CAPI in Architecture navigation")
    # Research navigation and publication boundaries.
    # Public Research must never expose private Jira ticket IDs or private URLs.
    # Scan source-owned pages and rendered HTML to catch future regressions.
    research_sources = ROOT / "website" / "pages" / "research"
    research_outputs = SITE / "research"
    for candidate in list(research_sources.rglob("*.md")) + list(research_outputs.rglob("*.html")):
        body = candidate.read_text(encoding="utf-8")
        if re.search(r"\bOK-\d+\b|kubernauts\.atlassian\.net", body, flags=re.I):
            raise SystemExit(f"Private Jira reference in public Research: {candidate}")
    for research_path in ("research/index.html", "research/security/index.html",
                          "research/security/hitl-hotl-policy-bounded-autonomy/index.html",
                          "research/experiments/index.html"):
        if not (SITE / research_path).is_file():
            raise SystemExit(f"Missing Research page: {research_path}")
    research_html = (SITE / "research/security/hitl-hotl-policy-bounded-autonomy/index.html").read_text(encoding="utf-8")
    # Verify stable maturity concepts, not a brittle exact editorial sentence.
    research_text = research_html.lower()
    for label in ("research paper 001", "reviewed research", "adr-035",
                  "standing mandate", "production"):
        if label not in research_text:
            raise SystemExit(f"Research maturity concept absent: {label}")
    if not re.search(r"new (?:accepted )?normative adr|new adr", research_text):
        raise SystemExit("Research paper does not explain the future HOTL ADR requirement")
    if not re.search(r"not a (?:deployed system diagram|production deployment)|not.*production[- ]approved", research_text):
        raise SystemExit("Research paper does not distinguish research from production")
    if '<a href="/research/">Research</a>' not in research_html:
        raise SystemExit("Shared Material navigation missing Research")
    lightbox_js = SITE / "assets/openkubes-research-lightbox.js"
    if not lightbox_js.is_file():
        raise SystemExit("Research lightbox JavaScript not staged")
    lightbox_source = lightbox_js.read_text(encoding="utf-8")
    for required in ('showModal()', 'dialog.addEventListener("close"', 'event.preventDefault()'):
        if required not in lightbox_source:
            raise SystemExit(f"Research lightbox missing required behavior: {required}")
    if "openkubes-research-lightbox.js" not in research_html:
        raise SystemExit("Research lightbox JavaScript not loaded on paper")
    research_svg = SITE / "research/security/policy-bounded-autonomy.svg"
    if not research_svg.is_file():
        raise SystemExit("Research architecture SVG missing")
    research_source = research_svg.read_text(encoding="utf-8")
    if "<svg" not in research_source or "<image" in research_source or "data:image/" in research_source:
        raise SystemExit("Research architecture must be native SVG, without embedded raster")
    if "FUTURE HOTL" not in research_source or "RESEARCH" not in research_source:
        raise SystemExit("Research diagram is missing future-HOTL maturity labels")
    if not re.search(r'<img[^>]+src="[^"]*policy-bounded-autonomy\.svg"', research_html):
        raise SystemExit("Research paper diagram not embedded")
    research_index_html = (SITE / "research/index.html").read_text(encoding="utf-8")
    if not re.search(r'<img[^>]+src="[^"]*policy-bounded-autonomy\.svg"', research_index_html):
        raise SystemExit("Research landing diagram preview missing")
    # Check imported, pinned CAPI architecture pages, ADRs and SVG assets.
    capi = SITE / "architecture" / "capi"
    for required in ("index.html", "blueprint/index.html", "decisions/index.html"):
        if not (capi / required).is_file():
            raise SystemExit(f"Missing CAPI architecture page: {required}")
    expected_adrs = (
        "ADR-CAPI-001-management-topologies",
        "ADR-CAPI-002-git-source-of-truth",
        "ADR-CAPI-003-ownership-fencing",
        "ADR-CAPI-004-disposable-bootstrap",
        "ADR-CAPI-005-git-velero-recovery",
        "ADR-CAPI-006-blue-green-handover",
        "ADR-CAPI-007-disaster-recovery",
    )
    for slug in expected_adrs:
        if not (capi / "decisions" / slug / "index.html").is_file():
            raise SystemExit(f"Missing imported CAPI ADR: {slug}")
    article = (capi / "blueprint" / "index.html").read_text(encoding="utf-8")
    for name in ("management-topologies.svg", "bootstrap-pivot.svg",
                 "blue-green-handover.svg", "disaster-recovery.svg"):
        if not (capi / "diagrams" / name).is_file() or name not in article:
            raise SystemExit(f"CAPI architecture diagram missing or unlinked: {name}")
    for phrase in ("Management is replaceable", "Workload clusters remain",
                   "production-readiness"):
        if phrase not in article:
            raise SystemExit(f"CAPI blueprint status/principle missing: {phrase}")
    # Ensure Developer Workspace pages are generated and linked in the new nav.
    for workspace_path in (
        "developer-workspace/index.html",
        "developer-workspace/architecture/index.html",
        "developer-workspace/coding-agents/index.html",
        "developer-workspace/status/index.html",
        "developer-workspace/tutorial/index.html",
    ):
        if not (SITE / workspace_path).is_file():
            raise SystemExit(f"Missing Developer Workspace page: {workspace_path}")
    workspace_html = (SITE / "developer-workspace" / "index.html").read_text(encoding="utf-8")
    if "Developer Workspace" not in workspace_html or "OpenCode" not in workspace_html:
        raise SystemExit("Developer Workspace overview incomplete")
    parser = Refs()
    parser.feed(html)
    missing = []
    for href in parser.refs:
        href = href.split("#", 1)[0].split("?", 1)[0]
        if not href or href.startswith(("http:", "https:", "mailto:", "//", "data:")):
            continue
        if href.startswith("/"):
            # Only validate known legacy article URLs; other site routes are out of scope.
            if href.strip("/") in ARTICLES and not (SITE / href.strip("/") / "index.html").is_file():
                missing.append(href)
            continue
        path = (SITE / href).resolve()
        if not path.is_relative_to(SITE.resolve()) or not path.is_file():
            missing.append(href)
    for section in ("features", "architecture", "research", "blog", "community"):
        if not (SITE / section / "index.html").is_file():
            missing.append("/" + section + "/")
    for slug in ARTICLES:
        if not (SITE / slug / "index.html").is_file():
            missing.append("/" + slug + "/")
    for path in ("docs/index.html", "docs/ok-local/tutorial-prerequisites/index.html",
                 "docs/ok-cluster/registry-trust/index.html", "search/search_index.json"):
        if not (SITE / path).is_file():
            missing.append(path)
    for source in (ROOT / "docs").rglob("*"):
        if source.is_file():
            relative = source.relative_to(ROOT / "docs")
            if relative.as_posix() in ("CNAME", "index.html"):
                continue
            target = SITE / relative
            if not target.is_file() or target.read_bytes() != source.read_bytes():
                missing.append("/" + relative.as_posix())
    # Published vision article must contain the conceptual architecture diagram and source asset.
    vision_html = (SITE / "if-we-built-kubernetes-today" / "index.html").read_text(encoding="utf-8")
    diagram_rel = "media/human-governance-cmcp-mcp-architecture.svg"
    if "From Human Authority to Verifiable Execution" not in vision_html or diagram_rel not in vision_html:
        missing.append("vision article architecture diagram or caption")
    if not (SITE / diagram_rel).is_file():
        missing.append("/" + diagram_rel)
    if missing:
        raise SystemExit("Preview missing files/links: " + ", ".join(sorted(set(missing))))
    print(f"Homepage, media, {len(ARTICLES)} permalink articles, docs and search checks passed.")

if __name__ == "__main__":
    main()
