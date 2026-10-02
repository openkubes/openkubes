#!/usr/bin/env python3
"""The Composition must emit exactly what the capability reference rendering produces.

render() in architecture/spikes/ADR-Platform-039/verify_developer_workspace_v1.py is the oracle
OK-174's live evidence was recorded against. For each case this runs `crossplane render` on the
Composition with the reviewed profile, then requires the manifests inside the composed Objects to
equal the unchanged render(doc, profile) plus profile_config's hostUsers and Namespace-label
extensions and the operational setting (imagePullSecrets). It also
requires the Composition to fail closed when the profile is missing or does not resolve a
reference.

Functions run as Development-runtime containers (see Makefile `functions-up`): this workstation's
Crossplane CLI cannot reach a Docker socket directly.
"""
import copy, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parent
REPO = CAPABILITY.parents[3]
SPIKE = REPO / 'architecture/spikes/ADR-Platform-039'
CROSSPLANE = os.environ.get('CROSSPLANE', 'crossplane')
TARGETS = {'function-go-templating': os.environ.get('GOTEMPLATING_TARGET', 'localhost:9443'),
           'function-auto-ready': os.environ.get('AUTOREADY_TARGET', 'localhost:9444')}
PROVIDER_CONFIG = 'in-cluster'
HOST_USERS_LABEL = 'workspace.openkubes.io/host-users'

spec = importlib.util.spec_from_file_location('profile_config', HERE / 'profile_config.py')
profile_configs = importlib.util.module_from_spec(spec); spec.loader.exec_module(profile_configs)

def load(path): return yaml.safe_load(Path(path).read_text())

def functions_file(directory):
    docs = []
    for doc in yaml.safe_load_all((HERE / 'functions.yaml').read_text()):
        doc['metadata'].setdefault('annotations', {}).update({
            'render.crossplane.io/runtime': 'Development',
            'render.crossplane.io/runtime-development-target': TARGETS[doc['metadata']['name']]})
        docs.append(doc)
    path = Path(directory) / 'functions.yaml'; path.write_text(yaml.safe_dump_all(docs)); return path

def profile_config(profile, pull_secret): return profile_configs.profile_config(profile, PROVIDER_CONFIG, pull_secret)

def render(doc, extra, directory, observed=None):
    xr = Path(directory) / 'xr.yaml'; xr.write_text(yaml.safe_dump(doc, sort_keys=False))
    args = [CROSSPLANE, 'composition', 'render', str(xr), str(CAPABILITY / 'composition.yaml'),
            str(functions_file(directory)), '--crossplane-version=v2.3.3']
    if observed is not None:
        path = Path(directory) / 'observed.yaml'; path.write_text(yaml.safe_dump_all(observed)); args.append(f'--observed-resources={path}')
    if extra is not None:
        path = Path(directory) / 'extra.yaml'; path.write_text(yaml.safe_dump_all(extra)); args.append(f'--required-resources={path}')
    done = subprocess.run(args, text=True, capture_output=True)
    return done, [d for d in yaml.safe_load_all(done.stdout) if d] if done.returncode == 0 else []

def expected(doc, profile, pull_secret):
    resources = profile_configs.reference_render(doc, profile)['spec']['resources']
    if pull_secret:
        pod = next(r for r in resources if r['kind'] == 'Deployment')['spec']['template']['spec']
        pod['imagePullSecrets'] = [{'name': pull_secret}]
    return {(r['kind'], r['metadata']['name']): r for r in resources}

def composed(outputs):
    objects = [o for o in outputs if o.get('kind') == 'Object']
    for o in objects:
        assert o['spec']['providerConfigRef'] == {'name': PROVIDER_CONFIG}, o['metadata']['name']
        assert o['spec']['deletionPolicy'] == 'Delete', o['metadata']['name']
        assert o['spec']['watch'] is True, o['metadata']['name']
    names = [o['metadata']['name'] for o in objects]
    assert len(set(names)) == len(names) and all(len(n) <= 63 for n in names), f'composed Object names collide or exceed 63: {names}'
    manifests = [o['spec']['forProvider']['manifest'] for o in objects]
    return {(m['kind'], m['metadata']['name']): m for m in manifests}, objects

