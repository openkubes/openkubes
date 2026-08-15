#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent
SPIKE=HERE.parent
RECORD=HERE/"m0a-v7-1-risk-acceptance-v1.yaml"
EXPECTED_SECURITY="sha256:41f3feebee02d625759bbaeba06dc8a0a2d10ef4345263e169fee01f02ec26d2"
class AcceptanceError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise AcceptanceError(f"{c}: expected {e!r}, got {a!r}")
def resolve(ref:dict[str,str])->Path:
    p=(RECORD.parent/ref["path"]).resolve()
    if SPIKE.resolve() not in p.parents or not p.is_file():raise AcceptanceError(f"invalid reference: {ref['path']}")
    expect(sha(p),ref["digest"],ref["path"]);return p
def verify()->dict[str,Any]:
    r=yaml.safe_load(RECORD.read_text())["spec"]
    expect(r["state"],"ACCEPTED-NON-AUTHORIZING","state")
    candidate=yaml.safe_load(resolve(r["references"]["acceptanceCandidate"]).read_text())["spec"]
    security=resolve(r["references"]["securityBoundary"])
    expect(sha(security),EXPECTED_SECURITY,"security")
    expect(r["decision"]["exactStatement"],candidate["acceptanceText"],"statement")
    expect(r["decision"]["acceptedRisks"],candidate["risks"],"risks")
    expect(r["authorization"],candidate["authorization"],"authorization")
    expect(r["authorization"]["mutationAuthorized"],False,"mutation")
    expect(r["authorization"]["evidencePublicationGranted"],False,"publication")
    return {"state":r["state"],"securityCandidateDigest":EXPECTED_SECURITY,"acceptedRisks":len(r["decision"]["acceptedRisks"]),"mutationAuthorized":False,"clusterContacted":False}
def main()->int:
    try:print(json.dumps(verify(),sort_keys=True,separators=(",",":")));return 0
    except (AcceptanceError,KeyError,OSError,TypeError,yaml.YAMLError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())

