#!/usr/bin/env python3
"""Live proof of the DeveloperWorkspace reconciler path (OK-175).

The OK-174 harness applied render() output itself. Here a DeveloperWorkspace XR is applied and
Crossplane, function-go-templating and provider-kubernetes reconcile it. The proof requires:
  - the reconciled Namespace objects equal render() for the same document and profile;
  - the checkout is the declared revision and the XR is Ready only once the workspace runs;
  - no ambient Kubernetes authority (no token, discovery-only RBAC, API unreachable);
  - no push or merge authority: the runtime has no source credential, the workspace credential
    is refused for push by the source, and a write-credential control push succeeds;
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
PERSISTENT, EPHEMERAL = ('ok175-live-proof', 'ws-ok175-proof'), ('ok175-ephemeral-proof', 'ws-ok175-ephemeral')
SQUAT = ('ok175-squat-proof', 'ws-ok175-squat')
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
def sha(data): return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
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
    role = next(d for d in yaml.safe_load_all((CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml').read_text()) if d['kind'] == 'ClusterRole')
    expect(get_json(['get', 'clusterrole', role['metadata']['name']])['rules'] == role['rules'], 'installed ClusterRole differs from rbac/')
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
    apply_file(CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml'); apply_file(CAPABILITY / 'install/namespace-guard.yaml'); apply_file(CAPABILITY / 'install/providerconfig.yaml')
    apply_file(CAPABILITY / 'xrd.yaml')
    kubectl(['wait', '--for=condition=Established', 'compositeresourcedefinition/developerworkspaces.workspace.openkubes.io', '--timeout=300s'], timeout=330)
    apply_file(CAPABILITY / 'composition.yaml')
    print('installed Crossplane', version, 'with the DeveloperWorkspace capability')

def uninstall(_args):
    target()
    listed = kubectl(['get', 'developerworkspaces', '-o', 'json'], check=False)
    expect(listed.returncode != 0 and 'the server doesn' in listed.stderr or listed.returncode == 0 and not json.loads(listed.stdout)['items'], 'DeveloperWorkspaces still exist; delete them first')
    for path in ('composition.yaml', 'xrd.yaml', 'install/providerconfig.yaml', 'install/namespace-guard.yaml', 'rbac/provider-kubernetes-clusterrole.yaml', 'install/provider-kubernetes.yaml', 'tests/functions.yaml'):
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

def composed_objects(name): return [o['metadata']['name'] for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items'] if o['metadata'].get('labels', {}).get('crossplane.io/composite') == name]

def delete_and_confirm_gone(name, namespace, expected_count):
    # Counting first keeps the "none left" check from passing on a label that never matched.
    expect(len(composed_objects(name)) == expected_count, f'{name} has {len(composed_objects(name))} composed Objects, expected {expected_count}')
    volumes = [c['spec'].get('volumeName') for c in get_json(['get', 'pvc', '-n', namespace])['items']]
    expect(all(volumes), f'unbound PVC in {namespace}')
    kubectl(['delete', f'developerworkspace/{name}', '--wait=true', '--timeout=600s'], timeout=630)
    wait_until(f'namespace {namespace} removal', lambda: kubectl(['get', 'namespace', namespace], check=False).returncode != 0, timeout=600)
    # The XR is gone before its composed Objects finish deleting; wait for them, bounded.
    wait_until(f'composed Objects of {name} to be deleted', lambda: not composed_objects(name), timeout=300)
    for volume in volumes: wait_until(f'PersistentVolume {volume} removal', lambda: kubectl(['get', 'pv', volume], check=False).returncode != 0, timeout=300)
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

    # Admission: the XRD's CEL rules reject an inconsistent lifecycle; the same document made consistent passes.
    bad = workspace_inputs('ok175-cel-probe', 'ws-ok175-cel', known, 'persistent'); bad['spec']['storage']['mode'] = 'ephemeral'
    rejected = kubectl(['apply', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(bad), check=False)
    expect(rejected.returncode != 0 and 'persistent lifecycle requires persistent storage' in rejected.stderr, 'XRD admitted a persistent lifecycle with ephemeral storage')
    kubectl(['apply', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(workspace_inputs('ok175-cel-probe', 'ws-ok175-cel', known, 'persistent')))
    record('admission-rules', 'the API server rejects a persistent lifecycle with ephemeral storage and admits the consistent document')
    # Without the profile EnvironmentConfig a workspace must compose nothing and must not be Ready.
    probe = workspace_inputs('ok175-no-profile', 'ws-ok175-no-profile', known, 'persistent'); apply([probe])
    def no_profile_settled():
        conditions = {c['type']: c for c in get_json(['get', 'developerworkspace/ok175-no-profile']).get('status', {}).get('conditions', [])}
        return conditions.get('Synced', {}).get('status') == 'False' and 'developer-workspace-profile not found' in conditions['Synced'].get('message', '')
    wait_until('the no-profile workspace to report the missing profile', no_profile_settled, timeout=180, interval=3)
    conditions = {c['type']: c['status'] for c in get_json(['get', 'developerworkspace/ok175-no-profile'])['status']['conditions']}
    expect(conditions.get('Ready') != 'True' and not composed_objects('ok175-no-profile') and kubectl(['get', 'namespace', 'dw-ok175-no-profile'], check=False).returncode != 0, f'no-profile workspace composed or became Ready: {conditions}')
    kubectl(['delete', 'developerworkspace/ok175-no-profile', '--wait=true', '--timeout=300s'], timeout=330)
    record('no-profile-fails-closed', 'without the profile EnvironmentConfig the workspace reports it missing, composes nothing and is not Ready', ready=conditions.get('Ready'))

    profile = yaml.safe_load((LIVE / 'profile/namespace-profile-live.yaml').read_text())
    profile['spec']['runtimeProfiles']['opencode']['image'] = runtime_image
    apply([render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')])

    def bring_up(name, workspace_id, mode):
        doc = workspace_inputs(name, workspace_id, known, mode); namespace = profile['spec']['namespacePrefix'] + workspace_id.removeprefix('ws-')
        # Dedicated: the reconciler would adopt an existing Namespace, so require that none exists.
        expect(kubectl(['get', 'namespace', namespace], check=False).returncode != 0, f'namespace {namespace} already exists')
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

        # One workspace at a time: a single small worker cannot schedule two.
        edoc, ens, _ = bring_up(*EPHEMERAL, 'ephemeral')
        ecount = readback(ens, expected_objects(edoc, profile, pulls))
        volumes = {v['name']: v for v in get_json(['get', 'deployment/workspace', '-n', ens])['spec']['template']['spec']['volumes']}
        expect('emptyDir' in volumes['workspace'] and not get_json(['get', 'pvc', '-n', ens])['items'], 'ephemeral workspace is not emptyDir-backed')
        record('ephemeral-reconcile', f'{ecount} reconciled objects equal render(); workspace volume is emptyDir, no PVC', namespace=ens)
        delete_and_confirm_gone(EPHEMERAL[0], ens, ecount)
        record('ephemeral-cleanup', f'deleting the XR removed its Namespace and all {ecount} composed Objects')
    finally:
        kubectl(['delete', 'namespace', 'dw-ok175-squat', '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        for name, _ in (EPHEMERAL, PERSISTENT, SQUAT, ('ok175-no-profile', '')):
            kubectl(['delete', f'developerworkspace/{name}', '--ignore-not-found', '--wait=true', '--timeout=600s'], timeout=630, check=False)
        kubectl(['delete', 'namespace', PROOF_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--ignore-not-found'], check=False)

    expect([r['name'] for r in results] == list(RESULTS), f'results out of order: {[r["name"] for r in results]}')
    evidence = {'apiVersion': 'workspace.openkubes.io/v1', 'kind': 'ReconcilerLiveEvidence', 'runID': run_id, 'startedAt': started, 'finishedAt': now(),
                'target': tgt, 'implementation': impl, 'images': {'runtime': runtime_image.split('@', 1)[1], 'fixture': fixture_image.split('@', 1)[1]},
                'crossplane': {'chart': CROSSPLANE_CHART[2], 'functions': 'tests/functions.yaml', 'provider': 'install/provider-kubernetes.yaml'},
                'knownCommit': known, 'sourceTip': tip, 'results': results}
    EVIDENCE.mkdir(exist_ok=True); out = EVIDENCE / f'live-{tgt["context"].split("@")[-1]}-{run_id}.json'
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n'); print(f'{len(results)}/{len(RESULTS)} checks passed; evidence {out.relative_to(REPO)}')

RESULTS = ('admission-rules', 'no-profile-fails-closed', 'dedicated-namespace-enforced', 'reconcile-readback', 'drift-restored', 'source-checkout', 'kubernetes-authority-denied', 'kubernetes-api-unreachable', 'runtime-push-denied',
           'workspace-credential-push-denied', 'write-credential-absent', 'persistent-cleanup', 'ephemeral-reconcile', 'ephemeral-cleanup')

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
