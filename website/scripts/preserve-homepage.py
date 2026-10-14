#!/usr/bin/env python3
"""Keep production homepage HTML byte-identical in isolated MkDocs preview output.

MkDocs renders a temporary index.md for the build. In the preview output only,
replace it with the exact existing index.html. Never touch docs/index.html.
"""
from pathlib import Path
import shutil
ROOT = Path(__file__).resolve().parents[2]
source = ROOT / "docs" / "index.html"
output = ROOT / ".mkdocs-site" / "index.html"
if not output.is_file() or not source.is_file():
    raise SystemExit("MkDocs output or existing homepage is missing.")
shutil.copy2(source, output)
if source.read_bytes() != output.read_bytes():
    raise SystemExit("Homepage preview differs from existing HTML.")
print("Existing homepage preserved byte-for-byte in preview artifact.")
