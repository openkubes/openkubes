"""Capability profile extension and the EnvironmentConfig consumed by the Composition.

OK-174's spike is frozen. Derive local-path profiles therefrom with explicit hostUsers=True;
reference_render validates this capability-only field, then extends the unchanged spike render.
"""
import copy, importlib.util
from pathlib import Path
import yaml

SPIKE = Path(__file__).resolve().parents[5] / 'architecture/spikes/ADR-Platform-039'
spec = importlib.util.spec_from_file_location('capability_spike_render', SPIKE / 'verify_developer_workspace_v1.py')
spike = importlib.util.module_from_spec(spec); spec.loader.exec_module(spike)

def load_profile(path):
    """Derive a capability-owned local-path profile from an unchanged spike catalog."""
    profile = yaml.safe_load(Path(path).read_text())
    profile['spec']['hostUsers'] = True
    return profile

def reference_render(doc, profile):
    """Require hostUsers, strip it for spike validation/rendering, then set the pod field."""
    selected = copy.deepcopy(profile)
    spike.expect(isinstance(selected.get('spec'), dict) and isinstance(selected['spec'].get('hostUsers'), bool),
                 'invalid profile shape: hostUsers must be a required boolean')
    host_users = selected['spec'].pop('hostUsers')
    rendered = spike.render(doc, selected)
    pod = next(r for r in rendered['spec']['resources'] if r['kind'] == 'Deployment')['spec']['template']['spec']
    pod['hostUsers'] = host_users
    return rendered

def profile_config(profile, provider_config, pull_secret=''):
    data = {'profile': profile, 'providerConfigName': provider_config}
    if pull_secret: data['imagePullSecret'] = pull_secret
    return {'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig',
            'metadata': {'name': 'developer-workspace-profile'}, 'data': data}
