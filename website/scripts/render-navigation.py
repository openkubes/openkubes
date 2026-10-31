#!/usr/bin/env python3
"""Preview-only shared OpenKubes navigation for the preserved legacy homepage.

Does not modify docs/index.html or any production files. Other pages use the
MkDocs Material navigation configured by mkdocs.yml.
"""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs" / "index.html"
OUTPUT = ROOT / ".mkdocs-site" / "index.html"
CSS = ROOT / "website" / "assets" / "openkubes-navigation.css"
WORDMARK = (ROOT / "website/overrides/partials/openkubes-wordmark.html").read_text(encoding="utf-8").strip()
NAV = [
    ("Home", "/"),
    ("Features", "/features/"),
    ("Architecture", "/architecture/"),
    ("Blog", "/blog/"),
    ("Docs", "/docs/"),
    ("Community", "/community/"),
]
def main():
    if not SOURCE.is_file() or not OUTPUT.is_file() or not CSS.is_file():
        raise SystemExit("Missing source, built homepage or navigation stylesheet")
    source = SOURCE.read_text(encoding="utf-8")
    current = OUTPUT.read_text(encoding="utf-8")
    if source != current:
        raise SystemExit("Homepage differs from source before navigation enhancement")
    if source.count("<body>") != 1 or source.count("</head>") != 1:
        raise SystemExit("Expected single HTML body/head insertion points")
    links = "".join(
        '<a href="' + escape(href, quote=True) + '"' +
        (' aria-current="page"' if href == "/" else "") + '>' +
        escape(title) + '</a>' for title, href in NAV
    )
    menu = (
        '<nav class="ok-global-nav" aria-label="OpenKubes primary navigation">'
        '<div class="ok-global-nav__inner">'
        '<a class="ok-global-nav__brand ok-global-nav__brand--text" href="/" aria-label="OpenKubes Home">' + WORDMARK + '</a>'
        '<div class="ok-global-nav__links">' + links + '</div></div></nav>'
    )
    html = source.replace(
        "</head>", '<link rel="stylesheet" href="/assets/openkubes-navigation.css">\n</head>', 1
    ).replace("<body>", "<body>\n" + menu, 1)
    # The source homepage now carries the approved Lite loader. Keep its
    # domain allowlist unchanged when adding preview-only navigation.
    lite_src = 'script.src = "/assets/ok-ai-lite-preview.js";'
    if source.count(lite_src) != 1 or html.count(lite_src) != 1:
        raise SystemExit("Expected one curated Lite loader in legacy homepage")
    if 'script.src = "/assets/ok-ai-floating-demo.js";' in html:
        raise SystemExit("Obsolete DEMO loader detected in homepage")
    OUTPUT.write_text(html, encoding="utf-8")
    print("Shared OpenKubes navigation injected into preview-only homepage")

if __name__ == "__main__":
    main()
