import copy
import hashlib
import importlib.util
import json
import shlex
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('workspace_verify',HERE/'verify_developer_workspace_v1.py')
V=importlib.util.module_from_spec(spec); sys.modules[spec.name]=V; spec.loader.exec_module(V)
class WorkspaceRenderTests(unittest.TestCase):
 def setUp(self):
  self.doc=V.load(HERE/'developer-workspace-v0alpha1.example.yaml'); self.profile=V.load(HERE/'namespace-profile-v1.yaml'); self.rendered=V.load(HERE/'developer-workspace-v0alpha1.rendered.yaml'); self.verdict=V.load(HERE/'developer-workspace-verdict-v1.yaml')
 def reject_render(self,d=None,p=None,r=None):
  with self.assertRaises(V.VerificationError): V.verify(d or self.doc,p or self.profile,r or self.rendered)
 def valid_evidence(self,root):
  """The committed live evidence and its raw transcripts, copied so a test may tamper with them."""
  src=HERE/'live/evidence'; evidence=V.load(src/'live-evidence-v1.yaml'); run=evidence['spec']['run']['runID']
  shutil.copytree(src/'raw'/run,Path(root)/'raw'/run); return evidence
 def rehash(self,evidence,root,binding):
  digest=hashlib.sha256((Path(root)/binding['path']).read_bytes()).hexdigest(); binding['sha256']=digest
  for raw_binding in evidence['spec']['rawEvidence'].values():
   if raw_binding['path']==binding['path']: raw_binding['sha256']=digest
 def test_tracked_persistent_render_passes(self): V.verify(self.doc,self.profile,self.rendered)
 def test_current_verdict_and_tampering_fail_closed(self):
  V.validate_verdict(self.verdict)
  for mutate in (
   lambda x: x['spec'].update({'recommendation':'REVISE'}),
   lambda x: x['spec'].update({'adrStatus':'Accepted'}),
   lambda x: x['spec'].update({'liveEvidenceComplete':False}),
   lambda x: x['spec'].update({'evidenceState':'superseded-pending-rerun'}),
   lambda x: x['spec']['unsupported'].append('unrecorded effect'),
   lambda x: x['spec']['mismatches'].pop(),
   lambda x: x['spec']['artifacts'].update({'namespace-profile-v1.yaml':'sha256:'+'0'*64}),
   lambda x: x['spec']['artifacts'].pop('verify_developer_workspace_v1.py'),
   lambda x: x['spec']['evidenceBoundaries'].append('Ticket status: Backlog'),
   lambda x: x['spec']['followUps'].__setitem__(0,{'key':'OK-175','role':'wrong'}),
  ):
   x=copy.deepcopy(self.verdict); mutate(x)
   with self.subTest(mutation=mutate):
    with self.assertRaises(V.VerificationError): V.validate_verdict(x)
 def test_ephemeral_and_review_render_pass(self):
  e=copy.deepcopy(self.doc); e['spec']['storage']['mode']='ephemeral'; e['spec']['lifecycle'].update({'profile':'ephemeral','deletion':'after-retention'}); V.render(e,self.profile)
  r=copy.deepcopy(self.doc); r['spec']['lifecycle']['profile']='review'; V.render(r,self.profile)
 def test_second_runtime_uses_unchanged_contract_shape(self):
  d=copy.deepcopy(self.doc); d['spec']['runtime']['profile']='codex'; output=V.render(d,self.profile)
  self.assertEqual(output['spec']['resources'][-1]['spec']['template']['spec']['containers'][0]['image'],'example.invalid/codex:reference')
 def test_portable_status_rendered_namespace_and_provider_injection_fail(self):
  for key,value in [('status',{}),('renderedProfile',{}),('namespace','caller-selected')]:
   d=copy.deepcopy(self.doc); (d if key in ('status','renderedProfile') else d['spec'])[key]=value
   with self.subTest(key=key):
    with self.assertRaises(V.VerificationError): V.validate_input(d)
 def test_profile_references_and_narrow_egress_fail_closed(self):
  p=copy.deepcopy(self.profile); p['spec']['capabilities']['capabilityref:git-source']['destination']['cidr']='10.0.0.0/8'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['modelProfiles']['modelref:shared-inference']['inferenceCapabilityRef']='capabilityref:git-source'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['capabilities']['capabilityref:mcp-diagnostics']['approvedTools']=[]; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['credentials'].pop('credentialref:workspace-git-auth'); self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['unexpected']='authority'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['runtimeProfiles']['opencode']['token']='inline'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['modelProfiles']['modelref:shared-inference']['endpoint']='inline'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['capabilities']['capabilityref:git-source']['destination']['token']='inline'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['credentials']['credentialref:workspace-git-auth']['value']='inline'; self.reject_render(p=p)
  p=copy.deepcopy(self.profile); p['spec']['sources']['sourceref:openkubes']['endpoint']='https://user:secret@git.example.invalid'; self.reject_render(p=p)
  for path in ('../../other','owner//repo','owner\\repo'):
   p=copy.deepcopy(self.profile); p['spec']['sources']['sourceref:openkubes']['repositoryPath']=path
   with self.subTest(path=path): self.reject_render(p=p)
  d=copy.deepcopy(self.doc); d['spec']['source']['repositoryRef']='sourceref:unknown'; self.reject_render(d=d)
 def test_lifecycle_and_storage_combinations_fail_closed(self):
  d=copy.deepcopy(self.doc); d['spec']['lifecycle']['profile']='ephemeral'; self.reject_render(d=d)
  d=copy.deepcopy(self.doc); d['spec']['lifecycle']['profile']='review'; d['spec']['capabilities']['kubernetes']['access']='read'; self.reject_render(d=d)
 def test_tampered_rendered_evidence_extra_resources_secrets_and_escape_fail(self):
  r=copy.deepcopy(self.rendered); r['spec']['resources'].append({'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'leak'},'data':{'token':'plaintext'}}); self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['hostNetwork']=True; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['containers'][0]['securityContext']['privileged']=True; self.reject_render(r=r)
 def test_checkout_only_has_source_credential_ca_and_writable_paths(self):
  pod=self.rendered['spec']['resources'][-1]['spec']['template']['spec']; checkout=pod['initContainers'][0]
  runtime=pod['containers'][0]
  self.assertIn({'name':'GIT_AUTH_TOKEN','valueFrom':{'secretKeyRef':{'name':'workspace-git-auth','key':'token'}}},checkout['env'])
  self.assertIn({'name':'GIT_SSL_CAINFO','value':'/etc/ssl/certs/source-ca/ca.crt'},checkout['env'])
  self.assertNotIn('GIT_AUTH_TOKEN',[item['name'] for item in runtime['env']])
  self.assertNotIn('GIT_SSL_CAINFO',[item['name'] for item in runtime['env']])
  self.assertEqual(runtime['env'],[{'name':'OK174_INFERENCE_BASE_URL','value':'http://192.168.100.202:11434/v1'},{'name':'OK174_MODEL','value':'ok174-gpt-oss:20b'}])
  self.assertEqual([x['name'] for x in checkout['volumeMounts']],['workspace','checkout-tmp','checkout-home','source-ca'])
  self.assertEqual([x['name'] for x in runtime['volumeMounts']],['workspace','runtime-tmp','runtime-home'])
  self.assertEqual({x['name'] for x in checkout['volumeMounts']} & {x['name'] for x in runtime['volumeMounts']},{'workspace'})
  self.assertEqual(checkout['workingDir'],'/workspace')
  self.assertEqual(checkout['command'],['checkout'])
  self.assertEqual(checkout['args'][-1],'/workspace')
  deployment=next(x for x in self.rendered['spec']['resources'] if x['kind']=='Deployment'); self.assertEqual(deployment['spec']['strategy'],{'type':'Recreate'}) # quota admits one workspace pod
  pvc=next(x for x in self.rendered['spec']['resources'] if x['kind']=='PersistentVolumeClaim')
  self.assertEqual(pvc['spec']['storageClassName'],'local-path')
  for container in [checkout,runtime]: self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
 def test_service_destinations_and_dns_are_rendered_from_profile_selectors(self):
  policies={x['metadata']['name']:x for x in self.rendered['spec']['resources'] if x['kind']=='NetworkPolicy'}
  target=policies['allow-git-source']['spec']['egress'][0]['to'][0]
  self.assertEqual(target['namespaceSelector']['matchLabels'],{'kubernetes.io/metadata.name':'ok174-proof-services'})
  self.assertEqual(target['podSelector']['matchLabels'],{'app':'git-fixture'})
  self.assertEqual(policies['allow-inference-shared']['spec']['egress'][0],{'to':[{'ipBlock':{'cidr':'192.168.100.202/32'}}],'ports':[{'protocol':'TCP','port':11434}]})
  self.assertEqual(policies['allow-kube-dns']['spec']['egress'][0]['ports'],[{'protocol':'UDP','port':53},{'protocol':'TCP','port':53}])
 def test_live_evidence_cross_checks_reject_all_known_mutations(self):
  with tempfile.TemporaryDirectory() as directory:
   evidence=self.valid_evidence(directory)
   mutations=(
   ('wrong cluster UID',lambda x,r: x['spec']['cluster'].update({'uidSha256':'0'*64})),
   ('swapped runtime digests',lambda x,r: x['spec']['imageDigests'].update({'opencode':x['spec']['imageDigests']['codex'],'codex':x['spec']['imageDigests']['opencode']})),
   ('imageID digest differs',lambda x,r: r['runtime-task-opencode'].update({'imageID':'registry.invalid/opencode@sha256:'+'0'*64})),
   ('imageID NOT-RUN prefix',lambda x,r: r['runtime-task-opencode'].update({'imageID':'NOT-RUN '+r['runtime-task-opencode']['approvedImage']})),
   ('finished before started',lambda x,r: x['spec']['run'].update({'finishedAt':'2020-01-01T00:00:00Z'})),
   ('non-RFC3339 startedAt',lambda x,r: x['spec']['run'].update({'startedAt':'yesterday-ish'})),
   ('checkout differs from knownCommit',lambda x,r: r['source-checkout'].update({'commit':x['spec']['revision']})),
   ('oldPodUID from another run',lambda x,r: r['persistent-marker-survives-replacement'].update({'oldPodUID':'stale-pod-uid'})),
   ('oldPodUID equals newPodUID',lambda x,r: r['persistent-marker-survives-replacement'].update({'newPodUID':r['persistent-marker-survives-replacement']['oldPodUID']})),
   ('reclaimed PV differs',lambda x,r: r['cleanup'].update({'reclaimedPVUID':r['persistent-marker-survives-replacement']['pvcUID']})),
   ('health hashes differ',lambda x,r: r['cluster-health'].update({'afterSha256':'0'*64})),
   ('revision is forty zeroes',lambda x,r: x['spec'].update({'revision':'0'*40})),
   ('runtime sees source secret',lambda x,r: r['secret-reference'].update({'runtimeHasSecret':True})),
   ('runtime security probe missing',lambda x,r: r['runtime-task-codex']['security'].update({'rbacDiscoveryOnly':False})),
   )
   for name,mutate in mutations:
    x=copy.deepcopy(evidence); current={item['name']:item['evidence'] for item in x['spec']['results']}; mutate(x,current)
    with self.subTest(mutation=name):
     with self.assertRaises(V.VerificationError): V.validate_live_evidence(x,directory)
 def test_non_go_verdict_is_derived_from_incomplete_evidence(self):
  with tempfile.TemporaryDirectory() as directory:
   evidence=self.valid_evidence(directory); evidence['spec']['status']='REVISE'; evidence['spec']['results'][0].update({'status':'FAIL','detail':'source checkout missing','evidence':{}})
   verdict=copy.deepcopy(self.verdict); verdict['spec'].update({'evidenceState':'current','liveEvidenceComplete':False,'recommendation':'REVISE','unsupported':evidence['spec']['unsupported'],'mismatches':evidence['spec']['mismatches']})
   V.validate_verdict(verdict,evidence,directory)
 def test_rehashed_raw_transcripts_cannot_substitute_wrong_effects(self):
  for mutation in ('privileged deployment','substituted security command','retargeted denial','unrelated eviction'):
   with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
    evidence=self.valid_evidence(directory); results={item['name']:item['evidence'] for item in evidence['spec']['results']}; root=Path(directory)
    if mutation=='privileged deployment':
     binding=results['runtime-task-opencode']['readback']['captures']['Deployment']; path=root/binding['path']; record=json.loads(path.read_text()); payload=json.loads(record['stdout']); deployment=next(x for x in payload['items'] if x['metadata']['name']=='workspace'); deployment['spec']['template']['spec']['containers'][0]['securityContext']['privileged']=True; record['stdout']=json.dumps(payload); path.write_text(json.dumps(record,sort_keys=True)); key='Deployment/workspace'; results['runtime-task-opencode']['readback']['hashes'][key]=hashlib.sha256(json.dumps(V.normalized_readback(deployment),sort_keys=True).encode()).hexdigest()
    elif mutation=='substituted security command':
     binding=results['runtime-task-codex']['security']['captures']['environment']; path=root/binding['path']; record=json.loads(path.read_text()); record['argv']=['kubectl']; path.write_text(json.dumps(record,sort_keys=True))
    elif mutation=='retargeted denial':
     binding=results['denied-egress']['captures']['curl']; path=root/binding['path']; record=json.loads(path.read_text()); record['argv'][-1]='http://127.0.0.1:9'; path.write_text(json.dumps(record,sort_keys=True))
    else:
     ephemeral=results['ephemeral-export-cleanup']; ephemeral['evictionMessage']='Usage of EmptyDir volume unrelated-cache exceeds the limit 1Mi'; binding=ephemeral['captures']['evicted']; path=root/binding['path']; record=json.loads(path.read_text()); record['stdout']=json.dumps({'status':{'reason':'Evicted','message':ephemeral['evictionMessage']}}); path.write_text(json.dumps(record,sort_keys=True))
    self.rehash(evidence,directory,binding)
    with self.assertRaises(V.VerificationError): V.validate_live_evidence(evidence,directory)
 def test_real_evidence_rejects_red_team_transcript_substitutions(self):
  def other_pod(results,root):
   codex=results['runtime-task-codex']; binding=codex['captures']['agent']; path=Path(root)/binding['path']; record=json.loads(path.read_text())
   record['argv']=[x.replace('pod/'+codex['podName'],'pod/'+results['runtime-task-opencode']['podName']) for x in record['argv']]; path.write_text(json.dumps(record,sort_keys=True)); return binding
  def scan_errors(results,root):
   binding=results['runtime-task-codex']['security']['captures']['canaryScan']; path=Path(root)/binding['path']; record=json.loads(path.read_text())
   record['stderr']='grep: /tmp/broken-link: No such file or directory\n'; path.write_text(json.dumps(record,sort_keys=True)); return binding
  def read_not_edit(results,root):
   binding=results['runtime-task-codex']['captures']['agent']; path=Path(root)/binding['path']; record=json.loads(path.read_text()); lines=[]
   for line in record['stdout'].splitlines():
    try: event=json.loads(line)
    except ValueError: lines.append(line); continue
    item=event.get('item') or {}
    if item.get('type')=='command_execution' and 'README.md' in str(item.get('command','')) and '>' in str(item.get('command','')): item['command']="/usr/bin/bash -lc 'cat README.md'"
    lines.append(json.dumps(event))
   record['stdout']='\n'.join(lines)+'\n'; path.write_text(json.dumps(record,sort_keys=True)); return binding
  for name,tamper in (('exec target is the other runtime pod',other_pod),('canary scan reported errors',scan_errors),('edit replaced by a read',read_not_edit)):
   with self.subTest(mutation=name), tempfile.TemporaryDirectory() as directory:
    evidence=self.valid_evidence(directory); V.validate_live_evidence(copy.deepcopy(evidence),directory)
    results={item['name']:item['evidence'] for item in evidence['spec']['results']}; self.rehash(evidence,directory,tamper(results,directory))
    with self.assertRaises(V.VerificationError): V.validate_live_evidence(evidence,directory)
 def test_each_resource_and_credential_bound_tamper_fails(self):
  r=copy.deepcopy(self.rendered); quota=next(x for x in r['spec']['resources'] if x['kind']=='ResourceQuota'); quota['spec']['hard']['limits.cpu']='9'; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['initContainers'][0]['volumeMounts']=[]; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['initContainers'][0].pop('workingDir'); self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['initContainers'][0]['args'][-1]='/tmp'; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['initContainers'][0]['env']=[]; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['containers'][0]['securityContext']['readOnlyRootFilesystem']=False; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); pod=r['spec']['resources'][-1]['spec']['template']['spec']; pod['initContainers'][0]['env'][0]['valueFrom']['secretKeyRef']['key']='wrong'; self.reject_render(r=r)
  r=copy.deepcopy(self.rendered); policy=next(x for x in r['spec']['resources'] if x['kind']=='NetworkPolicy' and x['metadata']['name']=='allow-git-source'); policy['spec']['egress'][0]['to'][0]['podSelector']['matchLabels']['app']='wide-open'; self.reject_render(r=r)
if __name__=='__main__': unittest.main()
