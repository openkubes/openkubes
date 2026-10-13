#!/usr/bin/env python3
"""Evaluate the capability's admission manifests with the pinned CEL implementation.

This is an offline expression and manifest-shape check. It does not prove that an API server
accepted the policies or exercised its real authorizer.
"""
import argparse
import copy
import sys
from pathlib import Path

import yaml

try:
    import celpy
    from celpy import celtypes
    from celpy.adapter import json_to_cel
except ModuleNotFoundError as error:
    print('FAIL cel-python is required; install tests/cel-requirements.txt', file=sys.stderr)
    raise SystemExit(2) from error


CAPABILITY = Path(__file__).resolve().parent.parent
STEERING_GUARD = CAPABILITY / 'install/provider-steering-guard.yaml'
NAMESPACE_GUARD = CAPABILITY / 'install/namespace-guard.yaml'
POLICY_NAME = 'developer-workspace-provider-steering'
OPERATOR_EXPRESSION = (
    "authorizer.group('apiextensions.crossplane.io').resource('environmentconfigs')."
    "name('developer-workspace-profile').check('update').allowed()"
)
EXPECTED_RESOURCES = {
    ('kubernetes.m.crossplane.io', 'objects', 'Namespaced'),
    ('kubernetes.m.crossplane.io', 'providerconfigs', 'Namespaced'),
    ('kubernetes.m.crossplane.io', 'observedobjectcollections', 'Namespaced'),
    ('kubernetes.m.crossplane.io', 'clusterproviderconfigs', 'Cluster'),
    ('kubernetes.crossplane.io', 'observedobjectcollections', 'Cluster'),
}
EXPECTED_OPERATIONS = {'CREATE', 'UPDATE'}


class NullableMap(celtypes.MapType):
    """Model Kubernetes' nullable namespaceObject around cel-python's null comparison gap."""

    def __eq__(self, other):
        if other is None:
            return celtypes.BoolType(False)
        return super().__eq__(other)

    def __ne__(self, other):
        if other is None:
            return celtypes.BoolType(True)
        return super().__ne__(other)


def documents(path):
    loaded = list(yaml.safe_load_all(path.read_text()))
    assert len(loaded) == 2, f'{path.name} must contain one policy and one binding'
    policy, binding = loaded
    assert policy['kind'] == 'ValidatingAdmissionPolicy', f'{path.name} policy is missing'
    assert binding['kind'] == 'ValidatingAdmissionPolicyBinding', f'{path.name} binding is missing'
    return policy, binding


def steering_shape(policy, binding):
    assert policy['metadata']['name'] == POLICY_NAME, 'provider-steering policy name changed'
    assert policy['spec']['failurePolicy'] == 'Fail', 'provider-steering policy must fail closed'
    assert binding['metadata']['name'] == POLICY_NAME, 'provider-steering binding name changed'
    assert binding['spec']['policyName'] == POLICY_NAME, 'provider-steering binding selects another policy'
    assert binding['spec']['validationActions'] == ['Deny'], 'provider-steering binding must Deny'
    assert 'paramKind' not in policy['spec'], 'provider-steering policy must not use parameters'
    assert 'paramRef' not in binding['spec'], 'provider-steering binding must not use parameters'
    assert not policy['spec'].get('matchConditions'), \
        'provider-steering policy must not have bypassing matchConditions'
    assert 'matchResources' not in binding['spec'], \
        'provider-steering binding must not narrow the policy with matchResources selectors'

    constraints = policy['spec']['matchConstraints']
    assert set(constraints) == {'matchPolicy', 'resourceRules'}, \
        'provider-steering matchConstraints must not contain selectors or exclusions'
    assert constraints['matchPolicy'] == 'Equivalent', \
        'provider-steering matchPolicy must remain Equivalent'

    actual = set()
    for rule in constraints['resourceRules']:
        assert rule['apiVersions'] == ['*'], f"{rule['apiGroups']} must match every served version"
        assert set(rule['operations']) == EXPECTED_OPERATIONS, \
            f"{rule['apiGroups']} {rule['resources']} operation set changed"
        assert len(rule['apiGroups']) == 1, 'each provider-steering rule must name one API group'
        for resource in rule['resources']:
            actual.add((rule['apiGroups'][0], resource, rule['scope']))
    assert actual == EXPECTED_RESOURCES, \
        f'provider-steering resource set changed: extra={actual - EXPECTED_RESOURCES}, missing={EXPECTED_RESOURCES - actual}'

    validations = policy['spec']['validations']
    assert len(validations) == 1, 'provider-steering policy must have one operator validation'
    assert validations[0]['expression'] == OPERATOR_EXPRESSION, 'operator authorizer definition changed'
    return validations[0]


