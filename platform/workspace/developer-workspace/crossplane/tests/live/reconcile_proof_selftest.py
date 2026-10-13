#!/usr/bin/env python3
"""Offline negative controls for reconcile_proof.py assertions."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('ok175_reconcile_proof', HERE / 'reconcile_proof.py')
proof = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proof
SPEC.loader.exec_module(proof)


def completed(args, returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(['kubectl', *args], returncode, stdout, stderr)


class FakeKubectl:
    def __init__(self):
        self.enforce_denial = True
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

    def add_observer_mutation(self, api_group, resource, verb):
        role = self.roles['developer-workspace-observer']
        role.append({'apiGroups': [api_group], 'resources': [resource], 'verbs': [verb]})

    def allowed(self, identity, verb, api_group, resource, name=None):
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
            allowed = self.allowed(identity, verb, api_group, resource, name or None)
            return completed(args, 0 if allowed else 1, 'yes\n' if allowed else 'no\n')
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
            if not self.allowed(identity, verb, api_group, resource, authorization_name):
                if identity.endswith(':developer-workspace-observer') and not self.enforce_denial:
                    return completed(args)
                error = (f'Error from server (Forbidden): {resource} is forbidden: User "{identity}" '
                         f'cannot {verb} resource "{resource}" in API group "{api_group}" at the cluster scope\n')
                return completed(args, 1, stderr=error)
            return completed(args)
        if args[0] == 'delete':
            return completed(args)
        if len(args) > 1 and args[0] == 'get' and args[1].startswith('developerworkspace/'):
            if self.candidate_get_error:
                return completed(args, 1, stderr=self.candidate_get_error)
            if self.candidate_exists:
                return completed(args, stdout='developerworkspace.workspace.openkubes.io/ws-duplicate-collision\n')
            return completed(args, 1, stderr='Error from server (NotFound): developerworkspaces.workspace.openkubes.io "ws-duplicate-collision" not found\n')
        if args[:2] == ['get', 'objects.kubernetes.crossplane.io']:
            return completed(args, stdout=json.dumps({'items': self.object_refs}))
        raise AssertionError(f'unexpected fake kubectl call: {args}')


def yaml_docs(path):
    return [d for d in proof.yaml.safe_load_all(path.read_text()) if d]


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
                for group, resource in proof.AUTHORITY_RESOURCES.values()]
    grant('cluster-admin', [{'kind': 'Group', 'name': 'system:masters'}], wildcard)
    grant('system:controller:generic-garbage-collector',
          [{'kind': 'ServiceAccount', 'name': 'generic-garbage-collector', 'namespace': 'kube-system'}],
          [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['get', 'list', 'watch', 'update', 'patch', 'delete']}])
    grant('system:controller:namespace-controller',
          [{'kind': 'ServiceAccount', 'name': 'namespace-controller', 'namespace': 'kube-system'}],
          [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['get', 'list', 'watch', 'delete', 'deletecollection']}])
    # Server-materialized aggregate rules are authoritative even if selectors match nothing.
    aggregation = {'aggregationRule': {'clusterRoleSelectors': [{'matchLabels': {'unused': 'true'}}]}}
    grant('crossplane', [{'kind': 'ServiceAccount', 'name': 'crossplane', 'namespace': 'crossplane-system'}],
          steering, **aggregation)
    if include_group:
        grant('crossplane-admin', [{'kind': 'Group', 'name': 'crossplane:masters'}], steering, **aggregation)
    grant('crossplane-rbac-manager', [{'kind': 'ServiceAccount', 'name': 'rbac-manager', 'namespace': 'crossplane-system'}],
          [{'apiGroups': ['rbac.authorization.k8s.io'], 'resources': ['*'], 'verbs': ['*']}])
    grant('provider-system', [{'kind': 'ServiceAccount', 'name': 'developer-workspace-provider-kubernetes',
                               'namespace': 'crossplane-system'}],
          [{'apiGroups': ['kubernetes.crossplane.io'], 'resources': ['objects', 'providerconfigs'],
            'verbs': ['get', 'list', 'watch', 'create', 'update', 'patch']}])
    roles.extend(yaml_docs(proof.CAPABILITY / 'rbac/authority-boundary.yaml'))
    bindings.extend(d for d in proof.authority_identities() if d['kind'] == 'ClusterRoleBinding')
    return {'clusterroles': roles, 'clusterrolebindings': bindings, 'roles': [], 'rolebindings': []}


class AuthorityWhoCanTest(unittest.TestCase):
    def setUp(self):
        self.original_get_json = proof.get_json
        self.fixture = authority_fixture()
        self.scopes = {f'{resource}.{group}': 'Cluster' for group, resource in proof.AUTHORITY_RESOURCES.values()}
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

    def test_rolebinding_only_is_reported_non_effective(self):
        self.add_binding('cluster-admin', {'kind': 'ServiceAccount', 'name': 'namespace-only'}, 'RoleBinding', 'team')
        role = {'kind': 'Role', 'metadata': {'name': 'local-editor', 'namespace': 'team'},
                'rules': [{'apiGroups': ['*'], 'resources': ['*'], 'verbs': ['*']}]}
        self.fixture['roles'].append(role)
        binding = self.add_binding('local-editor', {'kind': 'User', 'name': 'local-only'}, 'RoleBinding', 'team')
        binding['roleRef']['kind'] = 'Role'
        result = proof.prove_authority_who_can()
        self.assertEqual(32, len(result['nonEffectiveRoleBindings']))
        for entry in result['nonEffectiveRoleBindings']:
            self.assertIn('cluster-scoped', entry['reason'])
            self.assertNotIn(entry['subjects'][0], result['holders'][entry['kind']][entry['verb']])
        self.assertIn({'kind': 'ServiceAccount', 'name': 'namespace-only', 'namespace': 'team'},
                      result['nonEffectiveRoleBindings'][0]['subjects'])
        print('CONTROL PASS: RoleBinding references to Role and ClusterRole grant no cluster-scoped mutation; subjects reported')

    def test_namespaced_kind_is_rejected_before_ignoring_rolebindings(self):
        self.scopes['objects.kubernetes.crossplane.io'] = 'Namespaced'
        with self.assertRaisesRegex(proof.ProofError, 'Object must be cluster-scoped'):
            proof.prove_authority_who_can()
        print('CONTROL FAILS AS EXPECTED: installed namespaced Object invalidates the scope premise')

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
            policy, binding = read_all('install/namespace-guard.yaml')
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
                ('validatingadmissionpolicy', policy['metadata']['name']): policy,
                ('validatingadmissionpolicybinding', binding['metadata']['name']): binding,
            }
            return mapping

        original_get_json = proof.get_json
        current = fixtures()
        def fake_get_json(args):
            return copy.deepcopy(current[(args[1], args[2])])
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

            proof.installed_matches_local()
            print('CONTROL PASS: generated CRD root/spec CEL and workspaceID maxLength match current XRD')
        finally:
            proof.get_json = original_get_json

    def test_collision_refusal_requires_admission_denial_and_no_object_refs(self):
        rejected = completed(['create'], 1, stderr="metadata.name must equal spec.workspaceID + '-xr'")
        observed = proof.assert_collision_refused(rejected, 'ws-duplicate-collision')
        self.assertEqual({'name': 'ws-duplicate-collision', 'exists': False, 'ready': False, 'objectRefs': []}, observed)
        with self.assertRaisesRegex(proof.ProofError, 'was not rejected'):
            proof.assert_collision_refused(completed(['create']), 'ws-duplicate-collision')

        # Exercise both postconditions independently after an otherwise-valid denial.
        self.fake.candidate_exists = True
        with self.assertRaisesRegex(proof.ProofError, 'exists'):
            proof.assert_collision_refused(rejected, 'ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: denied collision with candidate still present fails NotFound postcondition')
        self.fake.candidate_exists = False
        self.fake.object_refs = [{'metadata': {'name': 'composed-collision', 'labels': {'crossplane.io/composite': 'ws-duplicate-collision'}}}]
        with self.assertRaisesRegex(proof.ProofError, 'composed Object references'):
            proof.assert_collision_refused(rejected, 'ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: denied collision with composed Object refs fails reference postcondition')

    def test_rejected_collision_delete_requires_not_found(self):
        proof.delete_rejected_collision('ws-duplicate-collision')
        self.fake.candidate_get_error = 'Unable to connect to the server: network is unreachable\n'
        with self.assertRaisesRegex(proof.ProofError, 'not confirmed absent'):
            proof.delete_rejected_collision('ws-duplicate-collision')
        print('CONTROL FAILS AS EXPECTED: arbitrary get error does not prove rejected collision absent')

    def test_owner_snapshot_allows_status_rv_churn_but_rejects_state_changes(self):
        before = {
            'xrUID': 'xr-uid',
            'namespace': {'uid': 'ns-uid', 'resourceVersion': '10', 'content': {'kind': 'Namespace', 'metadata': {'name': 'dw-a'}}},
            'objects': {'object-a': {'uid': 'object-uid', 'resourceVersion': '20',
                                     'metadata': {'name': 'object-a', 'uid': 'object-uid', 'labels': {'crossplane.io/composite': 'dw-a'},
                                                  'annotations': {'example': 'before'}, 'finalizers': ['example/finalizer'],
                                                  'creationTimestamp': '2026-10-13T00:00:00Z', 'generation': 1,
                                                  'deletionTimestamp': None},
                                     'ownerReferences': [{'uid': 'xr-uid', 'controller': True}],
                                     'spec': {'forProvider': {'manifest': {'kind': 'Namespace'}}}}},
        }
        after = copy.deepcopy(before)
        after['objects']['object-a']['resourceVersion'] = '21'
        observed = proof.assert_owner_unchanged(before, after)
        self.assertEqual('20', observed['objects'][0]['resourceVersionBefore'])
        self.assertEqual('21', observed['objects'][0]['resourceVersionAfter'])

        changed_spec = copy.deepcopy(after)
        changed_spec['objects']['object-a']['spec']['forProvider']['manifest']['kind'] = 'ConfigMap'
        with self.assertRaisesRegex(proof.ProofError, 'spec changed'):
            proof.assert_owner_unchanged(before, changed_spec)
        changed_namespace = copy.deepcopy(after)
        changed_namespace['namespace']['resourceVersion'] = '11'
        with self.assertRaisesRegex(proof.ProofError, 'Namespace identity'):
            proof.assert_owner_unchanged(before, changed_namespace)

        for key, value in (('labels', {'crossplane.io/composite': 'other'}),
                           ('annotations', {'example': 'changed'}),
                           ('finalizers', ['example/changed']),
                           ('creationTimestamp', '2026-10-13T00:01:00Z'),
                           ('generation', 2), ('deletionTimestamp', '2026-10-13T00:01:00Z')):
            changed_metadata = copy.deepcopy(after)
            changed_metadata['objects']['object-a']['metadata'][key] = value
            with self.subTest(metadata=key):
                with self.assertRaisesRegex(proof.ProofError, 'metadata changed'):
                    proof.assert_owner_unchanged(before, changed_metadata)
            print(f'CONTROL FAILS AS EXPECTED: owner Object metadata {key} mutation is detected')


if __name__ == '__main__':
    if '--disable-who-can-check' in sys.argv:
        sys.argv.remove('--disable-who-can-check')
        proof.assert_authority_holder_sets = lambda holders, expected: None
    unittest.main(verbosity=2)
