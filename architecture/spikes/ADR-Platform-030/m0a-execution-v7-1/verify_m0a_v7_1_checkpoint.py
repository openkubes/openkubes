#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent;SPIKE=HERE.parent;CHECKPOINT=HERE/"m0a-v7-1-candidate-checkpoint.yaml"
class CheckpointError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise CheckpointError(f"{c}: expected {e!r}, got {a!r}")
def verify()->dict[str,Any]:
    s=yaml.safe_load(CHECKPOINT.read_text())["spec"]
    refs={
      "authorityPartition":SPIKE/"m0a-execution-v7"/"m0a-v7-authority-partition-v1.yaml",
      "v7Security":SPIKE/"m0a-execution-v7"/"m0a-v7-security-boundary.yaml",
      "v7Acceptance":SPIKE/"m0a-v7-risk-acceptance"/"m0a-v7-risk-acceptance-v1.yaml",
      "invalidation":HERE/"m0a-v7-execution-invalidation-v1.yaml",
      "v71Security":HERE/"m0a-v7-1-security-boundary.yaml",
      "v71Acceptance":SPIKE/"m0a-v7-1-risk-acceptance"/"m0a-v7-1-risk-acceptance-v1.yaml",
      "admission":HERE/"m0a-installer-admission-v7-1.yaml","credential":HERE/"m0a-installer-rbac-v7-1.yaml",
      "candidate":HERE/"m0a-execution-candidate-v7-1.yaml","preflight":HERE/"m0a-v7-1-live-preflight-v1.yaml"}
    claims=[s["historicalV7"]["authorityPartition"],s["historicalV7"]["securityCandidate"],s["historicalV7"]["acceptedRiskRecord"],s["historicalV7"]["executionInvalidation"],s["correctedV71"]["securityCandidate"],s["correctedV71"]["acceptedRiskRecord"],s["correctedV71"]["admissionManifest"],s["correctedV71"]["credentialManifest"],s["correctedV71"]["executionCandidate"],s["correctedV71"]["livePreflight"]]
    expect(claims,[sha(x) for x in refs.values()],"evidence chain")
    expect(s["proofs"]["testsPassed"],11,"tests");expect(s["authorization"]["mutationAuthorized"],False,"mutation");expect(s["authorization"]["publicationGranted"],False,"publication")
    return {"state":s["state"],"checkpointDigest":sha(CHECKPOINT),"references":len(refs),"testsPassed":11,"mutationAuthorized":False,"publicationGranted":False}
def main()->int:
    try:print(json.dumps(verify(),sort_keys=True,separators=(",",":")));return 0
    except (CheckpointError,KeyError,OSError,TypeError,yaml.YAMLError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
