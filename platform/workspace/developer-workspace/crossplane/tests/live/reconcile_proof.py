#!/usr/bin/env python3
"""Live proof of the DeveloperWorkspace reconciler path (OK-175).

The OK-174 harness applied render() output itself. Here a DeveloperWorkspace XR is applied and
Crossplane, function-go-templating and provider-kubernetes reconcile it. The proof requires:
  - the reconciled Namespace objects equal render() for the same document and profile;
  - the checkout is the declared revision and the XR is Ready only once the workspace runs;
  - no ambient Kubernetes authority (no token, discovery-only RBAC, API unreachable);
  - no push or merge authority: the runtime has no source credential, the workspace credential
    is refused for push by the source, and a write-credential control push succeeds;
  - workspace identity collisions are refused without changing or deleting the owner;
  - operator and observer identities stay inside their documented authority boundary;
  - deleting the XR removes the Namespace and every composed object.
Every denial has a control that shows the same check passes when the authority exists.

Actions: install | run | uninstall. Mutation requires an explicit KUBECONFIG whose current
context is TARGET_CONTEXT and one of the disposable targets below.
"""
from __future__ import annotations
import argparse, base64, copy, hashlib, importlib.util, json, os, re, secrets, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parents[1]
REPO = CAPABILITY.parents[3]
LIVE = REPO / 'architecture/spikes/ADR-Platform-039/live'
EVIDENCE = CAPABILITY / 'evidence'
DISPOSABLE_CONTEXTS = ('ok-175-proof-admin@ok-175-proof', 'kind-ok175-preflight')
CROSSPLANE_CHART = ('https://charts.crossplane.io/stable', 'crossplane', '2.3.3')
PROOF_NS = 'ok174-proof-services'  # the reviewed live profile's source destination
PULL_SECRET = 'workspace-registry-pull'
PERSISTENT = ('ws-ok175-proof-xr', 'ws-ok175-proof')
DISTINCT = (('ws-c69924-xr', 'ws-c69924'), ('ws-cd9634-xr', 'ws-cd9634'))
SQUAT = ('ws-ok175-squat-xr', 'ws-ok175-squat')
NO_PROFILE = ('ws-ok175-no-profile-xr', 'ws-ok175-no-profile')
OPERATOR_SA, OBSERVER_SA = 'developer-workspace-operator', 'developer-workspace-observer'
OPERATOR_BINDING, OBSERVER_BINDING = 'ok175-proof-developer-workspace-operator', 'ok175-proof-developer-workspace-observer'
GIT_URL = 'https://git-fixture.ok174-proof-services.svc.cluster.local:8443/workspace-fixture.git'
KUBE_API = 'https://kubernetes.default.svc'

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path); module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module; spec.loader.exec_module(module); return module  # dataclasses resolve their module by name

spike = load_module('ok174_live_proof', LIVE / 'probes/live_proof.py')  # reused helpers only; the spike is not modified
render_profile = load_module('ok175_profile', CAPABILITY / 'tests/profile_config.py')

class ProofError(RuntimeError): pass
def expect(ok, message):
    if not ok: raise ProofError(message)
