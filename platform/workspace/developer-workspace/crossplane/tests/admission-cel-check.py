#!/usr/bin/env python3
"""Evaluate the capability's admission manifests with the pinned CEL implementation.

This exercises the exact expressions loaded from all four admission manifests. It models the
Kubernetes authorizer CEL chain used by the guards; API-server matching, parameter lookup, and
installation are covered only by manifest assertions. It does not prove that an API server
accepted the policies or exercised its real authorizer.
"""
import argparse
import copy
import re
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
LABEL_GUARD = CAPABILITY / 'install/namespace-host-users-guard.yaml'
POD_GUARD = CAPABILITY / 'install/pod-user-namespace-guard.yaml'
STEERING_GUARD = CAPABILITY / 'install/provider-steering-guard.yaml'
NAMESPACE_GUARD = CAPABILITY / 'install/namespace-guard.yaml'
POLICY_NAME = 'developer-workspace-namespace-host-users-guard'
ID_LABEL = 'workspace.openkubes.io/id'
HOST_USERS_LABEL = 'workspace.openkubes.io/host-users'
PROVIDER = 'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'
PROFILE_MESSAGE = 'developer-workspace-profile data.profile.spec.hostUsers must be a boolean'
PROVIDER_MESSAGE = ('the DeveloperWorkspace provider must preserve the workspace identity and '
                    'render host-users from developer-workspace-profile')
CREATE_MESSAGE = ('only the DeveloperWorkspace provider or an operator may create a protected '
                  'workspace Namespace')
UPDATE_MESSAGE = 'only an operator may change workspace identity or host-users Namespace labels'
DELETE_MESSAGE = ('only the DeveloperWorkspace provider or an operator may delete a protected '
                  'workspace Namespace')
POD_MESSAGE = 'Pods in this workspace Namespace must set spec.hostUsers to false'


def documents(path):
    return list(yaml.safe_load_all(path.read_text()))


def normalized(expression):
    return ' '.join(expression.split())


def unauthorized(_receiver=None):
    return json_to_cel({'allow': False})


def authorizer_functions():
    from celpy.evaluation import bool_ne

    def expect(expected):
        def call(receiver, actual):
            return receiver if str(actual) == expected else unauthorized()
        return call

    def allowed(receiver):
        return receiver.get(celpy.celtypes.StringType('allow'), celpy.celtypes.BoolType(False))

    def not_equal(left, right):
        # cel-python represents the CEL null literal as Python None but JSON null as NullType.
        if right is None:
            return celpy.celtypes.BoolType(not isinstance(left, celpy.celtypes.NullType))
        if left is None:
            return celpy.celtypes.BoolType(not isinstance(right, celpy.celtypes.NullType))
        return bool_ne(left, right)

    return {
        'group': expect('apiextensions.crossplane.io'),
        'resource': expect('environmentconfigs'),
        'name': expect('developer-workspace-profile'),
        'check': expect('update'),
        'allowed': allowed,
        '_!=_': not_equal,
    }


ANNOTATIONS = {
    'object': celpy.celtypes.MapType,
    'oldObject': celpy.celtypes.MapType,
    'request': celpy.celtypes.MapType,
    'params': celpy.celtypes.MapType,
    'variables': celpy.celtypes.MapType,
    'authorizer': celpy.celtypes.MapType,
}


def evaluate(expression, activation):
    environment = celpy.Environment(annotations=ANNOTATIONS)
    ast = environment.compile(expression)
    program = environment.program(ast, functions=authorizer_functions())

    def convert(value):
        if isinstance(value, (celpy.celtypes.BoolType, celpy.celtypes.StringType,
                              celpy.celtypes.MapType, celpy.celtypes.ListType)):
            return value
        if value is None:
            return celpy.celtypes.NullType()
        if isinstance(value, dict):
            return celpy.celtypes.MapType({celpy.celtypes.StringType(key): convert(item)
                                          for key, item in value.items()})
        if isinstance(value, list):
            return celpy.celtypes.ListType(convert(item) for item in value)
        return json_to_cel(value)

    converted = {key: convert(value) for key, value in activation.items()}
    return program.evaluate(converted)


