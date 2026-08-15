#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent
MANIFEST=HERE/"m0a-installer-rbac-v7-1.yaml"
class CredentialError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise CredentialError(f"{c}: expected {e!r}, got {a!r}")
def verify()->dict[str,Any]:
    docs=[x for x in yaml.safe_load_all(MANIFEST.read_text()) if x]
    expect([x["kind"] for x in docs],["ServiceAccount","Role","RoleBinding","ClusterRole","ClusterRoleBinding"],"objects")
    sa,role,rb,cr,crb=docs
    expect(sa["metadata"]["namespace"],"openkubes-system","SA namespace")
    expect(role["metadata"]["namespace"],"caaph-system","Role namespace")
    expect(rb["metadata"]["namespace"],"caaph-system","RoleBinding namespace")
    expect(rb["subjects"][0]["namespace"],"openkubes-system","cross-namespace subject")
    forbidden_verbs={"bind","escalate","patch","update","delete","list","watch"}
    forbidden_resources={"namespaces","roles","rolebindings","clusterroles","clusterrolebindings","secrets","serviceaccounts/token"}
    for obj in (role,cr):
        for rule in obj["rules"]:
            if forbidden_verbs & set(rule["verbs"]):raise CredentialError("forbidden installer verb")
            if forbidden_resources & set(rule["resources"]):raise CredentialError("forbidden installer resource")
            if set(rule["verbs"])-{"create","get"}:raise CredentialError("unexpected installer verb")
    return {"state":"OFFLINE-NO-GO","objects":5,"manifestDigest":sha(MANIFEST),"namespacedAuthority":"Role/caaph-system","clusterAuthority":"ClusterRole/exact-non-rbac-types","bindAllowed":False,"escalateAllowed":False,"mutationAuthorized":False,"clusterContacted":False}
def main()->int:
    try:print(json.dumps(verify(),sort_keys=True,separators=(",",":")));return 0
    except (CredentialError,KeyError,OSError,TypeError,yaml.YAMLError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())

