#!/usr/bin/env python3
"""Keep the documented OK-185 trust/scope decisions explicit alongside the guard.

These checks verify documentation coverage, not RBAC or API-server enforcement. CEL and
the live proof exercise the corresponding behavior; this check prevents omission of the
chosen documented boundaries when the guard or README is edited.
"""
import argparse
from pathlib import Path
import re
import sys

CAPABILITY = Path(__file__).resolve().parents[1]
TRUSTED = ('system:masters', 'crossplane-system:crossplane',
           'kube-system:generic-garbage-collector', 'crossplane:masters')


def section(text, start, end):
    assert start in text and end in text, f'missing documented section {start}'
    return text.split(start, 1)[1].split(end, 1)[0]


def check_scope(readme, comment):
    scope = section(readme, '**Label trust boundary.**', '**One workspace shape per cluster.**')
    for term in ('labels only', '`ownerReferences`', '`finalizers`', 'garbage collection',
                 'reserve Namespace mutation permissions', 'roles grant none'):
        assert term in scope, f'finding 2: label-only boundary must disclose {term}'
    for term in ('labels only', 'ownerReferences/finalizers', 'trusted garbage collector',
                 'workspace/observer roles grant no such authority'):
        assert term in comment, f'finding 2: guard comment must disclose {term}'
    assert not re.search(r'guard (?:protects|prevents changes to) (?:all|every) Namespace metadata', scope), \
        'finding 2: guard must not claim to protect all Namespace metadata'


def check_trust(readme, comment):
    trust = section(readme, '**Trusted Namespace label operators.**', '`authority-indirect-who-can` checks')
    rows = [line for line in trust.splitlines() if line.startswith('|')]
    for subject in TRUSTED:
        assert any(f'`{subject}`' in row for row in rows), \
            f'finding 3: missing trusted-identity table row {subject}'
        assert subject in comment, f'finding 3: missing trusted guard comment identity {subject}'
    for term in ('intentionally satisfy the exemption', 'not an assertion that they lack Namespace',
                 'explicitly excluded', 'impersonation'):
        assert term in trust, f'finding 3: incomplete operator trust explanation: {term}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disable-ownerreference-disclosure', action='store_true')
    parser.add_argument('--disable-platform-trust-disclosure', action='store_true')
    parser.add_argument('--readme', type=Path, default=CAPABILITY / 'README.md')
    parser.add_argument('--guard', type=Path, default=CAPABILITY / 'install/namespace-host-users-guard.yaml')
    args = parser.parse_args()
    readme = args.readme.read_text()
    comment = '\n'.join(line[1:].strip() for line in args.guard.read_text().splitlines() if line.startswith('#'))
    if args.disable_ownerreference_disclosure:
        readme = readme.replace('`ownerReferences`', 'ownership metadata')
    if args.disable_platform_trust_disclosure:
        readme = '\n'.join(line for line in readme.splitlines()
                           if not (line.startswith('|') and '`kube-system:generic-garbage-collector`' in line))
    try:
        check_scope(readme, comment)
        check_trust(readme, comment)
    except AssertionError as error:
        print(f'FAIL {error}', file=sys.stderr)
        return 1
    print('PASS finding 2 documentation: label-only scope, ownerReference/finalizer and trusted GC path')
    print('PASS finding 3 documentation: named platform identities explicitly trusted in table and guard comment')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
