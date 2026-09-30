#!/usr/bin/env python3
"""Deterministic contract and revision-bound live-evidence verifier for ADR-039."""
from __future__ import annotations
import argparse, copy, hashlib, ipaddress, json, re, shlex, sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from pathlib import Path
from typing import Any
import jsonschema, yaml
HERE=Path(__file__).resolve().parent
SCHEMA=HERE/'developer-workspace-v0alpha1.schema.json'; CANDIDATE=HERE/'developer-workspace-v0alpha1.example.yaml'; PROFILE=HERE/'namespace-profile-v1.yaml'; RENDERED=HERE/'developer-workspace-v0alpha1.rendered.yaml'; VERDICT=HERE/'developer-workspace-verdict-v1.yaml'; LIVE_SCHEMA=HERE/'live/evidence/live-evidence-v1.schema.json'; LIVE_EVIDENCE=HERE/'live/evidence/live-evidence-v1.yaml'; NEGATIVE_EVIDENCE=HERE/'live/evidence/negative-controls-v1.yaml'
ARTIFACTS=('developer-workspace-v0alpha1.schema.json','developer-workspace-v0alpha1.example.yaml','namespace-profile-v1.yaml','developer-workspace-v0alpha1.rendered.yaml','verify_developer_workspace_v1.py','tests/test_developer_workspace_v1.py','live/evidence/live-evidence-v1.yaml','live/evidence/negative-controls-v1.yaml')
FOLLOW_UPS={'OK-175':'namespace-opencode-implementation','OK-176':'live-isolation-lifecycle-proof','OK-177':'second-runtime-validation'}
CLUSTER_UID_SHA256_PINS={'ok-obs-verify-admin@ok-obs-verify':'c0d2fe748219faf80f3f8a6858131aed4df2803dc1de1595a01112d9dd166bdc'} # sha256 of the kube-system Namespace UID
SUPERSEDED_EVIDENCE_SHA256='4cdc53615c62738a84173923ee59d532c3619dbf3a3ec34d4adfaa8d68cd630c'
BOUNDARIES=['live proof covers the reviewed Namespace profile on ok-obs-verify, not a VM or hostile multi-tenant boundary','credential evidence is a bounded manifest, argv, workspace, output, and log scan; unobserved exfiltration is not disproved','inference is ok-ai shared Ollama reached through a reviewed /32 host route; that host and the selected model are trusted inputs, and the model is a portability probe, not a production coding-quality claim','persistent requested capacity is not enforced by the local-path provisioner; storage proof covers quota rejection and ephemeral emptyDir eviction','source knownCommit, implementation revision, and image digests are bound separately; no build attestation binds those images to that revision','Codex runs with its own sandbox disabled because it cannot nest inside the unprivileged pod; the pod securityContext and NetworkPolicy are the isolation boundary','MCP capability is proven as network reachability to one reviewed endpoint; approvedTools is declared but not enforced at the tool level','no reconciling controller exists: the harness applies the render and performs export-before-deletion ordering that a future controller must own','evidence is integrity-bound after capture, not attested: beyond the cluster, node, image and model identifiers, its content could be recomputed offline','no merge, release, deployment, or human approval authority is granted by runtime conformance']
RESULT_NAMES=('source-checkout','fixture-test','known-commit-retrieval','kubernetes-denied','serviceaccount-denied','secret-reference','denied-positive-control','allowed-connectivity','denied-egress','undeclared-port-denied','quota-rejection','runtime-task-opencode','runtime-task-codex','persistent-marker-survives-replacement','secret-no-leak','ephemeral-export-cleanup','cleanup','cluster-health')
RESULT_KEYS={'source-checkout':{'commit'},'fixture-test':{'test'},'known-commit-retrieval':{'commit'},'kubernetes-denied':{'httpCode'},'serviceaccount-denied':{'checks'},'secret-reference':{'secretRef','runtimeHasSecret'},'denied-positive-control':{'controlPodUID','approvedFixtureImage','fixtureImageID','apiHttpCode','captures'},'allowed-connectivity':{'ports','inferenceEndpoint','captures'},'denied-egress':{'endpoint'},'undeclared-port-denied':{'ports'},'quota-rejection':{'resourceQuota','exceededResource'},'runtime-task-opencode':{'podUID','podName','approvedImage','imageID','runtimeVersion','verificationCommand','beforeSha256','afterSha256','readback','agent','security','captures'},'runtime-task-codex':{'podUID','podName','approvedImage','imageID','runtimeVersion','verificationCommand','beforeSha256','afterSha256','readback','agent','security','captures'},'persistent-marker-survives-replacement':{'markerSha256','oldPodUID','newPodUID','pvcUID','pvUID'},'secret-no-leak':{'scanned','canarySha256'},'ephemeral-export-cleanup':{'namespaceUID','podName','markerSha256','exportReadBack','belowLimitReady','namespaceAbsent','evicted','evictionMessage','sizeLimit','readback'},'cleanup':{'deletedNamespaceUIDs','reclaimedPVUID'},'cluster-health':{'beforeSha256','afterSha256'}}
class VerificationError(ValueError): pass
def expect(ok,msg):
 if not ok: raise VerificationError(msg)
def load(path):
 try: data=yaml.safe_load(path.read_text())
 except yaml.YAMLError as e: raise VerificationError(f'invalid YAML: {e}') from e
 expect(isinstance(data,dict),'document must be a mapping'); return data
