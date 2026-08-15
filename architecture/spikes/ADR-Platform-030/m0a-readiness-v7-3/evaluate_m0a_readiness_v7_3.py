#!/usr/bin/env python3
"""Read-only CAAPH readiness evaluator with correct OCI index/platform semantics."""

from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import yaml

HERE=Path(__file__).resolve().parent;SPIKE=HERE.parent
KUBECTL_DIGEST="sha256:bb211f2b31f2b3bc60562b44cc1e3b712a16a98e9072968ba255beb04cefcfdf"
def _load(name:str,path:Path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m
    assert s.loader is not None;s.loader.exec_module(m);return m
V71=_load("ok141_m0a_v71_for_readiness_v73",SPIKE/"m0a-execution-v7-1"/"controlled_m0a_execution_v7_1.py")
class EvaluationError(ValueError):pass
def sha(path:Path)->str:return "sha256:"+hashlib.sha256(path.read_bytes()).hexdigest()
def expect(actual:Any,expected:Any,claim:str)->None:
    if actual!=expected:raise EvaluationError(f"{claim}: expected {expected!r}, got {actual!r}")
def read_yaml(path:Path)->dict[str,Any]:
    value=yaml.safe_load(path.read_text())
    if not isinstance(value,dict):raise EvaluationError(f"expected mapping in {path}")
    return value
def resolve(base:Path,ref:dict[str,Any])->Path:
    path=(base/ref["path"]).resolve()
    if SPIKE.resolve() not in path.parents or not path.is_file():raise EvaluationError(f"invalid reference: {ref['path']}")
    expect(sha(path),ref["digest"],ref["path"]);return path
def verify_candidate(path:Path)->tuple[dict[str,Any],dict[str,Path]]:
    document=read_yaml(path);spec=document["spec"]
    expect(spec["version"],"ok141-m0a-readiness/v7.3","version");expect(spec["state"],"READY-READ-ONLY","state")
    refs={name:resolve(path.parent,ref) for name,ref in spec["references"].items()}
    expect(refs["evaluator"],Path(__file__).resolve(),"evaluator")
    lock=read_yaml(refs["installationLock"])["spec"]
    image=lock["source"]["controllerImage"]
    expect(image["reference"],spec["imageIdentity"]["reference"],"image reference")
    expect(image["indexDigest"],spec["imageIdentity"]["indexDigest"],"index digest")
    expect(image["linuxAmd64Digest"],spec["imageIdentity"]["linuxAmd64ChildManifestDigest"],"platform digest")
    expect(spec["imageIdentity"]["expectedRuntimeImageID"],image["reference"].split(":v0.6.4")[0]+"@"+image["indexDigest"],"runtime image ID")
    expect(spec["authorization"],{key:False for key in spec["authorization"]},"authorization")
    return document,refs
def kubectl(binary:Path,config:Path,args:list[str])->subprocess.CompletedProcess:
    return subprocess.run([str(binary),"--kubeconfig",str(config),*args],capture_output=True,check=True,timeout=90)
def get_json(binary:Path,config:Path,args:list[str])->dict[str,Any]:return json.loads(kubectl(binary,config,[*args,"-o","json"]).stdout)
def ready_condition(value:dict[str,Any],kind:str="Ready")->bool:return any(x.get("type")==kind and x.get("status")=="True" for x in value.get("status",{}).get("conditions",[]))
def write_evidence(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as stream:stream.write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
def evaluate(candidate_path:Path,binary:Path,config:Path,output:Path)->dict[str,Any]:
    candidate,refs=verify_candidate(candidate_path);spec=candidate["spec"]
    expect(sha(binary),KUBECTL_DIGEST,"kubectl digest")
    expect(output.resolve(),Path(spec["evidence"]["localOutputPath"]).resolve(),"output path")
    if output.exists():raise EvaluationError("readiness evidence already exists")
    read_yaml(refs["repairCandidate"])
    _,_,base,base_refs=V71.verify_candidate((SPIKE/"m0a-execution-v7-1/m0a-execution-candidate-v7-1.yaml").resolve())
    reviewed=V71.V6.V5.INSTALLER.verify_reviewed_object_set(read_yaml(base_refs["installationProtocol"]),base_refs["installationProtocol"])
    evidence={"version":"ok141-m0a-readiness-evidence/v7.3","candidateDigest":sha(candidate_path),"observedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"mutationPerformed":False,"result":"STARTED"}
    try:
        namespace=get_json(binary,config,["get","namespace","kube-system"]);expect(namespace["metadata"]["uid"],spec["target"]["kubeSystemNamespaceUID"],"target UID")
        deployment=get_json(binary,config,["--namespace","caaph-system","get","deployment","caaph-controller-manager"])
        expect(deployment["metadata"]["uid"],spec["target"]["deploymentUID"],"deployment UID");expect(deployment["metadata"]["generation"],spec["target"]["expectedGeneration"],"deployment generation")
        expect(deployment["status"].get("observedGeneration"),deployment["metadata"]["generation"],"observed generation");expect(deployment["status"].get("availableReplicas",0),1,"available replicas");expect(deployment["status"].get("readyReplicas",0),1,"ready replicas")
        container=deployment["spec"]["template"]["spec"]["containers"][0];expect(container["image"],spec["imageIdentity"]["reference"],"image");expect(container["args"],spec["expectedArguments"],"arguments")
        cert=get_json(binary,config,["--namespace","caaph-system","get","certificate","caaph-serving-cert"]);expect(ready_condition(cert),True,"certificate")
        crds=[get_json(binary,config,["get","customresourcedefinition",name]) for name in ("helmchartproxies.addons.cluster.x-k8s.io","helmreleaseproxies.addons.cluster.x-k8s.io")];expect(sum(ready_condition(x,"Established") for x in crds),2,"CRDs")
        endpoints=[get_json(binary,config,["--namespace","caaph-system","get","endpoints",name]) for name in ("caaph-controller-manager-metrics-service","caaph-webhook-service")];expect(sum(any(s.get("addresses") for s in x.get("subsets",[])) for x in endpoints),2,"endpoints")
        pods=get_json(binary,config,["--namespace","caaph-system","get","pods","--selector","cluster.x-k8s.io/provider=helm,control-plane=controller-manager"])["items"];expect(len(pods),1,"pod count")
        statuses=pods[0].get("status",{}).get("containerStatuses",[]);expect(len(statuses),1,"container status count");status=statuses[0]
        expect(status.get("ready"),True,"pod readiness");expect(status.get("restartCount"),0,"controller restarts");expect(status.get("imageID"),spec["imageIdentity"]["expectedRuntimeImageID"],"runtime index imageID")
        inventory=V71.V6.V5.V4.exact_object_inventory(config,reviewed);expect(inventory["present"],19,"reviewed objects")
        custom={resource:len(get_json(binary,config,["get",resource,"--all-namespaces"]).get("items",[])) for resource in ("helmchartproxies.addons.cluster.x-k8s.io","helmreleaseproxies.addons.cluster.x-k8s.io")};expect(sum(custom.values()),0,"CAAPH custom resources")
        lifecycle={label:len(get_json(binary,config,["get",resource,"--all-namespaces"]).get("items",[])) for label,resource in (("clusters","clusters.cluster.x-k8s.io"),("machines","machines.cluster.x-k8s.io"),("machineDeployments","machinedeployments.cluster.x-k8s.io"))};expect(lifecycle,{"clusters":0,"machines":0,"machineDeployments":0},"lifecycle")
        evidence.update({"result":"PASS","target":{"kubeSystemNamespaceUID":namespace["metadata"]["uid"],"deploymentUID":deployment["metadata"]["uid"],"deploymentGeneration":deployment["metadata"]["generation"],"observedGeneration":deployment["status"].get("observedGeneration")},"readiness":{"deploymentAvailable":True,"certificateReady":True,"crdsEstablished":2,"serviceEndpointsReady":2,"readyControllerPods":1,"controllerRestarts":0},"imageIdentity":{"reference":container["image"],"runtimeImageID":status["imageID"],"runtimeImageIDEqualsLockedIndex":True,"lockedIndexDigest":spec["imageIdentity"]["indexDigest"],"lockedLinuxAmd64ChildManifestDigest":spec["imageIdentity"]["linuxAmd64ChildManifestDigest"],"runtimeImageIDEqualsPlatformChild":False},"inventory":{"reviewedObjectsPresent":19,"caaphCustomResources":custom,"capiLifecycleInventory":lifecycle}});return evidence
    except Exception as error:evidence.update({"result":"FAIL-CLOSED","failureType":type(error).__name__,"failure":str(error)});raise
    finally:write_evidence(output,evidence)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("command",choices=("verify","evaluate"));p.add_argument("--candidate",type=Path,required=True);p.add_argument("--kubectl-bin",type=Path);p.add_argument("--admin-kubeconfig",type=Path);p.add_argument("--evidence-output",type=Path);a=p.parse_args()
    try:
        candidate,_=verify_candidate(a.candidate.resolve());result={"candidateDigest":sha(a.candidate.resolve()),"state":candidate["spec"]["state"],"mutationAuthorized":False}
        if a.command=="evaluate":
            if None in (a.kubectl_bin,a.admin_kubeconfig,a.evidence_output):raise EvaluationError("evaluate requires toolchain target and evidence output")
            result=evaluate(a.candidate.resolve(),a.kubectl_bin.resolve(),a.admin_kubeconfig.resolve(),a.evidence_output.resolve())
        print(json.dumps(result,sort_keys=True,separators=(",",":")));return 0
    except (EvaluationError,OSError,KeyError,TypeError,ValueError,yaml.YAMLError,json.JSONDecodeError,subprocess.SubprocessError) as error:print(f"ERROR: {error}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