def check_user_namespace_policy():
    docs = list(yaml.safe_load_all((CAPABILITY / 'install/pod-user-namespace-guard.yaml').read_text()))
    policy = next(d for d in docs if d['kind'] == 'ValidatingAdmissionPolicy')
    binding = next(d for d in docs if d['kind'] == 'ValidatingAdmissionPolicyBinding')
    assert policy['metadata']['name'] == 'workspace-pod-user-namespace-required'
    assert policy['spec']['failurePolicy'] == 'Fail'
    constraints = policy['spec']['matchConstraints']
    assert constraints['namespaceSelector'] == {'matchLabels': {HOST_USERS_LABEL: 'false'}}
    assert constraints['resourceRules'] == [{
        'apiGroups': [''], 'apiVersions': ['v1'], 'operations': ['CREATE', 'UPDATE'],
        'resources': ['pods', 'pods/ephemeralcontainers'], 'scope': 'Namespaced'}]
    assert policy['spec']['validations'] == [{
        'expression': 'has(object.spec.hostUsers) && object.spec.hostUsers == false',
        'message': 'Pods in this workspace Namespace must set spec.hostUsers to false'}]
    assert binding['spec'] == {
        'policyName': 'workspace-pod-user-namespace-required', 'validationActions': ['Deny']}
    print('PASS pod user namespace policy: manifest defines Fail/Deny and Namespaced Pod CREATE/UPDATE scope')

def variant(base, runtime='opencode', mode='persistent'):
    doc = copy.deepcopy(base); doc['spec']['runtime']['profile'] = runtime
    if mode == 'ephemeral':
        doc['spec']['storage']['mode'] = 'ephemeral'
        doc['spec']['lifecycle'].update({'profile': 'ephemeral', 'deletion': 'after-retention'})
    return doc

