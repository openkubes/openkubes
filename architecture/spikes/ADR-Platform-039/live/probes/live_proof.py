#!/usr/bin/env python3
"""Renderer-driven, fail-closed OK-174 live proof harness.

`probe` writes only a run-specific candidate.  `evidence` is the sole operation
which may replace the canonical evidence after schema and semantic validation.
"""
from __future__ import annotations
import argparse, base64, copy, hashlib, importlib.util, json, os, re, secrets, shlex, subprocess, sys, tempfile, time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import yaml

HERE=Path(__file__).resolve(); LIVE=HERE.parents[1]; SPIKE=LIVE.parent
EVIDENCE_DIR=LIVE/'evidence'; RAW_DIR=EVIDENCE_DIR/'raw'; STATE_DIR=EVIDENCE_DIR/'state'
CANDIDATE=LIVE/'profile'/'developer-workspace-live.yaml'; PROFILE=LIVE/'profile'/'namespace-profile-live.yaml'; FINAL_EVIDENCE=EVIDENCE_DIR/'live-evidence-v1.yaml'
TARGET_CONTEXT='ok-obs-verify-admin@ok-obs-verify'; TARGET_CLUSTER_UID_SHA256='c0d2fe748219faf80f3f8a6858131aed4df2803dc1de1595a01112d9dd166bdc'; # sha256 of the kube-system Namespace UID; the UID itself is not published
NAMESPACE='dw-ok174-proof'; EPHEMERAL_NAMESPACE='dw-ok174-ephemeral'; PROOF_NAMESPACE='ok174-proof-services'; EVIDENCE_NAMESPACE='ok174-evidence'; REGISTRY_PULL_SECRET='ok174-registry-pull'
RUN_LABEL='workspace.openkubes.io/run-id'; OWNER_LABELS={'workspace.openkubes.io/proof':'ok-174','workspace.openkubes.io/owner':'developer-workspace-spike'}
RESULT_NAMES=('source-checkout','fixture-test','known-commit-retrieval','kubernetes-denied','serviceaccount-denied','secret-reference','denied-positive-control','allowed-connectivity','denied-egress','undeclared-port-denied','quota-rejection','runtime-task-opencode','runtime-task-codex','persistent-marker-survives-replacement','secret-no-leak','ephemeral-export-cleanup','cleanup','cluster-health')
OVERLAY_MISMATCHES=('imagePullSecrets operational overlay','run and owner label operational overlays','registry pull Secret materialization outside render','source credential Secret materialization outside render','source CA ConfigMap materialization outside render')
# The canary arrives on stdin (exec -i), never in argv; an empty pattern is an error, not a clean scan.
CANARY_SCAN='p=$(cat); test -n "$p" || exit 8; if grep -a -R -F -e "$p" /workspace /tmp /home/workspace; then exit 9; fi'
def canary_scan(k,raw,name,namespace,pod,canary):
 done=k.result(['exec','-i',f'pod/{pod}','-n',namespace,'-c','runtime','--','sh','-ec',CANARY_SCAN],input_text=canary); cap=capture(raw,name,done)
 expect(done.returncode==0 and not done.stderr.strip(),f'credential canary scan of {pod} found the canary or reported errors'); return cap
def cgroup_limits(resources):
 mem=resources['memory']; cpu=resources['cpu']; units={'Mi':2**20,'Gi':2**30}
 return [str(int(mem[:-2])*units[mem[-2:]]),str(int(cpu[:-1])*100 if cpu.endswith('m') else int(cpu)*100000),'100000']
CAPTURE_REDACTIONS:tuple[str,...]=(); CAPTURE_LEAKS:list[str]=[]
class ProofError(RuntimeError): pass
@dataclass
class Result: name:str; status:str; detail:str; evidence:dict[str,Any]
class Kubectl:
 def __init__(self,runner:Callable[...,subprocess.CompletedProcess]|None=None): self.runner=runner or subprocess.run
 def result(self,args,*,input_text=None,timeout=90): return self.runner(['kubectl',*args],input=input_text,text=True,capture_output=True,timeout=timeout,check=False)
 def run(self,args,**kwargs):
  check=kwargs.pop('check',True); p=self.result(args,**kwargs)
  if check and p.returncode: raise ProofError(f"kubectl failed ({p.returncode}): {' '.join(args)}: {p.stderr[:300]}")
  return p.stdout
 def apply(self,objects): self.run(['apply','-f','-'],input_text='---\n'.join(yaml.safe_dump(x,sort_keys=False) for x in objects))
def expect(ok,msg):
 if not ok: raise ProofError(msg)
