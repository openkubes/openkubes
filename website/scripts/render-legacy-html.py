#!/usr/bin/env python3
"""Render legacy Jekyll-style .html article URLs for the Cloudflare build.

The original GitHub Pages site served docs/*.md under corresponding *.html
paths. MkDocs serves selected documents under pretty URLs instead. Preserve
both URL forms as real HTML pages, including older articles not in MkDocs nav.
Do not overwrite MkDocs output or touch docs/ sources.
"""
from html import escape
from pathlib import Path
import markdown

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "docs"
SITE = ROOT / ".mkdocs-site"
WORDMARK = (ROOT / "website/overrides/partials/openkubes-wordmark.html").read_text(encoding="utf-8").strip()
NAV = (("Home", "/"), ("Features", "/features/"), ("Architecture", "/architecture/"),
       ("Blog", "/blog/"), ("Docs", "/docs/"), ("Community", "/community/"))

def render(source):
    title = source.stem.replace("-", " ").replace("_", " ").strip()
    body = markdown.markdown(source.read_text(encoding="utf-8"),
                             extensions=["fenced_code", "tables", "toc"])
    links = " ".join(f'<a href="{url}">{escape(name)}</a>' for name, url in NAV)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)} | OpenKubes</title>"
        '<link rel="stylesheet" href="/assets/openkubes-navigation.css">'
        '<link rel="stylesheet" href="/assets/openkubes-branding.css">'
        '<link rel="icon" type="image/svg+xml" href="/openkubes-cube-v2.svg">'
        '<style>body{margin:0;color:#222;font:16px/1.6 system-ui,sans-serif}'
        'main{max-width:940px;margin:2rem auto;padding:0 1.25rem}'
        'pre{overflow:auto;padding:1rem;background:#f2f4f8}'
        'img{max-width:100%}article a{overflow-wrap:anywhere}</style>'
        "</head><body>"
        '<nav class="ok-global-nav" aria-label="OpenKubes primary navigation">'
        '<div class="ok-global-nav__inner">'
        '<a class="ok-global-nav__brand ok-global-nav__brand--text" href="/" aria-label="OpenKubes Home">' + WORDMARK + '</a>'
        f'<div class="ok-global-nav__links">{links}</div>'
        "<div class=\\"ok-global-nav__socials\\"><a class=\"ok-global-nav__github\" href=\"https://github.com/orgs/openkubes/repositories\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"OpenKubes GitHub repositories\" title=\"All OpenKubes repositories\"><svg viewBox=\"0 0 24 24\" width=\"19\" height=\"19\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M12 .75a11.25 11.25 0 0 0-3.558 21.925c.563.105.77-.245.77-.544 0-.27-.01-1.155-.016-2.096-3.132.68-3.793-1.328-3.793-1.328-.512-1.3-1.25-1.645-1.25-1.645-1.022-.7.078-.685.078-.685 1.13.08 1.726 1.16 1.726 1.16 1.005 1.722 2.637 1.224 3.281.936.101-.727.393-1.224.715-1.505-2.5-.284-5.128-1.25-5.128-5.56 0-1.229.439-2.234 1.16-3.021-.116-.284-.502-1.428.11-2.98 0 0 .945-.303 3.095 1.154A10.76 10.76 0 0 1 12 6.174c.96.005 1.926.13 2.83.38 2.149-1.457 3.092-1.154 3.092-1.154.614 1.552.228 2.696.112 2.98.722.787 1.158 1.792 1.158 3.02 0 4.322-2.632 5.274-5.14 5.553.403.35.762 1.036.762 2.089 0 1.51-.014 2.727-.014 3.09 0 .302.204.655.775.544A11.252 11.252 0 0 0 12 .75Z\"/></svg></a><a class=\"ok-global-nav__slack\" href=\"https://slack.kubernauts.io\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"Join OpenKubes on Slack\" title=\"Join us on Slack\"><svg viewBox=\"0 0 24 24\" width=\"20\" height=\"20\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M5.2 15.1a2.1 2.1 0 1 1-2.1-2.1h2.1v2.1Zm1.05 0a2.1 2.1 0 1 1 4.2 0v5.25a2.1 2.1 0 1 1-4.2 0V15.1Zm2.1-8.35a2.1 2.1 0 1 1 2.1-2.1v2.1h-2.1Zm0 1.05a2.1 2.1 0 1 1 0 4.2H3.1a2.1 2.1 0 1 1 0-4.2h5.25Zm8.35 2.1a2.1 2.1 0 1 1 2.1 2.1h-2.1V9.9Zm-1.05 0a2.1 2.1 0 1 1-4.2 0V4.65a2.1 2.1 0 1 1 4.2 0V9.9Zm-2.1 8.35a2.1 2.1 0 1 1-2.1 2.1v-2.1h2.1Zm0-1.05a2.1 2.1 0 1 1 0-4.2h5.25a2.1 2.1 0 1 1 0 4.2h-5.25Z\"/></svg></a><a class=\"ok-global-nav__x\" href=\"https://x.com/kubernauts\" target=\"_blank\" rel=\"noopener noreferrer\" aria-label=\"Kubernauts on X\" title=\"Follow Kubernauts on X\"><svg viewBox=\"0 0 24 24\" width=\"20\" height=\"20\" aria-hidden=\"true\" focusable=\"false\" fill=\"currentColor\"><path d=\"M18.9 2H22l-6.78 7.75L23.2 22h-6.25l-4.9-7.43L5.54 22H2.4l7.25-8.29L1.98 2h6.4l4.43 6.78L18.9 2Zm-1.1 18h1.73L7.45 3.9H5.58L17.8 20Z\"/></svg></a></div></div></nav>"
        f'<main><article>{body}</article></main></body></html>\n'
    )

def main():
    if not SITE.is_dir():
        raise SystemExit("Run the MkDocs build before rendering compatibility HTML")
    created = 0
    for source in sorted(SOURCE.rglob("*.md")):
        relative = source.relative_to(SOURCE).with_suffix(".html")
        destination = SITE / relative
        if destination.exists():
            # A MkDocs-generated file has priority. Never overwrite it.
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render(source), encoding="utf-8")
        created += 1
    print(f"Rendered {created} legacy Jekyll-style HTML compatibility pages")

if __name__ == "__main__":
    main()
