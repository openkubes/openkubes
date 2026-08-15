#!/usr/bin/env python3
"""Create exactly five immutable-render-derived ClusterRole prerequisites."""
from __future__ import annotations
import base64,hashlib,json,os,subprocess
from pathlib import Path
import yaml
HERE=Path(__file__).resolve().parent;CANDIDATE=HERE/"exact-clusterrole-prerequisites-v1.yaml"
CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64");MGMT=Path("/Users/arash/.kube/ok-mgmt.yaml");ADMIN=Path("/private/tmp/ok141-exact-clusterrole-prerequisites-admin.yaml")
NAMES={"disposable-ok141-observability-core-kube-state-metrics","ok-observability-grafana-clusterrole","ok-observability-log-collector","ok-observability-operator","ok-observability-prometheus"}
def sha(path):return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
def raw(config,verb,uri,payload=None,allow_not_found=False):
 cmd=[str(CLIENT),"--kubeconfig",str(config),verb,"--raw",uri]
 if payload is not None:cmd.extend(["--filename","-"])
 r=subprocess.run(cmd,input=payload,capture_output=True,check=False)
 if r.returncode:
  failure=(r.stderr+b"\n"+r.stdout).lower()
  if allow_not_found and (b'"code": 404' in failure or b"notfound" in failure or b"not found" in failure):return None
  raise RuntimeError(f"exact {verb} failed")
 return json.loads(r.stdout)
def semantic(value):
 return {"apiVersion":value.get("apiVersion"),"kind":value.get("kind"),"metadata":{"name":value.get("metadata",{}).get("name"),"labels":value.get("metadata",{}).get("labels") or {},"annotations":value.get("metadata",{}).get("annotations") or {}},"rules":value.get("rules") or [],"aggregationRule":value.get("aggregationRule")}
def main():
 spec=yaml.safe_load(CANDIDATE.read_text())["spec"];ext=spec["extraction"];evidence_path=Path(ext["evidencePath"]);directory=Path(ext["payloadDirectory"]);output=Path(spec["outputPath"])
 if set(spec["exactNames"])!=NAMES or sha(evidence_path)!=ext["evidenceDigest"]:raise RuntimeError("extraction binding mismatch")
 extraction=json.loads(evidence_path.read_text());expected={x["name"]:x["rawDocumentDigest"] for x in extraction["objects"]}
 files={p.stem:p for p in directory.glob("*.yaml")}
 if set(files)!=NAMES or any(sha(files[n])!=expected[n] for n in NAMES):raise RuntimeError("private payload mismatch")
 if sha(CLIENT)!="sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf" or MGMT.is_symlink() or (MGMT.stat().st_mode&0o777)!=0o600 or ADMIN.exists() or output.exists():raise RuntimeError("local precondition failed")
 result={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1ExactClusterRolePrerequisiteCreateEvidence","candidateDigest":sha(CANDIDATE),"extractionEvidenceDigest":ext["evidenceDigest"],"payloadDigest":ext["payloadDigest"],"exactNames":sorted(NAMES),"preflightAbsentCount":0,"created":[],"mutationPerformed":False,"updatePatchReplacePerformed":False,"deletePerformed":False,"rollbackOrCleanupPerformed":False,"syncRetryPerformed":False,"credentialPayloadRetained":False,"rawObjectsRetained":False,"failureInjectionPerformed":False,"state":"STARTED"}
 try:
  secret=raw(MGMT,"get",spec["management"]["workloadKubeconfigSecretURI"]);kube=base64.b64decode(secret.get("data",{}).get("value",""),validate=True)
  fd=os.open(ADMIN,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,"wb") as f:f.write(kube)
  kube=b"";secret={}
  for name in sorted(NAMES):
   if raw(ADMIN,"get",f"{spec['target']['collectionURI']}/{name}",allow_not_found=True) is not None:raise RuntimeError("exact prerequisite already exists")
   result["preflightAbsentCount"]+=1
  if result["preflightAbsentCount"]!=5:raise RuntimeError("absence preflight incomplete")
  for name in sorted(NAMES):
   desired=yaml.safe_load(files[name].read_bytes());created=raw(ADMIN,"create",spec["target"]["collectionURI"],files[name].read_bytes());meta=created.get("metadata",{})
   if meta.get("name")!=name or not meta.get("uid") or semantic(created)!=semantic(desired):raise RuntimeError("create postcondition failed")
   result["created"].append({"name":name,"uidPresent":True,"semanticMatch":True})
  result["mutationPerformed"]=True;result["state"]="PASS-EXACT-CLUSTERROLE-PREREQUISITES-CREATED"
 except Exception as exc:
  result["mutationPerformed"]=bool(result["created"]);result["state"]="STOP-PRESERVE-NO-RETRY";result["failureClass"]=type(exc).__name__
 finally:
  ADMIN.unlink(missing_ok=True);result["temporaryAdminRemoved"]=not ADMIN.exists()
 fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(result,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({"state":result["state"],"createdCount":len(result["created"]),"evidenceDigest":sha(output)},sort_keys=True));return 0 if result["state"].startswith("PASS") else 2
if __name__=="__main__":raise SystemExit(main())
