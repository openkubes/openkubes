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
        '<style>body{margin:0;color:#222;font:16px/1.6 system-ui,sans-serif}'
        'main{max-width:940px;margin:2rem auto;padding:0 1.25rem}'
        'pre{overflow:auto;padding:1rem;background:#f2f4f8}'
        'img{max-width:100%}article a{overflow-wrap:anywhere}</style>'
        "</head><body>"
        '<nav class="ok-global-nav" aria-label="OpenKubes primary navigation">'
        '<div class="ok-global-nav__inner">'
        '<a class="ok-global-nav__brand ok-global-nav__brand--text" href="/">OpenKubes</a>'
        f'<div class="ok-global-nav__links">{links}</div></div></nav>'
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
