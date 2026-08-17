#!/usr/bin/env python3
"""Review exact effective Argo ClusterRole write permissions."""
from __future__ import annotations
import base64,hashlib,json,os,subprocess
from pathlib import Path
import yaml
HERE=Path(__file__).resolve().parent;CANDIDATE=HERE/"effective-clusterrole-write-review-v1.yaml"
CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64");SHARED=Path("/Users/arash/.kube/ok-shared.yaml")
NAMES={"disposable-ok141-observability-core-kube-state-metrics","ok-observability-grafana-clusterrole","ok-observability-log-collector","ok-observability-operator","ok-observability-prometheus"};VERBS={"create","get","patch","update"}
def sha(path):return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(config,verb,uri,payload=None):
 cmd=[str(CLIENT),"--kubeconfig",str(config),verb,"--raw",uri]
 if payload is not None:cmd.extend(["--filename","-"])
 r=subprocess.run(cmd,input=payload,capture_output=True,check=False)
 if r.returncode:raise RuntimeError(f"exact {verb} failed")
 return json.loads(r.stdout)
def decode(secret,name):return base64.b64decode(secret["data"][name],validate=True).decode()
def main():
 spec=yaml.safe_load(CANDIDATE.read_text())["spec"];pred=Path(spec["predecessor"]["path"]);ephemeral=Path(spec["ephemeralKubeconfigPath"]);output=Path(spec["outputPath"])
 if sha(pred)!=spec["predecessor"]["digest"] or set(spec["exactResourceNames"])!=NAMES or set(spec["exactVerbs"])!=VERBS:raise RuntimeError("scope mismatch")
 if sha(CLIENT)!="sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf" or SHARED.is_symlink() or (SHARED.stat().st_mode&0o777)!=0o600 or ephemeral.exists() or output.exists():raise RuntimeError("local precondition failed")
 result={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1EffectiveClusterRoleWriteReviewEvidence","candidateDigest":sha(CANDIDATE),"predecessorDigest":spec["predecessor"]["digest"],"reviews":[],"registrationSecretReadPerformed":False,"credentialPayloadRetained":False,"endpointRetained":False,"rawResponsesRetained":False,"persistentResourceCreated":False,"rbacChanged":False,"retryPerformed":False,"cleanupPerformed":False,"failureInjectionPerformed":False}
 try:
  secret=run(SHARED,"get",spec["registrationSecretURI"]);result["registrationSecretReadPerformed"]=True;server=decode(secret,"server");config=json.loads(decode(secret,"config"));token=config["bearerToken"];ca=config["tlsClientConfig"]["caData"]
  kube={"apiVersion":"v1","kind":"Config","clusters":[{"name":"target","cluster":{"server":server,"certificate-authority-data":ca}}],"users":[{"name":"argo","user":{"token":token}}],"contexts":[{"name":"target","context":{"cluster":"target","user":"argo"}}],"current-context":"target"}
  fd=os.open(ephemeral,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,"w") as f:yaml.safe_dump(kube,f,sort_keys=True)
  token="";ca="";server="";config={};secret={};kube={};uri="/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"
  for name in sorted(NAMES):
   for verb in sorted(VERBS):
    body={"apiVersion":"authorization.k8s.io/v1","kind":"SelfSubjectAccessReview","spec":{"resourceAttributes":{"group":"rbac.authorization.k8s.io","resource":"clusterroles","verb":verb,"name":name}}}
    status=run(ephemeral,"create",uri,json.dumps(body,separators=(",",":")).encode()).get("status",{});result["reviews"].append({"name":name,"verb":verb,"allowed":status.get("allowed") is True,"denied":status.get("denied") is True})
  result["exactReviewCount"]=len(result["reviews"]);result["allAllowed"]=all(x["allowed"] for x in result["reviews"]);result["state"]="PASS-EFFECTIVE-WRITE-REVIEW"
 finally:
  ephemeral.unlink(missing_ok=True);result["temporaryKubeconfigRemoved"]=not ephemeral.exists()
 fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(result,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({"state":result.get("state"),"allAllowed":result.get("allAllowed"),"denied":[x for x in result.get("reviews",[]) if not x["allowed"]],"evidenceDigest":sha(output)},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
