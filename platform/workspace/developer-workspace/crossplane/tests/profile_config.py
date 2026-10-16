"""Capability profile extension and the EnvironmentConfig consumed by the Composition.

OK-174's spike is frozen. Derive local-path profiles with explicit hostUsers=True and no
runtime capacity claim; validate capability fields before extending the unchanged spike render.
"""
import copy, importlib.util, re
from pathlib import Path
import yaml

SPIKE = Path(__file__).resolve().parents[5] / 'architecture/spikes/ADR-Platform-039'
spec = importlib.util.spec_from_file_location('capability_spike_render', SPIKE / 'verify_developer_workspace_v1.py')
spike = importlib.util.module_from_spec(spec); spec.loader.exec_module(spike)

def load_profile(path):
    """Derive a capability-owned local-path profile from an unchanged spike catalog."""
    profile = yaml.safe_load(Path(path).read_text())
    profile['spec']['hostUsers'] = True
    profile['spec']['persistentCapacity'] = {'runtimeEnforced': False, 'capacityEnforcingStorageClasses': []}
    return profile

def validate_capacity(profile):
    """Validate the operator declaration; this cannot certify a backend's runtime behavior."""
    p = profile.get('spec', {})
    spike.expect(isinstance(p, dict) and isinstance(p.get('hostUsers'), bool),
                 'invalid profile shape: hostUsers must be a required boolean')
    capacity = p.get('persistentCapacity')
    spike.expect(isinstance(capacity, dict) and set(capacity) == {'runtimeEnforced', 'capacityEnforcingStorageClasses'},
                 'invalid profile shape: persistentCapacity')
    spike.expect(isinstance(capacity['runtimeEnforced'], bool), 'invalid persistentCapacity: runtimeEnforced')
    classes = capacity['capacityEnforcingStorageClasses']
    spike.expect(isinstance(classes, list), 'invalid persistentCapacity: capacityEnforcingStorageClasses')
    spike.expect(all(isinstance(c, str) and re.fullmatch(r'[a-z0-9]([-a-z0-9.]*[a-z0-9])?', c) for c in classes),
                 'invalid capacity-enforcing storage class')
    if capacity['runtimeEnforced']:
        spike.expect(p['hostUsers'] is False, 'runtime-enforced capacity requires hostUsers=false')
        spike.expect(p.get('storageClassName') in classes,
                     'runtime-enforced capacity requires a declared capacity-enforcing storageClassName')
    return capacity

def reference_render(doc, profile):
    """Validate and strip capability fields, then add capability-owned runtime metadata."""
    selected = copy.deepcopy(profile)
    capacity = validate_capacity(selected)
    host_users = selected['spec'].pop('hostUsers')
    selected['spec'].pop('persistentCapacity')
    rendered = spike.render(doc, selected)
    namespace = next(r for r in rendered['spec']['resources'] if r['kind'] == 'Namespace')
    namespace['metadata']['labels']['workspace.openkubes.io/persistent-capacity'] = (
        'runtime-enforced' if capacity['runtimeEnforced'] else 'not-runtime-enforced')
    pod = next(r for r in rendered['spec']['resources'] if r['kind'] == 'Deployment')['spec']['template']['spec']
    pod['hostUsers'] = host_users
    return rendered

def profile_config(profile, provider_config, pull_secret=''):
    data = {'profile': profile, 'providerConfigName': provider_config}
    if pull_secret: data['imagePullSecret'] = pull_secret
    return {'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig',
            'metadata': {'name': 'developer-workspace-profile'}, 'data': data}
