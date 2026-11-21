#!/usr/bin/env python3
"""Isolated OK-196 spike staging. Never modifies the existing docs/ site."""
from pathlib import Path
import os
import shutil

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / ".mkdocs-staging"
SOURCES = {
    "ok-local": ("docs/tutorial-prerequisites.md",),
    "ok-cluster": ("docs/registry-trust.md",),
}

def main():
    if STAGING.exists():
        shutil.rmtree(STAGING)
    (STAGING / "docs").mkdir(parents=True)
    (STAGING / "assets").mkdir()
    (STAGING / "docs" / "index.md").write_text(
        "# Developer Documentation\n\n"
        "Preview of source-owned docs from the OpenKubes repositories.\n\n"
        "- [Local prerequisites](ok-local/tutorial-prerequisites.md)\n"
        "- [Cluster registry trust](ok-cluster/registry-trust.md)\n",
        encoding="utf-8",
    )
    (STAGING / "index.md").write_text(
        "# OpenKubes MkDocs spike preview\n\n"
        "**This is not the production homepage.** "
        "The current site and its URLs remain unchanged throughout OK-196.\n\n"
        "[Developer documentation](docs/index.md)\n",
        encoding="utf-8",
    )
    logo = ROOT / "docs" / "openkubes-logo.png"
    if not logo.is_file():
        raise SystemExit(f"Missing branding asset: {logo}")
    shutil.copy2(logo, STAGING / "assets" / logo.name)
    workspace = Path(os.environ.get("OK196_SOURCES", str(ROOT / ".ok196-sources")))
    for name, filenames in SOURCES.items():
        source = workspace / name
        target = STAGING / "docs" / name
        target.mkdir(parents=True)
        for relative in filenames:
            src = source / relative
            if not src.is_file():
                raise SystemExit(f"Missing source documentation: {src}")
            shutil.copy2(src, target / Path(relative).name)
            print(f"Staged {name}/{relative}")
    print(f"Ready: {STAGING}")

if __name__ == "__main__":
    main()
