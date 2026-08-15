#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
from typing import Any
import yaml

class VerificationError(ValueError): pass
def sha(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def expect(actual:Any,expected:Any,claim:str)->None:
    if actual!=expected:raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")
def verify(path:Path)->str:
    s=yaml.safe_load(path.read_text())["spec"]
    expect(s["state"],"PARTIAL-STATE-RETAINED","state")
    expect(s["execution"]["result"],"STOP-NOT-SUCCESS","execution")
    expect(s["execution"]["runsConsumed"],1,"runs")
    expect(s["submission"]["reviewedObjectsPresent"],19,"objects")
    expect(s["submission"]["temporaryBootstrapObjectsRemoved"],7,"cleanup")
    expect(s["submission"]["tokenRejection"]["result"],"PROVEN","token rejection")
    expect(s["readiness"]["cause"],"LITERAL-PROVIDER-VARIABLE-SYNTAX-IN-CONTAINER-ARGS","cause")
    expect(s["retainedState"]["caaphObjectCount"],19,"retained objects")
    expect(s["retainedState"]["capiLifecycleObjects"],0,"lifecycle")
    for k,v in s["authorization"].items():expect(v,False,k)
    for k,v in s["redaction"].items():expect(v,False,k)
    return sha(path)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--evidence",type=Path,required=True);a=p.parse_args()
    try:print(verify(a.evidence.resolve()));return 0
    except (OSError,KeyError,TypeError,ValueError,VerificationError,yaml.YAMLError) as x:print(f"ERROR: {x}");return 2
if __name__=="__main__":raise SystemExit(main())
