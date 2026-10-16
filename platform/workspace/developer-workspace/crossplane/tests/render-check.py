#!/usr/bin/env python3
"""The Composition must emit exactly what the capability reference rendering produces.

render() in architecture/spikes/ADR-Platform-039/verify_developer_workspace_v1.py is the oracle
OK-174's live evidence was recorded against. For each case this runs `crossplane render` on the
Composition with the reviewed profile, then requires the manifests inside the composed Objects to
equal the unchanged render(doc, profile) plus profile_config's validated capacity/hostUsers extension and the
operational setting (imagePullSecrets). It also
requires the Composition to fail closed when the profile is missing or does not resolve a
reference.

Functions run as Development-runtime containers (see Makefile `functions-up`): this workstation's
Crossplane CLI cannot reach a Docker socket directly.
"""
import copy, hashlib, importlib.util, json, os, subprocess, sys, tempfile
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parent
REPO = CAPABILITY.parents[3]
SPIKE = REPO / 'architecture/spikes/ADR-Platform-039'
CROSSPLANE = os.environ.get('CROSSPLANE', 'crossplane')
RENDER_BINARY = os.environ.get('CROSSPLANE_RENDER_BINARY', '')
TARGETS = {'function-go-templating': os.environ.get('GOTEMPLATING_TARGET', 'localhost:9443'),
           'function-auto-ready': os.environ.get('AUTOREADY_TARGET', 'localhost:9444')}
PROVIDER_CONFIG = 'in-cluster'

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
            str(functions_file(directory))]
    args.append(f'--crossplane-binary={RENDER_BINARY}' if RENDER_BINARY else '--crossplane-version=v2.3.3')
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

def expected_object_name(workspace_id, resource_key):
    digest = hashlib.sha256(workspace_id.encode()).hexdigest()[:32]
    return f'dw-{digest}-{resource_key}'[:63].removesuffix('-')

def composition_resource_keys(doc, profile):
    keys = ['namespace', 'serviceaccount', 'resourcequota', 'limitrange', 'networkpolicy-default-deny']
    if doc['spec']['storage']['mode'] == 'persistent': keys.append('persistentvolumeclaim')
    refs = [doc['spec']['capabilities'][kind]['reference'] for kind in ('git', 'inference', 'mcp')]
    keys.extend('networkpolicy-allow-' + ref.split(':', 1)[1] for ref in refs)
    if any('service' in profile['spec']['capabilities'][ref]['destination'] for ref in refs):
        keys.append('networkpolicy-allow-kube-dns')
    keys.append('deployment')
    return keys

def composed(outputs, workspace_id=None, profile=None, doc=None):
    objects = [o for o in outputs if o.get('kind') == 'Object']
    for o in objects:
        assert o['spec']['providerConfigRef'] == {'name': PROVIDER_CONFIG}, o['metadata']['name']
        assert o['spec']['deletionPolicy'] == 'Delete', o['metadata']['name']
        assert o['spec']['watch'] is True, o['metadata']['name']
    names = [o['metadata']['name'] for o in objects]
    assert len(set(names)) == len(names) and all(len(n) <= 63 for n in names), f'composed Object names collide or exceed 63: {names}'
    if workspace_id is not None:
        assert profile is not None and doc is not None
        expected_names = {expected_object_name(workspace_id, key) for key in composition_resource_keys(doc, profile)}
        assert set(names) == expected_names, f'composed Object names differ: expected={sorted(expected_names)} got={sorted(names)}'
    manifests = [o['spec']['forProvider']['manifest'] for o in objects]
    return {(m['kind'], m['metadata']['name']): m for m in manifests}, objects

def assert_capacity_label(manifests, value):
    """Require the runtime-capacity declaration on the Namespace and nowhere else."""
    label = 'workspace.openkubes.io/persistent-capacity'
    namespaces = [m for (kind, _), m in manifests.items() if kind == 'Namespace']
    assert len(namespaces) == 1, f'expected one Namespace, got {len(namespaces)}'
    assert namespaces[0]['metadata']['labels'].get(label) == value, (
        f'Namespace {label}={namespaces[0]["metadata"]["labels"].get(label)!r}, expected {value!r}')
    leaked = sorted((kind, name) for (kind, name), manifest in manifests.items()
                    if kind != 'Namespace' and label in manifest.get('metadata', {}).get('labels', {}))
    assert not leaked, f'{label} leaked onto non-Namespace resources: {leaked}'

