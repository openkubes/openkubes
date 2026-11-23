#!/usr/bin/env python3
# Copyright 2026 The OpenKubes Authors.
# SPDX-License-Identifier: Apache-2.0
"""Provider-neutrality check of the tracked files of a repository.

OpenKubes runs on bare metal, virtual machines and supported clouds; no
infrastructure provider is a default or a requirement. This check fails on
provider-specific names, domains, regions, instance types, lab addresses and
lab host names, except in

  - files listed in the allowlist (hack/provider-neutrality-allowlist.txt):
    one glob per line, followed by "# reason" (a reason is required), for
    labeled lab records, historical evidence and provider-specific adapters;
  - lines that carry the marker "provider-neutrality: allow" (with a reason),
    for a single labeled reference in otherwise generic documentation.

An allowlist entry that matches no tracked file is an error, so that stale
exceptions are removed.

Usage: check-provider-neutrality.py [--root DIR] [--allowlist FILE]
"""
import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    r"scaleway",
    r"\bscw[0-9]*\b",
    r"\bscw[-_.]",
    r"\b(?:fr-par|nl-ams|pl-waw)(?:-[0-9])?\b",
    r"\bDEV1-(?:S|M|L|XL)\b",
    r"\b(?:GP1|PLAY2|PRO2|POP2)-[A-Z0-9]+\b",
    r"elastic[ -]metal",
    r"\bEM-[A-Z][0-9]",
    r"\bstardust[0-9]",
    r"\b51\.15[0-9]\.[0-9]{1,3}\.[0-9]{1,3}\b",
    r"\bok-bm-lab-[0-9]",
    r"bunnycdn",
]
PROVIDER = re.compile("|".join(PATTERNS), re.IGNORECASE)
MARKER = "provider-neutrality: allow"


def load_allowlist(path):
    entries = []
    for number, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        glob, sep, reason = line.partition("#")
        if not sep or not reason.strip():
            raise SystemExit(f"{path}:{number}: an exception needs a reason ('<glob>  # <reason>')")
        entries.append((glob.strip(), number))
    return entries


def tracked_files(root):
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True).stdout
    return [f for f in out.decode().split("\0") if f]


def scan(root, files, allowlist, skip=()):
    findings, used = [], set()
    for name in files:
        if name in skip:
            continue
        allowed = [n for glob, n in allowlist if fnmatch.fnmatchcase(name, glob)]
        if allowed:
            used.update(allowed)
            continue
        try:
            text = (root / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            match = PROVIDER.search(line)
            if match and MARKER not in line:
                findings.append(f"{name}:{number}: '{match.group(0)}': {line.strip()[:160]}")
    stale = [f"allowlist line {n}: '{glob}' matches no tracked file" for glob, n in allowlist if n not in used]
    return findings, stale


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--allowlist", default="hack/provider-neutrality-allowlist.txt")
    args = parser.parse_args(argv)
    root = Path(args.root)
    # The allowlist names the excepted paths, so it is never scanned itself.
    findings, stale = scan(root, tracked_files(root), load_allowlist(root / args.allowlist), skip={args.allowlist})
    for line in findings + stale:
        print(line)
    if findings or stale:
        print(f"FAIL: {len(findings)} provider-specific references outside the documented exceptions, "
              f"{len(stale)} stale exceptions. Generalize them, move lab material to a labeled lab location, "
              f"or document an exception (hack/provider-neutrality-allowlist.txt or '{MARKER} (<reason>)').")
        return 1
    print("PASS: no provider-specific references outside the documented exceptions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
