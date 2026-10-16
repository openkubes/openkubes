#!/usr/bin/env python3
"""Fake API safety tests for UID-bound hands-on up/down ownership."""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('ok180_reconcile_proof', HERE / 'reconcile_proof.py')
proof = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = proof
SPEC.loader.exec_module(proof)


TARGET = {'context': 'ok-178-ws-admin@ok-178-ws', 'kubeSystemUidSha256': 'cluster-sha256'}
NONCE = 'a' * 32


def resource(kind, name, uid, *, marker=NONCE, rv='7', namespace=None, **fields):
    metadata = {'name': name, 'uid': uid, 'resourceVersion': rv}
    if namespace: metadata['namespace'] = namespace
    if marker is not None: metadata['annotations'] = {proof.HANDS_ON_RUN: marker}
    return {'apiVersion': 'v1', 'kind': kind, 'metadata': metadata, **fields}


def entry(kind, name, uid, *, rv='7', namespace=None, **fields):
    return {'kind': kind, 'name': name, 'namespace': namespace, 'uid': uid,
            'resourceVersion': rv, 'intent': False, **fields}


class Result:
    def __init__(self, returncode, stderr):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ''


class FakeAPI:
    def __init__(self):
        self.objects = {}
        self.deletes = []
        self.composed = []

    @staticmethod
    def key(kind, name, namespace=None):
        return kind, namespace, name

    def add(self, kind, name, obj, namespace=None):
        self.objects[self.key(kind, name, namespace)] = copy.deepcopy(obj)

    def get(self, kind, name, namespace=None):
        value = self.objects.get(self.key(kind, name, namespace))
        return copy.deepcopy(value) if value is not None else None

    def get_json(self, args):
        if args[:2] == ['get', 'developerworkspaces']:
            return {'items': [copy.deepcopy(obj) for (kind, _ns, _name), obj in self.objects.items()
                              if kind == 'developerworkspace']}
        if args[:2] == ['get', 'pv']:
            return {'items': [copy.deepcopy(obj) for (kind, _ns, _name), obj in self.objects.items() if kind == 'pv']}
        raise AssertionError(f'unexpected get_json: {args}')

    def get_composed(self, _name):
        return copy.deepcopy(self.composed)

    def kubectl(self, args, *, input_text=None, timeout=120, check=True):
        if args and args[0] == 'create':
            doc = proof.yaml.safe_load(input_text)
            kind = {'Namespace': 'namespace'}[doc['kind']]
            name = doc['metadata']['name']
            if self.get(kind, name) is not None:
                raise proof.ProofError(f'{kind}/{name} AlreadyExists')
            doc['metadata'].update(uid=f'created-{name}', resourceVersion='1')
            self.add(kind, name, doc)
            return type('Result', (), {'stdout': json.dumps(doc)})()
        if args and args[0] == 'patch':
            kind, name = args[1].split('/', 1)
            obj = self.objects.get(self.key(kind, name))
            if obj is None: raise proof.ProofError(f'{kind}/{name} not found')
            operations = json.loads(args[args.index('-p') + 1])
            metadata = obj.setdefault('metadata', {})
            for operation in operations:
                path = operation['path']
                if operation['op'] == 'test':
                    field = path.rsplit('/', 1)[1]
                    if metadata.get(field) != operation['value']:
                        raise proof.ProofError(f'{kind}/{name} JSON Patch test failed: {path}')
                elif path == '/metadata/annotations':
                    metadata['annotations'] = copy.deepcopy(operation['value'])
                elif path.startswith('/metadata/annotations/'):
                    key = path.rsplit('/', 1)[1].replace('~1', '/')
                    metadata.setdefault('annotations', {})[key] = operation['value']
            return type('Result', (), {'stdout': json.dumps(obj)})()
        if args and args[0] == 'delete' and any(x.startswith('--raw=') for x in args):
            path = next(x.removeprefix('--raw=') for x in args if x.startswith('--raw='))
            options = json.loads(input_text)
            if path.startswith('/apis/workspace.openkubes.io/'):
                kind, name = 'developerworkspace', path.rsplit('/', 1)[1]
            elif path.startswith('/apis/apiextensions.crossplane.io/'):
                kind, name = 'environmentconfig', path.rsplit('/', 1)[1]
            elif path.startswith('/api/v1/namespaces/'):
                kind, name = 'namespace', path.rsplit('/', 1)[1]
            elif path.startswith('/api/v1/persistentvolumes/'):
                kind, name = 'pv', path.rsplit('/', 1)[1]
            else: raise AssertionError(f'unexpected raw delete path: {path}')
            key = self.key(kind, name)
            obj = self.objects.get(key)
            self.deletes.append((kind, name, copy.deepcopy(options)))
            if obj is not None:
                preconditions = options.get('preconditions', {})
                prefix = f'Error from server (Conflict): Operation cannot be fulfilled on {kind} "{name}": Precondition failed: '
                if preconditions.get('uid') != obj['metadata'].get('uid'):
                    return Result(1, prefix + f"UID in precondition: {preconditions.get('uid')}, UID in object meta: {obj['metadata'].get('uid')}")
                if preconditions.get('resourceVersion') != obj['metadata'].get('resourceVersion'):
                    return Result(1, prefix + f"ResourceVersion in precondition: {preconditions.get('resourceVersion')}, "
                                              f"ResourceVersion in object meta: {obj['metadata'].get('resourceVersion')}")
                del self.objects[key]
                if kind == 'developerworkspace':
                    self.objects.pop(self.key('namespace', 'dw-hands-on'), None)
                    self.objects.pop(self.key('pvc', 'workspace', 'dw-hands-on'), None)
            return Result(0, '')
        raise AssertionError(f'unexpected kubectl: {args}')


class HandsOnOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ok180-ownership-')
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / 'state.json'
        self.api = FakeAPI()
        self.patches = [
            patch.dict(os.environ, {'OK180_STATE_FILE': str(self.ledger)}),
            patch.object(proof, 'storage_inputs', lambda: {}),
            patch.object(proof, 'target', lambda: copy.deepcopy(TARGET)),
            patch.object(proof, 'installed_matches_local', lambda: {}),
            patch.object(proof, 'hands_on_namespace', lambda: 'dw-hands-on'),
            patch.object(proof, 'optional_object', self.api.get),
            patch.object(proof, 'get_json', self.api.get_json),
            patch.object(proof, 'kubectl', self.api.kubectl),
            patch.object(proof, 'composed_objects', lambda _name: []),
            patch.object(proof, 'composed_object_items', self.api.get_composed),
            patch.object(proof, 'wait_until', self.wait_once),
        ]
        for item in self.patches: item.start()
        self.addCleanup(self.stop_patches)

    def stop_patches(self):
        for item in reversed(self.patches): item.stop()

    @staticmethod
    def wait_once(what, predicate, **_kwargs):
        if not predicate(): raise proof.ProofError(f'fake wait did not observe {what}')

    def save_state(self, resources):
        state = {'version': 1, 'nonce': NONCE, 'target': copy.deepcopy(TARGET),
                 'workspaceNamespaceName': 'dw-hands-on', 'resources': resources}
        proof.write_hands_on_state(self.ledger, state, initial=True)
        return state

    def run_down(self):
        proof.down(None)

    def test_foreign_xr_same_name_has_no_delete_effect(self):
        bad = resource('DeveloperWorkspace', proof.HANDS_ON[0], 'foreign-xr', marker='foreign',
                       spec={'workspaceID': proof.HANDS_ON[1]})
        self.api.add('developerworkspace', proof.HANDS_ON[0], bad)
        state = self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], 'foreign-xr')})
        with self.assertRaisesRegex(proof.ProofError, 'foreign ownership marker'): self.run_down()
        self.assertEqual([], self.api.deletes)
        self.assertIsNotNone(self.api.get('developerworkspace', proof.HANDS_ON[0]))

    def test_foreign_environmentconfig_is_not_adopted(self):
        obj = resource('EnvironmentConfig', 'developer-workspace-profile', 'foreign-profile', marker='foreign',
                       data={'profile': {'spec': {}}})
        self.api.add('environmentconfig', 'developer-workspace-profile', obj)
        state = self.save_state({})
        with self.assertRaisesRegex(proof.ProofError, 'without a ledger entry'): self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_preexisting_fixture_namespace_is_not_adopted(self):
        self.api.add('namespace', proof.PROOF_NS,
                     resource('Namespace', proof.PROOF_NS, 'foreign-fixture', marker='foreign'))
        state = self.save_state({})
        with self.assertRaisesRegex(proof.ProofError, 'without a ledger entry'): self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_foreign_pv_replacement_is_not_deleted(self):
        state = self.save_state({'pv:pv-hands-on': entry('pv', 'pv-hands-on', 'old-pv')})
        self.api.add('pv', 'pv-hands-on', resource('PersistentVolume', 'pv-hands-on', 'new-pv'))
        with self.assertRaisesRegex(proof.ProofError, 'UID changed'): self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_altered_marker_fails_before_xr_delete(self):
        obj = resource('DeveloperWorkspace', proof.HANDS_ON[0], 'xr-1', marker='altered',
                       spec={'workspaceID': proof.HANDS_ON[1]})
        self.api.add('developerworkspace', proof.HANDS_ON[0], obj)
        state = self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], 'xr-1')})
        with self.assertRaisesRegex(proof.ProofError, 'foreign ownership marker'): self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_missing_ledger_fails_down_entrypoint(self):
        with self.assertRaisesRegex(proof.ProofError, 'ownership ledger is missing'):
            self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_second_up_refuses_an_existing_ledger(self):
        self.save_state({})
        with self.assertRaisesRegex(proof.ProofError, 'already exists'):
            proof.require_fresh_hands_on_ledger(self.ledger)

    def test_missing_marker_on_direct_created_resources_fails_closed(self):
        cases = (
            ('xr', 'developerworkspace', proof.HANDS_ON[0], 'xr-1', {'spec': {'workspaceID': proof.HANDS_ON[1]}}),
            ('profile', 'environmentconfig', 'developer-workspace-profile', 'profile-1',
             {'data': {'profile': {'spec': {}}}}),
            ('fixtureNamespace', 'namespace', proof.PROOF_NS, 'fixture-1', {}),
        )
        for key, kind, name, uid, extra in cases:
            with self.subTest(resource=f'{kind}/{name}'):
                self.api.objects.clear(); self.api.deletes.clear()
                self.ledger.unlink(missing_ok=True)
                fields = dict(extra)
                if kind == 'profile': fields['metadata'] = {'name': name, 'uid': uid, 'resourceVersion': '7'}
                api_kind = {'developerworkspace': 'DeveloperWorkspace',
                            'environmentconfig': 'EnvironmentConfig', 'namespace': 'Namespace'}[kind]
                obj = resource(api_kind, name, uid, marker=None, **fields)
                self.api.add(kind, name, obj)
                record = entry(kind, name, uid)
                if key == 'profile': record['dataSha256'] = proof.sha_json(extra['data'])
                self.save_state({key: record})
                with self.assertRaisesRegex(proof.ProofError, 'missing or foreign ownership marker'):
                    self.run_down()
                self.assertEqual([], self.api.deletes)

    def test_uid_bound_live_down_removes_only_journaled_xr_namespace_pv_and_support(self):
        namespace = 'dw-hands-on'; xr_uid = 'xr-1'; ns_uid = 'ns-1'; pvc_uid = 'pvc-1'; pv_name = 'pv-1'
        profile_data = {'profile': {'spec': {}}}
        resources = {'xr': entry('developerworkspace', proof.HANDS_ON[0], xr_uid),
                     'workspaceNamespace': entry('namespace', namespace, ns_uid),
                     'fixtureNamespace': entry('namespace', proof.PROOF_NS, 'fixture-1'),
                     'profile': entry('environmentconfig', 'developer-workspace-profile', 'profile-1',
                                      dataSha256=proof.sha_json(profile_data)),
                     f'pv:{pv_name}': entry('pv', pv_name, 'pv-1')}
        self.save_state(resources)
        self.api.add('developerworkspace', proof.HANDS_ON[0], resource(
            'DeveloperWorkspace', proof.HANDS_ON[0], xr_uid,
            spec={'workspaceID': proof.HANDS_ON[1]}))
        ns_obj = resource('Namespace', namespace, ns_uid)
        ns_obj['metadata']['labels'] = {proof.WORKSPACE_ID_LABEL: proof.HANDS_ON[1]}
        self.api.add('namespace', namespace, ns_obj)
        self.api.add('namespace', proof.PROOF_NS, resource('Namespace', proof.PROOF_NS, 'fixture-1'))
        self.api.add('environmentconfig', 'developer-workspace-profile', resource(
            'EnvironmentConfig', 'developer-workspace-profile', 'profile-1', data=profile_data))
        pvc = resource('PersistentVolumeClaim', 'workspace', pvc_uid, namespace=namespace,
                       spec={'volumeName': pv_name})
        self.api.add('pvc', 'workspace', pvc, namespace)
        self.api.add('pv', pv_name, resource('PersistentVolume', pv_name, 'pv-1',
            spec={'claimRef': {'uid': pvc_uid, 'namespace': namespace, 'name': 'workspace'}}))
        self.api.composed = [
            {'metadata': {'name': 'object-ns', 'uid': 'object-ns',
                          'labels': {'crossplane.io/composite': proof.HANDS_ON[0]},
                          'ownerReferences': [{'uid': xr_uid, 'controller': True}]},
             'spec': {'forProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace}}}},
             'status': {'atProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace, 'uid': ns_uid}}}}},
            {'metadata': {'name': 'object-pvc', 'uid': 'object-pvc',
                          'labels': {'crossplane.io/composite': proof.HANDS_ON[0]},
                          'ownerReferences': [{'uid': xr_uid, 'controller': True}]},
             'spec': {'forProvider': {'manifest': {'kind': 'PersistentVolumeClaim',
                         'metadata': {'name': 'workspace', 'namespace': namespace}}}},
             'status': {'atProvider': {'manifest': {'kind': 'PersistentVolumeClaim',
                         'metadata': {'name': 'workspace', 'namespace': namespace, 'uid': pvc_uid}}}},
            }]
        self.run_down()
        self.assertFalse(self.ledger.exists())
        self.assertEqual({'developerworkspace', 'namespace', 'environmentconfig', 'pv'},
                         {item[0] for item in self.api.deletes})
        for _kind, _name, options in self.api.deletes:
            self.assertTrue(options['preconditions']['uid'])
            self.assertTrue(options['preconditions']['resourceVersion'])

    def test_unrecorded_namespace_is_not_adopted_from_provider_observation(self):
        namespace = 'dw-hands-on'
        self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], 'xr-1'),
                         'workspaceNamespace': entry('namespace', namespace, None, intent=True)})
        self.api.add('developerworkspace', proof.HANDS_ON[0], resource(
            'DeveloperWorkspace', proof.HANDS_ON[0], 'xr-1', spec={'workspaceID': proof.HANDS_ON[1]}))
        obj = resource('Namespace', namespace, 'foreign-ns', marker=None)
        obj['metadata']['labels'] = {proof.WORKSPACE_ID_LABEL: proof.HANDS_ON[1]}
        self.api.add('namespace', namespace, obj)
        self.api.composed = [{
            'metadata': {'name': 'object-ns', 'uid': 'object-ns',
                         'labels': {'crossplane.io/composite': proof.HANDS_ON[0]},
                         'ownerReferences': [{'uid': 'xr-1', 'controller': True}]},
            'spec': {'forProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace}}}},
            'status': {'atProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace, 'uid': 'foreign-ns'}}}},
        }]
        with self.assertRaisesRegex(proof.ProofError, 'ownership marker|recorded UID'):
            self.run_down()
        self.assertEqual(obj, self.api.get('namespace', namespace))
        self.assertEqual([], self.api.deletes)

    def test_unrecorded_pv_blocks_interrupted_down(self):
        self.save_state({})
        obj = resource('PersistentVolume', 'foreign-pv', 'foreign-pv', marker=None,
                       spec={'claimRef': {'namespace': 'dw-hands-on', 'name': 'workspace', 'uid': 'foreign-pvc'}})
        self.api.add('pv', 'foreign-pv', obj)
        with self.assertRaisesRegex(proof.ProofError, '[Pp][Vv]/foreign-pv.*ledger'):
            self.run_down()
        self.assertEqual(obj, self.api.get('pv', 'foreign-pv'))
        self.assertEqual([], self.api.deletes)
        self.assertTrue(self.ledger.exists())

    def test_racing_namespace_create_is_not_adopted(self):
        state = self.save_state({})
        foreign = resource('Namespace', 'dw-hands-on', 'foreign-ns', marker=None)
        self.api.add('namespace', 'dw-hands-on', foreign)
        doc = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'dw-hands-on'}}
        with self.assertRaisesRegex(proof.ProofError, 'AlreadyExists'):
            proof.create_owned_namespace(self.ledger, state, doc)
        self.assertEqual(foreign, self.api.get('namespace', 'dw-hands-on'))
        self.assertIsNone(json.loads(self.ledger.read_text())['resources']['workspaceNamespace']['uid'])
        self.assertEqual([], self.api.deletes)

    def test_interrupted_up_before_xr_cleans_uid_recorded_namespace(self):
        state = self.save_state({})
        doc = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'dw-hands-on'}}
        proof.create_owned_namespace(self.ledger, state, doc)
        self.assertEqual('created-dw-hands-on', json.loads(self.ledger.read_text())['resources']['workspaceNamespace']['uid'])
        self.run_down()
        self.assertFalse(self.ledger.exists())
        self.assertIsNone(self.api.get('namespace', 'dw-hands-on'))

    def test_foreign_marker_on_first_pv_observation_is_preserved(self):
        namespace, xr_uid, _pvc_uid, pv_name, pv, state = self.bound_pv_scene(marker='foreign')
        with self.assertRaisesRegex(proof.ProofError, 'PV/pv-owned.*ownership marker'):
            proof.record_workspace_pv(self.ledger, state, namespace, xr_uid)
        self.assertEqual(pv, self.api.get('pv', pv_name))
        self.assertEqual([], self.api.deletes)

    def test_removed_pv_marker_cannot_be_restored_after_adoption(self):
        self.save_state({'pv:pv-1': entry('pv', 'pv-1', 'pv-1')})
        obj = resource('PersistentVolume', 'pv-1', 'pv-1', marker=None)
        self.api.add('pv', 'pv-1', obj)
        with self.assertRaisesRegex(proof.ProofError, 'missing or foreign ownership marker'):
            self.run_down()
        self.assertEqual(obj, self.api.get('pv', 'pv-1'))
        self.assertEqual([], self.api.deletes)

    def test_create_response_loss_keeps_ambiguous_same_name_object(self):
        xr = resource('DeveloperWorkspace', proof.HANDS_ON[0], 'xr-created',
                      spec={'workspaceID': proof.HANDS_ON[1]})
        self.api.add('developerworkspace', proof.HANDS_ON[0], xr)
        state = self.save_state({'xr': {'kind': 'developerworkspace', 'name': proof.HANDS_ON[0], 'namespace': None,
                                        'intent': True, 'uid': None, 'resourceVersion': None}})
        with self.assertRaisesRegex(proof.ProofError, 'no recorded UID'): self.run_down()
        self.assertEqual([], self.api.deletes)
        self.assertIsNotNone(self.api.get('developerworkspace', proof.HANDS_ON[0]))

    def bound_pv_scene(self, marker=None):
        namespace = 'dw-hands-on'; xr_uid = 'xr-owned'; pvc_uid = 'pvc-owned'; pv_name = 'pv-owned'
        self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], xr_uid)})
        pvc = resource('PersistentVolumeClaim', 'workspace', pvc_uid, namespace=namespace,
                       spec={'volumeName': pv_name})
        pv = resource('PersistentVolume', pv_name, 'pv-uid', marker=marker,
                      spec={'claimRef': {'uid': pvc_uid, 'namespace': namespace, 'name': 'workspace'}})
        self.api.add('pvc', 'workspace', pvc, namespace)
        self.api.add('pv', pv_name, pv)
        self.api.composed = [{
            'metadata': {'name': 'composed-pvc', 'uid': 'object-uid',
                         'labels': {'crossplane.io/composite': proof.HANDS_ON[0]},
                         'ownerReferences': [{'uid': xr_uid, 'controller': True}]},
            'spec': {'forProvider': {'manifest': {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                                                   'metadata': {'name': 'workspace', 'namespace': namespace}}}},
            'status': {'atProvider': {'manifest': {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                                                    'metadata': {'name': 'workspace', 'namespace': namespace,
                                                                 'uid': pvc_uid}}}},
        }]
        state = json.loads(self.ledger.read_text())
        return namespace, xr_uid, pvc_uid, pv_name, pv, state

    def test_pv_record_requires_composed_pvc_and_claimref_uid_chain(self):
        namespace, xr_uid, pvc_uid, pv_name, pv, state = self.bound_pv_scene()
        proof.record_workspace_pv(self.ledger, state, namespace, xr_uid)
        state = json.loads(self.ledger.read_text())
        self.assertEqual(pvc_uid, state['pvcOwnership']['uid'])
        self.assertEqual('pv-uid', state['resources']['pv:pv-owned']['uid'])
        self.assertEqual(NONCE, self.api.get('pv', pv_name)['metadata']['annotations'][proof.HANDS_ON_RUN])
        self.api.objects[self.api.key('pv', pv_name)]['metadata']['annotations'].pop(proof.HANDS_ON_RUN)
        with self.assertRaisesRegex(proof.ProofError, 'missing or foreign ownership marker'):
            proof.record_workspace_pv(self.ledger, state, namespace, xr_uid)

        foreign = copy.deepcopy(pv)
        foreign['spec']['claimRef']['uid'] = 'same-name-different-pvc-uid'
        self.api.objects[self.api.key('pv', pv_name)] = foreign
        with self.assertRaisesRegex(proof.ProofError, 'claimRef does not match'):
            proof.record_workspace_pv(self.ledger, state, namespace, xr_uid)
        self.assertNotIn(proof.HANDS_ON_RUN, self.api.get('pv', pv_name)['metadata'].get('annotations', {}))

    def test_stamp_and_delete_preconditions_close_get_to_mutation_races(self):
        self.api.add('namespace', 'dw-hands-on', resource('Namespace', 'dw-hands-on', 'ns-original', marker=None))
        live = self.api.get('namespace', 'dw-hands-on')
        stamped = proof.stamp_owned('namespace', 'dw-hands-on', live, NONCE)
        self.assertEqual('ns-original', stamped['metadata']['uid'])
        self.assertEqual(NONCE, stamped['metadata']['annotations'][proof.HANDS_ON_RUN])
        stale = self.api.get('namespace', 'dw-hands-on')
        self.api.objects[self.api.key('namespace', 'dw-hands-on')]['metadata']['resourceVersion'] = '8'
        with self.assertRaisesRegex(proof.ProofError, 'JSON Patch test failed'):
            proof.stamp_owned('namespace', 'dw-hands-on', stale, NONCE)
        self.api.objects[self.api.key('namespace', 'dw-hands-on')] = resource(
            'Namespace', 'dw-hands-on', 'ns-replacement', marker=NONCE, rv='9')
        with self.assertRaisesRegex(proof.ProofError, 'Precondition failed: UID in precondition'):
            proof.delete_preconditioned('namespace', 'dw-hands-on', 'ns-original', '8')
        self.assertIsNotNone(self.api.get('namespace', 'dw-hands-on'))

    def test_interrupted_up_after_uid_journal_cleans_created_fixture_and_profile(self):
        self.save_state({'fixtureNamespace': entry('namespace', proof.PROOF_NS, 'fixture-1'),
                         'profile': entry('environmentconfig', 'developer-workspace-profile', 'profile-1',
                                          dataSha256=proof.sha_json({'profile': {'spec': {}}}))})
        self.api.add('namespace', proof.PROOF_NS, resource('Namespace', proof.PROOF_NS, 'fixture-1'))
        self.api.add('environmentconfig', 'developer-workspace-profile',
                     resource('EnvironmentConfig', 'developer-workspace-profile', 'profile-1',
                              data={'profile': {'spec': {}}}))
        self.run_down()
        self.assertFalse(self.ledger.exists())
        self.assertEqual({'environmentconfig', 'namespace'}, {item[0] for item in self.api.deletes})

    def test_interrupted_down_resumes_and_same_name_replacement_stays(self):
        # XR cleanup already completed; its old ledger remains while profile and fixture are pending.
        self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], 'deleted-xr'),
                         'profile': entry('environmentconfig', 'developer-workspace-profile', 'profile-1',
                                          dataSha256=proof.sha_json({'profile': {'spec': {}}})),
                         'fixtureNamespace': entry('namespace', proof.PROOF_NS, 'fixture-1')})
        self.api.add('environmentconfig', 'developer-workspace-profile',
                     resource('EnvironmentConfig', 'developer-workspace-profile', 'profile-1',
                              data={'profile': {'spec': {}}}))
        self.api.add('namespace', proof.PROOF_NS, resource('Namespace', proof.PROOF_NS, 'fixture-1'))
        self.run_down()
        self.assertFalse(self.ledger.exists())
        self.assertEqual({'environmentconfig', 'namespace'}, {item[0] for item in self.api.deletes})

        # A replacement with the old run's copied marker still fails on UID and remains untouched.
        self.api.objects.clear(); self.api.deletes.clear()
        self.api.add('developerworkspace', proof.HANDS_ON[0], resource(
            'DeveloperWorkspace', proof.HANDS_ON[0], 'replacement-xr',
            spec={'workspaceID': proof.HANDS_ON[1]}))
        state = self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], 'original-xr')})
        with self.assertRaisesRegex(proof.ProofError, 'UID changed'): self.run_down()
        self.assertEqual([], self.api.deletes)
        self.assertIsNotNone(self.api.get('developerworkspace', proof.HANDS_ON[0]))


    def seed_owned_world(self):
        """The ledger and live objects of one completed live-up, all UID- and marker-consistent."""
        namespace = 'dw-hands-on'; xr_uid = 'xr-1'; pvc_uid = 'pvc-1'; pv_name = 'pv-1'
        profile_data = {'profile': {'spec': {}}}
        self.save_state({'xr': entry('developerworkspace', proof.HANDS_ON[0], xr_uid),
                         'workspaceNamespace': entry('namespace', namespace, 'ns-1'),
                         'fixtureNamespace': entry('namespace', proof.PROOF_NS, 'fixture-1'),
                         'profile': entry('environmentconfig', 'developer-workspace-profile', 'profile-1',
                                          dataSha256=proof.sha_json(profile_data)),
                         f'pv:{pv_name}': entry('pv', pv_name, 'pv-1')})
        self.api.add('developerworkspace', proof.HANDS_ON[0], resource(
            'DeveloperWorkspace', proof.HANDS_ON[0], xr_uid, spec={'workspaceID': proof.HANDS_ON[1]}))
        ns_obj = resource('Namespace', namespace, 'ns-1')
        ns_obj['metadata']['labels'] = {proof.WORKSPACE_ID_LABEL: proof.HANDS_ON[1]}
        self.api.add('namespace', namespace, ns_obj)
        self.api.add('namespace', proof.PROOF_NS, resource('Namespace', proof.PROOF_NS, 'fixture-1'))
        self.api.add('environmentconfig', 'developer-workspace-profile', resource(
            'EnvironmentConfig', 'developer-workspace-profile', 'profile-1', data=profile_data))
        self.api.add('pvc', 'workspace', resource('PersistentVolumeClaim', 'workspace', pvc_uid, namespace=namespace,
                                                  spec={'volumeName': pv_name}), namespace)
        self.api.add('pv', pv_name, resource('PersistentVolume', pv_name, 'pv-1',
            spec={'claimRef': {'uid': pvc_uid, 'namespace': namespace, 'name': 'workspace'}}))
        owner = [{'uid': xr_uid, 'controller': True}]
        labels = {'crossplane.io/composite': proof.HANDS_ON[0]}
        self.api.composed = [
            {'metadata': {'name': 'object-ns', 'uid': 'object-ns', 'labels': labels, 'ownerReferences': owner},
             'spec': {'forProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace}}}},
             'status': {'atProvider': {'manifest': {'kind': 'Namespace', 'metadata': {'name': namespace, 'uid': 'ns-1'}}}}},
            {'metadata': {'name': 'object-pvc', 'uid': 'object-pvc', 'labels': labels, 'ownerReferences': owner},
             'spec': {'forProvider': {'manifest': {'kind': 'PersistentVolumeClaim',
                         'metadata': {'name': 'workspace', 'namespace': namespace}}}},
             'status': {'atProvider': {'manifest': {'kind': 'PersistentVolumeClaim',
                         'metadata': {'name': 'workspace', 'namespace': namespace, 'uid': pvc_uid}}}}}]

    def test_foreign_workspace_blocks_shared_profile_removal(self):
        self.seed_owned_world()
        self.api.add('developerworkspace', 'someone-else-xr', resource(
            'DeveloperWorkspace', 'someone-else-xr', 'foreign-xr', marker=None, spec={'workspaceID': 'someone-else'}))
        with self.assertRaisesRegex(proof.ProofError, 'other DeveloperWorkspaces exist'): self.run_down()
        self.assertEqual([], self.api.deletes)
        self.assertIsNotNone(self.api.get('environmentconfig', 'developer-workspace-profile'))

    def test_changed_profile_data_is_not_deleted(self):
        self.seed_owned_world()
        self.api.objects[self.api.key('environmentconfig', 'developer-workspace-profile')]['data'] = {
            'profile': {'spec': {'changed': True}}}
        with self.assertRaisesRegex(proof.ProofError, 'profile data changed'): self.run_down()
        self.assertEqual([], self.api.deletes)

    def test_up_refuses_every_preexisting_object_before_writing_a_ledger(self):
        cases = {
            'xr': ('developerworkspace', 'any-xr', resource('DeveloperWorkspace', 'any-xr', 'u1', marker=None), 'DeveloperWorkspaces already exist'),
            'workspace-namespace': ('namespace', 'dw-hands-on', resource('Namespace', 'dw-hands-on', 'u2', marker=None), 'namespace/dw-hands-on already exists'),
            'fixture-namespace': ('namespace', proof.PROOF_NS, resource('Namespace', proof.PROOF_NS, 'u3', marker=None), f'namespace/{proof.PROOF_NS} already exists'),
            'profile': ('environmentconfig', 'developer-workspace-profile', resource('EnvironmentConfig', 'developer-workspace-profile', 'u4', marker=None), 'environmentconfig/developer-workspace-profile already exists'),
        }
        def past_refusals(*_args, **_kwargs):
            raise proof.ProofError('up continued past the pre-existing object refusals')
        with patch.object(proof, 'image', lambda name: 'registry.example/x@sha256:' + 'b' * 64), \
             patch.object(proof, 'registry_inputs', past_refusals):
            for label, (kind, name, obj, message) in cases.items():
                with self.subTest(preexisting=label):
                    self.api.objects.clear()
                    self.api.add(kind, name, obj)
                    with self.assertRaisesRegex(proof.ProofError, message): proof.up(None)
                    self.assertFalse(self.ledger.exists())
                    self.assertEqual([], self.api.deletes)

    def test_delete_retries_a_resourceversion_conflict_with_the_same_uid(self):
        self.api.add('developerworkspace', 'x-xr', resource('DeveloperWorkspace', 'x-xr', 'xr-same', rv='8'))
        refreshed = []
        def refresh():
            refreshed.append(True); return self.api.get('developerworkspace', 'x-xr')
        proof.delete_preconditioned('developerworkspace', 'x-xr', 'xr-same', '7', refresh=refresh)
        self.assertEqual(1, len(refreshed))
        self.assertIsNone(self.api.get('developerworkspace', 'x-xr'))
        self.assertEqual(['7', '8'], [options['preconditions']['resourceVersion'] for _k, _n, options in self.api.deletes])

    def test_delete_never_retries_onto_a_replaced_object(self):
        self.api.add('developerworkspace', 'x-xr', resource('DeveloperWorkspace', 'x-xr', 'xr-replacement', rv='9'))
        with self.assertRaisesRegex(proof.ProofError, 'Precondition failed: UID in precondition'):
            proof.delete_preconditioned('developerworkspace', 'x-xr', 'xr-original', '7',
                                        refresh=lambda: self.api.get('developerworkspace', 'x-xr'))
        self.assertIsNotNone(self.api.get('developerworkspace', 'x-xr'))
        # A refresh that reports a different UID also stops the retry.
        self.api.objects[self.api.key('developerworkspace', 'x-xr')] = resource('DeveloperWorkspace', 'x-xr', 'xr-original', rv='9')
        with self.assertRaisesRegex(proof.ProofError, 'changed identity'):
            proof.delete_preconditioned('developerworkspace', 'x-xr', 'xr-original', '7',
                                        refresh=lambda: resource('DeveloperWorkspace', 'x-xr', 'xr-other', rv='10'))
        self.assertIsNotNone(self.api.get('developerworkspace', 'x-xr'))

@unittest.skipUnless(os.environ.get('OK180_OLD_PROOF'), 'set OK180_OLD_PROOF to the pre-review reconcile_proof.py')
class OldDownContrastTest(unittest.TestCase):
    """Negative evidence for the replaced design: label/name ownership deletes a foreign same-name XR.

    Run with the pre-review harness (origin/feat/ok-180-hands-on 7a0ec1b) extracted to a file:
      git show 7a0ec1b:<this dir>/reconcile_proof.py > tests/live/old_reconcile_proof.py
      OK180_OLD_PROOF=tests/live/old_reconcile_proof.py python3 tests/live/hands_on_ownership_selftest.py OldDownContrastTest
      rm tests/live/old_reconcile_proof.py
    (It resolves repository paths relative to its own location, so it must sit beside this file.)
    """
    def test_old_down_deletes_a_foreign_same_name_xr_that_new_down_refuses(self):
        spec = importlib.util.spec_from_file_location('ok180_old_reconcile_proof', os.environ['OK180_OLD_PROOF'])
        old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
        name, workspace_id = old.HANDS_ON
        objects = {('developerworkspace', name): {
            'kind': 'DeveloperWorkspace',
            'metadata': {'name': name, 'uid': 'foreign-xr', 'labels': {old.HANDS_ON_LABEL: 'true'}},
            'spec': {'workspaceID': workspace_id}}}
        deleted = []
        def kubectl(args, **_kwargs):
            if args[0] == 'delete':
                kind, obj_name = args[1].split('/', 1)
                deleted.append((kind, obj_name, objects.pop((kind, obj_name))['metadata']['uid']))
                return Result(0, '')
            raise AssertionError(f'unexpected old kubectl: {args}')
        def get_json(args):
            if args[:2] == ['get', 'developerworkspaces']:
                return {'items': [o for (k, _n), o in objects.items() if k == 'developerworkspace']}
            if args[:2] == ['get', 'pv']:
                return {'items': []}
            raise AssertionError(f'unexpected old get_json: {args}')
        stubs = {'storage_inputs': lambda: {}, 'target': lambda: {}, 'installed_matches_local': lambda: {},
                 'hands_on_namespace': lambda: 'dw-hands-on', 'kubectl': kubectl, 'get_json': get_json,
                 'optional_object': lambda kind, obj_name, *_a: objects.get((kind, obj_name)),
                 'wait_until': lambda *_a, **_k: None, 'composed_objects': lambda _n: []}
        with contextlib.ExitStack() as stack:
            for attr, value in stubs.items(): stack.enter_context(patch.object(old, attr, value))
            try: old.down(None)
            except old.ProofError: pass  # later steps may stop; the deletion already happened
        self.assertIn(('developerworkspace', name, 'foreign-xr'), deleted,
                      'expected the replaced label/name design to delete the foreign same-name XR')
        print('CONTRAST: the pre-review down deleted a foreign same-name XR carrying only the hands-on label; '
              'the UID-ledger down refuses it (test_foreign_xr_same_name_has_no_delete_effect)')

MUTATION_CASES = {
    'test_foreign_xr_same_name_has_no_delete_effect': 'owned_live',
    'test_foreign_environmentconfig_is_not_adopted': 'require_ledger_entry',
    'test_preexisting_fixture_namespace_is_not_adopted': 'require_ledger_entry',
    'test_foreign_pv_replacement_is_not_deleted': 'require_recorded_uid',
    'test_altered_marker_fails_before_xr_delete': 'owned_live',
    'test_missing_ledger_fails_down_entrypoint': 'load_hands_on_state',
    'test_create_response_loss_keeps_ambiguous_same_name_object': 'require_recorded_uid',
    'test_interrupted_down_resumes_and_same_name_replacement_stays': 'owned_live',
    'test_foreign_marker_on_first_pv_observation_is_preserved': 'require_pv_marker_for_adoption',
    'test_unrecorded_pv_blocks_interrupted_down': 'assert_no_unrecorded_pvs',
    'test_unrecorded_namespace_is_not_adopted_from_provider_observation': 'owned_live',
    'test_foreign_workspace_blocks_shared_profile_removal': 'refuse_foreign_workspaces',
    'test_changed_profile_data_is_not_deleted': 'require_profile_data_unchanged',
    'test_up_refuses_every_preexisting_object_before_writing_a_ledger': 'refuse_preexisting_hands_on_objects',
}


def prove_mutations():
    for test_name, guard_name in MUTATION_CASES.items():
        original = getattr(proof, guard_name)
        if guard_name == 'owned_live':
            mutant = lambda entry, _nonce: proof.optional_object(entry['kind'], entry['name'], entry.get('namespace'))
        elif guard_name == 'require_ledger_entry':
            mutant = lambda _entries, _key, kind, name: {'kind': kind, 'name': name}
        elif guard_name in ('require_recorded_uid', 'require_pv_marker_for_adoption', 'assert_no_unrecorded_pvs',
                            'refuse_foreign_workspaces', 'require_profile_data_unchanged',
                            'refuse_preexisting_hands_on_objects'):
            mutant = lambda *_args, **_kwargs: None
        else:
            mutant = lambda *_args, **_kwargs: {'version': 1, 'nonce': NONCE, 'target': TARGET,
                                                'workspaceNamespaceName': 'dw-hands-on', 'resources': {}}
        setattr(proof, guard_name, mutant)
        try:
            suite = unittest.defaultTestLoader.loadTestsFromName(f'{HandsOnOwnershipTest.__name__}.{test_name}', sys.modules[__name__])
            result = unittest.TestResult()
            suite.run(result)
        finally:
            setattr(proof, guard_name, original)
        if result.errors:
            details = '\n'.join(message for _test, message in result.errors)
            raise AssertionError(f'MUTANT ERRORED {test_name} with {guard_name}:\n{details}')
        if not result.failures:
            raise AssertionError(f'MUTANT SURVIVED {test_name}: disabling {guard_name} did not fail the safety assertion')
        print(f'MUTANT KILLED {test_name} guard={guard_name}')
    print(f'{len(MUTATION_CASES)} ownership mutants killed')


if __name__ == '__main__' and '--prove-mutations' in sys.argv:
    sys.argv.remove('--prove-mutations')
    prove_mutations()
elif __name__ == '__main__':
    unittest.main(verbosity=2)
