#!/usr/bin/env python3
"""Classify the bound core Application's RBAC failure without retaining messages."""
from __future__ import annotations
import hashlib,json,os,re,subprocess
from pathlib import Path

CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
KUBECONFIG=Path("/Users/arash/.kube/ok-shared.yaml")
OUTPUT=Path("/private/tmp/ok141-rbac-escalation-cause-diagnostic-v1-evidence.json")
URI="/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/disposable-ok141-observability-core"
EXPECTED={"disposable-ok141-observability-core-kube-state-metrics","ok-observability-grafana-clusterrole","ok-observability-log-collector","ok-observability-operator","ok-observability-prometheus"}
def sha_bytes(v):return "sha256:"+hashlib.sha256(v).hexdigest()
def main():
 r=subprocess.run([str(CLIENT),"--kubeconfig",str(KUBECONFIG),"get","--raw",URI],capture_output=True,check=False)
 if r.returncode: raise RuntimeError("exact Application GET failed")
 value=json.loads(r.stdout);messages=[];failed=set()
 for item in value.get("status",{}).get("conditions") or []: messages.append(item.get("message", ""))
 for item in value.get("status",{}).get("operationState",{}).get("syncResult",{}).get("resources") or []:
  msg=item.get("message","");messages.append(msg)
  if item.get("kind")=="ClusterRole" and item.get("status")=="SyncFailed": failed.add(item.get("name"))
 joined="\n".join(messages).lower()
 evidence={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1RBACEscalationCauseDiagnosticEvidence","exactApplicationReads":1,"failedClusterRoleNames":sorted(failed),"failedClusterRoleSetExact":failed==EXPECTED,"attemptToGrantPrivilegesNotHeld":("attempting to grant rbac permissions not currently held" in joined or "attempt to grant extra privileges" in joined),"explicitEscalateIndicator":"escalat" in joined,"explicitBindIndicator":(" bind " in f" {joined} " or "cannot bind" in joined),"cannotCreateClusterRoleIndicator":("cannot create resource \"clusterroles\"" in joined),"messageSetDigest":sha_bytes("\n".join(sorted(messages)).encode()),"rawMessagesRetained":False,"rawObjectRetained":False,"secretOrTargetReadPerformed":False,"mutationPerformed":False,"retryPerformed":False,"cleanupPerformed":False,"failureInjectionPerformed":False}
 fd=os.open(OUTPUT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(evidence,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({k:evidence[k] for k in ("failedClusterRoleNames","failedClusterRoleSetExact","attemptToGrantPrivilegesNotHeld","explicitEscalateIndicator","explicitBindIndicator","cannotCreateClusterRoleIndicator")},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