def mutations(doc):
    """Inputs the capability reference rejects; the Composition must reject each one too."""
    s = doc['spec']; git, inference, mcp = (s['capabilities'][k]['reference'] for k in ('git', 'inference', 'mcp'))
    def p(fn): return lambda d, pr: fn(pr['spec'])
    def d(fn): return lambda dd, pr: fn(dd['spec'])
    service = lambda pr: next(c['destination'] for c in pr['capabilities'].values() if 'service' in c['destination'])
    def top(fn): return lambda d, pr: fn(pr)
    return {
        'wrong profile kind': top(lambda x: x.update(kind='OtherCatalog')),
        'wrong profile apiVersion': top(lambda x: x.update(apiVersion='workspace.openkubes.io/v2')),
        'unreviewed profile name': top(lambda x: x['metadata'].update(name='unreviewed-profile')),
        'extra profile metadata': top(lambda x: x['metadata'].update(labels={'a': 'b'})),
        'extra top-level profile key': top(lambda x: x.update(status={})),
        'extra spec key': p(lambda x: x.update(extra='x')),
        'malformed IPv6 host route': p(lambda x: x['capabilities'][inference]['destination'].update(cidr=':::::/128')),
        'empty namespacePrefix': p(lambda x: x.update(namespacePrefix='')),
        'invalid storageClassName': p(lambda x: x.update(storageClassName='Bad_Class')),
        'missing hostUsers': p(lambda x: x.pop('hostUsers')),
        'non-boolean hostUsers': p(lambda x: x.update(hostUsers='false')),
        'extra source': p(lambda x: x['sources'].update({'sourceref:other': next(iter(x['sources'].values()))})),
        'http source endpoint': p(lambda x: next(iter(x['sources'].values())).update(endpoint='http://git.example.invalid')),
        'source endpoint with path': p(lambda x: next(iter(x['sources'].values())).update(endpoint='https://git.example.invalid/sub')),
        'unsafe repositoryPath': p(lambda x: next(iter(x['sources'].values())).update(repositoryPath='../etc')),
        'CA bundle without key': p(lambda x: next(iter(x['sources'].values()))['caBundle'].pop('key')),
        'extra runtime profile': p(lambda x: x['runtimeProfiles'].update(other=x['runtimeProfiles']['opencode'])),
        'env template bound to git': p(lambda x: x['runtimeProfiles']['opencode']['envTemplate'].update(capabilityRef=git)),
        'ftp endpoint scheme': p(lambda x: x['runtimeProfiles']['codex']['envTemplate'].update(endpointScheme='ftp')),
        'relative endpoint path': p(lambda x: x['runtimeProfiles']['opencode']['envTemplate'].update(endpointPath='v1')),
        'extra capability': p(lambda x: x['capabilities'].update({'capabilityref:extra': x['capabilities'][git]})),
        'missing mcp capability': p(lambda x: x['capabilities'].pop(mcp)),
        'approvedTools on git capability': p(lambda x: x['capabilities'][git].update(approvedTools=[])),
        'port 0': p(lambda x: x['capabilities'][git]['destination'].update(port=0)),
        'port 70000': p(lambda x: x['capabilities'][inference]['destination'].update(port=70000)),
        'non-host CIDR': p(lambda x: x['capabilities'][inference]['destination'].update(cidr='10.0.0.0/24')),
        'service without name': p(lambda x: service(x)['service'].pop('name')),
        'extra service selector': p(lambda x: x['serviceSelectors'].update({'other/svc': {'app': 'x'}})),
        'empty service selector': p(lambda x: x['serviceSelectors'].update({k: {} for k in x['serviceSelectors']})),
        'extra model profile': p(lambda x: x['modelProfiles'].update({'modelref:other': next(iter(x['modelProfiles'].values()))})),
        'model bound to git': p(lambda x: next(iter(x['modelProfiles'].values())).update(inferenceCapabilityRef=git)),
        'model ref not in profile': d(lambda x: x['model'].update(profileRef='modelref:not-in-profile')),
        'undeclared MCP tool': d(lambda x: x['capabilities']['mcp'].update(approvedTools=['toolref:delete-everything'])),
        'inference ref equals git ref': d(lambda x: x['capabilities']['inference'].update(reference=git)),
        'extra credential': p(lambda x: x['credentials'].update({'credentialref:other': next(iter(x['credentials'].values()))})),
        'credential bound to inference': p(lambda x: next(iter(x['credentials'].values())).update(capabilityRef=inference)),
        'credential without secretKey': p(lambda x: next(iter(x['credentials'].values())).pop('secretKey')),
    }

