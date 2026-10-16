#!/usr/bin/env python3
"""Offline negative controls for reconcile_proof.py assertions."""
from __future__ import annotations

import copy
import contextlib
import io
from unittest.mock import patch
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('ok175_reconcile_proof', HERE / 'reconcile_proof.py')
proof = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proof
SPEC.loader.exec_module(proof)
DISABLE_PROVIDER_STEERING_POLICY = '--disable-provider-steering-policy' in sys.argv
DISABLE_NAMESPACE_MUTATION_PROBES = '--disable-namespace-mutation-probes' in sys.argv
DISABLE_ADMISSION_RECEIPT_ORDERING = '--disable-admission-receipt-ordering' in sys.argv


def completed(args, returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(['kubectl', *args], returncode, stdout, stderr)


class CapacityDeclarationTest(unittest.TestCase):
    def test_admission_gate_cannot_omit_a_required_guard(self):
        proof.validate_required_admission_guards(proof.ADMISSION_GUARDS)
        for omitted in proof.ADMISSION_GUARDS:
            with self.subTest(omitted=omitted):
                with self.assertRaisesRegex(proof.ProofError, 'admission gate must include'):
                    proof.validate_required_admission_guards(
                        tuple(path for path in proof.ADMISSION_GUARDS if path != omitted))
        print('CONTROL FAILS AS EXPECTED: omitting any required admission guard closes the install/XR gate')

    def test_installed_profile_data_and_identity_must_match(self):
        profile = proof.render_profile.load_profile(proof.LIVE / 'profile/namespace-profile-live.yaml')
        config = proof.render_profile.profile_config(profile, 'in-cluster')
        live = copy.deepcopy(config)
        live['metadata'].update(uid='profile-uid', resourceVersion='1')
        original = proof.get_json
        proof.get_json = lambda args: live
        try:
            initial = proof.profile_readback(config)
            live['metadata']['resourceVersion'] = '2'
            self.assertEqual(proof.profile_readback(config, initial)['uid'], initial['uid'])
            live['data']['profile']['spec']['persistentCapacity']['runtimeEnforced'] = True
            with self.assertRaisesRegex(proof.ProofError, 'differs from the selected operator declaration'):
                proof.profile_readback(config, initial)
            live['data'] = copy.deepcopy(config['data'])
            live['metadata']['uid'] = 'replacement-uid'
            with self.assertRaisesRegex(proof.ProofError, 'was replaced during proof'):
                proof.profile_readback(config, initial)
        finally:
            proof.get_json = original

    def test_mode_comes_from_profile_and_invalid_claims_fail_before_cluster_use(self):
        profile = proof.render_profile.load_profile(proof.LIVE / 'profile/namespace-profile-live.yaml')
        with tempfile.TemporaryDirectory(prefix='ok176-profile-') as directory:
            path = Path(directory) / 'profile.yaml'
            def read(selected):
                path.write_text(proof.yaml.safe_dump(selected))
                return proof.storage_inputs({'OK176_PROFILE_FILE': str(path)})
            self.assertEqual(read(profile)['mode'], 'observed-negative')
            profile['spec'].update(hostUsers=False, storageClassName='quota-class',
                                  persistentCapacity={'runtimeEnforced': True,
                                                      'capacityEnforcingStorageClasses': ['quota-class']})
            storage = read(profile)
            self.assertEqual(storage['mode'], 'enforced')
            self.assertEqual(storage['declaration'], profile['spec']['persistentCapacity'])
            self.assertEqual(storage['profile'], profile)
            for field, value, reason in [('hostUsers', True, 'requires hostUsers=false'),
                                         ('storageClassName', 'local-path', 'requires a declared capacity-enforcing')]:
                broken = copy.deepcopy(profile); broken['spec'][field] = value
                with self.assertRaisesRegex(proof.ProofError, reason): read(broken)
            with self.assertRaisesRegex(proof.ProofError, 'must come from the profile declaration'):
                proof.storage_inputs({'OK176_PROFILE_FILE': str(path), 'OK176_CAPACITY_MODE': 'enforced'})


class CapacityRefusalTest(unittest.TestCase):
    def setUp(self):
        self.storage = proof.storage_inputs({'OK176_PROFILE_FILE': str(HERE.parent / 'fixtures/self-declared-local-path.yaml')})
        self.assertEqual(self.storage['mode'], 'self-declared-negative')
        self.limit = 16 * proof.WRITE_CHUNK
        self.probe = {'requestedBytes': 20 * proof.WRITE_CHUNK, 'writtenBytes': self.limit,
                      'probeAllocatedBytes': self.limit, 'baselineAllocatedBytes': 0,
                      'totalAllocatedBytes': self.limit, 'availableBeforeBytes': self.limit,
                      'availableAfterBytes': 0, 'reportedCapacityBeforeBytes': self.limit,
                      'reportedCapacityAfterBytes': self.limit, 'error': 'ENOSPC'}

    def exercise(self, bring_up, probe):
        output = io.StringIO()
        with patch.object(proof, 'get_json', return_value={'metadata': {'labels': {'workspace.openkubes.io/persistent-capacity': 'runtime-enforced'}}}), \
             patch.object(proof, 'workspace_pod', return_value='workspace-pod'), \
             patch.object(proof, 'capacity_probe', return_value=probe) as pressure, contextlib.redirect_stdout(output):
            with self.assertRaisesRegex(proof.ProofError, 'persistent-capacity-enforced: certification refused'):
                proof.refuse_self_declared_capacity(self.storage, bring_up)
        result = json.loads(output.getvalue())
        self.assertEqual(result['name'], 'persistent-capacity-certification-refused')
        self.assertEqual(result['status'], 'fail')
        self.assertEqual(result['failedCheck'], 'persistent-capacity-enforced')
        return result, pressure.call_count

    def ready(self, *args):
        return {'spec': {'storage': {'size': '16Mi'}}}, 'dw-negative', None

    def test_live_overfill_refuses_certification(self):
        overfill = dict(self.probe, error=None, writtenBytes=20 * proof.WRITE_CHUNK,
                        totalAllocatedBytes=20 * proof.WRITE_CHUNK)
        result, calls = self.exercise(self.ready, overfill)
        self.assertEqual(calls, 1)
        self.assertEqual(result['stage'], 'persistent-capacity-enforced')
        self.assertIn('overfill was not rejected', result['reason'])
        self.assertEqual(result['observed'], overfill)
        print('CONTROL PASS: self-declared backend overfill fails persistent-capacity-enforced and refuses certification')

    def test_unready_workspace_refuses_certification(self):
        def unready(*args): raise proof.ProofError('timed out waiting for workspace Ready (mount)')
        result, calls = self.exercise(unready, self.probe)
        self.assertEqual(calls, 0)
        self.assertEqual(result['stage'], 'workspace-readiness')
        self.assertIn('workspace Ready', result['reason'])
        print('CONTROL PASS: unready negative-control workspace refuses certification')

    def test_unexpected_enforcement_still_cannot_certify_negative_control(self):
        proof.validate_enforced_capacity(self.probe, self.limit)
        result, calls = self.exercise(self.ready, self.probe)
        self.assertEqual(calls, 1)
        self.assertIn('unexpectedly satisfied', result['reason'])

    def test_capacity_boundaries_reject_false_positives(self):
        mutations = [('writtenBytes', proof.WRITE_CHUNK, 'before filling'),
                     ('requestedBytes', self.limit, 'did not request more'),
                     ('availableBeforeBytes', 0, 'lacked the declared free capacity'),
                     ('totalAllocatedBytes', self.limit + 2 * proof.WRITE_CHUNK, 'total allocated bytes'),
                     ('reportedCapacityBeforeBytes', self.limit * 2, 'statfs reported capacity'),
                     ('reportedCapacityAfterBytes', self.limit * 2, 'statfs reported capacity'),
                     ('availableAfterBytes', 2 * proof.WRITE_CHUNK, 'still reports more')]
        for key, value, reason in mutations:
            with self.subTest(key=key):
                with self.assertRaisesRegex(proof.ProofError, reason):
                    proof.validate_enforced_capacity(dict(self.probe, **{key: value}), self.limit)

    def test_cli_dispatch_refuses_overfill_and_unready_and_writes_no_report(self):
        for ready in (True, False):
            with self.subTest(ready=ready), tempfile.TemporaryDirectory(prefix='ok176-refusal-') as directory, contextlib.ExitStack() as stack:
                output, errors = io.StringIO(), io.StringIO()
                def fake_json(args):
                    if args == ['get', 'developerworkspaces']: return {'items': []}
                    if args[:2] == ['get', 'pods']: return {'items': [{'metadata': {'name': 'git-fixture'}}]}
                    if args == ['get', f'developerworkspace/{proof.NO_PROFILE[0]}']:
                        return {'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}}
                    return {'metadata': {'creationTimestamp': '2026-01-01T00:00:00Z',
                                         'labels': {'workspace.openkubes.io/persistent-capacity': 'runtime-enforced'}}}
                def fake_kubectl(args, **kwargs):
                    if args[:2] == ['apply', '--dry-run=server']:
                        return completed(args, 1, stderr='persistent lifecycle requires persistent storage')
                    if args[:2] == ['create', '--dry-run=server'] and 'ok175-cel-probe' in kwargs.get('input_text', ''):
                        return completed(args, 1, stderr='metadata.name must equal workspaceID + -xr')
                    if (args[:2] == ['create', '-f'] and
                            proof.canonical_xr_name('ws-ok185-policy-gate') in kwargs.get('input_text', '')):
                        raise proof.ProofError('workspace-pod-user-namespace-required binding is missing')
                    if args[0] == 'get': return completed(args, 1, stderr='(NotFound): absent')
                    return completed(args)
                def fake_exec(ns, pod, command, *args, **kwargs):
                    return completed(command, stdout=('a' if command[0] == 'cat' else 'b') * 40)
                patches = {'storage_inputs': lambda: self.storage, 'target': lambda: {'context': 'offline'},
                           'implementation': lambda clean: {}, 'image': lambda name: 'fixture@sha256:' + 'a' * 64,
                           'apply': lambda docs: None, 'proof_services': lambda *args: [],
                           'get_json': fake_json, 'kubectl': fake_kubectl, 'exec_in': fake_exec,
                           'installed_matches_local': lambda: {}, 'assert_noncanonical_name_refused': lambda *args: {},
                           'wait_for_admission_policies': lambda: [],
                           'prove_admission_receipt_gate': lambda *args: {},
                           'wait_until': lambda *args, **kwargs: None, 'profile_readback': lambda *args: {},
                           'composed_objects': lambda name: [], 'revision_matches': lambda *args: {},
                           'workspace_pod': lambda ns: 'runtime-pod',
                           'capacity_probe': lambda *args: dict(self.probe, error=None),
                           'EVIDENCE': Path(directory)}
                for name, value in patches.items(): stack.enter_context(patch.object(proof, name, value))
                wait = stack.enter_context(patch.object(proof, 'wait_ready'))
                if not ready: wait.side_effect = proof.ProofError('workspace mount never became Ready')
                marker = stack.enter_context(patch.object(proof, 'assert_capacity_marker', wraps=proof.assert_capacity_marker))
                stack.enter_context(patch.object(proof.spike, 'tls_material', return_value={'ca': 'fixture'}))
                stack.enter_context(patch.dict(proof.os.environ, {'OK175_REGISTRY_USERNAME': ''}))
                stack.enter_context(patch.object(sys, 'argv', ['reconcile_proof.py', 'run']))
                stack.enter_context(contextlib.redirect_stdout(output)); stack.enter_context(contextlib.redirect_stderr(errors))
                self.assertEqual(proof.main(), 1)
                refusals = [json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
                self.assertEqual(len(refusals), 1, errors.getvalue())
                self.assertEqual(refusals[0]['name'], 'persistent-capacity-certification-refused')
                self.assertEqual(refusals[0]['status'], 'fail')
                self.assertEqual(refusals[0]['stage'], 'persistent-capacity-enforced' if ready else 'workspace-readiness')
                self.assertIn('certification refused', errors.getvalue())
                marker.assert_called()
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_marker_checks_both_declarations_and_rejects_missing_or_wrong_label(self):
        for enforced in (False, True):
            storage = copy.deepcopy(self.storage); storage['declaration']['runtimeEnforced'] = enforced
            marker = 'runtime-enforced' if enforced else 'not-runtime-enforced'
            with patch.object(proof, 'get_json', return_value={'metadata': {'labels': {'workspace.openkubes.io/persistent-capacity': marker}}}):
                proof.assert_capacity_marker('dw-negative', storage)
            for labels in ({}, {'workspace.openkubes.io/persistent-capacity': 'wrong'}):
                with patch.object(proof, 'get_json', return_value={'metadata': {'labels': labels}}):
                    with self.assertRaisesRegex(proof.ProofError, 'marker differs'):
                        proof.assert_capacity_marker('dw-negative', storage)


class FakeKubectl:
    def __init__(self):
        self.enforce_denial = True
        self.provider_steering_policy_enabled = not DISABLE_PROVIDER_STEERING_POLICY
        self.candidate_exists = False
        self.object_refs = []
        self.candidate_get_error = None
        self.roles = {
            d['metadata']['name']: d['rules']
            for d in yaml_docs(proof.CAPABILITY / 'rbac/authority-boundary.yaml')
            if d.get('kind') == 'ClusterRole'
        }
        self.subject_roles = {
            f"system:serviceaccount:{s['namespace']}:{s['name']}": d['roleRef']['name']
            for d in proof.authority_identities() if d.get('kind') == 'ClusterRoleBinding'
            for s in d['subjects'] if s['kind'] == 'ServiceAccount'
        }
        self.namespaced_edit_identities = {
            f'system:serviceaccount:{proof.STEERING_NS}:{proof.STEERING_SA}',
            f'system:serviceaccount:{proof.PROOF_NS}:{proof.OPERATOR_SA}',
        }

    def add_observer_mutation(self, api_group, resource, verb):
        role = self.roles['developer-workspace-observer']
        role.append({'apiGroups': [api_group], 'resources': [resource], 'verbs': [verb]})

    def allowed(self, identity, verb, api_group, resource, name=None, namespace=None):
        if api_group == 'kubernetes.m.crossplane.io' and identity in self.namespaced_edit_identities:
            return namespace == proof.STEERING_NS
        role_name = self.subject_roles.get(identity)
        for rule in self.roles.get(role_name, []):
            if api_group not in rule.get('apiGroups', []) and '*' not in rule.get('apiGroups', []):
                continue
            if resource not in rule.get('resources', []) and '*' not in rule.get('resources', []):
                continue
            if verb not in rule.get('verbs', []) and '*' not in rule.get('verbs', []):
                continue
            names = rule.get('resourceNames')
            if names and name not in names:
                continue
            return True
        return False

    def __call__(self, args, *, input_text=None, timeout=120, check=True):
        if args[:2] == ['auth', 'can-i']:
            identity = next(value.removeprefix('--as=') for value in args if value.startswith('--as='))
            verb, target = args[2], args[3]
            target, _, name = target.partition('/')
            resource, _, api_group = target.partition('.')
            subresource = next((value.removeprefix('--subresource=') for value in args if value.startswith('--subresource=')), '')
            if subresource: resource = f'{resource}/{subresource}'
            namespace = None
            if '--namespace' in args:
                namespace = args[args.index('--namespace') + 1]
            allowed = self.allowed(identity, verb, api_group, resource, name or None, namespace)
            return completed(args, 0 if allowed else 1, 'yes\n' if allowed else 'no\n')
        if args[:2] == ['apply', '-f']:
            return completed(args)
        if args[0] in ('create', 'replace'):
            identity = next(value.removeprefix('--as=') for value in args if value.startswith('--as='))
            verb = 'create' if args[0] == 'create' else 'update'
            doc = proof.yaml.safe_load(input_text)
            kind = doc['kind']
            api_group, _, _version = doc['apiVersion'].partition('/')
            resource = {'DeveloperWorkspace': 'developerworkspaces', 'Object': 'objects',
                        'ProviderConfig': 'providerconfigs', 'EnvironmentConfig': 'environmentconfigs'}[kind]
            name = doc.get('metadata', {}).get('name')
            authorization_name = None if verb == 'create' else name
            namespace = doc.get('metadata', {}).get('namespace')
            if not self.allowed(identity, verb, api_group, resource, authorization_name, namespace):
                if identity.endswith(':developer-workspace-observer') and not self.enforce_denial:
                    return completed(args)
                error = (f'Error from server (Forbidden): {resource} is forbidden: User "{identity}" '
                         f'cannot {verb} resource "{resource}" in API group "{api_group}" at the cluster scope\n')
                return completed(args, 1, stderr=error)
            operator = self.allowed(identity, 'update', 'apiextensions.crossplane.io',
                                    'environmentconfigs', 'developer-workspace-profile')
            if (self.provider_steering_policy_enabled and not operator and
                    api_group == 'kubernetes.m.crossplane.io' and resource in ('objects', 'providerconfigs')):
                error = (f'Error from server (Invalid): ValidatingAdmissionPolicy '
                         f'"{proof.STEERING_POLICY}" denied request: only a DeveloperWorkspace operator may '
                         'create or update provider steering resources\n')
                return completed(args, 1, stderr=error)
            return completed(args)
        if args[0] == 'delete':
            return completed(args)
        if args[:2] == ['get', 'crd']:
            name = args[2]
            resource, group = name.split('.', 1)
            kind = {'objects': 'Object', 'providerconfigs': 'ProviderConfig'}[resource]
            return completed(args, stdout=json.dumps({
                'spec': {'scope': 'Namespaced', 'names': {'kind': kind},
                         'versions': [{'name': 'v1alpha1', 'served': True, 'storage': True}]},
            }))
        if len(args) > 1 and (args[1].startswith('objects.kubernetes.m.crossplane.io/') or
                              args[1].startswith('providerconfigs.kubernetes.m.crossplane.io/') or
                              args[1] == 'namespace'):
            return completed(args, 1, stderr='Error from server (NotFound): resource not found\n')
        if len(args) > 1 and args[0] == 'get' and args[1].startswith('developerworkspace/'):
            if self.candidate_get_error:
                return completed(args, 1, stderr=self.candidate_get_error)
            if self.candidate_exists:
                return completed(args, stdout='developerworkspace.workspace.openkubes.io/ws-duplicate-collision\n')
            return completed(args, 1, stderr='Error from server (NotFound): developerworkspaces.workspace.openkubes.io "ws-duplicate-collision" not found\n')
        if args[:2] == ['get', 'objects.kubernetes.crossplane.io']:
            return completed(args, stdout=json.dumps({'items': self.object_refs}))
        raise AssertionError(f'unexpected fake kubectl call: {args}')


class NamespaceProbeKubectl:
    def __init__(self, denial='policy', operator_allowed=True):
        self.denial = denial
        self.operator_allowed = operator_allowed
        self.granted = False
        self.role_deleted = False
        self.binding_deleted = False
        self.calls = []
        self.applied = []
        self.namespace = {
            'apiVersion': 'v1', 'kind': 'Namespace',
            'metadata': {'name': 'dw-a', 'uid': 'namespace-uid', 'resourceVersion': '17',
                         'labels': {proof.WORKSPACE_ID_LABEL: 'ws-a', proof.HOST_USERS_LABEL: 'false',
                                    'kubernetes.io/metadata.name': 'dw-a'}},
            'spec': {'finalizers': ['kubernetes']}, 'status': {'phase': 'Active'},
        }

    @staticmethod
    def identity(args):
        return next((value.removeprefix('--as=') for value in args if value.startswith('--as=')), None)

    def mutation_result(self, args, identity, changed):
        operator = identity and identity.endswith(f':{proof.OPERATOR_SA}')
        if not changed:
            return completed(args)
        if operator and self.operator_allowed:
            return completed(args)
        verb = 'delete' if args[0] == 'delete' else 'update'
        if self.denial == 'forbidden':
            return completed(args, 1, stderr=(
                f'Error from server (Forbidden): namespaces "dw-a" is forbidden: User "{identity}" '
                f'cannot {verb} resource "namespaces" at the cluster scope\n'))
        policy = proof.NAMESPACE_HOST_USERS_POLICY if self.denial == 'policy' else 'wrong-policy'
        reason = ('only the DeveloperWorkspace provider or an operator may delete a protected workspace Namespace'
                  if verb == 'delete' else
                  'only an operator may change workspace identity or host-users Namespace labels')
        return completed(args, 1, stderr=(
            f'Error from server (Invalid): namespaces "dw-a" is forbidden: ValidatingAdmissionPolicy '
            f"'{policy}' denied request: {reason}\n"))

    def __call__(self, args, *, input_text=None, timeout=120, check=True):
        self.calls.append((copy.deepcopy(args), input_text))
        if args[:2] == ['get', 'namespace'] and args[2] == 'dw-a':
            return completed(args, stdout=json.dumps(self.namespace))
        if args[0] == 'get' and len(args) > 1 and args[1] in (
                f'clusterrole/{proof.LABEL_PROBE_ROLE}',
                f'clusterrolebinding/{proof.LABEL_PROBE_BINDING}'):
            deleted = self.role_deleted if args[1].startswith('clusterrole/') else self.binding_deleted
            if not self.granted or deleted:
                return completed(args, 1, stderr='Error from server (NotFound): resource not found\n')
            return completed(args, stdout=args[1] + '\n')
        if args[:2] == ['apply', '-f']:
            self.applied = [doc for doc in proof.yaml.safe_load_all(input_text) if doc]
            self.granted = True
            return completed(args)
        if args[:2] == ['auth', 'can-i']:
            verb, target = args[2], args[3]
            # Real kubectl: subresource only via --subresource; a path-embedded one is never granted.
            resource, _, name = target.partition('/')
            subresource = next((value.removeprefix('--subresource=') for value in args if value.startswith('--subresource=')), '')
            if subresource: resource = f'{resource}/{subresource}'
            allowed = self.granted and name == 'dw-a' and (
                (resource == 'namespaces' and verb in ('get', 'update', 'patch', 'delete')) or
                (resource in ('namespaces/status', 'namespaces/finalize') and verb == 'update'))
            return completed(args, 0 if allowed else 1, 'yes\n' if allowed else 'no\n')
        if args[0] == 'label':
            return self.mutation_result(args, self.identity(args), True)
        if args[0] == 'replace':
            document = json.loads(input_text) if '--raw' in args else proof.yaml.safe_load(input_text)
            before = self.namespace['metadata']['labels']
            changed = document.get('metadata', {}).get('labels', {}) != before
            return self.mutation_result(args, self.identity(args), changed)
        if args[:3] == ['delete', 'namespace', 'dw-a'] and '--dry-run=server' in args:
            return self.mutation_result(args, self.identity(args), True)
        if args[:2] == ['delete', 'clusterrolebinding']:
            self.binding_deleted = True
            return completed(args)
        if args[:2] == ['delete', 'clusterrole']:
            self.role_deleted = True
            return completed(args)
        raise AssertionError(f'unexpected namespace probe kubectl call: {args}')


def yaml_docs(path):
    return [d for d in proof.yaml.safe_load_all(path.read_text()) if d]


def sample_snapshot(label='a'):
    namespace = f'dw-{label}'
    xr_uid = f'xr-{label}-uid'
    return {
        'xrUID': xr_uid, 'xrResourceVersion': '10', 'xrGeneration': 1,
        'xrSpec': {'workspaceID': f'ws-{label}'},
        'namespace': {'uid': f'ns-{label}-uid', 'resourceVersion': '20',
                      'content': {'kind': 'Namespace', 'metadata': {'name': namespace}}},
        'objects': {f'object-{label}': {
            'uid': f'object-{label}-uid', 'resourceVersion': '30', 'generation': 1,
            'metadata': {'name': f'object-{label}', 'uid': f'object-{label}-uid',
                         'labels': {'crossplane.io/composite': f'ws-{label}-xr'},
                         'annotations': {'example': label}, 'finalizers': ['example/finalizer'],
                         'creationTimestamp': '2026-10-13T00:00:00Z', 'generation': 1,
                         'deletionTimestamp': None},
            'ownerReferences': [{'uid': xr_uid, 'controller': True}],
            'spec': {'forProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace}}}},
        }},
        'resources': {f'Namespace/{namespace}': {
            'uid': f'ns-{label}-uid', 'resourceVersion': '20',
            'content': {'kind': 'Namespace', 'metadata': {'name': namespace}},
        }, f'Deployment/workspace-{label}': {
            'uid': f'deployment-{label}-uid', 'resourceVersion': '40',
            'content': {'kind': 'Deployment', 'metadata': {'name': f'workspace-{label}', 'namespace': namespace},
                        'spec': {'replicas': 1}},
        }},
    }


def authority_fixture(include_group=True):
    """Independent source-based RBAC fixture, not a copy of the expected-set function."""
    roles = []
    bindings = []

    def grant(name, subjects, rules, **extra):
        roles.append({'kind': 'ClusterRole', 'metadata': {'name': name}, 'rules': rules, **extra})
        bindings.append({'kind': 'ClusterRoleBinding', 'metadata': {'name': name},
                         'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': name},
                         'subjects': subjects})

    wildcard = [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['*']}]
    steering = [{'apiGroups': [group], 'resources': [resource], 'verbs': ['*']}
                for group, resource, _scope in proof.AUTHORITY_RESOURCES.values()]
    grant('cluster-admin', [{'kind': 'Group', 'name': 'system:masters'}], wildcard)
    grant('system:controller:generic-garbage-collector',
          [{'kind': 'ServiceAccount', 'name': 'generic-garbage-collector', 'namespace': 'kube-system'}],
          [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['get', 'list', 'watch', 'update', 'patch', 'delete']}])
    grant('system:controller:namespace-controller',
          [{'kind': 'ServiceAccount', 'name': 'namespace-controller', 'namespace': 'kube-system'}],
          [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['get', 'list', 'watch', 'delete', 'deletecollection']}])
    grant('system:controller:clusterrole-aggregation-controller',
          [{'kind': 'ServiceAccount', 'name': 'clusterrole-aggregation-controller', 'namespace': 'kube-system'}],
          [{'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterroles'],
            'verbs': ['escalate', 'get', 'list', 'watch', 'update', 'patch']}])
    for controller in ('daemon-set-controller', 'job-controller', 'persistent-volume-binder',
                       'replicaset-controller', 'replication-controller', 'statefulset-controller'):
        grant(f'system:controller:{controller}',
              [{'kind': 'ServiceAccount', 'name': controller, 'namespace': 'kube-system'}],
              [{'apiGroups': [''], 'resources': ['pods'], 'verbs': ['create']}])
    grant('system:controller:service-account-controller',
          [{'kind': 'ServiceAccount', 'name': 'service-account-controller', 'namespace': 'kube-system'}],
          [{'apiGroups': [''], 'resources': ['serviceaccounts'], 'verbs': ['create']}])
    grant('system:controller:resourcequota-controller',
          [{'kind': 'ServiceAccount', 'name': 'resourcequota-controller', 'namespace': 'kube-system'}],
          [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['list', 'watch']}])
    grant('system:kube-controller-manager', [{'kind': 'User', 'name': 'system:kube-controller-manager'}], [
        {'apiGroups': [''], 'resources': ['secrets', 'serviceaccounts'], 'verbs': ['create']},
        {'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['get']},
        {'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['list', 'watch']},
        {'apiGroups': [''], 'resources': ['serviceaccounts/token'], 'verbs': ['create']},
    ])
    # Server-materialized aggregate rules are authoritative even if selectors match nothing.
    aggregation = {'aggregationRule': {'clusterRoleSelectors': [{'matchLabels': {'unused': 'true'}}]}}
    grant('crossplane', [{'kind': 'ServiceAccount', 'name': 'crossplane', 'namespace': 'crossplane-system'}],
          [*steering,
           {'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
           {'apiGroups': [''], 'resources': ['serviceaccounts'], 'verbs': ['*']}], **aggregation)
    if include_group:
        grant('crossplane-admin', [{'kind': 'Group', 'name': 'crossplane:masters'}],
              [*steering,
               {'apiGroups': [''], 'resources': ['secrets', 'namespaces'], 'verbs': ['*']},
               {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterrolebindings', 'rolebindings'], 'verbs': ['*']}],
              **aggregation)
    grant('crossplane-rbac-manager', [{'kind': 'ServiceAccount', 'name': 'rbac-manager', 'namespace': 'crossplane-system'}],
          [{'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterroles', 'roles'],
            'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'escalate']},
           {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterroles'], 'verbs': ['bind']},
           {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterrolebindings'], 'verbs': ['*']}])
    provider_rules = [{'apiGroups': [proof.AUTHORITY_RESOURCES[kind][0]],
                       'resources': [proof.AUTHORITY_RESOURCES[kind][1]],
                       'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch']}
                      for kind in sorted(proof.PROVIDER_SYSTEM_RESOURCES)]
    grant('provider-system', [{'kind': 'ServiceAccount', 'name': 'developer-workspace-provider-kubernetes',
                               'namespace': 'crossplane-system'}],
          [*provider_rules,
           {'apiGroups': [''], 'resources': ['serviceaccounts'],
            'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']},
           {'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['*']}])
    grant('cilium-operator', [{'kind': 'ServiceAccount', 'name': 'cilium-operator', 'namespace': 'kube-system'}],
          [{'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['get', 'list', 'watch']}])
    roles.extend(yaml_docs(proof.CAPABILITY / 'rbac/authority-boundary.yaml'))
    bindings.extend(d for d in proof.authority_identities() if d['kind'] == 'ClusterRoleBinding')
    local_role = {'kind': 'Role', 'metadata': {'name': 'local-path-provisioner-role', 'namespace': 'local-path-storage'},
                  'rules': [{'apiGroups': [''], 'resources': ['pods'], 'verbs': ['create']}]}
    local_binding = {'kind': 'RoleBinding', 'metadata': {'name': 'local-path-provisioner-bind', 'namespace': 'local-path-storage'},
                     'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': local_role['metadata']['name']},
                     'subjects': [{'kind': 'ServiceAccount', 'name': 'local-path-provisioner-service-account', 'namespace': 'local-path-storage'}]}
    return {'clusterroles': roles, 'clusterrolebindings': bindings, 'roles': [local_role], 'rolebindings': [local_binding]}


class AuthorityWhoCanTest(unittest.TestCase):
    def setUp(self):
        self.original_get_json = proof.get_json
        self.fixture = authority_fixture()
        self.scopes = {f'{resource}.{group}': scope
                       for group, resource, scope in proof.AUTHORITY_RESOURCES.values()}
        self.reads = []
        def fake_get_json(args):
            self.reads.append(args)
            if args[:2] == ['get', 'crd']:
                return {'spec': {'scope': self.scopes[args[2]]}}
            return {'items': copy.deepcopy(self.fixture[args[1]])}
        proof.get_json = fake_get_json

    def tearDown(self):
        proof.get_json = self.original_get_json

    def add_binding(self, role, subject, kind='ClusterRoleBinding', namespace=None):
        binding = {'kind': kind, 'metadata': {'name': 'extra-binding'},
                   'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': role},
                   'subjects': [subject]}
        if namespace:
            binding['metadata']['namespace'] = namespace
        self.fixture['clusterrolebindings' if kind == 'ClusterRoleBinding' else 'rolebindings'].append(binding)
        return binding

    def test_expected_subjects_pass_with_or_without_default_group(self):
        for include_group in (True, False):
            self.fixture = authority_fixture(include_group)
            result = proof.prove_authority_who_can()
            self.assertEqual(include_group, result['defaultCrossplaneGroupBindingPresent'])
            self.assertEqual([], result['nonEffectiveRoleBindings'])
            self.assertEqual([], result['effectiveRoleBindings'])
            self.assertEqual({'clusterroles', 'clusterrolebindings', 'roles', 'rolebindings'},
                             {args[1] for args in self.reads if args[1] != 'crd'})
            self.assertTrue(all('--all-namespaces' in args for args in self.reads if args[1] in ('roles', 'rolebindings')))
            object_holders = result['holders']['Object']
            provider = {'kind': 'ServiceAccount', 'name': 'developer-workspace-provider-kubernetes', 'namespace': 'crossplane-system'}
            self.assertIn(provider, object_holders['create'])
            self.assertNotIn(provider, object_holders['delete'])
            gc = {'kind': 'ServiceAccount', 'name': 'generic-garbage-collector', 'namespace': 'kube-system'}
            nc = {'kind': 'ServiceAccount', 'name': 'namespace-controller', 'namespace': 'kube-system'}
            self.assertNotIn(gc, object_holders['create'])
            self.assertIn(gc, object_holders['update'])
            self.assertNotIn(nc, object_holders['patch'])
            self.assertIn(nc, object_holders['delete'])
            self.assertIn(nc, object_holders['deletecollection'])
            operator = {'kind': 'ServiceAccount', 'name': proof.OPERATOR_SA, 'namespace': proof.PROOF_NS}
            self.assertNotIn(operator, object_holders['deletecollection'])
            self.assertNotIn(operator, result['holders']['NamespacedObject']['create'])
            self.assertIn(provider, result['holders']['NamespacedObject']['create'])
            self.assertEqual('Namespaced', result['scopes']['NamespacedObject'])
            self.assertEqual('Cluster', result['scopes']['ClusterProviderConfig'])
            controller = {'kind': 'ServiceAccount', 'name': 'crossplane', 'namespace': 'crossplane-system'}
            self.assertIn(controller, result['indirectHolders']['impersonate-serviceaccounts'])
            self.assertNotIn(controller, result['indirectHolders']['impersonate-users'])
        print('CONTROL PASS: complete expected sets, optional default group, materialized aggregates and provider delete asymmetry')

    def test_extra_object_create_via_each_wildcard_fails(self):
        for rule in (
            {'apiGroups': ['*'], 'resources': ['objects'], 'verbs': ['create']},
            {'apiGroups': ['kubernetes.crossplane.io'], 'resources': ['*'], 'verbs': ['create']},
            {'apiGroups': ['kubernetes.crossplane.io'], 'resources': ['objects'], 'verbs': ['*']},
            {'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['*']},
        ):
            self.fixture = authority_fixture()
            self.fixture['clusterroles'].append({'kind': 'ClusterRole', 'metadata': {'name': 'wildcard-extra'}, 'rules': [rule]})
            self.add_binding('wildcard-extra', {'kind': 'User', 'name': 'unexpected-object-creator'})
            with self.subTest(rule=rule):
                with self.assertRaisesRegex(proof.ProofError, 'Object/create: extra=.*unexpected-object-creator') as rejected:
                    proof.prove_authority_who_can()
                print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_admin_edit_aggregate_and_named_grants_cannot_hide_extra_subjects(self):
        for role in ('admin', 'edit', 'named-config-editor'):
            self.fixture = authority_fixture()
            rule = {'apiGroups': ['apiextensions.crossplane.io'], 'resources': ['environmentconfigs'], 'verbs': ['patch']}
            if role == 'named-config-editor':
                rule['resourceNames'] = ['some-other-profile']
            self.fixture['clusterroles'].append({'kind': 'ClusterRole', 'metadata': {'name': role}, 'rules': [rule],
                                                'aggregationRule': {'clusterRoleSelectors': []}})
            self.add_binding(role, {'kind': 'Group', 'name': 'unexpected-config-editors'})
            with self.subTest(role=role):
                with self.assertRaisesRegex(proof.ProofError, 'EnvironmentConfig/patch: extra=.*unexpected-config-editors') as rejected:
                    proof.prove_authority_who_can()
                print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_rolebinding_is_effective_only_for_namespaced_resources(self):
        direct_rules = [{'apiGroups': [group], 'resources': [resource], 'verbs': list(proof.AUTHORITY_VERBS)}
                        for group, resource, _scope in proof.AUTHORITY_RESOURCES.values()]
        self.fixture['clusterroles'].append({'kind': 'ClusterRole', 'metadata': {'name': 'steering-only'}, 'rules': direct_rules})
        self.add_binding('steering-only', {'kind': 'ServiceAccount', 'name': 'namespace-only', 'namespace': 'team'}, 'RoleBinding', 'team')
        with self.assertRaisesRegex(
                proof.ProofError,
                'NamespacedObject/create: extra=.*namespace-only') as rejected:
            proof.prove_authority_who_can()
        print(f'CONTROL FAILS AS EXPECTED: namespaced RoleBinding is an effective extra holder: {rejected.exception}')

        # With only cluster-scoped rules, the same RoleBinding grants nothing and is reported.
        self.fixture = authority_fixture()
        cluster_rules = [{'apiGroups': [group], 'resources': [resource], 'verbs': list(proof.AUTHORITY_VERBS)}
                         for group, resource, scope in proof.AUTHORITY_RESOURCES.values() if scope == 'Cluster']
        self.fixture['clusterroles'].append({'kind': 'ClusterRole', 'metadata': {'name': 'cluster-steering-only'},
                                             'rules': cluster_rules})
        self.add_binding('cluster-steering-only',
                         {'kind': 'ServiceAccount', 'name': 'namespace-only', 'namespace': 'team'},
                         'RoleBinding', 'team')
        result = proof.prove_authority_who_can()
        self.assertEqual(len(cluster_rules) * len(proof.AUTHORITY_VERBS), len(result['nonEffectiveRoleBindings']))
        self.assertTrue(all('cluster-scoped' in entry['reason'] for entry in result['nonEffectiveRoleBindings']))
        self.assertEqual([], result['effectiveRoleBindings'])
        print('CONTROL PASS: the same RoleBinding is non-effective for cluster-scoped kinds and is reported')

    def test_deletecollection_removal_fails(self):
        role = next(r for r in self.fixture['clusterroles']
                    if r['metadata']['name'] == 'system:controller:namespace-controller')
        role['rules'][0]['verbs'].remove('deletecollection')
        with self.assertRaisesRegex(proof.ProofError, 'deletecollection:.*missing=.*namespace-controller') as rejected:
            proof.prove_authority_who_can()
        print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_extra_impersonate_holder_fails(self):
        self.fixture['clusterroles'].append({
            'kind': 'ClusterRole', 'metadata': {'name': 'unexpected-impersonator'},
            'rules': [{'apiGroups': [''], 'resources': ['users', 'groups', 'serviceaccounts'], 'verbs': ['impersonate']}],
        })
        self.add_binding('unexpected-impersonator', {'kind': 'User', 'name': 'unexpected-impersonator'})
        with self.assertRaisesRegex(proof.ProofError, 'impersonate-users: extra=.*unexpected-impersonator') as rejected:
            proof.prove_authority_who_can()
        print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_every_indirect_authority_row_rejects_an_extra_holder(self):
        for name, (group, resource, verb, _scope) in proof.INDIRECT_AUTHORITY.items():
            self.fixture = authority_fixture()
            role_name = f'unexpected-{name}'
            self.fixture['clusterroles'].append({
                'kind': 'ClusterRole', 'metadata': {'name': role_name},
                'rules': [{'apiGroups': [group], 'resources': [resource], 'verbs': [verb]}],
            })
            self.add_binding(role_name, {'kind': 'User', 'name': role_name})
            with self.subTest(authority=name):
                with self.assertRaisesRegex(proof.ProofError, rf'{name}: extra=.*{role_name}') as rejected:
                    proof.prove_authority_who_can()
                print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_local_quota_provisioner_is_expected_only_with_its_exact_binding(self):
        provisioner = {'kind': 'ServiceAccount', 'name': 'ok-storage-local-quota-provisioner',
                       'namespace': 'ok-storage-local-quota'}
        role = {'kind': 'ClusterRole', 'metadata': {'name': 'ok-storage-local-quota-provisioner'},
                'rules': [{'apiGroups': ['*'], 'resources': ['namespaces', 'pods', 'events', 'endpoints'],
                           'verbs': ['*']}]}
        self.fixture = authority_fixture()
        self.fixture['clusterroles'].append(role)
        self.add_binding('ok-storage-local-quota-provisioner', provisioner)['metadata']['name'] = 'ok-storage-local-quota-provisioner'
        result = proof.prove_authority_who_can()
        self.assertTrue(result['localQuotaProvisionerBindingPresent'])
        print('CONTROL PASS: the exact ok-storage binding makes its provisioner an expected Pod creator')
        # The same grant under any other binding shape is an unexpected holder.
        self.fixture = authority_fixture()
        self.fixture['clusterroles'].append(role)
        self.add_binding('ok-storage-local-quota-provisioner', provisioner)['metadata']['name'] = 'ok-storage-local-quota-provisioner'
        self.fixture['clusterrolebindings'][-1]['subjects'].append({'kind': 'User', 'name': 'extra-user'})
        with self.assertRaisesRegex(proof.ProofError, r'create-pods-crossplane-system: extra=') as rejected:
            proof.prove_authority_who_can()
        print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_subresource_and_resource_name_matching_matches_kubernetes(self):
        named_token = {'apiGroups': [''], 'resources': ['*/token'], 'verbs': ['create'],
                       'resourceNames': ['crossplane']}
        unsupported_prefix = {'apiGroups': [''], 'resources': ['serviceaccounts/*'], 'verbs': ['create']}
        named_serviceaccount = {'apiGroups': [''], 'resources': ['serviceaccounts'], 'verbs': ['create'],
                                'resourceNames': ['crossplane']}
        named_secret_list = {'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['list'],
                             'resourceNames': ['crossplane-root-ca']}
        self.assertTrue(proof.authority_rule_matches(named_token, '', 'serviceaccounts/token', 'create'))
        self.assertFalse(proof.authority_rule_matches(unsupported_prefix, '', 'serviceaccounts/token', 'create'))
        self.assertFalse(proof.authority_rule_matches(named_serviceaccount, '', 'serviceaccounts', 'create'))
        self.assertTrue(proof.authority_rule_matches(named_secret_list, '', 'secrets', 'list'))
        print('CONTROL PASS: */token and named list match; serviceaccounts/* and named top-level create do not')

    def test_named_secret_list_holder_is_not_hidden(self):
        role_name = 'named-secret-lister'
        self.fixture['clusterroles'].append({
            'kind': 'ClusterRole', 'metadata': {'name': role_name},
            'rules': [{'apiGroups': [''], 'resources': ['secrets'], 'verbs': ['list'],
                       'resourceNames': ['named-secret']}],
        })
        self.add_binding(role_name, {'kind': 'User', 'name': role_name}, 'RoleBinding', 'crossplane-system')
        with self.assertRaisesRegex(
                proof.ProofError,
                'list-secrets-crossplane-system: extra=.*named-secret-lister') as rejected:
            proof.prove_authority_who_can()
        print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_rolebinding_to_clusterrole_can_grant_bind_clusterroles_in_any_namespace(self):
        for namespace in ('crossplane-system', 'team'):
            self.fixture = authority_fixture()
            role_name = f'{namespace}-clusterrole-grantor'
            self.fixture['clusterroles'].append({
                'kind': 'ClusterRole', 'metadata': {'name': role_name},
                'rules': [{'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['clusterroles'],
                           'verbs': ['bind'], 'resourceNames': ['admin']}],
            })
            self.add_binding(role_name, {'kind': 'User', 'name': role_name}, 'RoleBinding', namespace)
            with self.subTest(namespace=namespace):
                with self.assertRaisesRegex(
                        proof.ProofError,
                        rf'bind-clusterroles: extra=.*{role_name}') as rejected:
                    proof.prove_authority_who_can()
                print(f'CONTROL FAILS AS EXPECTED: {rejected.exception}')

    def test_serviceaccount_subject_requires_explicit_namespace(self):
        with self.assertRaisesRegex(proof.ProofError, 'has no namespace'):
            proof.authority_subject({'kind': 'ServiceAccount', 'name': 'ambiguous'}, 'binding-namespace')
        print('CONTROL FAILS AS EXPECTED: binding namespace is not substituted for a ServiceAccount subject namespace')

    def test_rolebinding_scope_is_all_namespaces_only_for_declared_rows(self):
        role = {'kind': 'Role', 'metadata': {'name': 'team-authority', 'namespace': 'team'},
                'rules': [
                    {'apiGroups': [''], 'resources': ['serviceaccounts'], 'verbs': ['impersonate']},
                    {'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['roles'], 'verbs': ['bind']},
                    {'apiGroups': [''], 'resources': ['pods'], 'verbs': ['create']},
                ]}
        self.fixture['roles'].append(role)
        binding = self.add_binding('team-authority', {'kind': 'User', 'name': 'team-authority'}, 'RoleBinding', 'team')
        binding['roleRef']['kind'] = 'Role'
        with self.assertRaises(proof.ProofError) as rejected:
            proof.prove_authority_who_can()
        message = str(rejected.exception)
        self.assertIn('impersonate-serviceaccounts: extra=', message)
        self.assertIn('bind-roles: extra=', message)
        self.assertNotIn('create-pods-crossplane-system: extra=', message)
        print('CONTROL FAILS AS EXPECTED: a team RoleBinding counts for all-namespace SA impersonation/Role bind but not crossplane-system Pod create')

    def test_installed_crd_scope_must_match_declared_scope(self):
        self.scopes['objects.kubernetes.crossplane.io'] = 'Namespaced'
        with self.assertRaisesRegex(proof.ProofError, 'Object must be Cluster, got Namespaced'):
            proof.prove_authority_who_can()
        self.scopes['objects.kubernetes.crossplane.io'] = 'Cluster'
        self.scopes['objects.kubernetes.m.crossplane.io'] = 'Cluster'
        with self.assertRaisesRegex(proof.ProofError, 'NamespacedObject must be Namespaced, got Cluster'):
            proof.prove_authority_who_can()
        print('CONTROL FAILS AS EXPECTED: installed CRD scope drift is rejected for both cluster and namespaced kinds')

    def test_missing_expected_subject_or_changed_default_group_fails(self):
        self.fixture['clusterrolebindings'] = [b for b in self.fixture['clusterrolebindings'] if b['metadata']['name'] != 'crossplane']
        with self.assertRaisesRegex(proof.ProofError, 'missing=.*crossplane'):
            proof.prove_authority_who_can()
        self.fixture = authority_fixture()
        binding = next(b for b in self.fixture['clusterrolebindings'] if b['metadata']['name'] == 'crossplane-admin')
        binding['subjects'] = [{'kind': 'Group', 'name': 'unexpected-default-group'}]
        with self.assertRaisesRegex(proof.ProofError, 'unexpected-default-group'):
            proof.prove_authority_who_can()
        print('CONTROL FAILS AS EXPECTED: missing expected controller or altered default group fails equality')


class RunPreexistingObjectsTest(unittest.TestCase):
    """run() deletes its fixtures by name in cleanup, so it must refuse to start over any of them."""
    def test_run_refuses_each_preexisting_cleanup_target_before_creating_anything(self):
        targets = [('namespace', proof.PROOF_NS), ('namespace', 'dw-ok175-squat'), ('namespace', proof.STEERING_NS),
                   ('environmentconfig', 'developer-workspace-profile'),
                   ('clusterrolebinding', proof.OPERATOR_BINDING), ('clusterrolebinding', proof.OBSERVER_BINDING)]
        for present in targets:
            calls = []
            def kubectl(args, **_kwargs):
                calls.append(args)
                if args[0] == 'get' and tuple(args[1:3]) == present:
                    return subprocess.CompletedProcess(args, 0, stdout='{}', stderr='')
                if args[0] == 'get':
                    return subprocess.CompletedProcess(args, 1, stdout='', stderr=f'Error from server (NotFound): {args[1]} "{args[2]}" not found')
                raise AssertionError(f'run() went past its refusals: {args}')
            stubs = {'storage_inputs': lambda: {}, 'target': lambda: {}, 'implementation': lambda _clean: {},
                     'image': lambda _name: 'registry.example/x@sha256:' + 'c' * 64,
                     'registry_inputs': lambda _image: (False, '', '', ''),
                     'get_json': lambda args: {'items': []}, 'kubectl': kubectl,
                     'fixture_setup': lambda *a, **k: (_ for _ in ()).throw(AssertionError('fixture_setup reached'))}
            with self.subTest(present=present), contextlib.ExitStack() as stack:
                for attr, value in stubs.items(): stack.enter_context(patch.object(proof, attr, value))
                stack.enter_context(patch.object(proof.spike, 'tls_material', lambda: {}))
                with self.assertRaisesRegex(proof.ProofError, f'{present[0]}/{present[1]} already exists'):
                    proof.run(type('Args', (), {'require_clean': False})())
                self.assertTrue(all(call[0] == 'get' for call in calls), calls)
        print('CONTROL FAILS AS EXPECTED: run() refuses every pre-existing object its cleanup would delete by name')


class KubectlFlagTest(unittest.TestCase):
    def test_can_i_never_embeds_a_subresource_in_the_resource_path(self):
        # kubectl auth can-i reads 'pods/ephemeralcontainers' as a Pod named ephemeralcontainers.
        source = Path(proof.__file__).read_text()
        for embedded in ("'pods/ephemeralcontainers', False", "'namespaces/status'", "'namespaces/finalize'"):
            self.assertNotIn("assert_can_i(identity, 'update', " + embedded, source)

    def test_no_kubectl_call_uses_a_nonexistent_preconditions_flag(self):
        # The fake kubectl accepts any flag; the real one rejects --preconditions (seen live).
        source = (Path(proof.__file__)).read_text()
        self.assertNotIn("'--preconditions", source)
        self.assertNotIn("f'--preconditions", source)


class ReconcileProofAssertionsTest(unittest.TestCase):
    def setUp(self):
        self.original_kubectl = proof.kubectl
        self.fake = FakeKubectl()
        proof.kubectl = self.fake

    def tearDown(self):
        proof.kubectl = self.original_kubectl

    def test_server_dry_run_denial_and_allowed_control(self):
        docs = (
            ('developerworkspaces', {'apiVersion': 'workspace.openkubes.io/v1alpha1', 'kind': 'DeveloperWorkspace', 'metadata': {'name': 'ws-a-xr'}}),
            ('objects', {'apiVersion': 'kubernetes.crossplane.io/v1alpha2', 'kind': 'Object', 'metadata': {'name': 'object-a'}}),
            ('providerconfigs', {'apiVersion': 'kubernetes.crossplane.io/v1alpha1', 'kind': 'ProviderConfig', 'metadata': {'name': 'in-cluster'}}),
            ('environmentconfigs', {'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig', 'metadata': {'name': 'developer-workspace-profile'}}),
        )
        operator = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-operator'
        observer = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-observer'
        for resource, doc in docs:
            for action in ('create', 'replace'):
                proof.assert_server_dry_run(observer, action, resource, doc, False)
                proof.assert_server_dry_run(operator, action, resource, doc, True)

        # A newly granted mutation must make both production denial checks fail for every
        # resource and verb, including each server-side create/update request.
        groups = {'developerworkspaces': 'workspace.openkubes.io', 'objects': 'kubernetes.crossplane.io',
                  'providerconfigs': 'kubernetes.crossplane.io', 'environmentconfigs': 'apiextensions.crossplane.io'}
        for resource, doc in docs:
            for action in ('create', 'replace'):
                verb = 'create' if action == 'create' else 'update'
                self.fake.add_observer_mutation(groups[resource], resource, verb)
                with self.subTest(resource=resource, verb=verb):
                    with self.assertRaisesRegex(proof.ProofError, f'expected False'):
                        proof.assert_can_i(observer, verb, f'{resource}.{groups[resource]}', False,
                                           doc['metadata']['name'] if verb == 'update' else None)
                    with self.assertRaisesRegex(proof.ProofError, f'denial did not report Forbidden/{verb}/{resource}'):
                        proof.assert_server_dry_run(observer, action, resource, doc, False)
                print(f'CONTROL FAILS AS EXPECTED: observer {verb} {resource}: can-i reports allowed; server request is not Forbidden')
                self.fake.roles['developer-workspace-observer'] = [
                    rule for rule in self.fake.roles['developer-workspace-observer']
                    if not (groups[resource] in rule.get('apiGroups', []) and resource in rule.get('resources', []) and verb in rule.get('verbs', []))
                ]

    def test_can_i_denial_and_disabled_denial(self):
        operator = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-operator'
        observer = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-observer'
        proof.assert_can_i(operator, 'create', 'objects.kubernetes.crossplane.io', True)
        proof.assert_can_i(observer, 'create', 'objects.kubernetes.crossplane.io', False)
        with self.assertRaisesRegex(proof.ProofError, 'expected False'):
            proof.assert_can_i(operator, 'create', 'objects.kubernetes.crossplane.io', False)

    def test_namespace_label_guard_validator_rejects_permissive_false_green(self):
        message = (f'Error from server (Invalid): namespaces "dw-a" is forbidden: ValidatingAdmissionPolicy '
                   f"'{proof.NAMESPACE_HOST_USERS_POLICY}' with binding '{proof.NAMESPACE_HOST_USERS_POLICY}' denied request: "
                   'only an operator may change workspace identity or host-users Namespace labels')
        delete_message = (f'Error from server (Invalid): namespaces "dw-a" is forbidden: ValidatingAdmissionPolicy '
                          f"'{proof.NAMESPACE_HOST_USERS_POLICY}' denied request: only the DeveloperWorkspace provider "
                          'or an operator may delete a protected workspace Namespace')
        operations = ('remove', 'alter', *proof.NAMESPACE_MUTATION_OPERATIONS)
        denied = {f'{identity}-{operation}': completed(['label'], 1,
                                                       stderr=delete_message if operation == 'delete' else message)
                  for identity in ('workspace', 'observer') for operation in operations}
        allowed = {f'operator-{operation}': completed(['label']) for operation in operations}
        allowed.update({f'{identity}-preserve': completed(['replace'])
                        for identity in ('workspace', 'observer', 'operator')})
        before = {'metadata': {'uid': 'namespace-uid', 'resourceVersion': '17',
                               'labels': {proof.HOST_USERS_LABEL: 'false', proof.WORKSPACE_ID_LABEL: 'ws-a'}}}
        result = proof.validate_namespace_label_admission('enforced', before, copy.deepcopy(before), denied, allowed)
        self.assertEqual(sorted(denied), result['denied'])
        without_control = {key: value for key, value in allowed.items() if key != 'workspace-preserve'}
        with self.assertRaisesRegex(proof.ProofError, 'incomplete Namespace label controls'):
            proof.validate_namespace_label_admission('enforced', before, copy.deepcopy(before), denied, without_control)
        denied['workspace-remove'] = completed(['label'])
        with self.assertRaisesRegex(proof.ProofError, 'workspace-remove was not denied'):
            proof.validate_namespace_label_admission('enforced', before, copy.deepcopy(before), denied, allowed)
        print('CONTROL FAILS AS EXPECTED: a permissive label guard makes the denial validator fail')

        outcomes = {
            'drop': {'synced': False, 'message': message.replace('only an operator may change workspace identity or host-users Namespace labels',
                                                                 'the DeveloperWorkspace provider must preserve the workspace identity and render host-users from developer-workspace-profile')},
            'alter': {'synced': False, 'message': message.replace('only an operator may change workspace identity or host-users Namespace labels',
                                                                  'the DeveloperWorkspace provider must preserve the workspace identity and render host-users from developer-workspace-profile')},
            'preserve': {'synced': True, 'message': ''},
        }
        labels = {proof.HOST_USERS_LABEL: 'false', proof.WORKSPACE_ID_LABEL: 'ws-a'}
        proof.validate_provider_label_reconcile(outcomes, labels, copy.deepcopy(labels), 'false')
        outcomes['alter'] = {'synced': True, 'message': ''}
        with self.assertRaisesRegex(proof.ProofError, 'provider alter Object did not fail'):
            proof.validate_provider_label_reconcile(outcomes, labels, copy.deepcopy(labels), 'false')
        print('CONTROL FAILS AS EXPECTED: a permissive provider label path makes the reconcile validator fail')

    def test_namespace_label_probes_drive_every_update_subresource_and_delete_cell(self):
        original_helper = proof.namespace_mutation_documents
        try:
            fake = NamespaceProbeKubectl()
            proof.kubectl = fake
            result = proof.namespace_label_probes('dw-a', 'enforced')
            self.assertTrue(result['dryRunUnchanged'])
            self.assertEqual('namespace-uid', result['namespaceUID'])
            role = next(doc for doc in fake.applied if doc['kind'] == 'ClusterRole')
            self.assertEqual([
                {'apiGroups': [''], 'resources': ['namespaces'], 'resourceNames': ['dw-a'],
                 'verbs': ['get', 'update', 'patch', 'delete']},
                {'apiGroups': [''], 'resources': ['namespaces/status', 'namespaces/finalize'],
                 'resourceNames': ['dw-a'], 'verbs': ['update']},
            ], role['rules'])
            raw_paths = {args[2] for args, _input in fake.calls if args[:2] == ['replace', '--raw']}
            self.assertEqual({'/api/v1/namespaces/dw-a/status?dryRun=All',
                              '/api/v1/namespaces/dw-a/finalize?dryRun=All'}, raw_paths)
            self.assertEqual(3, sum(args[:3] == ['delete', 'namespace', 'dw-a'] and '--dry-run=server' in args
                                    for args, _input in fake.calls))
            self.assertEqual(6, sum(args[:2] == ['label', 'namespace'] for args, _input in fake.calls))
            self.assertTrue(fake.role_deleted and fake.binding_deleted)

            def missing_status(document):
                mutations = original_helper(document)
                mutations.pop('status-drop-both')
                return mutations
            proof.kubectl = NamespaceProbeKubectl()
            with patch.object(proof, 'namespace_mutation_documents', missing_status):
                with self.assertRaisesRegex(proof.ProofError, 'incomplete Namespace label denials'):
                    proof.namespace_label_probes('dw-a', 'enforced')
            print('CONTROL FAILS AS EXPECTED: omitting a namespace/status mutation cell fails the probe matrix')

            for denial, message in (('wrong-policy', 'was not denied specifically'),
                                    ('forbidden', 'denied by RBAC instead')):
                proof.kubectl = NamespaceProbeKubectl(denial=denial)
                with self.subTest(denial=denial):
                    with self.assertRaisesRegex(proof.ProofError, message):
                        proof.namespace_label_probes('dw-a', 'enforced')
            proof.kubectl = NamespaceProbeKubectl(operator_allowed=False)
            with self.assertRaisesRegex(proof.ProofError, 'operator-.* allowed control failed'):
                proof.namespace_label_probes('dw-a', 'enforced')
            print('CONTROL FAILS AS EXPECTED: wrong-policy, RBAC Forbidden, and denied operator controls cannot satisfy the Namespace mutation proof')
        finally:
            proof.kubectl = self.fake

    def test_ephemeralcontainers_validator_rejects_permissive_false_green(self):
        denial = completed(['replace'], 1, stderr=(
            f'Error from server (Invalid): pods "legacy" is forbidden: ValidatingAdmissionPolicy '
            f"'{proof.POD_USER_NAMESPACE_POLICY}' denied request: Pods in this workspace Namespace must set spec.hostUsers to false"))
        authority = {name: completed(['replace'], 1, stderr=(
            f'Error from server (Forbidden): pods "control" is forbidden: User "{name}" cannot update resource '
            '"pods/ephemeralcontainers" in API group "" in the namespace "probe"'))
                     for name in ('workspace', 'observer')}
        proof.validate_ephemeralcontainers_admission(completed(['replace']), denial, authority,
                                                     {'compliant': True, 'legacy': True})
        with self.assertRaisesRegex(proof.ProofError, 'legacy hostUsers=true Pod'):
            proof.validate_ephemeralcontainers_admission(completed(['replace']), completed(['replace']), authority,
                                                         {'compliant': True, 'legacy': True})
        print('CONTROL FAILS AS EXPECTED: a permissive ephemeralcontainers policy makes the validator fail')

    def test_install_admission_validator_requires_each_guard_and_unrelated_control(self):
        vap = lambda policy, reason: completed(
            ['create'], 1, stderr=f"Error from server (Invalid): forbidden: ValidatingAdmissionPolicy '{policy}' denied request: {reason}")
        outcomes = {
            'provider-preserve': completed(['create']),
            'provider-alter': vap(proof.NAMESPACE_HOST_USERS_POLICY,
                                  'the DeveloperWorkspace provider must preserve the workspace identity and render host-users from developer-workspace-profile'),
            'provider-adopt': vap('developer-workspace-namespace-guard',
                                  'the DeveloperWorkspace provider may change or delete only Namespaces it created for a workspace'),
            'pod-false': completed(['create']),
            'pod-true': vap(proof.POD_USER_NAMESPACE_POLICY,
                            'Pods in this workspace Namespace must set spec.hostUsers to false'),
            'pod-absent': vap(proof.POD_USER_NAMESPACE_POLICY,
                              'Pods in this workspace Namespace must set spec.hostUsers to false'),
            'missing-param': vap(proof.NAMESPACE_HOST_USERS_POLICY, 'no params found'),
            'missing-param-unrelated': completed(['create']),
        }
        proof.validate_install_admission_observation(outcomes)
        for name in ('provider-alter', 'provider-adopt', 'pod-true'):
            mutant = copy.deepcopy(outcomes); mutant[name] = completed(['create'])
            with self.subTest(permissive=name):
                with self.assertRaises(proof.ProofError): proof.validate_install_admission_observation(mutant)
        mutant = copy.deepcopy(outcomes); mutant['missing-param-unrelated'] = vap(proof.NAMESPACE_HOST_USERS_POLICY, 'no params found')
        with self.assertRaisesRegex(proof.ProofError, 'missing-param-unrelated'):
            proof.validate_install_admission_observation(mutant)
        print('CONTROL FAILS AS EXPECTED: each guard denial and the unrelated Namespace allow control are required')

    def test_namespaced_provider_steering_policy_denial_and_operator_control(self):
        result = proof.prove_namespaced_provider_steering_denied()
        self.assertEqual(proof.STEERING_POLICY, result['policy'])
        self.assertEqual(['providerconfigs', 'objects'], result['resources'])
        document = proof.provider_api_document('kubernetes.m.crossplane.io', 'objects',
                                               proof.STEERING_NS, 'provider-steering-probe')
        self.assertEqual({'kind': 'ProviderConfig', 'name': 'provider-steering-probe'},
                         document['spec']['providerConfigRef'])
        nonoperator = f'system:serviceaccount:{proof.STEERING_NS}:{proof.STEERING_SA}'
        proof.assert_can_i(nonoperator, 'create', 'objects.kubernetes.m.crossplane.io', True,
                           namespace=proof.STEERING_NS)
        proof.assert_can_i(nonoperator, 'create', 'objects.kubernetes.m.crossplane.io', False)
        print('CONTROL PASS: namespaced RBAC says yes, the named policy denies real non-operator creates, and the independently defined operator dry-run is admitted')

    def test_can_i_checks_operator_allow_and_observer_mutation_denial_from_role_manifest(self):
        operator = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-operator'
        observer = f'system:serviceaccount:{proof.PROOF_NS}:developer-workspace-observer'
        resources = (('developerworkspaces', 'workspace.openkubes.io'),
                     ('objects', 'kubernetes.crossplane.io'),
                     ('providerconfigs', 'kubernetes.crossplane.io'),
                     ('environmentconfigs', 'apiextensions.crossplane.io'))
        for resource, group in resources:
            for verb in ('create', 'update'):
                named = 'in-cluster' if resource == 'providerconfigs' else 'developer-workspace-profile'
                target = f'{resource}.{group}' + (f'/{named}' if verb == 'update' and resource in ('providerconfigs', 'environmentconfigs') else '')
                proof.assert_can_i(operator, verb, target, True)
                proof.assert_can_i(observer, verb, target, False)
                self.fake.add_observer_mutation(group, resource, verb)
                with self.subTest(resource=resource, verb=verb):
                    with self.assertRaisesRegex(proof.ProofError, 'expected False'):
                        proof.assert_can_i(observer, verb, target, False)
                print(f'CONTROL FAILS AS EXPECTED: observer can-i {verb} {resource}: expected denied, manifest grant returns yes')
                self.fake.roles['developer-workspace-observer'] = [
                    rule for rule in self.fake.roles['developer-workspace-observer']
                    if not (group in rule.get('apiGroups', []) and resource in rule.get('resources', []) and verb in rule.get('verbs', []))
                ]

        # ProviderConfig and EnvironmentConfig reads/writes are name-limited; their
        # separate create rules intentionally have no resourceNames restriction.
        for resource, group, allowed_name in (
            ('providerconfigs', 'kubernetes.crossplane.io', 'in-cluster'),
            ('environmentconfigs', 'apiextensions.crossplane.io', 'developer-workspace-profile'),
        ):
            named_target = f'{resource}.{group}/{allowed_name}'
            other_target = f'{resource}.{group}/ok175-other-name'
            for verb in ('get', 'update', 'patch', 'delete'):
                proof.assert_can_i(operator, verb, named_target, True)
                proof.assert_can_i(operator, verb, other_target, False)
                proof.assert_can_i(observer, verb, named_target, False)
            for verb in ('list', 'watch'):
                proof.assert_can_i(operator, verb, f'{resource}.{group}', False)
                proof.assert_can_i(observer, verb, f'{resource}.{group}', False)
            proof.assert_can_i(operator, 'create', f'{resource}.{group}', True)
            print(f'CONTROL PASS: operator create {resource} is allowed; named get/update/patch/delete are limited to {allowed_name}')
            operator_rules = self.fake.roles['developer-workspace-operator']
            self.fake.roles['developer-workspace-operator'] = [
                rule for rule in operator_rules
                if not (group in rule.get('apiGroups', []) and resource in rule.get('resources', [])
                        and rule.get('verbs') == ['create'] and not rule.get('resourceNames'))
            ]
            with self.assertRaisesRegex(proof.ProofError, 'expected True'):
                proof.assert_can_i(operator, 'create', f'{resource}.{group}', True)
            print(f'CONTROL FAILS AS EXPECTED: removing the separate broad create rule denies operator create {resource}')
            self.fake.roles['developer-workspace-operator'] = operator_rules

        object_resource = 'objects.kubernetes.crossplane.io'
        for verb in ('get', 'list', 'watch'):
            proof.assert_can_i(observer, verb, object_resource, False)
        self.fake.add_observer_mutation('kubernetes.crossplane.io', 'objects', 'get')
        with self.assertRaisesRegex(proof.ProofError, 'expected False'):
            proof.assert_can_i(observer, 'get', object_resource, False)
        print('CONTROL FAILS AS EXPECTED: observer Object read grant makes can-i get objects fail the denial assertion')

    def test_installed_matches_local_checks_generated_crd_guards(self):
        def fixtures():
            capability = proof.CAPABILITY
            read = lambda path: proof.yaml.safe_load((capability / path).read_text())
            read_all = lambda path: [d for d in proof.yaml.safe_load_all((capability / path).read_text()) if d]
            composition = read('composition.yaml')
            xrd = read('xrd.yaml')
            provider_role = next(d for d in read_all('rbac/provider-kubernetes-clusterrole.yaml') if d['kind'] == 'ClusterRole')
            authority_roles = [d for d in read_all('rbac/authority-boundary.yaml') if d]
            version = xrd['spec']['versions'][0]
            crd_name = f"{xrd['spec']['names']['plural']}.{xrd['spec']['group']}"
            generated_crd = {
                'apiVersion': 'apiextensions.k8s.io/v1', 'kind': 'CustomResourceDefinition',
                'metadata': {'name': crd_name},
                'spec': {'versions': [{'name': version['name'], 'schema': {'openAPIV3Schema': copy.deepcopy(version['schema']['openAPIV3Schema'])}}]},
            }
            mapping = {
                ('composition', composition['metadata']['name']): composition,
                ('compositeresourcedefinition', xrd['metadata']['name']): xrd,
                ('crd', crd_name): generated_crd,
                ('clusterrole', provider_role['metadata']['name']): provider_role,
                **{('clusterrole', role['metadata']['name']): role for role in authority_roles},
            }
            for path in proof.ADMISSION_GUARDS:
                policy, bindings = proof.admission_guard_documents(path)
                policy = copy.deepcopy(policy); bindings = copy.deepcopy(bindings)
                policy['metadata']['generation'] = 1
                policy['status'] = {'observedGeneration': 1, 'typeChecking': {}}
                mapping[('validatingadmissionpolicy', policy['metadata']['name'])] = policy
                for binding in bindings:
                    mapping[('validatingadmissionpolicybinding', binding['metadata']['name'])] = binding
            return mapping

        original_get_json = proof.get_json
        current = fixtures()
        def fake_get_json(args):
            key = (args[1], args[2])
            if key not in current: raise proof.ProofError(f'kubectl get {args[1]} failed: NotFound {args[2]}')
            return copy.deepcopy(current[key])
        proof.get_json = fake_get_json
        try:
            generated = current[('crd', 'developerworkspaces.workspace.openkubes.io')]
            generated_schema = generated['spec']['versions'][0]['schema']['openAPIV3Schema']
            root_rule = generated_schema['x-kubernetes-validations'][0]
            spec_rules = generated_schema['properties']['spec']['x-kubernetes-validations']
            immutability_rule = next(rule for rule in spec_rules if rule['message'] == 'spec.workspaceID is immutable')
            workspace_id = generated_schema['properties']['spec']['properties']['workspaceID']

            generated_schema['x-kubernetes-validations'] = []
            with self.assertRaisesRegex(proof.ProofError, 'generated CRD root CEL validations differ'):
                proof.installed_matches_local()
            print('CONTROL FAILS AS EXPECTED: generated CRD missing canonical-name root CEL guard is rejected')
            generated_schema['x-kubernetes-validations'] = [root_rule]

            generated_schema['properties']['spec']['x-kubernetes-validations'] = [
                rule for rule in spec_rules if rule is not immutability_rule
            ]
            with self.assertRaisesRegex(proof.ProofError, 'generated CRD spec CEL validations differ'):
                proof.installed_matches_local()
            print('CONTROL FAILS AS EXPECTED: generated CRD missing spec immutability CEL guard is rejected')
            generated_schema['properties']['spec']['x-kubernetes-validations'] = spec_rules

            workspace_id['maxLength'] -= 1
            with self.assertRaisesRegex(proof.ProofError, 'generated CRD workspaceID maxLength differs'):
                proof.installed_matches_local()
            print('CONTROL FAILS AS EXPECTED: generated CRD workspaceID maxLength drift is rejected')
            workspace_id['maxLength'] += 1

            # The API server materializes harmless defaults. The gate accepts only those exact
            # defaults and still rejects selectors, exclusions and parameter bypasses.
            steering_policy = current[('validatingadmissionpolicy', proof.STEERING_POLICY)]
            steering_binding = current[('validatingadmissionpolicybinding', proof.STEERING_POLICY)]
            steering_policy['spec']['matchConstraints'].update({
                'matchPolicy': 'Equivalent', 'namespaceSelector': {}, 'objectSelector': {},
                'excludeResourceRules': [],
            })
            steering_binding['spec']['matchResources'] = {
                'matchPolicy': 'Equivalent', 'namespaceSelector': {}, 'objectSelector': {},
                'resourceRules': [], 'excludeResourceRules': [],
            }
            proof.installed_matches_local()
            print('CONTROL PASS: generated CRD root/spec CEL and workspaceID maxLength match current XRD')

            for path in proof.ADMISSION_GUARDS:
                policy, bindings = proof.admission_guard_documents(path)
                resources = [('validatingadmissionpolicy', policy['metadata']['name'])]
                resources.extend(('validatingadmissionpolicybinding', binding['metadata']['name']) for binding in bindings)
                for kind, name in resources:
                    saved = current.pop((kind, name))
                    with self.subTest(path=path, missing=kind):
                        with self.assertRaisesRegex(proof.ProofError, 'NotFound'):
                            proof.installed_matches_local()
                    current[(kind, name)] = saved
                print(f'CONTROL FAILS AS EXPECTED: either missing policy resource for {path} closes the XR gate')

            policy_key = ('validatingadmissionpolicy', proof.POD_USER_NAMESPACE_POLICY)
            current[policy_key]['status']['observedGeneration'] = 0
            with self.assertRaisesRegex(proof.ProofError, 'observedGeneration'):
                proof.installed_matches_local()
            current[policy_key]['status']['observedGeneration'] = 1
            current[policy_key]['status']['typeChecking'] = {'expressionWarnings': [{'fieldRef': 'spec.validations[0].expression', 'warning': 'mutant'}]}
            with self.assertRaisesRegex(proof.ProofError, 'type-check warnings'):
                proof.installed_matches_local()
            current[policy_key]['status']['typeChecking'] = {}
            # An in-place update with a clean type check leaves only observedGeneration.
            del current[policy_key]['status']['typeChecking']
            proof.installed_matches_local()
            current[policy_key]['status']['typeChecking'] = {}
            print('CONTROL FAILS AS EXPECTED: stale generation and CEL type warning close the XR gate')

            binding_key = ('validatingadmissionpolicybinding', proof.POD_USER_NAMESPACE_POLICY)
            saved_binding = current.pop(binding_key)
            dispatched = []
            original_kubectl = proof.kubectl
            proof.kubectl = lambda *args, **kwargs: dispatched.append((args, kwargs))
            try:
                doc = {'apiVersion': 'workspace.openkubes.io/v0alpha1', 'kind': 'DeveloperWorkspace',
                       'metadata': {'name': 'ws-gate-xr'}}
                with self.assertRaisesRegex(proof.ProofError, 'NotFound'):
                    proof.gated_xr_request(['create', '-f', '-'], doc)
                self.assertEqual([], dispatched)
            finally:
                proof.kubectl = original_kubectl
                current[binding_key] = saved_binding
            print('CONTROL PASS: missing binding fails before gated_xr_request dispatches kubectl CREATE')

            steering_policy['spec']['matchConstraints']['namespaceSelector'] = {
                'matchLabels': {'policy-bypass': 'true'},
            }
            with self.assertRaisesRegex(proof.ProofError, 'installed admission policy differs from install/provider-steering-guard.yaml'):
                proof.installed_matches_local()
            print('CONTROL FAILS AS EXPECTED: an installed provider guard Namespace selector cannot narrow enforcement')
            steering_policy['spec']['matchConstraints']['namespaceSelector'] = {}
            steering_policy['spec']['paramKind'] = {'apiVersion': 'v1', 'kind': 'ConfigMap'}
            steering_binding['spec']['paramRef'] = {'name': 'missing'}
            steering_binding['spec']['parameterNotFoundAction'] = 'Allow'
            with self.assertRaisesRegex(proof.ProofError, 'installed admission policy differs from install/provider-steering-guard.yaml'):
                proof.installed_matches_local()
            print('CONTROL FAILS AS EXPECTED: installed policy parameterization cannot bypass the provider steering guard')
            steering_policy['spec'].pop('paramKind')
            steering_binding['spec'].pop('paramRef')
            steering_binding['spec'].pop('parameterNotFoundAction')

            proof.installed_matches_local()
            print('CONTROL PASS: generated CRD guards and every admission policy/binding match local files including harmless API defaults')
        finally:
            proof.get_json = original_get_json

    def test_install_orders_admission_receipt_after_every_guard_check_and_never_mints_on_failure(self):
        original_target = proof.target
        original_run = proof.subprocess.run
        original_apply_file = proof.apply_file
        original_kubectl = proof.kubectl
        original_wait_for_admission_policies = proof.wait_for_admission_policies
        original_observe_installed_admission = proof.observe_installed_admission
        original_invalidate_admission_ready = proof.invalidate_admission_ready
        original_publish_admission_ready = proof.publish_admission_ready
        proof.target = lambda: {'context': 'offline'}
        proof.subprocess.run = lambda *args, **kwargs: completed(list(args[0]))
        proof.kubectl = lambda args, **kwargs: completed(args)
        try:
            def exercise(failure=None):
                actions = []
                def apply_file(path):
                    relative = str(path.relative_to(proof.CAPABILITY))
                    actions.append(relative)
                    if failure == relative:
                        raise proof.ProofError(f'forced failure at {relative}')
                def wait_policies():
                    actions.append('wait-for-admission-policies')
                    if failure == 'wait-for-admission-policies': raise proof.ProofError('forced wait failure')
                    return []
                def observe():
                    actions.append('observe-installed-admission')
                    if failure == 'observe-installed-admission': raise proof.ProofError('forced observation failure')
                    return {}
                def invalidate():
                    if not DISABLE_ADMISSION_RECEIPT_ORDERING:
                        actions.append('receipt-invalidated')
                def publish():
                    actions.append('receipt-published')
                    return {'name': proof.render_profile.ADMISSION_READY_NAME,
                            'data': {'guardRevision': proof.render_profile.ADMISSION_GUARD_REVISION}}
                proof.apply_file = apply_file
                proof.wait_for_admission_policies = wait_policies
                proof.observe_installed_admission = observe
                proof.invalidate_admission_ready = invalidate
                proof.publish_admission_ready = publish
                if failure:
                    with self.assertRaises(proof.ProofError):
                        proof.install(None)
                else:
                    proof.install(None)
                return actions

            actions = exercise()
            first_guard = actions.index(proof.ADMISSION_GUARDS[0])
            self.assertLess(actions.index('receipt-invalidated'), first_guard)
            self.assertEqual(list(proof.ADMISSION_GUARDS),
                             [action for action in actions if action in proof.ADMISSION_GUARDS])
            self.assertLess(actions.index('install/provider-steering-guard.yaml'),
                            actions.index('install/providerconfig.yaml'))
            self.assertLess(actions.index('wait-for-admission-policies'),
                            actions.index('observe-installed-admission'))
            self.assertLess(actions.index('observe-installed-admission'), actions.index('receipt-published'))
            self.assertLess(actions.index('receipt-published'), actions.index('xrd.yaml'))
            self.assertLess(actions.index('xrd.yaml'), actions.index('composition.yaml'))

            for failure in (*proof.ADMISSION_GUARDS, 'wait-for-admission-policies', 'observe-installed-admission'):
                with self.subTest(failure=failure):
                    failed_actions = exercise(failure)
                    self.assertIn('receipt-invalidated', failed_actions)
                    self.assertNotIn('receipt-published', failed_actions)
            print('CONTROL FAILS AS EXPECTED: every guard apply/equality/behavior failure leaves the admission receipt absent')
        finally:
            proof.target = original_target
            proof.subprocess.run = original_run
            proof.apply_file = original_apply_file
            proof.kubectl = original_kubectl
            proof.wait_for_admission_policies = original_wait_for_admission_policies
            proof.observe_installed_admission = original_observe_installed_admission
            proof.invalidate_admission_ready = original_invalidate_admission_ready
            proof.publish_admission_ready = original_publish_admission_ready

    def test_admission_receipt_helpers_require_exact_absence_and_readback(self):
        original_kubectl = proof.kubectl
        state = {'present': True, 'document': proof.render_profile.admission_ready_config()}
        calls = []
        def fake_kubectl(args, *, input_text=None, **_kwargs):
            calls.append(args)
            if args[:2] == ['delete', f'environmentconfig/{proof.render_profile.ADMISSION_READY_NAME}']:
                state['present'] = False
                return completed(args)
            if args[:2] == ['get', f'environmentconfig/{proof.render_profile.ADMISSION_READY_NAME}']:
                if not state['present']:
                    return completed(args, 1, stderr='Error from server (NotFound): receipt not found\n')
                return completed(args, stdout=json.dumps(state['document']))
            if args[:2] == ['apply', '-f']:
                state['document'] = proof.yaml.safe_load(input_text)
                state['present'] = True
                return completed(args)
            raise AssertionError(args)
        proof.kubectl = fake_kubectl
        try:
            proof.invalidate_admission_ready()
            observed = proof.publish_admission_ready()
            self.assertEqual({'guardRevision': proof.render_profile.ADMISSION_GUARD_REVISION}, observed['data'])
            self.assertEqual('delete', calls[0][0])

            state['present'] = False
            def forbidden_get(args, **_kwargs):
                if args[0] == 'delete': return completed(args)
                return completed(args, 1, stderr='Error from server (Forbidden): forbidden\n')
            proof.kubectl = forbidden_get
            with self.assertRaisesRegex(proof.ProofError, 'absence was not confirmed by NotFound'):
                proof.invalidate_admission_ready()

            state.update(present=True, document={'metadata': {'name': proof.render_profile.ADMISSION_READY_NAME},
                                                 'data': {'guardRevision': 'wrong'}})
            proof.kubectl = fake_kubectl
            original_apply = proof.apply
            proof.apply = lambda _documents: None
            try:
                with self.assertRaisesRegex(proof.ProofError, 'receipt differs'):
                    proof.publish_admission_ready()
            finally:
                proof.apply = original_apply
            print('CONTROL FAILS AS EXPECTED: Forbidden absence and wrong receipt readback cannot satisfy receipt lifecycle checks')
        finally:
            proof.kubectl = original_kubectl

    def test_receipt_refusal_accepts_only_named_missing_or_revision_errors(self):
        original_kubectl = proof.kubectl
        original_get_json = proof.get_json
        original_composed_objects = proof.composed_objects
        original_wait_until = proof.wait_until
        try:
            for message in (
                    f'{proof.render_profile.ADMISSION_READY_NAME} not found',
                    f'admission installation receipt {proof.render_profile.ADMISSION_READY_NAME} must declare guardRevision=ok185-v1'):
                proof.kubectl = lambda args, **_kwargs: (
                    completed(args, stdout=json.dumps({'metadata': {'uid': 'probe-uid'}})) if args[0] == 'create' else
                    completed(args, 1, stderr='Error from server (NotFound): resource not found\n'))
                proof.get_json = lambda _args, message=message: {
                    'metadata': {'uid': 'probe-uid'},
                    'status': {'conditions': [{'type': 'Synced', 'status': 'False', 'message': message},
                                              {'type': 'Ready', 'status': 'False'}]}}
                proof.composed_objects = lambda _name: []
                proof.wait_until = lambda what, predicate, **_kwargs: proof.expect(predicate(), f'{what} did not refuse')
                result = proof.admission_receipt_refusal('ws-receipt-xr', 'ws-receipt', 'a' * 40, 'dw-')
                self.assertTrue(result['namespaceAbsent'])

            proof.get_json = lambda _args: {
                'metadata': {'uid': 'probe-uid'},
                'status': {'conditions': [{'type': 'Synced', 'status': 'False',
                                           'message': 'some unrelated rendering error'}]}}
            with self.assertRaisesRegex(proof.ProofError, 'did not refuse'):
                proof.admission_receipt_refusal('ws-receipt-xr', 'ws-receipt', 'a' * 40, 'dw-')
            print('CONTROL FAILS AS EXPECTED: an unrelated Composition error cannot satisfy the admission receipt proof')
        finally:
            proof.kubectl = original_kubectl
            proof.get_json = original_get_json
            proof.composed_objects = original_composed_objects
            proof.wait_until = original_wait_until

    def test_uninstall_deletes_provider_steering_guard(self):
        original_target = proof.target
        original_run = proof.subprocess.run
        original_kubectl = proof.kubectl
        original_invalidate_admission_ready = proof.invalidate_admission_ready
        deleted = []
        actions = []
        proof.target = lambda: {'context': 'offline'}
        def fake_run(args, **_kwargs):
            return completed(list(args), returncode=1 if args[:2] == ['helm', 'status'] else 0)
        def fake_kubectl(args, **_kwargs):
            if args[:2] == ['get', 'developerworkspaces']:
                return completed(args, stdout=json.dumps({'items': []}))
            if args[:2] == ['get', 'crd']:
                return completed(args, stdout=json.dumps({'items': []}))
            if args[0] == 'delete' and '-f' in args:
                relative = str(Path(args[args.index('-f') + 1]).relative_to(proof.CAPABILITY))
                deleted.append(relative)
                actions.append(relative)
            return completed(args)
        proof.subprocess.run = fake_run
        proof.kubectl = fake_kubectl
        proof.invalidate_admission_ready = lambda: actions.append('receipt-invalidated')
        try:
            proof.uninstall(None)
            self.assertIn('install/provider-steering-guard.yaml', deleted)
            self.assertLess(actions.index('receipt-invalidated'),
                            actions.index('install/provider-steering-guard.yaml'))
            print('CONTROL PASS: uninstall recipe deletes the provider steering policy and binding')
        finally:
            proof.target = original_target
            proof.subprocess.run = original_run
            proof.kubectl = original_kubectl
            proof.invalidate_admission_ready = original_invalidate_admission_ready

    def test_noncanonical_name_refusal_requires_admission_denial_and_no_object_refs(self):
        rejected = completed(['create'], 1, stderr="metadata.name must equal spec.workspaceID + '-xr'")
        observed = proof.assert_noncanonical_name_refused(rejected, 'ws-duplicate-collision')
        self.assertEqual({'name': 'ws-duplicate-collision', 'exists': False, 'ready': False, 'objectRefs': []}, observed)
        with self.assertRaisesRegex(proof.ProofError, 'was not rejected'):
            proof.assert_noncanonical_name_refused(completed(['create']), 'ws-duplicate-collision')

        # Exercise both postconditions independently after an otherwise-valid denial.
        self.fake.candidate_exists = True
        with self.assertRaisesRegex(proof.ProofError, 'absence was not confirmed by NotFound'):
            proof.assert_noncanonical_name_refused(rejected, 'ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: denied noncanonical owner still present fails NotFound postcondition')
        self.fake.candidate_exists = False
        self.fake.object_refs = [{'metadata': {'name': 'composed-collision', 'labels': {'crossplane.io/composite': 'ws-duplicate-collision'}}}]
        with self.assertRaisesRegex(proof.ProofError, 'composed Object references'):
            proof.assert_noncanonical_name_refused(rejected, 'ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: denied noncanonical owner with composed Object refs fails reference postcondition')
        self.fake.object_refs = []
        self.fake.candidate_get_error = 'Unable to connect to the server: network is unreachable\n'
        with self.assertRaisesRegex(proof.ProofError, 'absence was not confirmed by NotFound'):
            proof.assert_noncanonical_name_refused(rejected, 'ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: a transport error cannot prove the noncanonical owner absent')

    def test_delete_cleanup_requires_exact_not_found_for_namespace_and_volume(self):
        original_get_json = proof.get_json
        original_composed_objects = proof.composed_objects
        original_wait_until = proof.wait_until

        def exercise(namespace_error, volume_error=None):
            volumes = ['pv-a'] if volume_error is not None else []
            proof.get_json = lambda args: {'items': [{'spec': {'volumeName': volume}} for volume in volumes]}
            proof.composed_objects = lambda _name: []
            proof.wait_until = lambda what, predicate, **_kwargs: proof.expect(predicate(), f'{what} absence was not confirmed')
            def fake_kubectl(args, **_kwargs):
                if args[0] == 'delete':
                    return completed(args)
                if args[:2] == ['get', 'namespace']:
                    return completed(args, 1, stderr=namespace_error)
                if args[:2] == ['get', 'pv']:
                    return completed(args, 1, stderr=volume_error)
                raise AssertionError(args)
            proof.kubectl = fake_kubectl
            return proof.delete_and_confirm_gone('ws-a-xr', 'dw-a', 0)

        not_found = 'Error from server (NotFound): resource not found\n'
        try:
            self.assertEqual(0, exercise(not_found))
            self.assertEqual(1, exercise(not_found, not_found))
            for error in ('Error from server (Forbidden): forbidden\n',
                          'Unable to connect to the server: network is unreachable\n'):
                with self.subTest(namespace_error=error):
                    with self.assertRaisesRegex(proof.ProofError, 'namespace dw-a removal absence was not confirmed'):
                        exercise(error)
                with self.subTest(volume_error=error):
                    with self.assertRaisesRegex(proof.ProofError, 'PersistentVolume pv-a removal absence was not confirmed'):
                        exercise(not_found, error)
            print('CONTROL FAILS AS EXPECTED: Forbidden and transport errors cannot prove Namespace or PersistentVolume deletion')
        finally:
            proof.kubectl = self.fake
            proof.get_json = original_get_json
            proof.composed_objects = original_composed_objects
            proof.wait_until = original_wait_until

    def test_canonical_collision_requires_exact_already_exists(self):
        owner = 'ws-ok175-proof-xr'
        rejected = completed(['create'], 1, stderr=(
            'Error from server (AlreadyExists): developerworkspaces.workspace.openkubes.io '
            f'"{owner}" already exists\n'))
        self.assertEqual({'name': owner, 'reason': 'AlreadyExists', 'created': False},
                         proof.assert_canonical_create_already_exists(rejected, owner))
        for bad in (
            completed(['create']),
            completed(['create'], 1, stderr=f'Error from server (NotFound): "{owner}" not found\n'),
            completed(['create'], 1, stderr='Error from server (AlreadyExists): "another-owner" already exists\n'),
        ):
            with self.subTest(stderr=bad.stderr):
                with self.assertRaisesRegex(proof.ProofError, 'did not report AlreadyExists'):
                    proof.assert_canonical_create_already_exists(bad, owner)
        print('CONTROL FAILS AS EXPECTED: success, another reason, or another owner cannot satisfy canonical collision proof')

    def test_owner_snapshot_strict_collision_and_relaxed_isolation_controls(self):
        before = sample_snapshot()
        after = copy.deepcopy(before)
        observed = proof.assert_owner_unchanged(before, after)
        self.assertEqual('30', observed['objects'][0]['resourceVersionBefore'])
        self.assertEqual('30', observed['objects'][0]['resourceVersionAfter'])

        changed_rv = copy.deepcopy(after)
        changed_rv['xrResourceVersion'] = '11'
        changed_rv['objects']['object-a']['resourceVersion'] = '31'
        changed_rv['resources']['Deployment/workspace-a']['resourceVersion'] = '41'
        with self.assertRaisesRegex(proof.ProofError, 'DeveloperWorkspace resourceVersion changed'):
            proof.assert_owner_unchanged(before, changed_rv)
        relaxed = proof.assert_owner_unchanged(before, changed_rv, strict_object_rv=False, strict_resource_rv=False)
        self.assertEqual('31', relaxed['objects'][0]['resourceVersionAfter'])
        self.assertEqual('41', next(r for r in relaxed['readback'] if r['name'].startswith('Deployment/'))['resourceVersionAfter'])

        changed_spec = copy.deepcopy(before)
        changed_spec['objects']['object-a']['spec']['forProvider']['manifest']['kind'] = 'ConfigMap'
        with self.assertRaisesRegex(proof.ProofError, 'spec changed'):
            proof.assert_owner_unchanged(before, changed_spec)
        changed_xr = copy.deepcopy(before)
        changed_xr['xrSpec']['workspaceID'] = 'ws-other'
        with self.assertRaisesRegex(proof.ProofError, 'DeveloperWorkspace spec changed'):
            proof.assert_owner_unchanged(before, changed_xr)
        changed_namespace = copy.deepcopy(before)
        changed_namespace['namespace']['resourceVersion'] = '21'
        with self.assertRaisesRegex(proof.ProofError, 'Namespace identity'):
            proof.assert_owner_unchanged(before, changed_namespace)

        changed_readback = copy.deepcopy(before)
        changed_readback['resources']['Deployment/workspace-a']['content']['spec']['replicas'] = 2
        with self.assertRaisesRegex(proof.ProofError, 'readback .* content changed'):
            proof.assert_owner_unchanged(before, changed_readback, strict_object_rv=False, strict_resource_rv=False)
        changed_readback_uid = copy.deepcopy(before)
        changed_readback_uid['resources']['Deployment/workspace-a']['uid'] = 'replacement-uid'
        with self.assertRaisesRegex(proof.ProofError, 'readback .* UID changed'):
            proof.assert_owner_unchanged(before, changed_readback_uid, strict_object_rv=False, strict_resource_rv=False)

        for key, value in (('labels', {'crossplane.io/composite': 'other'}),
                           ('annotations', {'example': 'changed'}),
                           ('finalizers', ['example/changed']),
                           ('creationTimestamp', '2026-10-13T00:01:00Z'),
                           ('generation', 2), ('deletionTimestamp', '2026-10-13T00:01:00Z')):
            changed_metadata = copy.deepcopy(before)
            changed_metadata['objects']['object-a']['metadata'][key] = value
            with self.subTest(metadata=key):
                with self.assertRaisesRegex(proof.ProofError, 'metadata changed'):
                    proof.assert_owner_unchanged(before, changed_metadata)
            print(f'CONTROL FAILS AS EXPECTED: owner Object metadata {key} mutation is detected')

    def test_distinct_workspace_snapshot_controls(self):
        first, second = sample_snapshot('c69924'), sample_snapshot('cd9634')
        result = proof.assert_distinct_workspace_snapshots(first, second)
        self.assertEqual([['object-c69924'], ['object-cd9634']], result['objectNames'])
        mutations = []
        same_namespace = copy.deepcopy(second)
        same_namespace['namespace']['uid'] = first['namespace']['uid']
        mutations.append((same_namespace, 'share a Namespace'))
        same_object_name = copy.deepcopy(second)
        same_object_name['objects']['object-c69924'] = same_object_name['objects'].pop('object-cd9634')
        mutations.append((same_object_name, 'share composed Object names'))
        same_object_uid = copy.deepcopy(second)
        same_object_uid['objects']['object-cd9634']['uid'] = first['objects']['object-c69924']['uid']
        mutations.append((same_object_uid, 'share composed Object UIDs'))
        same_resource_uid = copy.deepcopy(second)
        same_resource_uid['resources']['Deployment/workspace-cd9634']['uid'] = \
            first['resources']['Deployment/workspace-c69924']['uid']
        mutations.append((same_resource_uid, 'share rendered-resource UIDs'))
        for changed, message in mutations:
            with self.subTest(message=message):
                with self.assertRaisesRegex(proof.ProofError, message):
                    proof.assert_distinct_workspace_snapshots(first, changed)
        print('CONTROL FAILS AS EXPECTED: shared Namespace, Object, or rendered-resource identities fail isolation')


if __name__ == '__main__':
    def without_expect(assertion):
        def unchecked(*args, **kwargs):
            original_expect = proof.expect
            proof.expect = lambda *_args, **_kwargs: None
            try:
                return assertion(*args, **kwargs)
            finally:
                proof.expect = original_expect
        return unchecked

    if '--disable-who-can-check' in sys.argv:
        sys.argv.remove('--disable-who-can-check')
        proof.assert_authority_holder_sets = lambda holders, expected: None
    if '--disable-indirect-check' in sys.argv:
        sys.argv.remove('--disable-indirect-check')
        proof.assert_indirect_authority_holder_sets = lambda holders, expected: None
    if '--disable-owner-unchanged-check' in sys.argv:
        sys.argv.remove('--disable-owner-unchanged-check')
        proof.assert_owner_unchanged = without_expect(proof.assert_owner_unchanged)
    if '--disable-distinct-workspace-check' in sys.argv:
        sys.argv.remove('--disable-distinct-workspace-check')
        proof.assert_distinct_workspace_snapshots = without_expect(proof.assert_distinct_workspace_snapshots)
    if '--disable-canonical-collision-check' in sys.argv:
        sys.argv.remove('--disable-canonical-collision-check')
        proof.assert_canonical_create_already_exists = without_expect(proof.assert_canonical_create_already_exists)
    if '--disable-provider-steering-policy' in sys.argv:
        sys.argv.remove('--disable-provider-steering-policy')
    if '--treat-namespaced-rolebindings-as-non-effective' in sys.argv:
        sys.argv.remove('--treat-namespaced-rolebindings-as-non-effective')
        proof.rolebinding_grants_resource = lambda cluster_binding, _scope: cluster_binding
    unittest.main(verbosity=2)