def sha(value): return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def implementation_revision(value): expect(bool(re.fullmatch(r'[0-9a-f]{40}',value or '')),'implementation revision must be a full lowercase Git commit'); return value
def digest_image(name):
 value=os.environ.get(name,''); expect(bool(re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',value)),f'{name} must be an immutable image digest'); return value
def images(): return {x:digest_image('OK174_'+x.upper()+'_IMAGE') for x in ('opencode','codex','fixture')}
def inference_url():
 d=yaml.safe_load(PROFILE.read_text())['spec']['capabilities']['capabilityref:inference-shared']['destination']; return f"http://{d['cidr'].split('/')[0]}:{d['port']}"
def selected_model():
 value=os.environ.get('OK174_MODEL','ok174-gpt-oss:20b'); expect(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]*',value)),'OK174_MODEL must be one model identifier'); return value
def live_approved(): expect(os.environ.get('APPROVE_LIVE')=='yes','APPROVE_LIVE=yes is required for live mutation')
def cleanup_approved(): expect(os.environ.get('APPROVE_LIVE_CLEANUP')=='yes','APPROVE_LIVE_CLEANUP=yes is required for cleanup')
def current_target(k):
 path=os.environ.get('KUBECONFIG',''); expect(path and os.pathsep not in path,'KUBECONFIG must select exactly one explicit file')
 expect(Path(path).is_file(),'selected KUBECONFIG file is unreadable')
 context=k.run(['config','current-context']).strip(); expect(context==TARGET_CONTEXT,f'selected context must be {TARGET_CONTEXT}')
 # Kubernetes exposes no Cluster UID object; the stable kube-system Namespace UID is
 # the reviewed cluster-identity pin and is read from the selected API server.
 version=json.loads(k.run(['version','-o','json'])).get('serverVersion',{}).get('gitVersion',''); expect(bool(re.match(r'v\d+\.\d+',version)), 'could not bind target cluster version'); cluster_uid=json.loads(k.run(['get','namespace','kube-system','-o','json'])).get('metadata',{}).get('uid',''); expect(bool(cluster_uid) and sha(cluster_uid)==TARGET_CLUSTER_UID_SHA256,'kube-system UID does not match the reviewed target-cluster pin')
 return {'context':context,'cluster':{'uidSha256':sha(cluster_uid),'version':version}}
def git_clean_revision(revision,runner=subprocess.run):
 # The run's own outputs (raw captures, final evidence) are excluded; everything else must be clean.
 repo=SPIKE.parents[2]; outputs=[f':(exclude){(LIVE/"evidence"/x).relative_to(repo)}' for x in ('raw','live-evidence-v1.yaml')]; head=runner(['git','-C',str(repo),'rev-parse','HEAD'],text=True,capture_output=True,check=False); status=runner(['git','-C',str(repo),'status','--porcelain','--','.',*outputs],text=True,capture_output=True,check=False)
 expect(head.returncode==0 and bool(re.fullmatch(r'[0-9a-f]{40}',head.stdout.strip())),'cannot capture implementation HEAD'); expect(status.returncode==0 and not status.stdout,'implementation checkout is dirty'); expect(head.stdout.strip()==implementation_revision(revision),'supplied revision does not match captured HEAD')
 return {'head':head.stdout.strip(),'worktreeClean':True,'gitStatusSha256':sha(status.stdout),'implementationTreeSha256':renderer().implementation_tree_sha256()}
_RENDERER=None
def renderer():
 global _RENDERER
 if _RENDERER is None:
  spec=importlib.util.spec_from_file_location('ok174_renderer',SPIKE/'verify_developer_workspace_v1.py'); expect(spec and spec.loader,'cannot load DeveloperWorkspace renderer'); _RENDERER=importlib.util.module_from_spec(spec); spec.loader.exec_module(_RENDERER)
 return _RENDERER
def profile_inputs(profile):
 storage=os.environ.get('OK174_STORAGE_CLASS','local-path'); model=selected_model(); expect(storage=='local-path','OK174_STORAGE_CLASS must be local-path')
 profile['spec']['storageClassName']=storage
 for runtime in ('opencode','codex'):
  profile['spec']['runtimeProfiles'][runtime]['image']=images()[runtime]; profile['spec']['runtimeProfiles'][runtime]['envTemplate']['model']=model
 return {'storageClassName':storage,'model':model,'images':images()}
def rendered_workspace(runtime,revision,mode='persistent',workspace_id='ws-ok174-proof'):
 expect(runtime in ('opencode','codex'),'unsupported runtime'); doc=yaml.safe_load(CANDIDATE.read_text()); profile=yaml.safe_load(PROFILE.read_text())
 doc['metadata']['name']='ok174-live-proof' if mode=='persistent' else 'ok174-ephemeral-proof'; doc['spec']['workspaceID']=workspace_id; doc['spec']['source']['revision']=revision; doc['spec']['runtime']['profile']=runtime; doc['spec']['storage']['mode']=mode
 if mode=='ephemeral': doc['spec']['storage']['size']='8Mi'; doc['spec']['lifecycle'].update({'profile':'ephemeral','deletion':'after-retention'})
 profile_inputs(profile); return doc,profile,renderer().render(doc,profile)
def rendered_pair(revision):
 pair={x:rendered_workspace(x,revision) for x in ('opencode','codex')}; left,right=copy.deepcopy(pair['opencode'][0]),copy.deepcopy(pair['codex'][0]); expect(left['spec']['runtime']=={'profile':'opencode'} and right['spec']['runtime']=={'profile':'codex'},'runtime documents do not select the expected profiles'); left['spec']['runtime']['profile']=right['spec']['runtime']['profile']='compared'; expect(left==right,'render documents differ outside spec.runtime.profile'); return pair
def binding_sha(value): return sha(json.dumps(value,sort_keys=True,separators=(',',':')))
def overlay(rendered,run_id):
 objects=copy.deepcopy(rendered['spec']['resources']); ledger=[]
 for item in objects:
  md=item.setdefault('metadata',{}); md.setdefault('labels',{}).update({**OWNER_LABELS,RUN_LABEL:run_id}); paths=['metadata.labels']
  if item.get('kind')=='Deployment':
   pod=item['spec']['template']['spec']; pod['imagePullSecrets']=[{'name':REGISTRY_PULL_SECRET}]; item['spec']['template'].setdefault('metadata',{}).setdefault('labels',{}).update({**OWNER_LABELS,RUN_LABEL:run_id}); paths += ['spec.template.metadata.labels','spec.template.spec.imagePullSecrets']
  ledger.append({'kind':item.get('kind'),'name':md.get('name'),'namespace':md.get('namespace',md.get('name','')),'overlays':paths})
 return objects,ledger
def normalized(item):
 value=copy.deepcopy(item); value.pop('status',None); md=value.get('metadata',{})
 for key in ('uid','resourceVersion','generation','creationTimestamp','managedFields'): md.pop(key,None)
 annotations=md.get('annotations',{}); annotations.pop('kubectl.kubernetes.io/last-applied-configuration',None); annotations.pop('deployment.kubernetes.io/revision',None)
 if value.get('kind')=='PersistentVolumeClaim':
  for key in ('pv.kubernetes.io/bind-completed','pv.kubernetes.io/bound-by-controller','volume.beta.kubernetes.io/storage-provisioner','volume.kubernetes.io/storage-provisioner','volume.kubernetes.io/selected-node'): annotations.pop(key,None)
  md.pop('finalizers',None); spec=value.get('spec',{}); spec.pop('volumeName',None)
  if spec.get('volumeMode')=='Filesystem': spec.pop('volumeMode')
  for key in ('dataSource','dataSourceRef'):
   if spec.get(key) is None: spec.pop(key,None)
 if not annotations: md.pop('annotations',None)
 if value.get('kind')=='Namespace':
  labels=md.get('labels',{}); name=md.get('name');
  if labels.get('kubernetes.io/metadata.name')==name: labels.pop('kubernetes.io/metadata.name')
  if not labels: md.pop('labels',None)
  value.pop('spec',None)
 if value.get('kind')=='Deployment':
  spec=value['spec']
  for key in ('progressDeadlineSeconds','revisionHistoryLimit'): spec.pop(key,None)
  template=spec['template']; template.get('metadata',{}).pop('creationTimestamp',None); pod=template['spec']
  for key in ('dnsPolicy','enableServiceLinks','restartPolicy','schedulerName','serviceAccount','terminationGracePeriodSeconds'): pod.pop(key,None)
  for key in ('hostNetwork','hostPID','hostIPC'):
   if pod.get(key) is False: pod.pop(key)
  for container in pod.get('initContainers',[])+pod.get('containers',[]):
   for key in ('imagePullPolicy','terminationMessagePath','terminationMessagePolicy'): container.pop(key,None)
  for volume in pod.get('volumes',[]):
   if 'configMap' in volume: volume['configMap'].pop('defaultMode',None)
   if volume.get('persistentVolumeClaim',{}).get('readOnly') is False: volume['persistentVolumeClaim'].pop('readOnly')
 return value
def controller_default(item): return item.get('kind')=='ServiceAccount' and item.get('metadata',{}).get('name')=='default' # created by kube-controller-manager in every namespace
def readback_contract(k,namespace,expected,raw=None,prefix=''):
 hashes={}; captures={}
 for kind in ('Namespace','Deployment','NetworkPolicy','ResourceQuota','PersistentVolumeClaim','ServiceAccount','LimitRange'):
  wanted=[x for x in expected if x.get('kind')==kind]
  if not wanted: continue
  args=['get','namespace',namespace,'-o','json'] if kind=='Namespace' else ['get',kind.lower(),'-n',namespace,'-o','json']
  if raw is None: text=k.run(args)
  else:
   done,binding=run_captured(k,raw,f'readback-{prefix}-{kind.lower()}',args); expect(done.returncode==0,f'{kind} read-back failed'); text=done.stdout; captures[kind]=binding
  decoded=json.loads(text); actual=[decoded] if kind=='Namespace' else [x for x in decoded.get('items',[]) if not controller_default(x)]; seen={x.get('metadata',{}).get('name'):normalized(x) for x in actual}
  expect(set(seen)=={x['metadata']['name'] for x in wanted},f'{kind} read-back contains missing or unrendered objects')
  for item in wanted:
   want=normalized(item); got=seen.get(item['metadata']['name']); expect(got is not None,f"rendered {kind}/{item['metadata']['name']} was not read back"); expect(got==want,f"rendered {kind}/{item['metadata']['name']} differs from read-back"); hashes[f"{kind}/{item['metadata']['name']}"]=sha(json.dumps(got,sort_keys=True))
 return {'hashes':hashes,'captures':captures} if raw is not None else hashes
def runtime_has_credential(deployment,env_name='GIT_AUTH_TOKEN'): return any(e.get('name')==env_name for c in deployment['spec']['template']['spec'].get('containers',[]) for e in c.get('env',[]))
def rbac_list_denied(text):
 allowed_resources={'selfsubjectreviews.authentication.k8s.io','selfsubjectaccessreviews.authorization.k8s.io','selfsubjectrulesreviews.authorization.k8s.io'}; allowed_urls=re.compile(r'^/(?:api|apis|healthz|livez|readyz|openapi)(?:/\*)?$|^/version/?$|^/openid/v1/jwks/?$|^/\.well-known/openid-configuration/?$'); saw=False
 for raw in text.splitlines():
  line=raw.strip()
  if not line or line.lower().startswith(('warning:','resources ')): continue
  groups=re.findall(r'\[([^]]*)\]',line); prefix=line.split('[',1)[0].strip().lower()
  if len(groups)<3:return False
  verbs={x for x in groups[-1].split() if x}; saw=True
  if '*' in verbs:return False
  if prefix:
   if prefix not in allowed_resources or verbs!={'create'} or groups[0].strip():return False
  else:
   urls={x for x in groups[0].split() if x};
   if not urls or verbs!={'get'} or not all(allowed_urls.fullmatch(x) for x in urls):return False
 return bool(text.strip()) and (saw or all(not x.strip() or x.lower().lstrip().startswith(('warning:','resources ')) for x in text.splitlines()))
def denied_egress(returncode,stderr): return returncode in (7,28) and bool(stderr)
def exact_container_image_id(pod,name,approved):
 container=next((x for x in pod.get('spec',{}).get('containers',[]) if x.get('name')==name),None); status=next((x for x in pod.get('status',{}).get('containerStatuses',[]) if x.get('name')==name),None); expect(container and container.get('image')==approved,f'{name} image differs from approved profile'); image=(status or {}).get('imageID',''); digest=re.escape(approved.rsplit('@',1)[1]); expect(bool(re.fullmatch(r'(?:[^\s]+@)?'+digest,image)),f'{name} imageID does not exactly bind approved digest'); return image
def exact_image_id(pod,approved): return exact_container_image_id(pod,'runtime',approved)
def configure_capture_redaction(secret):
 global CAPTURE_REDACTIONS,CAPTURE_LEAKS
 CAPTURE_REDACTIONS=(secret,base64.b64encode(secret.encode()).decode()) if secret else (); CAPTURE_LEAKS=[]
def redacted(value,name):
 text=value
 for secret in CAPTURE_REDACTIONS:
  if secret and secret in text: CAPTURE_LEAKS.append(name); text=text.replace(secret,'[REDACTED-CREDENTIAL-CANARY]')
 return text
def node_view(x): return {'metadata':{'uid':sha(x.get('metadata',{}).get('uid',''))},'spec':{'unschedulable':x.get('spec',{}).get('unschedulable',False)},'status':{'conditions':[{k:c.get(k,'') for k in ('type','status','reason')} for c in x.get('status',{}).get('conditions',[])]}}
def id_view(x): return {'kind':x.get('kind'),'metadata':{k:x.get('metadata',{}).get(k) for k in ('name','uid')}}
def pod_view(x):
 st=x.get('status',{}); cs=lambda key:[{k:c.get(k) for k in ('name','imageID','restartCount','ready')} for c in st.get(key,[])]
 return {**id_view(x),'spec':{'containers':[{k:c.get(k) for k in ('name','image')} for c in x.get('spec',{}).get('containers',[])]},'status':{'phase':st.get('phase'),'reason':st.get('reason'),'message':st.get('message'),'initContainerStatuses':cs('initContainerStatuses'),'containerStatuses':cs('containerStatuses')}}
def minimized(argv,stdout,name):
 """Keep only the fields the verifier needs, so public evidence carries no node, network or inventory detail."""
 a=[x for x in argv if isinstance(x,str)]
 try:
  if a[1:2]==['exec'] and a[-1]=='env': return ''.join(sorted(l.split('=',1)[0]+'\n' for l in stdout.splitlines() if '=' in l))
  if a[-1].endswith('/api/tags'): return 'sha256:'+sha(stdout)+'\n' if stdout else stdout
  if a[1:3]==['delete','--raw'] and stdout: return json.dumps(id_view(json.loads(stdout)))
  if a[1:2]==['get'] and '-o' in a and a[a.index('-o')+1]=='json' and stdout:
   d=json.loads(stdout); kind=a[2]
   if name.startswith('readback-'): return json.dumps(normalized(d) if kind=='namespace' else {'items':[normalized(x) for x in d.get('items',[])]})
   view={'nodes':node_view,'pod':pod_view,'pods':pod_view,'pv':id_view,'namespace':id_view,'pvc':lambda x:{**id_view(x),'spec':{'volumeName':x.get('spec',{}).get('volumeName')}},'configmap':lambda x:{**id_view(x),'data':x.get('data',{})},'events':lambda x:{k:x.get(k) for k in ('type','reason','message')}}.get(kind)
   if view: return json.dumps({'items':[view(x) for x in d['items']]} if 'items' in d else view(d))
 except (ValueError,KeyError,IndexError,TypeError): pass
 return stdout
def capture(root,name,completed):
 root.mkdir(parents=True,exist_ok=True); path=root/f'{name}.json'; record={'argv':completed.args,'returncode':completed.returncode,'stdout':minimized(completed.args,completed.stdout or '',name),'stderr':completed.stderr}; encoded=redacted(json.dumps(record,sort_keys=True),name); path.write_text(encoded)
 stored=capture_path(path)
 return {'path':stored,'sha256':sha(path.read_bytes())}
def capture_path(path):
 try: return str(path.relative_to(EVIDENCE_DIR))
 except ValueError: return str(path) # Unit tests intentionally use isolated temporary roots.
def run_captured(k,root,name,args,**kwargs):
 p=k.result(args,**kwargs); return p,capture(root,name,p)
def state_path(run_id): return STATE_DIR/f'{run_id}.json'
def candidate_path(run_id): return EVIDENCE_DIR/f'{run_id}.candidate.json'
def write_state(state): STATE_DIR.mkdir(parents=True,exist_ok=True); path=state_path(state['runID']); path.write_text(json.dumps(state,sort_keys=True)); return path
def read_state(run_id):
 try: state=json.loads(state_path(run_id).read_text())
 except (OSError,json.JSONDecodeError) as exc: raise ProofError('persisted apply state is unavailable or corrupt') from exc
 expect(state.get('runID')==run_id and state.get('phase') in ('applying','applied','probed'),'persisted state is not an OK-174 run ledger'); return state
def read_secret_fd(name='OK174_REGISTRY_PASSWORD_FD'):
 fd=os.environ.get(name,''); expect(bool(re.fullmatch(r'\d+',fd)) ,f'{name} must be an inherited numeric descriptor')
 with os.fdopen(os.dup(int(fd)),'rb') as handle: value=handle.read().rstrip(b'\r\n')
 expect(value,f'{name} supplied an empty secret'); return value
def tls_material():
 """Use an openssl subprocess in a guarded temporary directory; return no private hashes."""
 with tempfile.TemporaryDirectory(prefix='ok174-tls-') as temp:
  root=Path(temp); root.chmod(0o700); ca_key,ca,server_key,csr,cert,conf=(root/x for x in ('ca.key','ca.crt','server.key','server.csr','server.crt','openssl.cnf'))
  conf.write_text('[req]\ndistinguished_name=dn\nreq_extensions=req_ext\n[dn]\n[req_ext]\nsubjectAltName=@alt\n[alt]\nDNS.1=git-fixture.ok174-proof-services.svc.cluster.local\nDNS.2=git-fixture\n')
  for p in (ca_key,server_key,conf): p.touch(exist_ok=True); p.chmod(0o600)
  commands=(['openssl','genrsa','-out',str(ca_key),'2048'],['openssl','req','-x509','-new','-nodes','-key',str(ca_key),'-sha256','-days','1','-subj','/CN=ok174-fixture-ca','-out',str(ca)],['openssl','genrsa','-out',str(server_key),'2048'],['openssl','req','-new','-key',str(server_key),'-subj','/CN=git-fixture.ok174-proof-services.svc.cluster.local','-config',str(conf),'-out',str(csr)],['openssl','x509','-req','-in',str(csr),'-CA',str(ca),'-CAkey',str(ca_key),'-CAcreateserial','-out',str(cert),'-days','1','-sha256','-extensions','req_ext','-extfile',str(conf)])
  for command in commands:
   done=subprocess.run(command,text=True,capture_output=True,check=False); expect(done.returncode==0,f'openssl TLS generation failed: {done.stderr[:200]}')
  return {'ca':ca.read_text(),'cert':cert.read_text(),'key':server_key.read_text(),'caSha256':sha(ca.read_bytes()),'certSha256':sha(cert.read_bytes())}
def proof_service_objects(run_id,tls,token):
 labels={**OWNER_LABELS,RUN_LABEL:run_id}; meta=lambda name:{'name':name,'namespace':PROOF_NAMESPACE,'labels':labels}
 objects=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':PROOF_NAMESPACE,'labels':labels}},{'apiVersion':'v1','kind':'Namespace','metadata':{'name':EVIDENCE_NAMESPACE,'labels':labels}},{'apiVersion':'v1','kind':'ConfigMap','metadata':meta('git-fixture-ca'),'data':{'ca.crt':tls['ca']}},{'apiVersion':'v1','kind':'Secret','metadata':meta('git-fixture-tls'),'type':'kubernetes.io/tls','stringData':{'tls.crt':tls['cert'],'tls.key':tls['key']}},{'apiVersion':'v1','kind':'Secret','metadata':meta('git-fixture-auth'),'type':'Opaque','stringData':{'token':token.decode()}}]
 for name,image,ports in (('git-fixture',images()['fixture'],[8443,8080]),('mcp-fixture',images()['fixture'],[8081]),('denied-fixture',images()['fixture'],[8081])):
  container={'name':name,'image':image,'ports':[{'containerPort':p} for p in ports]}; spec={'imagePullSecrets':[{'name':REGISTRY_PULL_SECRET}],'containers':[container]}
  container['env']=[{'name':'FIXTURE_MODE','value':name.split('-')[0]}]
  if name=='git-fixture': container['env'].append({'name':'GIT_AUTH_TOKEN','valueFrom':{'secretKeyRef':{'name':'git-fixture-auth','key':'token'}}}); container['volumeMounts']=[{'name':'tls','mountPath':'/var/run/ok174-git-tls','readOnly':True}]; spec['volumes']=[{'name':'tls','secret':{'secretName':'git-fixture-tls'}}]
  objects += [{'apiVersion':'apps/v1','kind':'Deployment','metadata':meta(name),'spec':{'selector':{'matchLabels':{'app':name}},'template':{'metadata':{'labels':{**labels,'app':name}},'spec':spec}}},{'apiVersion':'v1','kind':'Service','metadata':meta(name),'spec':{'selector':{'app':name},'ports':[{'name':f'p{p}','port':p,'targetPort':p} for p in ports]}}]
 objects.append({'apiVersion':'v1','kind':'Pod','metadata':meta('network-control'),'spec':{'restartPolicy':'Never','imagePullSecrets':[{'name':REGISTRY_PULL_SECRET}],'containers':[{'name':'control','image':images()['fixture'],'command':['sleep','infinity']}]}}); return objects
def workspace_support_objects(run_id,tls,token,namespace=NAMESPACE):
 labels={**OWNER_LABELS,RUN_LABEL:run_id}; return [{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'git-fixture-ca','namespace':namespace,'labels':labels},'data':{'ca.crt':tls['ca']}},{'apiVersion':'v1','kind':'Secret','metadata':{'name':'workspace-git-auth','namespace':namespace,'labels':labels},'type':'Opaque','stringData':{'token':token.decode()}}]
def registry_pull_object(namespace,run_id,username,password):
 registry=images()['opencode'].split('/',1)[0]; secret=password.decode(); auth=base64.b64encode(f'{username}:{secret}'.encode()).decode(); config={'auths':{registry:{'username':username,'password':secret,'auth':auth}}}; data=base64.b64encode(json.dumps(config,separators=(',',':')).encode()).decode()
 return {'apiVersion':'v1','kind':'Secret','metadata':{'name':REGISTRY_PULL_SECRET,'namespace':namespace,'labels':{**OWNER_LABELS,RUN_LABEL:run_id}},'type':'kubernetes.io/dockerconfigjson','data':{'.dockerconfigjson':data}}
def copy_secret(k,name,source,target,run_id):
 item=json.loads(k.run(['get','secret',name,'-n',source,'-o','json'])); expect(bool(item.get('data')),'secret copy source has no data'); k.apply([{'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':target,'labels':{**OWNER_LABELS,RUN_LABEL:run_id}},'type':item.get('type','Opaque'),'data':item['data']}])