def assert_shape_control_rejected(policy, binding, mutate, label):
    changed_policy = copy.deepcopy(policy)
    changed_binding = copy.deepcopy(binding)
    mutate(changed_policy, changed_binding)
    try:
        steering_shape(changed_policy, changed_binding)
    except AssertionError:
        return
    raise AssertionError(f'provider-steering shape check admitted {label}')


def check_shape_negative_controls(policy, binding):
    assert_shape_control_rejected(
        policy, binding,
        lambda candidate, unused: candidate['spec'].__setitem__(
            'matchConditions', [{'name': 'disabled', 'expression': 'false'}]),
        'a false matchCondition')
    assert_shape_control_rejected(
        policy, binding,
        lambda candidate, unused: candidate['spec']['matchConstraints'].__setitem__(
            'objectSelector', {'matchLabels': {'admission-bypass': 'true'}}),
        'an objectSelector exclusion')
    assert_shape_control_rejected(
        policy, binding,
        lambda candidate, unused: candidate['spec']['matchConstraints'].__setitem__(
            'excludeResourceRules', copy.deepcopy(
                candidate['spec']['matchConstraints']['resourceRules'])),
        'excludeResourceRules')
    assert_shape_control_rejected(
        policy, binding,
        lambda unused, candidate: candidate['spec'].__setitem__(
            'matchResources', {'namespaceSelector': {'matchLabels': {'admission-bypass': 'true'}}}),
        'binding matchResources selectors')


def authorizer_functions():
    def advance(field):
        def function(receiver, value):
            state = celtypes.MapType(receiver)
            state[celtypes.StringType(field)] = value
            return state
        return function

    def allowed(receiver):
        expected = {
            'group': 'apiextensions.crossplane.io',
            'resource': 'environmentconfigs',
            'name': 'developer-workspace-profile',
            'verb': 'update',
        }
        for key, value in expected.items():
            if str(receiver.get(celtypes.StringType(key), '')) != value:
                return celtypes.BoolType(False)
        return celtypes.BoolType(bool(receiver.get(celtypes.StringType('operator'), False)))

    return {
        'group': advance('group'),
        'resource': advance('resource'),
        'name': advance('name'),
        'check': advance('verb'),
        'allowed': allowed,
    }


def steering_program(expression):
    environment = celpy.Environment(annotations={'authorizer': celtypes.MapType})
    return environment.program(environment.compile(expression), functions=authorizer_functions())


def rule_matches(policy, group, resource, operation, scope, version='v1alpha1'):
    for rule in policy['spec']['matchConstraints']['resourceRules']:
        if operation not in rule['operations']:
            continue
        if group not in rule['apiGroups']:
            continue
        if version not in rule['apiVersions'] and '*' not in rule['apiVersions']:
            continue
        if resource not in rule['resources']:
            continue
        if rule.get('scope', '*') not in ('*', scope):
            continue
        return True
    return False


def admitted(policy, program, group, resource, operation, scope, operator):
    if not rule_matches(policy, group, resource, operation, scope):
        return True
    authorizer = json_to_cel({'operator': operator})
    return bool(program.evaluate({'authorizer': authorizer}))


def check_steering(disable_policy=False):
    policy, binding = documents(STEERING_GUARD)
    validation = steering_shape(policy, binding)
    check_shape_negative_controls(policy, binding)
    policy = copy.deepcopy(policy)
    if disable_policy:
        policy['spec']['validations'][0]['expression'] = 'true'
    program = steering_program(policy['spec']['validations'][0]['expression'])

    exercised = set()
    for group, resource, scope in sorted(EXPECTED_RESOURCES):
        for operation in sorted(EXPECTED_OPERATIONS):
            assert rule_matches(policy, group, resource, operation, scope), \
                f'{group}/{resource} {operation} {scope} did not match'
            assert admitted(policy, program, group, resource, operation, scope, True), \
                f'operator was denied {operation} on {group}/{resource}'
            assert not admitted(policy, program, group, resource, operation, scope, False), \
                f'non-operator was admitted {operation} on {group}/{resource}'
            exercised.add((group, resource, scope, operation))
    assert len(exercised) == len(EXPECTED_RESOURCES) * len(EXPECTED_OPERATIONS)

    for group, resource, scope in EXPECTED_RESOURCES:
        assert not rule_matches(policy, group, resource, 'DELETE', scope), \
            f'{group}/{resource} unexpectedly matched DELETE'
    assert not rule_matches(
        policy, 'kubernetes.m.crossplane.io', 'providerconfigusages', 'CREATE', 'Namespaced'), \
        'providerconfigusages must not be a steering target'
    assert validation['message'], 'provider-steering denial message is empty'
    print('PASS provider steering shape: Fail/Deny binding, exact 5-resource set, all versions and correct scopes')
    print('PASS provider steering match controls: conditions, selectors and exclusions cannot narrow enforcement')
    print('PASS provider steering CEL: operator admitted and non-operator denied for 10 CREATE/UPDATE paths')