def canonical(value): return json.dumps(value,sort_keys=True,indent=2,separators=(',', ': '))+'\n'
def binding_sha(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def image_id_matches(image_id,approved): return isinstance(image_id,str) and bool(re.fullmatch(r'(?:[^\s]+@)?'+re.escape(approved.rsplit('@',1)[1]),image_id))
def labels(w): return {'workspace.openkubes.io/id':w,'app':'developer-workspace'}
def validate_input(doc):
 try: jsonschema.Draft7Validator(json.loads(SCHEMA.read_text())).validate(doc)
 except jsonschema.ValidationError as e: raise VerificationError(f'schema validation failed: {e.message}') from e
 s=doc['spec']; life=s['lifecycle']; mode=s['storage']['mode']
 expect(s['capabilities']['kubernetes']=={'access':'none'},'Kubernetes access must be none')
 expect('status' not in doc and 'renderedProfile' not in doc,'portable input must not supply status/rendered authority')
 if life['profile']=='persistent': expect(mode=='persistent' and life['deletion']=='explicit','persistent lifecycle requires persistent storage and explicit deletion')
 if life['profile']=='ephemeral': expect(mode=='ephemeral' and life['deletion']=='after-retention' and life['evidence']['exportBeforeCleanup'] is True,'ephemeral lifecycle requires ephemeral storage, retention cleanup, evidence export')
 if life['profile']=='review': expect(s['capabilities']['kubernetes']=={'access':'none'},'review must not gain Kubernetes authority')
def validate_profile(profile,doc):
 expect(set(profile)=={'apiVersion','kind','metadata','spec'} and profile.get('apiVersion')=='workspace.openkubes.io/v1' and profile.get('kind')=='NamespaceProfileCatalog','invalid profile identity')
 expect(set(profile['metadata'])=={'name'} and profile['metadata']['name']=='reviewed-namespace-profile-v1','invalid profile metadata')
 p=profile['spec']; expect(set(p)=={'namespacePrefix','storageClassName','sources','runtimeProfiles','modelProfiles','capabilities','serviceSelectors','credentials'} and isinstance(p['namespacePrefix'],str) and p['namespacePrefix'] and isinstance(p['storageClassName'],str) and re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?',p['storageClassName']),'invalid profile shape')
 s=doc['spec']; sources=p['sources']; expect(set(sources)=={s['source']['repositoryRef']},'source catalog must exactly resolve declaration')
 source=sources[s['source']['repositoryRef']]; expect(set(source)=={'endpoint','repositoryPath','caBundle'} and all(isinstance(x,str) and x for k,x in source.items() if k!='caBundle'),'invalid source mapping')
 parsed=urlparse(source['endpoint']); expect(parsed.scheme=='https' and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ('','/'),'source endpoint is not a safe HTTPS authority')
 path=source['repositoryPath']; segments=path.split('/')
 expect(bool(path) and not path.startswith('/') and not path.endswith('/') and all(segment not in ('','.','..') and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',segment) for segment in segments),'source repository path is unsafe')
 ca=source['caBundle']; expect(set(ca)=={'configMapName','key'} and all(isinstance(x,str) and x for x in ca.values()),'invalid source CA bundle')
 runtimes=p['runtimeProfiles']; expect(set(runtimes)=={'opencode','codex'} and s['runtime']['profile'] in runtimes,'runtime profile unresolved')
 env_keys={'capabilityRef','endpointName','endpointScheme','endpointPath','modelName','model'}
 for name,item in runtimes.items():
  expect(set(item)=={'image','envTemplate'} and isinstance(item['image'],str) and item['image'] and set(item['envTemplate'])==env_keys and all(isinstance(x,str) and x for x in item['envTemplate'].values()),'invalid runtime profile')
  env=item['envTemplate']; expect(env['capabilityRef']==s['capabilities']['inference']['reference'] and env['endpointScheme'] in ('http','https') and env['endpointPath'].startswith('/') and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env['endpointName']) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env['modelName']),'runtime env template is not bound to declared inference capability')
 caps=p['capabilities']; declared=[s['capabilities']['git']['reference'],s['capabilities']['inference']['reference'],s['capabilities']['mcp']['reference']]
 expect(set(caps)==set(declared) and len(set(declared))==3,'capability catalog must exactly resolve declarations')
 for ref,item in caps.items():
  allowed={'destination','approvedTools'} if ref==s['capabilities']['mcp']['reference'] else {'destination'}
  expect(set(item)==allowed and isinstance(item.get('destination'),dict),f'invalid capability mapping {ref}')
  dest=item['destination']; port=dest.get('port')
  expect(isinstance(port,int) and 1<=port<=65535,'destination must have a valid port')
  if set(dest)=={'cidr','port'}:
   try: net=ipaddress.ip_network(dest['cidr'],strict=True)
   except ValueError as e: raise VerificationError(f'invalid destination CIDR for {ref}') from e
   expect(net.prefixlen==net.max_prefixlen,'destination CIDR must be a host route')
  else:
   expect(set(dest)=={'service','port'} and isinstance(dest['service'],dict) and set(dest['service'])=={'namespace','name'} and all(isinstance(x,str) and x for x in dest['service'].values()),'invalid service destination')
   key=dest['service']['namespace']+'/'+dest['service']['name']; selector=p['serviceSelectors'].get(key)
   expect(isinstance(selector,dict) and selector and all(isinstance(k,str) and isinstance(v,str) and k and v for k,v in selector.items()),f'unresolved service selector {key}')
 service_keys={d['service']['namespace']+'/'+d['service']['name'] for d in (item['destination'] for item in caps.values()) if 'service' in d}; expect(set(p['serviceSelectors'])==service_keys,'service selector catalog must exactly resolve service destinations')
 models=p['modelProfiles']; expect(set(models)=={s['model']['profileRef']},'model catalog must exactly resolve declaration')
 model=models[s['model']['profileRef']]; expect(set(model)=={'inferenceCapabilityRef'} and model['inferenceCapabilityRef']==s['capabilities']['inference']['reference'],'model profile is not bound to declared inference capability')
 expect(caps[s['capabilities']['mcp']['reference']]['approvedTools']==s['capabilities']['mcp']['approvedTools'],'MCP tool catalog differs from declaration')
 creds=p['credentials']; expect(set(creds)==set(s['credentials']),'credential catalog must exactly resolve declarations')
 for ref,item in creds.items(): expect(set(item)=={'capabilityRef','secretName','secretKey','envName'} and item['capabilityRef']==s['capabilities']['git']['reference'] and all(isinstance(x,str) and x for x in item.values()),f'invalid credential mapping {ref}')
def render(doc,profile):
 validate_input(doc); validate_profile(profile,doc)
 s=doc['spec']; p=profile['spec']; w=s['workspaceID']; ns=p['namespacePrefix']+w.removeprefix('ws-'); lab=labels(w); cpu=s['resources']['cpu']; mem=s['resources']['memory']; size=s['storage']['size']; mode=s['storage']['mode']
 container_resources={'requests':{'cpu':cpu,'memory':mem},'limits':{'cpu':cpu,'memory':mem}}
 volume={'name':'workspace'}; quota={'requests.cpu':cpu,'limits.cpu':cpu,'requests.memory':mem,'limits.memory':mem}
 if mode=='persistent': volume['persistentVolumeClaim']={'claimName':'workspace'}; quota['requests.storage']=size
 else: volume['emptyDir']={'sizeLimit':size}; container_resources['requests']['ephemeral-storage']=size; quota['requests.ephemeral-storage']=size
 git_env=[]
 for ref in s['credentials']:
  c=p['credentials'][ref]; git_env.append({'name':c['envName'],'valueFrom':{'secretKeyRef':{'name':c['secretName'],'key':c['secretKey']}}})
 source=p['sources'][s['source']['repositoryRef']]; ca=source['caBundle']; ca_path='/etc/ssl/certs/source-ca/'+ca['key']; git_env.append({'name':'GIT_SSL_CAINFO','value':ca_path})
 hardening={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']},'runAsNonRoot':True,'readOnlyRootFilesystem':True}
 workspace_mount=[{'name':'workspace','mountPath':'/workspace'}]; checkout_writable=[{'name':'checkout-tmp','mountPath':'/tmp'},{'name':'checkout-home','mountPath':'/home/workspace'}]; runtime_writable=[{'name':'runtime-tmp','mountPath':'/tmp'},{'name':'runtime-home','mountPath':'/home/workspace'}]; ca_mount={'name':'source-ca','mountPath':'/etc/ssl/certs/source-ca','readOnly':True}
 runtime=p['runtimeProfiles'][s['runtime']['profile']]; template=runtime['envTemplate']; inference=p['capabilities'][template['capabilityRef']]['destination']
 host=inference['cidr'].split('/')[0] if 'cidr' in inference else inference['service']['name']+'.'+inference['service']['namespace']+'.svc.cluster.local'
 endpoint=f"{template['endpointScheme']}://{host}:{inference['port']}{template['endpointPath']}"; runtime_env=[{'name':template['endpointName'],'value':endpoint},{'name':template['modelName'],'value':template['model']}]
 pod={'serviceAccountName':'workspace','automountServiceAccountToken':False,'hostNetwork':False,'hostPID':False,'hostIPC':False,'securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},'initContainers':[{'name':'checkout','image':runtime['image'],'command':['checkout'],'args':[source['endpoint'],source['repositoryPath'],s['source']['revision'],'/workspace'],'workingDir':'/workspace','env':git_env,'resources':container_resources,'securityContext':hardening,'volumeMounts':workspace_mount+checkout_writable+[ca_mount]}],'containers':[{'name':'runtime','image':runtime['image'],'env':runtime_env,'resources':container_resources,'securityContext':hardening,'volumeMounts':workspace_mount+runtime_writable}],'volumes':[volume,{'name':'checkout-tmp','emptyDir':{}},{'name':'checkout-home','emptyDir':{}},{'name':'runtime-tmp','emptyDir':{}},{'name':'runtime-home','emptyDir':{}},{'name':'source-ca','configMap':{'name':ca['configMapName'],'items':[{'key':ca['key'],'path':ca['key']}]}}]}
 resources=[{'apiVersion':'v1','kind':'Namespace','metadata':{'name':ns,'labels':lab}},{'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':'workspace','namespace':ns,'labels':lab},'automountServiceAccountToken':False},{'apiVersion':'v1','kind':'ResourceQuota','metadata':{'name':'workspace-bounds','namespace':ns,'labels':lab},'spec':{'hard':quota}},{'apiVersion':'v1','kind':'LimitRange','metadata':{'name':'workspace-defaults','namespace':ns,'labels':lab},'spec':{'limits':[{'type':'Container','default':container_resources['limits'],'defaultRequest':container_resources['requests'],'max':container_resources['limits']}]}},{'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'default-deny','namespace':ns,'labels':lab},'spec':{'podSelector':{},'policyTypes':['Ingress','Egress']}}]
 if mode=='persistent': resources.append({'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'workspace','namespace':ns,'labels':lab},'spec':{'storageClassName':p['storageClassName'],'accessModes':['ReadWriteOnce'],'resources':{'requests':{'storage':size}}}})
 for ref in declared_refs(s):
  d=p['capabilities'][ref]['destination']; name='allow-'+ref.split(':',1)[1]; target={'ipBlock':{'cidr':d['cidr']}} if 'cidr' in d else {'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':d['service']['namespace']}},'podSelector':{'matchLabels':p['serviceSelectors'][d['service']['namespace']+'/'+d['service']['name']]}}
  resources.append({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':name,'namespace':ns,'labels':lab,'annotations':{'workspace.openkubes.io/capability-ref':ref}},'spec':{'podSelector':{'matchLabels':lab},'policyTypes':['Egress'],'egress':[{'to':[target],'ports':[{'protocol':'TCP','port':d['port']}]}]}})
 if any('service' in p['capabilities'][ref]['destination'] for ref in declared_refs(s)):
  resources.append({'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'allow-kube-dns','namespace':ns,'labels':lab},'spec':{'podSelector':{'matchLabels':lab},'policyTypes':['Egress'],'egress':[{'to':[{'namespaceSelector':{'matchLabels':{'kubernetes.io/metadata.name':'kube-system'}},'podSelector':{'matchLabels':{'k8s-app':'kube-dns'}}}],'ports':[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}]}]}})
 resources.append({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'workspace','namespace':ns,'labels':lab},'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':lab},'template':{'metadata':{'labels':lab},'spec':pod}}})
 resources=json.loads(json.dumps(resources)) # shared label dicts must not alias selector and template
 return {'apiVersion':'workspace.openkubes.io/v1','kind':'DeveloperWorkspaceNamespaceRender','metadata':{'name':doc['metadata']['name']},'spec':{'inputDigest':'sha256:'+hashlib.sha256(canonical(doc).encode()).hexdigest(),'profile':'reviewed-namespace-profile-v1','resources':resources}}
def declared_refs(s): return [s['capabilities']['git']['reference'],s['capabilities']['inference']['reference'],s['capabilities']['mcp']['reference']]
IMPLEMENTATION_EXCLUDES=('live/evidence/raw/','live/evidence/state/','live/evidence/live-evidence-v1.yaml','live/evidence/negative-controls-v1.yaml','live/evidence/published-images.env','live/rendered-live.yaml','live/README.md','developer-workspace-verdict-v1.yaml')
def implementation_tree_sha256(root=HERE):
 """Content hash of the spike's implementation files: everything except evidence, verdict and evidence-status docs.
 It survives rebases and squash merges, so recorded evidence stays checkable against any checkout."""
 lines=[]
 for path in sorted(p for p in root.rglob('*') if p.is_file()):
  rel=path.relative_to(root).as_posix()
  if '__pycache__/' in rel or rel.endswith(('.pyc','.candidate.json')) or rel.startswith(IMPLEMENTATION_EXCLUDES): continue
  lines.append(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+rel)
 return hashlib.sha256(('\n'.join(lines)+'\n').encode()).hexdigest()
def evidence_complete(evidence):
 s=evidence['spec']; return not s['unsupported'] and all(x['status']=='PASS' for x in s['results'])
def derived_recommendation(evidence):
 return 'GO' if evidence_complete(evidence) else 'REVISE'
def parse_time(value):
 try: return datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError as e: raise VerificationError('timestamp must be RFC3339') from e
def nested_bindings(value):
 if isinstance(value,dict):
  if {'path','sha256'}.issubset(value): yield {'path':value['path'],'sha256':value['sha256']}
  for item in value.values(): yield from nested_bindings(item)
 if isinstance(value,list):
  for item in value: yield from nested_bindings(item)
def capture_record(root,binding):
 try: record=json.loads((root/binding['path']).read_text())
 except (OSError,json.JSONDecodeError) as e: raise VerificationError(f"invalid raw transcript: {binding.get('path')}") from e
 expect(isinstance(record,dict) and set(record)=={'argv','returncode','stdout','stderr'} and isinstance(record['argv'],list) and isinstance(record['returncode'],int) and isinstance(record['stdout'],str) and isinstance(record['stderr'],str),'raw transcript shape is invalid'); return record
def observed_image_id(pod,name): return next((x.get('imageID','') for x in pod.get('status',{}).get('containerStatuses',[]) if x.get('name')==name),'')
def capture_for(root,evidence,name):
 captures=evidence.get('captures',{}); expect(name in captures,f'missing raw transcript: {name}'); return capture_record(root,captures[name])
def stable_node_health(data):
 return sorted(({'uid':item.get('metadata',{}).get('uid'),'unschedulable':item.get('spec',{}).get('unschedulable',False),'conditions':sorted(({'type':x.get('type'),'status':x.get('status'),'reason':x.get('reason','')} for x in item.get('status',{}).get('conditions',[])),key=lambda x:x['type'] or '')} for item in data.get('items',[])),key=lambda x:x['uid'] or '')
def record_command(value):
 if not isinstance(value,dict): return ''
 if isinstance(value.get('command'),str): return value['command']
 if isinstance(value.get('cmd'),str): return value['cmd']
 for item in value.values():
  found=record_command(item)
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
  sessions={x.get('sessionID') for x in events if x.get('type') in ('step_start','tool_use','step_finish')}; expect(len(sessions)==1 and next(iter(sessions)),'opencode stream lacks one stable sessionID'); expect(any(x.get('type')=='step_start' for x in events) and any(x.get('type')=='step_finish' and x.get('part',{}).get('reason')=='stop' for x in events),'opencode stream lacks start/stop lifecycle')
  for event in events:
   if event.get('type')!='tool_use' or not isinstance(event.get('part'),dict): continue
   part=event['part']; state=part.get('state',{}); identifier=part.get('callID'); tool=part.get('tool'); expect(isinstance(identifier,str) and identifier and isinstance(tool,str) and isinstance(state,dict),'opencode tool_use identity is invalid')
   if state.get('status')=='completed' and isinstance(state.get('input'),dict) and 'output' in state:
    record={'id':identifier,'tool':tool.lower(),'command':record_command(state['input'])}; output=str(state['output'])
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
   if kind=='command_execution' and status=='completed' and item.get('exit_code')==0 and 'aggregated_output' in item: records.append({'id':identifier,'tool':'exec','command':shell_inner(str(item.get('command','')))})
   if kind=='file_change' and status=='completed' and isinstance(item.get('changes'),list) and item['changes']: records.append({'id':identifier,'tool':'file_change','command':' '.join(str(x.get('path','')) for x in item['changes'] if isinstance(x,dict))})
 return records
def shell_inner(command):
 """Codex reports shell tool calls as `<shell> -lc '<command>'`; compare the inner command."""
 try: parts=shlex.split(command)
 except ValueError: return command
 return parts[2] if len(parts)==3 and parts[0].rsplit('/',1)[-1] in ('bash','sh','zsh') and parts[1] in ('-c','-lc') else command
def rbac_discovery_only(text):
 allowed_resources={'selfsubjectreviews.authentication.k8s.io','selfsubjectaccessreviews.authorization.k8s.io','selfsubjectrulesreviews.authorization.k8s.io'}; allowed_urls=re.compile(r'^/(?:api|apis|healthz|livez|readyz|openapi)(?:/\*)?$|^/version/?$|^/openid/v1/jwks/?$|^/\.well-known/openid-configuration/?$')
 for raw in text.splitlines():
  line=raw.strip()
  if not line or line.lower().startswith(('warning:','resources ')): continue
  groups=re.findall(r'\[([^]]*)\]',line); prefix=line.split('[',1)[0].strip().lower()
  if len(groups)<3:return False
  verbs={x for x in groups[-1].split() if x}
  if '*' in verbs:return False
  if prefix:
   if prefix not in allowed_resources or verbs!={'create'} or groups[0].strip():return False
  else:
   urls={x for x in groups[0].split() if x}
   if not urls or verbs!={'get'} or not all(allowed_urls.fullmatch(x) for x in urls):return False
 return bool(text.strip())
def controller_default(item): return item.get('kind')=='ServiceAccount' and item.get('metadata',{}).get('name')=='default'
def normalized_readback(item):
 value=copy.deepcopy(item); value.pop('status',None); metadata=value.get('metadata',{})
 for key in ('uid','resourceVersion','generation','creationTimestamp','managedFields'): metadata.pop(key,None)
 annotations=metadata.get('annotations',{}); annotations.pop('kubectl.kubernetes.io/last-applied-configuration',None); annotations.pop('deployment.kubernetes.io/revision',None)
 if value.get('kind')=='PersistentVolumeClaim':
  for key in ('pv.kubernetes.io/bind-completed','pv.kubernetes.io/bound-by-controller','volume.beta.kubernetes.io/storage-provisioner','volume.kubernetes.io/storage-provisioner','volume.kubernetes.io/selected-node'): annotations.pop(key,None)
  metadata.pop('finalizers',None); spec=value.get('spec',{}); spec.pop('volumeName',None)
  if spec.get('volumeMode')=='Filesystem': spec.pop('volumeMode')
  for key in ('dataSource','dataSourceRef'):
   if spec.get(key) is None: spec.pop(key,None)
 if not annotations: metadata.pop('annotations',None)
 if value.get('kind')=='Namespace':
  labels=metadata.get('labels',{}); name=metadata.get('name')
  if labels.get('kubernetes.io/metadata.name')==name: labels.pop('kubernetes.io/metadata.name')
  if not labels: metadata.pop('labels',None)
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
def expected_live_material(s):
 documents={}; renders={}
 for runtime in ('opencode','codex'):
  doc=load(HERE/'live/profile/developer-workspace-live.yaml'); profile=load(HERE/'live/profile/namespace-profile-live.yaml')
  doc['metadata']['name']='ok174-live-proof'; doc['spec']['workspaceID']='ws-ok174-proof'; doc['spec']['source']['revision']=s['knownCommit']; doc['spec']['runtime']['profile']=runtime; doc['spec']['storage']['mode']='persistent'
  profile['spec']['storageClassName']=s['storageProfile']['name']
  for name in ('opencode','codex'):
   profile['spec']['runtimeProfiles'][name]['image']=s['imageReferences'][name]; profile['spec']['runtimeProfiles'][name]['envTemplate']['model']=s['model']
  documents[runtime]=doc; renders[runtime]=render(doc,profile)
 objects=copy.deepcopy(renders['opencode']['spec']['resources']); overlays=[]; owner={'workspace.openkubes.io/proof':'ok-174','workspace.openkubes.io/owner':'developer-workspace-spike'}; run_label={'workspace.openkubes.io/run-id':s['run']['runID']}
 for item in objects:
  md=item.setdefault('metadata',{}); md.setdefault('labels',{}).update({**owner,**run_label}); paths=['metadata.labels']
  if item.get('kind')=='Deployment':
   pod=item['spec']['template']['spec']; pod['imagePullSecrets']=[{'name':'ok174-registry-pull'}]; item['spec']['template'].setdefault('metadata',{}).setdefault('labels',{}).update({**owner,**run_label}); paths += ['spec.template.metadata.labels','spec.template.spec.imagePullSecrets']
  overlays.append({'kind':item.get('kind'),'name':md.get('name'),'namespace':md.get('namespace',md.get('name','')),'overlays':paths})
 return documents,renders,objects,overlays
def live_overlay(rendered,run_id):
 objects=copy.deepcopy(rendered['spec']['resources']); owner={'workspace.openkubes.io/proof':'ok-174','workspace.openkubes.io/owner':'developer-workspace-spike'}; run_label={'workspace.openkubes.io/run-id':run_id}
 for item in objects:
  md=item.setdefault('metadata',{}); md.setdefault('labels',{}).update({**owner,**run_label})
  if item.get('kind')=='Deployment': item['spec']['template']['spec']['imagePullSecrets']=[{'name':'ok174-registry-pull'}]; item['spec']['template'].setdefault('metadata',{}).setdefault('labels',{}).update({**owner,**run_label})
 return objects
def expected_ephemeral_objects(s):
 doc=load(HERE/'live/profile/developer-workspace-live.yaml'); profile=load(HERE/'live/profile/namespace-profile-live.yaml'); doc['metadata']['name']='ok174-ephemeral-proof'; doc['spec']['workspaceID']='ws-ok174-ephemeral'; doc['spec']['source']['revision']=s['knownCommit']; doc['spec']['runtime']['profile']='opencode'; doc['spec']['storage'].update({'mode':'ephemeral','size':'8Mi'}); doc['spec']['lifecycle'].update({'profile':'ephemeral','deletion':'after-retention'}); profile['spec']['storageClassName']=s['storageProfile']['name']
 for name in ('opencode','codex'): profile['spec']['runtimeProfiles'][name]['image']=s['imageReferences'][name]; profile['spec']['runtimeProfiles'][name]['envTemplate']['model']=s['model']
 return live_overlay(render(doc,profile),s['run']['runID'])
def expected_live_bindings(s):
 documents,renders,objects,overlays=expected_live_material(s); return {'documentsSha256':binding_sha(documents),'rendersSha256':binding_sha(renders),'appliedObjectsSha256':binding_sha(objects),'overlaysSha256':binding_sha(overlays)}
CANARY_SCAN='p=$(cat); test -n "$p" || exit 8; if grep -a -R -F -e "$p" /workspace /tmp /home/workspace; then exit 9; fi'
def exec_pod(record):
 argv=record['argv']; return next((x[4:] for x in argv if isinstance(x,str) and x.startswith('pod/')),'') if len(argv)>1 and argv[1]=='exec' else ''
def expect_pod(record,pod,what): expect(exec_pod(record)==pod,f'{what} transcript ran in {exec_pod(record) or "no pod"}, not {pod}')
def expect_clean_scan(record,pod,what): expect(record['returncode']==0 and not record['stderr'].strip() and record['argv'][1:3]==['exec','-i'] and record['argv'][-3:]==['sh','-ec',CANARY_SCAN] and exec_pod(record)==pod,f'{what} canary scan found the canary, reported errors, or ran elsewhere')
def cgroup_limits(resources):
 mem=resources['memory']; cpu=resources['cpu']; units={'Mi':2**20,'Gi':2**30}
 return [str(int(mem[:-2])*units[mem[-2:]]),str(int(cpu[:-1])*100 if cpu.endswith('m') else int(cpu)*100000),'100000']
def is_fixture_edit(item):
 cmd=item['command']
 return item['tool'] in ('write','edit','patch','file_change') or ('README.md' in cmd and bool(re.search(r'>\s*README\.md|sed\s+-i|\btee\b|apply_patch',cmd)))
def validate_runtime_transcripts(runtime,e,root,command,expected_objects,expected_resources):
 captures=e['captures']; expect(set(captures)=={'logs','before','version','agent','verification','diff','marker'},f'{runtime} transcript set is incomplete'); expect(set(captures['logs'])=={'pod','checkout-current','runtime-current'},f'{runtime} log transcript set is incomplete')
 for binding in captures['logs'].values(): expect(capture_record(root,binding)['returncode']==0,f'{runtime} log capture failed')
 logged_pod=json.loads(capture_record(root,captures['logs']['pod'])['stdout']); statuses=logged_pod.get('status',{}).get('initContainerStatuses',[])+logged_pod.get('status',{}).get('containerStatuses',[]); expect({x.get('name') for x in statuses}=={'checkout','runtime'} and all(x.get('restartCount')==0 for x in statuses),f'{runtime} restarted container lacks complete log custody')
 expect(logged_pod.get('metadata',{}).get('name')==e['podName'] and logged_pod.get('metadata',{}).get('uid')==e['podUID'],f'{runtime} log custody belongs to another pod')
 for name in ('before','marker','version','verification','diff','agent'): expect_pod(capture_record(root,captures[name]),e['podName'],f'{runtime} {name}')
 before=capture_record(root,captures['before']); marker=capture_record(root,captures['marker']); version=capture_record(root,captures['version']); verification=capture_record(root,captures['verification']); diff=capture_record(root,captures['diff']); agent=capture_record(root,captures['agent'])
 expect(before['returncode']==0 and before['stdout'].split()[0]==e['beforeSha256'],f'{runtime} before hash contradicts transcript'); expect(marker['returncode']==0 and marker['stdout'].split()[0]==e['afterSha256'],f'{runtime} after hash contradicts transcript'); expect(version['returncode']==0 and version['stdout'].strip()==e['runtimeVersion'],f'{runtime} version contradicts transcript'); expect(verification['returncode']==0 and verification['argv'][-len(command):]==command,f'{runtime} verification transcript does not execute the declared command'); expect(diff['returncode']==0 and bool(diff['stdout'].strip()),f'{runtime} diff transcript is empty'); expect(agent['returncode']==0,f'{runtime} agent transcript failed')
 events=[]
 for line in agent['stdout'].splitlines():
  try: event=json.loads(line)
  except json.JSONDecodeError: continue
  if isinstance(event,dict): events.append(event)
 records=typed_tool_records(runtime,events); expected=shlex.join(command); edit_indexes=[i for i,item in enumerate(records) if is_fixture_edit(item)]; verify_indexes=[i for i,item in enumerate(records) if item['command']==expected and item['tool'] in ('bash','shell','exec')]; expect(events and len({x['id'] for x in records})==len(records) and edit_indexes and verify_indexes and min(edit_indexes)<max(verify_indexes),f'{runtime} raw agent stream does not prove ordered runtime-native successful edit plus exact verification exec results'); expect(e['agent'].get('eventCount')==len(events) and e['agent'].get('typedToolEventCount')==len(records) and e['agent'].get('editObserved') is True,f'{runtime} agent event summary contradicts transcript')
 security=e['security']; security_captures=security.get('captures',{}); expected_security={'credentialAbsence','environment','api','serviceAccountMount','canIList','allowed-git','allowed-mcp','allowed-ollama','denied','undeclared','cgroupLimits','canaryScan'}; expect(set(security_captures)==expected_security,f'{runtime} security transcript set is incomplete')
 for name in ('credentialAbsence','environment','api','serviceAccountMount','allowed-git','allowed-mcp','allowed-ollama','denied','undeclared','cgroupLimits','canaryScan'): expect_pod(capture_record(root,security_captures[name]),e['podName'],f'{runtime} security {name}')
 limits=capture_record(root,security_captures['cgroupLimits']); expect(limits['returncode']==0 and limits['argv'][-2:]==['/sys/fs/cgroup/memory.max','/sys/fs/cgroup/cpu.max'] and limits['stdout'].split()==cgroup_limits(expected_resources) and security.get('cgroupLimits')==cgroup_limits(expected_resources),f'{runtime} kernel cgroup limits differ from rendered CPU/memory limits')
 expect_clean_scan(capture_record(root,security_captures['canaryScan']),e['podName'],f'{runtime} runtime')
 for name in ('credentialAbsence','environment','serviceAccountMount','canIList','allowed-git','allowed-mcp','allowed-ollama'): expect(capture_record(root,security_captures[name])['returncode']==0,f'{runtime} {name} transcript failed')
 expect(rbac_discovery_only(capture_record(root,security_captures['canIList'])['stdout']),f'{runtime} can-i transcript exceeds discovery-only rules')
 for name in ('api','denied','undeclared'): expect(capture_record(root,security_captures[name])['returncode'] in (7,28),f'{runtime} {name} transcript has wrong denial polarity')
 security_records={name:capture_record(root,binding) for name,binding in security_captures.items()}; expect(security_records['credentialAbsence']['argv'][-3:]==['sh','-ec','test -z "${GIT_AUTH_TOKEN+x}" && test -z "${GIT_SSL_CAINFO+x}"'] and security_records['environment']['argv'][-1]=='env' and security_records['api']['argv'][-1]=='https://kubernetes.default.svc' and security_records['serviceAccountMount']['argv'][-3:]==['sh','-ec','test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token && test ! -e /var/run/secrets/kubernetes.io/serviceaccount/ca.crt'] and security_records['canIList']['argv'][1:4]==['auth','can-i','--list'],'runtime security transcripts execute unexpected commands')
 endpoints={'allowed-git':':8443/known-commit','allowed-mcp':':8081/mcp','allowed-ollama':':11434/api/tags','denied':':8081','undeclared':':8080'}
 for name,suffix in endpoints.items(): expect(security_records[name]['argv'][-1].endswith(suffix),f'{runtime} {name} transcript targets an unexpected endpoint')
 readback=e['readback']; readback_captures=readback.get('captures',{}); expect(set(readback_captures)=={'Namespace','Deployment','NetworkPolicy','ResourceQuota','PersistentVolumeClaim','ServiceAccount','LimitRange'},f'{runtime} read-back transcript set is incomplete')
 observed={}; observed_values={}
 for kind,binding in readback_captures.items():
  record=capture_record(root,binding); expect(record['returncode']==0,f'{runtime} read-back command failed')
  decoded=json.loads(record['stdout']); items=[decoded] if kind=='Namespace' else [x for x in decoded.get('items',[]) if not controller_default(x)]
  for item in items:
   value=normalized_readback(item); key=f"{item['kind']}/{item['metadata']['name']}"; observed_values[key]=value; observed[key]=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
 expect(readback.get('hashes')==observed,f'{runtime} read-back hashes contradict raw API objects')
 expected_values={f"{item['kind']}/{item['metadata']['name']}":normalized_readback(item) for item in expected_objects if item['kind'] in readback_captures}; expect(observed_values==expected_values,f'{runtime} raw read-back differs from independently rendered objects plus approved overlays')
def live_inference_url():
 d=load(HERE/'live/profile/namespace-profile-live.yaml')['spec']['capabilities']['capabilityref:inference-shared']['destination']; return f"http://{d['cidr'].split('/')[0]}:{d['port']}"
def validate_live_evidence(evidence,artifact_root=None):
 try: jsonschema.Draft7Validator(json.loads(LIVE_SCHEMA.read_text()),format_checker=jsonschema.FormatChecker()).validate(evidence)
 except jsonschema.ValidationError as e: raise VerificationError(f'live evidence schema validation failed: {e.message}') from e
 s=evidence['spec']; expect(artifact_root is not None,'artifact root is required to verify raw evidence'); root=Path(artifact_root).resolve()
 for name,binding in s['rawEvidence'].items():
  path=(root/binding['path']).resolve(); expect(path.is_relative_to(root) and path.is_file(),f'raw evidence file is missing: {name}')
  expect(hashlib.sha256(path.read_bytes()).hexdigest()==binding['sha256'],f'raw evidence digest mismatch: {name}')
 catalog={(x['path'],x['sha256']) for x in s['rawEvidence'].values()}
 for binding in nested_bindings(s['results']): expect((binding['path'],binding['sha256']) in catalog,'result transcript is not present in rawEvidence')
 expect(s['cluster']['uidSha256']==CLUSTER_UID_SHA256_PINS.get(s['context']),'cluster UID does not match context')
 expect(s['revision']!='0'*40,'revision must not be forty zeroes')
 expect(s['run']['implementationTreeSha256']==implementation_tree_sha256(),'evidence was recorded against different implementation files than this checkout')
 expect(s['run']['worktreeClean'] is True and s['revision']==s['run']['gitHead'],'revision must equal the clean harness-captured Git HEAD')
 started,finished=parse_time(s['run']['startedAt']),parse_time(s['run']['finishedAt']); expect(started<=finished,'run timestamps are reversed'); expect(finished<=datetime.now(timezone.utc)+timedelta(minutes=5),'run timestamp is implausibly in the future')
 expect({name:s['run'][name] for name in ('documentsSha256','rendersSha256','appliedObjectsSha256','overlaysSha256')}==expected_live_bindings(s),'evidence is not bound to the independently rendered live documents, resources, and overlays')
 expect(tuple(item['name'] for item in s['results'])==RESULT_NAMES,'live evidence result order/membership mismatch')
 status={item['name']:item['status'] for item in s['results']}; results={item['name']:item['evidence'] for item in s['results']}; command=load(CANDIDATE)['spec']['verification']['command']; expected_command=shlex.join(command)
 if all(status[name]=='PASS' for name in ('persistent-marker-survives-replacement','ephemeral-export-cleanup','cleanup')):
  ledger={'namespaceUIDs':results['cleanup']['deletedNamespaceUIDs'],'persistentPVUID':results['persistent-marker-survives-replacement']['pvUID'],'ephemeralNamespaceUID':results['ephemeral-export-cleanup']['namespaceUID']}; expect(s['run']['cleanupLedgerSha256']==binding_sha(ledger),'cleanup/PV/ephemeral UID results differ from the apply-state ledger binding')
 for name in RESULT_NAMES:
  if status[name]=='PASS': expect(RESULT_KEYS[name].issubset(results[name]),f'PASS result evidence is incomplete: {name}')
 for name,reference in s['imageReferences'].items(): expect(reference.endswith('@'+s['imageDigests'][name]),f'image digest catalog differs from approved {name} reference')
 expect(s['status']==('PASS' if evidence_complete(evidence) else 'REVISE'),'top-level evidence status is inconsistent with results or unsupported effects')
 if status['source-checkout']=='PASS' and status['known-commit-retrieval']=='PASS': expect(results['source-checkout']['commit']==s['knownCommit'] and results['known-commit-retrieval']['commit']==s['knownCommit'],'checkout commit differs from known commit')
 if status['source-checkout']=='PASS':
  record=capture_for(root,results['source-checkout'],'head'); expect(record['returncode']==0 and record['argv'][-4:]==['git','-C','/workspace','rev-parse','HEAD'][-4:] and record['stdout'].strip()==s['knownCommit'],'source-checkout summary contradicts raw rev-parse')
 if status['fixture-test']=='PASS':
  record=capture_for(root,results['fixture-test'],'beforeMutation'); expect(record['returncode']!=0 and record['argv'][-len(command):]==command,'fixture-test PASS does not contain the expected failing declared command')
 if status['known-commit-retrieval']=='PASS':
  record=capture_for(root,results['known-commit-retrieval'],'knownCommit'); expect(record['returncode']==0 and record['stdout'].strip()==s['knownCommit'] and record['argv'][-1].endswith(':8443/known-commit'),'known-commit summary contradicts raw TLS request')
 if status['kubernetes-denied']=='PASS': expect(results['kubernetes-denied']['httpCode']=='000','Kubernetes denial summary has a reachable HTTP code')
 if status['kubernetes-denied']=='PASS':
  record=capture_for(root,results['kubernetes-denied'],'api'); expect(record['returncode'] in (7,28) and record['stderr'] and record['argv'][-1]=='https://kubernetes.default.svc','Kubernetes denial summary contradicts raw curl')
 if status['serviceaccount-denied']=='PASS':
  service=results['serviceaccount-denied']; expect(service['checks']==2,'service-account denial summary omitted a check'); mount=capture_for(root,service,'mount'); auth=capture_for(root,service,'canIList'); expect(mount['returncode']==0 and auth['returncode']==0 and rbac_discovery_only(auth['stdout']) and auth['argv'][1:4]==['auth','can-i','--list'],'service-account denial summary contradicts raw checks')
 if status['secret-reference']=='PASS': expect(results['secret-reference']['runtimeHasSecret'] is False,'runtime sees the source credential')
 if status['denied-positive-control']=='PASS':
  control=results['denied-positive-control']; expect(set(control['captures'])=={'pod','kubernetes-api','git-auth-absent','git-auth-wrong','git-undeclared','mcp','denied'},'network-control transcript set is incomplete'); expect(control['apiHttpCode'] in ('401','403'),'Kubernetes API positive control did not observe an authentication response'); expect(control['approvedFixtureImage']==s['imageReferences']['fixture'] and image_id_matches(control['fixtureImageID'],control['approvedFixtureImage']),'fixture imageID differs from approved image'); pod_record=capture_record(root,control['captures']['pod']); control_pod=json.loads(pod_record['stdout']); expect(pod_record['argv'][1:]==['get','pod','network-control','-n','ok174-proof-services','-o','json'] and control_pod.get('metadata',{}).get('uid')==control['controlPodUID'] and observed_image_id(control_pod,'control')==control['fixtureImageID'],'fixture/control summary contradicts raw Pod'); api_record=capture_record(root,control['captures']['kubernetes-api']); expect(api_record['returncode']==0 and api_record['stdout'].strip()==control['apiHttpCode'] and api_record['argv'][-1]=='https://kubernetes.default.svc','Kubernetes API positive-control summary contradicts transcript')
  control_urls={'git-undeclared':'http://git-fixture:8080/known-commit','mcp':'http://mcp-fixture:8081/mcp','denied':'http://denied-fixture:8081/mcp'}
  for name,url in control_urls.items():
   record=capture_record(root,control['captures'][name]); expect(record['returncode']==0 and record['argv'][-1]==url,f'network positive control failed or retargeted: {name}')
  for name in ('git-auth-absent','git-auth-wrong'):
   auth=capture_record(root,control['captures'][name]); expect(auth['returncode']==0 and auth['stdout'].strip()=='401' and auth['argv'][-1]=='https://git-fixture:8443/workspace-fixture.git/info/refs?service=git-upload-pack','Git fixture credential control did not reject absent/wrong token')
  expect('-H' not in capture_record(root,control['captures']['git-auth-absent'])['argv'] and 'Authorization: Bearer intentionally-wrong' in capture_record(root,control['captures']['git-auth-wrong'])['argv'],'Git credential controls do not distinguish absent and wrong tokens')
 if status['allowed-connectivity']=='PASS':
  allowed=results['allowed-connectivity']; expect(set(allowed['captures'])=={'git','mcp','ollama'},'allowed-connectivity transcript set is incomplete'); expect(allowed['ports']==[8443,11434,8081],'allowed-connectivity ports differ from the reviewed profile'); expect(allowed['inferenceEndpoint']==live_inference_url(),'inference endpoint differs from the live profile host route')
  allowed_urls={'git':'https://git-fixture.ok174-proof-services.svc.cluster.local:8443/known-commit','mcp':'http://mcp-fixture.ok174-proof-services.svc.cluster.local:8081/mcp','ollama':live_inference_url()+'/api/tags'}
  for name,url in allowed_urls.items():
   record=capture_record(root,allowed['captures'][name]); expect(record['returncode']==0 and record['argv'][-1]==url,f'allowed connectivity transcript failed or retargeted: {name}')
 for name in ('denied-egress','undeclared-port-denied'):
  if status[name]=='PASS':
   expected_endpoint={'denied-egress':'http://denied-fixture.ok174-proof-services.svc.cluster.local:8081','undeclared-port-denied':'http://git-fixture.ok174-proof-services.svc.cluster.local:8080'}[name]; record=capture_for(root,results[name],'curl'); expect(record['returncode'] in (7,28) and record['stderr'] and record['argv'][-1]==expected_endpoint and (results[name].get('endpoint',expected_endpoint)==expected_endpoint),'network denial transcript has wrong target or polarity')
 if status['quota-rejection']=='PASS':
  quota=results['quota-rejection']; record=capture_for(root,quota,'apply'); expect(quota['resourceQuota']=='workspace-bounds' and quota['exceededResource']=='requests.storage' and record['argv'][1:]==['apply','-f','-'] and record['returncode']!=0 and 'requests.storage' in record['stderr'],'quota rejection does not bind raw requests.storage rejection')
 if status['ephemeral-export-cleanup']=='PASS':
  ephemeral=results['ephemeral-export-cleanup']; expect_clean_scan(capture_for(root,ephemeral,'canaryScan'),ephemeral['podName'],'ephemeral'); export=capture_for(root,ephemeral,'export'); expect_pod(export,ephemeral['podName'],'ephemeral export'); expect_pod(capture_for(root,ephemeral,'fill'),ephemeral['podName'],'ephemeral fill'); exported=capture_for(root,ephemeral,'exportReadBack'); expect(exported['returncode']==0 and exported['argv'][1:]==['get','configmap','ephemeral-proof','-n','ok174-evidence','-o','json'] and json.loads(exported['stdout']).get('data')=={'markerSha256':ephemeral['markerSha256'],'sourceNamespaceUID':ephemeral['namespaceUID']},'ephemeral export read-back contradicts marker or namespace UID'); fill=capture_for(root,ephemeral,'fill'); evicted=capture_for(root,ephemeral,'evicted'); before_delete=capture_for(root,ephemeral,'beforeDelete'); deleted=capture_for(root,ephemeral,'delete'); absent=capture_for(root,ephemeral,'namespaceAbsent'); pod_status=json.loads(evicted['stdout']).get('status',{}); expect(ephemeral['evicted'] is True and ephemeral['belowLimitReady'] is True and ephemeral['exportReadBack'] is True and ephemeral['namespaceAbsent'] is True and ephemeral['sizeLimit']=='8Mi' and export['returncode']==fill['returncode']==0 and export['stdout'].split()[0]==ephemeral['markerSha256'] and evicted['returncode']==0 and pod_status.get('reason')=='Evicted' and pod_status.get('message')==ephemeral['evictionMessage'] and re.search(r'workspace',ephemeral['evictionMessage'],re.I) and re.search(r'8Mi',ephemeral['evictionMessage'],re.I) and before_delete['returncode']==deleted['returncode']==0 and json.loads(before_delete['stdout']).get('metadata',{}).get('uid')==ephemeral['namespaceUID'] and deleted['argv'][1:]==['delete','--raw','/api/v1/namespaces/dw-ok174-ephemeral','-f','-'] and json.loads(deleted['stdout']).get('metadata',{}).get('uid')==ephemeral['namespaceUID'] and absent['returncode']!=0,'ephemeral workspace 8Mi eviction/export/UID cleanup evidence is incomplete or contradicts raw transcripts')
  readback=ephemeral['readback']; captures=readback.get('captures',{}); expect(set(captures)=={'Namespace','Deployment','NetworkPolicy','ResourceQuota','ServiceAccount','LimitRange'},'ephemeral read-back transcript set is incomplete'); observed={}
  for kind,binding in captures.items():
   record=capture_record(root,binding); expect(record['returncode']==0,'ephemeral read-back command failed'); decoded=json.loads(record['stdout']); items=[decoded] if kind=='Namespace' else [x for x in decoded.get('items',[]) if not controller_default(x)]
   for item in items: observed[f"{item['kind']}/{item['metadata']['name']}"]=normalized_readback(item)
  expected={f"{item['kind']}/{item['metadata']['name']}":normalized_readback(item) for item in expected_ephemeral_objects(s)}; expect(observed==expected and readback.get('hashes')=={key:hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest() for key,value in observed.items()},'ephemeral raw read-back differs from independently rendered objects plus approved overlays')
 for runtime in ('opencode','codex'):
  if status['runtime-task-'+runtime]=='PASS':
   e=results['runtime-task-'+runtime]; expected=s['imageReferences'][runtime]; digest=s['imageDigests'][runtime]
   expect(e['approvedImage']==expected and expected.endswith('@'+digest),'runtime approved image digest differs from image catalog')
   expect(isinstance(e['imageID'],str) and re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',e['imageID']) and e['imageID'].endswith('@'+digest),'runtime imageID digest differs from approved image')
   expect(e['beforeSha256']!=e['afterSha256'],'agent runtime task did not change fixture content')
   security=e['security']; expect(security.get('credentialAbsent') is True and security.get('apiDenied') is True and security.get('serviceAccountTokenAbsent') is True and security.get('rbacDiscoveryOnly') is True,'runtime security probes are incomplete'); expect(security.get('allowedPorts')==[8443,11434,8081] and security.get('deniedPort')==8081 and security.get('undeclaredPort')==8080,'runtime network probe set differs from the reviewed profile')
   expect(e['verificationCommand']==expected_command,'runtime verification command differs from DeveloperWorkspace declaration'); agent=e['agent']; expect(isinstance(agent.get('eventCount'),int) and agent['eventCount']>0 and agent.get('verificationCommand')==expected_command,'agent event stream does not bind the declared verification command')
   hashes=e['readback'].get('hashes',{}); required={'Namespace/dw-ok174-proof','Deployment/workspace','ResourceQuota/workspace-bounds','NetworkPolicy/default-deny','NetworkPolicy/allow-git-source','NetworkPolicy/allow-inference-shared','NetworkPolicy/allow-mcp-diagnostics','NetworkPolicy/allow-kube-dns'}; expect(required.issubset(hashes),'runtime read-back omits rendered Namespace, Deployment, quota, or NetworkPolicies')
   expected_renders=expected_live_material(s)[1]; validate_runtime_transcripts(runtime,e,root,command,live_overlay(expected_renders[runtime],s['run']['runID']),expected_live_material(s)[0][runtime]['spec']['resources'])
 if status['persistent-marker-survives-replacement']=='PASS':
  persistence=results['persistent-marker-survives-replacement']; expect(status['runtime-task-opencode']=='PASS' and persistence['oldPodUID']==results['runtime-task-opencode']['podUID'],'persistent old pod UID is stale'); expect(status['runtime-task-codex']=='PASS' and persistence['newPodUID']==results['runtime-task-codex']['podUID'],'persistent new pod UID is stale'); expect(persistence['oldPodUID']!=persistence['newPodUID'],'persistent replacement did not replace pod'); pvc_before=json.loads(capture_for(root,persistence,'pvcBefore')['stdout']); pvc_after=json.loads(capture_for(root,persistence,'pvcAfter')['stdout']); pv_before=json.loads(capture_for(root,persistence,'pvBefore')['stdout']); pv_after=json.loads(capture_for(root,persistence,'pvAfter')['stdout']); marker=capture_for(root,persistence,'markerRead'); expect_pod(marker,results['runtime-task-codex']['podName'],'persistence read'); expect_pod(capture_for(root,persistence,'markerWrite'),results['runtime-task-opencode']['podName'],'persistence write'); expect(pvc_before['metadata']['uid']==persistence['pvcUID']==pvc_after['metadata']['uid'] and pv_before['metadata']['uid']==persistence['pvUID']==pv_after['metadata']['uid'] and marker['returncode']==0 and marker['stdout'].split()[0]==persistence['markerSha256'],'persistence summary contradicts raw PVC/PV/marker transcripts')
 if status['secret-no-leak']=='PASS':
  scan=capture_for(root,results['secret-no-leak'],'runtimeWritableMounts'); expect_clean_scan(scan,results['runtime-task-codex']['podName'],'final runtime')
 if status['cleanup']=='PASS': expect(status['persistent-marker-survives-replacement']=='PASS' and results['cleanup']['reclaimedPVUID']==results['persistent-marker-survives-replacement']['pvUID'],'cleanup reclaimed PV UID differs from persistent PV UID')
 if status['cleanup']=='PASS':
  cleanup=results['cleanup']; deleted=cleanup['deletedNamespaceUIDs']; base={'ok174-proof-services','dw-ok174-proof','ok174-evidence'}; allowed=(base,) if status['ephemeral-export-cleanup']=='PASS' else (base,base|{'dw-ok174-ephemeral'}); expect(set(deleted) in allowed and all(isinstance(x,str) and x for x in deleted.values()) and len(set(deleted.values()))==len(deleted),'cleanup namespace UID ledger is incomplete or inconsistent'); captures=cleanup.get('captures',{}); expect(set(captures)=={*(f'before-{x}' for x in deleted),*(f'delete-{x}' for x in deleted),*(f'after-{x}' for x in deleted),'pvs'},'cleanup transcript set is incomplete')
  for namespace,uid in deleted.items():
   before=capture_record(root,captures['before-'+namespace]); removed=capture_record(root,captures['delete-'+namespace]); after=capture_record(root,captures['after-'+namespace]); expect(before['returncode']==removed['returncode']==0 and json.loads(before['stdout']).get('metadata',{}).get('uid')==uid and removed['argv'][1:]==['delete','--raw','/api/v1/namespaces/'+namespace,'-f','-'] and json.loads(removed['stdout']).get('metadata',{}).get('uid')==uid and after['returncode']!=0,'cleanup namespace transcript contradicts UID ledger or UID-precondition delete')
  pvs=capture_record(root,captures['pvs']); expect(pvs['returncode']==0 and not any(x.get('metadata',{}).get('uid')==cleanup['reclaimedPVUID'] for x in json.loads(pvs['stdout']).get('items',[])),'cleanup PV transcript contradicts reclaimed UID')
 if status['cluster-health']=='PASS':
  health=results['cluster-health']; before=capture_for(root,health,'before'); after=capture_for(root,health,'after'); before_hash=hashlib.sha256(json.dumps(stable_node_health(json.loads(before['stdout'])),sort_keys=True).encode()).hexdigest(); after_hash=hashlib.sha256(json.dumps(stable_node_health(json.loads(after['stdout'])),sort_keys=True).encode()).hexdigest(); expect(before['returncode']==after['returncode']==0 and health['beforeSha256']==before_hash==after_hash==health['afterSha256'],'cluster health summary contradicts raw normalized node state')
NEGATIVE_CONTROLS=('runtime-credential','serviceaccount-token','rbac-discovery-only','denied-egress','undeclared-port','storage-quota','secret-scan')
def validate_negative_controls(doc,live,root):
 """Each control must be green, then red on its live fault, then green after the revert, from hash-bound transcripts."""
 expect(doc.get('kind')=='DeveloperWorkspaceNegativeControls','invalid negative-control identity'); s=doc['spec']
 expect(s['status']=='PASS' and s['unexpectedCanaryCaptures']==[],'negative controls did not all pass')
 expect(s['implementationTreeSha256']==live['spec']['run']['implementationTreeSha256'] and s['cluster']==live['spec']['cluster'],'negative controls ran against other implementation files or on another cluster')
 expect(tuple(x['name'] for x in s['controls'])==NEGATIVE_CONTROLS,'negative control set differs')
 for path,digest in s['rawEvidence'].items():
  f=(Path(root)/path).resolve(); expect(f.is_relative_to(Path(root).resolve()) and f.is_file() and hashlib.sha256(f.read_bytes()).hexdigest()==digest,f'negative-control transcript missing or altered: {path}')
 bound={(p,d) for p,d in s['rawEvidence'].items()}
 for control in s['controls']:
  expect(control['status']=='PASS' and control.get('baselineGreen') is True and control.get('redOnFault') is True and control.get('greenAfterRevert') is True,f"negative control {control['name']} is not green-red-green")
  phases={}
  for phase in ('baseline','faulted','reverted'):
   bindings=[b for b in nested_bindings(control['captures'][phase])]; expect(bindings and all((b['path'],b['sha256']) in bound for b in bindings),f"negative control {control['name']} {phase} transcript is not bound")
   phases[phase]=[json.loads((Path(root)/b['path']).read_text()) for b in bindings]
  outcome=lambda records:[(r['returncode'],r['stdout']) for r in records]
  expect(outcome(phases['faulted'])!=outcome(phases['baseline']) and [r['returncode'] for r in phases['reverted']]==[r['returncode'] for r in phases['baseline']],f"negative control {control['name']} fault did not change the probe outcome")
def validate_verdict(verdict,evidence=None,artifact_root=None):
 expect(set(verdict)=={'apiVersion','kind','metadata','spec'} and verdict.get('apiVersion')=='evidence.openkubes.io/v1alpha1' and verdict.get('kind')=='DeveloperWorkspaceVerdict','invalid verdict identity')
 expect(verdict['metadata']=={'name':'ok174-developer-workspace-verdict-v1','ticket':'OK-174'},'invalid verdict metadata')
 spec=verdict['spec']; expected={'version','adr','adrStatus','evidenceState','recommendation','liveEvidenceComplete','unsupported','mismatches','artifacts','followUps','evidenceBoundaries'}
 expect(set(spec)==expected,'invalid verdict shape')
 expect(spec['version']=='developer-workspace-verdict/v1' and spec['adr']=='ADR-Platform-039' and spec['adrStatus']=='Proposed','verdict must leave ADR acceptance to the decision-holder')
 if evidence is None and spec['evidenceState']=='superseded-pending-rerun':
  expect(hashlib.sha256(LIVE_EVIDENCE.read_bytes()).hexdigest()==SUPERSEDED_EVIDENCE_SHA256,'pending verdict may only quarantine the known superseded evidence')
  expect(spec['liveEvidenceComplete'] is False and spec['recommendation']=='REVISE','superseded evidence requires an incomplete REVISE verdict')
  expect(spec['unsupported']==['corrected rendered-contract live evidence pending rerun'],'pending verdict unsupported list is incomplete')
  expect(spec['mismatches']==['imagePullSecrets operational overlay','run and owner label operational overlays','registry pull Secret materialization outside render','source credential Secret materialization outside render','source CA ConfigMap materialization outside render'],'pending verdict mismatch list is incomplete')
 else:
  live=load(LIVE_EVIDENCE) if evidence is None else evidence; validate_live_evidence(live,LIVE_EVIDENCE.parent if evidence is None else artifact_root); complete=evidence_complete(live); recommendation=derived_recommendation(live)
  expect(spec['evidenceState']=='current' and spec['liveEvidenceComplete'] is complete and spec['recommendation']==recommendation,'verdict recommendation and completeness must be derived from live evidence')
  expect(spec['unsupported']==live['spec']['unsupported'],'verdict mismatch list differs from live evidence')
  expect(spec['mismatches']==live['spec']['mismatches'],'verdict overlay mismatch list differs from live evidence')
  if evidence is None: validate_negative_controls(load(NEGATIVE_EVIDENCE),live,LIVE_EVIDENCE.parent)
 expect(set(spec['artifacts'])==set(ARTIFACTS),'verdict artifact membership mismatch')
 for name in ARTIFACTS:
  digest='sha256:'+hashlib.sha256((HERE/name).read_bytes()).hexdigest()
  expect(spec['artifacts'][name]==digest,f'verdict digest mismatch: {name}')
 actual={item.get('key'):item.get('role') for item in spec['followUps'] if isinstance(item,dict)}
 expect(len(spec['followUps'])==3 and actual==FOLLOW_UPS,'verdict follow-up membership/roles mismatch')
 expect(spec['evidenceBoundaries']==BOUNDARIES,'verdict evidence boundaries must be the approved immutable list')
def verify(doc,profile,rendered,verdict=None):
 expected=render(doc,profile); expect(canonical(rendered)==canonical(expected),'tracked rendered artifact differs from deterministic render')
 validate_verdict(load(VERDICT) if verdict is None else verdict)
def main():
 a=argparse.ArgumentParser(); a.add_argument('--candidate',type=Path,default=CANDIDATE); a.add_argument('--profile',type=Path,default=PROFILE); a.add_argument('--render-to',type=Path); a.add_argument('--rendered',type=Path,default=RENDERED); args=a.parse_args()
 try:
  doc=load(args.candidate); profile=load(args.profile); output=render(doc,profile)
  if args.render_to: args.render_to.write_text(canonical(output)); print('PASS rendered offline-deterministic'); return 0
  verify(doc,profile,load(args.rendered)); print('PASS schema profile deterministic-render verdict'); state=load(VERDICT)['spec']['evidenceState']; print('PASS revision-bound live evidence cross-checked against raw transcripts' if state=='current' else 'PASS superseded live evidence quarantined; corrected rerun pending'); return 0
 except (VerificationError,OSError,json.JSONDecodeError) as e: print(f'ERROR: {e}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