def copy_pull_secret(k,source,target,run_id): copy_secret(k,REGISTRY_PULL_SECRET,source,target,run_id)
def secret_value(k,name,namespace,key):
 item=json.loads(k.run(['get','secret',name,'-n',namespace,'-o','json'])); encoded=item.get('data',{}).get(key,''); expect(bool(encoded),f'{name}/{key} is absent'); return base64.b64decode(encoded,validate=True)
def namespace_uid(k,name):
 uid=json.loads(k.run(['get','namespace',name,'-o','json'])).get('metadata',{}).get('uid',''); expect(uid,f'namespace {name} has no UID'); return uid
def selected_ready_pod(k,namespace,selector):
 items=json.loads(k.run(['get','pods','-n',namespace,'-l',selector,'-o','json'])).get('items',[]); ready=[x for x in items if x.get('status',{}).get('phase')=='Running' and x.get('status',{}).get('containerStatuses') and all(s.get('ready') for s in x['status']['containerStatuses'])]; expect(len(ready)==1,f'expected one Ready pod for {selector}'); return ready[0]
def stable_node_health(data):
 return sorted(({'uid':item.get('metadata',{}).get('uid'),'unschedulable':item.get('spec',{}).get('unschedulable',False),'conditions':sorted(({'type':x.get('type'),'status':x.get('status'),'reason':x.get('reason','')} for x in item.get('status',{}).get('conditions',[])),key=lambda x:x['type'] or '')} for item in data.get('items',[])),key=lambda x:x['uid'] or '')
def health_hash(k,raw,name):
 done,binding=run_captured(k,raw,name,['get','nodes','-o','json']); expect(done.returncode==0,'cluster health capture failed'); return sha(json.dumps(stable_node_health(json.loads(minimized(done.args,done.stdout,name))),sort_keys=True)),binding
def wait_model(k,raw,model):
 deadline=time.monotonic()+900; last=None
 while time.monotonic()<deadline:
  last=k.result(['exec','pod/network-control','-n',PROOF_NAMESPACE,'--','curl','-fsS','--max-time','5',inference_url()+'/api/tags'])
  if last.returncode==0:
   try: names={x.get('name') for x in json.loads(last.stdout).get('models',[])}
   except json.JSONDecodeError: names=set()
   if model in names: return capture(raw,'ollama-model-ready',last)
  time.sleep(5)
 if last is not None: capture(raw,'ollama-model-not-ready',last)
 raise ProofError(f'external inference does not serve model {model}')
def apply(k,revision,git_runner=subprocess.run):
 live_approved(); target=current_target(k); git=git_clean_revision(revision,git_runner); started_at=now(); run_id=secrets.token_hex(12); tls=tls_material(); registry_password=read_secret_fd(); registry_username=os.environ.get('OK174_REGISTRY_USERNAME',''); expect(bool(registry_username),'OK174_REGISTRY_USERNAME is required'); token=secrets.token_urlsafe(32).encode(); model=selected_model(); raw=RAW_DIR/run_id; health,health_capture=health_hash(k,raw,'cluster-health-before')
 ledger={'runID':run_id,'phase':'applying','startedAt':started_at,'revision':revision,'target':target,'git':git,'namespaceUIDs':{}}; write_state(ledger)
 proof_objects=proof_service_objects(run_id,tls,token); proof_namespaces=[x for x in proof_objects if x.get('kind')=='Namespace']
 for namespace in proof_namespaces:
  k.apply([namespace]); name=namespace['metadata']['name']; ledger['namespaceUIDs'][name]=namespace_uid(k,name); write_state(ledger)
 k.apply([registry_pull_object(PROOF_NAMESPACE,run_id,registry_username,registry_password)])
 k.apply([x for x in proof_objects if x.get('kind')!='Namespace'])
 for name in ('git-fixture','mcp-fixture','denied-fixture'): k.run(['rollout','status',f'deployment/{name}','-n',PROOF_NAMESPACE,'--timeout=300s'],timeout=330)
 k.run(['wait','--for=condition=Ready','pod/network-control','-n',PROOF_NAMESPACE,'--timeout=300s'],timeout=330); wait_model(k,raw,model); fixture_pod=selected_ready_pod(k,PROOF_NAMESPACE,'app=git-fixture'); known=k.run(['exec',f"pod/{fixture_pod['metadata']['name']}",'-n',PROOF_NAMESPACE,'--','cat','/srv/git/KNOWN_COMMIT']).strip(); expect(bool(re.fullmatch(r'[0-9a-f]{40}',known)),'fixture did not expose a full known commit')
 pair=rendered_pair(known); objects,overlays=overlay(pair['opencode'][2],run_id); workspace_namespace=next(x for x in objects if x.get('kind')=='Namespace'); k.apply([workspace_namespace]); ledger['namespaceUIDs'][NAMESPACE]=namespace_uid(k,NAMESPACE); write_state(ledger); k.apply([registry_pull_object(NAMESPACE,run_id,registry_username,registry_password)]); k.apply(workspace_support_objects(run_id,tls,token)); k.apply([x for x in objects if x.get('kind')!='Namespace']); k.run(['rollout','status','deployment/workspace','-n',NAMESPACE,'--timeout=300s'],timeout=330); uids=ledger['namespaceUIDs']
 documents={name:value[0] for name,value in pair.items()}; renders={name:value[2] for name,value in pair.items()}; bindings={'documentsSha256':binding_sha(documents),'rendersSha256':binding_sha(renders),'appliedObjectsSha256':binding_sha(objects),'overlaysSha256':binding_sha(overlays)}
 state={'runID':run_id,'phase':'applied','startedAt':started_at,'revision':revision,'knownCommit':known,'target':target,'git':git,'documents':documents,'renders':renders,'bindings':bindings,'profileInputs':{'storageClassName':pair['opencode'][1]['spec']['storageClassName'],'model':pair['opencode'][1]['spec']['runtimeProfiles']['opencode']['envTemplate']['model'],'images':images()},'expectedObjects':{'opencode':objects},'overlays':overlays,'namespaceUIDs':uids,'pullSecretSource':NAMESPACE,'tls':{'caSha256':tls['caSha256'],'certSha256':tls['certSha256']},'healthBefore':{'sha256':health,'capture':health_capture},'canarySha256':sha(token)}; write_state(state); return state
