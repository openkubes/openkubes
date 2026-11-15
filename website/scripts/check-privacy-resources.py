#!/usr/bin/env python3
"""Fail the static website build on known third-party autoload and marketing endpoints.

This is a deterministic static guard, NOT a replacement for browser HAR and storage QA.
Outbound hyperlinks remain allowed: a visitor may explicitly navigate to third-party sites.
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / ".mkdocs-site"

FORBIDDEN_HOSTS = (
    "googletagmanager.com",
    "google-analytics.com",
    "googleadservices.com",
    "doubleclick.net",
    "googlesyndication.com",
    "snap.licdn.com",
    "px.ads.linkedin.com",
    "analytics.google.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "i.ytimg.com",
    "img.youtube.com",
)

CSS_URL = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.I)
CSS_IMPORT = re.compile(r"@import\s+(?:url\()?\s*['\"]([^'\"]+)", re.I)
JS_ENDPOINT = re.compile(
    r"""(?:(?:https?:)?//)(?:[^\s"'<>\\)]+)""", re.I
)


def forbidden(url: str) -> bool:
    value = url.strip()
    if value.startswith("//"):
        value = "https:" + value
    if not value.startswith(("https://", "http://")):
        return False
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except ValueError:
        # Regex-based discovery may encounter JS comments or literal `//[` fragments.
        # They are not valid resource URLs; never crash the entire site build.
        return False
    return any(host == domain or host.endswith("." + domain) for domain in FORBIDDEN_HOSTS)


def css_urls(css: str):
    for pattern in (CSS_URL, CSS_IMPORT):
        for match in pattern.finditer(css):
            yield match.group(1)


class ResourceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[str, str]] = []
        self._in_style = False
        self._style: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        tag = tag.lower()
        if tag == "style":
            self._in_style = True
        for key in ("src", "poster", "data"):
            if key in values and tag in {"script", "img", "iframe", "video", "audio", "source", "embed", "object"}:
                self.urls.append((f"{tag}.{key}", values[key] or ""))
        if tag == "link":
            rel = (values.get("rel") or "").lower()
            if any(token in rel.split() for token in ("stylesheet", "preload", "modulepreload", "prefetch", "preconnect", "dns-prefetch")):
                self.urls.append(("link.href", values.get("href") or ""))
        for url in css_urls(values.get("style") or ""):
            self.urls.append(("inline-style", url))
        if "srcset" in values:
            for entry in (values["srcset"] or "").split(","):
                self.urls.append(("srcset", entry.strip().split()[0] if entry.strip() else ""))

    def handle_endtag(self, tag):
        if tag.lower() == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            for url in css_urls(data):
                self.urls.append(("style", url))


def inspect_file(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    content = path.read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    if suffix == ".html":
        parser = ResourceParser()
        parser.feed(content)
        for kind, url in parser.urls:
            if forbidden(url):
                failures.append(f"{path}: {kind} autoloads {url}")
        # Check script bodies for known advertising endpoints (including dynamic injection).
        for url in JS_ENDPOINT.findall(content):
            if forbidden(url):
                failures.append(f"{path}: script/content references blocked endpoint {url}")
    elif suffix == ".css":
        for url in css_urls(content):
            if forbidden(url):
                failures.append(f"{path}: CSS autoloads {url}")
    elif suffix == ".js":
        for url in JS_ENDPOINT.findall(content):
            if forbidden(url):
                failures.append(f"{path}: JS references blocked endpoint {url}")
    return failures


def scan(site: Path) -> list[str]:
    if not site.is_dir():
        return [f"Missing built site: {site}"]
    files = sorted(p for p in site.rglob("*") if p.is_file() and p.suffix.lower() in (".html", ".css", ".js"))
    if not files:
        return [f"No generated HTML/CSS/JS found in {site}"]
    failures: list[str] = []
    for path in files:
        failures.extend(inspect_file(path))
    return failures


def main() -> int:
    failures = scan(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE)
    if failures:
        for failure in failures:
            print("PRIVACY BLOCK:", failure, file=sys.stderr)
        return 1
    print("Static privacy resource guard passed (browser/network QA still required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
