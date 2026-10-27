#!/usr/bin/env python3
"""Extract the five exact OK-141 ClusterRoles from the bound immutable render."""
from __future__ import annotations
import hashlib,json,os,subprocess,tarfile,tempfile
from pathlib import Path
import yaml

HERE=Path(__file__).resolve().parent;SPIKE=HERE.parent
SOURCE=Path("/Users/arash/temp/kubernauts/ok/ok-observability");COMMIT="b5f7be6a7ddab798f31f32197fcbb9e86a9798b6"
APPLICATIONS=SPIKE/"harness/profiles/platform/minimal-observability-v5/applications.yaml"
OUTPUT=Path("/private/tmp/ok141-exact-five-clusterroles-v1");EVIDENCE=Path("/private/tmp/ok141-exact-five-clusterroles-v1-evidence.json")
NAMES={"disposable-ok141-observability-core-kube-state-metrics","ok-observability-grafana-clusterrole","ok-observability-log-collector","ok-observability-operator","ok-observability-prometheus"}
RAW="sha256:61ee9bfc11141ab89809e8817ee6a1ec828fd20f0316d6cc17426979c43a4519"
def digest(raw):return "sha256:"+hashlib.sha256(raw).hexdigest()
def main():
 if OUTPUT.exists() or EVIDENCE.exists():raise RuntimeError("exclusive output exists")
 apps={x["metadata"]["name"]:x for x in yaml.safe_load_all(APPLICATIONS.read_text()) if x};values=yaml.safe_dump(apps["disposable-ok141-observability-core"]["spec"]["source"]["helm"]["valuesObject"],sort_keys=True).encode()
 with tempfile.TemporaryDirectory(prefix="ok141-five-roles-") as d:
  root=Path(d);archive=root/"source.tar";subprocess.run(["git","-C",str(SOURCE),"archive","--format=tar",f"--output={archive}",COMMIT],check=True);src=root/"source";src.mkdir()
  with tarfile.open(archive,"r") as a:a.extractall(src,filter="data")
  vp=root/"values.yaml";vp.write_bytes(values)
  rendered=subprocess.run(["helm","template","disposable-ok141-observability-core",str(src/"profiles/ok-observability-standard"),"--namespace","ok-observability","--kube-version","1.36.2","--include-crds","--values",str(vp)],check=True,capture_output=True).stdout
 if digest(rendered)!=RAW:raise RuntimeError("bound render digest mismatch")
 selected={}
 for part in rendered.split(b"\n---\n"):
  raw=(b"---\n"+part) if not part.startswith(b"---\n") else part
  value=yaml.load(raw,Loader=yaml.BaseLoader)
  if value and value.get("kind")=="ClusterRole" and value.get("metadata",{}).get("name") in NAMES:selected[value["metadata"]["name"]]=(raw,value)
 if set(selected)!=NAMES or len(selected)!=5:raise RuntimeError("exact ClusterRole set mismatch")
 OUTPUT.mkdir(mode=0o700)
 summary=[]
 for name in sorted(selected):
  raw,value=selected[name];path=OUTPUT/f"{name}.yaml";fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
  with os.fdopen(fd,"wb") as f:f.write(raw)
  summary.append({"name":name,"ruleCount":len(value.get("rules") or []),"rawDocumentDigest":digest(raw)})
 manifest=json.dumps(summary,sort_keys=True,separators=(",",":")).encode()
 evidence={"apiVersion":"evidence.openkubes.io/v1alpha1","kind":"GO1ExactClusterRoleExtractionEvidence","sourceCommit":COMMIT,"boundRenderDigest":RAW,"exactNames":sorted(NAMES),"objectCount":5,"objects":summary,"privatePayloadDigest":digest(manifest),"rawObjectsPublished":False,"mutationPerformed":False,"retryPerformed":False,"cleanupPerformed":False,"failureInjectionPerformed":False,"state":"PASS-EXACT-FIVE-CLUSTERROLES-EXTRACTED"}
 fd=os.open(EVIDENCE,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,"w") as f:json.dump(evidence,f,sort_keys=True,separators=(",",":"));f.write("\n")
 print(json.dumps({"state":evidence["state"],"payloadDigest":evidence["privatePayloadDigest"],"evidenceDigest":digest(EVIDENCE.read_bytes())},sort_keys=True));return 0
if __name__=="__main__":raise SystemExit(main())
