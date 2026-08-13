#!/usr/bin/env python3
"""Exact M0a-v7.2 Deployment repair; impossible to mutate without one exact grant."""

from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import yaml

HERE=Path(__file__).resolve().parent
SPIKE=HERE.parent
def _load(name:str,path:Path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m
    assert s.loader is not None;s.loader.exec_module(m);return m
V71=_load("ok141_m0a_v71_for_v72",SPIKE/"m0a-execution-v7-1"/"controlled_m0a_execution_v7_1.py")
class RepairError(ValueError):pass
def sha(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def expect(actual:Any,expected:Any,claim:str)->None:
    if actual!=expected:raise RepairError(f"{claim}: expected {expected!r}, got {actual!r}")
def read_yaml(path:Path)->dict[str,Any]:
    value=yaml.safe_load(path.read_text())
    if not isinstance(value,dict):raise RepairError(f"expected mapping in {path}")
    return value
def resolve(base:Path,ref:dict[str,Any])->Path:
    path=(base/ref["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():raise RepairError(f"invalid reference: {ref['path']}")
    expect(sha(path),ref["digest"],ref["path"]);return path
def utc(value:str)->datetime:
    result=datetime.fromisoformat(value.replace("Z","+00:00"))
    if result.tzinfo!=timezone.utc:raise RepairError("grant timestamps must be UTC")
    return result
def verify_candidate(path:Path)->tuple[dict[str,Any],dict[str,Path],dict[str,Any],dict[str,Path]]:
    document=read_yaml(path);spec=document["spec"]
    expect(spec["version"],"ok141-m0a-v7-2-exact-repair/v1","version")
    expect(spec["state"],"READY-FOR-ONE-EXPLICIT-REPAIR-GRANT","state")
    refs={name:resolve(path.parent,ref) for name,ref in spec["references"].items()}
    expect(refs["executor"],Path(__file__).resolve(),"executor")
    v71,_,base,base_refs=V71.verify_candidate(refs["v71Candidate"])
    runtime=read_yaml(refs["v71RuntimeEvidence"])["spec"]
    expect(runtime["state"],"PARTIAL-STATE-RETAINED","runtime state")
    expect(runtime["execution"]["rawLocalEvidenceDigest"],spec["source"]["rawEvidenceDigest"],"raw evidence")
    patch=json.loads(refs["jsonPatch"].read_text())
    expect(len(patch),4,"patch operations")
    expect([x["op"] for x in patch],["test","test","test","replace"],"patch operations")
    expect(patch[0],{"op":"test","path":"/metadata/uid","value":spec["target"]["deploymentUID"]},"UID test")
    expect(patch[1],{"op":"test","path":"/spec/template/spec/containers/0/name","value":"manager"},"container test")
    expect(patch[2]["value"],spec["repair"]["oldArguments"],"old arguments")
    expect(patch[3]["value"],spec["repair"]["newArguments"],"new arguments")
    expect(spec["authorization"],{"decision":"NO-GO","repairGranted":False,"retryGranted":False,"rollbackGranted":False,"evidencePublicationGranted":False,"hcpHrpSubmissionGranted":False,"m0bInstallationGranted":False,"go1Granted":False,"targetConvergenceGranted":False,"failureInjectionGranted":False},"authorization")
    return document,refs,base,base_refs
def verify_grant(candidate_path:Path,grant_path:Path,now:datetime|None=None)->dict[str,Any]:
    candidate,_,_,_=verify_candidate(candidate_path);grant=read_yaml(grant_path)["spec"]
    expect(grant["version"],"ok141-m0a-v7-2-exact-repair-grant/v1","grant version")
    expect(grant["candidateDigest"],sha(candidate_path),"candidate binding")
    expect((grant["authority"],grant["decision"],grant["repairAuthorized"]),("github:arashkaffamanesh","GO",True),"grant")
    expect(grant["repairGrant"]["gate"],"M0A-F1-v7.2","gate")
    if not grant["repairGrant"]["grantID"]:raise RepairError("grant ID required")
    start,end=utc(grant["validFrom"]),utc(grant["validUntil"]);current=now or datetime.now(timezone.utc)
    if end<=start or (end-start).total_seconds()>3600 or not start<=current<=end:raise RepairError("repair window invalid")
    expect(grant["maximumRuns"],1,"maximum runs")
    output=Path(grant["evidenceOutputPath"])
    if not output.is_absolute() or Path("/private/tmp") not in output.resolve().parents:raise RepairError("evidence path must be below /private/tmp")
    for key in ("retryGranted","rollbackGranted","evidencePublicationGranted","hcpHrpSubmissionGranted","m0bInstallationGranted","go1Granted","targetConvergenceGranted","failureInjectionGranted"):expect(grant[key],False,key)
    return grant
def kubectl(binary:Path,config:Path,args:list[str],check:bool=True,input_bytes:bytes|None=None)->subprocess.CompletedProcess:
    return subprocess.run([str(binary),"--kubeconfig",str(config),*args],input=input_bytes,capture_output=True,check=check,timeout=90)
def get_json(binary:Path,config:Path,args:list[str])->dict[str,Any]:return json.loads(kubectl(binary,config,[*args,"-o","json"]).stdout)
def live_preflight(candidate:dict[str,Any],base:dict[str,Any],base_refs:dict[str,Path],binary:Path,config:Path)->dict[str,Any]:
    spec=candidate["spec"]
    V71.V6.V5.configure_kubectl(binary,base)
    namespace=get_json(binary,config,["get","namespace","kube-system"])
    expect(namespace["metadata"]["uid"],spec["target"]["kubeSystemNamespaceUID"],"target UID")
    deployment=get_json(binary,config,["--namespace","caaph-system","get","deployment","caaph-controller-manager"])
    expect(deployment["metadata"]["uid"],spec["target"]["deploymentUID"],"deployment UID")
    expect(deployment["metadata"]["generation"],spec["target"]["expectedGeneration"],"generation")
    container=deployment["spec"]["template"]["spec"]["containers"][0]
    expect(container["name"],"manager","container")
    expect(container["image"],spec["target"]["image"],"image")
    expect(container["args"],spec["repair"]["oldArguments"],"old arguments")
    V71.ensure_bootstrap_absent(config)
    reviewed=V71.V6.V5.INSTALLER.verify_reviewed_object_set(read_yaml(base_refs["installationProtocol"]),base_refs["installationProtocol"])
    inventory=V71.V6.V5.V4.exact_object_inventory(config,reviewed);expect(inventory["present"],19,"reviewed objects")
    for resource in ("helmchartproxies.addons.cluster.x-k8s.io","helmreleaseproxies.addons.cluster.x-k8s.io"):
        expect(len(get_json(binary,config,["get",resource,"--all-namespaces"]).get("items",[])),0,resource)
    lifecycle={}
    for label,resource in (("clusters","clusters.cluster.x-k8s.io"),("machines","machines.cluster.x-k8s.io"),("machineDeployments","machinedeployments.cluster.x-k8s.io")):
        lifecycle[label]=len(get_json(binary,config,["get",resource,"--all-namespaces"]).get("items",[]))
    expect(lifecycle,{"clusters":0,"machines":0,"machineDeployments":0},"lifecycle")
    return {"targetUID":namespace["metadata"]["uid"],"deploymentUID":deployment["metadata"]["uid"],"deploymentGeneration":deployment["metadata"]["generation"],"reviewedObjectsPresent":inventory["present"],"temporaryBootstrapObjectsPresent":0,"caaphCustomResources":0,"lifecycleInventory":lifecycle,"oldArgumentsMatch":True}
def write_evidence(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream:stream.write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
def execute(candidate_path:Path,grant_path:Path,binary:Path,config:Path,output:Path)->dict[str,Any]:
    candidate,refs,base,base_refs=verify_candidate(candidate_path);grant=verify_grant(candidate_path,grant_path)
    expect(output.resolve(),Path(grant["evidenceOutputPath"]).resolve(),"evidence path")
    if output.exists():raise RepairError("repair evidence already exists")
    preflight=live_preflight(candidate,base,base_refs,binary,config)
    evidence={"version":"ok141-m0a-v7-2-repair-evidence/v1","candidateDigest":sha(candidate_path),"grantDigest":sha(grant_path),"grantID":grant["repairGrant"]["grantID"],"startedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"result":"STARTED","preflight":preflight}
    try:
        result=kubectl(binary,config,["--namespace","caaph-system","patch","deployment","caaph-controller-manager","--type=json","--patch-file",str(refs["jsonPatch"])],check=False)
        evidence["patch"]={"exitCode":result.returncode,"stdout":result.stdout.decode(errors="replace")[:4096],"stderr":result.stderr.decode(errors="replace")[:4096],"payloadRetained":False}
        if result.returncode!=0:raise RepairError("exact deployment patch failed")
        readiness=V71.V6.V5.V1.wait_ready(config,base["spec"]["installation"]["readinessTimeoutSeconds"])
        deployment=get_json(binary,config,["--namespace","caaph-system","get","deployment","caaph-controller-manager"])
        expect(deployment["metadata"]["uid"],candidate["spec"]["target"]["deploymentUID"],"post-patch UID")
        expect(deployment["spec"]["template"]["spec"]["containers"][0]["args"],candidate["spec"]["repair"]["newArguments"],"new arguments")
        evidence.update({"readiness":readiness,"postPatch":{"deploymentUID":deployment["metadata"]["uid"],"generation":deployment["metadata"]["generation"],"observedGeneration":deployment["status"].get("observedGeneration"),"readyReplicas":deployment["status"].get("readyReplicas",0),"newArgumentsMatch":True},"result":"SUCCESS"})
        return evidence
    except Exception as error:
        evidence.update({"result":"STOP-NOT-SUCCESS","failureType":type(error).__name__,"failure":str(error)});raise
    finally:
        evidence["finishedAt"]=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");write_evidence(output,evidence)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("command",choices=("verify","verify-grant","preflight","execute"));p.add_argument("--candidate",type=Path,required=True);p.add_argument("--grant",type=Path);p.add_argument("--kubectl-bin",type=Path);p.add_argument("--admin-kubeconfig",type=Path);p.add_argument("--evidence-output",type=Path);p.add_argument("--execute",action="store_true");a=p.parse_args()
    try:
        candidate,_,base,base_refs=verify_candidate(a.candidate.resolve());result={"candidateDigest":sha(a.candidate.resolve()),"state":candidate["spec"]["state"],"mutationAuthorized":False}
        if a.command=="verify-grant":
            if a.grant is None:raise RepairError("grant required")
            verify_grant(a.candidate.resolve(),a.grant.resolve());result["grantValidNow"]=True
        elif a.command=="preflight":
            if None in (a.kubectl_bin,a.admin_kubeconfig):raise RepairError("preflight requires toolchain and target")
            result={"result":"PASS","mutationPerformed":False,"observation":live_preflight(candidate,base,base_refs,a.kubectl_bin.resolve(),a.admin_kubeconfig.resolve())}
        elif a.command=="execute":
            if not a.execute or None in (a.grant,a.kubectl_bin,a.admin_kubeconfig,a.evidence_output):raise RepairError("execute requires grant toolchain target output and --execute")
            run=execute(a.candidate.resolve(),a.grant.resolve(),a.kubectl_bin.resolve(),a.admin_kubeconfig.resolve(),a.evidence_output.resolve());result={"result":run["result"],"evidenceOutput":str(a.evidence_output)}
        print(json.dumps(result,sort_keys=True,separators=(",",":")));return 0
    except (RepairError,OSError,KeyError,TypeError,ValueError,yaml.YAMLError,json.JSONDecodeError,subprocess.SubprocessError) as error:print(f"ERROR: {error}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