def unique_ready_pod(k,namespace,approved):
 items=json.loads(k.run(['get','pods','-n',namespace,'-l','app=developer-workspace','-o','json'])).get('items',[]); ready=[x for x in items if x.get('status',{}).get('phase')=='Running' and x.get('status',{}).get('containerStatuses') and all(s.get('ready') for s in x['status']['containerStatuses'])]; expect(len(ready)==1,'expected exactly one Ready rendered workspace pod'); exact_image_id(ready[0],approved); return ready[0]
def shell_inner(command):
 """Codex reports shell tool calls as `<shell> -lc '<command>'`; compare the inner command."""
 try: parts=shlex.split(command)
 except ValueError: return command
 return parts[2] if len(parts)==3 and parts[0].rsplit('/',1)[-1] in ('bash','sh','zsh') and parts[1] in ('-c','-lc') else command
def runtime_command(runtime,verification):
 edit="printf '%s\\n' 'developer workspace fixture modified by agent' > README.md"
 prompt=f"You are in /workspace. Make exactly two shell tool calls, one per command, each command exactly as written with nothing added, removed or combined. Call 1: {edit} Call 2: {shlex.join(verification)} Then report both exit codes."
 # Codex's own Landlock/seccomp sandbox cannot run inside the unprivileged, cap-dropped pod;
 # the pod's securityContext and NetworkPolicy are the isolation boundary instead.
 return ['opencode','run','--format','json',prompt] if runtime=='opencode' else ['codex','exec','--json','--sandbox','danger-full-access','--skip-git-repo-check',prompt]
def event_command(event):
 if not isinstance(event,dict): return ''
 if isinstance(event.get('command'),str): return event['command']
 if isinstance(event.get('cmd'),str): return event['cmd']
 for v in event.values():
  found=event_command(v)
  if found:return found
 return ''
def dict_nodes(value,completed=False):
 if isinstance(value,dict):
  kind=str(value.get('type','')).lower(); completed=completed or kind.endswith(('.completed','_completed'))
  yield value,completed
  for item in value.values(): yield from dict_nodes(item,completed)
 if isinstance(value,list):
  for item in value: yield from dict_nodes(item,completed)
def typed_tool_records(runtime,events):
 records=[]
 if runtime=='opencode':
  sessions={x.get('sessionID') for x in events if x.get('type') in ('step_start','tool_use','step_finish')}; expect(len(sessions)==1 and next(iter(sessions)), 'opencode stream lacks one stable sessionID'); expect(any(x.get('type')=='step_start' for x in events) and any(x.get('type')=='step_finish' and x.get('part',{}).get('reason')=='stop' for x in events),'opencode stream lacks start/stop lifecycle')
  for event in events:
   if event.get('type')!='tool_use' or not isinstance(event.get('part'),dict): continue
   part=event['part']; state=part.get('state',{}); identifier=part.get('callID'); tool=part.get('tool'); expect(isinstance(identifier,str) and identifier and isinstance(tool,str) and isinstance(state,dict),'opencode tool_use identity is invalid')
   if state.get('status')=='completed' and isinstance(state.get('input'),dict) and 'output' in state:
    record={'id':identifier,'kind':'tool_use','tool':tool.lower(),'command':event_command(state['input'])}; output=str(state['output'])
    if record['tool'] in ('bash','shell'):
     metadata=state.get('metadata'); exit_code=metadata.get('exit') if isinstance(metadata,dict) else None; expect(type(exit_code) is int,'opencode shell result lacks a native integer exit status')
     reported=re.search(r'\bexit(?:ed)?(?:\s+with)?(?:\s+code)?\s*[:=]?\s*(-?\d+)\b',output,re.I); expect(not reported or int(reported.group(1))==exit_code,'opencode shell output contradicts its native exit status')
     expect(not (exit_code==0 and re.search(r'\b(?:command failed|tool error|error: command)\b',output,re.I)),'opencode shell reports failure with a zero exit status')
     if exit_code!=0: continue
    records.append(record)
 else:
  expect(runtime=='codex','unknown runtime event schema'); expect(any(x.get('type')=='turn.completed' for x in events),'codex stream lacks turn.completed')
  for event in events:
   if event.get('type')!='item.completed' or not isinstance(event.get('item'),dict): continue
   item=event['item']; identifier=item.get('id'); kind=item.get('type'); status=item.get('status'); expect(isinstance(identifier,str) and identifier,'codex item.completed identity is invalid')
   if kind=='command_execution' and status=='completed' and item.get('exit_code')==0 and 'aggregated_output' in item: records.append({'id':identifier,'kind':kind,'tool':'exec','command':shell_inner(str(item.get('command','')))})
   if kind=='file_change' and status=='completed' and isinstance(item.get('changes'),list) and item['changes']: records.append({'id':identifier,'kind':kind,'tool':'file_change','command':' '.join(str(x.get('path','')) for x in item['changes'] if isinstance(x,dict))})
 return records
def is_fixture_edit(item):
 cmd=item['command']
 return item['tool'] in ('write','edit','patch','file_change') or ('README.md' in cmd and bool(re.search(r'>\s*README\.md|sed\s+-i|\btee\b|apply_patch',cmd)))
def validate_agent_events(runtime,output,verification=None):
 events=[]
 for line in output.splitlines():
  try: value=json.loads(line)
  except json.JSONDecodeError: continue
  if isinstance(value,dict): events.append(value)
 records=typed_tool_records(runtime,events); expect(bool(records) and len({x['id'] for x in records})==len(records),f'{runtime} emitted no uniquely identified successful tool results'); edit_indexes=[i for i,item in enumerate(records) if is_fixture_edit(item)]; edit=bool(edit_indexes); expect(edit,f'{runtime} typed events do not prove a fixture edit tool result')
 if verification is not None:
  exact=shlex.join(verification); verification_indexes=[i for i,x in enumerate(records) if x['command']==exact and x['tool'] in ('bash','shell','exec')]; expect(verification_indexes and min(edit_indexes)<max(verification_indexes),f'{runtime} typed results omit an ordered successful exact verification exec')
 return {'eventCount':len(events),'typedToolEventCount':len(records),'editObserved':edit,'verificationCommand':shlex.join(verification) if verification else None}
def capture_pod_logs(k,root,namespace,pod,runtime):
 bindings={}; observed,pod_binding=run_captured(k,root,f'logs-{runtime}-pod',['get','pod',pod,'-n',namespace,'-o','json'],timeout=60); expect(observed.returncode==0,'required pod status capture failed'); value=json.loads(observed.stdout); statuses=value.get('status',{}).get('initContainerStatuses',[])+value.get('status',{}).get('containerStatuses',[]); expect({x.get('name') for x in statuses}=={'checkout','runtime'} and all(x.get('restartCount')==0 for x in statuses),'restarted checkout/runtime container would leave uncaptured previous logs'); bindings['pod']=pod_binding
 for container in ('checkout','runtime'):
  done,binding=run_captured(k,root,f'logs-{runtime}-{container}-current',['logs',f'pod/{pod}','-n',namespace,'-c',container],timeout=60); expect(done.returncode==0,f'required {container} log capture failed'); bindings[f'{container}-current']=binding
 return bindings
def exec_capture(k,raw,name,namespace,pod,command,timeout=90):
 container=['-c','runtime'] if namespace in (NAMESPACE,EPHEMERAL_NAMESPACE) else []
 return run_captured(k,raw,name,['exec',f'pod/{pod}','-n',namespace,*container,'--',*command],timeout=timeout)
def source_matches(actual,known): expect(actual==known,'workspace HEAD differs from knownCommit')
def quota_rejects_storage(p): expect(p.returncode!=0 and 'requests.storage' in p.stderr,'quota rejection did not name requests.storage')
def persistence_binding(expected,observed,old,new,pvc_before,pvc_after,pv_before,pv_after):
 expect(expected==observed,'persistent marker hash changed'); expect(old!=new,'persistent replacement did not replace pod'); expect(pvc_before==pvc_after,'PVC UID changed'); expect(pv_before==pv_after,'PV UID changed')
def scan_no_canary(canary,values):
 for label,value in values.items(): expect(canary not in (value.decode(errors='replace') if isinstance(value,bytes) else str(value)),f'credential canary found in {label}')
def required_result(name,status,detail,evidence): expect(name in RESULT_NAMES,f'unknown result {name}'); return asdict(Result(name,status,detail,evidence))
def validate_run(run):
 expect(run.get('kind')=='DeveloperWorkspaceProbeRun','results are not a probe-run envelope'); results=run.get('results',[]); expect([x.get('name') for x in results]==list(RESULT_NAMES),'probe-run must contain all 18 ordered named results')
 expect(set(run.get('bindings',{}))=={'documentsSha256','rendersSha256','appliedObjectsSha256','overlaysSha256','cleanupLedgerSha256'} and all(re.fullmatch(r'[0-9a-f]{64}',x) for x in run['bindings'].values()),'probe-run render/cleanup bindings are incomplete')
 for result in results: expect(result.get('status') in ('PASS','FAIL') and bool(result.get('detail')) and isinstance(result.get('evidence'),dict),f"result {result.get('name')} lacks concrete evidence")
 for binding in run.get('rawEvidence',{}).values():
  path=Path(binding['path']); path=(EVIDENCE_DIR/path) if not path.is_absolute() else path; expect(path.is_file() and sha(path.read_bytes())==binding['sha256'],f'raw capture binding failed for {path}')
def result_or_failure(name,action):
 try:
  detail,evidence=action(); return required_result(name,'PASS',detail,evidence)
 except (ProofError,OSError,ValueError,json.JSONDecodeError,subprocess.TimeoutExpired) as exc: return required_result(name,'FAIL',str(exc),{'failure':str(exc)})
