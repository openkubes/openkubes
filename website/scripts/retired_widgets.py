"""Reject the retired floating OK AI widgets in generated site artifacts."""
from pathlib import Path
import re


WIDGET_ASSETS = (
    "ok-ai-floating-demo.css",
    "ok-ai-floating-demo.js",
    "ok-ai-lite-preview.js",
)
WIDGET_IDS = (
    "okai-floating-demo",
    "okai-float-panel",
    "okai-floating-input",
)
# Match complete filenames and IDs, including in inline loaders and bundled code.
WIDGET_MARKER = re.compile(
    r"(?<![\w.-])(?:" + "|".join(map(re.escape, WIDGET_ASSETS)) + r")(?![\w.-])"
    r"|(?<![\w-])(?:" + "|".join(WIDGET_IDS) + r")(?![\w-])",
    re.IGNORECASE,
)


def check_retired_widgets(site: Path) -> None:
    for path in site.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(site)
        if path.name.lower() in WIDGET_ASSETS:
            raise SystemExit(f"Retired OK AI widget asset shipped: {relative}")
        if path.suffix.lower() in {".html", ".css", ".js", ".mjs"}:
            source = path.read_text(encoding="utf-8", errors="replace")
            if marker := WIDGET_MARKER.search(source):
                raise SystemExit(f"Retired OK AI widget marker {marker.group()} in {relative}")
