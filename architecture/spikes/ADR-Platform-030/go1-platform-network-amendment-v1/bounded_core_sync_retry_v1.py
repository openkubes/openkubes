#!/usr/bin/env python3
"""Submit one exact Argo sync operation for the bound OK-141 core Application."""
from __future__ import annotations
import argparse,copy,hashlib,json,os,subprocess
from pathlib import Path
import yaml

HERE=Path(__file__).resolve().parent
CANDIDATE=HERE/"core-sync-retry-v1.yaml"
CLIENT=Path("/private/tmp/ok141-kubectl-v1.34.1-darwin-amd64")
KUBECONFIG=Path("/Users/arash/.kube/ok-shared.yaml")
EXPECTED_CLIENT="sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
def sha(path):return "sha256:"+hashlib.sha256(Path(path).read_bytes()).hexdigest()
def exact(verb,uri,payload=None):
 cmd=[str(CLIENT),"--kubeconfig",str(KUBECONFIG),verb,"--raw",uri]
 if payload is not None:cmd.extend(["--filename","-"])
 r=subprocess.run(cmd,input=payload,capture_output=True,check=False)
 if r.returncode:raise RuntimeError(f"exact {verb} failed")
 return json.loads(r.stdout)
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--candidate",type=Path,default=CANDIDATE);args=parser.parse_args();candidate_path=args.candidate
 spec=yaml.safe_load(candidate_path.read_text())["spec"]
 expected_auth={"state":"GRANTED","source":"standing-dev-execution-envelope-v1","envelopeDigest":"sha256:85e997df331d2ced4ea147c32cc4a94a419e9efdba6de17d8a8ef3cb1dbeac93"}
 if spec["authorization"]!=expected_auth:raise RuntimeError("authorization mismatch")
 for key in ("predecessor","remediation"):
  p=Path(spec[key]["path"])
  if sha(p)!=spec[key]["digest"]:raise RuntimeError(f"{key} mismatch")
 if json.loads(Path(spec["remediation"]["path"]).read_text()).get("state")!="PASS-EXACT-RBAC-REMEDIATION":raise RuntimeError("remediation state mismatch")
 if sha(CLIENT)!=EXPECTED_CLIENT or KUBECONFIG.is_symlink() or not KUBECONFIG.is_file() or (KUBECONFIG.stat().st_mode&0o777)!=0o600:raise RuntimeError("local identity mismatch")
 app=spec["application"];retry_ordinal=int(app.get("retryOrdinal",1))
 if retry_ordinal not in (1,2):raise RuntimeError("retry ordinal mismatch")
 prior_retry_digest=None
 if retry_ordinal==2:
  prior=Path(spec["priorRetry"]["path"]);prior_value=json.loads(prior.read_text())
  if sha(prior)!=spec["priorRetry"]["digest"] or prior_value.get("state")!=spec["priorRetry"]["state"]:raise RuntimeError("prior retry mismatch")
  prior_retry_digest=spec["priorRetry"]["digest"]
 output=Path(spec["outputPath"])
 if output.exists() or output.is_symlink():raise RuntimeError("exclusive output exists")
 current=exact("get",app["uri"]);meta=current.get("metadata",{});annotations=meta.get("annotations",{})
 if (meta.get("namespace"),meta.get("name"))!=(app["namespace"],app["name"]):raise RuntimeError("application identity mismatch")
 if not meta.get("uid") or not meta.get("resourceVersion"):raise RuntimeError("concurrency identity missing")
 if current.get("operation") is not None:raise RuntimeError("operation already present")
 if current.get("status",{}).get("operationState",{}).get("phase")!=app["expectedPriorPhase"]:raise RuntimeError("prior phase mismatch")
 if annotations.get("openkubes.io/intent-revision")!=app["R"] or annotations.get("openkubes.io/platform-revision")!=app["P"] or annotations.get("openkubes.io/execution-fixture")!=app["fixtureDigest"]:raise RuntimeError("OpenKubes identity mismatch")
 if current.get("spec",{}).get("source",{}).get("targetRevision")!=app["sourceRevision"]:raise RuntimeError("source revision mismatch")
 uid,rv=meta["uid"],meta["resourceVersion"]
 replacement=copy.deepcopy(current);replacement["metadata"].pop("managedFields",None);replacement["metadata"].pop("selfLink",None);replacement["operation"]=copy.deepcopy(app["operation"])
 returned=exact("replace",app["uri"],json.dumps(replacement,sort_keys=True,separators=(",",":")).encode());new=returned.get("metadata",{})
 if new.get("uid")!=uid or new.get("resourceVersion")==rv or returned.get("operation")!=app["operation"]:raise RuntimeError("replace postcondition failed")
 evidence={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1BoundedArgoApplicationSyncRetryEvidence","candidateDigest":sha(candidate_path),"predecessorDigest":spec["predecessor"]["digest"],"remediationDigest":spec["remediation"]["digest"],"priorRetryDigest":prior_retry_digest,"retryOrdinal":retry_ordinal,"applicationName":app["name"],"sourceRevision":app["sourceRevision"],"uidPreserved":True,"resourceVersionAdvanced":True,"exactOperationSubmitted":True,"specChanged":False,"credentialChanged":False,"rbacChanged":False,"deletePerformed":False,"rollbackOrCleanupPerformed":False,"secondRetryPerformed":retry_ordinal==2,"rawObjectRetained":False,"failureInjectionPerformed":False,"state":"PASS-SYNC-RETRY-SUBMITTED"}
 fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(evidence,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({"state":evidence["state"],"evidenceDigest":sha(output)},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
