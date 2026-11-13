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
        '<div class="ok-global-nav__links">' + links + "</div><div class=\"ok-global-nav__socials\"><a class=\"ok-global-nav__github\" href=\"https://github.com/orgs/openkubes/repositories\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"OpenKubes GitHub repositories\" title=\"All OpenKubes repositories\"><svg viewBox=\"0 0 24 24\" width=\"19\" height=\"19\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M12 .75a11.25 11.25 0 0 0-3.558 21.925c.563.105.77-.245.77-.544 0-.27-.01-1.155-.016-2.096-3.132.68-3.793-1.328-3.793-1.328-.512-1.3-1.25-1.645-1.25-1.645-1.022-.7.078-.685.078-.685 1.13.08 1.726 1.16 1.726 1.16 1.005 1.722 2.637 1.224 3.281.936.101-.727.393-1.224.715-1.505-2.5-.284-5.128-1.25-5.128-5.56 0-1.229.439-2.234 1.16-3.021-.116-.284-.502-1.428.11-2.98 0 0 .945-.303 3.095 1.154A10.76 10.76 0 0 1 12 6.174c.96.005 1.926.13 2.83.38 2.149-1.457 3.092-1.154 3.092-1.154.614 1.552.228 2.696.112 2.98.722.787 1.158 1.792 1.158 3.02 0 4.322-2.632 5.274-5.14 5.553.403.35.762 1.036.762 2.089 0 1.51-.014 2.727-.014 3.09 0 .302.204.655.775.544A11.252 11.252 0 0 0 12 .75Z\"/></svg></a><a class=\"ok-global-nav__slack\" href=\"https://slack.kubernauts.io\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"Join OpenKubes on Slack\" title=\"Join us on Slack\"><svg viewBox=\"0 0 24 24\" width=\"20\" height=\"20\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M5.2 15.1a2.1 2.1 0 1 1-2.1-2.1h2.1v2.1Zm1.05 0a2.1 2.1 0 1 1 4.2 0v5.25a2.1 2.1 0 1 1-4.2 0V15.1Zm2.1-8.35a2.1 2.1 0 1 1 2.1-2.1v2.1h-2.1Zm0 1.05a2.1 2.1 0 1 1 0 4.2H3.1a2.1 2.1 0 1 1 0-4.2h5.25Zm8.35 2.1a2.1 2.1 0 1 1 2.1 2.1h-2.1V9.9Zm-1.05 0a2.1 2.1 0 1 1-4.2 0V4.65a2.1 2.1 0 1 1 4.2 0V9.9Zm-2.1 8.35a2.1 2.1 0 1 1-2.1 2.1v-2.1h2.1Zm0-1.05a2.1 2.1 0 1 1 0-4.2h5.25a2.1 2.1 0 1 1 0 4.2h-5.25Z\"/></svg></a><a class=\"ok-global-nav__x\" href=\"https://x.com/kubernauts\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"Kubernauts on X\" title=\"Follow Kubernauts on X\"><svg viewBox=\"0 0 24 24\" width=\"20\" height=\"20\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M18.9 2H22l-6.78 7.75L23.2 22h-6.25l-4.9-7.43L5.54 22H2.4l7.25-8.29L1.98 2h6.4l4.43 6.78L18.9 2Zm-1.1 18h1.73L7.45 3.9H5.58L17.8 20Z\"/></svg></a></div></div></nav>"

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
