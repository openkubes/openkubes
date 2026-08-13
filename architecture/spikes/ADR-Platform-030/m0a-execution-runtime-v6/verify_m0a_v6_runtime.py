#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib
from pathlib import Path
from typing import Any
import yaml
class VerificationError(ValueError): pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise VerificationError(f"{c}: expected {e!r}, got {a!r}")
def verify(path:Path)->str:
    s=yaml.safe_load(path.read_text())["spec"]
    expect(s["state"],"BASELINE-RESTORED","state")
    expect(s["execution"]["result"],"STOP-NOT-SUCCESS","execution")
    expect(s["execution"]["runsConsumed"],1,"execution runs")
    expect(s["execution"]["tokenRejection"]["result"],"PROVEN","token rejection")
    expect(s["execution"]["submission"]["objectsCreated"],4,"partial objects")
    expect(s["rollback"]["result"],"SUCCESS","rollback")
    expect(s["rollback"]["runsConsumed"],1,"rollback runs")
    expect(s["rollback"]["exactObjectsDeleted"],4,"deleted")
    expect(s["postRollbackPreflight"]["exactIdentityAbsence"],19,"absence")
    expect(s["postRollbackPreflight"]["lifecycleInventory"],{"clusters":0,"machines":0,"machineDeployments":0},"lifecycle")
    for k,v in s["authorization"].items():expect(v,False,k)
    for k,v in s["redaction"].items():expect(v,False,k)
    return sha(path)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("--evidence",type=Path,required=True);a=p.parse_args()
    try:print(verify(a.evidence.resolve()));return 0
    except (OSError,KeyError,TypeError,ValueError,VerificationError,yaml.YAMLError) as x:print(f"ERROR: {x}");return 2
if __name__=="__main__":raise SystemExit(main())