def variant(base, runtime='opencode', mode='persistent'):
    doc = copy.deepcopy(base); doc['spec']['runtime']['profile'] = runtime
    if mode == 'ephemeral':
        doc['spec']['storage']['mode'] = 'ephemeral'
        doc['spec']['lifecycle'].update({'profile': 'ephemeral', 'deletion': 'after-retention'})
    return doc

def canonicalize_name(doc):
    """Use the XRD admission envelope's canonical XR name for positive render inputs."""
    doc['metadata']['name'] = doc['spec']['workspaceID'] + '-xr'
    return doc

def replace_capability_refs(doc, profile, refs):
    """Return an oracle-valid input/profile pair with the three capability refs replaced."""
    doc, profile = copy.deepcopy(doc), copy.deepcopy(profile)
    old = {kind: doc['spec']['capabilities'][kind]['reference'] for kind in ('git', 'inference', 'mcp')}
    for kind in old:
        doc['spec']['capabilities'][kind]['reference'] = refs[kind]
        profile['spec']['capabilities'][refs[kind]] = profile['spec']['capabilities'].pop(old[kind])
    for runtime in profile['spec']['runtimeProfiles'].values():
        runtime['envTemplate']['capabilityRef'] = refs['inference']
    for model in profile['spec']['modelProfiles'].values():
        model['inferenceCapabilityRef'] = refs['inference']
    for credential in profile['spec']['credentials'].values():
        credential['capabilityRef'] = refs['git']
    return doc, profile

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
        'missing persistentCapacity': p(lambda x: x.pop('persistentCapacity')),
        'missing runtimeEnforced': p(lambda x: x['persistentCapacity'].pop('runtimeEnforced')),
        'non-boolean runtimeEnforced': p(lambda x: x['persistentCapacity'].update(runtimeEnforced='true')),
        'extra persistentCapacity key': p(lambda x: x['persistentCapacity'].update(extra=True)),
        'missing capacityEnforcingStorageClasses': p(lambda x: x['persistentCapacity'].pop('capacityEnforcingStorageClasses')),
        'non-list capacityEnforcingStorageClasses': p(lambda x: x['persistentCapacity'].update(capacityEnforcingStorageClasses='quota-class')),
        'invalid capacity-enforcing class': p(lambda x: x['persistentCapacity'].update(capacityEnforcingStorageClasses=['Bad_Class'])),
        'non-string capacity-enforcing class': p(lambda x: x['persistentCapacity'].update(capacityEnforcingStorageClasses=[42])),
        'enforced class with hostUsers:true': p(lambda x: x.update(hostUsers=True, persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': [x['storageClassName']]})),
        'enforced class with hostUsers omitted': p(lambda x: (x.update(persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': [x['storageClassName']]}), x.pop('hostUsers'))),
        'undeclared class with enforced claim': p(lambda x: x.update(hostUsers=False, storageClassName='other-class', persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': ['quota-class']})),
        'empty enforcing classes with enforced claim': p(lambda x: x.update(hostUsers=False, persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': []})),
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
    # crossplane render does not execute XRD admission CEL; keep oracle inputs admissible.
    base = canonicalize_name(load(SPIKE / 'developer-workspace-v0alpha1.example.yaml')); profile = profile_configs.load_profile(SPIKE / 'namespace-profile-v1.yaml')
    failures = []; checked = 0; capacity_labels = set()
    with tempfile.TemporaryDirectory(prefix='ok175-render-') as directory:
        collision_names = []
        try:
            for workspace_id in ('ws-c69924', 'ws-cd9634'):
                doc = copy.deepcopy(base); doc['spec']['workspaceID'] = workspace_id; canonicalize_name(doc)
                done, outputs = render(doc, [profile_config(profile, '')], directory)
                if done.returncode: raise AssertionError(f'{workspace_id}: {done.stderr.strip()[:300]}')
                got, objects = composed(outputs, doc['spec']['workspaceID'], profile, doc)
                assert_capacity_label(got, 'not-runtime-enforced')
                capacity_labels.add('not-runtime-enforced')
                assert got == expected(doc, profile, ''), f'{workspace_id}: manifests differ from render()'
                collision_names.append({o['metadata']['name'] for o in objects})
            assert collision_names[0].isdisjoint(collision_names[1]), 'formerly colliding workspaceIDs produced overlapping composed Object names'
            checked += 1; print('PASS workspace digest collision: formerly colliding workspaceIDs produce disjoint Object names')
        except AssertionError as error:
            print(f'FAIL workspace digest collision: {error}', file=sys.stderr)
            return 1
        for host_users in (True, False):
            selected_profile = copy.deepcopy(profile); selected_profile['spec']['hostUsers'] = host_users
            for runtime in ('opencode', 'codex'):
                for mode in ('persistent', 'ephemeral'):
                    for pull_secret in ('', 'registry-pull'):
                        doc = variant(base, runtime, mode); name = f'hostUsers={str(host_users).lower()}/{runtime}/{mode}/{"pull-secret" if pull_secret else "no-pull-secret"}'
                        done, outputs = render(doc, [profile_config(selected_profile, pull_secret)], directory)
                        if done.returncode: failures.append(f'{name}: render failed: {done.stderr.strip()[:300]}'); continue
                        want = expected(doc, selected_profile, pull_secret); got, objects = composed(outputs, doc['spec']['workspaceID'], selected_profile, doc)
                        try:
                            assert_capacity_label(got, 'not-runtime-enforced')
                            capacity_labels.add('not-runtime-enforced')
                        except AssertionError as error:
                            failures.append(f'{name}: {error}')
                        if got != want:
                            missing = sorted(set(want) - set(got)); extra = sorted(set(got) - set(want))
                            differ = sorted(k for k in set(want) & set(got) if want[k] != got[k])
                            failures.append(f'{name}: missing={missing} extra={extra} differ={differ}')
                            for k in differ[:2]: failures.append(f'  {k} want={json.dumps(want[k], sort_keys=True)[:400]}\n  {k} got ={json.dumps(got[k], sort_keys=True)[:400]}')
                        else:
                            checked += 1; print(f'PASS {name}: {len(objects)} Objects equal capability reference rendering')
        enforcing = copy.deepcopy(profile)
        enforcing['spec'].update(hostUsers=False, storageClassName='quota-class',
                                 persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': ['quota-class']})
        for runtime in ('opencode', 'codex'):
            for mode in ('persistent', 'ephemeral'):
                for pull_secret in ('', 'registry-pull'):
                    doc = variant(base, runtime, mode)
                    done, outputs = render(doc, [profile_config(enforcing, pull_secret)], directory)
                    name = f'runtime-enforced/{runtime}/{mode}/{"pull-secret" if pull_secret else "no-pull-secret"}'
                    if done.returncode:
                        failures.append(f'{name}: render failed: {done.stderr.strip()[:300]}'); continue
                    got, objects = composed(outputs, doc['spec']['workspaceID'], enforcing, doc)
                    try:
                        assert_capacity_label(got, 'runtime-enforced')
                        capacity_labels.add('runtime-enforced')
                    except AssertionError as error:
                        failures.append(f'{name}: {error}')
                    if got != expected(doc, enforcing, pull_secret): failures.append(f'{name}: manifests differ')
                    else:
                        checked += 1; print(f'PASS {name}: {len(objects)} Objects equal capability reference rendering')
        local_path_enforcing = copy.deepcopy(profile)
        local_path_enforcing['spec'].update(
            hostUsers=False,
            persistentCapacity={'runtimeEnforced': True, 'capacityEnforcingStorageClasses': ['local-path']})
        done, outputs = render(base, [profile_config(local_path_enforcing, '')], directory)
        name = 'self-declared-local-path/runtime-enforced'
        if done.returncode:
            failures.append(f'{name}: render failed: {done.stderr.strip()[:300]}')
        else:
            got, objects = composed(outputs, base['spec']['workspaceID'], local_path_enforcing, base)
            try:
                assert_capacity_label(got, 'runtime-enforced')
                capacity_labels.add('runtime-enforced')
            except AssertionError as error:
                failures.append(f'{name}: {error}')
            if got != expected(base, local_path_enforcing, ''):
                failures.append(f'{name}: manifests differ')
            else:
                namespace = next(m for (kind, _), m in got.items() if kind == 'Namespace')
                checked += 1
                print(f'PASS {name}: operator declaration accepted; {len(objects)} Objects equal capability reference rendering')
                print('RENDERED self-declared local-path Namespace:\n' + yaml.safe_dump(namespace, sort_keys=False).rstrip())
        if capacity_labels == {'runtime-enforced', 'not-runtime-enforced'}:
            print('PASS Namespace persistent-capacity label: both explicit values rendered and confined to Namespace')
        else:
            failures.append(f'Namespace persistent-capacity label values: got {sorted(capacity_labels)}')
        doc = copy.deepcopy(base); doc['spec']['workspaceID'] = 'ws-' + 'a' * 48  # the schema's longest ID
        canonicalize_name(doc)
        max_refs = {
            'git': 'capabilityref:git-' + 'g' * 63,
            'inference': 'capabilityref:inference-' + 'i' * 63,
            'mcp': 'capabilityref:mcp-' + 'm' * 63,
        }
        doc, longest_profile = replace_capability_refs(doc, profile, max_refs)
        done, outputs = render(doc, [profile_config(longest_profile, '')], directory)
        try:
            if done.returncode: raise AssertionError(done.stderr.strip()[:300])
            got, objects = composed(outputs, doc['spec']['workspaceID'], longest_profile, doc); assert got == expected(doc, longest_profile, ''), 'manifests differ from render()'
            longest_key = max(composition_resource_keys(doc, longest_profile), key=len)
            assert longest_key == 'networkpolicy-allow-inference-' + 'i' * 63, f'unexpected longest resource key: {longest_key}'
            assert len(longest_key) == 93, f'longest resource key is {len(longest_key)} characters, expected 93'
            longest_name = expected_object_name(doc['spec']['workspaceID'], longest_key)
            assert longest_name in {o['metadata']['name'] for o in objects}, f'longest composed Object name is absent: {longest_name}'
            assert len(longest_name) == 63, f'longest composed Object name is {len(longest_name)} characters, expected 63'
            checked += 1; print(f'PASS longest workspaceID and resource keys: {len(objects)} uniquely named Objects equal render() within 63 characters')
            longest = next(o for o in objects if o['metadata']['name'] == longest_name)
            print(f'RENDERED longest Object name: {longest["metadata"]["name"]} (length={len(longest["metadata"]["name"])}, key length={len(longest_key)})')
        except AssertionError as error: failures.append(f'longest workspaceID: {error}')
        status = lambda outputs: {k: v for k, v in next((o for o in outputs if o.get('kind') == 'DeveloperWorkspace'), {}).get('status', {}).items() if k != 'conditions'}
        done, outputs = render(base, [profile_config(profile, '')], directory)
        if done.returncode:
            for failure in failures: print('FAIL ' + failure, file=sys.stderr)
            print(f'FAIL status render: {done.stderr.strip()[:600]}', file=sys.stderr)
            return 1
        _, objects = composed(outputs, base['spec']['workspaceID'], profile, base)
        if status(outputs) == {'namespace': 'dw-sample-174', 'lifecyclePhase': 'pending'}: print('PASS status: pending until the Deployment is observed available')
        else: failures.append(f'status before availability: {status(outputs)}')
        deployment = next((o for o in objects if o['spec']['forProvider']['manifest']['kind'] == 'Deployment'), None)
        if deployment is None:
            print('FAIL status render: no composed Deployment', file=sys.stderr)
            return 1
        deployment = copy.deepcopy(deployment)
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
            if done.returncode != 0 and 'fatal result' in done.stderr and not outputs:
                required_reason = {
                    'enforced class with hostUsers:true': 'runtime-enforced capacity requires hostUsers=false',
                    'undeclared class with enforced claim': 'runtime-enforced capacity requires a declared capacity-enforcing storageClassName',
                }.get(label)
                if required_reason and required_reason not in done.stderr:
                    failures.append(f'{label}: rejection did not name the capacity guard: {done.stderr[:300]}')
                else:
                    rejected += 1
                    if 'enforced' in label or 'persistentCapacity' in label or 'Enforcing' in label or 'runtimeEnforced' in label or 'capacity-enforcing' in label:
                        print(f'PASS negative {label}: fatal rejection, nothing composed')
            else: failures.append(f'{label}: reference_render() rejects it but the Composition composed {len([o for o in outputs if o.get("kind") == "Object"])} Objects')
        if rejected == len(cases): print(f'PASS fail closed: the Composition rejects all {rejected} inputs the capability reference rejects')
    for f in failures: print('FAIL ' + f, file=sys.stderr)
    if not failures and checked == 27:
        print(f'PASS render-check: {checked} valid renders, status controls, missing-profile control, {rejected} invalid inputs rejected')
    return 1 if failures or checked != 27 else 0

if __name__ == '__main__':
    raise SystemExit(main())