def main():
    base = load(SPIKE / 'developer-workspace-v0alpha1.example.yaml'); profile = profile_configs.load_profile(SPIKE / 'namespace-profile-v1.yaml')
    failures = []; checked = 0
    try: check_user_namespace_policy()
    except (AssertionError, KeyError, StopIteration) as error: failures.append(f'pod user namespace policy: {error!r}')
    with tempfile.TemporaryDirectory(prefix='ok175-render-') as directory:
        for host_users in (True, False):
            selected_profile = copy.deepcopy(profile); selected_profile['spec']['hostUsers'] = host_users
            for runtime in ('opencode', 'codex'):
                for mode in ('persistent', 'ephemeral'):
                    for pull_secret in ('', 'registry-pull'):
                        doc = variant(base, runtime, mode); name = f'hostUsers={str(host_users).lower()}/{runtime}/{mode}/{"pull-secret" if pull_secret else "no-pull-secret"}'
                        done, outputs = render(doc, [profile_config(selected_profile, pull_secret)], directory)
                        if done.returncode: failures.append(f'{name}: render failed: {done.stderr.strip()[:300]}'); continue
                        want = expected(doc, selected_profile, pull_secret); got, objects = composed(outputs)
                        namespace = got.get(('Namespace', 'dw-sample-174'))
                        labels = namespace.get('metadata', {}).get('labels', {}) if namespace else {}
                        labeled = sorted(key for key, manifest in got.items()
                                         if HOST_USERS_LABEL in manifest.get('metadata', {}).get('labels', {}))
                        if host_users is False and (labels.get(HOST_USERS_LABEL) != 'false' or labeled != [('Namespace', 'dw-sample-174')]):
                            failures.append(f'{name}: expected {HOST_USERS_LABEL}=false only on the Namespace; labeled={labeled}')
                        elif host_users is True and labeled:
                            failures.append(f'{name}: {HOST_USERS_LABEL} unexpectedly labels {labeled}')
                        if got != want:
                            missing = sorted(set(want) - set(got)); extra = sorted(set(got) - set(want))
                            differ = sorted(k for k in set(want) & set(got) if want[k] != got[k])
                            failures.append(f'{name}: missing={missing} extra={extra} differ={differ}')
                            for k in differ[:2]: failures.append(f'  {k} want={json.dumps(want[k], sort_keys=True)[:400]}\n  {k} got ={json.dumps(got[k], sort_keys=True)[:400]}')
                        else:
                            checked += 1; print(f'PASS {name}: {len(objects)} Objects equal capability reference rendering; Namespace {HOST_USERS_LABEL}={labels.get(HOST_USERS_LABEL, "absent")}')
        doc = copy.deepcopy(base); doc['spec']['workspaceID'] = 'ws-' + 'a' * 48  # the schema's longest ID
        done, outputs = render(doc, [profile_config(profile, '')], directory)
        try:
            if done.returncode: raise AssertionError(done.stderr.strip()[:300])
            got, objects = composed(outputs); assert got == expected(doc, profile, ''), 'manifests differ from capability reference rendering'
            checked += 1; print(f'PASS longest workspaceID: {len(objects)} uniquely named Objects equal capability reference rendering')
        except AssertionError as error: failures.append(f'longest workspaceID: {error}')
        status = lambda outputs: {k: v for k, v in next((o for o in outputs if o.get('kind') == 'DeveloperWorkspace'), {}).get('status', {}).items() if k != 'conditions'}
        done, outputs = render(base, [profile_config(profile, '')], directory)
        _, objects = composed(outputs)
        if status(outputs) == {'namespace': 'dw-sample-174', 'lifecyclePhase': 'pending'}: print('PASS status: pending until the Deployment is observed available')
        else: failures.append(f'status before availability: {status(outputs)}')
        deployment = copy.deepcopy(next(o for o in objects if o['spec']['forProvider']['manifest']['kind'] == 'Deployment'))
        deployment['status'] = {'atProvider': {'manifest': {'status': {'availableReplicas': 1}}}}
        done, outputs = render(base, [profile_config(profile, '')], directory, [deployment])
        if done.returncode == 0 and status(outputs).get('lifecyclePhase') == 'running': print('PASS status: running once the Deployment is available')
        else: failures.append(f'status after availability: rc={done.returncode} {status(outputs) if done.returncode == 0 else done.stderr[:300]}')
        done, outputs = render(base, None, directory)
        if done.returncode != 0 and 'developer-workspace-profile not found' in done.stderr: print('PASS no profile EnvironmentConfig: render fails, nothing composed')
        else: failures.append(f'no profile EnvironmentConfig: expected a failure naming it, got rc={done.returncode} objects={len([o for o in outputs if o.get("kind") == "Object"])}')
        rejected = 0; cases = mutations(base)
        for label, mutate in cases.items():
            doc, broken = copy.deepcopy(base), copy.deepcopy(profile); mutate(doc, broken)
            try: profile_configs.reference_render(doc, broken); failures.append(f'{label}: reference_render() accepts it; the case is not a rejection'); continue
            except Exception: pass
            done, outputs = render(doc, [profile_config(broken, '')], directory)
            if done.returncode != 0 and 'fatal result' in done.stderr: rejected += 1
            else: failures.append(f'{label}: reference_render() rejects it but the Composition composed {len([o for o in outputs if o.get("kind") == "Object"])} Objects')
        if rejected == len(cases): print(f'PASS fail closed: the Composition rejects all {rejected} inputs the capability reference rejects')
    for f in failures: print('FAIL ' + f, file=sys.stderr)
    return 1 if failures or checked != 17 else 0

if __name__ == '__main__':
    raise SystemExit(main())
