#!/usr/bin/env python3
"""Exercise the checked-in capability profiles through the shared profile extension."""
from copy import deepcopy
from pathlib import Path
import importlib.util
import yaml

HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parents[1]
SPIKE = CAPABILITY.parents[3] / 'architecture/spikes/ADR-Platform-039'
spec = importlib.util.spec_from_file_location('profile_config', CAPABILITY / 'tests/profile_config.py')
profile_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile_config)


def load(path):
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise AssertionError(f'{path} must contain a YAML mapping')
    return value


def must_reject(label, call):
    try:
        call()
    except (AssertionError, ValueError):
        print(f'PASS invalid profile rejected: {label}')
        return
    raise AssertionError(f'invalid profile accepted: {label}')


base = load(SPIKE / 'live/profile/namespace-profile-live.yaml')
doc = load(SPIKE / 'developer-workspace-v0alpha1.example.yaml')
cases = (
    ('namespace-profile-local-quota.yaml', 'ok-storage-local-quota', False, True, ['ok-storage-local-quota']),
    ('namespace-profile-local-path.yaml', 'local-path', True, False, []),
)
for filename, storage_class, host_users, enforced, classes in cases:
    expected = deepcopy(base)
    expected['spec'].update({
        'storageClassName': storage_class,
        'hostUsers': host_users,
        'persistentCapacity': {
            'runtimeEnforced': enforced,
            'capacityEnforcingStorageClasses': classes,
        },
    })
    profile = load(CAPABILITY / 'profiles' / filename)
    if profile != expected:
        raise AssertionError(f'{filename} drifted from the frozen spike profile plus reviewed capability fields')
    capacity = profile_config.validate_capacity(profile)
    if capacity['runtimeEnforced'] is not enforced:
        raise AssertionError(f'{filename} returned an unexpected capacity mode')
    rendered = profile_config.reference_render(doc, profile)
    resources = rendered['spec']['resources']
    deployment = next(item for item in resources if item['kind'] == 'Deployment')
    namespace = next(item for item in resources if item['kind'] == 'Namespace')
    pod = deployment['spec']['template']['spec']
    if pod.get('hostUsers') is not host_users:
        raise AssertionError(f'{filename} rendered the wrong hostUsers value')
    has_namespace_marker = namespace['metadata'].get('labels', {}).get('workspace.openkubes.io/host-users') == 'false'
    if has_namespace_marker is not (not host_users):
        raise AssertionError(f'{filename} rendered the wrong Namespace user-namespace marker')
    print(f'PASS profile validated and reference-rendered: {filename}')

invalid = load(CAPABILITY / 'profiles/namespace-profile-local-quota.yaml')
invalid['spec']['persistentCapacity']['capacityEnforcingStorageClasses'] = []
must_reject('enforced class absent from declaration', lambda: profile_config.validate_capacity(invalid))
must_reject('reference render rejects inconsistent declaration', lambda: profile_config.reference_render(doc, invalid))
