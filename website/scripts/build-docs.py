#!/usr/bin/env python3
"""Isolated OK-196 spike staging. Never modifies the existing docs/ site."""
from pathlib import Path
import os
import shutil
from byoh_guide import stage as stage_byoh

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / ".mkdocs-staging"
SOURCES = {
    "ok-local": ("docs/tutorial-prerequisites.md",),
}

def main():
    if STAGING.exists():
        shutil.rmtree(STAGING)
    (STAGING / "docs").mkdir(parents=True)
    (STAGING / "assets").mkdir()
    (STAGING / "docs" / "index.md").write_text(
        "# Developer Documentation\n\n"
        "Preview of source-owned docs from the OpenKubes repositories.\n\n"
        "- [Local prerequisites](ok-local/tutorial-prerequisites.md)\n",
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
    # Import the complete, pinned CAPI architecture tree as a read-only projection.
    # The ok-cluster repository remains the sole authoritative source.
    capi_source = workspace / "ok-cluster" / "docs" / "architecture" / "capi"
    capi_target = STAGING / "architecture" / "capi"
    required = (
        "blueprint.md",
        "decisions/ADR-CAPI-001-management-topologies.md",
        "decisions/ADR-CAPI-002-git-source-of-truth.md",
        "decisions/ADR-CAPI-003-ownership-fencing.md",
        "decisions/ADR-CAPI-004-disposable-bootstrap.md",
        "decisions/ADR-CAPI-005-git-velero-recovery.md",
        "decisions/ADR-CAPI-006-blue-green-handover.md",
        "decisions/ADR-CAPI-007-disaster-recovery.md",
        "diagrams/management-topologies.svg",
        "diagrams/bootstrap-pivot.svg",
        "diagrams/blue-green-handover.svg",
        "diagrams/disaster-recovery.svg",
    )
    for relative in required:
        src = capi_source / relative
        if not src.is_file():
            raise SystemExit(f"Missing pinned CAPI architecture source: {src}")
        if src.is_symlink():
            raise SystemExit(f"Refusing symlink in CAPI source: {src}")
        dst = capi_target / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    # Copy source README files only as MkDocs index pages: no duplicate URLs.
    for section, source in (
        (capi_target, capi_source / "README.md"),
        (capi_target / "decisions", capi_source / "decisions" / "README.md"),
    ):
        if not source.is_file() or source.is_symlink():
            raise SystemExit(f"Missing safe CAPI section index: {source}")
        section.mkdir(parents=True, exist_ok=True)
        index_text = source.read_text(encoding="utf-8").replace("../README.md", "../index.md")
        (section / "index.md").write_text(index_text, encoding="utf-8")
    print(f"Staged {len(required) + 2} pinned CAPI architecture source files.")
    stage_byoh(workspace, STAGING)
    with (STAGING / "docs/index.md").open("a", encoding="utf-8") as index:
        index.write("- [BYOH Advanced Guide](byoh/advanced-guide/index.md)\n")
    print(f"Ready: {STAGING}")

if __name__ == "__main__":
    main()