def runtime_security(k,state,runtime,raw,pod):
 name=pod['metadata']['name']; captures={}
 absent,cap=exec_capture(k,raw,f'credential-absence-{runtime}',NAMESPACE,name,['sh','-ec','test -z "${GIT_AUTH_TOKEN+x}" && test -z "${GIT_SSL_CAINFO+x}"']); expect(absent.returncode==0,f'{runtime} live runtime exposes source credential settings'); captures['credentialAbsence']=cap
 environment,cap=exec_capture(k,raw,f'environment-{runtime}',NAMESPACE,name,['env']); expect(environment.returncode==0 and not any(secret in environment.stdout for secret in CAPTURE_REDACTIONS),f'{runtime} live environment contains the source credential canary'); captures['environment']=cap
 api,cap=exec_capture(k,raw,f'kubernetes-denied-{runtime}',NAMESPACE,name,['curl','-ksS','-o','/dev/null','--connect-timeout','3','--max-time','3','https://kubernetes.default.svc']); expect(denied_egress(api.returncode,api.stderr),f'{runtime} Kubernetes API probe was not connect-refused or timed out'); captures['api']=cap
 mount,cap=exec_capture(k,raw,f'serviceaccount-mount-{runtime}',NAMESPACE,name,['sh','-ec','test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token && test ! -e /var/run/secrets/kubernetes.io/serviceaccount/ca.crt']); expect(mount.returncode==0,f'{runtime} has mounted service-account credentials'); captures['serviceAccountMount']=cap
 auth,cap=run_captured(k,raw,f'can-i-list-{runtime}',['auth','can-i','--list','-n',NAMESPACE,f'--as=system:serviceaccount:{NAMESPACE}:workspace']); expect(auth.returncode==0 and rbac_list_denied(auth.stdout),f'{runtime} service account exceeds discovery-only authority'); captures['canIList']=cap
 allowed=(('git',['curl','-kfsS','https://git-fixture.ok174-proof-services.svc.cluster.local:8443/known-commit']),('mcp',['curl','-fsS','http://mcp-fixture.ok174-proof-services.svc.cluster.local:8081/mcp']),('ollama',['curl','-fsS',inference_url()+'/api/tags']))
 for endpoint,command in allowed:
  done,cap=exec_capture(k,raw,f'allowed-{endpoint}-{runtime}',NAMESPACE,name,command); expect(done.returncode==0,f'{runtime} allowed {endpoint} probe failed'); captures['allowed-'+endpoint]=cap
 for endpoint,url in (('denied','http://denied-fixture.ok174-proof-services.svc.cluster.local:8081'),('undeclared','http://git-fixture.ok174-proof-services.svc.cluster.local:8080')):
  done,cap=exec_capture(k,raw,f'{endpoint}-{runtime}',NAMESPACE,name,['curl','-sS','--connect-timeout','3','--max-time','3',url]); expect(denied_egress(done.returncode,done.stderr),f'{runtime} {endpoint} probe was not connect-refused or timed out'); captures[endpoint]=cap
 limits,cap=exec_capture(k,raw,f'cgroup-limits-{runtime}',NAMESPACE,name,['cat','/sys/fs/cgroup/memory.max','/sys/fs/cgroup/cpu.max']); wanted=cgroup_limits(state['documents'][runtime]['spec']['resources']); expect(limits.returncode==0 and limits.stdout.split()==wanted,f'{runtime} kernel cgroup limits differ from the rendered CPU/memory limits'); captures['cgroupLimits']=cap
 captures['canaryScan']=canary_scan(k,raw,f'canary-scan-{runtime}',NAMESPACE,name,CAPTURE_REDACTIONS[0] if CAPTURE_REDACTIONS else '')
 return {'credentialAbsent':True,'apiDenied':True,'serviceAccountTokenAbsent':True,'rbacDiscoveryOnly':True,'allowedPorts':[8443,11434,8081],'deniedPort':8081,'undeclaredPort':8080,'cgroupLimits':wanted,'captures':captures}
def runtime_probe(k,state,runtime,raw):
 expected,_=overlay(state['renders'][runtime],state['runID']); deployment=next(x for x in expected if x.get('kind')=='Deployment'); expect(not runtime_has_credential(deployment),'runtime credential is present in rendered Deployment'); pod=unique_ready_pod(k,NAMESPACE,images()[runtime]); verification=state['documents'][runtime]['spec']['verification']['command']; logs={}
 try:
  readback=readback_contract(k,NAMESPACE,expected,raw,runtime); security=runtime_security(k,state,runtime,raw,pod)
  before,bcap=exec_capture(k,raw,f'before-{runtime}',NAMESPACE,pod['metadata']['name'],['sh','-ec','sha256sum /workspace/README.md']); expect(before.returncode==0 and before.stdout.strip(),f'{runtime} pre-agent content capture failed')
  version,versioncap=exec_capture(k,raw,f'version-{runtime}',NAMESPACE,pod['metadata']['name'],[runtime,'--version']); expect(version.returncode==0 and version.stdout.strip(),f'{runtime} version capture failed')
  agent,acap=exec_capture(k,raw,f'agent-{runtime}',NAMESPACE,pod['metadata']['name'],runtime_command(runtime,verification),660); expect(agent.returncode==0,f'{runtime} agent command failed'); events=validate_agent_events(runtime,agent.stdout,verification)
  verify,vcap=exec_capture(k,raw,f'verify-{runtime}',NAMESPACE,pod['metadata']['name'],verification); expect(verify.returncode==0,f'{runtime} post-agent verification command failed'); diff,dcap=exec_capture(k,raw,f'diff-{runtime}',NAMESPACE,pod['metadata']['name'],['git','-C','/workspace','diff','--','README.md']); expect(diff.returncode==0 and bool(diff.stdout.strip()),f'{runtime} did not produce an independently observable fixture diff'); marker,mcap=exec_capture(k,raw,f'marker-{runtime}',NAMESPACE,pod['metadata']['name'],['sh','-ec','sha256sum /workspace/README.md']); expect(marker.returncode==0 and marker.stdout.strip(),f'{runtime} marker capture failed'); expect(before.stdout.split()[0]!=marker.stdout.split()[0],f'{runtime} did not change fixture content')
 finally: logs=capture_pod_logs(k,raw,NAMESPACE,pod['metadata']['name'],runtime)
 return {'podUID':pod['metadata']['uid'],'podName':pod['metadata']['name'],'approvedImage':images()[runtime],'imageID':exact_image_id(pod,images()[runtime]),'runtimeVersion':version.stdout.strip(),'verificationCommand':shlex.join(verification),'beforeSha256':before.stdout.split()[0],'afterSha256':marker.stdout.split()[0],'readback':readback,'agent':events,'security':security,'markerSha256':marker.stdout.split()[0],'captures':{'logs':logs,'before':bcap,'version':versioncap,'agent':acap,'verification':vcap,'diff':dcap,'marker':mcap}}