def cel_program(expression, annotations):
    environment = celpy.Environment(annotations=annotations)
    return environment.program(environment.compile(expression))


def evaluate(program, values):
    activation = {
        key: value if isinstance(value, NullableMap) else json_to_cel(value)
        for key, value in values.items()
    }
    return bool(program.evaluate(activation))


def check_namespace_guard():
    policy, binding = documents(NAMESPACE_GUARD)
    assert policy['metadata']['name'] == 'developer-workspace-namespace-guard'
    assert policy['spec']['failurePolicy'] == 'Fail'
    assert binding['spec']['policyName'] == 'developer-workspace-namespace-guard'
    assert binding['spec']['validationActions'] == ['Deny']

    map_annotations = {
        'request': celtypes.MapType,
        'object': celtypes.MapType,
        'oldObject': celtypes.MapType,
        'namespaceObject': celtypes.MapType,
        'variables': celtypes.MapType,
    }
    condition = cel_program(policy['spec']['matchConditions'][0]['expression'], map_annotations)
    provider_request = {
        'userInfo': {'username': 'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'},
        'operation': 'CREATE',
        'resource': {'resource': 'namespaces'},
    }
    other_request = copy.deepcopy(provider_request)
    other_request['userInfo']['username'] = 'system:serviceaccount:default:other'
    assert evaluate(condition, {'request': provider_request})
    assert not evaluate(condition, {'request': other_request})

    validations = [cel_program(item['expression'], map_annotations) for item in policy['spec']['validations']]
    workspace_labels = {'workspace.openkubes.io/id': 'ws-one'}
    namespace = {'metadata': {'labels': workspace_labels}}
    matching_object = {'metadata': {'labels': workspace_labels}}
    mismatched_object = {'metadata': {'labels': {'workspace.openkubes.io/id': 'ws-two'}}}
    namespace_request = copy.deepcopy(provider_request)
    namespaced_request = copy.deepcopy(provider_request)
    namespaced_request['resource']['resource'] = 'serviceaccounts'
    variables = {'id': 'workspace.openkubes.io/id', 'subject': matching_object}

    assert evaluate(validations[0], {
        'request': namespace_request, 'object': namespace, 'oldObject': namespace,
        'namespaceObject': {}, 'variables': variables,
    })
    namespace_update = copy.deepcopy(namespace_request)
    namespace_update['operation'] = 'UPDATE'
    assert not evaluate(validations[0], {
        'request': namespace_update, 'object': {'metadata': {}}, 'oldObject': {'metadata': {}},
        'namespaceObject': {}, 'variables': variables,
    })
    assert evaluate(validations[1], {
        'request': namespace_request, 'object': namespace, 'oldObject': namespace,
        'namespaceObject': {}, 'variables': variables,
    })
    assert evaluate(validations[1], {
        'request': namespaced_request, 'object': matching_object, 'oldObject': matching_object,
        'namespaceObject': NullableMap(json_to_cel(namespace)), 'variables': variables,
    })
    variables['subject'] = mismatched_object
    assert not evaluate(validations[1], {
        'request': namespaced_request, 'object': mismatched_object, 'oldObject': mismatched_object,
        'namespaceObject': NullableMap(json_to_cel(namespace)), 'variables': variables,
    })
    print('PASS namespace guard CEL: provider match, unlabeled Namespace denial and label-match paths evaluated')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--disable-provider-steering-policy', action='store_true',
        help='mutation proof: make the provider-steering validation allow every matched request')
    args = parser.parse_args()
    try:
        check_steering(args.disable_provider_steering_policy)
        check_namespace_guard()
    except (AssertionError, KeyError, TypeError, celpy.CELEvalError, celpy.CELParseError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
