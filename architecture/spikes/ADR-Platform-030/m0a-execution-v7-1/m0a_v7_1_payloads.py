#!/usr/bin/env python3
"""Derive v7.1 authority payloads from the single reviewed 19-object source."""

from __future__ import annotations
import importlib.util,sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent
SPIKE=HERE.parent
PARTITION=SPIKE/"m0a-execution-v7"/"m0a-v7-authority-partition-v1.yaml"
SOURCE=SPIKE/"m0a-installation"/"caaph-v0.6.4-addon-components.yaml"
def _load(name:str,path:Path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m
    assert s.loader is not None;s.loader.exec_module(m);return m
V7=_load("ok141_v7_partition_for_payloads",SPIKE/"m0a-execution-v7"/"verify_m0a_v7_boundary.py")
@dataclass(frozen=True)
class Payload:
    documents:list[dict[str,Any]]
    raw:bytes
    semantic_digest:str
def render(documents:list[dict[str,Any]])->bytes:
    return yaml.safe_dump_all(documents,sort_keys=False,explicit_start=True).encode()
def derive()->dict[str,Payload]:
    V7.verify(PARTITION)
    spec=yaml.safe_load(PARTITION.read_text())["spec"]
    documents=[x for x in yaml.safe_load_all(SOURCE.read_text()) if x]
    by_key={V7.identity_key(V7.identity(x)):x for x in documents}
    result={}
    for domain in ("administrator","temporaryInstaller"):
        keys={V7.identity_key(x) for x in spec["authorityDomains"][domain]["identities"]}
        selected=[x for x in documents if V7.identity_key(V7.identity(x)) in keys]
        if set(V7.identity_key(V7.identity(x)) for x in selected)!=keys:raise V7.BoundaryError(f"incomplete {domain} projection")
        digest=V7.HARNESS.semantic_revision(selected)
        if digest!=spec["authorityDomains"][domain]["expectedSemanticDigest"]:raise V7.BoundaryError(f"{domain} semantic digest mismatch")
        result[domain]=Payload(selected,render(selected),digest)
    return result

