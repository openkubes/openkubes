#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent
EVIDENCE=HERE/"m0a-v7-1-live-preflight-v1.yaml";CANDIDATE=HERE/"m0a-execution-candidate-v7-1.yaml"
class PreflightError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise PreflightError(f"{c}: expected {e!r}, got {a!r}")
def verify()->dict[str,Any]:
    s=yaml.safe_load(EVIDENCE.read_text())["spec"]
    expect(s["state"],"PASS-READ-ONLY","state");expect(s["candidateDigest"],sha(CANDIDATE),"candidate")
    expect(s["target"]["kubeSystemNamespaceUID"],"c3b45aab-d2a1-4e64-8f12-77b99186ad4a","target")
    expect(s["target"]["bootstrapIdentity"],{"username":"kubernetes-admin","group":"system:masters"},"authority")
    expect((s["source"]["exactIdentityAbsence"],s["source"]["v71BootstrapAbsence"]),(19,7),"absence")
    expect(s["lifecycleInventory"],{"clusters":0,"machines":0,"machineDeployments":0},"lifecycle")
    expect(s["mutationPerformed"],False,"mutation")
    for k,v in s["authorization"].items():
        if k=="decision":expect(v,"NO-GO",k)
        else:expect(v,False,k)
    return {"state":s["state"],"candidateDigest":s["candidateDigest"],"exactIdentityAbsence":19,"bootstrapAbsence":7,"mutationPerformed":False,"clusterContacted":True}
def main()->int:
    try:print(json.dumps(verify(),sort_keys=True,separators=(",",":")));return 0
    except (PreflightError,KeyError,OSError,TypeError,yaml.YAMLError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())