def is_not_found(done): return done.returncode != 0 and bool(re.search(r'\(NotFound\):', done.stderr))
def sha(data): return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
def sha_json(value): return sha(json.dumps(value, sort_keys=True, separators=(',', ':')))
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def kubectl(args, *, input_text=None, timeout=120, check=True):
    done = subprocess.run(['kubectl', *args], input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and done.returncode: raise ProofError(f"kubectl {' '.join(args[:3])} failed ({done.returncode}): {done.stderr.strip()[:300]}")
    return done
def apply(objects): kubectl(['apply', '-f', '-'], input_text='---\n'.join(yaml.safe_dump(o, sort_keys=False) for o in objects))
def apply_file(path): kubectl(['apply', '-f', str(path)])
def get_json(args): return json.loads(kubectl([*args, '-o', 'json']).stdout)
def exec_in(namespace, pod, command, container=None, input_text=None):
    args = ['exec', *(['-i'] if input_text is not None else []), f'pod/{pod}', '-n', namespace, *(['-c', container] if container else []), '--', *command]
    return kubectl(args, input_text=input_text, check=False)
def wait_until(what, predicate, timeout=600, interval=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(interval)
    raise ProofError(f'timed out waiting for {what}')

def target():
    path = os.environ.get('KUBECONFIG', ''); expect(path and os.pathsep not in path and Path(path).is_file(), 'KUBECONFIG must name exactly one readable file')
    context = kubectl(['config', 'current-context']).stdout.strip()
    expect(context == os.environ.get('TARGET_CONTEXT') and context in DISPOSABLE_CONTEXTS, f'current context {context!r} is not the selected disposable target')
    version = get_json(['version'])['serverVersion']['gitVersion']; uid = get_json(['get', 'namespace', 'kube-system'])['metadata']['uid']
    # A context name can be reused; the kube-system UID pins the one cluster the operator selected.
    expect(os.environ.get('OK175_TARGET_UID_SHA256') == sha(uid), 'OK175_TARGET_UID_SHA256 does not match the kube-system UID of the selected cluster')
    return {'context': context, 'kubernetesVersion': version, 'kubeSystemUidSha256': sha(uid)}

# Spike files this proof depends on: the render() oracle, the reused helpers and the live inputs.
SPIKE_INPUTS = ('verify_developer_workspace_v1.py', 'live/probes/live_proof.py', 'live/profile/namespace-profile-live.yaml',
                'live/profile/developer-workspace-live.yaml', 'live/fixtures/entrypoint.sh', 'live/fixtures/Dockerfile')

def implementation(require_clean):
    head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True, capture_output=True, check=True).stdout.strip()
    spike_paths = [LIVE.parent / x for x in SPIKE_INPUTS]
    dirty = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain', '--', str(CAPABILITY.relative_to(REPO)), *(str(x.relative_to(REPO)) for x in spike_paths), ':(exclude)' + str(EVIDENCE.relative_to(REPO))], text=True, capture_output=True, check=True).stdout
    expect(not (require_clean and dirty), 'capability directory or spike inputs have uncommitted changes')
    files = sorted(p for p in CAPABILITY.rglob('*') if p.is_file() and EVIDENCE not in p.parents and '__pycache__' not in p.parts)
    return {'head': head, 'clean': not dirty, 'files': {str(p.relative_to(CAPABILITY)): sha(p.read_bytes()) for p in files},
            'spikeInputs': {x: sha((LIVE.parent / x).read_bytes()) for x in SPIKE_INPUTS}}

def installed_matches_local():
    """The objects that ran must be the files the evidence hashes, not an earlier install."""
    local = lambda path: yaml.safe_load((CAPABILITY / path).read_text())
    composition = get_json(['get', 'composition', local('composition.yaml')['metadata']['name']])
    expect(composition['spec']['pipeline'] == local('composition.yaml')['spec']['pipeline'], 'installed Composition differs from composition.yaml')
    xrd = get_json(['get', 'compositeresourcedefinition', local('xrd.yaml')['metadata']['name']])
    expect(xrd['spec']['versions'][0]['schema'] == local('xrd.yaml')['spec']['versions'][0]['schema'], 'installed XRD schema differs from xrd.yaml')
    xrd_schema = local('xrd.yaml')['spec']['versions'][0]['schema']['openAPIV3Schema']
    generated_crd = get_json(['get', 'crd', 'developerworkspaces.workspace.openkubes.io'])
    generated_version = next(v for v in generated_crd['spec']['versions'] if v['name'] == 'v0alpha1')
    generated_schema = generated_version['schema']['openAPIV3Schema']
    expect(generated_schema.get('x-kubernetes-validations') == xrd_schema.get('x-kubernetes-validations'),
           'generated CRD root CEL validations differ from xrd.yaml')
    expect(generated_schema['properties']['spec'].get('x-kubernetes-validations') == xrd_schema['properties']['spec'].get('x-kubernetes-validations'),
           'generated CRD spec CEL validations differ from xrd.yaml')
    expect(generated_schema['properties']['spec']['properties']['workspaceID'].get('maxLength') ==
           xrd_schema['properties']['spec']['properties']['workspaceID'].get('maxLength') == 51,
           'generated CRD workspaceID maxLength differs from xrd.yaml or is not 51')
    role = next(d for d in yaml.safe_load_all((CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml').read_text()) if d['kind'] == 'ClusterRole')
    expect(get_json(['get', 'clusterrole', role['metadata']['name']])['rules'] == role['rules'], 'installed ClusterRole differs from rbac/')
    authority_roles = [d for d in yaml.safe_load_all((CAPABILITY / 'rbac/authority-boundary.yaml').read_text()) if d]
    expect({d['kind'] for d in authority_roles} == {'ClusterRole'}, 'authority-boundary.yaml must contain only ClusterRoles')
    for authority_role in authority_roles:
        live_role = get_json(['get', 'clusterrole', authority_role['metadata']['name']])
        expect(live_role['rules'] == authority_role['rules'], f"installed ClusterRole {authority_role['metadata']['name']} differs from authority-boundary.yaml")
    policy, binding = yaml.safe_load_all((CAPABILITY / 'install/namespace-guard.yaml').read_text())
    live = get_json(['get', 'validatingadmissionpolicy', policy['metadata']['name']])['spec']
    expect(all(live.get(k) == policy['spec'][k] for k in ('matchConditions', 'variables', 'validations')), 'installed namespace guard differs from install/namespace-guard.yaml')
    expect(get_json(['get', 'validatingadmissionpolicybinding', binding['metadata']['name']])['spec'].get('validationActions') == ['Deny'], 'namespace guard binding is not Deny')
    return composition

def revision_matches(xr_name, composition):
    ref = get_json(['get', f'developerworkspace/{xr_name}'])['spec']['crossplane']['compositionRevisionRef']['name']
    revision = get_json(['get', 'compositionrevision', ref])
    expect(revision['spec']['pipeline'] == composition['spec']['pipeline'], f'{xr_name} runs CompositionRevision {ref}, which differs from composition.yaml')
    return ref

def image(name):
    value = os.environ.get(name, ''); expect(bool(re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', value)), f'{name} must be a digest reference'); return value

def install(_args):
    target()
    repo, chart, version = CROSSPLANE_CHART
    subprocess.run(['helm', 'upgrade', '--install', 'crossplane', chart, '--repo', repo, '--version', version, '-n', 'crossplane-system', '--create-namespace', '--wait', '--timeout', '10m'], check=True)
    apply_file(CAPABILITY / 'tests/functions.yaml'); apply_file(CAPABILITY / 'install/provider-kubernetes.yaml')
    kubectl(['wait', '--for=condition=Healthy', 'function.pkg.crossplane.io/function-go-templating', 'function.pkg.crossplane.io/function-auto-ready', 'provider.pkg.crossplane.io/provider-kubernetes', '--timeout=600s'], timeout=630)
    apply_file(CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml'); apply_file(CAPABILITY / 'rbac/authority-boundary.yaml')
    apply_file(CAPABILITY / 'install/namespace-guard.yaml'); apply_file(CAPABILITY / 'install/providerconfig.yaml')
    apply_file(CAPABILITY / 'xrd.yaml')
    kubectl(['wait', '--for=condition=Established', 'compositeresourcedefinition/developerworkspaces.workspace.openkubes.io', '--timeout=300s'], timeout=330)
    apply_file(CAPABILITY / 'composition.yaml')
    print('installed Crossplane', version, 'with the DeveloperWorkspace capability')

def uninstall(_args):
    target()
    listed = kubectl(['get', 'developerworkspaces', '-o', 'json'], check=False)
    expect(listed.returncode != 0 and 'the server doesn' in listed.stderr or listed.returncode == 0 and not json.loads(listed.stdout)['items'], 'DeveloperWorkspaces still exist; delete them first')
    for path in ('composition.yaml', 'xrd.yaml', 'install/providerconfig.yaml', 'install/namespace-guard.yaml', 'rbac/authority-boundary.yaml', 'rbac/provider-kubernetes-clusterrole.yaml', 'install/provider-kubernetes.yaml', 'tests/functions.yaml'):
        done = kubectl(['delete', '--ignore-not-found', '--wait=true', '-f', str(CAPABILITY / path)], timeout=600, check=False)
        expect(done.returncode == 0 or 'no matches for kind' in done.stderr, f'deleting {path} failed: {done.stderr.strip()[:300]}')  # kind already gone with its CRD
    if subprocess.run(['helm', 'status', 'crossplane', '-n', 'crossplane-system'], capture_output=True).returncode == 0:
        subprocess.run(['helm', 'uninstall', 'crossplane', '-n', 'crossplane-system', '--wait'], check=True)
    kubectl(['delete', 'namespace', 'crossplane-system', '--ignore-not-found', '--wait=true'], timeout=600)
    # Helm never deletes CRDs; Crossplane's and the packages' are left otherwise.
    crds = [c['metadata']['name'] for c in get_json(['get', 'crd'])['items'] if c['spec']['group'].endswith('crossplane.io')]
    if crds: kubectl(['delete', 'crd', *crds, '--wait=true'], timeout=600)
    expect(not [c for c in get_json(['get', 'crd'])['items'] if c['spec']['group'].endswith('crossplane.io')], 'Crossplane CRDs remain')
    print(f'uninstalled; removed {len(crds)} Crossplane CRDs')

# ---- proof fixtures -------------------------------------------------------------------------

def pull_secret(namespace, registry, username, password):
    auth = base64.b64encode(f'{username}:{password}'.encode()).decode()
    data = base64.b64encode(json.dumps({'auths': {registry: {'username': username, 'password': password, 'auth': auth}}}).encode()).decode()
    return {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': PULL_SECRET, 'namespace': namespace}, 'type': 'kubernetes.io/dockerconfigjson', 'data': {'.dockerconfigjson': data}}

def proof_services(fixture_image, tls, read_token, write_token, pulls):
    meta = lambda name: {'name': name, 'namespace': PROOF_NS}
    pod_base = {'imagePullSecrets': [{'name': PULL_SECRET}]} if pulls else {}
    token_env = [{'name': n, 'valueFrom': {'secretKeyRef': {'name': 'git-source-tokens', 'key': k}}} for n, k in (('GIT_READ_TOKEN', 'read'), ('GIT_WRITE_TOKEN', 'write'))]
    git = {'name': 'git-fixture', 'image': fixture_image, 'ports': [{'containerPort': 8443}],
           'env': [*token_env, {'name': 'GIT_TLS_CERT_FILE', 'value': '/var/run/git-tls/tls.crt'}, {'name': 'GIT_TLS_KEY_FILE', 'value': '/var/run/git-tls/tls.key'}],
           'volumeMounts': [{'name': 'tls', 'mountPath': '/var/run/git-tls', 'readOnly': True}, {'name': 'server', 'mountPath': '/usr/local/bin/server.py', 'subPath': 'server.py', 'readOnly': True}],
           'readinessProbe': {'tcpSocket': {'port': 8443}}}
    control = {'name': 'control', 'image': fixture_image, 'command': ['sleep', 'infinity'], 'env': [*token_env, {'name': 'GIT_SSL_CAINFO', 'value': '/var/run/git-ca/ca.crt'}, {'name': 'GIT_TERMINAL_PROMPT', 'value': '0'}, {'name': 'HOME', 'value': '/tmp'}],
               'volumeMounts': [{'name': 'ca', 'mountPath': '/var/run/git-ca', 'readOnly': True}]}
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': PROOF_NS}},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': meta('git-fixture-tls'), 'type': 'kubernetes.io/tls', 'stringData': {'tls.crt': tls['cert'], 'tls.key': tls['key']}},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': meta('git-source-tokens'), 'type': 'Opaque', 'stringData': {'read': read_token, 'write': write_token}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('git-fixture-ca'), 'data': {'ca.crt': tls['ca']}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('git-source-server'), 'data': {'server.py': (HERE / 'source-server.py').read_text()}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta('git-fixture'), 'spec': {'selector': {'matchLabels': {'app': 'git-fixture'}}, 'template': {'metadata': {'labels': {'app': 'git-fixture'}}, 'spec': {
            **pod_base, 'containers': [git], 'volumes': [{'name': 'tls', 'secret': {'secretName': 'git-fixture-tls'}}, {'name': 'server', 'configMap': {'name': 'git-source-server'}}]}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': meta('git-fixture'), 'spec': {'selector': {'app': 'git-fixture'}, 'ports': [{'name': 'https', 'port': 8443, 'targetPort': 8443}]}},
        {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': meta('control'), 'spec': {**pod_base, 'restartPolicy': 'Never', 'containers': [control], 'volumes': [{'name': 'ca', 'configMap': {'name': 'git-fixture-ca'}}]}},
    ]

def workspace_inputs(name, workspace_id, revision, mode):
    doc = yaml.safe_load((LIVE / 'profile/developer-workspace-live.yaml').read_text())
    doc['metadata']['name'] = name; doc['spec']['workspaceID'] = workspace_id; doc['spec']['source']['revision'] = revision
    if mode == 'ephemeral':
        doc['spec']['storage'] = {'mode': 'ephemeral', 'size': '8Mi'}; doc['spec']['lifecycle'].update({'profile': 'ephemeral', 'deletion': 'after-retention'})
    return doc

def canonical_xr_name(workspace_id): return f'{workspace_id}-xr'

def expected_objects(doc, profile, pulls):
    resources = copy.deepcopy(spike.renderer().render(doc, profile)['spec']['resources'])
    if pulls: next(r for r in resources if r['kind'] == 'Deployment')['spec']['template']['spec']['imagePullSecrets'] = [{'name': PULL_SECRET}]
    return resources

def normalized(item):
    value = spike.normalized(item)
    annotations = value.get('metadata', {}).get('annotations', {})
    for key in [k for k in annotations if k.startswith('kubernetes.crossplane.io/')]: annotations.pop(key)  # provider bookkeeping
    if not annotations: value.get('metadata', {}).pop('annotations', None)
    return value

def readback(namespace, expected):
    """Every composed object must equal its render() counterpart; nothing unrendered may appear."""
    for kind in ('Namespace', 'ServiceAccount', 'ResourceQuota', 'LimitRange', 'NetworkPolicy', 'PersistentVolumeClaim', 'Deployment'):
        wanted = {o['metadata']['name']: normalized(o) for o in expected if o['kind'] == kind}
        if kind == 'Namespace': items = [get_json(['get', 'namespace', namespace])]
        else: items = [i for i in get_json(['get', kind.lower(), '-n', namespace])['items'] if not spike.controller_default(i)]
        got = {i['metadata']['name']: normalized(i) for i in items}
        expect(set(got) == set(wanted), f'{kind}: reconciled {sorted(got)} != rendered {sorted(wanted)}')
        for name in wanted:
            expect(got[name] == wanted[name], f'{kind}/{name} differs from render(): got {json.dumps(got[name], sort_keys=True)[:600]}')
    return len(expected)

def workspace_pod(namespace):
    pods = [p for p in get_json(['get', 'pods', '-n', namespace])['items'] if p.get('status', {}).get('phase') == 'Running' and not p['metadata'].get('deletionTimestamp')]
    expect(len(pods) == 1, f'expected one running workspace pod in {namespace}, found {len(pods)}'); return pods[0]['metadata']['name']

def wait_ready(name):
    kubectl(['wait', '--for=condition=Ready', f'developerworkspace/{name}', '--timeout=600s'], timeout=630)

def composed_object_items(name):
    return [o for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items'] if o['metadata'].get('labels', {}).get('crossplane.io/composite') == name]

def composed_objects(name): return [o['metadata']['name'] for o in composed_object_items(name)]

def owner_snapshot(name, namespace, expected=None):
    """Capture owner, composed Object desired state, and rendered-resource readback."""
    xr = get_json(['get', f'developerworkspace/{name}'])
    xr_uid = xr['metadata']['uid']
    owner = get_json(['get', 'namespace', namespace])
    objects = {}
    for item in composed_object_items(name):
        metadata = item['metadata']
        owner_references = sorted(metadata.get('ownerReferences', []), key=lambda ref: (ref.get('kind', ''), ref.get('name', '')))
        expect(any(ref.get('uid') == xr_uid and ref.get('controller') is True for ref in owner_references),
               f"Object/{metadata['name']} lacks a controller reference to {name}/{xr_uid}")
        objects[metadata['name']] = {
            'uid': metadata['uid'],
            'resourceVersion': metadata['resourceVersion'],
            'generation': metadata['generation'],
            'metadata': {key: copy.deepcopy(value) for key, value in metadata.items() if key not in ('resourceVersion', 'managedFields')},
            'ownerReferences': owner_references,
            'spec': copy.deepcopy(item['spec']),
        }
    expect(objects, f'{name} has no composed Object references to snapshot')
    resources = {}
    for wanted in expected or ():
        kind, resource_name = wanted['kind'], wanted['metadata']['name']
        item = owner if kind == 'Namespace' else get_json(['get', f'{kind.lower()}/{resource_name}', '-n', namespace])
        resources[f'{kind}/{resource_name}'] = {
            'uid': item['metadata']['uid'],
            'resourceVersion': item['metadata']['resourceVersion'],
            'content': normalized(item),
        }
    return {
        'xrUID': xr_uid,
        'xrResourceVersion': xr['metadata']['resourceVersion'],
        'xrGeneration': xr['metadata']['generation'],
        'xrSpec': copy.deepcopy(xr['spec']),
        'namespace': {'uid': owner['metadata']['uid'], 'resourceVersion': owner['metadata']['resourceVersion'], 'content': normalized(owner)},
        'objects': objects,
        'resources': resources,
    }

def assert_owner_unchanged(before, after, *, strict_object_rv=True, strict_resource_rv=True):
    expect(after['xrUID'] == before['xrUID'], 'owner DeveloperWorkspace UID changed during protected interval')
    expect(after['xrGeneration'] == before['xrGeneration'], 'owner DeveloperWorkspace generation changed during protected interval')
    expect(after['xrSpec'] == before['xrSpec'], 'owner DeveloperWorkspace spec changed during protected interval')
    expect(bool(after['xrResourceVersion']) and bool(before['xrResourceVersion']), 'owner DeveloperWorkspace resourceVersion missing')
    if strict_object_rv:
        expect(after['xrResourceVersion'] == before['xrResourceVersion'], 'owner DeveloperWorkspace resourceVersion changed during protected interval')
    expect(after['namespace'] == before['namespace'], 'owner Namespace identity, resourceVersion or content changed during protected interval')
    expect(set(after['objects']) == set(before['objects']), 'owner composed Object reference set changed during protected interval')
    for name, old in before['objects'].items():
        new = after['objects'][name]
        expect(new['uid'] == old['uid'], f'owner Object/{name} UID changed during protected interval')
        expect(new['metadata'] == old['metadata'], f'owner Object/{name} metadata changed during protected interval')
        expect(new['ownerReferences'] == old['ownerReferences'], f'owner Object/{name} ownership changed during protected interval')
        expect(new['spec'] == old['spec'], f'owner Object/{name} spec changed during protected interval')
        expect(new['generation'] == old['generation'], f'owner Object/{name} generation changed during protected interval')
        expect(bool(new['resourceVersion']) and bool(old['resourceVersion']), f'owner Object/{name} resourceVersion missing')
        if strict_object_rv:
            expect(new['resourceVersion'] == old['resourceVersion'], f'owner Object/{name} resourceVersion changed during protected interval')
    expect(set(after.get('resources', {})) == set(before.get('resources', {})), 'owner rendered resource set changed during protected interval')
    for name, old in before.get('resources', {}).items():
        new = after['resources'][name]
        expect(new['uid'] == old['uid'], f'owner readback {name} UID changed during protected interval')
        expect(new['content'] == old['content'], f'owner readback {name} content changed during protected interval')
        expect(bool(new['resourceVersion']) and bool(old['resourceVersion']), f'owner readback {name} resourceVersion missing')
        if strict_resource_rv:
            expect(new['resourceVersion'] == old['resourceVersion'], f'owner readback {name} resourceVersion changed during protected interval')
    return {
        'workspaceUID': before['xrUID'], 'workspaceGeneration': before['xrGeneration'],
        'workspaceResourceVersionBefore': before['xrResourceVersion'],
        'workspaceResourceVersionAfter': after['xrResourceVersion'],
        'workspaceSpecSha256Before': sha_json(before['xrSpec']),
        'workspaceSpecSha256After': sha_json(after['xrSpec']),
        'namespace': {'uid': before['namespace']['uid'], 'resourceVersionBefore': before['namespace']['resourceVersion'],
                      'resourceVersionAfter': after['namespace']['resourceVersion'],
                      'contentSha256Before': sha_json(before['namespace']['content']),
                      'contentSha256After': sha_json(after['namespace']['content'])},
        'objects': [{'name': name, 'uid': old['uid'], 'resourceVersionBefore': old['resourceVersion'],
                     'resourceVersionAfter': after['objects'][name]['resourceVersion'],
                     'metadataSha256Before': sha_json(old['metadata']),
                     'metadataSha256After': sha_json(after['objects'][name]['metadata']),
                     'specSha256Before': sha_json(old['spec']),
                     'specSha256After': sha_json(after['objects'][name]['spec'])} for name, old in sorted(before['objects'].items())],
        'readback': [{'name': name, 'uid': old['uid'], 'resourceVersionBefore': old['resourceVersion'],
                      'resourceVersionAfter': after['resources'][name]['resourceVersion'],
                      'contentSha256Before': sha_json(old['content']),
                      'contentSha256After': sha_json(after['resources'][name]['content'])}
                     for name, old in sorted(before.get('resources', {}).items())],
    }


def assert_distinct_workspace_snapshots(first, second):
    expect(first['namespace']['uid'] != second['namespace']['uid'] and
           first['namespace']['content']['metadata']['name'] != second['namespace']['content']['metadata']['name'],
           'distinct workspaces share a Namespace name or UID')
    expect(set(first['objects']).isdisjoint(second['objects']), 'distinct workspaces share composed Object names')
    first_object_uids = {value['uid'] for value in first['objects'].values()}
    second_object_uids = {value['uid'] for value in second['objects'].values()}
    expect(first_object_uids.isdisjoint(second_object_uids), 'distinct workspaces share composed Object UIDs')
    first_resource_uids = {value['uid'] for value in first.get('resources', {}).values()}
    second_resource_uids = {value['uid'] for value in second.get('resources', {}).values()}
    expect(first_resource_uids.isdisjoint(second_resource_uids), 'distinct workspaces share rendered-resource UIDs')
    return {'namespaceUIDs': [first['namespace']['uid'], second['namespace']['uid']],
            'objectNames': [sorted(first['objects']), sorted(second['objects'])],
            'objectUIDs': [sorted(first_object_uids), sorted(second_object_uids)]}

def assert_noncanonical_name_refused(done, candidate_name):
    error = done.stderr
    expect(done.returncode != 0 and 'metadata.name' in error and 'workspaceID' in error and '-xr' in error,
           f'noncanonical duplicate workspaceID was not rejected by the naming rule: {error.strip()[:300]}')
    missing = kubectl(['get', f'developerworkspace/{candidate_name}'], check=False)
    expect(is_not_found(missing), f'rejected DeveloperWorkspace {candidate_name} absence was not confirmed by NotFound: {missing.stderr.strip()[:300]}')
    refs = composed_objects(candidate_name)
    expect(not refs, f'rejected DeveloperWorkspace {candidate_name} has composed Object references: {refs}')
    return {'name': candidate_name, 'exists': False, 'ready': False, 'objectRefs': refs}

def assert_canonical_create_already_exists(done, owner_name):
    error = done.stderr
    expect(done.returncode != 0 and '(AlreadyExists)' in error and 'already exists' in error and f'"{owner_name}"' in error,
           f'second canonical CREATE did not report AlreadyExists for {owner_name}: rc={done.returncode} {error.strip()[:300]}')
    return {'name': owner_name, 'reason': 'AlreadyExists', 'created': False}

def authority_identities():
    def binding(name, service_account, role):
        return {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding', 'metadata': {'name': name},
                'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': role},
                'subjects': [{'kind': 'ServiceAccount', 'name': service_account, 'namespace': PROOF_NS}]}
    return [
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': OPERATOR_SA, 'namespace': PROOF_NS}},
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': OBSERVER_SA, 'namespace': PROOF_NS}},
        binding(OPERATOR_BINDING, OPERATOR_SA, 'developer-workspace-operator'),
        binding(OBSERVER_BINDING, OBSERVER_SA, 'developer-workspace-observer'),
    ]

# Expected holders come from the pinned chart/RBAC-manager sources linked in README,
# Kubernetes' default cluster-admin binding, and this capability's shipped operator role.
AUTHORITY_RESOURCES = {
    'DeveloperWorkspace': ('workspace.openkubes.io', 'developerworkspaces'),
    'Object': ('kubernetes.crossplane.io', 'objects'),
    'ProviderConfig': ('kubernetes.crossplane.io', 'providerconfigs'),
    'EnvironmentConfig': ('apiextensions.crossplane.io', 'environmentconfigs'),
}
AUTHORITY_VERBS = ('create', 'update', 'patch', 'delete', 'deletecollection')
INDIRECT_AUTHORITY = {
    'impersonate-users': ('', 'users', 'impersonate', None),
    'impersonate-groups': ('', 'groups', 'impersonate', None),
    'impersonate-serviceaccounts': ('', 'serviceaccounts', 'impersonate', '*'),
    'bind-roles': ('rbac.authorization.k8s.io', 'roles', 'bind', '*'),
    'bind-clusterroles': ('rbac.authorization.k8s.io', 'clusterroles', 'bind', '*'),
    'escalate-roles': ('rbac.authorization.k8s.io', 'roles', 'escalate', '*'),
    'escalate-clusterroles': ('rbac.authorization.k8s.io', 'clusterroles', 'escalate', None),
    'create-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'create', None),
    'update-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'update', None),
    'patch-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'patch', None),
    'create-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'create', '*'),
    'update-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'update', '*'),
    'patch-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'patch', '*'),
    'create-serviceaccounts-crossplane-system': ('', 'serviceaccounts', 'create', 'crossplane-system'),
    'create-serviceaccount-tokens-crossplane-system': ('', 'serviceaccounts/token', 'create', 'crossplane-system'),
    'create-pods-crossplane-system': ('', 'pods', 'create', 'crossplane-system'),
    'get-secrets-crossplane-system': ('', 'secrets', 'get', 'crossplane-system'),
    'list-secrets-crossplane-system': ('', 'secrets', 'list', 'crossplane-system'),
}


def authority_subject(subject, namespace=None):
    kind = subject['kind']
    expect(kind in ('User', 'Group', 'ServiceAccount'), f'unknown RBAC subject kind {kind}')
    ns = subject.get('namespace') if kind == 'ServiceAccount' else None
    expect(kind != 'ServiceAccount' or bool(ns), f'ServiceAccount subject {subject["name"]} has no namespace')
    return (kind, subject['name'], ns or '')


def authority_subject_record(subject):
    kind, name, namespace = subject
    return {'kind': kind, 'name': name, **({'namespace': namespace} if namespace else {})}


def expected_authority_holders(default_group_present):
    # Do not derive this policy from the observed grants. Only the documented optional
    # default group binding controls presence; an altered binding still fails comparison.
    superuser = ('Group', 'system:masters', '')
    garbage_collector = ('ServiceAccount', 'generic-garbage-collector', 'kube-system')
    namespace_controller = ('ServiceAccount', 'namespace-controller', 'kube-system')
    controller = ('ServiceAccount', 'crossplane', 'crossplane-system')
    # The chart's rbac-manager SA manages RBAC, but has no mutation verbs on these kinds.
    provider = ('ServiceAccount', 'developer-workspace-provider-kubernetes', 'crossplane-system')
    operator = ('ServiceAccount', OPERATOR_SA, PROOF_NS)
    group = {('Group', 'crossplane:masters', '')} if default_group_present else set()
    result = {}
    for kind in AUTHORITY_RESOURCES:
        result[kind] = {}
        for verb in AUTHORITY_VERBS:
            holders = {superuser, controller, operator} | group
            if verb in ('update', 'patch', 'delete'):
                holders.add(garbage_collector)
            if verb in ('delete', 'deletecollection'):
                holders.add(namespace_controller)
            if kind in ('Object', 'ProviderConfig') and verb in ('create', 'update', 'patch'):
                holders.add(provider)  # provider system role deliberately omits delete
            if verb == 'deletecollection':
                holders.discard(operator)  # the shipped operator role intentionally omits it
            result[kind][verb] = holders
    return result


def expected_indirect_holders(default_group_present):
    master = ('Group', 'system:masters', '')
    group = {('Group', 'crossplane:masters', '')} if default_group_present else set()
    sa = lambda name, namespace='kube-system': ('ServiceAccount', name, namespace)
    controller = sa('crossplane', 'crossplane-system')
    rbac_manager = sa('rbac-manager', 'crossplane-system')
    provider = sa('developer-workspace-provider-kubernetes', 'crossplane-system')
    gc = sa('generic-garbage-collector')
    namespace_controller = sa('namespace-controller')
    kcm = ('User', 'system:kube-controller-manager', '')
    result = {name: {master} for name in INDIRECT_AUTHORITY}
    result['impersonate-serviceaccounts'].add(controller)
    result['bind-clusterroles'].add(rbac_manager)
    result['escalate-roles'].add(rbac_manager)
    result['escalate-clusterroles'].update({rbac_manager, sa('clusterrole-aggregation-controller')})
    result['create-clusterrolebindings'].update({rbac_manager, *group})
    for name in ('update-clusterrolebindings', 'patch-clusterrolebindings'):
        result[name].update({rbac_manager, gc, *group})
    result['create-rolebindings'].update(group)
    for name in ('update-rolebindings', 'patch-rolebindings'):
        result[name].update({gc, *group})
    result['create-serviceaccounts-crossplane-system'].update({kcm, sa('service-account-controller'), controller, provider})
    result['create-serviceaccount-tokens-crossplane-system'].add(kcm)
    result['create-pods-crossplane-system'].update(sa(name) for name in (
        'daemon-set-controller', 'job-controller', 'persistent-volume-binder',
        'replicaset-controller', 'replication-controller', 'statefulset-controller'))
    secret_readers = {kcm, gc, namespace_controller, controller, provider, sa('cilium-operator'), *group}
    result['get-secrets-crossplane-system'].update(secret_readers)
    result['list-secrets-crossplane-system'].update({*secret_readers, sa('resourcequota-controller')})
    return result


def authority_rule_matches(rule, group, resource, verb):
    matches = lambda value, entries: value in entries or '*' in entries
    resources = rule.get('resources', [])
    resource_match = matches(resource, resources)
    if '/' in resource:
        _, subresource = resource.split('/', 1)
        resource_match = resource_match or f'*/{subresource}' in resources
    return (matches(group, rule.get('apiGroups', [])) and
            resource_match and
            matches(verb, rule.get('verbs', [])) and
            # Top-level CREATE has no resource name at authorization time. Named rules still
            # count for updates, named subresource creates, and list with metadata.name selectors.
            not (verb == 'deletecollection' and rule.get('resourceNames')) and
            not (verb == 'create' and '/' not in resource and rule.get('resourceNames')))


def assert_authority_holder_sets(holders, expected):
    differences = []
    for kind in AUTHORITY_RESOURCES:
        for verb in AUTHORITY_VERBS:
            extra = sorted(holders[kind][verb] - expected[kind][verb])
            missing = sorted(expected[kind][verb] - holders[kind][verb])
            if extra or missing:
                differences.append(f'{kind}/{verb}: extra={list(map(authority_subject_record, extra))}, '
                                   f'missing={list(map(authority_subject_record, missing))}')
    expect(not differences, 'authority-who-can holder mismatch: ' + '; '.join(differences))


def assert_indirect_authority_holder_sets(holders, expected):
    differences = []
    for name in INDIRECT_AUTHORITY:
        extra = sorted(holders[name] - expected[name])
        missing = sorted(expected[name] - holders[name])
        if extra or missing:
            differences.append(f'{name}: extra={list(map(authority_subject_record, extra))}, '
                               f'missing={list(map(authority_subject_record, missing))}')
    expect(not differences, 'indirect authority holder mismatch: ' + '; '.join(differences))


def prove_authority_who_can():
    # Scope is checked against the installed CRDs, rather than inferred from a kind name.
    for kind, (group, resource) in AUTHORITY_RESOURCES.items():
        crd = get_json(['get', 'crd', f'{resource}.{group}'])
        expect(crd['spec']['scope'] == 'Cluster', f'authority-who-can {kind} must be cluster-scoped')
    cluster_roles = get_json(['get', 'clusterroles'])['items']
    cluster_bindings = get_json(['get', 'clusterrolebindings'])['items']
    roles = get_json(['get', 'roles', '--all-namespaces'])['items']
    bindings = get_json(['get', 'rolebindings', '--all-namespaces'])['items']
    cluster_index = {r['metadata']['name']: r for r in cluster_roles}
    role_index = {(r['metadata']['namespace'], r['metadata']['name']): r for r in roles}
    holders = {kind: {verb: set() for verb in AUTHORITY_VERBS} for kind in AUTHORITY_RESOURCES}
    indirect = {name: set() for name in INDIRECT_AUTHORITY}
    non_effective = []
    for binding in [*cluster_bindings, *bindings]:
        cluster_binding = binding['kind'] == 'ClusterRoleBinding'
        namespace = binding['metadata'].get('namespace')
        ref = binding['roleRef']
        expect(ref['apiGroup'] == 'rbac.authorization.k8s.io', 'unexpected RBAC roleRef API group')
        if cluster_binding:
            expect(ref['kind'] == 'ClusterRole', 'ClusterRoleBinding must reference a ClusterRole')
        if ref['kind'] == 'ClusterRole':
            role = cluster_index.get(ref['name'])
        else:
            expect(ref['kind'] == 'Role' and not cluster_binding, 'unexpected RBAC roleRef kind')
            role = role_index.get((namespace, ref['name']))
        # A dangling binding grants nothing, including when a role was removed.
        if role is None:
            continue
        subjects = {authority_subject(subject, namespace) for subject in binding.get('subjects', [])}
        for kind, (group, resource) in AUTHORITY_RESOURCES.items():
            for verb in AUTHORITY_VERBS:
                # The aggregation controller materializes rules. Never resolve selectors here.
                if not any(authority_rule_matches(rule, group, resource, verb) for rule in role.get('rules', [])):
                    continue
                if cluster_binding:
                    holders[kind][verb].update(subjects)
                else:
                    non_effective.append({'binding': {'name': binding['metadata']['name'], 'namespace': namespace},
                                          'kind': kind, 'verb': verb,
                                          'subjects': list(map(authority_subject_record, sorted(subjects))),
                                          'reason': 'RoleBinding cannot grant access to a cluster-scoped resource'})
        for name, (group, resource, verb, scope) in INDIRECT_AUTHORITY.items():
            if not any(authority_rule_matches(rule, group, resource, verb) for rule in role.get('rules', [])):
                continue
            if cluster_binding or scope == '*' or namespace == scope:
                indirect[name].update(subjects)
    default_group_present = any(b['metadata']['name'] == 'crossplane-admin' for b in cluster_bindings)
    assert_authority_holder_sets(holders, expected_authority_holders(default_group_present))
    assert_indirect_authority_holder_sets(indirect, expected_indirect_holders(default_group_present))
    return {'holders': {kind: {verb: list(map(authority_subject_record, sorted(subjects)))
                              for verb, subjects in verbs.items()} for kind, verbs in holders.items()},
            'indirectHolders': {name: list(map(authority_subject_record, sorted(subjects)))
                                for name, subjects in indirect.items()},
            'nonEffectiveRoleBindings': non_effective,
            'scope': 'Cluster', 'defaultCrossplaneGroupBindingPresent': default_group_present}


def assert_can_i(identity, verb, resource, allowed, name=None):
    target = f'{resource}/{name}' if name else resource
    done = kubectl(['auth', 'can-i', verb, target, f'--as={identity}'], check=False)
    answer = done.stdout.strip()
    expect(answer == ('yes' if allowed else 'no') and (done.returncode == 0) == allowed,
           f'auth can-i {verb} {target} for {identity} returned rc={done.returncode} {answer!r}, expected {allowed}')

def assert_server_dry_run(identity, action, resource, doc, allowed):
    verb = 'create' if action == 'create' else 'update'
    done = kubectl([action, '--dry-run=server', '-f', '-', f'--as={identity}'], input_text=yaml.safe_dump(doc), check=False)
    if allowed:
        expect(done.returncode == 0, f'{identity} could not {verb} {resource}: {done.stderr.strip()[:300]}')
    else:
        expected = rf'is forbidden:.*cannot {verb} resource "{re.escape(resource)}"'
        expect(done.returncode != 0 and re.search(expected, done.stderr, re.S | re.I),
               f'{identity} denial did not report Forbidden/{verb}/{resource}: rc={done.returncode} {done.stderr.strip()[:300]}')

def replace_document(doc):
    value = copy.deepcopy(doc); value.pop('status', None)
    for key in ('uid', 'creationTimestamp', 'generation', 'managedFields', 'deletionTimestamp', 'deletionGracePeriodSeconds'):
        value.get('metadata', {}).pop(key, None)
    return value

def prove_authority_boundary(owner_name, owner_doc, profile_doc):
    operator = f'system:serviceaccount:{PROOF_NS}:{OPERATOR_SA}'
    observer = f'system:serviceaccount:{PROOF_NS}:{OBSERVER_SA}'
    apply(authority_identities())

    full = ('get', 'list', 'watch', 'create', 'update', 'patch', 'delete')
    for resource in ('developerworkspaces.workspace.openkubes.io', 'objects.kubernetes.crossplane.io'):
        for verb in full:
            assert_can_i(operator, verb, resource, True)
            assert_can_i(observer, verb, resource, resource.startswith('developerworkspaces.') and verb in ('get', 'list', 'watch'))
        assert_can_i(operator, 'deletecollection', resource, False)
        assert_can_i(observer, 'deletecollection', resource, False)
    named = (('providerconfigs.kubernetes.crossplane.io', 'in-cluster'),
             ('environmentconfigs.apiextensions.crossplane.io', 'developer-workspace-profile'))
    for resource, name in named:
        assert_can_i(operator, 'create', resource, True)
        assert_can_i(observer, 'create', resource, False)
        for verb in ('list', 'watch'):
            assert_can_i(operator, verb, resource, False)
            assert_can_i(observer, verb, resource, False)
        assert_can_i(operator, 'deletecollection', resource, False)
        assert_can_i(observer, 'deletecollection', resource, False)
        for verb in ('get', 'update', 'patch', 'delete'):
            assert_can_i(operator, verb, resource, True, name)
            assert_can_i(operator, verb, resource, False, 'ok175-other-name')
            assert_can_i(observer, verb, resource, False, name)

    # A real read complements can-i for the observer's one positive permission.
    observed = kubectl(['get', f'developerworkspace/{owner_name}', f'--as={observer}', '-o', 'name'], check=False)
    expect(observed.returncode == 0 and observed.stdout.strip().endswith(f'/{owner_name}'), 'observer could not read the owner DeveloperWorkspace')

    live_owner = get_json(['get', f'developerworkspace/{owner_name}'])
    live_object = sorted(composed_object_items(owner_name), key=lambda item: item['metadata']['name'])[0]
    provider = get_json(['get', 'providerconfig/in-cluster'])
    live_profile = get_json(['get', 'environmentconfig/developer-workspace-profile'])

    create_owner = workspace_inputs(canonical_xr_name('ws-ok175-authority'), 'ws-ok175-authority', owner_doc['spec']['source']['revision'], 'persistent')
    create_object = replace_document(live_object)
    create_object['metadata']['name'] = 'ok175-authority-object-probe'
    for key in ('resourceVersion', 'ownerReferences', 'finalizers'):
        create_object['metadata'].pop(key, None)
    create_provider = replace_document(provider); create_provider['metadata'] = {'name': 'ok175-authority-provider-probe'}
    create_profile = replace_document(profile_doc); create_profile['metadata'] = {'name': 'ok175-authority-profile-probe'}
    documents = (
        ('developerworkspaces', create_owner, replace_document(live_owner)),
        ('objects', create_object, replace_document(live_object)),
        ('providerconfigs', create_provider, replace_document(provider)),
        ('environmentconfigs', create_profile, replace_document(live_profile)),
    )
    for resource, create_doc, replace_doc in documents:
        for identity, allowed in ((observer, False), (operator, True)):
            assert_server_dry_run(identity, 'create', resource, create_doc, allowed)
            assert_server_dry_run(identity, 'replace', resource, replace_doc, allowed)
    return {'operator': operator, 'observer': observer, 'resources': [resource for resource, _, _ in documents]}

def delete_and_confirm_gone(name, namespace, expected_count):
    # Counting first keeps the "none left" check from passing on a label that never matched.
    expect(len(composed_objects(name)) == expected_count, f'{name} has {len(composed_objects(name))} composed Objects, expected {expected_count}')
    volumes = [c['spec'].get('volumeName') for c in get_json(['get', 'pvc', '-n', namespace])['items']]
    expect(all(volumes), f'unbound PVC in {namespace}')
    kubectl(['delete', f'developerworkspace/{name}', '--wait=true', '--timeout=600s'], timeout=630)
    wait_until(f'namespace {namespace} removal', lambda: is_not_found(kubectl(['get', 'namespace', namespace], check=False)), timeout=600)
    # The XR is gone before its composed Objects finish deleting; wait for them, bounded.
    wait_until(f'composed Objects of {name} to be deleted', lambda: not composed_objects(name), timeout=300)
    for volume in volumes:
        wait_until(f'PersistentVolume {volume} removal', lambda volume=volume: is_not_found(kubectl(['get', 'pv', volume], check=False)), timeout=300)
    return len(volumes)

# ---- run ------------------------------------------------------------------------------------

def run(args):
    started = now(); run_id = secrets.token_hex(8); tgt = target(); impl = implementation(args.require_clean)
    runtime_image, fixture_image = image('OK175_RUNTIME_IMAGE'), image('OK175_FIXTURE_IMAGE')
    username = os.environ.get('OK175_REGISTRY_USERNAME', ''); pulls = bool(username)
    password = os.read(int(os.environ['OK175_REGISTRY_PASSWORD_FD']), 4096).decode().strip() if pulls else ''
    expect(not pulls or password, 'registry password descriptor is empty')
    registry = runtime_image.split('/', 1)[0]
    tls = spike.tls_material(); read_token, write_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    results = []
    def record(name, detail, **observed): results.append({'name': name, 'status': 'pass', 'detail': detail, **({'observed': observed} if observed else {})}); print(f'PASS {name}: {detail}', flush=True)

    expect(not get_json(['get', 'developerworkspaces'])['items'], 'DeveloperWorkspaces already exist on the target')
    kubectl(['create', 'namespace', PROOF_NS])
    if pulls: apply([pull_secret(PROOF_NS, registry, username, password)])
    apply(proof_services(fixture_image, tls, read_token, write_token, pulls))
    kubectl(['rollout', 'status', 'deployment/git-fixture', '-n', PROOF_NS, '--timeout=300s'], timeout=330)
    kubectl(['wait', '--for=condition=Ready', 'pod/control', '-n', PROOF_NS, '--timeout=300s'], timeout=330)
    source_pod = get_json(['get', 'pods', '-n', PROOF_NS, '-l', 'app=git-fixture'])['items'][0]['metadata']['name']
    known = exec_in(PROOF_NS, source_pod, ['cat', '/srv/git/KNOWN_COMMIT']).stdout.strip(); expect(bool(re.fullmatch(r'[0-9a-f]{40}', known)), 'source did not report a known commit')
    # Control for the checkout check: the source's default branch has moved past the declared revision.
    tip = exec_in(PROOF_NS, source_pod, ['git', '--git-dir=/srv/git/workspace-fixture.git', 'rev-parse', 'HEAD']).stdout.strip()
    expect(bool(re.fullmatch(r'[0-9a-f]{40}', tip)) and tip != known, 'source tip equals the declared revision; the checkout check could not fail')
    composition = installed_matches_local()

    # Admission: the XRD's CEL rules reject an inconsistent lifecycle and noncanonical identity;
    # the same documents made consistent and canonical pass.
    cel_name = canonical_xr_name('ws-ok175-cel')
    bad = workspace_inputs(cel_name, 'ws-ok175-cel', known, 'persistent'); bad['spec']['storage']['mode'] = 'ephemeral'
    rejected = kubectl(['apply', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(bad), check=False)
    expect(rejected.returncode != 0 and 'persistent lifecycle requires persistent storage' in rejected.stderr, 'XRD admitted a persistent lifecycle with ephemeral storage')
    canonical = workspace_inputs(cel_name, 'ws-ok175-cel', known, 'persistent')
    kubectl(['create', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(canonical))
    wrong_name = copy.deepcopy(canonical); wrong_name['metadata']['name'] = 'ok175-cel-probe'
    rejected_name = kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(wrong_name), check=False)
    try:
        noncanonical = assert_noncanonical_name_refused(rejected_name, wrong_name['metadata']['name'])
    finally:
        # Cleanup only if the guard regressed and the supposedly rejected document persisted.
        if rejected_name.returncode == 0:
            kubectl(['delete', f'developerworkspace/{wrong_name["metadata"]["name"]}', '--ignore-not-found', '--wait=true', '--timeout=300s'], timeout=330, check=False)
    record('admission-rules', 'the API server rejects inconsistent lifecycle and admits the consistent document')
    record('canonical-name-rule', 'the API server rejects a distinct noncanonical metadata.name and admits metadata.name = spec.workspaceID + "-xr"',
           rejected=noncanonical, admitted=canonical['metadata']['name'])
    # Without the profile EnvironmentConfig a workspace must compose nothing and must not be Ready.
    probe = workspace_inputs(*NO_PROFILE, known, 'persistent'); apply([probe])
    def no_profile_settled():
        conditions = {c['type']: c for c in get_json(['get', f'developerworkspace/{NO_PROFILE[0]}']).get('status', {}).get('conditions', [])}
        return conditions.get('Synced', {}).get('status') == 'False' and 'developer-workspace-profile not found' in conditions['Synced'].get('message', '')
    wait_until('the no-profile workspace to report the missing profile', no_profile_settled, timeout=180, interval=3)
    conditions = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{NO_PROFILE[0]}'])['status']['conditions']}
    no_profile_namespace = kubectl(['get', 'namespace', 'dw-ok175-no-profile'], check=False)
    expect(conditions.get('Ready') != 'True' and not composed_objects(NO_PROFILE[0]) and is_not_found(no_profile_namespace),
           f'no-profile workspace composed, became Ready, or Namespace absence was not confirmed by NotFound: {conditions}; {no_profile_namespace.stderr.strip()[:200]}')
    kubectl(['delete', f'developerworkspace/{NO_PROFILE[0]}', '--wait=true', '--timeout=300s'], timeout=330)
    record('no-profile-fails-closed', 'without the profile EnvironmentConfig the workspace reports it missing, composes nothing and is not Ready', ready=conditions.get('Ready'))

    profile = yaml.safe_load((LIVE / 'profile/namespace-profile-live.yaml').read_text())
    profile['spec']['runtimeProfiles']['opencode']['image'] = runtime_image
    profile_config = render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')
    apply([profile_config])

    def bring_up(name, workspace_id, mode, resources=None):
        expect(name == canonical_xr_name(workspace_id), f'{name} is not the canonical XR name for {workspace_id}')
        doc = workspace_inputs(name, workspace_id, known, mode); namespace = profile['spec']['namespacePrefix'] + workspace_id.removeprefix('ws-')
        if resources:
            doc['spec']['resources'].update(resources)
        # Dedicated: the reconciler would adopt an existing Namespace, so require that none exists.
        missing_namespace = kubectl(['get', 'namespace', namespace], check=False)
        expect(is_not_found(missing_namespace), f'namespace {namespace} absence was not confirmed by NotFound: {missing_namespace.stderr.strip()[:300]}')
        apply([doc])
        wait_until(f'namespace {namespace}', lambda: kubectl(['get', 'namespace', namespace], check=False).returncode == 0, timeout=300)
        # Per-run values the contract only references: the source credential, CA and pull Secret.
        support = [{'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'workspace-git-auth', 'namespace': namespace}, 'type': 'Opaque', 'stringData': {'token': read_token}},
                   {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'git-fixture-ca', 'namespace': namespace}, 'data': {'ca.crt': tls['ca']}}]
        if pulls: support.append(pull_secret(namespace, registry, username, password))
        apply(support)
        wait_ready(name)
        revision = revision_matches(name, composition)
        xr, created = get_json(['get', f'developerworkspace/{name}']), get_json(['get', 'namespace', namespace])
        expect(created['metadata']['creationTimestamp'] >= xr['metadata']['creationTimestamp'], f'namespace {namespace} predates its DeveloperWorkspace')
        return doc, namespace, revision

    try:
        # Dedicated Namespace: a workspace whose Namespace already exists must not adopt it.
        squat = 'dw-ok175-squat'
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': squat}},
               {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'owner-data', 'namespace': squat}, 'data': {'k': 'v'}}])
        apply([workspace_inputs(SQUAT[0], SQUAT[1], known, 'persistent')])
        def refused():
            for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items']:
                if o['metadata'].get('labels', {}).get('crossplane.io/composite') == SQUAT[0] and o['spec']['forProvider']['manifest']['kind'] == 'Namespace':
                    return any('only Namespaces it created' in c.get('message', '') for c in o.get('status', {}).get('conditions', []))
            return False
        wait_until('the provider to be refused the existing Namespace', refused, timeout=300, interval=3)
        time.sleep(20)  # let every other composed Object attempt its write too
        existing = get_json(['get', 'namespace', squat])
        ready = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{SQUAT[0]}']).get('status', {}).get('conditions', [])}.get('Ready')
        written = [f"{k}/{i['metadata']['name']}" for k in ('serviceaccounts', 'resourcequotas', 'limitranges', 'networkpolicies', 'persistentvolumeclaims', 'deployments') for i in get_json(['get', k, '-n', squat])['items'] if not spike.controller_default(i)]
        expect('workspace.openkubes.io/id' not in existing['metadata'].get('labels', {}) and not written and ready != 'True'
               and kubectl(['get', 'configmap/owner-data', '-n', squat], check=False).returncode == 0, f'existing Namespace was adopted or written: written={written} ready={ready}')
        kubectl(['delete', 'namespace', squat, '--wait=true'], timeout=600)  # the owner removes it, then the XR can go
        kubectl(['delete', f'developerworkspace/{SQUAT[0]}', '--wait=true', '--timeout=300s'], timeout=330)
        wait_until(f'composed Objects of {SQUAT[0]} to be deleted', lambda: not composed_objects(SQUAT[0]), timeout=300)
        record('dedicated-namespace-enforced', 'a workspace whose Namespace already existed was refused it: no label, no workspace object written, owner data intact, XR not Ready; the persistent run below is the control', ready=ready)

        doc, ns, revision = bring_up(*PERSISTENT, 'persistent')
        xr = get_json(['get', f'developerworkspace/{PERSISTENT[0]}'])
        expect(xr.get('status', {}).get('namespace') == ns and xr['status'].get('lifecyclePhase') == 'running', f"XR status {xr.get('status', {}).get('namespace')}/{xr.get('status', {}).get('lifecyclePhase')}")
        count = readback(ns, expected_objects(doc, profile, pulls))
        record('reconcile-readback', f'XR Ready; {count} reconciled objects equal render() for the persistent profile; the XR runs the local Composition', namespace=ns, lifecyclePhase='running', compositionRevision=revision)

        # workspaceID is the durable identity: even a server-side dry-run update cannot change it.
        live_owner = get_json(['get', f'developerworkspace/{PERSISTENT[0]}'])
        changed = replace_document(live_owner); changed['spec']['workspaceID'] = 'ws-ok175-mutated'
        immutable = kubectl(['replace', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(changed), check=False)
        expect(immutable.returncode != 0 and 'workspaceID' in immutable.stderr and 'immutable' in immutable.stderr.lower(),
               f'workspaceID mutation was not rejected: {immutable.stderr.strip()[:300]}')
        kubectl(['replace', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(replace_document(live_owner)))
        record('workspace-id-immutable', 'the API server rejects a workspaceID update and admits an otherwise identical replacement')

        authority = prove_authority_boundary(PERSISTENT[0], doc, profile_config)
        record('authority-boundary-rbac', 'observer is read-only for DeveloperWorkspace and denied every mutation; operator passes documented can-i checks and real server dry-run create/update checks for all four resource types', **authority)

        who_can = prove_authority_who_can()
        record('authority-who-can', 'all cluster RBAC holders equal the documented expected subject sets for every steering kind and mutation verb',
               holders=who_can['holders'], nonEffectiveRoleBindings=who_can['nonEffectiveRoleBindings'], scope=who_can['scope'],
               defaultCrossplaneGroupBindingPresent=who_can['defaultCrossplaneGroupBindingPresent'])
        record('authority-indirect-who-can', 'all RBAC holders of impersonation, bind, escalate, binding mutation, service-account token, Pod creation and Secret read paths equal the source-derived expected sets',
               holders=who_can['indirectHolders'], defaultCrossplaneGroupBindingPresent=who_can['defaultCrossplaneGroupBindingPresent'])

        rendered = expected_objects(doc, profile, pulls)
        before = owner_snapshot(PERSISTENT[0], ns, rendered)
        denied_collision = kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(doc), check=False)
        refused = assert_canonical_create_already_exists(denied_collision, PERSISTENT[0])
        readback(ns, rendered); after_create = owner_snapshot(PERSISTENT[0], ns, rendered)
        identities = assert_owner_unchanged(before, after_create)
        record('workspace-id-duplicate-create-refused', 'a second CREATE of the canonical owner name returns AlreadyExists; owner UID/spec, Namespace, composed Object resourceVersions/specs, and rendered-resource readback remain byte-equivalent', candidate=refused, owner=identities)
        # A reconciler, not a one-shot apply: remove the default-deny policy and require it back as rendered.
        # A new UID is the control that the policy was really deleted, however fast it returns.
        uid = lambda: (lambda d: json.loads(d.stdout)['metadata']['uid'] if d.returncode == 0 else None)(kubectl(['get', 'networkpolicy/default-deny', '-n', ns, '-o', 'json'], check=False))
        before = uid(); expect(before is not None, 'default-deny missing before drift')
        kubectl(['delete', 'networkpolicy/default-deny', '-n', ns, '--wait=true']); removed = time.monotonic()
        wait_until('default-deny to be restored', lambda: uid() not in (None, before), timeout=300, interval=2)
        readback(ns, expected_objects(doc, profile, pulls))
        patched = json.loads(kubectl(['patch', 'resourcequota/workspace-bounds', '-n', ns, '--type=merge', '-o', 'json', '-p', json.dumps({'spec': {'hard': {'limits.cpu': '64'}}})]).stdout)
        expect(patched['spec']['hard']['limits.cpu'] == '64', 'control: quota patch did not land')  # the response is the patched object itself
        quota = lambda: get_json(['get', 'resourcequota/workspace-bounds', '-n', ns])
        wait_until('quota limits.cpu to be restored', lambda: (lambda q: q['metadata']['resourceVersion'] != patched['metadata']['resourceVersion'] and q['spec']['hard']['limits.cpu'] == doc['spec']['resources']['cpu'])(quota()), timeout=300, interval=2)
        readback(ns, expected_objects(doc, profile, pulls))
        record('drift-restored', 'a deleted default-deny NetworkPolicy was recreated (new UID) and a patched quota value was reverted, both as rendered', seconds=round(time.monotonic() - removed))
        pod = workspace_pod(ns)

        head = exec_in(ns, pod, ['git', '-C', '/workspace', 'rev-parse', 'HEAD'], 'runtime'); expect(head.returncode == 0 and head.stdout.strip() == known, 'checkout is not the declared revision')
        record('source-checkout', 'workspace HEAD equals the declared revision, not the newer default-branch tip', commit=known, sourceTip=tip)

        token = exec_in(ns, pod, ['sh', '-c', 'test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token'], 'runtime'); expect(token.returncode == 0, 'a ServiceAccount token is mounted')
        sa = f'system:serviceaccount:{ns}:workspace'
        can = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as={sa}']).stdout
        # Baseline: an identity with no bindings at all, in the same namespace. Whatever the cluster
        # grants every authenticated identity appears in both; anything else is workspace authority.
        baseline = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as=system:serviceaccount:{ns}:ok175-unbound']).stdout
        rows = lambda text: {re.sub(r'\s+', ' ', line.strip()) for line in text.splitlines() if line.strip()}
        expect(rows(can) == rows(baseline), f'workspace ServiceAccount authority differs from an unbound identity: {sorted(rows(can) ^ rows(baseline))}')
        # Beyond equality, the rows themselves must be discovery only: OK-174's allowlist plus the one
        # read Kubernetes >= 1.33 grants every authenticated identity (public ClusterTrustBundles).
        strict = lambda text: spike.rbac_list_denied('\n'.join(l for l in text.splitlines() if not re.match(r'\s*clustertrustbundles\.certificates\.k8s\.io\s+\[\]\s+\[\]\s+\[get list watch\]\s*$', l)))
        expect(strict(can), 'workspace ServiceAccount holds more than discovery authority')
        provider_sa = 'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'
        provider = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as={provider_sa}']).stdout
        expect(rows(provider) != rows(baseline) and not strict(provider), 'control: the comparison cannot tell a privileged identity from the baseline')
        bindings = get_json(['get', 'rolebindings', '-n', ns])['items']; expect(not bindings, f'RoleBindings exist in {ns}')
        record('kubernetes-authority-denied', 'no token mounted; can-i --list equals an unbound identity and is discovery-only; no RoleBindings; the provider identity fails both checks', baselineRows=len(rows(baseline)), providerRows=len(rows(provider)))

        api = exec_in(ns, pod, ['curl', '-ksS', '-o', '/dev/null', '--connect-timeout', '3', '--max-time', '3', KUBE_API], 'runtime')
        expect(spike.denied_egress(api.returncode, api.stderr), f'runtime reached the Kubernetes API (curl rc={api.returncode})')
        reach = exec_in(PROOF_NS, 'control', ['curl', '-ksS', '-o', '/dev/null', '-w', '%{http_code}', '--connect-timeout', '3', '--max-time', '5', KUBE_API])
        expect(reach.returncode == 0 and reach.stdout.strip() in ('401', '403'), 'control: Kubernetes API transport not reachable from the proof namespace')
        record('kubernetes-api-unreachable', 'runtime API connection refused or timed out; control reaches API transport', runtimeCurlExit=api.returncode, controlHttp=reach.stdout.strip())

        env = get_json(['get', 'deployment/workspace', '-n', ns])['spec']['template']['spec']
        expect(not spike.runtime_has_credential({'spec': {'template': {'spec': env}}}), 'runtime container holds the source credential')
        config = exec_in(ns, pod, ['git', '-C', '/workspace', 'config', '--list', '--show-origin'], 'runtime')
        expect(config.returncode == 0 and not re.search(r'extraheader|credential|askpass|token', config.stdout, re.I), 'workspace git config carries a credential setting')
        runtime_env = exec_in(ns, pod, ['sh', '-c', 'env | cut -d= -f1'], 'runtime').stdout.split()
        expect(not [v for v in runtime_env if re.search(r'TOKEN|PASSWORD|SECRET|CREDENTIAL', v)], f'runtime environment names a credential: {runtime_env}')
        # TLS verification is off for this probe only, so the result is the source's answer, not a CA failure.
        push = exec_in(ns, pod, ['sh', '-c', f'GIT_TERMINAL_PROMPT=0 git -c http.sslVerify=false -C /workspace push {GIT_URL} {known}:refs/heads/main {known}:refs/heads/agent-probe'], 'runtime')
        expect(push.returncode != 0 and re.search(r'could not read Username|Authentication failed|401', push.stderr) and 'SSL' not in push.stderr, f'runtime push was not refused for lack of a credential: {push.stderr.strip()[:200]}')
        record('runtime-push-denied', 'the runtime holds no source credential (git config, environment) and the source refuses its push to main and a new branch for lack of one', exit=push.returncode)

        auth = lambda var: f'-c http.extraHeader="Authorization: Bearer ${var}"'
        heads_of = lambda text: {line.split()[1]: line.split()[0] for line in text.splitlines() if line.strip()}
        tip_heads = heads_of(exec_in(PROOF_NS, 'control', ['sh', '-c', f'git {auth("GIT_READ_TOKEN")} ls-remote {GIT_URL}']).stdout)
        # Command-scoped -c only: `git clone -c` would persist the header into the clone and send it on every push.
        tmp = f'rm -rf /tmp/r && git {auth("GIT_READ_TOKEN")} clone -q --bare {GIT_URL} /tmp/r && cd /tmp/r && ! git config --get-all http.extraHeader'
        denied = exec_in(PROOF_NS, 'control', ['sh', '-c', f'{tmp} && git {auth("GIT_READ_TOKEN")} push {GIT_URL} {known}:refs/heads/main {known}:refs/heads/agent-probe'])
        expect(denied.returncode != 0 and '403' in denied.stderr, f'workspace credential push was not refused with 403 (rc={denied.returncode})')
        allowed = exec_in(PROOF_NS, 'control', ['sh', '-c', f'{tmp} && git {auth("GIT_WRITE_TOKEN")} push {GIT_URL} {known}:refs/heads/control-probe'])
        expect(allowed.returncode == 0, f'control: write-credential push failed: {allowed.stderr.strip()[:200]}')
        refs = exec_in(PROOF_NS, 'control', ['sh', '-c', f'git {auth("GIT_READ_TOKEN")} ls-remote {GIT_URL}']).stdout
        heads = heads_of(refs)
        expect('refs/heads/agent-probe' not in heads and heads.get('refs/heads/control-probe') == known, f'unexpected source refs {sorted(heads)}')
        expect({k: v for k, v in heads.items() if k.startswith('refs/heads/') and k != 'refs/heads/control-probe'} == {k: v for k, v in tip_heads.items() if k.startswith('refs/heads/')}, 'a branch moved')
        record('workspace-credential-push-denied', 'source refuses push with the workspace credential (403); write-credential control push succeeds; no denied ref exists', refs=sorted(heads))

        stored = [base64.b64decode(v).decode(errors='replace') for s in get_json(['get', 'secrets', '-n', ns])['items'] for v in (s.get('data') or {}).values()]
        expect(write_token not in stored and not any(write_token in v for v in stored), 'the write credential is present in the workspace namespace')
        record('write-credential-absent', 'no Secret in the workspace namespace carries the write credential', secrets=len(stored))

        volumes = delete_and_confirm_gone(PERSISTENT[0], ns, count)
        expect(volumes == 1, f'persistent workspace had {volumes} PVCs')
        record('persistent-cleanup', f'deleting the XR removed its Namespace, all {count} composed Objects and the PersistentVolume')

        # These IDs collided under the former 40-bit Object-name hash. Reduced requests keep
        # this a concurrent Ready proof on the disposable single-worker profile.
        workspaces = []
        for identity in DISTINCT:
            edoc, ens, _ = bring_up(*identity, 'ephemeral', resources={'cpu': '100m', 'memory': '256Mi'})
            expected = expected_objects(edoc, profile, pulls)
            ecount = readback(ens, expected)
            volumes = {v['name']: v for v in get_json(['get', 'deployment/workspace', '-n', ens])['spec']['template']['spec']['volumes']}
            expect('emptyDir' in volumes['workspace'] and not get_json(['get', 'pvc', '-n', ens])['items'], f'{identity[0]} is not emptyDir-backed')
            workspaces.append({'name': identity[0], 'namespace': ens, 'doc': edoc, 'expected': expected,
                               'count': ecount, 'snapshot': owner_snapshot(identity[0], ens, expected)})
        for item in workspaces:
            ready = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{item["name"]}'])['status']['conditions']}
            expect(ready.get('Ready') == 'True', f'{item["name"]} was not Ready while both distinct workspaces existed: {ready}')
        disjoint = assert_distinct_workspace_snapshots(workspaces[0]['snapshot'], workspaces[1]['snapshot'])
        record('ephemeral-reconcile', 'both former-hash-collision workspaces are concurrently Ready; each rendered readback is emptyDir-backed with no PVC',
               workspaces=[{'name': item['name'], 'namespace': item['namespace'], 'objects': item['count']} for item in workspaces], resources={'cpu': '100m', 'memory': '256Mi'})

        second = workspaces[1]
        second_volumes = delete_and_confirm_gone(second['name'], second['namespace'], second['count'])
        expect(second_volumes == 0, f'{second["name"]} unexpectedly had PersistentVolumes')
        first = workspaces[0]
        readback(first['namespace'], first['expected'])
        first_after = owner_snapshot(first['name'], first['namespace'], first['expected'])
        first_unchanged = assert_owner_unchanged(first['snapshot'], first_after, strict_object_rv=False, strict_resource_rv=False)
        record('distinct-workspace-isolation', 'ws-c69924 and ws-cd9634 are concurrently Ready with disjoint Namespaces/Object identities; deleting ws-cd9634 leaves ws-c69924 UIDs, desired Object specs and rendered-resource readback unchanged',
               deleted=second['name'], survivor=first['name'], disjoint=disjoint, survivorBeforeAndAfter=first_unchanged)
        first_volumes = delete_and_confirm_gone(first['name'], first['namespace'], first['count'])
        expect(first_volumes == 0, f'{first["name"]} unexpectedly had PersistentVolumes')
        record('ephemeral-cleanup', f'deleting the remaining XR removed its Namespace and all {first["count"]} composed Objects')
    finally:
        kubectl(['delete', 'namespace', 'dw-ok175-squat', '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        for binding in (OPERATOR_BINDING, OBSERVER_BINDING):
            kubectl(['delete', 'clusterrolebinding', binding, '--ignore-not-found', '--wait=true'], check=False)
        for name, _ in (*DISTINCT, PERSISTENT, SQUAT, NO_PROFILE):
            kubectl(['delete', f'developerworkspace/{name}', '--ignore-not-found', '--wait=true', '--timeout=600s'], timeout=630, check=False)
        kubectl(['delete', 'namespace', PROOF_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--ignore-not-found'], check=False)
        def require_not_found(args, description):
            missing = kubectl(['get', *args], check=False)
            expect(is_not_found(missing),
                   f'cleanup did not confirm {description} absent: rc={missing.returncode} {missing.stderr.strip()[:300]}')
        require_not_found(['namespace', 'dw-ok175-squat'], 'squat Namespace')
        require_not_found(['namespace', PROOF_NS], 'proof services Namespace and its generated credentials')
        require_not_found(['environmentconfig', 'developer-workspace-profile'], 'profile EnvironmentConfig')
        for binding in (OPERATOR_BINDING, OBSERVER_BINDING):
            require_not_found(['clusterrolebinding', binding], f'ClusterRoleBinding/{binding}')
        cleanup_xrs = (*(name for name, _ in DISTINCT), PERSISTENT[0], SQUAT[0], NO_PROFILE[0])
        for name in cleanup_xrs:
            require_not_found(['developerworkspace', name], f'DeveloperWorkspace/{name}')
            expect(not composed_objects(name), f'cleanup left composed Objects for {name}')
        record('harness-cleanup', 'proof services, generated credentials, profile, temporary authority bindings, XRs and composed Objects are absent')

    expect([r['name'] for r in results] == list(RESULTS), f'results out of order: {[r["name"] for r in results]}')
    evidence = {'apiVersion': 'workspace.openkubes.io/v1', 'kind': 'ReconcilerLiveEvidence', 'runID': run_id, 'startedAt': started, 'finishedAt': now(),
                'target': tgt, 'implementation': impl, 'images': {'runtime': runtime_image.split('@', 1)[1], 'fixture': fixture_image.split('@', 1)[1]},
                'crossplane': {'chart': CROSSPLANE_CHART[2], 'functions': 'tests/functions.yaml', 'provider': 'install/provider-kubernetes.yaml'},
                'knownCommit': known, 'sourceTip': tip, 'results': results}
    EVIDENCE.mkdir(exist_ok=True); out = EVIDENCE / f'live-{tgt["context"].split("@")[-1]}-{run_id}.json'
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n'); print(f'{len(results)}/{len(RESULTS)} checks passed; evidence {out.relative_to(REPO)}')

RESULTS = ('admission-rules', 'canonical-name-rule', 'no-profile-fails-closed', 'dedicated-namespace-enforced', 'reconcile-readback', 'workspace-id-immutable', 'authority-boundary-rbac', 'authority-who-can', 'authority-indirect-who-can',
           'workspace-id-duplicate-create-refused', 'drift-restored', 'source-checkout', 'kubernetes-authority-denied', 'kubernetes-api-unreachable', 'runtime-push-denied',
           'workspace-credential-push-denied', 'write-credential-absent', 'persistent-cleanup', 'ephemeral-reconcile', 'distinct-workspace-isolation', 'ephemeral-cleanup', 'harness-cleanup')

def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('install').set_defaults(fn=install); sub.add_parser('uninstall').set_defaults(fn=uninstall)
    r = sub.add_parser('run'); r.add_argument('--require-clean', action='store_true'); r.set_defaults(fn=run)
    args = parser.parse_args()
    try: args.fn(args)
    except ProofError as error: print(f'FAIL {error}', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