def compile_policy(policy):
    expressions = [condition['expression'] for condition in policy['spec']['matchConditions']]
    expressions += [variable['expression'] for variable in policy['spec']['variables']]
    expressions += [validation['expression'] for validation in policy['spec']['validations']]
    environment = celpy.Environment(annotations=ANNOTATIONS)
    for expression in expressions:
        environment.compile(expression)
    return len(expressions)


def namespace(name='dw-one', labels=None, **metadata_fields):
    metadata = {'name': name}
    if labels is not None:
        metadata['labels'] = labels
    metadata.update(metadata_fields)
    return {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': metadata}


def profile(host_users):
    return {
        'apiVersion': 'apiextensions.crossplane.io/v1beta1',
        'kind': 'EnvironmentConfig',
        'metadata': {'name': 'developer-workspace-profile'},
        'data': {'profile': {'spec': {'hostUsers': host_users}}},
    }


def namespace_rule_matches(policy, operation, subresource=''):
    resource = 'namespaces' + (f'/{subresource}' if subresource else '')
    for rule in policy['spec']['matchConstraints']['resourceRules']:
        if (operation in rule['operations'] and resource in rule['resources'] and
                '' in rule['apiGroups'] and 'v1' in rule['apiVersions'] and
                rule.get('scope', '*') in ('*', 'Cluster')):
            return True
    return False


def admission(policy, operation, current, previous, username='workspace-user', operator=False,
              param=None, subresource=''):
    if not namespace_rule_matches(policy, operation, subresource):
        return []
    activation = {
        'object': current,
        'oldObject': previous,
        'request': {
            'operation': operation,
            'resource': {'group': '', 'version': 'v1', 'resource': 'namespaces'},
            'subResource': subresource,
            'userInfo': {'username': username},
        },
        'params': param,
        'variables': {},
        'authorizer': {'allow': operator},
    }
    if not all(evaluate(item['expression'], activation)
               for item in policy['spec']['matchConditions']):
        return []
    variables = {}
    for item in policy['spec']['variables']:
        activation['variables'] = variables
        variables[item['name']] = evaluate(item['expression'], activation)
    activation['variables'] = variables
    rejected = []
    for validation in policy['spec']['validations']:
        try:
            valid = evaluate(validation['expression'], activation)
        except celpy.CELEvalError:
            valid = False
        if not valid:
            rejected.append(validation['message'])
    return rejected


def expect_allowed(policy, description, **request):
    rejected = admission(policy, **request)
    assert rejected == [], f'{description} was rejected: {rejected}'


def expect_denied(policy, description, message, **request):
    rejected = admission(policy, **request)
    assert message in rejected, f'{description} was admitted: {rejected}'


def assert_manifests(label_documents, pod_documents):
    assert len(label_documents) == 3, 'Namespace label guard must contain one policy and two bindings'
    policy, *bindings = label_documents
    assert policy['kind'] == 'ValidatingAdmissionPolicy'
    assert policy['metadata']['name'] == POLICY_NAME
    assert policy['spec']['failurePolicy'] == 'Fail'
    assert policy['spec']['paramKind'] == {
        'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig'}
    # The API server type-checks params against the EnvironmentConfig schema, where `data` is a
    # free-form map that the checker does not expose as a field; only dyn(params) type-checks.
    expressions = [v['expression'] for v in policy['spec'].get('variables', [])]
    expressions += [v['expression'] for v in policy['spec']['validations']]
    raw = [e for e in expressions if re.search(r'(?<!dyn\()params\.', e)]
    assert not raw, f'params field access must go through dyn(params): {raw[0][:120]}'
    rule = policy['spec']['matchConstraints']['resourceRules']
    assert rule == [{
        'apiGroups': [''], 'apiVersions': ['v1'],
        'operations': ['CREATE', 'UPDATE', 'DELETE'],
        'resources': ['namespaces', 'namespaces/status', 'namespaces/finalize'],
        'scope': 'Cluster',
    }], 'Namespace guard must cover create/update/delete and both Namespace subresources'
    for subresource in ('', 'status', 'finalize'):
        assert namespace_rule_matches(policy, 'UPDATE', subresource), \
            f'Namespace {subresource or "main"} UPDATE must match the guard'
    assert namespace_rule_matches(policy, 'CREATE'), 'Namespace CREATE must match the guard'
    assert namespace_rule_matches(policy, 'DELETE'), 'Namespace DELETE must match the guard'
    match = normalized(policy['spec']['matchConditions'][0]['expression'])
    assert match.count(ID_LABEL) == 2 and match.count(HOST_USERS_LABEL) == 2, \
        'Namespace match must inspect both protected labels on oldObject and object'
    variables = {item['name']: normalized(item['expression'])
                 for item in policy['spec']['variables']}
    assert '!variables.provider' in variables['operator'], \
        'provider must be excluded from the operator authorization branch'
    assert ("authorizer.group('apiextensions.crossplane.io').resource('environmentconfigs'). "
            "name('developer-workspace-profile').check('update').allowed()"
            in variables['operator']), 'operator authority must use the named profile update check'
    messages = {item['message'] for item in policy['spec']['validations']}
    assert messages == {PROFILE_MESSAGE, PROVIDER_MESSAGE, CREATE_MESSAGE, UPDATE_MESSAGE,
                        DELETE_MESSAGE}, 'Namespace guard validations changed unexpectedly'
    for binding, label, name in zip(bindings, (ID_LABEL, HOST_USERS_LABEL),
                                    (POLICY_NAME, POLICY_NAME + '-selection')):
        assert binding == {
            'apiVersion': 'admissionregistration.k8s.io/v1',
            'kind': 'ValidatingAdmissionPolicyBinding',
            'metadata': {'name': name},
            'spec': {
                'policyName': POLICY_NAME,
                'matchResources': {'objectSelector': {'matchExpressions': [
                    {'key': label, 'operator': 'Exists'}]}},
                'paramRef': {'name': 'developer-workspace-profile',
                             'parameterNotFoundAction': 'Deny'},
                'validationActions': ['Deny'],
            },
        }, 'Namespace guard binding must select a protected label and fail closed on the named profile'

    assert len(pod_documents) == 2, 'Pod guard must contain one policy and one binding'
    pod_policy, pod_binding = pod_documents
    pod_rule = pod_policy['spec']['matchConstraints']['resourceRules'][0]
    assert pod_policy['spec']['failurePolicy'] == 'Fail'
    assert pod_rule['operations'] == ['CREATE', 'UPDATE']
    assert pod_rule['resources'] == ['pods', 'pods/ephemeralcontainers'], \
        'Pod guard must cover pods/ephemeralcontainers'
    assert pod_policy['spec']['matchConstraints']['namespaceSelector']['matchLabels'] == {
        HOST_USERS_LABEL: 'false'}
    assert pod_binding['spec'] == {
        'policyName': 'workspace-pod-user-namespace-required',
        'validationActions': ['Deny'],
    }
    assert evaluate(pod_policy['spec']['validations'][0]['expression'], {
        'object': {'spec': {'hostUsers': False}}, 'oldObject': None, 'request': {},
        'params': None, 'variables': {}, 'authorizer': {'allow': False}})
    assert not evaluate(pod_policy['spec']['validations'][0]['expression'], {
        'object': {'spec': {'hostUsers': True}}, 'oldObject': None, 'request': {},
        'params': None, 'variables': {}, 'authorizer': {'allow': False}})


def check(label_documents, pod_documents):
    assert_manifests(label_documents, pod_documents)
    policy = label_documents[0]
    compiled = compile_policy(policy)
    print(f'PASS manifest: Fail/Deny label guard, profile param, Namespace subresources, and '
          f'pods/ephemeralcontainers ({compiled} exact CEL expressions compile)')

    ws_false = {ID_LABEL: 'ws-one', HOST_USERS_LABEL: 'false'}
    expect_denied(policy, 'provider CREATE without host-users=false', PROVIDER_MESSAGE,
                  operation='CREATE', current=namespace(labels={ID_LABEL: 'ws-one'}), previous=None,
                  username=PROVIDER, param=profile(False))
    expect_denied(policy, 'provider CREATE with host-users=true', PROVIDER_MESSAGE,
                  operation='CREATE', current=namespace(labels={ID_LABEL: 'ws-one',
                                                                 HOST_USERS_LABEL: 'true'}),
                  previous=None, username=PROVIDER, param=profile(False))
    expect_allowed(policy, 'provider CREATE rendered for hostUsers=false', operation='CREATE',
                   current=namespace(labels=ws_false), previous=None, username=PROVIDER,
                   param=profile(False))
    expect_allowed(policy, 'provider CREATE rendered for hostUsers=true', operation='CREATE',
                   current=namespace(labels={ID_LABEL: 'ws-one'}), previous=None,
                   username=PROVIDER, param=profile(True))
    expect_denied(policy, 'provider CREATE retaining host-users for hostUsers=true',
                  PROVIDER_MESSAGE, operation='CREATE', current=namespace(labels=ws_false),
                  previous=None, username=PROVIDER, param=profile(True))
    expect_denied(policy, 'provider UPDATE changing workspace identity', PROVIDER_MESSAGE,
                  operation='UPDATE', current=namespace(labels={ID_LABEL: 'ws-two',
                                                                 HOST_USERS_LABEL: 'false'}),
                  previous=namespace(labels=ws_false), username=PROVIDER, param=profile(False))
    expect_denied(policy, 'provider UPDATE dropping workspace identity', PROVIDER_MESSAGE,
                  operation='UPDATE', current=namespace(labels={HOST_USERS_LABEL: 'false'}),
                  previous=namespace(labels=ws_false), username=PROVIDER, param=profile(False))
    expect_denied(policy, 'provider UPDATE dropping host-users for hostUsers=false',
                  PROVIDER_MESSAGE, operation='UPDATE',
                  current=namespace(labels={ID_LABEL: 'ws-one'}),
                  previous=namespace(labels=ws_false), username=PROVIDER, param=profile(False))
    expect_denied(policy, 'provider UPDATE setting host-users=true for hostUsers=false',
                  PROVIDER_MESSAGE, operation='UPDATE',
                  current=namespace(labels={ID_LABEL: 'ws-one', HOST_USERS_LABEL: 'true'}),
                  previous=namespace(labels=ws_false), username=PROVIDER, param=profile(False))
    expect_allowed(policy, 'provider UPDATE removes host-users after profile changes to true',
                   operation='UPDATE', current=namespace(labels={ID_LABEL: 'ws-one'}),
                   previous=namespace(labels=ws_false), username=PROVIDER, param=profile(True))
    print('PASS provider: only the profile-rendered host-users value is admitted; workspace id is '
          'present and immutable')

    expect_denied(policy, 'nonoperator UPDATE dropping host-users', UPDATE_MESSAGE,
                  operation='UPDATE', current=namespace(labels={ID_LABEL: 'ws-one'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator UPDATE dropping both protected labels', UPDATE_MESSAGE,
                  operation='UPDATE', current=namespace(labels={'other': 'kept'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator status UPDATE dropping both protected labels',
                  UPDATE_MESSAGE, operation='UPDATE', subresource='status',
                  current=namespace(labels={'other': 'kept'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator finalize UPDATE changing workspace id', UPDATE_MESSAGE,
                  operation='UPDATE', subresource='finalize',
                  current=namespace(labels={ID_LABEL: 'ws-two', HOST_USERS_LABEL: 'false'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator UPDATE changing host-users to true', UPDATE_MESSAGE,
                  operation='UPDATE',
                  current=namespace(labels={ID_LABEL: 'ws-one', HOST_USERS_LABEL: 'true'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator UPDATE changing workspace id', UPDATE_MESSAGE,
                  operation='UPDATE', current=namespace(labels={ID_LABEL: 'ws-two',
                                                                 HOST_USERS_LABEL: 'false'}),
                  previous=namespace(labels=ws_false), param=profile(False))
    expect_denied(policy, 'nonoperator UPDATE adding a protected label', UPDATE_MESSAGE,
                  operation='UPDATE', current=namespace(labels={HOST_USERS_LABEL: 'false'}),
                  previous=namespace(labels={'other': 'kept'}), param=profile(False))
    expect_allowed(policy, 'nonoperator UPDATE preserving protected labels', operation='UPDATE',
                   current=namespace(labels={**ws_false, 'other': 'changed'}),
                   previous=namespace(labels=ws_false), param=profile(False))
    expect_allowed(
        policy, 'nonoperator UPDATE changing ownerReferences and finalizers while preserving labels',
        operation='UPDATE',
        current=namespace(
            labels=ws_false,
            ownerReferences=[{'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': 'new-owner',
                              'uid': '22222222-2222-2222-2222-222222222222'}],
            finalizers=['example.invalid/new-finalizer']),
        previous=namespace(
            labels=ws_false,
            ownerReferences=[{'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': 'old-owner',
                              'uid': '11111111-1111-1111-1111-111111111111'}],
            finalizers=['example.invalid/old-finalizer']),
        param=profile(False))
    expect_denied(policy, 'nonoperator CREATE with protected labels', CREATE_MESSAGE,
                  operation='CREATE', current=namespace(labels=ws_false), previous=None,
                  param=profile(False))
    expect_denied(policy, 'nonoperator DELETE of workspace Namespace', DELETE_MESSAGE,
                  operation='DELETE', current=None, previous=namespace(labels=ws_false),
                  param=profile(False))
    print('PASS nonoperator: protected labels cannot be added, changed, or removed; delete is denied')

    expect_allowed(policy, 'operator UPDATE changing protected labels', operation='UPDATE',
                   current=namespace(labels={ID_LABEL: 'ws-renamed'}),
                   previous=namespace(labels=ws_false), operator=True, param=profile(True))
    expect_allowed(policy, 'operator status UPDATE dropping both protected labels',
                   operation='UPDATE', subresource='status', current=namespace(labels={}),
                   previous=namespace(labels=ws_false), operator=True, param=profile(True))
    expect_allowed(policy, 'operator finalize UPDATE changing workspace id',
                   operation='UPDATE', subresource='finalize',
                   current=namespace(labels={ID_LABEL: 'ws-renamed'}),
                   previous=namespace(labels=ws_false), operator=True, param=profile(True))
    expect_allowed(policy, 'operator DELETE', operation='DELETE', current=None,
                   previous=namespace(labels=ws_false), operator=True, param=profile(False))
    expect_allowed(policy, 'provider DELETE', operation='DELETE', current=None,
                   previous=namespace(labels=ws_false), username=PROVIDER, operator=True,
                   param=profile(False))
    expect_allowed(policy, 'namespace controller status update preserving labels',
                   operation='UPDATE', current=namespace(labels=ws_false),
                   previous=namespace(labels=ws_false),
                   username='system:serviceaccount:kube-system:namespace-controller',
                   param=profile(False))
    provider_variables = {item['name']: item['expression']
                          for item in policy['spec']['variables']}
    provider_operator = {
        'object': namespace(labels=ws_false), 'oldObject': namespace(labels=ws_false),
        'request': {'operation': 'UPDATE', 'userInfo': {'username': PROVIDER}},
        'params': profile(False), 'variables': {'provider': True},
        'authorizer': {'allow': True},
    }
    assert not evaluate(provider_variables['operator'], provider_operator), \
        'provider inherited operator authority from the authorizer check'
    print('PASS authority: named-profile update permission admits operators on Namespace, status, '
          'finalize and delete; the provider is excluded; label-preserving metadata changes remain possible')

    expect_denied(policy, 'string hostUsers profile', PROFILE_MESSAGE, operation='UPDATE',
                  current=namespace(labels=ws_false), previous=namespace(labels=ws_false),
                  param=profile('false'))
    print('PASS profile: malformed hostUsers is denied and a missing bound profile is configured '
          'to Deny')


STEERING_POLICY_NAME = 'developer-workspace-provider-steering'
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
NAMESPACE_GUARD_PROVIDER_EXPRESSION = (
    "request.userInfo.username == "
    "'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'"
)
NAMESPACE_GUARD_RESOURCES = {
    ('', 'namespaces'),
    ('', 'serviceaccounts'),
    ('', 'resourcequotas'),
    ('', 'limitranges'),
    ('', 'persistentvolumeclaims'),
    ('networking.k8s.io', 'networkpolicies'),
    ('apps', 'deployments'),
}
NAMESPACE_GUARD_MESSAGES = {
    'the DeveloperWorkspace provider may change or delete only Namespaces it created for a workspace',
    'the DeveloperWorkspace provider may write only into a Namespace created for the same workspace',
}


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


def guard_documents(path):
    loaded = list(yaml.safe_load_all(path.read_text()))
    assert len(loaded) == 2, f'{path.name} must contain one policy and one binding'
    policy, binding = loaded
    assert policy['kind'] == 'ValidatingAdmissionPolicy', f'{path.name} policy is missing'
    assert binding['kind'] == 'ValidatingAdmissionPolicyBinding', f'{path.name} binding is missing'
    return policy, binding


def steering_shape(policy, binding):
    assert policy['metadata']['name'] == STEERING_POLICY_NAME, 'provider-steering policy name changed'
    assert policy['spec']['failurePolicy'] == 'Fail', 'provider-steering policy must fail closed'
    assert binding['metadata']['name'] == STEERING_POLICY_NAME, 'provider-steering binding name changed'
    assert binding['spec']['policyName'] == STEERING_POLICY_NAME, 'provider-steering binding selects another policy'
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


def steering_authorizer_functions():
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
    return environment.program(environment.compile(expression), functions=steering_authorizer_functions())


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
    policy, binding = guard_documents(STEERING_GUARD)
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


def evaluate_program(program, values):
    activation = {
        key: value if isinstance(value, NullableMap) else json_to_cel(value)
        for key, value in values.items()
    }
    return bool(program.evaluate(activation))


def namespace_guard_shape(policy, binding):
    assert policy['metadata']['name'] == 'developer-workspace-namespace-guard'
    assert policy['spec']['failurePolicy'] == 'Fail'
    assert binding['metadata']['name'] == 'developer-workspace-namespace-guard'
    assert binding['spec'] == {
        'policyName': 'developer-workspace-namespace-guard',
        'validationActions': ['Deny'],
    }, 'namespace-guard binding must apply globally with Deny and no narrowing selectors'

    constraints = policy['spec']['matchConstraints']
    assert set(constraints) == {'resourceRules'}, \
        'namespace-guard matchConstraints must contain only resourceRules'
    actual = set()
    for rule in constraints['resourceRules']:
        assert len(rule['apiGroups']) == 1, 'namespace-guard rules must name one API group each'
        assert rule['apiVersions'] == ['v1'], 'namespace-guard rules must match only v1'
        assert set(rule['operations']) == {'CREATE', 'UPDATE', 'DELETE'}, \
            'namespace-guard rules must cover CREATE, UPDATE and DELETE'
        assert rule.get('scope', '*') == '*', 'namespace-guard resource scope must remain All'
        actual.update((rule['apiGroups'][0], resource) for resource in rule['resources'])
    assert actual == NAMESPACE_GUARD_RESOURCES, \
        f'namespace-guard resource set changed: extra={actual - NAMESPACE_GUARD_RESOURCES}, missing={NAMESPACE_GUARD_RESOURCES - actual}'

    conditions = policy['spec']['matchConditions']
    assert conditions == [{
        'name': 'provider-identity',
        'expression': NAMESPACE_GUARD_PROVIDER_EXPRESSION,
    }], 'namespace-guard must have exactly the provider identity match condition'
    assert policy['spec']['variables'] == [
        {'name': 'id', 'expression': "'workspace.openkubes.io/id'"},
        {'name': 'subject', 'expression': "request.operation == 'DELETE' ? oldObject : object"},
    ], 'namespace-guard variable definitions changed'
    validations = policy['spec']['validations']
    assert len(validations) == 2, 'namespace-guard must have exactly two validations'
    assert {item['message'] for item in validations} == NAMESPACE_GUARD_MESSAGES, \
        'namespace-guard validation messages changed'


def assert_namespace_shape_control_rejected(policy, binding, mutate, label):
    changed_policy = copy.deepcopy(policy)
    changed_binding = copy.deepcopy(binding)
    mutate(changed_policy, changed_binding)
    try:
        namespace_guard_shape(changed_policy, changed_binding)
    except AssertionError:
        return
    raise AssertionError(f'namespace-guard shape check admitted {label}')


def check_namespace_shape_negative_controls(policy, binding):
    controls = {
        'a second false matchCondition': lambda candidate, unused: candidate['spec'][
            'matchConditions'].append({'name': 'disabled', 'expression': 'false'}),
        'a narrowed binding': lambda unused, candidate: candidate['spec'].__setitem__(
            'matchResources', {'namespaceSelector': {'matchLabels': {'bypass': 'true'}}}),
        'a dropped Namespace resource': lambda candidate, unused: candidate['spec'][
            'matchConstraints']['resourceRules'][0]['resources'].remove('namespaces'),
        'an objectSelector': lambda candidate, unused: candidate['spec'][
            'matchConstraints'].__setitem__('objectSelector', {'matchLabels': {'bypass': 'true'}}),
        'excludeResourceRules': lambda candidate, unused: candidate['spec'][
            'matchConstraints'].__setitem__(
                'excludeResourceRules', copy.deepcopy(
                    candidate['spec']['matchConstraints']['resourceRules'])),
        'Namespaced scope': lambda candidate, unused: candidate['spec'][
            'matchConstraints']['resourceRules'][0].__setitem__('scope', 'Namespaced'),
        'a changed provider condition': lambda candidate, unused: candidate['spec'][
            'matchConditions'][0].__setitem__('expression', 'true'),
        'one validation': lambda candidate, unused: candidate['spec'][
            'validations'].pop(),
    }
    for label, mutate in controls.items():
        assert_namespace_shape_control_rejected(policy, binding, mutate, label)


def check_namespace_guard(disable_scope=False):
    policy, binding = guard_documents(NAMESPACE_GUARD)
    if disable_scope:
        policy['spec']['matchConstraints']['resourceRules'][0]['resources'].remove('namespaces')
    namespace_guard_shape(policy, binding)
    check_namespace_shape_negative_controls(policy, binding)

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
    assert evaluate_program(condition, {'request': provider_request})
    assert not evaluate_program(condition, {'request': other_request})

    validations = [cel_program(item['expression'], map_annotations) for item in policy['spec']['validations']]
    workspace_labels = {'workspace.openkubes.io/id': 'ws-one'}
    namespace = {'metadata': {'labels': workspace_labels}}
    matching_object = {'metadata': {'labels': workspace_labels}}
    mismatched_object = {'metadata': {'labels': {'workspace.openkubes.io/id': 'ws-two'}}}
    namespace_request = copy.deepcopy(provider_request)
    namespaced_request = copy.deepcopy(provider_request)
    namespaced_request['resource']['resource'] = 'serviceaccounts'
    variables = {'id': 'workspace.openkubes.io/id', 'subject': matching_object}

    assert evaluate_program(validations[0], {
        'request': namespace_request, 'object': namespace, 'oldObject': namespace,
        'namespaceObject': {}, 'variables': variables,
    })
    namespace_update = copy.deepcopy(namespace_request)
    namespace_update['operation'] = 'UPDATE'
    assert not evaluate_program(validations[0], {
        'request': namespace_update, 'object': {'metadata': {}}, 'oldObject': {'metadata': {}},
        'namespaceObject': {}, 'variables': variables,
    })
    assert evaluate_program(validations[1], {
        'request': namespace_request, 'object': namespace, 'oldObject': namespace,
        'namespaceObject': {}, 'variables': variables,
    })
    assert evaluate_program(validations[1], {
        'request': namespaced_request, 'object': matching_object, 'oldObject': matching_object,
        'namespaceObject': NullableMap(json_to_cel(namespace)), 'variables': variables,
    })
    variables['subject'] = mismatched_object
    assert not evaluate_program(validations[1], {
        'request': namespaced_request, 'object': mismatched_object, 'oldObject': mismatched_object,
        'namespaceObject': NullableMap(json_to_cel(namespace)), 'variables': variables,
    })
    print('PASS namespace guard shape: exact provider condition, global binding, 7-resource scope and 2 validations')
    print('PASS namespace guard match controls: conditions, selectors, exclusions, scope and resources cannot narrow enforcement')
    print('PASS namespace guard CEL: provider match, unlabeled Namespace denial and label-match paths evaluated')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--disable-label-guard', action='store_true',
                        help='mutation proof: replace the provider label expression with true')
    parser.add_argument('--disable-nonoperator-label-guard', action='store_true',
                        help='mutation proof: replace the nonoperator update expression with true')
    parser.add_argument('--disable-ephemeralcontainers-scope', action='store_true',
                        help='mutation proof: remove pods/ephemeralcontainers from the Pod policy')
    parser.add_argument('--allow-missing-profile', action='store_true',
                        help='mutation proof: change parameterNotFoundAction from Deny to Allow')
    parser.add_argument(
        '--disable-provider-steering-policy', action='store_true',
        help='mutation proof: make the provider-steering validation allow every matched request')
    parser.add_argument(
        '--disable-namespace-guard-scope', action='store_true',
        help='mutation proof: remove Namespaces from the namespace-guard resource scope')
    args = parser.parse_args()
    label_documents = documents(LABEL_GUARD)
    pod_documents = documents(POD_GUARD)
    if args.disable_label_guard:
        provider_rules = [validation for validation in label_documents[0]['spec']['validations']
                          if validation['message'] == PROVIDER_MESSAGE]
        assert len(provider_rules) == 1, 'provider label-guard mutation found the wrong rule count'
        provider_rules[0]['expression'] = 'true'
    if args.disable_nonoperator_label_guard:
        update_rules = [validation for validation in label_documents[0]['spec']['validations']
                        if validation['message'] == UPDATE_MESSAGE]
        assert len(update_rules) == 1, 'nonoperator label-guard mutation found the wrong rule count'
        update_rules[0]['expression'] = 'true'
    if args.disable_ephemeralcontainers_scope:
        pod_documents[0]['spec']['matchConstraints']['resourceRules'][0]['resources'].remove(
            'pods/ephemeralcontainers')
    if args.allow_missing_profile:
        label_documents[1]['spec']['paramRef']['parameterNotFoundAction'] = 'Allow'
    try:
        check(label_documents, pod_documents)
        check_steering(args.disable_provider_steering_policy)
        check_namespace_guard(args.disable_namespace_guard_scope)
    except (AssertionError, KeyError, TypeError, celpy.CELEvalError, celpy.CELParseError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
