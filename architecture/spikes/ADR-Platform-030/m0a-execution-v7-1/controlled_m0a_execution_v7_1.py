#!/usr/bin/env python3
"""Split-authority M0a-v7.1 executor; impossible to mutate without four exact grants."""

from __future__ import annotations
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import yaml
HERE=Path(__file__).resolve().parent
SPIKE=HERE.parent
def _load(name:str,path:Path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m
    assert s.loader is not None;s.loader.exec_module(m);return m
V6=_load("ok141_m0a_v6_for_v71",SPIKE/"m0a-execution-v6"/"controlled_m0a_execution_v6.py")
PAYLOADS=_load("ok141_m0a_v71_payloads",HERE/"m0a_v7_1_payloads.py")
CREDENTIAL=_load("ok141_m0a_v71_credential",HERE/"verify_m0a_v7_1_credential.py")
SA_NAME="ok141-m0a-installer-v7-1";SA_NAMESPACE="openkubes-system";POLICY_NAME="ok141-m0a-installer-v7-1.openkubes.io"
BOOTSTRAP_OBJECTS=(
    ("ServiceAccount","serviceaccount",SA_NAME,SA_NAMESPACE),("Role","role",SA_NAME,"caaph-system"),
    ("RoleBinding","rolebinding",SA_NAME,"caaph-system"),("ClusterRole","clusterrole",SA_NAME,None),
    ("ClusterRoleBinding","clusterrolebinding",SA_NAME,None),("ValidatingAdmissionPolicy","validatingadmissionpolicy",POLICY_NAME,None),
    ("ValidatingAdmissionPolicyBinding","validatingadmissionpolicybinding",POLICY_NAME,None),
)
class ExecutionError(ValueError):pass
def sha(p:Path)->str:return "sha256:"+hashlib.sha256(p.read_bytes()).hexdigest()
def expect(a:Any,e:Any,c:str)->None:
    if a!=e:raise ExecutionError(f"{c}: expected {e!r}, got {a!r}")
def read_yaml(p:Path)->dict[str,Any]:
    v=yaml.safe_load(p.read_text())
    if not isinstance(v,dict):raise ExecutionError(f"expected mapping in {p}")
    return v
def resolve(base:Path,ref:dict[str,Any])->Path:
    p=(base/ref["path"]).resolve()
    if SPIKE.resolve() not in p.parents or not p.is_file():raise ExecutionError(f"invalid reference: {ref['path']}")
    expect(sha(p),ref["digest"],ref["path"]);return p
def parse_utc(v:str)->datetime:
    d=datetime.fromisoformat(v.replace("Z","+00:00"))
    if d.tzinfo!=timezone.utc:raise ExecutionError("grant timestamps must be UTC")
    return d
def verify_candidate(path:Path)->tuple[dict[str,Any],dict[str,Path],dict[str,Any],dict[str,Path]]:
    doc=read_yaml(path);s=doc["spec"]
    expect(s["version"],"ok141-m0a-combined-candidate/v7.1","version")
    expect(s["state"],"READY-FOR-FOUR-SEPARATE-EXPLICIT-GRANTS","state")
    refs={k:resolve(path.parent,v) for k,v in s["references"].items()}
    expect(refs["executor"],Path(__file__).resolve(),"executor")
    _,_,base,base_refs=V6.verify_candidate(refs["baseCandidate"])
    derived=PAYLOADS.derive();credential=CREDENTIAL.verify()
    expect((len(derived["administrator"].documents),len(derived["temporaryInstaller"].documents)),(8,11),"partition counts")
    expect(derived["administrator"].semantic_digest,s["submission"]["administratorSemanticDigest"],"admin semantic")
    expect(derived["temporaryInstaller"].semantic_digest,s["submission"]["installerSemanticDigest"],"installer semantic")
    expect(credential["manifestDigest"],s["credential"]["manifestDigest"],"credential manifest")
    expect(s["executionWindow"]["grantsRequired"],["M0A-AP1-v7.1","M0A-C1-v7.1","M0A-A1-v7.1","M0a-I-v7.1"],"grant inventory")
    expect(s["authorization"],{"decision":"NO-GO","mutationAuthorized":False,"administratorPrerequisiteGrantRequired":True,"credentialGrantRequired":True,"admissionBootstrapGrantRequired":True,"installationGrantRequired":True,"retryGranted":False,"rollbackGranted":False,"m0bInstallationGranted":False,"go1Granted":False,"evidencePublicationGranted":False,"targetConvergenceGranted":False,"failureInjectionGranted":False},"authorization")
    return doc,refs,base,base_refs
def verify_grant(candidate_path:Path,grant_path:Path,now:datetime|None=None)->dict[str,Any]:
    candidate,_,_,_=verify_candidate(candidate_path);g=read_yaml(grant_path)["spec"]
    expect(g["version"],"ok141-m0a-combined-grant/v7.1","grant version");expect(g["candidateDigest"],sha(candidate_path),"candidate binding")
    expect((g["authority"],g["decision"],g["mutationAuthorized"]),("github:arashkaffamanesh","GO",True),"grant decision")
    expected=(("administratorPrerequisiteGrant","M0A-AP1-v7.1"),("credentialGrant","M0A-C1-v7.1"),("admissionGrant","M0A-A1-v7.1"),("installationGrant","M0a-I-v7.1"))
    ids=[]
    for field,gate in expected:
        expect((g[field]["gate"],g[field]["granted"]),(gate,True),field);ids.append(g[field]["grantID"])
    if len(set(ids))!=4 or any(not x for x in ids):raise ExecutionError("four distinct non-empty grant IDs required")
    start,end=parse_utc(g["validFrom"]),parse_utc(g["validUntil"])
    if end<=start or (end-start).total_seconds()>candidate["spec"]["executionWindow"]["maximumDurationMinutes"]*60:raise ExecutionError("invalid grant window")
    current=now or datetime.now(timezone.utc)
    if not start<=current<=end:raise ExecutionError("outside grant window")
    expect(g["maximumRuns"],1,"maximum runs")
    output=Path(g["evidenceOutputPath"])
    if not output.is_absolute() or Path("/private/tmp") not in output.resolve().parents:raise ExecutionError("evidence path must be below /private/tmp")
    for f in ("retryGranted","rollbackGranted","targetConvergenceGranted","m0bInstallationGranted","go1Granted","evidencePublicationGranted","failureInjectionGranted"):expect(g[f],False,f)
    return g
def kubectl(k:Path,args:list[str],**kwargs):return V6.V5.kubectl(k,args,**kwargs)
def object_get(k:Path,kind:str,name:str,namespace:str|None,check:bool=False):
    args=["get",kind,name,"--output=json"]
    if namespace:args[1:1]=["--namespace",namespace]
    return kubectl(k,args,check=check)
def ensure_bootstrap_absent(k:Path)->None:
    for _,kind,name,ns in BOOTSTRAP_OBJECTS:
        r=object_get(k,kind,name,ns)
        if r.returncode==0:raise ExecutionError(f"bootstrap object exists: {kind}/{name}")
        if "NotFound" not in r.stderr.decode(errors="replace") and "not found" not in r.stderr.decode(errors="replace"):raise ExecutionError(f"cannot prove bootstrap absence: {kind}/{name}")
def discover_bootstrap(k:Path)->dict[str,str]:
    found={}
    for label,kind,name,ns in BOOTSTRAP_OBJECTS:
        r=object_get(k,kind,name,ns)
        if r.returncode!=0:
            if "NotFound" in r.stderr.decode(errors="replace") or "not found" in r.stderr.decode(errors="replace"):continue
            raise ExecutionError(f"cannot inspect bootstrap: {kind}/{name}")
        obj=json.loads(r.stdout);labels=obj["metadata"].get("labels",{})
        if labels.get("openkubes.io/ticket")!="OK-141" or labels.get("openkubes.io/gate") not in {"M0A-C1-v7.1","M0A-A1-v7.1"}:raise ExecutionError(f"foreign bootstrap ownership: {kind}/{name}")
        found[label]=obj["metadata"]["uid"]
    return found
def cleanup_bootstrap(k:Path,uids:dict[str,str])->dict[str,Any]:
    live=discover_bootstrap(k)
    for label,uid in live.items():
        if uids.get(label) not in (None,uid):raise ExecutionError(f"bootstrap UID changed: {label}")
    for label,kind,name,ns in reversed(BOOTSTRAP_OBJECTS):
        if label not in live:continue
        args=["delete",kind,name,"--wait=true"]
        if ns:args.extend(["--namespace",ns])
        kubectl(k,args)
    if discover_bootstrap(k):raise ExecutionError("temporary bootstrap remains")
    return {"removed":True,"objectCount":len(live),"objectUIDs":live}
def wait_policy(k:Path,timeout:int=60)->dict[str,Any]:
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        p=json.loads(object_get(k,"validatingadmissionpolicy",POLICY_NAME,None,True).stdout);status=p.get("status",{});tc=status.get("typeChecking",{});warnings=tc.get("expressionWarnings")
        if status.get("observedGeneration")==p["metadata"].get("generation") and warnings in (None,[]):return {"observedGeneration":p["metadata"].get("generation"),"expressionWarnings":0}
        time.sleep(2)
    raise ExecutionError("admission type-check timeout")
def temporary_kubeconfig(admin:Path,token:str,candidate:dict[str,Any])->Path:
    cfg=read_yaml(admin);current=cfg["current-context"];context=next(x["context"] for x in cfg["contexts"] if x["name"]==current);cluster=next(x["cluster"] for x in cfg["clusters"] if x["name"]==context["cluster"])
    expect(cluster["server"],candidate["spec"]["target"]["apiServer"],"target server")
    value={"apiVersion":"v1","kind":"Config","clusters":[{"name":"ok-mgmt","cluster":cluster}],"contexts":[{"name":"installer@ok-mgmt","context":{"cluster":"ok-mgmt","user":"installer"}}],"current-context":"installer@ok-mgmt","users":[{"name":"installer","user":{"token":token}}]}
    f=tempfile.NamedTemporaryFile(prefix="ok141-m0a-v71-",suffix=".kubeconfig",delete=False);f.write(yaml.safe_dump(value,sort_keys=False).encode());f.close();Path(f.name).chmod(0o600);return Path(f.name)
def auth_can_i(k:Path,verb:str,resource:str,name:str|None=None,namespace:str|None=None)->bool:return V6.V5.V1.auth_can_i(k,verb,resource,name,namespace)
def authorization_probes(k:Path,documents:list[dict[str,Any]])->dict[str,Any]:
    for item in documents:
        resource,default=V6.V5.V1.RESOURCE_MAP[item["kind"]];ns=item["metadata"].get("namespace",default)
        if not auth_can_i(k,"create",resource,namespace=ns):raise ExecutionError(f"missing create: {resource}")
        if not auth_can_i(k,"get",resource,item["metadata"]["name"],ns):raise ExecutionError(f"missing exact get: {resource}")
    forbidden=(("create","namespaces",None,None),("create","roles.rbac.authorization.k8s.io",None,"caaph-system"),("create","clusterroles.rbac.authorization.k8s.io",None,None),("bind","clusterroles.rbac.authorization.k8s.io","cluster-admin",None),("escalate","clusterroles.rbac.authorization.k8s.io",SA_NAME,None),("get","secrets",None,"caaph-system"),("create","serviceaccounts/token",None,SA_NAMESPACE),("patch","deployments.apps","caaph-controller-manager","caaph-system"),("delete","customresourcedefinitions.apiextensions.k8s.io","helmchartproxies.addons.cluster.x-k8s.io",None),("list","deployments.apps",None,"caaph-system"),("watch","deployments.apps",None,"caaph-system"))
    for verb,res,name,ns in forbidden:
        if auth_can_i(k,verb,res,name,ns):raise ExecutionError(f"negative probe allowed: {verb} {res}")
    exact_cluster=next(x for x in documents if x["kind"]=="MutatingWebhookConfiguration")
    exact_namespaced=next(x for x in documents if x["kind"]=="ConfigMap")
    for item in (exact_cluster,exact_namespaced):
        allowed=kubectl(k,["create","--dry-run=server","--filename","-"],input_bytes=yaml.safe_dump(item,sort_keys=False).encode(),check=False)
        if allowed.returncode!=0:raise ExecutionError(f"exact identity admission dry-run failed: {item['kind']}/{item['metadata']['name']}")
    wrong_cluster=json.loads(json.dumps(exact_cluster));wrong_cluster["metadata"]["name"]="ok141-wrong.openkubes.io"
    wrong_namespaced=json.loads(json.dumps(exact_namespaced));wrong_namespaced["metadata"]["name"]="ok141-wrong"
    for item in (wrong_cluster,wrong_namespaced):
        denied=kubectl(k,["create","--dry-run=server","--filename","-"],input_bytes=yaml.safe_dump(item,sort_keys=False).encode(),check=False)
        if denied.returncode==0 or "OK-141 M0a v7.1 permits only" not in denied.stderr.decode(errors="replace"):raise ExecutionError(f"wrong identity not denied: {item['kind']}")
    return {"createAndExactGetTargets":len(documents),"negativeAuthorizationProbes":len(forbidden),"positiveAdmissionDryRuns":2,"negativeAdmissionProbes":2}
def live_preflight(candidate:dict[str,Any],base:dict[str,Any],base_refs:dict[str,Path],admin:Path)->dict[str,Any]:
    observation=V6.V5.V4.live_preflight(base,base_refs,admin);ensure_bootstrap_absent(admin);return observation|{"v71BootstrapAbsence":len(BOOTSTRAP_OBJECTS)}
def write_evidence(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as f:f.write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
def execute(candidate_path:Path,grant_path:Path,admin:Path,kubectl_bin:Path,output:Path)->dict[str,Any]:
    candidate,refs,base,base_refs=verify_candidate(candidate_path);tool=V6.V5.configure_kubectl(kubectl_bin,base);grant=verify_grant(candidate_path,grant_path)
    expect(output.resolve(),Path(grant["evidenceOutputPath"]).resolve(),"evidence output")
    if output.exists():raise ExecutionError("evidence output exists")
    preflight=live_preflight(candidate,base,base_refs,admin);parts=PAYLOADS.derive();reviewed=V6.V5.INSTALLER.verify_reviewed_object_set(read_yaml(base_refs["installationProtocol"]),base_refs["installationProtocol"])
    temp=None;expires=None;bootstrap_uids={};admin_attempted=False;installer_attempted=False
    evidence={"version":"ok141-m0a-execution-evidence/v7.1","candidateDigest":sha(candidate_path),"grantDigest":sha(grant_path),"grantIDs":[grant[x]["grantID"] for x in ("administratorPrerequisiteGrant","credentialGrant","admissionGrant","installationGrant")],"fixtureDigest":base["spec"]["fixtureDigest"],"toolchain":tool,"target":preflight,"startedAt":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"result":"STARTED","secretMaterialRetained":False}
    try:
        admin_attempted=True;r=kubectl(admin,["create","--filename","-"],input_bytes=parts["administrator"].raw,check=False);evidence["administratorCreate"]=V6.V5.diagnostic(r,"create-exact-admin-8",[admin,kubectl_bin],base)
        if r.returncode!=0:raise ExecutionError("administrator prerequisite create failed")
        inv=V6.V5.V4.exact_object_inventory(admin,reviewed);evidence["postAdministratorInventory"]=inv;expect(inv["present"],8,"administrator created count")
        bootstrap=refs["credentialManifest"].read_bytes()+b"\n---\n"+refs["admissionManifest"].read_bytes();kubectl(admin,["create","--filename","-"],input_bytes=bootstrap)
        bootstrap_uids=discover_bootstrap(admin);expect(set(bootstrap_uids),{x[0] for x in BOOTSTRAP_OBJECTS},"bootstrap inventory");evidence["policy"]=wait_policy(admin)
        requested=datetime.now(timezone.utc);tr=json.loads(kubectl(admin,["--namespace",SA_NAMESPACE,"create","token",SA_NAME,"--duration=10m","--audience",candidate["spec"]["target"]["apiAudience"],"--output=json"]).stdout);token=tr["status"]["token"];expires=parse_utc(tr["status"]["expirationTimestamp"])
        if len(token)<80 or (expires-requested).total_seconds()>610:raise ExecutionError("invalid TokenRequest result")
        evidence["credential"]={"requestedAt":requested.isoformat().replace("+00:00","Z"),"expiresAt":expires.isoformat().replace("+00:00","Z"),"audience":candidate["spec"]["target"]["apiAudience"],"tokenMaterialRetained":False}
        temp=temporary_kubeconfig(admin,token,candidate);token="";evidence["authorizationProbes"]=authorization_probes(temp,parts["temporaryInstaller"].documents)
        parts=PAYLOADS.derive();installer_attempted=True;r=kubectl(temp,["create","--filename","-"],input_bytes=parts["temporaryInstaller"].raw,check=False);evidence["installerCreate"]=V6.V5.diagnostic(r,"create-exact-installer-11",[admin,temp,kubectl_bin],base)
        if r.returncode!=0:raise ExecutionError("installer create failed")
        inv=V6.V5.V4.exact_object_inventory(admin,reviewed);evidence["postSubmissionInventory"]=inv;expect(inv["present"],19,"created object count")
        evidence["readiness"]=V6.V5.V1.wait_ready(admin,base["spec"]["installation"]["readinessTimeoutSeconds"]);evidence["objects"]=V6.V5.V1.object_evidence(admin,reviewed);evidence["result"]="SUCCESS";return evidence
    except Exception as e:evidence.update({"result":"STOP-NOT-SUCCESS","failureType":type(e).__name__,"failure":str(e)});raise
    finally:
        if (admin_attempted or installer_attempted) and "postSubmissionInventory" not in evidence:
            try:evidence["postSubmissionInventory"]=V6.V5.V4.exact_object_inventory(admin,reviewed)
            except Exception as e:evidence["postSubmissionInventory"]={"failureType":type(e).__name__,"failure":str(e)};evidence["result"]="STOP-NOT-SUCCESS"
        try:evidence["bootstrapCleanup"]=cleanup_bootstrap(admin,bootstrap_uids)
        except Exception as e:evidence["bootstrapCleanup"]={"removed":False,"failureType":type(e).__name__,"failure":str(e)};evidence["result"]="STOP-NOT-SUCCESS"
        if temp is not None and expires is not None:
            try:evidence["revocation"]=V6.decisive_probe(temp,expires,candidate["spec"]["credential"]["rejectionDeadlineOffsetSeconds"]);evidence["result"]="STOP-NOT-SUCCESS" if not evidence["revocation"]["tokenRejected"] else evidence["result"]
            except Exception as e:evidence["revocation"]={"tokenRejected":False,"failureType":type(e).__name__,"failure":str(e)};evidence["result"]="STOP-NOT-SUCCESS"
        if temp is not None:temp.unlink(missing_ok=True)
        evidence["finishedAt"]=datetime.now(timezone.utc).isoformat().replace("+00:00","Z");write_evidence(output,evidence)
def main()->int:
    p=argparse.ArgumentParser();p.add_argument("command",choices=("verify","verify-grant","preflight","execute"));p.add_argument("--candidate",type=Path,required=True);p.add_argument("--grant",type=Path);p.add_argument("--kubectl-bin",type=Path);p.add_argument("--admin-kubeconfig",type=Path);p.add_argument("--evidence-output",type=Path);p.add_argument("--execute",action="store_true");a=p.parse_args()
    try:
        c,_,_,_=verify_candidate(a.candidate.resolve());result={"candidateDigest":sha(a.candidate.resolve()),"state":c["spec"]["state"],"mutationAuthorized":False}
        if a.command=="verify-grant":
            if a.grant is None:raise ExecutionError("grant required")
            verify_grant(a.candidate.resolve(),a.grant.resolve());result["grantValidNow"]=True
        elif a.command=="preflight":
            if None in (a.kubectl_bin,a.admin_kubeconfig):raise ExecutionError("preflight requires toolchain and target")
            c,_,base,base_refs=verify_candidate(a.candidate.resolve());tool=V6.V5.configure_kubectl(a.kubectl_bin.resolve(),base);observation=live_preflight(c,base,base_refs,a.admin_kubeconfig.resolve())
            result={"result":"PASS","mutationPerformed":False,"toolchain":tool,"observation":observation}
        elif a.command=="execute":
            if not a.execute or None in (a.grant,a.kubectl_bin,a.admin_kubeconfig,a.evidence_output):raise ExecutionError("execute requires grant toolchain target output and --execute")
            run=execute(a.candidate.resolve(),a.grant.resolve(),a.admin_kubeconfig.resolve(),a.kubectl_bin.resolve(),a.evidence_output.resolve())
            if run["result"]!="SUCCESS" or not run.get("revocation",{}).get("tokenRejected"):raise ExecutionError("execution did not fully succeed")
            result={"result":"SUCCESS","evidenceOutput":str(a.evidence_output)}
        print(json.dumps(result,sort_keys=True,separators=(",",":")));return 0
    except (ExecutionError,OSError,KeyError,TypeError,ValueError,yaml.YAMLError,json.JSONDecodeError,subprocess.SubprocessError) as e:print(f"ERROR: {e}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