def probe(k,state):
 revalidated=git_clean_revision(state['revision']); expect(revalidated==state['git'],'implementation revision binding changed since apply'); raw=RAW_DIR/state['runID']; results=[]; runtime={}; replacement={}; add=lambda name,action:results.append(result_or_failure(name,action)); canary=''; canary_error=''
 try: canary=secret_value(k,'workspace-git-auth',NAMESPACE,'token').decode(); expect(sha(canary)==state['canarySha256'],'live Git canary no longer matches apply state')
 except (ProofError,ValueError,json.JSONDecodeError) as exc: canary_error=str(exc)
 configure_capture_redaction(canary)
 def pod(): return unique_ready_pod(k,NAMESPACE,images()['opencode'])
 def checkout():
  p=pod(); done,cap=exec_capture(k,raw,'source-head',NAMESPACE,p['metadata']['name'],['git','-C','/workspace','rev-parse','HEAD']); expect(done.returncode==0,'cannot read workspace HEAD'); source_matches(done.stdout.strip(),state['knownCommit']); return 'workspace checkout equals fixture knownCommit',{'commit':done.stdout.strip(),'captures':{'head':cap}}
 def fixture():
  p=pod(); command=state['documents']['opencode']['spec']['verification']['command']; done,cap=exec_capture(k,raw,'fixture-test-before-agent',NAMESPACE,p['metadata']['name'],command); expect(done.returncode!=0,'fixture test unexpectedly passes before agent mutation'); return 'fixture test is initially red',{'test':'README fixture','captures':{'beforeMutation':cap}}
 def known():
  p=pod(); done,cap=exec_capture(k,raw,'known-commit',NAMESPACE,p['metadata']['name'],['curl','-kfsS','https://git-fixture.ok174-proof-services.svc.cluster.local:8443/known-commit']); expect(done.returncode==0,'known commit endpoint failed'); source_matches(done.stdout.strip(),state['knownCommit']); return 'TLS source endpoint reports the checkout knownCommit; init checkout proves CA trust',{'commit':done.stdout.strip(),'captures':{'knownCommit':cap}}
 add('source-checkout',checkout); add('fixture-test',fixture); add('known-commit-retrieval',known)
 def kube():
  p=pod(); done,cap=exec_capture(k,raw,'kubernetes-denied',NAMESPACE,p['metadata']['name'],['curl','-ksS','-o','/dev/null','--connect-timeout','3','--max-time','3','https://kubernetes.default.svc']); expect(denied_egress(done.returncode,done.stderr),'Kubernetes API probe was not connect-refused or timed out'); return 'no ambient Kubernetes API connectivity',{'httpCode':'000','curlExit':done.returncode,'captures':{'api':cap}}
 def serviceaccount():
  p=pod(); done,cap=exec_capture(k,raw,'serviceaccount-denied',NAMESPACE,p['metadata']['name'],['sh','-ec','test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token && test ! -e /var/run/secrets/kubernetes.io/serviceaccount/ca.crt']); expect(done.returncode==0,'service-account credentials are mounted'); auth,acap=run_captured(k,raw,'can-i-list',['auth','can-i','--list','-n',NAMESPACE,f'--as=system:serviceaccount:{NAMESPACE}:workspace']); expect(auth.returncode==0 and rbac_list_denied(auth.stdout),'service account exposes undeclared authority'); return 'token absent and can-i --list lacks broad authority',{'checks':2,'captures':{'mount':cap,'canIList':acap}}
 def secretref():
  d=next(x for x in state['renders']['opencode']['spec']['resources'] if x.get('kind')=='Deployment'); expect(not runtime_has_credential(d),'GIT_AUTH_TOKEN reached runtime'); checkout=d['spec']['template']['spec']['initContainers'][0]; expect(any(x.get('name')=='GIT_AUTH_TOKEN' for x in checkout.get('env',[])),'checkout is missing Git secret reference'); return 'Git secret is checkout-init-only',{'secretRef':'workspace-git-auth','runtimeHasSecret':False}
 add('kubernetes-denied',kube); add('serviceaccount-denied',serviceaccount); add('secret-reference',secretref)
 def control():
  done,cap=run_captured(k,raw,'network-control',['get','pod','network-control','-n',PROOF_NAMESPACE,'-o','json']); expect(done.returncode==0,'network control pod unavailable'); control_pod=json.loads(done.stdout); uid=control_pod.get('metadata',{}).get('uid',''); expect(uid,'network control pod UID missing'); fixture_image=exact_container_image_id(control_pod,'control',images()['fixture'])
  captures={'pod':cap}; api,api_cap=exec_capture(k,raw,'control-kubernetes-api',PROOF_NAMESPACE,'network-control',['curl','-ksS','-o','/dev/null','-w','%{http_code}','--connect-timeout','3','--max-time','5','https://kubernetes.default.svc']); expect(api.returncode==0 and api.stdout.strip() in ('401','403'),'network control did not reach Kubernetes API transport'); captures['kubernetes-api']=api_cap
  git_auth_url='https://git-fixture:8443/workspace-fixture.git/info/refs?service=git-upload-pack'
  for name,extra in (('git-auth-absent',[]),('git-auth-wrong',['-H','Authorization: Bearer intentionally-wrong'])):
   auth,auth_cap=exec_capture(k,raw,'control-'+name,PROOF_NAMESPACE,'network-control',['curl','-ksS','-o','/dev/null','-w','%{http_code}',*extra,git_auth_url]); expect(auth.returncode==0 and auth.stdout.strip()=='401',f'Git fixture did not reject {name} credential control'); captures[name]=auth_cap
  for name,url in (('git-undeclared','http://git-fixture:8080/known-commit'),('mcp','http://mcp-fixture:8081/mcp'),('denied','http://denied-fixture:8081/mcp')):
   p,p_cap=exec_capture(k,raw,f'control-{name}',PROOF_NAMESPACE,'network-control',['curl','-fsS','--max-time','5',url]); expect(p.returncode==0,f'network control cannot reach {name}'); captures[name]=p_cap
  return 'control proves API transport, credential rejection, and Git 8080, MCP 8081 and denied fixture 8081 answers before denial claims',{'controlPodUID':uid,'approvedFixtureImage':images()['fixture'],'fixtureImageID':fixture_image,'apiHttpCode':api.stdout.strip(),'captures':captures}
 def allowed():
  p=pod(); captures={}; commands=(('git',['curl','-kfsS','https://git-fixture.ok174-proof-services.svc.cluster.local:8443/known-commit']),('mcp',['curl','-fsS','http://mcp-fixture.ok174-proof-services.svc.cluster.local:8081/mcp']),('ollama',['curl','-fsS',inference_url()+'/api/tags']))
  for name,command in commands:
   done,cap=exec_capture(k,raw,f'allowed-{name}',NAMESPACE,p['metadata']['name'],command); expect(done.returncode==0,f'allowed {name} connectivity failed'); captures[name]=cap
  return 'declared TLS Git, MCP and inference connections work',{'ports':[8443,11434,8081],'inferenceEndpoint':inference_url(),'captures':captures}
 def deny(name,endpoint):
  p=pod(); done,cap=exec_capture(k,raw,name,NAMESPACE,p['metadata']['name'],['curl','-sS','--max-time','3',endpoint]); expect(denied_egress(done.returncode,done.stderr),f'{name} did not fail with curl 7 or 28'); evidence={'endpoint':endpoint,'captures':{'curl':cap}}
  if name=='undeclared-port': evidence['ports']=[8080]
  return 'undeclared destination was connection-denied',evidence
 add('denied-positive-control',control); add('allowed-connectivity',allowed); add('denied-egress',lambda:deny('denied-egress','http://denied-fixture.ok174-proof-services.svc.cluster.local:8081')); add('undeclared-port-denied',lambda:deny('undeclared-port','http://git-fixture.ok174-proof-services.svc.cluster.local:8080'))
 def quota():
  rendered=rendered_workspace('opencode',state['knownCommit'],workspace_id='ws-ok174-quota')[2]['spec']['resources']; pvc=next(x for x in rendered if x.get('kind')=='PersistentVolumeClaim'); pvc['metadata']['name']='oversized-storage'; pvc['metadata']['namespace']=NAMESPACE; pvc['spec']['resources']['requests']['storage']='100Ti'; done,cap=run_captured(k,raw,'quota-rejection',['apply','-f','-'],input_text=yaml.safe_dump(pvc,sort_keys=False)); quota_rejects_storage(done); return 'oversized second PVC rejected by requests.storage quota',{'resourceQuota':'workspace-bounds','exceededResource':'requests.storage','captures':{'apply':cap}}
 add('quota-rejection',quota)
 for name in ('opencode','codex'):
  def agent(name=name):
   if name=='codex':
    pod_name=selected_ready_pod(k,NAMESPACE,'app=developer-workspace')['metadata']['name']; pvc_done,pvc_cap=run_captured(k,raw,'pvc-before',['get','pvc','workspace','-n',NAMESPACE,'-o','json']); expect(pvc_done.returncode==0,'persistent PVC unavailable before replacement'); pvc=json.loads(pvc_done.stdout); pv_name=pvc['spec'].get('volumeName',''); expect(pv_name,'PVC is not bound before replacement'); pv_done,pv_cap=run_captured(k,raw,'pv-before',['get','pv',pv_name,'-o','json']); expect(pv_done.returncode==0,'persistent PV unavailable before replacement'); marker_done,marker_cap=exec_capture(k,raw,'persistence-marker-write',NAMESPACE,pod_name,['sh','-ec',f"printf '%s\\n' '{state['runID']}' > /workspace/.ok174-persistence && sha256sum /workspace/.ok174-persistence"]); expect(marker_done.returncode==0,'could not write persistent replacement marker'); reset,reset_cap=exec_capture(k,raw,'fixture-reset-before-codex',NAMESPACE,pod_name,['sh','-ec',"printf '%s\\n' 'developer workspace fixture' > /workspace/README.md"]); expect(reset.returncode==0,'could not reset fixture before Codex agent')
    replacement.update({'pvcUID':pvc['metadata']['uid'],'pvName':pv_name,'pvUID':json.loads(pv_done.stdout)['metadata']['uid'],'markerSha256':marker_done.stdout.split()[0],'captures':{'pvcBefore':pvc_cap,'pvBefore':pv_cap,'markerWrite':marker_cap,'fixtureReset':reset_cap}}); objects,_=overlay(state['renders']['codex'],state['runID']); k.apply(objects); rollout=k.result(['rollout','status','deployment/workspace','-n',NAMESPACE,'--timeout=300s'],timeout=330)
    if rollout.returncode: capture(raw,'codex-rollout-events',k.result(['get','events','-n',NAMESPACE,'-o','json'])); raise ProofError('runtime swap to the Codex render did not roll out: '+rollout.stderr[:200])
   evidence=runtime_probe(k,state,name,raw); runtime[name]=evidence
   return 'agent mutation, exact tool event, independent verification and image binding observed',evidence
  add('runtime-task-'+name,agent)
 def persistence():
  old,new=runtime.get('opencode',{}).get('podUID',''),runtime.get('codex',{}).get('podUID',''); expect(old and new and replacement,'runtime replacement did not record identities'); pod_name=selected_ready_pod(k,NAMESPACE,'app=developer-workspace')['metadata']['name']; marker_done,marker_cap=exec_capture(k,raw,'persistence-marker-read',NAMESPACE,pod_name,['sha256sum','/workspace/.ok174-persistence']); expect(marker_done.returncode==0,'replacement cannot read persistent marker'); pvc_done,pvc_cap=run_captured(k,raw,'pvc-after',['get','pvc','workspace','-n',NAMESPACE,'-o','json']); expect(pvc_done.returncode==0,'persistent PVC unavailable after replacement'); pvc=json.loads(pvc_done.stdout); pv_done,pv_cap=run_captured(k,raw,'pv-after',['get','pv',replacement['pvName'],'-o','json']); expect(pv_done.returncode==0,'persistent PV unavailable after replacement'); persistence_binding(replacement['markerSha256'],marker_done.stdout.split()[0],old,new,replacement['pvcUID'],pvc['metadata']['uid'],replacement['pvUID'],json.loads(pv_done.stdout)['metadata']['uid']); state['persistentPVUID']=replacement['pvUID']; captures={**replacement['captures'],'markerRead':marker_cap,'pvcAfter':pvc_cap,'pvAfter':pv_cap}; return 'replacement retains marker and PVC/PV identity',{'markerSha256':replacement['markerSha256'],'oldPodUID':old,'newPodUID':new,'pvcUID':replacement['pvcUID'],'pvUID':replacement['pvUID'],'captures':captures}
 def no_leak():
  expect(not canary_error,canary_error); expect(not CAPTURE_LEAKS,'credential canary was found and redacted in raw captures: '+','.join(sorted(set(CAPTURE_LEAKS)))); values={'render':json.dumps(state['renders']),'argv':json.dumps(sys.argv),'raw':''.join(x.read_text(errors='replace') for x in raw.glob('*.json'))}; scan_no_canary(canary,values); pod_name=selected_ready_pod(k,NAMESPACE,'app=developer-workspace')['metadata']['name']; cap=canary_scan(k,raw,'runtime-writable-canary-scan',NAMESPACE,pod_name,canary); expect(not CAPTURE_LEAKS,'credential canary was found and redacted in writable-mount scan'); return 'bounded scan found no canary; checkout-only writable mounts are not shared with runtime',{'scanned':'bounded-output-logs-runtime-writable-mounts-render-argv','canarySha256':state['canarySha256'],'captures':{'runtimeWritableMounts':cap}}
 add('persistent-marker-survives-replacement',persistence)
 def ephemeral():
  _,_,render=rendered_workspace('opencode',state['knownCommit'],mode='ephemeral',workspace_id='ws-ok174-ephemeral'); objects,_=overlay(render,state['runID']); namespace=next(x for x in objects if x.get('kind')=='Namespace'); k.apply([namespace]); uid=namespace_uid(k,EPHEMERAL_NAMESPACE); state['namespaceUIDs'][EPHEMERAL_NAMESPACE]=uid; state['ephemeralNamespaceUID']=uid; write_state(state); copy_pull_secret(k,state['pullSecretSource'],EPHEMERAL_NAMESPACE,state['runID']); copy_secret(k,'workspace-git-auth',NAMESPACE,EPHEMERAL_NAMESPACE,state['runID']); ca=json.loads(k.run(['get','configmap','git-fixture-ca','-n',NAMESPACE,'-o','json'])); k.apply([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'git-fixture-ca','namespace':EPHEMERAL_NAMESPACE,'labels':{**OWNER_LABELS,RUN_LABEL:state['runID']}},'data':ca['data']}]); k.apply([x for x in objects if x.get('kind')!='Namespace']); k.run(['rollout','status','deployment/workspace','-n',EPHEMERAL_NAMESPACE,'--timeout=300s'],timeout=330); p=unique_ready_pod(k,EPHEMERAL_NAMESPACE,images()['opencode']); readback=readback_contract(k,EPHEMERAL_NAMESPACE,objects,raw,'ephemeral'); logs=capture_pod_logs(k,raw,EPHEMERAL_NAMESPACE,p['metadata']['name'],'ephemeral'); scan_cap=canary_scan(k,raw,'ephemeral-canary-scan',EPHEMERAL_NAMESPACE,p['metadata']['name'],CAPTURE_REDACTIONS[0] if CAPTURE_REDACTIONS else ''); export,export_cap=exec_capture(k,raw,'ephemeral-export',EPHEMERAL_NAMESPACE,p['metadata']['name'],['sh','-ec',f"printf '%s\\n' '{state['runID']}' > /workspace/export.marker && sha256sum /workspace/export.marker"]); expect(export.returncode==0,'could not export ephemeral marker before pressure'); marker=export.stdout.split()[0]; k.apply([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'ephemeral-proof','namespace':EVIDENCE_NAMESPACE,'labels':{**OWNER_LABELS,RUN_LABEL:state['runID']}},'data':{'markerSha256':marker,'sourceNamespaceUID':uid}}]); exported,xcap=run_captured(k,raw,'ephemeral-export-readback',['get','configmap','ephemeral-proof','-n',EVIDENCE_NAMESPACE,'-o','json']); expect(exported.returncode==0 and json.loads(exported.stdout).get('data')=={'markerSha256':marker,'sourceNamespaceUID':uid},'ephemeral marker export read-back differs'); fill,fcap=exec_capture(k,raw,'ephemeral-fill',EPHEMERAL_NAMESPACE,p['metadata']['name'],['sh','-ec','(dd if=/dev/zero of=/workspace/fill bs=1M count=32 conv=fsync || true) >/tmp/ok174-fill.log 2>&1 &']); expect(fill.returncode==0,'could not start ephemeral size-limit pressure'); deadline=time.monotonic()+180; evicted=None
  while time.monotonic()<deadline:
   current=k.result(['get','pod',p['metadata']['name'],'-n',EPHEMERAL_NAMESPACE,'-o','json']); evicted=current
   if current.returncode==0 and json.loads(current.stdout).get('status',{}).get('reason')=='Evicted': break
   time.sleep(3)
  status=json.loads(evicted.stdout).get('status',{}) if evicted is not None and evicted.returncode==0 else {}; message=status.get('message',''); expect(status.get('reason')=='Evicted' and bool(re.search(r'workspace',message,re.I)) and bool(re.search(r'8Mi',message,re.I)),'ephemeral pod was not evicted for the workspace 8Mi emptyDir limit'); ecap=capture(raw,'ephemeral-evicted',evicted); before_delete,before_delete_cap=run_captured(k,raw,'ephemeral-before-delete',['get','namespace',EPHEMERAL_NAMESPACE,'-o','json']); expect(before_delete.returncode==0 and json.loads(before_delete.stdout).get('metadata',{}).get('uid')==uid,'ephemeral namespace UID changed before deletion'); deleted=uid_delete(k,EPHEMERAL_NAMESPACE,uid); delete_cap=capture(raw,'ephemeral-delete',deleted); expect(deleted_uid(deleted)==uid,'ephemeral namespace UID-precondition delete failed'); absent=wait_namespace_absent(k,EPHEMERAL_NAMESPACE); acap=capture(raw,'ephemeral-namespace-absent',absent); expect(absent.returncode!=0,'ephemeral namespace remains after UID-precondition delete'); state['namespaceUIDs'].pop(EPHEMERAL_NAMESPACE); write_state(state); return 'workspace 8Mi emptyDir limit evicted pod, marker exported, namespace UID-deleted',{'namespaceUID':uid,'markerSha256':marker,'exportReadBack':True,'belowLimitReady':True,'namespaceAbsent':True,'evicted':True,'evictionMessage':message,'sizeLimit':'8Mi','readback':readback,'podName':p['metadata']['name'],'captures':{'logs':logs,'canaryScan':scan_cap,'export':export_cap,'exportReadBack':xcap,'fill':fcap,'evicted':ecap,'beforeDelete':before_delete_cap,'delete':delete_cap,'namespaceAbsent':acap}}
 ephemeral_result=result_or_failure('ephemeral-export-cleanup',ephemeral); add('secret-no-leak',no_leak); results.append(ephemeral_result)
 def cleanup():
  cleanup_approved(); deleted=clean_workspaces(k,state,True,raw); captures=deleted['captures']
  for namespace in state['namespaceUIDs']:
   absent,cap=run_captured(k,raw,'cleanup-after-'+namespace,['get','namespace',namespace,'-o','json']); expect(absent.returncode!=0,f'namespace remains after cleanup: {namespace}'); captures['after-'+namespace]=cap
  pvs,cap=run_captured(k,raw,'cleanup-pvs',['get','pv','-o','json']); expect(pvs.returncode==0 and not any(x.get('metadata',{}).get('uid')==deleted['pvUID'] for x in json.loads(pvs.stdout).get('items',[])),'reclaimed PV UID remains after cleanup'); captures['pvs']=cap
  return 'state-recorded namespace/PV UIDs removed',{'deletedNamespaceUIDs':deleted['namespaces'],'reclaimedPVUID':deleted['pvUID'],'captures':captures}
 add('cleanup',cleanup)
 def health():
  after,cap=health_hash(k,raw,'cluster-health-after'); expect(after==state['healthBefore']['sha256'],'normalized cluster health changed'); return 'normalized cluster health unchanged',{'beforeSha256':state['healthBefore']['sha256'],'afterSha256':after,'captures':{'before':state['healthBefore']['capture'],'after':cap}}
 add('cluster-health',health)
 state['bindings']['cleanupLedgerSha256']=binding_sha({'namespaceUIDs':state['namespaceUIDs'],'persistentPVUID':state.get('persistentPVUID',''),'ephemeralNamespaceUID':state.get('ephemeralNamespaceUID','')}); index={p.stem:{'path':capture_path(p),'sha256':sha(p.read_bytes())} for p in raw.glob('*.json')}; run={'kind':'DeveloperWorkspaceProbeRun','runID':state['runID'],'startedAt':state['startedAt'],'finishedAt':now(),'bindings':state['bindings'],'results':results,'rawEvidence':index,'overlays':state['overlays'],'mismatches':list(OVERLAY_MISMATCHES),'failures':[x['detail'] for x in results if x['status']!='PASS']}; validate_run(run); candidate_path(state['runID']).write_text(json.dumps(run,sort_keys=True)); state['phase']='probed'; state['finishedAt']=run['finishedAt']; write_state(state); return run
