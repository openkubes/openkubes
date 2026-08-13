#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent;CANDIDATE=HERE/"m0a-v7-1-execution-grant-candidate.yaml";EXECUTION=HERE/"m0a-execution-candidate-v7-1.yaml";PREFLIGHT=HERE/"m0a-v7-1-live-preflight-v1.yaml"
class GrantCandidateError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise GrantCandidateError(f"{c}: expected {e!r}, got {a!r}")
def verify()->dict[str,Any]:
    s=yaml.safe_load(CANDIDATE.read_text())["spec"]
    expect(s["state"],"AWAITING-FOUR-EXPLICIT-GRANTS","state");expect(s["executionCandidateDigest"],sha(EXECUTION),"execution candidate");expect(s["livePreflight"]["digest"],sha(PREFLIGHT),"preflight")
    grants=list(s["proposedGrants"].values());expect(len(grants),4,"grant count")
    if len({x["grantID"] for x in grants})!=4:raise GrantCandidateError("grant IDs not distinct")
    start=datetime.fromisoformat(s["proposedWindow"]["validFrom"].replace("Z","+00:00"));end=datetime.fromisoformat(s["proposedWindow"]["validUntil"].replace("Z","+00:00"))
    if start.tzinfo!=timezone.utc or end.tzinfo!=timezone.utc or end<=start or (end-start).total_seconds()!=10800:raise GrantCandidateError("window must be exact three-hour UTC interval")
    expect(s["rawEvidence"]["outputPath"],"/private/tmp/ok141-m0a-v7-1-execution-evidence-20260813.json","evidence path")
    expect(s["authorization"]["mutationAuthorized"],False,"mutation");expect(s["authorization"]["evidencePublicationGranted"],False,"publication")
    return {"state":s["state"],"grantCandidateDigest":sha(CANDIDATE),"grantDomains":4,"validFrom":s["proposedWindow"]["validFrom"],"validUntil":s["proposedWindow"]["validUntil"],"mutationAuthorized":False}
def main()->int:
    try:print(json.dumps(verify(),sort_keys=True,separators=(",",":")));return 0
    except (GrantCandidateError,KeyError,OSError,TypeError,ValueError,yaml.YAMLError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
