#!/usr/bin/env python3
"""Add bind/escalate only for five exact Platform-owned ClusterRoles."""
from __future__ import annotations
import argparse,base64,copy,hashlib,json,os,subprocess
from pathlib import Path
import yaml

CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
MGMT=Path("/Users/arash/.kube/ok-mgmt.yaml")
ADMIN=Path("/private/tmp/ok141-exact-rbac-escalate-bind-admin.yaml")
EXPECTED_CLIENT="sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
EXPECTED_NAMES={"disposable-ok141-observability-core-kube-state-metrics","ok-observability-grafana-clusterrole","ok-observability-log-collector","ok-observability-operator","ok-observability-prometheus"}
def sha(path):return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
def get(config,uri):
 r=subprocess.run([str(CLIENT),"--kubeconfig",str(config),"get","--raw",uri],capture_output=True,check=False)
 if r.returncode:raise RuntimeError("exact GET failed")
 return json.loads(r.stdout)
def replace(config,uri,value):
 r=subprocess.run([str(CLIENT),"--kubeconfig",str(config),"replace","--raw",uri,"--filename","-"],input=json.dumps(value,sort_keys=True,separators=(",",":")).encode(),capture_output=True,check=False)
 if r.returncode:raise RuntimeError("exact replace failed")
 return json.loads(r.stdout)
def main():
 p=argparse.ArgumentParser();p.add_argument("--candidate",type=Path,required=True);a=p.parse_args();candidate=yaml.safe_load(a.candidate.read_text());spec=candidate["spec"]
 if spec["authorization"]!={"state":"GRANTED","source":"standing-dev-execution-envelope-v1","envelopeDigest":"sha256:85e997df331d2ced4ea147c32cc4a94a419e9efdba6de17d8a8ef3cb1dbeac93"}:raise RuntimeError("authorization mismatch")
 pred=Path(spec["predecessor"]["path"]); evidence=json.loads(pred.read_text())
 if sha(pred)!=spec["predecessor"]["digest"] or not evidence.get("failedClusterRoleSetExact") or not evidence.get("attemptToGrantPrivilegesNotHeld"):raise RuntimeError("predecessor mismatch")
 rule=spec["target"]["exactRule"]
 if set(rule["resourceNames"])!=EXPECTED_NAMES or rule["apiGroups"]!=["rbac.authorization.k8s.io"] or rule["resources"]!=["clusterroles"] or set(rule["verbs"])!={"bind","escalate"}:raise RuntimeError("exact rule mismatch")
 if sha(CLIENT)!=EXPECTED_CLIENT or MGMT.is_symlink() or (MGMT.stat().st_mode&0o777)!=0o600 or ADMIN.exists():raise RuntimeError("local identity precondition failed")
 output=Path(spec["outputPath"]); result={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1ExactRBACEscalateBindRemediationEvidence","candidateDigest":sha(a.candidate),"predecessorDigest":spec["predecessor"]["digest"],"exactResourceNameCount":5,"exactVerbs":["bind","escalate"],"wildcardAdded":False,"credentialPayloadRetained":False,"rawObjectsRetained":False,"automaticArgoReconciliationMayResume":True,"mutationPerformed":False,"retryPerformed":False,"rollbackOrCleanupPerformed":False,"platformObservationPerformed":False,"failureInjectionPerformed":False}
 try:
  secret=get(MGMT,spec["management"]["workloadKubeconfigSecretURI"]); raw=base64.b64decode(secret.get("data",{}).get("value",""),validate=True)
  if not raw:raise RuntimeError("empty workload kubeconfig")
  fd=os.open(ADMIN,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,"wb") as f:f.write(raw)
  current=get(ADMIN,spec["target"]["clusterRoleURI"]); meta=current.get("metadata",{});uid,rv=meta.get("uid"),meta.get("resourceVersion")
  if not uid or not rv:raise RuntimeError("target lacks concurrency identity")
  rules=current.get("rules") or []
  if any("*" in x.get("apiGroups",[])+x.get("resources",[])+x.get("verbs",[]) for x in rules):raise RuntimeError("pre-existing wildcard boundary")
  if rule in rules:raise RuntimeError("exact rule already present")
  replacement=copy.deepcopy(current); replacement["metadata"].pop("managedFields",None);replacement.setdefault("rules",[]).append(copy.deepcopy(rule))
  returned=replace(ADMIN,spec["target"]["clusterRoleURI"],replacement);new=returned.get("metadata",{})
  if new.get("uid")!=uid or new.get("resourceVersion")==rv or rule not in (returned.get("rules") or []):raise RuntimeError("replace postcondition failed")
  result.update({"mutationPerformed":True,"uidPreserved":True,"resourceVersionAdvanced":True,"exactRuleAdded":True,"state":"PASS-EXACT-RBAC-REMEDIATION"})
 finally:
  ADMIN.unlink(missing_ok=True);result["ephemeralAdminRemoved"]=not ADMIN.exists()
 fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(result,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({"state":result.get("state"),"exactRuleAdded":result.get("exactRuleAdded"),"evidenceDigest":sha(output)},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