def uid_delete(k,namespace,uid):
 """kubectl has no UID-precondition flag; DeleteOptions.preconditions is the API mechanism."""
 body=json.dumps({'apiVersion':'v1','kind':'DeleteOptions','preconditions':{'uid':uid},'propagationPolicy':'Foreground'})
 return k.result(['delete','--raw',f'/api/v1/namespaces/{namespace}','-f','-'],input_text=body,timeout=60)
def wait_namespace_absent(k,namespace,timeout=300):
 deadline=time.monotonic()+timeout
 while True:
  absent=k.result(['get','namespace',namespace,'-o','json'])
  if absent.returncode!=0 and 'NotFound' in absent.stderr or time.monotonic()>=deadline: return absent
  time.sleep(3)
def deleted_uid(done): return json.loads(done.stdout).get('metadata',{}).get('uid','') if done.returncode==0 else ''
def clean_workspaces(k,state,approve_checked=False,raw=None):
 if not approve_checked: cleanup_approved()
 deleted={}; captures={}
 for namespace,uid in state['namespaceUIDs'].items():
  if raw is None: expect(namespace_uid(k,namespace)==uid,f'refusing cleanup: namespace {namespace} UID changed')
  else:
   observed,cap=run_captured(k,raw,'cleanup-before-'+namespace,['get','namespace',namespace,'-o','json']); expect(observed.returncode==0 and json.loads(observed.stdout).get('metadata',{}).get('uid')==uid,f'refusing cleanup: namespace {namespace} UID changed'); captures['before-'+namespace]=cap
  removed=uid_delete(k,namespace,uid); expect(deleted_uid(removed)==uid,f'UID-precondition cleanup failed for {namespace}: {removed.stderr[:200]}')
  if raw is not None: captures['delete-'+namespace]=capture(raw,'cleanup-delete-'+namespace,removed)
  deleted[namespace]=uid
 for namespace in deleted: expect(wait_namespace_absent(k,namespace).returncode!=0,f'namespace remains after cleanup: {namespace}')
 pvuid=state.get('persistentPVUID',''); expect(pvuid or state.get('phase')=='applying','persistent PV UID was not recorded; cleanup cannot prove reclaim'); deadline=time.monotonic()+180; present=bool(pvuid)
 while time.monotonic()<deadline:
  pvs=json.loads(k.run(['get','pv','-o','json'])).get('items',[]); present=any(x.get('metadata',{}).get('uid')==pvuid for x in pvs)
  if not present: break
  time.sleep(3)
 expect(not present,'persistent PV UID remains after cleanup')
 if raw is not None:
  final_pvs,cap=run_captured(k,raw,'cleanup-pvs',['get','pv','-o','json']); expect(final_pvs.returncode==0 and not any(x.get('metadata',{}).get('uid')==pvuid for x in json.loads(final_pvs.stdout).get('items',[])),'persistent PV UID remains in final cleanup read-back'); captures['pvs']=cap
 return {'namespaces':deleted,'pvUID':pvuid,'captures':captures}
def final_evidence(state,candidate):
 complete=all(x['status']=='PASS' for x in candidate['results']); refs=state['profileInputs']['images']
 return {'apiVersion':'evidence.openkubes.io/v1alpha1','kind':'DeveloperWorkspaceLiveEvidence','spec':{'status':'PASS' if complete else 'REVISE','context':state['target']['context'],'cluster':state['target']['cluster'],'revision':state['revision'],'knownCommit':state['knownCommit'],'model':state['profileInputs']['model'],'imageReferences':refs,'imageDigests':{k:v.rsplit('@',1)[1] for k,v in refs.items()},'storageProfile':{'name':state['profileInputs']['storageClassName'],'provisioner':'rancher.io/local-path','reclaimPolicy':'Delete','volumeBindingMode':'WaitForFirstConsumer','persistentCapacityEnforced':False},'results':candidate['results'],'rawEvidence':candidate['rawEvidence'],'mismatches':list(OVERLAY_MISMATCHES),'secretValuesIncluded':False,'unsupported':[],'run':{'runID':state['runID'],'startedAt':candidate['startedAt'],'finishedAt':candidate['finishedAt'],'gitHead':state['git']['head'],'worktreeClean':state['git']['worktreeClean'],'gitStatusSha256':state['git']['gitStatusSha256'],'implementationTreeSha256':state['git']['implementationTreeSha256'],**candidate['bindings']}}}
def write_evidence(state):
 try: candidate=json.loads(candidate_path(state['runID']).read_text())
 except (OSError,json.JSONDecodeError) as exc: raise ProofError('probe candidate is unavailable or corrupt') from exc
 validate_run(candidate); expect(candidate.get('runID')==state['runID'] and candidate.get('startedAt')==state['startedAt'] and candidate.get('bindings')==state['bindings'],'candidate does not belong to persisted apply state'); revalidated=git_clean_revision(state['revision']); expect(revalidated==state['git'],'implementation revision binding changed since probe'); evidence=final_evidence(state,candidate)
 try: renderer().validate_live_evidence(evidence,EVIDENCE_DIR)
 except Exception as exc: raise ProofError(f'candidate failed schema/semantic live-evidence validation: {exc}') from exc
 FINAL_EVIDENCE.write_text(yaml.safe_dump(evidence,sort_keys=False)); return evidence
