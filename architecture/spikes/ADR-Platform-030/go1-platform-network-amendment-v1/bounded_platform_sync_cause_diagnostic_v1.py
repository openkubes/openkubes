#!/usr/bin/env python3
"""Classify three exact Argo Application statuses without retaining messages."""

from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess
from pathlib import Path
import yaml

CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
KUBECONFIG=Path("/Users/arash/.kube/ok-shared.yaml")

def sha(path): return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
def text_digest(value): return "sha256:"+hashlib.sha256(value.encode()).hexdigest()
def classify(message):
    lower=message.lower()
    if "not managed" in lower: return "NAMESPACE-NOT-MANAGED"
    if "forbidden" in lower or "cannot " in lower: return "AUTHORIZATION"
    if "not found" in lower or "could not find" in lower: return "DEPENDENCY-NOT-FOUND"
    if "failed to apply" in lower or "sync task" in lower: return "APPLY-FAILURE"
    if "shared resource warning" in lower or "orphaned" in lower: return "OWNERSHIP-WARNING"
    if "comparisonerror" in lower: return "COMPARISON"
    return "OTHER"
def namespace_category(value):
    if value=="ok-observability": return "OK-OBSERVABILITY"
    if value=="kube-system": return "KUBE-SYSTEM"
    if not value: return "CLUSTER-SCOPED"
    return "OTHER"
def exact_get(name):
    uri=f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{name}"
    r=subprocess.run([str(CLIENT),"--kubeconfig",str(KUBECONFIG),"get","--raw",uri],capture_output=True,check=False)
    if r.returncode: raise RuntimeError("exact Application GET failed")
    return json.loads(r.stdout)
def main():
    p=argparse.ArgumentParser();p.add_argument("--candidate",type=Path,required=True);a=p.parse_args();c=yaml.safe_load(a.candidate.read_text());s=c["spec"]
    if s["authorization"]["state"]!="GRANTED": raise RuntimeError("not granted")
    if sha(s["predecessor"]["path"])!=s["predecessor"]["digest"]: raise RuntimeError("predecessor mismatch")
    apps=[]
    for name in s["applications"]:
        value=exact_get(name); conditions=[]
        for item in value.get("status",{}).get("conditions") or []:
            msg=item.get("message","")
            conditions.append({"type":item.get("type"),"cause":classify(msg),"messageDigest":text_digest(msg)})
        resources=[]
        sync_result=value.get("status",{}).get("operationState",{}).get("syncResult",{})
        for item in sync_result.get("resources") or []:
            msg=item.get("message","")
            if item.get("status") not in (None,"Synced") or msg:
                resources.append({"group":item.get("group") or "core","kind":item.get("kind"),"namespaceCategory":namespace_category(item.get("namespace")),"name":item.get("name"),"status":item.get("status"),"hookPhase":item.get("hookPhase"),"cause":classify(msg),"messageDigest":text_digest(msg)})
        apps.append({"name":name,"conditions":conditions,"syncResources":resources})
    evidence={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1PlatformSyncCauseDiagnosticEvidence","candidateDigest":sha(a.candidate),"predecessorDigest":s["predecessor"]["digest"],"applications":apps,"exactApplicationReads":len(apps),"rawMessagesRetained":False,"rawObjectsRetained":False,"secretOrTargetReadPerformed":False,"mutationPerformed":False,"retryPerformed":False,"cleanupPerformed":False,"failureInjectionPerformed":False}
    output=Path(s["outputPath"]); fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f: json.dump(evidence,f,sort_keys=True,separators=(",",":"));f.write("\n")
    print(json.dumps({"evidenceDigest":sha(output),"applications":[{"name":x["name"],"conditionCauses":[y["cause"] for y in x["conditions"]],"failedResources":len(x["syncResources"])} for x in apps]},sort_keys=True));return 0
if __name__=="__main__": raise SystemExit(main())
