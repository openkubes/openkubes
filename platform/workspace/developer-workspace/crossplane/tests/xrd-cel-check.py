#!/usr/bin/env python3
"""Exercise DeveloperWorkspace XRD admission rules with a real CEL evaluator.

This is an offline expression check: it does not claim that an API server accepted the XRD or
regenerated its CRD. Install the pinned evaluator with:
  python3 -m pip install -r tests/cel-requirements.txt
"""
import argparse
import copy
import sys
from pathlib import Path

import yaml

try:
    import celpy
    from celpy.adapter import json_to_cel
except ModuleNotFoundError as error:
    print('FAIL cel-python is required; install tests/cel-requirements.txt', file=sys.stderr)
    raise SystemExit(2) from error


XRD = Path(__file__).resolve().parent.parent / 'xrd.yaml'
NAME_MESSAGE = "metadata.name must equal spec.workspaceID + '-xr'"
IMMUTABLE_MESSAGE = 'spec.workspaceID is immutable'
NAME_RULE = "self.metadata.name == self.spec.workspaceID + '-xr'"
IMMUTABLE_RULE = 'self.workspaceID == oldSelf.workspaceID'


def schema():
    document = yaml.safe_load(XRD.read_text())
    return document['spec']['versions'][0]['schema']['openAPIV3Schema']


def evaluate(rule, current, previous=None):
    annotations = {'self': celpy.celtypes.MapType, 'oldSelf': celpy.celtypes.MapType}
    environment = celpy.Environment(annotations=annotations)
    program = environment.program(environment.compile(rule))
    activation = {'self': json_to_cel(current)}
    if previous is not None:
        activation['oldSelf'] = json_to_cel(previous)
    return bool(program.evaluate(activation))


def compile_rule(rule):
    environment = celpy.Environment(
        annotations={'self': celpy.celtypes.MapType, 'oldSelf': celpy.celtypes.MapType})
    environment.compile(rule)


def failures(current, previous, root_rules, spec_rules):
    rejected = []
    for validation in root_rules:
        if not evaluate(validation['rule'], current, previous):
            rejected.append(validation['message'])
    for validation in spec_rules:
        if previous is None and 'oldSelf' in validation['rule']:
            continue  # Kubernetes transition rules run only when oldSelf exists.
        old_spec = previous['spec'] if previous is not None else None
        if not evaluate(validation['rule'], current['spec'], old_spec):
            rejected.append(validation['message'])
    return rejected


def workspace(workspace_id, name=None):
    return {
        'metadata': {'name': name if name is not None else workspace_id + '-xr'},
        'spec': {
            'workspaceID': workspace_id,
            'storage': {'mode': 'persistent'},
            'lifecycle': {
                'profile': 'persistent',
                'deletion': 'explicit',
                'evidence': {'exportBeforeCleanup': True},
            },
        },
    }


def check(disable_name_guard=False, disable_workspace_id_guard=False):
    xrd_schema = schema()
    root_rules = copy.deepcopy(xrd_schema['x-kubernetes-validations'])
    spec_rules = xrd_schema['properties']['spec']['x-kubernetes-validations']
    by_message = {rule['message']: rule['rule'] for rule in root_rules + spec_rules}
    assert by_message.get(NAME_MESSAGE) == NAME_RULE, \
        'canonical-name CEL guard is missing or changed'
    assert by_message.get(IMMUTABLE_MESSAGE) == IMMUTABLE_RULE, \
        'workspaceID immutability CEL guard is missing or changed'
    assert xrd_schema['properties']['spec']['properties']['workspaceID']['maxLength'] == 51, \
        'workspaceID maxLength must be 51 for bounded CEL cost'
    if disable_name_guard:
        mutated = [rule for rule in root_rules if rule['rule'] != NAME_RULE]
        assert len(root_rules) - len(mutated) == 1, 'name-guard mutation did not remove exactly one rule'
        root_rules = mutated
    if disable_workspace_id_guard:
        mutated = [rule for rule in spec_rules if rule['rule'] != IMMUTABLE_RULE]
        assert len(spec_rules) - len(mutated) == 1, \
            'workspaceID-guard mutation did not remove exactly one rule'
        spec_rules = mutated
    for validation in root_rules + spec_rules:
        compile_rule(validation['rule'])
    print(f'PASS CEL rules compile: {len(root_rules) + len(spec_rules)} exact XRD expressions')

    collision_id = 'ws-collision'
    first = workspace(collision_id)
    assert failures(first, None, root_rules, spec_rules) == [], 'canonical first XR was rejected'
    second = workspace(collision_id, 'collision-two')
    rejected = failures(second, None, root_rules, spec_rules)
    assert NAME_MESSAGE in rejected, f'second XR with duplicate workspaceID was admitted: {rejected}'
    assert first['metadata']['name'] != second['metadata']['name']
    print('PASS collision: canonical first XR is admitted; a distinct name with its workspaceID is rejected')

    canonical = workspace('ws-canonical')
    assert failures(canonical, None, root_rules, spec_rules) == [], 'canonical XR was rejected'
    print('PASS canonical: metadata.name == workspaceID + -xr is admitted')

    trailing_id = 'ws-' + 'a' * 47 + '-'
    assert len(trailing_id) == 51
    trailing = workspace(trailing_id)
    assert failures(trailing, None, root_rules, spec_rules) == [], 'longest trailing-hyphen ID was rejected'
    assert trailing['metadata']['name'].endswith('--xr')
    print('PASS boundary: 51-character trailing-hyphen workspaceID is admitted as a valid --xr name')

    previous = workspace('ws-stable')
    current = copy.deepcopy(previous)
    current['spec']['workspaceID'] = 'ws-changed'
    rejected = failures(current, previous, root_rules, spec_rules)
    assert IMMUTABLE_MESSAGE in rejected, f'workspaceID immutability guard did not reject update: {rejected}'
    assert failures(previous, previous, root_rules, spec_rules) == [], 'unchanged workspaceID update was rejected'
    print('PASS update: changed workspaceID is rejected and unchanged workspaceID is admitted')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--disable-name-guard', action='store_true',
                        help='mutation proof: remove the name guard so the collision assertion fails')
    parser.add_argument('--disable-workspace-id-guard', action='store_true',
                        help='mutation proof: remove immutability so the update assertion fails')
    args = parser.parse_args()
    try:
        check(args.disable_name_guard, args.disable_workspace_id_guard)
    except (AssertionError, celpy.CELEvalError, celpy.CELParseError) as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