def render_to(output,revision):
 old={k:os.environ.get(k) for k in ('OK174_OPENCODE_IMAGE','OK174_CODEX_IMAGE','OK174_FIXTURE_IMAGE')}
 try:
  for key,letter in (('OK174_OPENCODE_IMAGE','a'),('OK174_CODEX_IMAGE','b'),('OK174_FIXTURE_IMAGE','c')): os.environ.setdefault(key,f'example.invalid/{key.lower()}@sha256:{letter*64}')
  pair=rendered_pair(revision); output.write_text('---\n'.join(yaml.safe_dump(x,sort_keys=False) for runtime in ('opencode','codex') for x in pair[runtime][2]['spec']['resources'])); return pair
 finally:
  for key,value in old.items(): os.environ.pop(key,None) if value is None else os.environ.__setitem__(key,value)
NEGATIVE_EVIDENCE=EVIDENCE_DIR/'negative-controls-v1.yaml'
NEGATIVE_CONTROLS=('runtime-credential','serviceaccount-token','rbac-discovery-only','denied-egress','undeclared-port','storage-quota','secret-scan')
def negative_controls(k,state):
 """Break each probe's precondition on the live cluster: the probe must go red, then green again after the revert."""
 live_approved(); cleanup_approved(); expect(current_target(k)['cluster']['uidSha256']==TARGET_CLUSTER_UID_SHA256,'target cluster changed since apply')
 expect(git_clean_revision(state['revision'])==state['git'],'implementation revision binding changed since apply')
 raw=RAW_DIR/state['runID']; canary=secret_value(k,'workspace-git-auth',NAMESPACE,'token').decode(); configure_capture_redaction(canary)
 def pod(): return selected_ready_pod(k,NAMESPACE,'app=developer-workspace')['metadata']['name']
 def rollout(): k.run(['rollout','status','deployment/workspace','-n',NAMESPACE,'--timeout=300s'],timeout=330)
 def patch(kind,name,kind_of_patch,body): k.run(['patch',kind,name,'-n',NAMESPACE,'--type',kind_of_patch,'-p',json.dumps(body)])
 def allow_egress(name,app,port): k.apply([{'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name,'namespace':NAMESPACE,'labels':{**OWNER_LABELS,RUN_LABEL:state['runID']}},'spec':{'podSelector':{'matchLabels':{'app':'developer-workspace'}},'policyTypes':['Egress'],'egress':[{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':PROOF_NAMESPACE}},'podSelector':{'matchLabels':{'app':app}}}],'ports':[{'protocol':'TCP','port':port}]}]}}])
 expected,_=overlay(state['renders']['opencode'],state['runID'])
 def credential(tag):
  done,cap=exec_capture(k,raw,f'neg-credential-{tag}',NAMESPACE,pod(),['sh','-ec','test -z "${GIT_AUTH_TOKEN+x}"'])
  try: readback_contract(k,NAMESPACE,expected); drift=False
  except ProofError: drift=True
  return done.returncode==0 and not drift,{'env':cap,'readbackDrift':drift}
 def token(tag):
  done,cap=exec_capture(k,raw,f'neg-token-{tag}',NAMESPACE,pod(),['sh','-ec','test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token'])
  return done.returncode==0,{'mount':cap}
 def rbac(tag):
  done,cap=run_captured(k,raw,f'neg-rbac-{tag}',['auth','can-i','--list','-n',NAMESPACE,f'--as=system:serviceaccount:{NAMESPACE}:workspace'])
  return done.returncode==0 and rbac_list_denied(done.stdout),{'canIList':cap}
 def curl_denied(tag,label,url):
  done,cap=exec_capture(k,raw,f'neg-{label}-{tag}',NAMESPACE,pod(),['curl','-sS','--connect-timeout','3','--max-time','3',url])
  return denied_egress(done.returncode,done.stderr),{'curl':cap}
 def quota(tag):
  pvc={'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'neg-oversized','namespace':NAMESPACE},'spec':{'storageClassName':'local-path','accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':'100Ti'}}}}
  done,cap=run_captured(k,raw,f'neg-quota-{tag}',['apply','-f','-'],input_text=yaml.safe_dump(pvc))
  if done.returncode==0: k.run(['delete','pvc','neg-oversized','-n',NAMESPACE,'--wait=false'])
  return done.returncode!=0 and 'requests.storage' in done.stderr,{'apply':cap}
 def scan(tag):
  done=k.result(['exec','-i',f'pod/{pod()}','-n',NAMESPACE,'--','sh','-ec',CANARY_SCAN],input_text=canary)
  return done.returncode==0,{'scan':capture(raw,f'neg-scan-{tag}',done)}
 env_path='/spec/template/spec/containers/0/env'
 controls={
  'runtime-credential':(credential,lambda:(patch('deployment','workspace','json',[{'op':'add','path':env_path+'/-','value':{'name':'GIT_AUTH_TOKEN','valueFrom':{'secretKeyRef':{'name':'workspace-git-auth','key':'token'}}}}]),rollout()),lambda:(patch('deployment','workspace','json',[{'op':'test','path':env_path+'/2/name','value':'GIT_AUTH_TOKEN'},{'op':'remove','path':env_path+'/2'}]),rollout())),
  'serviceaccount-token':(token,lambda:(patch('deployment','workspace','json',[{'op':'replace','path':'/spec/template/spec/automountServiceAccountToken','value':True}]),rollout()),lambda:(patch('deployment','workspace','json',[{'op':'replace','path':'/spec/template/spec/automountServiceAccountToken','value':False}]),rollout())),
  'rbac-discovery-only':(rbac,lambda:(k.run(['create','role','neg-reader','--verb=get,list','--resource=pods,secrets','-n',NAMESPACE]),k.run(['create','rolebinding','neg-reader','--role=neg-reader',f'--serviceaccount={NAMESPACE}:workspace','-n',NAMESPACE])),lambda:k.run(['delete','rolebinding,role','neg-reader','-n',NAMESPACE])),
  'denied-egress':(lambda tag:curl_denied(tag,'denied',f'http://denied-fixture.{PROOF_NAMESPACE}.svc.cluster.local:8081'),lambda:allow_egress('neg-allow-denied','denied-fixture',8081),lambda:k.run(['delete','networkpolicy','neg-allow-denied','-n',NAMESPACE])),
  'undeclared-port':(lambda tag:curl_denied(tag,'undeclared',f'http://git-fixture.{PROOF_NAMESPACE}.svc.cluster.local:8080'),lambda:allow_egress('neg-allow-undeclared','git-fixture',8080),lambda:k.run(['delete','networkpolicy','neg-allow-undeclared','-n',NAMESPACE])),
  'storage-quota':(quota,lambda:patch('resourcequota','workspace-bounds','merge',{'spec':{'hard':{'requests.storage':'200Ti'}}}),lambda:patch('resourcequota','workspace-bounds','merge',{'spec':{'hard':{'requests.storage':'1Gi'}}})),
  'secret-scan':(scan,lambda:expect(k.result(['exec','-i',f'pod/{pod()}','-n',NAMESPACE,'--','sh','-ec','cat > /tmp/ok174-planted-canary'],input_text=canary).returncode==0,'could not plant canary'),lambda:k.run(['exec',f'pod/{pod()}','-n',NAMESPACE,'--','rm','-f','/tmp/ok174-planted-canary'])),
 }
 expect(tuple(controls)==NEGATIVE_CONTROLS,'negative control set drifted')
 results=[]
 for name,(check,fault,revert) in controls.items():
  entry={'name':name}
  try:
   baseline,bcap=check('baseline'); expect(baseline,f'{name}: probe is red before the fault')
   fault(); faulted,fcap=check('faulted'); revert(); reverted,rcap=check('reverted')
   entry.update({'baselineGreen':baseline,'redOnFault':not faulted,'greenAfterRevert':reverted,'captures':{'baseline':bcap,'faulted':fcap,'reverted':rcap}})
  except (ProofError,subprocess.TimeoutExpired,ValueError,json.JSONDecodeError) as exc: entry.update({'error':str(exc)[:300]})
  entry['status']='PASS' if entry.get('baselineGreen') and entry.get('redOnFault') and entry.get('greenAfterRevert') else 'FAIL'; results.append(entry)
 pvc=json.loads(k.run(['get','pvc','workspace','-n',NAMESPACE,'-o','json'])); state['persistentPVUID']=json.loads(k.run(['get','pv',pvc['spec']['volumeName'],'-o','json']))['metadata']['uid']; write_state(state)
 cleaned=clean_workspaces(k,state,True,raw)
 index={capture_path(p):sha(p.read_bytes()) for p in sorted(raw.glob('*.json')) if p.name.startswith(('neg-','cleanup-'))}
 unexpected_leaks=sorted(set(CAPTURE_LEAKS)-{'neg-scan-faulted'}) # only the planted-canary scan may see it
 doc={'apiVersion':'evidence.openkubes.io/v1alpha1','kind':'DeveloperWorkspaceNegativeControls','spec':{'status':'PASS' if all(x['status']=='PASS' for x in results) and not unexpected_leaks else 'FAIL','runID':state['runID'],'revision':state['revision'],'implementationTreeSha256':state['git']['implementationTreeSha256'],'cluster':state['target']['cluster'],'controls':results,'cleanup':{'namespaceUIDs':cleaned['namespaces'],'reclaimedPVUID':cleaned['pvUID']},'rawEvidence':index,'unexpectedCanaryCaptures':unexpected_leaks,'notCovered':['Kubernetes API egress: CIDR NetworkPolicy cannot select the API server under Cilium, so no fault opens it; the network-control pod is the positive control']}}
 NEGATIVE_EVIDENCE.write_text(yaml.safe_dump(doc,sort_keys=False)); return doc
def main(argv=None):
 parser=argparse.ArgumentParser(); parser.add_argument('action',choices=('render','apply','probe','evidence','clean-workspaces','negative')); parser.add_argument('--revision'); parser.add_argument('--run-id'); parser.add_argument('--output',type=Path,default=Path('live-rendered.yaml')); args=parser.parse_args(argv)
 try:
  if args.action=='render': expect(bool(args.revision),'--revision is required'); render_to(args.output,implementation_revision(args.revision)); print(f'PASS rendered {args.output}'); return 0
  if args.action=='apply': expect(bool(args.revision),'--revision is required'); state=apply(Kubectl(),implementation_revision(args.revision)); print(json.dumps({'runID':state['runID'],'overlays':state['overlays']},sort_keys=True)); return 0
  expect(bool(args.run_id) and bool(re.fullmatch(r'[0-9a-f]{24}',args.run_id)),'--run-id must be the 24-hex apply run ID'); state=read_state(args.run_id)
  if args.action!='clean-workspaces': expect(state.get('phase') in ('applied','probed'),'apply did not reach a probe-ready state')
  if args.action=='evidence': print(yaml.safe_dump(write_evidence(state),sort_keys=False)); return 0
  if args.action=='clean-workspaces': clean_workspaces(Kubectl(),state); print('PASS cleanup'); return 0
  if args.action=='negative': doc=negative_controls(Kubectl(),state); print(yaml.safe_dump(doc['spec']['controls'],sort_keys=False)); return 0 if doc['spec']['status']=='PASS' else 1
  print(json.dumps(probe(Kubectl(),state),sort_keys=True)); return 0
 except (ProofError,OSError,ValueError,json.JSONDecodeError,subprocess.TimeoutExpired) as exc: print(f'ERROR: {exc}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
