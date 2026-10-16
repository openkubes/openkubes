#!/usr/bin/env python3
"""Live proof of the DeveloperWorkspace reconciler path (OK-175).

The OK-174 harness applied render() output itself. Here a DeveloperWorkspace XR is applied and
Crossplane, function-go-templating and provider-kubernetes reconcile it. The proof requires:
  - the reconciled Namespace objects equal the capability reference rendering for the same inputs;
  - the checkout is the declared revision and the XR is Ready only once the workspace runs;
  - no ambient Kubernetes authority (no token, discovery-only RBAC, API unreachable);
  - no push or merge authority: the runtime has no source credential, the workspace credential
    is refused for push by the source, and a write-credential control push succeeds;
  - workspace identity collisions are refused without changing or deleting the owner;
  - operator and observer identities stay inside their documented authority boundary;
  - deleting the XR removes the Namespace and every composed object.
Every denial has a control that shows the same check passes when the authority exists.

Actions: install | run | up | down | uninstall. Mutation requires an explicit KUBECONFIG whose current
context is TARGET_CONTEXT and one of the disposable targets below.
"""
from __future__ import annotations
import argparse, base64, copy, errno, hashlib, importlib.util, json, os, re, secrets, subprocess, sys, time
from datetime import datetime, timezone
import shlex
from pathlib import Path
import yaml

HERE = Path(__file__).resolve().parent
CAPABILITY = HERE.parents[1]
REPO = CAPABILITY.parents[3]
LIVE = REPO / 'architecture/spikes/ADR-Platform-039/live'
EVIDENCE = CAPABILITY / 'evidence'
DISPOSABLE_CONTEXTS = ('ok-175-proof-admin@ok-175-proof', 'ok-176-c3-admin@ok-176-c3',
                       'ok-178-ws-admin@ok-178-ws', 'kind-ok175-preflight')
CROSSPLANE_CHART = ('https://charts.crossplane.io/stable', 'crossplane', '2.3.3')
POD_USER_NAMESPACE_POLICY = 'workspace-pod-user-namespace-required'
NAMESPACE_HOST_USERS_POLICY = 'developer-workspace-namespace-host-users-guard'
HOST_USERS_LABEL = 'workspace.openkubes.io/host-users'
WORKSPACE_ID_LABEL = 'workspace.openkubes.io/id'
ADMISSION_GUARDS = ('install/namespace-guard.yaml', 'install/provider-steering-guard.yaml',
                    'install/namespace-host-users-guard.yaml', 'install/pod-user-namespace-guard.yaml')
PROOF_NS = 'ok174-proof-services'  # the reviewed live profile's source destination
PULL_SECRET = 'workspace-registry-pull'
PERSISTENT = ('ws-ok175-proof-xr', 'ws-ok175-proof')
DISTINCT = (('ws-c69924-xr', 'ws-c69924'), ('ws-cd9634-xr', 'ws-cd9634'))
SQUAT = ('ws-ok175-squat-xr', 'ws-ok175-squat')
NO_PROFILE = ('ws-ok175-no-profile-xr', 'ws-ok175-no-profile')
RECEIPT_PROBES = (('ws-ok185-receipt-missing-xr', 'ws-ok185-receipt-missing'),
                  ('ws-ok185-receipt-wrong-xr', 'ws-ok185-receipt-wrong'))
OPERATOR_SA, OBSERVER_SA = 'developer-workspace-operator', 'developer-workspace-observer'
OPERATOR_BINDING, OBSERVER_BINDING = 'ok175-proof-developer-workspace-operator', 'ok175-proof-developer-workspace-observer'
LABEL_PROBE_ROLE, LABEL_PROBE_BINDING = 'ok185-namespace-label-probe', 'ok185-namespace-label-probe'
EPHEMERAL_PROBE_NS = 'ok185-ephemeralcontainers-proof'
PROVIDER_IDENTITY = 'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'
HANDS_ON = ('ws-hands-on-xr', 'ws-hands-on')
HANDS_ON_LABEL = 'workspace.openkubes.io/hands-on'
HANDS_ON_RUN = 'workspace.openkubes.io/hands-on-run'
STEERING_NS = 'ok175-provider-steering-proof'
STEERING_SA = 'provider-steering-nonoperator'
STEERING_POLICY = 'developer-workspace-provider-steering'
NAMESPACE_MUTATION_OPERATIONS = ('drop-both', 'change-id', 'status-drop-both',
                                 'finalize-drop-both', 'delete')
GIT_URL = 'https://git-fixture.ok174-proof-services.svc.cluster.local:8443/workspace-fixture.git'
KUBE_API = 'https://kubernetes.default.svc'
WRITE_CHUNK = 1024 * 1024

PROJECT_RESET_PY = r'''import fcntl, json, os, struct, sys
path = sys.argv[1]
fmt = '=IIIII8s'
size = struct.calcsize(fmt)
def ioctl(direction, number):
    return (direction << 30) | (size << 16) | (ord('X') << 8) | number
getxattr, setxattr = ioctl(2, 31), ioctl(1, 32)
fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
try:
    raw = bytearray(size)
    fcntl.ioctl(fd, getxattr, raw, True)
    values = list(struct.unpack(fmt, raw)); before = values[3]; values[3] = 0
    try:
        fcntl.ioctl(fd, setxattr, struct.pack(fmt, *values)); rejected, error = False, 0
    except OSError as exc:
        rejected, error = True, exc.errno
    raw = bytearray(size)
    fcntl.ioctl(fd, getxattr, raw, True); after = struct.unpack(fmt, raw)[3]
    print(json.dumps({'tool': 'python3-fcntl', 'before': before, 'after': after,
                      'rejected': rejected, 'errno': error}, sort_keys=True))
finally:
    os.close(fd)
    try: os.unlink(path)
    except FileNotFoundError: pass
'''

PROJECT_RESET_PL = r'''use strict;
use warnings;
use Fcntl qw(O_CREAT O_EXCL O_RDWR);
my $path = shift @ARGV;
defined $path or die "project probe path is required\n";
my $format = 'I5a8';
my $size = length(pack($format, (0) x 6));
$size == 28 or die "unexpected fsxattr size $size\n";
my $getxattr = (2 << 30) | ($size << 16) | (ord('X') << 8) | 31;
my $setxattr = (1 << 30) | ($size << 16) | (ord('X') << 8) | 32;
sub call_ioctl { return ioctl($_[0], $_[1], $_[2]); }
sysopen(my $fh, $path, O_RDWR | O_CREAT | O_EXCL, 0600) or die "create project probe: $!\n";
my ($before, $after, $rejected, $error_number);
my $error = '';
eval {
    my $before_buffer = pack($format, (0) x 6);
    defined(call_ioctl($fh, $getxattr, $before_buffer)) or die "FS_IOC_FSGETXATTR before: $!\n";
    my @values = unpack($format, $before_buffer);
    $before = $values[3];
    $values[3] = 0;
    my $requested = pack($format, @values);
    $! = 0;
    my $set_ok = defined(call_ioctl($fh, $setxattr, $requested));
    $error_number = $set_ok ? 0 : 0 + $!;
    $rejected = $set_ok ? 0 : 1;
    my $after_buffer = pack($format, (0) x 6);
    defined(call_ioctl($fh, $getxattr, $after_buffer)) or die "FS_IOC_FSGETXATTR after: $!\n";
    my @after_values = unpack($format, $after_buffer);
    $after = $after_values[3];
    1;
} or $error = $@ || "project ioctl probe failed\n";
close($fh) or $error ||= "close project probe: $!\n";
unlink($path) or $error ||= "unlink project probe: $!\n";
die $error if length($error);
printf qq|{"after":%u,"before":%u,"errno":%u,"rejected":%s,"tool":"perl-ioctl"}\n|,
    $after, $before, $error_number, $rejected ? 'true' : 'false';
'''

MARKER_WRITE_JS = r'''const fs=require('fs'),c=require('crypto'),v=process.argv[1],p=process.argv[2];
let fd,created=false,keep=false;
try {
  fd=fs.openSync(p,'wx',0o600); created=true; fs.writeFileSync(fd,v+'\n'); fs.fsyncSync(fd);
  fs.closeSync(fd); fd=undefined; console.log(c.createHash('sha256').update(fs.readFileSync(p)).digest('hex')); keep=true;
} finally {
  if(fd!==undefined) try{fs.closeSync(fd)}catch(_){}
  if(created&&!keep) try{fs.unlinkSync(p)}catch(_){}
}
'''

MARKER_READ_JS = r'''const fs=require('fs'),c=require('crypto'),p=process.argv[1];
try { console.log(c.createHash('sha256').update(fs.readFileSync(p)).digest('hex')); }
finally { fs.unlinkSync(p); }
'''

CAPACITY_PROBE_JS = r'''const fs = require('fs');
const root = '/workspace', path = root + '/.ok176-capacity-probe';
const limit = Number(process.argv[2]), requested = limit + Math.floor(limit / 4), chunkSize = 1024 * 1024;
function allocated(p, seen, exclude) {
  if (p === exclude) return 0n;
  const st = fs.lstatSync(p, {bigint: true}), key = st.dev + ':' + st.ino;
  if (seen.has(key)) return 0n;
  seen.add(key); let total = st.blocks * 512n;
  if (st.isDirectory()) for (const name of fs.readdirSync(p)) total += allocated(p + '/' + name, seen, exclude);
  return total;
}
const baseline = allocated(root, new Set(), path), beforeFs = fs.statfsSync(root, {bigint: true});
const availableBefore = beforeFs.bavail * beforeFs.bsize, reportedCapacityBefore = beforeFs.blocks * beforeFs.bsize, block = Buffer.alloc(chunkSize);
let fd, created = false, written = 0, error = null, result;
try {
  fd = fs.openSync(path, 'wx', 0o600); created = true;
  while (written < requested) {
    const wanted = Math.min(chunkSize, requested - written);
    try {
      const n = fs.writeSync(fd, block, 0, wanted);
      if (n === 0) { error = 'SHORT_WRITE'; break; }
      written += n; fs.fsyncSync(fd);
    } catch (e) { error = e.code || String(e); break; }
  }
  fs.closeSync(fd); fd = undefined;
  const file = fs.lstatSync(path, {bigint: true}), afterFs = fs.statfsSync(root, {bigint: true});
  result = {requestedBytes: requested, writtenBytes: written, probeAllocatedBytes: Number(file.blocks * 512n),
    baselineAllocatedBytes: Number(baseline), totalAllocatedBytes: Number(allocated(root, new Set(), null)),
    availableBeforeBytes: Number(availableBefore), availableAfterBytes: Number(afterFs.bavail * afterFs.bsize),
    reportedCapacityBeforeBytes: Number(reportedCapacityBefore), reportedCapacityAfterBytes: Number(afterFs.blocks * afterFs.bsize), error};
} finally {
  if (fd !== undefined) try { fs.closeSync(fd); } catch (_) {}
  if (created) try { fs.unlinkSync(path); } catch (_) {}
}
console.log(JSON.stringify(result));
'''

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path); module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module; spec.loader.exec_module(module); return module  # dataclasses resolve their module by name

spike = load_module('ok174_live_proof', LIVE / 'probes/live_proof.py')  # reused helpers only; the spike is not modified
render_profile = load_module('ok175_profile', CAPABILITY / 'tests/profile_config.py')

class ProofError(RuntimeError): pass
def expect(ok, message):
    if not ok: raise ProofError(message)
def is_not_found(done): return done.returncode != 0 and bool(re.search(r'\(NotFound\):', done.stderr))
def sha(data): return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
def sha_json(value): return sha(json.dumps(value, sort_keys=True, separators=(',', ':')))
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def storage_inputs(environ=None):
    env = os.environ if environ is None else environ
    expect(not any(k in env for k in ('OK176_STORAGE_CLASS', 'OK176_HOST_USERS', 'OK176_CAPACITY_MODE')),
           'use OK176_PROFILE_FILE; storage and enforcement mode must come from the profile declaration')
    path = env.get('OK176_PROFILE_FILE', '')
    expect(bool(path), 'OK176_PROFILE_FILE must name the operator-owned capability profile')
    try:
        profile = yaml.safe_load(Path(path).read_text())
        capacity = render_profile.validate_capacity(profile)
        # Validate the entire profile before any cluster operation; image is pinned below.
        render_profile.reference_render(yaml.safe_load((LIVE / 'profile/developer-workspace-live.yaml').read_text()), profile)
    except Exception as error:
        raise ProofError(f'invalid OK176_PROFILE_FILE: {error}') from error
    p = profile['spec']
    mode = ('self-declared-negative' if p['storageClassName'] == 'local-path' else 'enforced') if capacity['runtimeEnforced'] else 'observed-negative'
    if mode == 'observed-negative':
        expect(p['hostUsers'] is True and p['storageClassName'] == 'local-path',
               'observed-negative proof requires local-path and hostUsers=true')
    return {'storageClassName': p['storageClassName'], 'hostUsers': p['hostUsers'], 'mode': mode,
            'declaration': copy.deepcopy(capacity), 'profile': profile}

def assert_capacity_marker(namespace, storage):
    declared = 'runtime-enforced' if storage['declaration']['runtimeEnforced'] else 'not-runtime-enforced'
    labels = get_json(['get', 'namespace', namespace])['metadata'].get('labels', {})
    expect(labels.get('workspace.openkubes.io/persistent-capacity') == declared,
           f'Namespace capacity declaration marker differs from {declared}')

def refuse_self_declared_capacity(storage, bring_up):
    """Exercise the real capacity assertion; a negative control never certifies a profile."""
    observation = {}; stage = 'workspace-readiness'
    try:
        doc, namespace, _ = bring_up(*PERSISTENT, 'persistent')
        assert_capacity_marker(namespace, storage)
        stage = 'persistent-capacity-enforced'
        limit = quantity_bytes(doc['spec']['storage']['size'])
        observation = capacity_probe(namespace, workspace_pod(namespace), limit)
        validate_enforced_capacity(observation, limit)
    except (ProofError, subprocess.TimeoutExpired) as error:
        # A blocked mount is a refusal, not an observed successful negative control.
        reason = str(error) if isinstance(error, ProofError) else 'workspace operation timed out'
    else:
        reason = 'negative-control backend unexpectedly satisfied the capacity assertion; review the deployment before certification'
    refusal = {'name': 'persistent-capacity-certification-refused', 'status': 'fail',
               'mode': storage['mode'], 'declaration': storage['declaration'],
               'failedCheck': 'persistent-capacity-enforced', 'stage': stage,
               'scope': 'negative control only; no capacity isolation certification',
               'reason': reason, 'observed': observation}
    print(json.dumps(refusal, sort_keys=True), flush=True)
    raise ProofError('persistent-capacity-enforced: certification refused for self-declared negative control')

def profile_readback(config, previous=None):
    """Bind proof mode to persisted operator configuration and refuse drift or replacement."""
    live = get_json(['get', 'environmentconfig/developer-workspace-profile'])
    expect(live.get('data') == config['data'], 'installed profile data differs from the selected operator declaration')
    render_profile.validate_capacity(live['data']['profile'])
    metadata = live.get('metadata', {})
    expect(bool(metadata.get('uid')) and bool(metadata.get('resourceVersion')), 'installed profile lacks UID/resourceVersion')
    snapshot = {'uid': metadata['uid'], 'resourceVersion': metadata['resourceVersion'], 'dataSha256': sha_json(live['data'])}
    if previous:
        expect(snapshot['uid'] == previous['uid'], 'installed profile was replaced during proof')
        expect(snapshot['dataSha256'] == previous['dataSha256'], 'installed profile declaration drifted during proof')
    return snapshot

def quantity_bytes(value):
    match = re.fullmatch(r'([1-9][0-9]*)(Mi|Gi)', value)
    expect(match is not None, f'unsupported storage quantity {value!r}; expected Mi or Gi')
    return int(match.group(1)) * 2 ** (20 if match.group(2) == 'Mi' else 30)

def uid_boundary(uid, mapping_text, host_users):
    entries = [tuple(int(x) for x in line.split()) for line in mapping_text.splitlines() if line.strip()]
    expect(entries and all(len(entry) == 3 and entry[2] > 0 for entry in entries), f'invalid runtime uid_map: {mapping_text!r}')
    match = next((entry for entry in entries if entry[0] <= uid < entry[0] + entry[2]), None)
    expect(match is not None, f'runtime uid {uid} is absent from uid_map')
    outside = match[1] + uid - match[0]
    if not host_users: expect(outside != uid, f'hostUsers=false runtime uid_map is identity-mapped for uid {uid}')
    return {'runtimeUID': uid, 'mappedHostUID': outside, 'uidMap': [list(entry) for entry in entries]}

def validate_project_reset(probe):
    expect(type(probe.get('before')) is int and probe['before'] > 0, f'project reset control lacks a nonzero project ID: {probe}')
    expect(probe.get('rejected') is True and probe.get('errno') == errno.EINVAL, f'project ID reset was not rejected with EINVAL (errno {errno.EINVAL}): {probe}')
    expect(probe.get('after') == probe['before'], f'project ID changed despite rejected reset: {probe}')

def validate_enforced_capacity(probe, limit):
    required = ('requestedBytes', 'writtenBytes', 'probeAllocatedBytes', 'baselineAllocatedBytes', 'totalAllocatedBytes', 'availableBeforeBytes', 'availableAfterBytes', 'reportedCapacityBeforeBytes', 'reportedCapacityAfterBytes')
    expect(all(type(probe.get(key)) is int and probe[key] >= 0 for key in required), f'capacity probe lacks numeric boundaries: {probe}')
    expect(probe['requestedBytes'] > limit, f'capacity probe did not request more than the {limit}-byte declaration')
    expect(probe.get('error') in ('ENOSPC', 'EDQUOT'), f'overfill was not rejected with ENOSPC or EDQUOT: {probe}')
    expect(probe['availableBeforeBytes'] >= max(WRITE_CHUNK, limit - probe['baselineAllocatedBytes'] - WRITE_CHUNK), f'volume lacked the declared free capacity before pressure: {probe}')
    expect(probe['writtenBytes'] >= max(WRITE_CHUNK, limit - probe['baselineAllocatedBytes'] - WRITE_CHUNK), f'capacity probe failed before filling the declared allocation: {probe}')
    expect(limit - WRITE_CHUNK <= probe['totalAllocatedBytes'] <= limit + WRITE_CHUNK, f'total allocated bytes are outside the one-write tolerance of the declaration: {probe}')
    expect(all(abs(probe[key] - limit) <= WRITE_CHUNK for key in ('reportedCapacityBeforeBytes', 'reportedCapacityAfterBytes')), f'statfs reported capacity is outside the one-write tolerance of the declaration: {probe}')
    expect(probe['availableAfterBytes'] <= WRITE_CHUNK, f'enforced volume still reports more than one write of available capacity: {probe}')

def validate_pod_user_namespace_admission(mode, namespace_labels, outcomes):
    """Interpret server dry-run results; kept pure so both assertion branches can be falsified offline."""
    expect(set(outcomes) == {'absent', 'true', 'false'}, f'incomplete Pod user-namespace probes: {sorted(outcomes)}')
    selected = namespace_labels.get(HOST_USERS_LABEL) == 'false'
    if mode == 'enforced':
        expect(selected, f'enforced workspace Namespace lacks {HOST_USERS_LABEL}=false')
        for value in ('absent', 'true'):
            result = outcomes[value]
            expect(result.returncode != 0 and POD_USER_NAMESPACE_POLICY in result.stderr,
                   f'hostUsers {value} Pod was not denied specifically by {POD_USER_NAMESPACE_POLICY}: rc={result.returncode} stderr={result.stderr.strip()[:200]}')
        allowed = outcomes['false']
        expect(allowed.returncode == 0, f'hostUsers false control Pod was not admitted: {allowed.stderr.strip()[:200]}')
    else:
        expect(HOST_USERS_LABEL not in namespace_labels, f'observed-negative workspace Namespace unexpectedly carries {HOST_USERS_LABEL}')
        for value, result in outcomes.items():
            expect(result.returncode == 0, f'unselected hostUsers {value} control Pod was not admitted: {result.stderr.strip()[:200]}')
    return {'policyName': POD_USER_NAMESPACE_POLICY, 'namespaceSelected': selected,
            'namespaceLabel': namespace_labels.get(HOST_USERS_LABEL),
            'returnCodes': {key: value.returncode for key, value in outcomes.items()}}

def validate_namespace_label_admission(mode, namespace_before, namespace_after, denied, allowed):
    """Require admission, rather than RBAC, to preserve the host-users selection label."""
    before_metadata = namespace_before.get('metadata', {})
    after_metadata = namespace_after.get('metadata', {})
    namespace_labels = before_metadata.get('labels', {})
    expected_value = 'false' if mode == 'enforced' else None
    expect(namespace_labels.get(HOST_USERS_LABEL) == expected_value and
           (mode == 'enforced' or HOST_USERS_LABEL not in namespace_labels),
           f'workspace Namespace has unexpected {HOST_USERS_LABEL} before label probes: {namespace_labels.get(HOST_USERS_LABEL)!r}')
    operations = ('remove', 'alter') if mode == 'enforced' else ('add-false', 'add-true')
    mutation_operations = (*operations, *NAMESPACE_MUTATION_OPERATIONS)
    expected_denied = {f'{identity}-{operation}' for identity in ('workspace', 'observer')
                       for operation in mutation_operations}
    expected_allowed = {f'operator-{operation}' for operation in mutation_operations}
    expected_allowed.update(f'{identity}-preserve' for identity in ('workspace', 'observer', 'operator'))
    expect(set(denied) == expected_denied,
           f'incomplete Namespace label denials: {sorted(denied)}')
    for name, result in denied.items():
        reason = ('only the DeveloperWorkspace provider or an operator may delete a protected workspace Namespace'
                  if name.endswith('-delete') else
                  'only an operator may change workspace identity or host-users Namespace labels')
        # RBAC first: an RBAC Forbidden never reaches admission, so it must not count as the policy.
        expect(not re.search(r'User .* cannot (update|patch|delete) resource "namespaces', result.stderr, re.I),
               f'{name} was denied by RBAC instead of {NAMESPACE_HOST_USERS_POLICY}: {result.stderr.strip()[:200]}')
        expect(result.returncode != 0 and NAMESPACE_HOST_USERS_POLICY in result.stderr and
               reason in result.stderr,
               f'{name} was not denied specifically by {NAMESPACE_HOST_USERS_POLICY}: '
               f'rc={result.returncode} stderr={result.stderr.strip()[:200]}')
    expect(set(allowed) == expected_allowed,
           f'incomplete Namespace label controls: {sorted(allowed)}')
    for name, result in allowed.items():
        expect(result.returncode == 0, f'{name} allowed control failed: {result.stderr.strip()[:200]}')
    expect(before_metadata.get('uid') and before_metadata.get('resourceVersion') and
           after_metadata.get('uid') == before_metadata.get('uid') and
           after_metadata.get('resourceVersion') == before_metadata.get('resourceVersion') and
           after_metadata.get('labels', {}) == namespace_labels,
           f'Namespace changed during server dry-run probes: before={before_metadata} after={after_metadata}')
    return {'policyName': NAMESPACE_HOST_USERS_POLICY, 'namespaceLabel': expected_value,
            'denied': sorted(denied), 'allowedControls': sorted(allowed),
            'namespaceUID': before_metadata['uid'],
            'namespaceResourceVersion': before_metadata['resourceVersion'],
            'dryRunUnchanged': True}

def validate_provider_label_reconcile(outcomes, labels_before, labels_after, expected_value):
    expect(set(outcomes) == {'drop', 'alter', 'preserve'}, f'incomplete provider label reconciles: {sorted(outcomes)}')
    reason = 'must preserve the workspace identity and render host-users from developer-workspace-profile'
    for variant in ('drop', 'alter'):
        outcome = outcomes[variant]
        expect(outcome.get('synced') is False and NAMESPACE_HOST_USERS_POLICY in outcome.get('message', '') and
               reason in outcome.get('message', ''),
               f'provider {variant} Object did not fail at the label guard: {outcome}')
    expect(outcomes['preserve'].get('synced') is True,
           f'provider rendered-value Object did not reconcile as an allowed control: {outcomes["preserve"]}')
    expect(labels_before == labels_after and labels_after.get(HOST_USERS_LABEL) == expected_value and
           (expected_value is not None or HOST_USERS_LABEL not in labels_after),
           f'provider label probes changed the Namespace: before={labels_before} after={labels_after}')
    return {'policyName': NAMESPACE_HOST_USERS_POLICY, 'deniedObjects': ['drop', 'alter'],
            'allowedControl': 'preserve', 'namespaceLabelsUnchanged': True,
            'probe': 'one standalone provider-kubernetes Object owns the rendered labels on an isolated Namespace; update omission tests SSA deletion; Object and Namespace are cleaned'}

def validate_ephemeralcontainers_admission(allowed, denied, authority, unchanged):
    """Interpret the Pod subresource proof independently of kubectl plumbing."""
    expect(allowed.returncode == 0, f'hostUsers=false ephemeralcontainers control was denied: {allowed.stderr.strip()[:200]}')
    expect(denied.returncode != 0 and POD_USER_NAMESPACE_POLICY in denied.stderr,
           f'legacy hostUsers=true Pod ephemeralcontainers update was not denied by {POD_USER_NAMESPACE_POLICY}: '
           f'rc={denied.returncode} stderr={denied.stderr.strip()[:200]}')
    expect(set(authority) == {'workspace', 'observer'}, f'incomplete ephemeralcontainers RBAC controls: {sorted(authority)}')
    for name, result in authority.items():
        expect(result.returncode != 0 and 'forbidden' in result.stderr.lower() and
               ('pods/ephemeralcontainers' in result.stderr or 'ephemeralcontainers' in result.stderr),
               f'{name} reached the ephemeralcontainers subresource: rc={result.returncode} stderr={result.stderr.strip()[:200]}')
    expect(unchanged == {'compliant': True, 'legacy': True},
           f'ephemeralcontainers dry-run changed a fixture Pod: {unchanged}')
    return {'policyName': POD_USER_NAMESPACE_POLICY, 'allowedControl': 'hostUsers=false',
            'deniedLegacy': 'hostUsers=true', 'rbacDenied': sorted(authority), 'dryRunUnchanged': unchanged}

def validate_install_admission_observation(outcomes):
    expect(set(outcomes) == {'provider-preserve', 'provider-alter', 'provider-adopt',
                             'pod-false', 'pod-true', 'pod-absent', 'missing-param', 'missing-param-unrelated'},
           f'incomplete install admission probes: {sorted(outcomes)}')
    for name in ('provider-preserve', 'pod-false', 'missing-param-unrelated'):
        expect(outcomes[name].returncode == 0, f'install allowed control {name} failed: {outcomes[name].stderr.strip()[:200]}')
    host_users = (NAMESPACE_HOST_USERS_POLICY, 'must preserve the workspace identity and render host-users')
    namespace_guard = ('developer-workspace-namespace-guard', 'may change or delete only Namespaces it created')
    pod_policy = (POD_USER_NAMESPACE_POLICY, 'must set spec.hostUsers to false')
    # Adoption is denied by both Namespace guards; the server reports whichever it evaluated first.
    expected = {'provider-alter': [host_users], 'provider-adopt': [namespace_guard, host_users],
                'pod-true': [pod_policy], 'pod-absent': [pod_policy]}
    for name, alternatives in expected.items():
        result = outcomes[name]
        expect(result.returncode != 0 and any(policy in result.stderr and reason in result.stderr for policy, reason in alternatives),
               f'install probe {name} was not denied by {" or ".join(p for p, _ in alternatives)}: rc={result.returncode} stderr={result.stderr.strip()[:200]}')
    missing = outcomes['missing-param']
    expect(missing.returncode != 0 and
           (NAMESPACE_HOST_USERS_POLICY in missing.stderr or 'no params' in missing.stderr.lower()),
           f'missing admission parameter did not fail closed: rc={missing.returncode} stderr={missing.stderr.strip()[:200]}')
    return {'allowed': ['provider-preserve', 'pod-false', 'missing-param-unrelated'],
            'denied': ['provider-alter', 'provider-adopt', 'pod-true', 'pod-absent', 'missing-param']}

def canonical_admission_spec(spec, binding=False):
    """Add only documented API defaults, then permit no other installed-spec difference."""
    value = copy.deepcopy(spec)
    match_key = 'matchResources' if binding else 'matchConstraints'
    match = value.setdefault(match_key, {})
    match.setdefault('matchPolicy', 'Equivalent')
    match.setdefault('namespaceSelector', {})
    match.setdefault('objectSelector', {})
    match.setdefault('resourceRules', [])
    match.setdefault('excludeResourceRules', [])
    for rule in [*match['resourceRules'], *match['excludeResourceRules']]: rule.setdefault('scope', '*')
    if not binding:
        value.setdefault('matchConditions', [])
        value.setdefault('variables', [])
        value.setdefault('auditAnnotations', [])
    return value

def admission_guard_documents(path):
    docs = [doc for doc in yaml.safe_load_all((CAPABILITY / path).read_text()) if doc]
    expect(len(docs) >= 2 and docs[0].get('kind') == 'ValidatingAdmissionPolicy' and
           all(doc.get('kind') == 'ValidatingAdmissionPolicyBinding' for doc in docs[1:]),
           f'{path} must contain one ValidatingAdmissionPolicy followed by one or more bindings')
    policy, bindings = docs[0], docs[1:]
    expect(len({binding.get('metadata', {}).get('name') for binding in bindings}) == len(bindings) and
           all(binding.get('spec', {}).get('policyName') == policy.get('metadata', {}).get('name') for binding in bindings),
           f'{path} bindings must be uniquely named and reference their policy')
    return policy, bindings

def validate_required_admission_guards(paths):
    expect(tuple(paths) == ('install/namespace-guard.yaml',
                            'install/provider-steering-guard.yaml',
                            'install/namespace-host-users-guard.yaml',
                            'install/pod-user-namespace-guard.yaml'),
           'admission gate must include collision, provider steering, Namespace label, and Pod guards in install order')

def validate_admission_policy_ready(policy, path):
    generation = policy.get('metadata', {}).get('generation')
    status = policy.get('status', {})
    expect(type(generation) is int and generation > 0, f'{path} installed policy lacks metadata.generation')
    expect(status.get('observedGeneration') == generation,
           f'{path} policy status observedGeneration {status.get("observedGeneration")!r} is not current generation {generation}')
    # The status controller writes observedGeneration and typeChecking together; on an in-place
    # update with no warnings it omits typeChecking, so a current observedGeneration is the signal.
    warnings = status.get('typeChecking') or {}
    expect(not warnings.get('expressionWarnings', []),
           f'{path} policy has type-check warnings: {warnings.get("expressionWarnings")}')
    return {'name': policy['metadata']['name'], 'generation': generation, 'typeCheckingWarnings': 0}

def admission_policies_match_local():
    """Fail closed unless every policy/binding is current and byte-equivalent at spec level."""
    validate_required_admission_guards(ADMISSION_GUARDS)
    observed = []
    for path in ADMISSION_GUARDS:
        policy, bindings = admission_guard_documents(path)
        name = policy['metadata']['name']
        live_policy = get_json(['get', 'validatingadmissionpolicy', name])
        expect(canonical_admission_spec(live_policy.get('spec', {})) == canonical_admission_spec(policy['spec']),
               f'installed admission policy differs from {path}')
        for binding in bindings:
            live_binding = get_json(['get', 'validatingadmissionpolicybinding', binding['metadata']['name']])
            expect(canonical_admission_spec(live_binding.get('spec', {}), binding=True) ==
                   canonical_admission_spec(binding['spec'], binding=True),
                   f'installed admission policy binding {binding["metadata"]["name"]} differs from {path}')
        observed.append(validate_admission_policy_ready(live_policy, path))
    return observed

def wait_for_admission_policies():
    def ready():
        try:
            admission_policies_match_local()
            return True
        except ProofError:
            return False
    wait_until('admission policies and bindings to be current and type-checked', ready, timeout=180, interval=2)
    return admission_policies_match_local()

def kubectl(args, *, input_text=None, timeout=120, check=True):
    done = subprocess.run(['kubectl', *args], input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and done.returncode:
        # kubectl prints advisory 'Warning:' lines first; keep them out of the truncated reason.
        errors = '\n'.join(l for l in done.stderr.splitlines() if not l.startswith('Warning:')).strip() or done.stderr.strip()
        raise ProofError(f"kubectl {' '.join(args[:3])} failed ({done.returncode}): {errors[:600]}")
    return done
def apply(objects): kubectl(['apply', '-f', '-'], input_text='---\n'.join(yaml.safe_dump(o, sort_keys=False) for o in objects))
def apply_file(path): kubectl(['apply', '-f', str(path)])
def get_json(args): return json.loads(kubectl([*args, '-o', 'json']).stdout)
def exec_in(namespace, pod, command, container=None, input_text=None):
    args = ['exec', *(['-i'] if input_text is not None else []), f'pod/{pod}', '-n', namespace, *(['-c', container] if container else []), '--', *command]
    return kubectl(args, input_text=input_text, check=False)
def project_reset_probe(namespace, pod):
    available = exec_in(namespace, pod, ['sh', '-c', 'if command -v python3 >/dev/null; then echo python3; elif command -v perl >/dev/null; then echo perl; else exit 127; fi'], 'runtime')
    expect(available.returncode == 0, 'runtime lacks python3 or perl required for the exact FS_IOC_FSSETXATTR errno probe')
    tool = available.stdout.strip()
    command, source = (['python3', '-', '/workspace/.ok176-project-probe'], PROJECT_RESET_PY) if tool == 'python3' else (['perl', '-', '/workspace/.ok176-project-probe'], PROJECT_RESET_PL)
    done = exec_in(namespace, pod, command, 'runtime', input_text=source)
    expect(done.returncode == 0, f'runtime project reset probe failed with {tool} (rc={done.returncode}): {done.stderr.strip()[:200]}')
    try: probe = json.loads(done.stdout)
    except json.JSONDecodeError as error: raise ProofError(f'runtime project reset probe returned invalid JSON: {error}') from error
    validate_project_reset(probe); return probe

def capacity_probe(namespace, pod, limit):
    done = exec_in(namespace, pod, ['node', '-', str(limit)], 'runtime', input_text=CAPACITY_PROBE_JS)
    expect(done.returncode == 0, f'runtime capacity probe failed (rc={done.returncode}): {done.stderr.strip()[:200]}')
    try: return json.loads(done.stdout)
    except json.JSONDecodeError as error: raise ProofError(f'runtime capacity probe returned invalid JSON: {error}') from error
def wait_until(what, predicate, timeout=600, interval=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(interval)
    raise ProofError(f'timed out waiting for {what}')

def target():
    path = os.environ.get('KUBECONFIG', ''); expect(path and os.pathsep not in path and Path(path).is_file(), 'KUBECONFIG must name exactly one readable file')
    context = kubectl(['config', 'current-context']).stdout.strip()
    expect(context == os.environ.get('TARGET_CONTEXT') and context in DISPOSABLE_CONTEXTS, f'current context {context!r} is not the selected disposable target')
    version = get_json(['version'])['serverVersion']['gitVersion']; uid = get_json(['get', 'namespace', 'kube-system'])['metadata']['uid']
    # A context name can be reused; the kube-system UID pins the one cluster the operator selected.
    expect(os.environ.get('OK175_TARGET_UID_SHA256') == sha(uid), 'OK175_TARGET_UID_SHA256 does not match the kube-system UID of the selected cluster')
    return {'context': context, 'kubernetesVersion': version, 'kubeSystemUidSha256': sha(uid)}

# Spike files this proof depends on: the render() oracle, the reused helpers and the live inputs.
SPIKE_INPUTS = ('verify_developer_workspace_v1.py', 'live/probes/live_proof.py', 'live/profile/namespace-profile-live.yaml',
                'live/profile/developer-workspace-live.yaml', 'live/fixtures/entrypoint.sh', 'live/fixtures/Dockerfile')

def implementation(require_clean):
    head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True, capture_output=True, check=True).stdout.strip()
    spike_paths = [LIVE.parent / x for x in SPIKE_INPUTS]
    dirty = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain', '--', str(CAPABILITY.relative_to(REPO)), *(str(x.relative_to(REPO)) for x in spike_paths), ':(exclude)' + str(EVIDENCE.relative_to(REPO))], text=True, capture_output=True, check=True).stdout
    expect(not (require_clean and dirty), 'capability directory or spike inputs have uncommitted changes')
    files = sorted(p for p in CAPABILITY.rglob('*') if p.is_file() and EVIDENCE not in p.parents and '__pycache__' not in p.parts)
    return {'head': head, 'clean': not dirty, 'files': {str(p.relative_to(CAPABILITY)): sha(p.read_bytes()) for p in files},
            'spikeInputs': {x: sha((LIVE.parent / x).read_bytes()) for x in SPIKE_INPUTS}}

def normalized_match_resources(value):
    normalized = copy.deepcopy(value or {})
    normalized.setdefault('matchPolicy', 'Equivalent')
    normalized.setdefault('namespaceSelector', {})
    normalized.setdefault('objectSelector', {})
    normalized.setdefault('resourceRules', [])
    normalized.setdefault('excludeResourceRules', [])
    # The API server defaults each rule's scope to "*" (seen live on an installed policy).
    for rules in (normalized['resourceRules'], normalized['excludeResourceRules']):
        for rule in rules:
            rule.setdefault('scope', '*')
    return normalized

def installed_matches_local():
    """The objects that ran must be the files the evidence hashes, not an earlier install."""
    local = lambda path: yaml.safe_load((CAPABILITY / path).read_text())
    composition = get_json(['get', 'composition', local('composition.yaml')['metadata']['name']])
    expect(composition['spec']['pipeline'] == local('composition.yaml')['spec']['pipeline'], 'installed Composition differs from composition.yaml')
    xrd = get_json(['get', 'compositeresourcedefinition', local('xrd.yaml')['metadata']['name']])
    expect(xrd['spec']['versions'][0]['schema'] == local('xrd.yaml')['spec']['versions'][0]['schema'], 'installed XRD schema differs from xrd.yaml')
    xrd_schema = local('xrd.yaml')['spec']['versions'][0]['schema']['openAPIV3Schema']
    generated_crd = get_json(['get', 'crd', 'developerworkspaces.workspace.openkubes.io'])
    generated_version = next(v for v in generated_crd['spec']['versions'] if v['name'] == 'v0alpha1')
    generated_schema = generated_version['schema']['openAPIV3Schema']
    expect(generated_schema.get('x-kubernetes-validations') == xrd_schema.get('x-kubernetes-validations'),
           'generated CRD root CEL validations differ from xrd.yaml')
    expect(generated_schema['properties']['spec'].get('x-kubernetes-validations') == xrd_schema['properties']['spec'].get('x-kubernetes-validations'),
           'generated CRD spec CEL validations differ from xrd.yaml')
    expect(generated_schema['properties']['spec']['properties']['workspaceID'].get('maxLength') ==
           xrd_schema['properties']['spec']['properties']['workspaceID'].get('maxLength') == 51,
           'generated CRD workspaceID maxLength differs from xrd.yaml or is not 51')
    role = next(d for d in yaml.safe_load_all((CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml').read_text()) if d['kind'] == 'ClusterRole')
    expect(get_json(['get', 'clusterrole', role['metadata']['name']])['rules'] == role['rules'], 'installed ClusterRole differs from rbac/')
    authority_roles = [d for d in yaml.safe_load_all((CAPABILITY / 'rbac/authority-boundary.yaml').read_text()) if d]
    expect({d['kind'] for d in authority_roles} == {'ClusterRole'}, 'authority-boundary.yaml must contain only ClusterRoles')
    for authority_role in authority_roles:
        live_role = get_json(['get', 'clusterrole', authority_role['metadata']['name']])
        expect(live_role['rules'] == authority_role['rules'], f"installed ClusterRole {authority_role['metadata']['name']} differs from authority-boundary.yaml")
    admission_policies_match_local()
    return composition

def gated_xr_request(args, document, check=True):
    """Re-check the complete local/current admission gate before dispatching an XR request."""
    composition = installed_matches_local()
    return composition, kubectl(args, input_text=yaml.safe_dump(document), check=check)

def revision_matches(xr_name, composition):
    ref = get_json(['get', f'developerworkspace/{xr_name}'])['spec']['crossplane']['compositionRevisionRef']['name']
    revision = get_json(['get', 'compositionrevision', ref])
    expect(revision['spec']['pipeline'] == composition['spec']['pipeline'], f'{xr_name} runs CompositionRevision {ref}, which differs from composition.yaml')
    return ref

def image(name):
    value = os.environ.get(name, ''); expect(bool(re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', value)), f'{name} must be a digest reference'); return value

def observe_installed_admission():
    """Exercise every installed guard before the capability CRDs can dispatch an XR."""
    namespace = 'ok185-admission-install-probe'
    profile = {'apiVersion': 'apiextensions.crossplane.io/v1beta1', 'kind': 'EnvironmentConfig',
               'metadata': {'name': 'developer-workspace-profile'},
               'data': {'profile': {'spec': {'hostUsers': False}}}}
    protected = {'apiVersion': 'v1', 'kind': 'Namespace',
                 'metadata': {'name': 'ok185-provider-install-probe',
                              'labels': {WORKSPACE_ID_LABEL: 'ws-ok185-install', HOST_USERS_LABEL: 'false'}}}
    outcomes = {}
    for resource, name in (('environmentconfig', 'developer-workspace-profile'), ('namespace', namespace)):
        existing = kubectl(['get', f'{resource}/{name}'], check=False)
        expect(existing.returncode != 0 and ('NotFound' in existing.stderr or "doesn't have a resource type" in existing.stderr),
               f'install admission fixture refuses to overwrite existing {resource}/{name}')
    existing_xrs = kubectl(['get', 'developerworkspaces', '-o', 'json'], check=False)
    expect((existing_xrs.returncode != 0 and "doesn't have a resource type" in existing_xrs.stderr) or
           (existing_xrs.returncode == 0 and not json.loads(existing_xrs.stdout)['items']),
           'install admission observation requires no existing DeveloperWorkspaces')
    apply([profile])
    try:
        def parameter_observed():
            outcomes['provider-preserve'] = kubectl(
                ['create', '--dry-run=server', '-f', '-', f'--as={PROVIDER_IDENTITY}'],
                input_text=yaml.safe_dump(protected), check=False)
            return outcomes['provider-preserve'].returncode == 0
        wait_until('admission parameter to be observed', parameter_observed, timeout=120, interval=2)
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': namespace}}])
        def provider_adopt_refused():
            adopted = get_json(['get', 'namespace', namespace]); adopted['metadata'].setdefault('labels', {})[WORKSPACE_ID_LABEL] = 'ws-ok185-adopt'
            adopted['metadata']['labels'][HOST_USERS_LABEL] = 'false'
            outcomes['provider-adopt'] = kubectl(
                ['replace', '--dry-run=server', '-f', '-', f'--as={PROVIDER_IDENTITY}'],
                input_text=yaml.safe_dump(replace_document(adopted)), check=False)
            # Both Namespace policies deny this adoption; the API server reports whichever it
            # evaluated first (seen live both ways), so either exact denial counts.
            stderr = outcomes['provider-adopt'].stderr
            return outcomes['provider-adopt'].returncode != 0 and any(
                policy in stderr and reason in stderr for policy, reason in (
                    ('developer-workspace-namespace-guard', 'may change or delete only Namespaces it created'),
                    (NAMESPACE_HOST_USERS_POLICY, 'must preserve the workspace identity and render host-users')))
        try:
            wait_until('provider adoption of an unowned Namespace to be denied', provider_adopt_refused, timeout=120, interval=2)
        except ProofError as error:
            last = outcomes.get('provider-adopt')
            detail = f' (last rc={last.returncode}, stderr={last.stderr.strip()[:400]!r})' if last else ''
            raise ProofError(f'{error}{detail}') from error
        kubectl(['label', 'namespace', namespace, f'{WORKSPACE_ID_LABEL}=ws-ok185-install', f'{HOST_USERS_LABEL}=false'])
        def behavior_observed():
            altered = copy.deepcopy(protected); altered['metadata']['labels'][HOST_USERS_LABEL] = 'true'
            outcomes['provider-alter'] = kubectl(
                ['create', '--dry-run=server', '-f', '-', f'--as={PROVIDER_IDENTITY}'],
                input_text=yaml.safe_dump(altered), check=False)
            for value in ('false', 'true', 'absent'):
                pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': f'ok185-install-{value}', 'namespace': namespace},
                       'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                                'containers': [{'name': 'probe', 'image': 'registry.k8s.io/pause:3.10'}]}}
                if value != 'absent': pod['spec']['hostUsers'] = value == 'true'
                outcomes[f'pod-{value}'] = kubectl(['create', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(pod), check=False)
            # missing-param is deliberately observed only after cleanup. Poll the other
            # outcomes here while API-server policy and parameter caches converge.
            return (outcomes['provider-preserve'].returncode == 0 and
                    outcomes['provider-alter'].returncode != 0 and NAMESPACE_HOST_USERS_POLICY in outcomes['provider-alter'].stderr and
                    outcomes['provider-adopt'].returncode != 0 and 'developer-workspace-namespace-guard' in outcomes['provider-adopt'].stderr and
                    outcomes['pod-false'].returncode == 0 and
                    all(outcomes[f'pod-{value}'].returncode != 0 and POD_USER_NAMESPACE_POLICY in outcomes[f'pod-{value}'].stderr
                        for value in ('true', 'absent')))
        wait_until('admission deny and allow behavior to be observed', behavior_observed, timeout=120, interval=2)
    finally:
        deleted_ns = kubectl(['delete', 'namespace', namespace, '--ignore-not-found', '--wait=true'], timeout=180, check=False)
        expect(deleted_ns.returncode == 0, f'install admission fixture Namespace cleanup failed: {deleted_ns.stderr.strip()[:200]}')
        deleted_profile = kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--ignore-not-found', '--wait=true'], check=False)
        expect(deleted_profile.returncode == 0, f'install admission profile cleanup failed: {deleted_profile.stderr.strip()[:200]}')
    for resource, name in (('namespace', namespace), ('environmentconfig', 'developer-workspace-profile')):
        gone = kubectl(['get', f'{resource}/{name}'], check=False)
        expect(gone.returncode != 0 and 'NotFound' in gone.stderr, f'install admission cleanup left {resource}/{name}')
    def missing_parameter_observed():
        outcomes['missing-param'] = kubectl(
            ['create', '--dry-run=server', '-f', '-', f'--as={PROVIDER_IDENTITY}'],
            input_text=yaml.safe_dump(protected), check=False)
        return outcomes['missing-param'].returncode != 0 and (
            NAMESPACE_HOST_USERS_POLICY in outcomes['missing-param'].stderr or 'no params' in outcomes['missing-param'].stderr.lower())
    wait_until('missing admission parameter to fail closed', missing_parameter_observed, timeout=120, interval=2)
    unrelated = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'ok185-unrelated-install-dry-run'}}
    outcomes['missing-param-unrelated'] = kubectl(
        ['create', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(unrelated), check=False)
    return validate_install_admission_observation(outcomes)

def invalidate_admission_ready():
    """Remove the provisioning receipt and prove it is absent before guard installation/removal."""
    name = render_profile.ADMISSION_READY_NAME
    deleted = kubectl(['delete', f'environmentconfig/{name}', '--ignore-not-found', '--wait=true'], check=False)
    expect(deleted.returncode == 0, f'deleting admission installation receipt failed: {deleted.stderr.strip()[:300]}')
    missing = kubectl(['get', f'environmentconfig/{name}'], check=False)
    expect(is_not_found(missing),
           f'admission installation receipt absence was not confirmed by NotFound: {missing.stderr.strip()[:300]}')

def admission_ready_readback():
    receipt = render_profile.admission_ready_config()
    live = get_json(['get', f'environmentconfig/{render_profile.ADMISSION_READY_NAME}'])
    expect(live.get('metadata', {}).get('name') == receipt['metadata']['name'] and
           live.get('data') == receipt['data'],
           f'admission installation receipt differs from {receipt}')
    return {'name': receipt['metadata']['name'], 'data': copy.deepcopy(receipt['data'])}

def publish_admission_ready():
    """Create the receipt only after the installed guards passed equality and behavior checks."""
    receipt = render_profile.admission_ready_config()
    apply([receipt])
    return admission_ready_readback()

def install(_args):
    validate_required_admission_guards(ADMISSION_GUARDS)
    target()
    repo, chart, version = CROSSPLANE_CHART
    subprocess.run(['helm', 'upgrade', '--install', 'crossplane', chart, '--repo', repo, '--version', version, '-n', 'crossplane-system', '--create-namespace', '--wait', '--timeout', '10m'], check=True)
    apply_file(CAPABILITY / 'tests/functions.yaml'); apply_file(CAPABILITY / 'install/provider-kubernetes.yaml')
    kubectl(['wait', '--for=condition=Healthy', 'function.pkg.crossplane.io/function-go-templating', 'function.pkg.crossplane.io/function-auto-ready', 'provider.pkg.crossplane.io/provider-kubernetes', '--timeout=600s'], timeout=630)
    apply_file(CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml'); apply_file(CAPABILITY / 'rbac/authority-boundary.yaml')
    invalidate_admission_ready()
    for path in ADMISSION_GUARDS: apply_file(CAPABILITY / path)
    apply_file(CAPABILITY / 'install/providerconfig.yaml')
    policies = wait_for_admission_policies()
    observed = observe_installed_admission()
    receipt = publish_admission_ready()
    apply_file(CAPABILITY / 'xrd.yaml')
    kubectl(['wait', '--for=condition=Established', 'compositeresourcedefinition/developerworkspaces.workspace.openkubes.io', '--timeout=300s'], timeout=330)
    apply_file(CAPABILITY / 'composition.yaml')
    print('installed Crossplane', version, 'with the DeveloperWorkspace capability; admission gate',
          json.dumps({'policies': policies, 'behavior': observed, 'receipt': receipt}, sort_keys=True))

def uninstall(_args):
    target()
    listed = kubectl(['get', 'developerworkspaces', '-o', 'json'], check=False)
    expect(listed.returncode != 0 and 'the server doesn' in listed.stderr or listed.returncode == 0 and not json.loads(listed.stdout)['items'], 'DeveloperWorkspaces still exist; delete them first')
    invalidate_admission_ready()
    for path in ('composition.yaml', 'xrd.yaml', 'install/providerconfig.yaml', *reversed(ADMISSION_GUARDS), 'rbac/authority-boundary.yaml', 'rbac/provider-kubernetes-clusterrole.yaml', 'install/provider-kubernetes.yaml', 'tests/functions.yaml'):
        done = kubectl(['delete', '--ignore-not-found', '--wait=true', '-f', str(CAPABILITY / path)], timeout=600, check=False)
        expect(done.returncode == 0 or 'no matches for kind' in done.stderr, f'deleting {path} failed: {done.stderr.strip()[:300]}')  # kind already gone with its CRD
    if subprocess.run(['helm', 'status', 'crossplane', '-n', 'crossplane-system'], capture_output=True).returncode == 0:
        subprocess.run(['helm', 'uninstall', 'crossplane', '-n', 'crossplane-system', '--wait'], check=True)
    kubectl(['delete', 'namespace', 'crossplane-system', '--ignore-not-found', '--wait=true'], timeout=600)
    # Helm never deletes CRDs; Crossplane's and the packages' are left otherwise.
    crds = [c['metadata']['name'] for c in get_json(['get', 'crd'])['items'] if c['spec']['group'].endswith('crossplane.io')]
    if crds: kubectl(['delete', 'crd', *crds, '--wait=true'], timeout=600)
    expect(not [c for c in get_json(['get', 'crd'])['items'] if c['spec']['group'].endswith('crossplane.io')], 'Crossplane CRDs remain')
    print(f'uninstalled; removed {len(crds)} Crossplane CRDs')

# ---- proof fixtures -------------------------------------------------------------------------

def pull_secret(namespace, registry, username, password):
    auth = base64.b64encode(f'{username}:{password}'.encode()).decode()
    data = base64.b64encode(json.dumps({'auths': {registry: {'username': username, 'password': password, 'auth': auth}}}).encode()).decode()
    return {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': PULL_SECRET, 'namespace': namespace}, 'type': 'kubernetes.io/dockerconfigjson', 'data': {'.dockerconfigjson': data}}

def wait_for_default_serviceaccount(namespace):
    """Pods in a fresh Namespace are Forbidden until the ServiceAccount controller creates `default`."""
    wait_until(f'ServiceAccount {namespace}/default',
               lambda: kubectl(['get', 'serviceaccount', 'default', '-n', namespace], check=False).returncode == 0,
               timeout=120, interval=1)

def proof_services(fixture_image, tls, read_token, write_token, pulls):
    meta = lambda name: {'name': name, 'namespace': PROOF_NS}
    pod_base = {'imagePullSecrets': [{'name': PULL_SECRET}]} if pulls else {}
    token_env = [{'name': n, 'valueFrom': {'secretKeyRef': {'name': 'git-source-tokens', 'key': k}}} for n, k in (('GIT_READ_TOKEN', 'read'), ('GIT_WRITE_TOKEN', 'write'))]
    git = {'name': 'git-fixture', 'image': fixture_image, 'ports': [{'containerPort': 8443}],
           'env': [*token_env, {'name': 'GIT_TLS_CERT_FILE', 'value': '/var/run/git-tls/tls.crt'}, {'name': 'GIT_TLS_KEY_FILE', 'value': '/var/run/git-tls/tls.key'}],
           'volumeMounts': [{'name': 'tls', 'mountPath': '/var/run/git-tls', 'readOnly': True}, {'name': 'server', 'mountPath': '/usr/local/bin/server.py', 'subPath': 'server.py', 'readOnly': True}],
           'readinessProbe': {'tcpSocket': {'port': 8443}}}
    control = {'name': 'control', 'image': fixture_image, 'command': ['sleep', 'infinity'], 'env': [*token_env, {'name': 'GIT_SSL_CAINFO', 'value': '/var/run/git-ca/ca.crt'}, {'name': 'GIT_TERMINAL_PROMPT', 'value': '0'}, {'name': 'HOME', 'value': '/tmp'}],
               'volumeMounts': [{'name': 'ca', 'mountPath': '/var/run/git-ca', 'readOnly': True}]}
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': PROOF_NS}},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': meta('git-fixture-tls'), 'type': 'kubernetes.io/tls', 'stringData': {'tls.crt': tls['cert'], 'tls.key': tls['key']}},
        {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': meta('git-source-tokens'), 'type': 'Opaque', 'stringData': {'read': read_token, 'write': write_token}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('git-fixture-ca'), 'data': {'ca.crt': tls['ca']}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': meta('git-source-server'), 'data': {'server.py': (HERE / 'source-server.py').read_text()}},
        {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': meta('git-fixture'), 'spec': {'selector': {'matchLabels': {'app': 'git-fixture'}}, 'template': {'metadata': {'labels': {'app': 'git-fixture'}}, 'spec': {
            **pod_base, 'containers': [git], 'volumes': [{'name': 'tls', 'secret': {'secretName': 'git-fixture-tls'}}, {'name': 'server', 'configMap': {'name': 'git-source-server'}}]}}}},
        {'apiVersion': 'v1', 'kind': 'Service', 'metadata': meta('git-fixture'), 'spec': {'selector': {'app': 'git-fixture'}, 'ports': [{'name': 'https', 'port': 8443, 'targetPort': 8443}]}},
        {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': meta('control'), 'spec': {**pod_base, 'restartPolicy': 'Never', 'containers': [control], 'volumes': [{'name': 'ca', 'configMap': {'name': 'git-fixture-ca'}}]}},
    ]

def workspace_inputs(name, workspace_id, revision, mode):
    doc = yaml.safe_load((LIVE / 'profile/developer-workspace-live.yaml').read_text())
    doc['metadata']['name'] = name; doc['spec']['workspaceID'] = workspace_id; doc['spec']['source']['revision'] = revision
    if mode == 'ephemeral':
        doc['spec']['storage'] = {'mode': 'ephemeral', 'size': '8Mi'}; doc['spec']['lifecycle'].update({'profile': 'ephemeral', 'deletion': 'after-retention'})
    return doc

def canonical_xr_name(workspace_id): return f'{workspace_id}-xr'

def expected_objects(doc, profile, pulls):
    resources = render_profile.reference_render(doc, profile)['spec']['resources']
    if pulls: next(r for r in resources if r['kind'] == 'Deployment')['spec']['template']['spec']['imagePullSecrets'] = [{'name': PULL_SECRET}]
    return resources

def normalized(item):
    value = spike.normalized(item)
    annotations = value.get('metadata', {}).get('annotations', {})
    for key in [k for k in annotations if k.startswith('kubernetes.crossplane.io/')]: annotations.pop(key)  # provider bookkeeping
    if not annotations: value.get('metadata', {}).pop('annotations', None)
    return value

def readback(namespace, expected):
    """Every composed object must equal its capability reference counterpart; nothing unrendered may appear."""
    for kind in ('Namespace', 'ServiceAccount', 'ResourceQuota', 'LimitRange', 'NetworkPolicy', 'PersistentVolumeClaim', 'Deployment'):
        wanted = {o['metadata']['name']: normalized(o) for o in expected if o['kind'] == kind}
        if kind == 'Namespace': items = [get_json(['get', 'namespace', namespace])]
        else: items = [i for i in get_json(['get', kind.lower(), '-n', namespace])['items'] if not spike.controller_default(i)]
        got = {i['metadata']['name']: normalized(i) for i in items}
        expect(set(got) == set(wanted), f'{kind}: reconciled {sorted(got)} != rendered {sorted(wanted)}')
        for name in wanted:
            expect(got[name] == wanted[name], f'{kind}/{name} differs from capability reference rendering: got {json.dumps(got[name], sort_keys=True)[:600]}')
    return len(expected)

def workspace_pod(namespace):
    pods = [p for p in get_json(['get', 'pods', '-n', namespace])['items'] if p.get('status', {}).get('phase') == 'Running' and not p['metadata'].get('deletionTimestamp')]
    expect(len(pods) == 1, f'expected one running workspace pod in {namespace}, found {len(pods)}'); return pods[0]['metadata']['name']

def pod_user_namespace_probes(namespace, template, mode):
    """Dry-run Pods shaped like the workspace while avoiding unrelated quota rejection."""
    outcomes = {}
    for value in ('absent', 'true', 'false'):
        spec = copy.deepcopy(template['spec'])
        if value == 'absent': spec.pop('hostUsers', None)
        else: spec['hostUsers'] = value == 'true'
        # The running workspace consumes its full CPU/memory quota. Explicit zero quantities keep
        # these CREATE dry-runs within quota; the copied security contexts satisfy Pod Security.
        for container in [*spec.get('initContainers', []), *spec['containers']]:
            container['resources'] = {'requests': {'cpu': '0', 'memory': '0'}, 'limits': {'cpu': '0', 'memory': '0'}}
        probe = {'apiVersion': 'v1', 'kind': 'Pod',
                 'metadata': {'name': f'ok178-host-users-{value}', 'namespace': namespace,
                              'labels': copy.deepcopy(template.get('metadata', {}).get('labels', {}))},
                 'spec': spec}
        outcomes[value] = kubectl(['create', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(probe), check=False)
    labels = get_json(['get', 'namespace', namespace])['metadata'].get('labels', {})
    return validate_pod_user_namespace_admission(mode, labels, outcomes)

def namespace_mutation_documents(namespace_object):
    """Build every full-object and subresource mutation independently of its expected outcome."""
    def without_protected_labels():
        document = replace_document(namespace_object)
        labels = document.setdefault('metadata', {}).setdefault('labels', {})
        labels.pop(WORKSPACE_ID_LABEL, None)
        labels.pop(HOST_USERS_LABEL, None)
        return document

    changed_identity = replace_document(namespace_object)
    labels = changed_identity.setdefault('metadata', {}).setdefault('labels', {})
    labels[WORKSPACE_ID_LABEL] = labels.get(WORKSPACE_ID_LABEL, '') + '-changed'
    status_drop = without_protected_labels()
    status_drop['status'] = copy.deepcopy(namespace_object.get('status', {}))
    return {
        'drop-both': without_protected_labels(),
        'change-id': changed_identity,
        'status-drop-both': status_drop,
        'finalize-drop-both': without_protected_labels(),
    }

def namespace_label_probes(namespace, mode):
    """Temporarily grant only Namespace mutation so admission, not RBAC, decides the probes."""
    workspace = f'system:serviceaccount:{namespace}:workspace'
    observer = f'system:serviceaccount:{PROOF_NS}:{OBSERVER_SA}'
    operator = f'system:serviceaccount:{PROOF_NS}:{OPERATOR_SA}'
    role = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole',
            'metadata': {'name': LABEL_PROBE_ROLE},
            'rules': [{'apiGroups': [''], 'resources': ['namespaces'], 'resourceNames': [namespace],
                       'verbs': ['get', 'update', 'patch', 'delete']},
                      {'apiGroups': [''], 'resources': ['namespaces/status', 'namespaces/finalize'],
                       'resourceNames': [namespace], 'verbs': ['update']}]}
    binding = {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding',
               'metadata': {'name': LABEL_PROBE_BINDING},
               'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': LABEL_PROBE_ROLE},
               'subjects': [{'kind': 'ServiceAccount', 'name': 'workspace', 'namespace': namespace},
                            {'kind': 'ServiceAccount', 'name': OBSERVER_SA, 'namespace': PROOF_NS},
                            {'kind': 'ServiceAccount', 'name': OPERATOR_SA, 'namespace': PROOF_NS}]}
    denied, allowed = {}, {}
    operations = ((('remove', f'{HOST_USERS_LABEL}-'), ('alter', f'{HOST_USERS_LABEL}=true'))
                  if mode == 'enforced' else
                  (('add-false', f'{HOST_USERS_LABEL}=false'), ('add-true', f'{HOST_USERS_LABEL}=true')))
    namespace_before = get_json(['get', 'namespace', namespace])
    for resource, name in (('clusterrole', LABEL_PROBE_ROLE), ('clusterrolebinding', LABEL_PROBE_BINDING)):
        existing = kubectl(['get', f'{resource}/{name}'], check=False)
        expect(existing.returncode != 0 and 'NotFound' in existing.stderr,
               f'label proof refuses to overwrite existing {resource}/{name}')
    apply([role, binding])
    try:
        for identity_name, identity in (('workspace', workspace), ('observer', observer), ('operator', operator)):
            for verb in ('get', 'update', 'patch', 'delete'):
                assert_can_i(identity, verb, 'namespaces', True, namespace)
            for subresource in ('status', 'finalize'):
                assert_can_i(identity, 'update', 'namespaces', True, namespace, subresource=subresource)
                assert_can_i(identity, 'patch', 'namespaces', False, namespace, subresource=subresource)
                assert_can_i(identity, 'delete', 'namespaces', False, namespace, subresource=subresource)
            assert_can_i(identity, 'create', 'namespaces', False)
            for operation, label in operations:
                result = kubectl(['label', 'namespace', namespace, label, '--overwrite', '--dry-run=server', '-o', 'name',
                                  f'--as={identity}'], check=False)
                (allowed if identity_name == 'operator' else denied)[f'{identity_name}-{operation}'] = result
            preserved = replace_document(namespace_before)
            allowed[f'{identity_name}-preserve'] = kubectl(
                ['replace', '--dry-run=server', '-f', '-', f'--as={identity}'],
                input_text=yaml.safe_dump(preserved), check=False)
            for operation, document in namespace_mutation_documents(namespace_before).items():
                if operation == 'status-drop-both':
                    args = ['replace', '--raw', f'/api/v1/namespaces/{namespace}/status?dryRun=All', '-f', '-', f'--as={identity}']
                    input_text = json.dumps(document)
                elif operation == 'finalize-drop-both':
                    args = ['replace', '--raw', f'/api/v1/namespaces/{namespace}/finalize?dryRun=All', '-f', '-', f'--as={identity}']
                    input_text = json.dumps(document)
                else:
                    args = ['replace', '--dry-run=server', '-f', '-', f'--as={identity}']
                    input_text = yaml.safe_dump(document)
                result = kubectl(args, input_text=input_text, check=False)
                (allowed if identity_name == 'operator' else denied)[f'{identity_name}-{operation}'] = result
            deleted = kubectl(['delete', 'namespace', namespace, '--dry-run=server', f'--as={identity}'], check=False)
            (allowed if identity_name == 'operator' else denied)[f'{identity_name}-delete'] = deleted
        namespace_after = get_json(['get', 'namespace', namespace])
        return validate_namespace_label_admission(mode, namespace_before, namespace_after, denied, allowed)
    finally:
        deleted_binding = kubectl(['delete', 'clusterrolebinding', LABEL_PROBE_BINDING, '--ignore-not-found', '--wait=true'], check=False)
        deleted_role = kubectl(['delete', 'clusterrole', LABEL_PROBE_ROLE, '--ignore-not-found', '--wait=true'], check=False)
        expect(deleted_binding.returncode == 0 and deleted_role.returncode == 0,
               f'label proof RBAC cleanup failed: binding={deleted_binding.stderr.strip()[:120]} role={deleted_role.stderr.strip()[:120]}')
        for resource, name in (('clusterrolebinding', LABEL_PROBE_BINDING), ('clusterrole', LABEL_PROBE_ROLE)):
            gone = kubectl(['get', f'{resource}/{name}'], check=False)
            expect(is_not_found(gone), f'label proof cleanup left {resource}/{name}: {gone.stderr.strip()[:200]}')

def provider_label_reconcile_probes(owner_name, namespace):
    """Use one SSA field manager on an isolated Namespace so omission really removes a label."""
    namespace_object = next((item for item in composed_object_items(owner_name)
                             if item.get('spec', {}).get('forProvider', {}).get('manifest', {}).get('kind') == 'Namespace'), None)
    expect(namespace_object is not None, f'{owner_name} has no rendered Namespace Object')
    probe_name, probe_namespace = 'ok185-provider-label-probe', 'ok185-provider-label-proof'
    base = replace_document(namespace_object)
    base['metadata'] = {'name': probe_name}
    base['spec']['deletionPolicy'] = 'Orphan'
    base['spec'].pop('readiness', None)
    manifest = base['spec']['forProvider']['manifest']
    expect(manifest['metadata']['name'] == namespace, 'rendered Namespace Object names another Namespace')
    manifest['metadata']['name'] = probe_namespace
    expected_value = manifest['metadata']['labels'].get(HOST_USERS_LABEL)
    expect(expected_value in (None, 'false'), f'rendered Namespace Object has invalid {HOST_USERS_LABEL}={expected_value!r}')
    labels_before = copy.deepcopy(get_json(['get', 'namespace', namespace])['metadata'].get('labels', {}))
    for resource, name in (('object', probe_name), ('namespace', probe_namespace)):
        existing = kubectl(['get', f'{resource}/{name}'], check=False)
        expect(existing.returncode != 0 and 'NotFound' in existing.stderr,
               f'provider label proof refuses to overwrite {resource}/{name}')

    def reconcile(document, allowed):
        apply([document])
        state = {}
        def settled():
            item = get_json(['get', f'object/{probe_name}'])
            synced = next((condition for condition in item.get('status', {}).get('conditions', [])
                           if condition.get('type') == 'Synced'), None)
            if synced is None or (synced.get('status') == 'True') != allowed: return False
            state.update(synced=allowed, message=synced.get('message', ''))
            return allowed or (NAMESPACE_HOST_USERS_POLICY in state['message'] and
                               'must preserve the workspace identity and render host-users' in state['message'])
        wait_until(f'provider label Object Synced={allowed}', settled, timeout=180, interval=2)
        return state

    outcomes = {}
    try:
        # This manager must own the original field before omission can request its removal.
        outcomes['preserve'] = reconcile(base, True)
        fixture_labels = copy.deepcopy(get_json(['get', 'namespace', probe_namespace])['metadata'].get('labels', {}))
        # The API server adds kubernetes.io/metadata.name to every Namespace; nothing else may differ.
        server_added = {'kubernetes.io/metadata.name': probe_namespace}
        expect(fixture_labels == {**manifest['metadata']['labels'], **server_added},
               f'provider control did not create the rendered labels: {fixture_labels}')
        for variant in ('drop', 'alter'):
            doc = copy.deepcopy(base)
            labels = doc['spec']['forProvider']['manifest']['metadata']['labels']
            if variant == 'drop':
                if expected_value == 'false': labels.pop(HOST_USERS_LABEL)
                else: labels[HOST_USERS_LABEL] = 'false'
            else: labels[HOST_USERS_LABEL] = 'true'
            outcomes[variant] = reconcile(doc, False)
            expect(get_json(['get', 'namespace', probe_namespace])['metadata'].get('labels', {}) == fixture_labels,
                   f'provider {variant} changed the fixture Namespace labels')
            # An allowed control between mutations also clears the previous denial condition.
            reconcile(base, True)
    finally:
        kubectl(['delete', f'object/{probe_name}', '--ignore-not-found', '--wait=true'], timeout=180, check=False)
        kubectl(['delete', f'namespace/{probe_namespace}', '--ignore-not-found', '--wait=true'], timeout=180, check=False)
        for resource, name in (('object', probe_name), ('namespace', probe_namespace)):
            gone = kubectl(['get', f'{resource}/{name}'], check=False)
            expect(gone.returncode != 0 and 'NotFound' in gone.stderr,
                   f'provider label proof cleanup left {resource}/{name}')
    labels_after = get_json(['get', 'namespace', namespace])['metadata'].get('labels', {})
    return validate_provider_label_reconcile(outcomes, labels_before, labels_after, expected_value)

def ephemeralcontainers_request(namespace, pod_name, image, identity=None):
    args = ['replace', '--raw', f'/api/v1/namespaces/{namespace}/pods/{pod_name}/ephemeralcontainers?dryRun=All', '-f', '-']
    if identity: args.append(f'--as={identity}')
    # The kubelet updates Pod status concurrently, so a PUT built from an earlier GET can hit an
    # optimistic-concurrency Conflict. Retry only that, from a fresh read; any admission or RBAC
    # outcome is returned on the first attempt that reaches it.
    for _ in range(5):
        pod = get_json(['get', f'pod/{pod_name}', '-n', namespace])
        before = copy.deepcopy(pod.get('spec', {}).get('ephemeralContainers', []))
        pod['spec']['ephemeralContainers'] = [*before, {'name': 'debugger', 'image': image,
                                                        'command': ['sleep', '60'], 'targetContainerName': 'runtime'}]
        result = kubectl(args, input_text=json.dumps(pod), check=False)
        if not (result.returncode != 0 and '(Conflict)' in result.stderr and 'the object has been modified' in result.stderr):
            break
        time.sleep(1)
    unchanged = get_json(['get', f'pod/{pod_name}', '-n', namespace]).get('spec', {}).get('ephemeralContainers', []) == before
    return result, unchanged

def ephemeralcontainers_probes(image, workspace_namespace):
    old_name, compliant_name = 'legacy-host-users', 'compliant-host-users'
    old = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': old_name, 'namespace': EPHEMERAL_PROBE_NS},
           'spec': {'hostUsers': True, 'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'runtime', 'image': image, 'command': ['sleep', '600']}]}}
    compliant = copy.deepcopy(old); compliant['metadata']['name'] = compliant_name; compliant['spec']['hostUsers'] = False
    workspace = f'system:serviceaccount:{workspace_namespace}:workspace'
    observer = f'system:serviceaccount:{PROOF_NS}:{OBSERVER_SA}'
    existing = kubectl(['get', f'namespace/{EPHEMERAL_PROBE_NS}'], check=False)
    expect(existing.returncode != 0 and 'NotFound' in existing.stderr,
           f'ephemeralcontainers proof refuses to overwrite Namespace/{EPHEMERAL_PROBE_NS}')
    try:
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': EPHEMERAL_PROBE_NS}}])
        wait_for_default_serviceaccount(EPHEMERAL_PROBE_NS)
        apply([old])
        kubectl(['label', 'namespace', EPHEMERAL_PROBE_NS, f'{HOST_USERS_LABEL}=false'])
        apply([compliant])
        allowed, allowed_unchanged = ephemeralcontainers_request(EPHEMERAL_PROBE_NS, compliant_name, image)
        denied, denied_unchanged = ephemeralcontainers_request(EPHEMERAL_PROBE_NS, old_name, image)
        authority = {}
        for name, identity in (('workspace', workspace), ('observer', observer)):
            # A path-embedded 'pods/ephemeralcontainers' would ask about a Pod named so; name the subresource.
            assert_can_i(identity, 'update', 'pods', False, compliant_name, EPHEMERAL_PROBE_NS, subresource='ephemeralcontainers')
            result, _ = ephemeralcontainers_request(EPHEMERAL_PROBE_NS, compliant_name, image, identity)
            authority[name] = result
        return validate_ephemeralcontainers_admission(
            allowed, denied, authority, {'compliant': allowed_unchanged, 'legacy': denied_unchanged})
    finally:
        kubectl(['delete', 'namespace', EPHEMERAL_PROBE_NS, '--ignore-not-found', '--wait=true'], timeout=300, check=False)
        gone = kubectl(['get', f'namespace/{EPHEMERAL_PROBE_NS}'], check=False)
        expect(gone.returncode != 0 and 'NotFound' in gone.stderr,
               f'ephemeralcontainers proof cleanup left Namespace/{EPHEMERAL_PROBE_NS}')

def wait_ready(name):
    kubectl(['wait', '--for=condition=Ready', f'developerworkspace/{name}', '--timeout=600s'], timeout=630)

def composed_object_items(name):
    return [o for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items'] if o['metadata'].get('labels', {}).get('crossplane.io/composite') == name]

def composed_objects(name): return [o['metadata']['name'] for o in composed_object_items(name)]

def owner_snapshot(name, namespace, expected=None):
    """Capture owner, composed Object desired state, and rendered-resource readback."""
    xr = get_json(['get', f'developerworkspace/{name}'])
    xr_uid = xr['metadata']['uid']
    owner = get_json(['get', 'namespace', namespace])
    objects = {}
    for item in composed_object_items(name):
        metadata = item['metadata']
        owner_references = sorted(metadata.get('ownerReferences', []), key=lambda ref: (ref.get('kind', ''), ref.get('name', '')))
        expect(any(ref.get('uid') == xr_uid and ref.get('controller') is True for ref in owner_references),
               f"Object/{metadata['name']} lacks a controller reference to {name}/{xr_uid}")
        objects[metadata['name']] = {
            'uid': metadata['uid'],
            'resourceVersion': metadata['resourceVersion'],
            'generation': metadata['generation'],
            'metadata': {key: copy.deepcopy(value) for key, value in metadata.items() if key not in ('resourceVersion', 'managedFields')},
            'ownerReferences': owner_references,
            'spec': copy.deepcopy(item['spec']),
        }
    expect(objects, f'{name} has no composed Object references to snapshot')
    resources = {}
    for wanted in expected or ():
        kind, resource_name = wanted['kind'], wanted['metadata']['name']
        item = owner if kind == 'Namespace' else get_json(['get', f'{kind.lower()}/{resource_name}', '-n', namespace])
        resources[f'{kind}/{resource_name}'] = {
            'uid': item['metadata']['uid'],
            'resourceVersion': item['metadata']['resourceVersion'],
            'content': normalized(item),
        }
    return {
        'xrUID': xr_uid,
        'xrResourceVersion': xr['metadata']['resourceVersion'],
        'xrGeneration': xr['metadata']['generation'],
        'xrSpec': copy.deepcopy(xr['spec']),
        'namespace': {'uid': owner['metadata']['uid'], 'resourceVersion': owner['metadata']['resourceVersion'], 'content': normalized(owner)},
        'objects': objects,
        'resources': resources,
    }

def assert_owner_unchanged(before, after, *, strict_object_rv=True, strict_resource_rv=True):
    expect(after['xrUID'] == before['xrUID'], 'owner DeveloperWorkspace UID changed during protected interval')
    expect(after['xrGeneration'] == before['xrGeneration'], 'owner DeveloperWorkspace generation changed during protected interval')
    expect(after['xrSpec'] == before['xrSpec'], 'owner DeveloperWorkspace spec changed during protected interval')
    expect(bool(after['xrResourceVersion']) and bool(before['xrResourceVersion']), 'owner DeveloperWorkspace resourceVersion missing')
    if strict_object_rv:
        expect(after['xrResourceVersion'] == before['xrResourceVersion'], 'owner DeveloperWorkspace resourceVersion changed during protected interval')
    expect(after['namespace'] == before['namespace'], 'owner Namespace identity, resourceVersion or content changed during protected interval')
    expect(set(after['objects']) == set(before['objects']), 'owner composed Object reference set changed during protected interval')
    for name, old in before['objects'].items():
        new = after['objects'][name]
        expect(new['uid'] == old['uid'], f'owner Object/{name} UID changed during protected interval')
        expect(new['metadata'] == old['metadata'], f'owner Object/{name} metadata changed during protected interval')
        expect(new['ownerReferences'] == old['ownerReferences'], f'owner Object/{name} ownership changed during protected interval')
        expect(new['spec'] == old['spec'], f'owner Object/{name} spec changed during protected interval')
        expect(new['generation'] == old['generation'], f'owner Object/{name} generation changed during protected interval')
        expect(bool(new['resourceVersion']) and bool(old['resourceVersion']), f'owner Object/{name} resourceVersion missing')
        if strict_object_rv:
            expect(new['resourceVersion'] == old['resourceVersion'], f'owner Object/{name} resourceVersion changed during protected interval')
    expect(set(after.get('resources', {})) == set(before.get('resources', {})), 'owner rendered resource set changed during protected interval')
    for name, old in before.get('resources', {}).items():
        new = after['resources'][name]
        expect(new['uid'] == old['uid'], f'owner readback {name} UID changed during protected interval')
        expect(new['content'] == old['content'], f'owner readback {name} content changed during protected interval')
        expect(bool(new['resourceVersion']) and bool(old['resourceVersion']), f'owner readback {name} resourceVersion missing')
        if strict_resource_rv:
            expect(new['resourceVersion'] == old['resourceVersion'], f'owner readback {name} resourceVersion changed during protected interval')
    return {
        'workspaceUID': before['xrUID'], 'workspaceGeneration': before['xrGeneration'],
        'workspaceResourceVersionBefore': before['xrResourceVersion'],
        'workspaceResourceVersionAfter': after['xrResourceVersion'],
        'workspaceSpecSha256Before': sha_json(before['xrSpec']),
        'workspaceSpecSha256After': sha_json(after['xrSpec']),
        'namespace': {'uid': before['namespace']['uid'], 'resourceVersionBefore': before['namespace']['resourceVersion'],
                      'resourceVersionAfter': after['namespace']['resourceVersion'],
                      'contentSha256Before': sha_json(before['namespace']['content']),
                      'contentSha256After': sha_json(after['namespace']['content'])},
        'objects': [{'name': name, 'uid': old['uid'], 'resourceVersionBefore': old['resourceVersion'],
                     'resourceVersionAfter': after['objects'][name]['resourceVersion'],
                     'metadataSha256Before': sha_json(old['metadata']),
                     'metadataSha256After': sha_json(after['objects'][name]['metadata']),
                     'specSha256Before': sha_json(old['spec']),
                     'specSha256After': sha_json(after['objects'][name]['spec'])} for name, old in sorted(before['objects'].items())],
        'readback': [{'name': name, 'uid': old['uid'], 'resourceVersionBefore': old['resourceVersion'],
                      'resourceVersionAfter': after['resources'][name]['resourceVersion'],
                      'contentSha256Before': sha_json(old['content']),
                      'contentSha256After': sha_json(after['resources'][name]['content'])}
                     for name, old in sorted(before.get('resources', {}).items())],
    }


def assert_distinct_workspace_snapshots(first, second):
    expect(first['namespace']['uid'] != second['namespace']['uid'] and
           first['namespace']['content']['metadata']['name'] != second['namespace']['content']['metadata']['name'],
           'distinct workspaces share a Namespace name or UID')
    expect(set(first['objects']).isdisjoint(second['objects']), 'distinct workspaces share composed Object names')
    first_object_uids = {value['uid'] for value in first['objects'].values()}
    second_object_uids = {value['uid'] for value in second['objects'].values()}
    expect(first_object_uids.isdisjoint(second_object_uids), 'distinct workspaces share composed Object UIDs')
    first_resource_uids = {value['uid'] for value in first.get('resources', {}).values()}
    second_resource_uids = {value['uid'] for value in second.get('resources', {}).values()}
    expect(first_resource_uids.isdisjoint(second_resource_uids), 'distinct workspaces share rendered-resource UIDs')
    return {'namespaceUIDs': [first['namespace']['uid'], second['namespace']['uid']],
            'objectNames': [sorted(first['objects']), sorted(second['objects'])],
            'objectUIDs': [sorted(first_object_uids), sorted(second_object_uids)]}

def assert_noncanonical_name_refused(done, candidate_name):
    error = done.stderr
    expect(done.returncode != 0 and 'metadata.name' in error and 'workspaceID' in error and '-xr' in error,
           f'noncanonical duplicate workspaceID was not rejected by the naming rule: {error.strip()[:300]}')
    missing = kubectl(['get', f'developerworkspace/{candidate_name}'], check=False)
    expect(is_not_found(missing), f'rejected DeveloperWorkspace {candidate_name} absence was not confirmed by NotFound: {missing.stderr.strip()[:300]}')
    refs = composed_objects(candidate_name)
    expect(not refs, f'rejected DeveloperWorkspace {candidate_name} has composed Object references: {refs}')
    return {'name': candidate_name, 'exists': False, 'ready': False, 'objectRefs': refs}

def assert_canonical_create_already_exists(done, owner_name):
    error = done.stderr
    expect(done.returncode != 0 and '(AlreadyExists)' in error and 'already exists' in error and f'"{owner_name}"' in error,
           f'second canonical CREATE did not report AlreadyExists for {owner_name}: rc={done.returncode} {error.strip()[:300]}')
    return {'name': owner_name, 'reason': 'AlreadyExists', 'created': False}

def authority_identities():
    def binding(name, service_account, role):
        return {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRoleBinding', 'metadata': {'name': name},
                'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': role},
                'subjects': [{'kind': 'ServiceAccount', 'name': service_account, 'namespace': PROOF_NS}]}
    return [
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': OPERATOR_SA, 'namespace': PROOF_NS}},
        {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': OBSERVER_SA, 'namespace': PROOF_NS}},
        binding(OPERATOR_BINDING, OPERATOR_SA, 'developer-workspace-operator'),
        binding(OBSERVER_BINDING, OBSERVER_SA, 'developer-workspace-observer'),
    ]

# Expected holders come from the pinned chart/RBAC-manager sources linked in README,
# Kubernetes' default cluster-admin binding, and this capability's shipped operator role.
# The provider v1.3.1 package installs both legacy cluster-scoped APIs and v2 namespaced APIs.
# Keep the scope alongside each resource so RoleBindings are counted exactly as Kubernetes does.
AUTHORITY_RESOURCES = {
    'DeveloperWorkspace': ('workspace.openkubes.io', 'developerworkspaces', 'Cluster'),
    'Object': ('kubernetes.crossplane.io', 'objects', 'Cluster'),
    'ProviderConfig': ('kubernetes.crossplane.io', 'providerconfigs', 'Cluster'),
    'EnvironmentConfig': ('apiextensions.crossplane.io', 'environmentconfigs', 'Cluster'),
    'NamespacedObject': ('kubernetes.m.crossplane.io', 'objects', 'Namespaced'),
    'NamespacedProviderConfig': ('kubernetes.m.crossplane.io', 'providerconfigs', 'Namespaced'),
    'NamespacedObservedObjectCollection': ('kubernetes.m.crossplane.io', 'observedobjectcollections', 'Namespaced'),
    'NamespacedProviderConfigUsage': ('kubernetes.m.crossplane.io', 'providerconfigusages', 'Namespaced'),
    'ClusterProviderConfig': ('kubernetes.m.crossplane.io', 'clusterproviderconfigs', 'Cluster'),
    'ObservedObjectCollection': ('kubernetes.crossplane.io', 'observedobjectcollections', 'Cluster'),
}
# These sets are source assertions, not observations. Crossplane 2.3.3 aggregates every provider
# CRD into its controller/admin roles; provider system roles have C/U/P but no delete. The shipped
# OK-175 operator predates the provider v2 APIs and grants only these four kinds.
PROVIDER_SYSTEM_RESOURCES = frozenset({
    'Object', 'ProviderConfig', 'NamespacedObject', 'NamespacedProviderConfig',
    'NamespacedObservedObjectCollection', 'NamespacedProviderConfigUsage',
    'ClusterProviderConfig', 'ObservedObjectCollection',
})
SHIPPED_OPERATOR_RESOURCES = frozenset({'DeveloperWorkspace', 'Object', 'ProviderConfig', 'EnvironmentConfig'})
AUTHORITY_VERBS = ('create', 'update', 'patch', 'delete', 'deletecollection')
INDIRECT_AUTHORITY = {
    'impersonate-users': ('', 'users', 'impersonate', None),
    'impersonate-groups': ('', 'groups', 'impersonate', None),
    'impersonate-serviceaccounts': ('', 'serviceaccounts', 'impersonate', '*'),
    'bind-roles': ('rbac.authorization.k8s.io', 'roles', 'bind', '*'),
    'bind-clusterroles': ('rbac.authorization.k8s.io', 'clusterroles', 'bind', '*'),
    'escalate-roles': ('rbac.authorization.k8s.io', 'roles', 'escalate', '*'),
    'escalate-clusterroles': ('rbac.authorization.k8s.io', 'clusterroles', 'escalate', None),
    'create-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'create', None),
    'update-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'update', None),
    'patch-clusterrolebindings': ('rbac.authorization.k8s.io', 'clusterrolebindings', 'patch', None),
    'create-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'create', '*'),
    'update-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'update', '*'),
    'patch-rolebindings': ('rbac.authorization.k8s.io', 'rolebindings', 'patch', '*'),
    'create-serviceaccounts-crossplane-system': ('', 'serviceaccounts', 'create', 'crossplane-system'),
    'create-serviceaccount-tokens-crossplane-system': ('', 'serviceaccounts/token', 'create', 'crossplane-system'),
    'create-pods-crossplane-system': ('', 'pods', 'create', 'crossplane-system'),
    'get-secrets-crossplane-system': ('', 'secrets', 'get', 'crossplane-system'),
    'list-secrets-crossplane-system': ('', 'secrets', 'list', 'crossplane-system'),
}


def authority_subject(subject, namespace=None):
    kind = subject['kind']
    expect(kind in ('User', 'Group', 'ServiceAccount'), f'unknown RBAC subject kind {kind}')
    ns = subject.get('namespace') if kind == 'ServiceAccount' else None
    expect(kind != 'ServiceAccount' or bool(ns), f'ServiceAccount subject {subject["name"]} has no namespace')
    return (kind, subject['name'], ns or '')


def authority_subject_record(subject):
    kind, name, namespace = subject
    return {'kind': kind, 'name': name, **({'namespace': namespace} if namespace else {})}


def expected_authority_holders(default_group_present):
    # Do not derive this policy from the observed grants. Only the documented optional
    # default group binding controls presence; an altered binding still fails comparison.
    superuser = ('Group', 'system:masters', '')
    garbage_collector = ('ServiceAccount', 'generic-garbage-collector', 'kube-system')
    namespace_controller = ('ServiceAccount', 'namespace-controller', 'kube-system')
    controller = ('ServiceAccount', 'crossplane', 'crossplane-system')
    # The chart's rbac-manager SA manages RBAC, but has no mutation verbs on these kinds.
    provider = ('ServiceAccount', 'developer-workspace-provider-kubernetes', 'crossplane-system')
    operator = ('ServiceAccount', OPERATOR_SA, PROOF_NS)
    group = {('Group', 'crossplane:masters', '')} if default_group_present else set()
    result = {}
    for kind in AUTHORITY_RESOURCES:
        result[kind] = {}
        for verb in AUTHORITY_VERBS:
            holders = {superuser, controller} | group
            if kind in SHIPPED_OPERATOR_RESOURCES:
                holders.add(operator)
            if verb in ('update', 'patch', 'delete'):
                holders.add(garbage_collector)
            if verb in ('delete', 'deletecollection'):
                holders.add(namespace_controller)
            if kind in PROVIDER_SYSTEM_RESOURCES and verb in ('create', 'update', 'patch'):
                holders.add(provider)  # provider system role deliberately omits delete
            if verb == 'deletecollection':
                holders.discard(operator)  # the shipped operator role intentionally omits it
            result[kind][verb] = holders
    return result


LOCAL_QUOTA_PROVISIONER = ('ServiceAccount', 'ok-storage-local-quota-provisioner', 'ok-storage-local-quota')


def local_quota_binding_present(cluster_bindings):
    """Only the exact ok-storage binding (this SA to its own ClusterRole) makes the SA expected."""
    return any(b['metadata']['name'] == 'ok-storage-local-quota-provisioner'
               and b.get('roleRef', {}).get('name') == 'ok-storage-local-quota-provisioner'
               and [(s.get('kind'), s.get('name'), s.get('namespace', '')) for s in b.get('subjects', [])]
                   == [LOCAL_QUOTA_PROVISIONER]
               for b in cluster_bindings)


def expected_indirect_holders(default_group_present, local_quota_present=False):
    master = ('Group', 'system:masters', '')
    group = {('Group', 'crossplane:masters', '')} if default_group_present else set()
    sa = lambda name, namespace='kube-system': ('ServiceAccount', name, namespace)
    controller = sa('crossplane', 'crossplane-system')
    rbac_manager = sa('rbac-manager', 'crossplane-system')
    provider = sa('developer-workspace-provider-kubernetes', 'crossplane-system')
    gc = sa('generic-garbage-collector')
    namespace_controller = sa('namespace-controller')
    kcm = ('User', 'system:kube-controller-manager', '')
    result = {name: {master} for name in INDIRECT_AUTHORITY}
    result['impersonate-serviceaccounts'].add(controller)
    result['bind-clusterroles'].add(rbac_manager)
    result['escalate-roles'].add(rbac_manager)
    result['escalate-clusterroles'].update({rbac_manager, sa('clusterrole-aggregation-controller')})
    result['create-clusterrolebindings'].update({rbac_manager, *group})
    for name in ('update-clusterrolebindings', 'patch-clusterrolebindings'):
        result[name].update({rbac_manager, gc, *group})
    result['create-rolebindings'].update(group)
    for name in ('update-rolebindings', 'patch-rolebindings'):
        result[name].update({gc, *group})
    result['create-serviceaccounts-crossplane-system'].update({kcm, sa('service-account-controller'), controller, provider})
    result['create-serviceaccount-tokens-crossplane-system'].add(kcm)
    result['create-pods-crossplane-system'].update(sa(name) for name in (
        'daemon-set-controller', 'job-controller', 'persistent-volume-binder',
        'replicaset-controller', 'replication-controller', 'statefulset-controller'))
    if local_quota_present:
        # ok-storage's pinned OpenEBS localpv 4.6.0 ClusterRole grants its provisioner all verbs on
        # pods and namespaces cluster-wide (helper Pods); documented in ok-storage README.
        result['create-pods-crossplane-system'].add(LOCAL_QUOTA_PROVISIONER)
    secret_readers = {kcm, gc, namespace_controller, controller, provider, sa('cilium-operator'), *group}
    result['get-secrets-crossplane-system'].update(secret_readers)
    result['list-secrets-crossplane-system'].update({*secret_readers, sa('resourcequota-controller')})
    return result


def authority_rule_matches(rule, group, resource, verb):
    matches = lambda value, entries: value in entries or '*' in entries
    resources = rule.get('resources', [])
    resource_match = matches(resource, resources)
    if '/' in resource:
        _, subresource = resource.split('/', 1)
        resource_match = resource_match or f'*/{subresource}' in resources
    return (matches(group, rule.get('apiGroups', [])) and
            resource_match and
            matches(verb, rule.get('verbs', [])) and
            # Top-level CREATE has no resource name at authorization time. Named rules still
            # count for updates, named subresource creates, and list with metadata.name selectors.
            not (verb == 'deletecollection' and rule.get('resourceNames')) and
            not (verb == 'create' and '/' not in resource and rule.get('resourceNames')))


def assert_authority_holder_sets(holders, expected):
    differences = []
    for kind in AUTHORITY_RESOURCES:
        for verb in AUTHORITY_VERBS:
            extra = sorted(holders[kind][verb] - expected[kind][verb])
            missing = sorted(expected[kind][verb] - holders[kind][verb])
            if extra or missing:
                differences.append(f'{kind}/{verb}: extra={list(map(authority_subject_record, extra))}, '
                                   f'missing={list(map(authority_subject_record, missing))}')
    expect(not differences, 'authority-who-can holder mismatch: ' + '; '.join(differences))


def assert_indirect_authority_holder_sets(holders, expected):
    differences = []
    for name in INDIRECT_AUTHORITY:
        extra = sorted(holders[name] - expected[name])
        missing = sorted(expected[name] - holders[name])
        if extra or missing:
            differences.append(f'{name}: extra={list(map(authority_subject_record, extra))}, '
                               f'missing={list(map(authority_subject_record, missing))}')
    expect(not differences, 'indirect authority holder mismatch: ' + '; '.join(differences))


def rolebinding_grants_resource(cluster_binding, scope):
    return cluster_binding or scope == 'Namespaced'


def prove_authority_who_can():
    # Scope is checked against the installed CRDs, rather than inferred from a kind name.
    for kind, (group, resource, scope) in AUTHORITY_RESOURCES.items():
        crd = get_json(['get', 'crd', f'{resource}.{group}'])
        expect(crd['spec']['scope'] == scope,
               f'authority-who-can {kind} must be {scope}, got {crd["spec"]["scope"]}')
    cluster_roles = get_json(['get', 'clusterroles'])['items']
    cluster_bindings = get_json(['get', 'clusterrolebindings'])['items']
    roles = get_json(['get', 'roles', '--all-namespaces'])['items']
    bindings = get_json(['get', 'rolebindings', '--all-namespaces'])['items']
    cluster_index = {r['metadata']['name']: r for r in cluster_roles}
    role_index = {(r['metadata']['namespace'], r['metadata']['name']): r for r in roles}
    holders = {kind: {verb: set() for verb in AUTHORITY_VERBS} for kind in AUTHORITY_RESOURCES}
    indirect = {name: set() for name in INDIRECT_AUTHORITY}
    non_effective = []
    effective_role_bindings = []
    for binding in [*cluster_bindings, *bindings]:
        cluster_binding = binding['kind'] == 'ClusterRoleBinding'
        namespace = binding['metadata'].get('namespace')
        ref = binding['roleRef']
        expect(ref['apiGroup'] == 'rbac.authorization.k8s.io', 'unexpected RBAC roleRef API group')
        if cluster_binding:
            expect(ref['kind'] == 'ClusterRole', 'ClusterRoleBinding must reference a ClusterRole')
        if ref['kind'] == 'ClusterRole':
            role = cluster_index.get(ref['name'])
        else:
            expect(ref['kind'] == 'Role' and not cluster_binding, 'unexpected RBAC roleRef kind')
            role = role_index.get((namespace, ref['name']))
        # A dangling binding grants nothing, including when a role was removed.
        if role is None:
            continue
        subjects = {authority_subject(subject, namespace) for subject in binding.get('subjects', [])}
        for kind, (group, resource, scope) in AUTHORITY_RESOURCES.items():
            for verb in AUTHORITY_VERBS:
                # The aggregation controller materializes rules. Never resolve selectors here.
                if not any(authority_rule_matches(rule, group, resource, verb) for rule in role.get('rules', [])):
                    continue
                if rolebinding_grants_resource(cluster_binding, scope):
                    holders[kind][verb].update(subjects)
                    if not cluster_binding:
                        effective_role_bindings.append({'binding': {'name': binding['metadata']['name'], 'namespace': namespace},
                                                        'kind': kind, 'verb': verb,
                                                        'subjects': list(map(authority_subject_record, sorted(subjects))),
                                                        'reason': 'RoleBinding grants access to this namespaced resource in its namespace'})
                else:
                    non_effective.append({'binding': {'name': binding['metadata']['name'], 'namespace': namespace},
                                          'kind': kind, 'verb': verb,
                                          'subjects': list(map(authority_subject_record, sorted(subjects))),
                                          'reason': 'RoleBinding cannot grant access to a cluster-scoped resource'})
        for name, (group, resource, verb, scope) in INDIRECT_AUTHORITY.items():
            if not any(authority_rule_matches(rule, group, resource, verb) for rule in role.get('rules', [])):
                continue
            if cluster_binding or scope == '*' or namespace == scope:
                indirect[name].update(subjects)
    default_group_present = any(b['metadata']['name'] == 'crossplane-admin' for b in cluster_bindings)
    local_quota_present = local_quota_binding_present(cluster_bindings)
    assert_authority_holder_sets(holders, expected_authority_holders(default_group_present))
    assert_indirect_authority_holder_sets(indirect, expected_indirect_holders(default_group_present, local_quota_present))
    return {'holders': {kind: {verb: list(map(authority_subject_record, sorted(subjects)))
                              for verb, subjects in verbs.items()} for kind, verbs in holders.items()},
            'indirectHolders': {name: list(map(authority_subject_record, sorted(subjects)))
                                for name, subjects in indirect.items()},
            'effectiveRoleBindings': effective_role_bindings,
            'nonEffectiveRoleBindings': non_effective,
            'scopes': {kind: scope for kind, (_group, _resource, scope) in AUTHORITY_RESOURCES.items()},
            'defaultCrossplaneGroupBindingPresent': default_group_present,
            'localQuotaProvisionerBindingPresent': local_quota_present}


def assert_can_i(identity, verb, resource, allowed, name=None, namespace=None, subresource=None):
    # kubectl names a subresource with --subresource, not inside the resource path.
    target = f'{resource}/{name}' if name else resource
    done = kubectl(['auth', 'can-i', verb, target, f'--as={identity}',
                    *([f'--subresource={subresource}'] if subresource else []),
                    *(['--namespace', namespace] if namespace else [])], check=False)
    if subresource: target = f'{target} --subresource={subresource}'
    answer = done.stdout.strip()
    expect(answer == ('yes' if allowed else 'no') and (done.returncode == 0) == allowed,
           f'auth can-i {verb} {target} for {identity} returned rc={done.returncode} {answer!r}, expected {allowed}')

def assert_server_dry_run(identity, action, resource, doc, allowed):
    verb = 'create' if action == 'create' else 'update'
    done = kubectl([action, '--dry-run=server', '-f', '-', f'--as={identity}'], input_text=yaml.safe_dump(doc), check=False)
    if allowed:
        expect(done.returncode == 0, f'{identity} could not {verb} {resource}: {done.stderr.strip()[:300]}')
    else:
        expected = rf'is forbidden:.*cannot {verb} resource "{re.escape(resource)}"'
        expect(done.returncode != 0 and re.search(expected, done.stderr, re.S | re.I),
               f'{identity} denial did not report Forbidden/{verb}/{resource}: rc={done.returncode} {done.stderr.strip()[:300]}')

def replace_document(doc):
    value = copy.deepcopy(doc); value.pop('status', None)
    for key in ('uid', 'creationTimestamp', 'generation', 'managedFields', 'deletionTimestamp', 'deletionGracePeriodSeconds'):
        value.get('metadata', {}).pop(key, None)
    return value

def prove_authority_boundary(owner_name, owner_doc, profile_doc):
    operator = f'system:serviceaccount:{PROOF_NS}:{OPERATOR_SA}'
    observer = f'system:serviceaccount:{PROOF_NS}:{OBSERVER_SA}'
    apply(authority_identities())

    full = ('get', 'list', 'watch', 'create', 'update', 'patch', 'delete')
    for resource in ('developerworkspaces.workspace.openkubes.io', 'objects.kubernetes.crossplane.io'):
        for verb in full:
            assert_can_i(operator, verb, resource, True)
            assert_can_i(observer, verb, resource, resource.startswith('developerworkspaces.') and verb in ('get', 'list', 'watch'))
        assert_can_i(operator, 'deletecollection', resource, False)
        assert_can_i(observer, 'deletecollection', resource, False)
    named = (('providerconfigs.kubernetes.crossplane.io', 'in-cluster'),
             ('environmentconfigs.apiextensions.crossplane.io', 'developer-workspace-profile'))
    for resource, name in named:
        assert_can_i(operator, 'create', resource, True)
        assert_can_i(observer, 'create', resource, False)
        for verb in ('list', 'watch'):
            assert_can_i(operator, verb, resource, False)
            assert_can_i(observer, verb, resource, False)
        assert_can_i(operator, 'deletecollection', resource, False)
        assert_can_i(observer, 'deletecollection', resource, False)
        for verb in ('get', 'update', 'patch', 'delete'):
            assert_can_i(operator, verb, resource, True, name)
            assert_can_i(operator, verb, resource, False, 'ok175-other-name')
            assert_can_i(observer, verb, resource, False, name)

    # A real read complements can-i for the observer's one positive permission.
    observed = kubectl(['get', f'developerworkspace/{owner_name}', f'--as={observer}', '-o', 'name'], check=False)
    expect(observed.returncode == 0 and observed.stdout.strip().endswith(f'/{owner_name}'), 'observer could not read the owner DeveloperWorkspace')

    live_owner = get_json(['get', f'developerworkspace/{owner_name}'])
    live_object = sorted(composed_object_items(owner_name), key=lambda item: item['metadata']['name'])[0]
    provider = get_json(['get', 'providerconfig/in-cluster'])
    live_profile = get_json(['get', 'environmentconfig/developer-workspace-profile'])

    create_owner = workspace_inputs(canonical_xr_name('ws-ok175-authority'), 'ws-ok175-authority', owner_doc['spec']['source']['revision'], 'persistent')
    create_object = replace_document(live_object)
    create_object['metadata']['name'] = 'ok175-authority-object-probe'
    for key in ('resourceVersion', 'ownerReferences', 'finalizers'):
        create_object['metadata'].pop(key, None)
    create_provider = replace_document(provider); create_provider['metadata'] = {'name': 'ok175-authority-provider-probe'}
    create_profile = replace_document(profile_doc); create_profile['metadata'] = {'name': 'ok175-authority-profile-probe'}
    documents = (
        ('developerworkspaces', create_owner, replace_document(live_owner)),
        ('objects', create_object, replace_document(live_object)),
        ('providerconfigs', create_provider, replace_document(provider)),
        ('environmentconfigs', create_profile, replace_document(live_profile)),
    )
    for resource, create_doc, replace_doc in documents:
        for identity, allowed in ((observer, False), (operator, True)):
            assert_server_dry_run(identity, 'create', resource, create_doc, allowed)
            assert_server_dry_run(identity, 'replace', resource, replace_doc, allowed)
    return {'operator': operator, 'observer': observer, 'resources': [resource for resource, _, _ in documents]}


def provider_api_document(group, resource, namespace, name):
    crd = get_json(['get', 'crd', f'{resource}.{group}'])
    version = next((v['name'] for v in crd['spec']['versions'] if v.get('storage')),
                   next(v['name'] for v in crd['spec']['versions'] if v.get('served')))
    kind = crd['spec']['names']['kind']
    metadata = {'name': name, 'namespace': namespace}
    if resource == 'providerconfigs':
        spec = {'credentials': {'source': 'InjectedIdentity'}}
    elif resource == 'objects':
        spec = {
            'forProvider': {'manifest': {'apiVersion': 'v1', 'kind': 'ConfigMap',
                                         'metadata': {'name': 'provider-steering-probe', 'namespace': namespace},
                                         'data': {'proof': 'denied'}}},
            'providerConfigRef': {'kind': 'ProviderConfig', 'name': 'provider-steering-probe'},
        }
    else:
        raise ProofError(f'no provider steering proof fixture for {resource}.{group}')
    return {'apiVersion': f'{group}/{version}', 'kind': kind, 'metadata': metadata, 'spec': spec}


def assert_provider_steering_denied(identity, resource, document):
    done = kubectl(['create', '-f', '-', f'--as={identity}'], input_text=yaml.safe_dump(document), check=False)
    expect(done.returncode != 0 and STEERING_POLICY in done.stderr,
           f'{identity} real create {resource} was not denied by {STEERING_POLICY}: '
           f'rc={done.returncode} {done.stderr.strip()[:300]}')


def prove_namespaced_provider_steering_denied():
    operator = f'system:serviceaccount:{PROOF_NS}:{OPERATOR_SA}'
    nonoperator = f'system:serviceaccount:{STEERING_NS}:{STEERING_SA}'
    subjects = (
        {'kind': 'ServiceAccount', 'name': STEERING_SA, 'namespace': STEERING_NS},
        {'kind': 'ServiceAccount', 'name': OPERATOR_SA, 'namespace': PROOF_NS},
    )
    fixtures = (
        ('providerconfigs', provider_api_document('kubernetes.m.crossplane.io', 'providerconfigs',
                                                  STEERING_NS, 'provider-steering-probe')),
        ('objects', provider_api_document('kubernetes.m.crossplane.io', 'objects',
                                          STEERING_NS, 'provider-steering-probe')),
    )
    existing = kubectl(['get', 'namespace', STEERING_NS], check=False)
    expect(is_not_found(existing),
           f'provider steering proof Namespace must not pre-exist: rc={existing.returncode} '
           f'{existing.stderr.strip()[:300]}')
    try:
        apply([
            {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': STEERING_NS}},
            {'apiVersion': 'v1', 'kind': 'ServiceAccount', 'metadata': {'name': STEERING_SA, 'namespace': STEERING_NS}},
            {'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
             'metadata': {'name': 'provider-steering-crossplane-edit', 'namespace': STEERING_NS},
             'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'ClusterRole', 'name': 'crossplane-edit'},
             'subjects': list(subjects)},
        ])
        assert_can_i(nonoperator, 'update', 'environmentconfigs.apiextensions.crossplane.io', False,
                     name='developer-workspace-profile')
        assert_can_i(operator, 'update', 'environmentconfigs.apiextensions.crossplane.io', True,
                     name='developer-workspace-profile')
        for resource, document in fixtures:
            target_resource = f'{resource}.kubernetes.m.crossplane.io'
            # This is the attack precondition and the control for a false RBAC denial.
            assert_can_i(nonoperator, 'create', target_resource, True, namespace=STEERING_NS)
            assert_provider_steering_denied(nonoperator, resource, document)
            missing = kubectl(['get', f'{target_resource}/{document["metadata"]["name"]}',
                               '-n', STEERING_NS], check=False)
            expect(is_not_found(missing),
                   f'denied {target_resource} persisted or absence was not confirmed by NotFound: '
                   f'{missing.stderr.strip()[:300]}')
            # crossplane-edit supplies namespaced CRUD; named profile update authority is the
            # policy's independent operator definition.
            assert_can_i(operator, 'create', target_resource, True, namespace=STEERING_NS)
            admitted = kubectl(['create', '--dry-run=server', '-f', '-', f'--as={operator}'],
                               input_text=yaml.safe_dump(document), check=False)
            expect(admitted.returncode == 0,
                   f'operator dry-run create {resource} was not admitted: {admitted.stderr.strip()[:300]}')
        return {'namespace': STEERING_NS, 'nonoperator': nonoperator, 'operator': operator,
                'resources': [resource for resource, _document in fixtures], 'policy': STEERING_POLICY}
    finally:
        kubectl(['delete', 'namespace', STEERING_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        missing = kubectl(['get', 'namespace', STEERING_NS], check=False)
        expect(is_not_found(missing),
               f'cleanup did not confirm provider steering proof Namespace absent: {missing.stderr.strip()[:300]}')

def admission_receipt_refusal(name, workspace_id, revision, namespace_prefix, owned=None):
    """Submit directly so the Composition, rather than the harness's local gate, proves refusal."""
    namespace = namespace_prefix + workspace_id.removeprefix('ws-')
    for resource, description in ((f'developerworkspace/{name}', 'DeveloperWorkspace'),
                                  (f'namespace/{namespace}', 'Namespace')):
        existing = kubectl(['get', resource], check=False)
        expect(is_not_found(existing), f'receipt probe refuses to overwrite {description}/{resource.split("/", 1)[1]}')
    document = workspace_inputs(name, workspace_id, revision, 'persistent')
    created_result = kubectl(['create', '-f', '-', '-o', 'json'], input_text=yaml.safe_dump(document))
    created = json.loads(created_result.stdout)
    uid = created.get('metadata', {}).get('uid')
    expect(bool(uid), f'receipt probe DeveloperWorkspace/{name} lacks a UID after apply')
    if owned is not None:
        owned.append((name, uid))

    observed = {}
    def refused():
        xr = get_json(['get', f'developerworkspace/{name}'])
        conditions = {condition['type']: condition for condition in xr.get('status', {}).get('conditions', [])}
        synced = conditions.get('Synced', {})
        message = synced.get('message', '')
        receipt_named = render_profile.ADMISSION_READY_NAME in message
        receipt_reason = ('not found' in message.lower() or 'admission installation receipt' in message)
        if synced.get('status') != 'False' or not (receipt_named and receipt_reason):
            return False
        observed.update(conditions=conditions)
        return True
    wait_until(f'{name} to refuse an invalid admission installation receipt', refused, timeout=180, interval=3)
    ready = observed['conditions'].get('Ready', {}).get('status')
    missing_namespace = kubectl(['get', f'namespace/{namespace}'], check=False)
    refs = composed_objects(name)
    expect(ready != 'True' and not refs and is_not_found(missing_namespace),
           f'{name} composed resources or became Ready without a valid receipt: ready={ready} refs={refs} '
           f'namespace={missing_namespace.stderr.strip()[:200]}')
    return {'name': name, 'ready': ready, 'objectRefs': refs, 'namespace': namespace,
            'namespaceAbsent': True,
            'message': observed['conditions']['Synced'].get('message', '')}

def prove_admission_receipt_gate(revision, namespace_prefix):
    """Exercise missing and wrong receipts, then restore the exact installation receipt."""
    observations, owned = {}, []
    try:
        observations['initial'] = admission_ready_readback()
        invalidate_admission_ready()
        observations['missing'] = admission_receipt_refusal(*RECEIPT_PROBES[0], revision, namespace_prefix, owned)
        wrong = render_profile.admission_ready_config()
        wrong['data']['guardRevision'] = 'wrong-revision'
        apply([wrong])
        observations['wrong'] = admission_receipt_refusal(*RECEIPT_PROBES[1], revision, namespace_prefix, owned)
    finally:
        for name, uid in owned:
            current = kubectl(['get', f'developerworkspace/{name}', '-o', 'json'], check=False)
            expect(current.returncode == 0 and json.loads(current.stdout).get('metadata', {}).get('uid') == uid,
                   f'receipt proof cleanup refuses to delete replaced DeveloperWorkspace/{name}')
            # kubectl has no --preconditions flag; a raw DELETE carries the UID precondition.
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {'uid': uid}}
            deleted = kubectl(['delete', f'--raw=/apis/workspace.openkubes.io/v0alpha1/developerworkspaces/{name}', '-f', '-'],
                              input_text=json.dumps(options), check=False)
            expect(deleted.returncode == 0, f'receipt proof cleanup failed for DeveloperWorkspace/{name}: {deleted.stderr.strip()[:300]}')
            wait_until(f'DeveloperWorkspace/{name} removal',
                       lambda name=name: is_not_found(kubectl(['get', f'developerworkspace/{name}'], check=False)), timeout=300)
        observations['restored'] = publish_admission_ready()
    for name, _workspace_id in RECEIPT_PROBES:
        missing = kubectl(['get', f'developerworkspace/{name}'], check=False)
        expect(is_not_found(missing) and not composed_objects(name),
               f'admission receipt proof cleanup left DeveloperWorkspace/{name} or composed Objects')
    return observations

def delete_and_confirm_gone(name, namespace, expected_count):
    # Counting first keeps the "none left" check from passing on a label that never matched.
    expect(len(composed_objects(name)) == expected_count, f'{name} has {len(composed_objects(name))} composed Objects, expected {expected_count}')
    volumes = [c['spec'].get('volumeName') for c in get_json(['get', 'pvc', '-n', namespace])['items']]
    expect(all(volumes), f'unbound PVC in {namespace}')
    kubectl(['delete', f'developerworkspace/{name}', '--wait=true', '--timeout=600s'], timeout=630)
    wait_until(f'namespace {namespace} removal', lambda: is_not_found(kubectl(['get', 'namespace', namespace], check=False)), timeout=600)
    # The XR is gone before its composed Objects finish deleting; wait for them, bounded.
    wait_until(f'composed Objects of {name} to be deleted', lambda: not composed_objects(name), timeout=300)
    for volume in volumes:
        wait_until(f'PersistentVolume {volume} removal', lambda volume=volume: is_not_found(kubectl(['get', 'pv', volume], check=False)), timeout=300)
    return len(volumes)

def registry_inputs(runtime_image):
    username = os.environ.get('OK175_REGISTRY_USERNAME', ''); pulls = bool(username)
    password = os.read(int(os.environ['OK175_REGISTRY_PASSWORD_FD']), 4096).decode().strip() if pulls else ''
    expect(not pulls or password, 'registry password descriptor is empty')
    registry = runtime_image.split('/', 1)[0]
    return pulls, registry, username, password


def live_profile(runtime_image, storage):
    profile = copy.deepcopy(storage['profile'])
    profile['spec']['runtimeProfiles']['opencode']['image'] = runtime_image
    profile['spec']['storageClassName'] = storage['storageClassName']; profile['spec']['hostUsers'] = storage['hostUsers']
    return profile


def fixture_setup(fixture_image, tls, read_token, write_token, pulls, registry, username, password, hands_on=False,
                  hands_on_nonce=None, on_namespace_created=None):
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': PROOF_NS}}
    if hands_on:
        namespace['metadata']['labels'] = {HANDS_ON_LABEL: 'true'}
        if hands_on_nonce: namespace['metadata']['annotations'] = {HANDS_ON_RUN: hands_on_nonce}
        created = kubectl(['create', '-f', '-', '-o', 'json'], input_text=yaml.safe_dump(namespace))
        if on_namespace_created:
            try: on_namespace_created(json.loads(created.stdout))
            except json.JSONDecodeError as error: raise ProofError(f'Namespace/{PROOF_NS} create returned no UID JSON: {error}') from error
    else: kubectl(['create', 'namespace', PROOF_NS])
    wait_for_default_serviceaccount(PROOF_NS)
    if pulls: apply([pull_secret(PROOF_NS, registry, username, password)])
    objects = proof_services(fixture_image, tls, read_token, write_token, pulls)
    if hands_on:
        objects = [o for o in objects if o['kind'] not in ('Namespace', 'Pod')]
        next(o for o in objects if o['metadata']['name'] == 'git-source-tokens')['stringData'].pop('write')
        git = next(o for o in objects if o['kind'] == 'Deployment')['spec']['template']['spec']['containers'][0]
        next(e for e in git['env'] if e['name'] == 'GIT_WRITE_TOKEN').update({'value': ''})
        next(e for e in git['env'] if e['name'] == 'GIT_WRITE_TOKEN').pop('valueFrom')
    apply(objects)
    kubectl(['rollout', 'status', 'deployment/git-fixture', '-n', PROOF_NS, '--timeout=300s'], timeout=330)
    if not hands_on: kubectl(['wait', '--for=condition=Ready', 'pod/control', '-n', PROOF_NS, '--timeout=300s'], timeout=330)
    source_pod = get_json(['get', 'pods', '-n', PROOF_NS, '-l', 'app=git-fixture'])['items'][0]['metadata']['name']
    known = exec_in(PROOF_NS, source_pod, ['cat', '/srv/git/KNOWN_COMMIT']).stdout.strip(); expect(bool(re.fullmatch(r'[0-9a-f]{40}', known)), 'source did not report a known commit')
    # Control for the checkout check: the source's default branch has moved past the declared revision.
    tip = exec_in(PROOF_NS, source_pod, ['git', '--git-dir=/srv/git/workspace-fixture.git', 'rev-parse', 'HEAD']).stdout.strip()
    expect(bool(re.fullmatch(r'[0-9a-f]{40}', tip)) and tip != known, 'source tip equals the declared revision; the checkout check could not fail')
    return known, tip


def bring_up(name, workspace_id, mode, *, known, profile, read_token, tls, pulls, registry, username, password,
             composition, hands_on=False, ownership=None, resources=None, storage=None):
    expect(name == canonical_xr_name(workspace_id), f'{name} is not the canonical XR name for {workspace_id}')
    doc = workspace_inputs(name, workspace_id, known, mode); namespace = profile['spec']['namespacePrefix'] + workspace_id.removeprefix('ws-')
    if resources:
        doc['spec']['resources'].update(resources)
    # Hands-on pre-creates and journals its Namespace with an atomic CREATE. The proof path
    # still asks the reconciler to create its Namespace and refuses a pre-existing one.
    if ownership:
        ns_entry = require_ledger_entry(ownership['state']['resources'], 'workspaceNamespace', 'namespace', namespace)
        expect(owned_live(ns_entry, ownership['state']['nonce']) is not None,
               f'Namespace/{namespace} disappeared before XR creation')
    else:
        expect(optional_object('namespace', namespace) is None, f'namespace {namespace} already exists')
    if hands_on:
        doc['metadata'].setdefault('labels', {})[HANDS_ON_LABEL] = 'true'
        if ownership:
            doc['metadata'].setdefault('annotations', {})[HANDS_ON_RUN] = ownership['state']['nonce']
            journal_intent(ownership['path'], ownership['state'], 'xr', 'developerworkspace', name)
        created = gated_xr_request(['create', '-f', '-', '-o', 'json'], doc)[1]
        if ownership:
            try: created_xr = json.loads(created.stdout)
            except json.JSONDecodeError as error: raise ProofError(f'DeveloperWorkspace/{name} create returned no UID JSON: {error}') from error
            mark_owned(ownership['path'], ownership['state'], 'xr', created_xr)
    else: gated_xr_request(['apply', '-f', '-'], doc)
    wait_until(f'namespace {namespace}', lambda: kubectl(['get', 'namespace', namespace], check=False).returncode == 0, timeout=300)
    if ownership:
        owned_live(ns_entry, ownership['state']['nonce'])
    # Per-run values the contract only references: the source credential, CA and pull Secret.
    support = [{'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'workspace-git-auth', 'namespace': namespace}, 'type': 'Opaque', 'stringData': {'token': read_token}},
               {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'git-fixture-ca', 'namespace': namespace}, 'data': {'ca.crt': tls['ca']}}]
    if pulls: support.append(pull_secret(namespace, registry, username, password))
    apply(support)
    if storage is not None:
        assert_capacity_marker(namespace, storage)
    wait_ready(name)
    revision = revision_matches(name, composition)
    xr, created = get_json(['get', f'developerworkspace/{name}']), get_json(['get', 'namespace', namespace])
    if ownership:
        expect(created['metadata']['uid'] == ns_entry['uid'], f'Namespace/{namespace} UID changed during setup')
        expect(xr['metadata']['uid'] == ownership['state']['resources']['xr']['uid'], f'DeveloperWorkspace/{name} UID changed during setup')
        composed_child_matches(name, 'Namespace', None, created, xr['metadata']['uid'])
    else:
        expect(created['metadata']['creationTimestamp'] >= xr['metadata']['creationTimestamp'], f'namespace {namespace} predates its DeveloperWorkspace')
    if ownership:
        record_workspace_pv(ownership['path'], ownership['state'], namespace,
                            ownership['state']['resources']['xr']['uid'])
    return doc, namespace, revision


# ---- run ------------------------------------------------------------------------------------

def run(args):
    started = now(); run_id = secrets.token_hex(8); storage = storage_inputs(); tgt = target(); impl = implementation(args.require_clean)
    runtime_image, fixture_image = image('OK175_RUNTIME_IMAGE'), image('OK175_FIXTURE_IMAGE')
    pulls, registry, username, password = registry_inputs(runtime_image)
    tls = spike.tls_material(); read_token, write_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    results = []
    def record(name, detail, **observed): results.append({'name': name, 'status': 'pass', 'detail': detail, **({'observed': observed} if observed else {})}); print(f'PASS {name}: {detail}', flush=True)

    expect(not get_json(['get', 'developerworkspaces'])['items'], 'DeveloperWorkspaces already exist on the target')
    # Cleanup below deletes these by name, so a run may only start when none of them exists.
    for kind, name in (('namespace', PROOF_NS), ('namespace', 'dw-ok175-squat'), ('namespace', STEERING_NS),
                       ('environmentconfig', 'developer-workspace-profile'),
                       ('clusterrolebinding', OPERATOR_BINDING), ('clusterrolebinding', OBSERVER_BINDING)):
        existing = kubectl(['get', kind, name], check=False)
        expect(is_not_found(existing), f'{kind}/{name} already exists or could not be confirmed absent; refusing to run')
    try:
        known, tip = fixture_setup(fixture_image, tls, read_token, write_token, pulls, registry, username, password)
        composition = installed_matches_local()
        # The run entry point fails closed before its first XR request. Remove one binding to prove
        # that a missing guard cannot fall through to CREATE, then restore and re-observe the gate.
        gate_path = 'install/pod-user-namespace-guard.yaml'
        _, gate_bindings = admission_guard_documents(gate_path)
        gate_binding = gate_bindings[0]
        gate_probe = workspace_inputs(canonical_xr_name('ws-ok185-policy-gate'), 'ws-ok185-policy-gate', known, 'persistent')
        kubectl(['delete', 'validatingadmissionpolicybinding', gate_binding['metadata']['name'], '--wait=true'])
        gate_error = None
        try:
            try:
                gated_xr_request(['create', '-f', '-'], gate_probe)
            except ProofError as error:
                gate_error = str(error)
            expect(gate_error is not None and gate_binding['metadata']['name'] in gate_error,
                   f'missing admission binding did not stop the XR entry point: {gate_error!r}')
            missing = kubectl(['get', f'developerworkspace/{gate_probe["metadata"]["name"]}'], check=False)
            expect(missing.returncode != 0 and 'NotFound' in missing.stderr and
                   not composed_objects(gate_probe['metadata']['name']),
                   'missing-policy gate dispatched an XR or composed Object')
        finally:
            apply_file(CAPABILITY / gate_path)
            wait_for_admission_policies()
        record('admission-policy-gate', 'removing one binding made the current/local policy gate fail before XR CREATE; the XR stayed NotFound with no composed Objects, then the restored gate became current')

        # Admission: the XRD's CEL rules reject an inconsistent lifecycle and noncanonical identity;
        # the same documents made consistent and canonical pass.
        cel_name = canonical_xr_name('ws-ok175-cel')
        bad = workspace_inputs(cel_name, 'ws-ok175-cel', known, 'persistent'); bad['spec']['storage']['mode'] = 'ephemeral'
        composition, rejected = gated_xr_request(['apply', '--dry-run=server', '-f', '-'], bad, check=False)
        expect(rejected.returncode != 0 and 'persistent lifecycle requires persistent storage' in rejected.stderr, 'XRD admitted a persistent lifecycle with ephemeral storage')
        canonical = workspace_inputs(cel_name, 'ws-ok175-cel', known, 'persistent')
        composition, _ = gated_xr_request(['create', '--dry-run=server', '-f', '-'], canonical)
        wrong_name = copy.deepcopy(canonical); wrong_name['metadata']['name'] = 'ok175-cel-probe'
        _, rejected_name = gated_xr_request(['create', '--dry-run=server', '-f', '-'], wrong_name, check=False)
        expect(rejected_name.returncode != 0 and 'metadata.name' in rejected_name.stderr and 'workspaceID' in rejected_name.stderr and '-xr' in rejected_name.stderr,
               'XRD admitted a DeveloperWorkspace whose metadata.name is not derived from workspaceID')
        try:
            noncanonical = assert_noncanonical_name_refused(rejected_name, wrong_name['metadata']['name'])
        finally:
            # Cleanup only if the guard regressed and the supposedly rejected document persisted.
            if rejected_name.returncode == 0:
                kubectl(['delete', f'developerworkspace/{wrong_name["metadata"]["name"]}', '--ignore-not-found', '--wait=true', '--timeout=300s'], timeout=330, check=False)
        record('admission-rules', 'the API server rejects inconsistent lifecycle and noncanonical workspace identity documents, then admits the consistent canonical document')
        record('canonical-name-rule', 'the API server rejects a distinct noncanonical metadata.name and admits metadata.name = spec.workspaceID + "-xr"',
               rejected=noncanonical, admitted=canonical['metadata']['name'])
        # Without the profile EnvironmentConfig a workspace must compose nothing and must not be Ready.
        probe = workspace_inputs(*NO_PROFILE, known, 'persistent'); gated_xr_request(['apply', '-f', '-'], probe)
        def no_profile_settled():
            conditions = {c['type']: c for c in get_json(['get', f'developerworkspace/{NO_PROFILE[0]}']).get('status', {}).get('conditions', [])}
            return conditions.get('Synced', {}).get('status') == 'False' and 'developer-workspace-profile not found' in conditions['Synced'].get('message', '')
        wait_until('the no-profile workspace to report the missing profile', no_profile_settled, timeout=180, interval=3)
        conditions = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{NO_PROFILE[0]}'])['status']['conditions']}
        no_profile_namespace = kubectl(['get', 'namespace', 'dw-ok175-no-profile'], check=False)
        expect(conditions.get('Ready') != 'True' and not composed_objects(NO_PROFILE[0]) and is_not_found(no_profile_namespace),
               f'no-profile workspace composed, became Ready, or Namespace absence was not confirmed by NotFound: {conditions}; {no_profile_namespace.stderr.strip()[:200]}')
        kubectl(['delete', f'developerworkspace/{NO_PROFILE[0]}', '--wait=true', '--timeout=300s'], timeout=330)
        record('no-profile-fails-closed', 'without the profile EnvironmentConfig the workspace reports it missing, composes nothing and is not Ready', ready=conditions.get('Ready'))

        profile = copy.deepcopy(storage['profile'])
        profile['spec']['runtimeProfiles']['opencode']['image'] = runtime_image
        profile['spec']['storageClassName'] = storage['storageClassName']; profile['spec']['hostUsers'] = storage['hostUsers']
        profile_config = render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')
        kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(profile_config))
        profile_initial = profile_readback(profile_config)
        receipt_gate = prove_admission_receipt_gate(known, profile['spec']['namespacePrefix'])
        record('admission-receipt-gate', 'direct XR requests with a missing or wrong installation receipt stay unready with zero composed Objects and no Namespace; the exact receipt is restored before the normal workspace positive path',
               **receipt_gate)

        def bring_up_workspace(name, workspace_id, mode, resources=None):
            profile_readback(profile_config, profile_initial)
            return bring_up(name, workspace_id, mode, known=known, profile=profile, read_token=read_token, tls=tls,
                            pulls=pulls, registry=registry, username=username, password=password, composition=composition,
                            resources=resources, storage=storage)

        if storage['mode'] == 'self-declared-negative':
            refuse_self_declared_capacity(storage, bring_up_workspace)
            raise ProofError('negative control returned without refusing certification')
        # Dedicated Namespace: a workspace whose Namespace already exists must not adopt it.
        squat = 'dw-ok175-squat'
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': squat}},
               {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'owner-data', 'namespace': squat}, 'data': {'k': 'v'}}])
        gated_xr_request(['apply', '-f', '-'], workspace_inputs(SQUAT[0], SQUAT[1], known, 'persistent'))
        def refused():
            for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items']:
                if o['metadata'].get('labels', {}).get('crossplane.io/composite') == SQUAT[0] and o['spec']['forProvider']['manifest']['kind'] == 'Namespace':
                    # Both Namespace guards deny the provider here; the API server reports whichever it
                    # evaluated first, so either policy's exact denial counts (as for the install probe).
                    return any(('developer-workspace-namespace-guard' in c.get('message', '') and 'only Namespaces it created' in c.get('message', '')) or
                               (NAMESPACE_HOST_USERS_POLICY in c.get('message', '') and 'must preserve the workspace identity and render host-users' in c.get('message', ''))
                               for c in o.get('status', {}).get('conditions', []))
            return False
        wait_until('the provider to be refused the existing Namespace', refused, timeout=300, interval=3)
        time.sleep(20)  # let every other composed Object attempt its write too
        existing = get_json(['get', 'namespace', squat])
        ready = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{SQUAT[0]}']).get('status', {}).get('conditions', [])}.get('Ready')
        written = [f"{k}/{i['metadata']['name']}" for k in ('serviceaccounts', 'resourcequotas', 'limitranges', 'networkpolicies', 'persistentvolumeclaims', 'deployments') for i in get_json(['get', k, '-n', squat])['items'] if not spike.controller_default(i)]
        expect('workspace.openkubes.io/id' not in existing['metadata'].get('labels', {}) and not written and ready != 'True'
               and kubectl(['get', 'configmap/owner-data', '-n', squat], check=False).returncode == 0, f'existing Namespace was adopted or written: written={written} ready={ready}')
        kubectl(['delete', 'namespace', squat, '--wait=true'], timeout=600)  # the owner removes it, then the XR can go
        kubectl(['delete', f'developerworkspace/{SQUAT[0]}', '--wait=true', '--timeout=300s'], timeout=330)
        wait_until(f'composed Objects of {SQUAT[0]} to be deleted', lambda: not composed_objects(SQUAT[0]), timeout=300)
        record('dedicated-namespace-enforced', 'a workspace whose Namespace already existed was refused it: no label, no workspace object written, owner data intact, XR not Ready; the persistent run below is the control', ready=ready)

        doc, ns, revision = bring_up_workspace(*PERSISTENT, 'persistent')
        xr = get_json(['get', f'developerworkspace/{PERSISTENT[0]}'])
        expect(xr.get('status', {}).get('namespace') == ns and xr['status'].get('lifecyclePhase') == 'running', f"XR status {xr.get('status', {}).get('namespace')}/{xr.get('status', {}).get('lifecyclePhase')}")
        count = readback(ns, expected_objects(doc, profile, pulls))
        record('reconcile-readback', f'XR Ready; {count} reconciled objects equal capability reference rendering for the persistent profile; the XR runs the local Composition', namespace=ns, lifecyclePhase='running', compositionRevision=revision)

        # workspaceID is the durable identity: even a server-side dry-run update cannot change it.
        live_owner = get_json(['get', f'developerworkspace/{PERSISTENT[0]}'])
        changed = replace_document(live_owner); changed['spec']['workspaceID'] = 'ws-ok175-mutated'
        immutable = kubectl(['replace', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(changed), check=False)
        expect(immutable.returncode != 0 and 'workspaceID' in immutable.stderr and 'immutable' in immutable.stderr.lower(),
               f'workspaceID mutation was not rejected: {immutable.stderr.strip()[:300]}')
        kubectl(['replace', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(replace_document(live_owner)))
        record('workspace-id-immutable', 'the API server rejects a workspaceID update and admits an otherwise identical replacement')

        authority = prove_authority_boundary(PERSISTENT[0], doc, profile_config)
        record('authority-boundary-rbac', 'observer is read-only for DeveloperWorkspace and denied every mutation; operator passes documented can-i checks and real server dry-run create/update checks for all four resource types', **authority)

        provider_steering = prove_namespaced_provider_steering_denied()
        record('namespaced-provider-steering-denied',
               'a non-operator with namespaced crossplane-edit RBAC is denied real ProviderConfig and Object creates by the named admission policy; the operator is admitted by server dry-run',
               **provider_steering)

        label_admission = namespace_label_probes(ns, storage['mode'])
        record('namespace-host-users-label-authority', 'temporary name-scoped Namespace RBAC lets the workspace and observer requests reach admission, which rejects both protected-label changes; the operator controls are admitted and the temporary grant is removed', **label_admission)
        provider_labels = provider_label_reconcile_probes(PERSISTENT[0], ns)
        record('provider-host-users-label-reconcile', 'one standalone provider-kubernetes Object owns a fixture Namespace label; drop and alter updates are Synced=False, rendered-value controls are Synced=True, and both fixtures are cleaned', **provider_labels)

        who_can = prove_authority_who_can()
        record('authority-who-can', 'all RBAC holders equal the documented expected subject sets for every cluster and namespaced steering kind and mutation verb',
               holders=who_can['holders'], effectiveRoleBindings=who_can['effectiveRoleBindings'],
               nonEffectiveRoleBindings=who_can['nonEffectiveRoleBindings'], scopes=who_can['scopes'],
               defaultCrossplaneGroupBindingPresent=who_can['defaultCrossplaneGroupBindingPresent'])
        record('authority-indirect-who-can', 'all RBAC holders of impersonation, bind, escalate, binding mutation, service-account token, Pod creation and Secret read paths equal the source-derived expected sets',
               holders=who_can['indirectHolders'], defaultCrossplaneGroupBindingPresent=who_can['defaultCrossplaneGroupBindingPresent'])

        rendered = expected_objects(doc, profile, pulls)
        collision = copy.deepcopy(doc)
        collision['metadata']['name'] = 'ws-ok175-proof-collision-xr'
        before = owner_snapshot(PERSISTENT[0], ns, rendered)
        _, denied_collision = gated_xr_request(['create', '-f', '-'], collision, check=False)
        refused_collision = assert_noncanonical_name_refused(denied_collision, collision['metadata']['name'])
        readback(ns, rendered)
        after_collision = owner_snapshot(PERSISTENT[0], ns, rendered)
        collision_owner = assert_owner_unchanged(before, after_collision)
        record('workspace-id-collision-refused', 'a second document with the live workspaceID and a distinct noncanonical name is rejected; owner UID/spec, Namespace, composed Objects and rendered-resource readback remain unchanged',
               candidate=refused_collision, owner=collision_owner)

        kubectl(['delete', f'developerworkspace/{collision["metadata"]["name"]}', '--ignore-not-found', '--wait=true'])
        deleted_candidate = kubectl(['get', f'developerworkspace/{collision["metadata"]["name"]}'], check=False)
        expect(is_not_found(deleted_candidate) and not composed_objects(collision['metadata']['name']),
               'deleting the rejected persistent collision did not leave it exactly absent')
        after_rejected_delete = owner_snapshot(PERSISTENT[0], ns, rendered)
        persistent_delete_isolation = assert_owner_unchanged(after_collision, after_rejected_delete)

        before = after_rejected_delete
        denied_collision = kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(doc), check=False)
        refused = assert_canonical_create_already_exists(denied_collision, PERSISTENT[0])
        readback(ns, rendered); after_create = owner_snapshot(PERSISTENT[0], ns, rendered)
        identities = assert_owner_unchanged(before, after_create)
        record('workspace-id-duplicate-create-refused', 'a second CREATE of the canonical owner name returns AlreadyExists; owner UID/spec, Namespace, composed Object resourceVersions/specs, and rendered-resource readback remain byte-equivalent', candidate=refused, owner=identities)
        # A reconciler, not a one-shot apply: remove the default-deny policy and require it back as rendered.
        # A new UID is the control that the policy was really deleted, however fast it returns.
        uid = lambda: (lambda d: json.loads(d.stdout)['metadata']['uid'] if d.returncode == 0 else None)(kubectl(['get', 'networkpolicy/default-deny', '-n', ns, '-o', 'json'], check=False))
        before = uid(); expect(before is not None, 'default-deny missing before drift')
        kubectl(['delete', 'networkpolicy/default-deny', '-n', ns, '--wait=true']); removed = time.monotonic()
        wait_until('default-deny to be restored', lambda: uid() not in (None, before), timeout=300, interval=2)
        readback(ns, expected_objects(doc, profile, pulls))
        patched = json.loads(kubectl(['patch', 'resourcequota/workspace-bounds', '-n', ns, '--type=merge', '-o', 'json', '-p', json.dumps({'spec': {'hard': {'limits.cpu': '64'}}})]).stdout)
        expect(patched['spec']['hard']['limits.cpu'] == '64', 'control: quota patch did not land')  # the response is the patched object itself
        quota = lambda: get_json(['get', 'resourcequota/workspace-bounds', '-n', ns])
        wait_until('quota limits.cpu to be restored', lambda: (lambda q: q['metadata']['resourceVersion'] != patched['metadata']['resourceVersion'] and q['spec']['hard']['limits.cpu'] == doc['spec']['resources']['cpu'])(quota()), timeout=300, interval=2)
        readback(ns, expected_objects(doc, profile, pulls))
        record('drift-restored', 'a deleted default-deny NetworkPolicy was recreated (new UID) and a patched quota value was reverted, both as rendered', seconds=round(time.monotonic() - removed))
        pod = workspace_pod(ns)
        pod_template = get_json(['get', 'deployment/workspace', '-n', ns])['spec']['template']
        pod_spec = pod_template['spec']
        expect(pod_spec.get('hostUsers') is storage['hostUsers'], f'rendered pod hostUsers {pod_spec.get("hostUsers")!r} differs from explicit input {storage["hostUsers"]}')
        admission = pod_user_namespace_probes(ns, pod_template, storage['mode'])
        if storage['mode'] == 'enforced':
            detail = 'the selected workspace Namespace denied dry-run Pods with hostUsers absent or true specifically by the user-namespace policy; hostUsers=false was admitted'
        else:
            detail = 'the workspace Namespace lacks the policy selector label; dry-run Pods with hostUsers absent, true and false were admitted as unselected controls'
        record('pod-user-namespace-admission', detail, **admission)

        ephemeral_admission = ephemeralcontainers_probes(fixture_image, ns)
        record('ephemeralcontainers-admission', 'the ephemeralcontainers subresource admits a hostUsers=false Pod, rejects a pre-existing hostUsers=true Pod by the Pod policy, and remains outside workspace and observer RBAC; both requests were server dry-runs', **ephemeral_admission)

        head = exec_in(ns, pod, ['git', '-C', '/workspace', 'rev-parse', 'HEAD'], 'runtime'); expect(head.returncode == 0 and head.stdout.strip() == known, 'checkout is not the declared revision')
        record('source-checkout', 'workspace HEAD equals the declared revision, not the newer default-branch tip', commit=known, sourceTip=tip)

        marker_value = f'ok176-persistent-marker-{run_id}'
        marker_path = '/workspace/.ok176-persistence-marker'
        marker_write = exec_in(ns, pod, ['node', '-e', MARKER_WRITE_JS, marker_value, marker_path], 'runtime')
        expect(marker_write.returncode == 0 and re.fullmatch(r'[0-9a-f]{64}', marker_write.stdout.strip()), f'could not write persistent marker: {marker_write.stderr.strip()[:200]}')
        marker_sha = marker_write.stdout.strip(); old_uid = get_json(['get', f'pod/{pod}', '-n', ns])['metadata']['uid']
        kubectl(['delete', f'pod/{pod}', '-n', ns, '--wait=true'])
        replacement = {}
        def replacement_ready():
            pods = [p for p in get_json(['get', 'pods', '-n', ns])['items'] if p.get('status', {}).get('phase') == 'Running' and not p['metadata'].get('deletionTimestamp')]
            if len(pods) != 1 or pods[0]['metadata']['name'] == pod: return False
            statuses = {c['name']: c.get('ready') for c in pods[0].get('status', {}).get('containerStatuses', [])}
            if statuses.get('runtime') is not True: return False
            replacement.update(name=pods[0]['metadata']['name'], uid=pods[0]['metadata']['uid']); return True
        wait_until('a ready replacement workspace pod', replacement_ready, timeout=300, interval=3)
        expect(replacement['uid'] != old_uid, 'workspace pod replacement retained the old Pod UID')
        pod = replacement['name']
        live_pod = get_json(['get', f'pod/{pod}', '-n', ns])
        expect(live_pod['spec'].get('hostUsers') is storage['hostUsers'], f'live pod hostUsers {live_pod["spec"].get("hostUsers")!r} differs from explicit input {storage["hostUsers"]}')
        marker_read = exec_in(ns, pod, ['node', '-e', MARKER_READ_JS, marker_path], 'runtime')
        expect(marker_read.returncode == 0 and marker_read.stdout.strip() == marker_sha, f'persistent marker changed across pod replacement: {marker_read.stderr.strip()[:200]}')
        record('persistent-marker-survives-replacement', 'a marker retained the same sha256 after the workspace Pod was replaced', markerSha256=marker_sha, oldPodUID=old_uid, newPodUID=replacement['uid'])

        runtime_uid = exec_in(ns, pod, ['id', '-u'], 'runtime'); runtime_map = exec_in(ns, pod, ['cat', '/proc/self/uid_map'], 'runtime')
        expect(runtime_uid.returncode == runtime_map.returncode == 0 and runtime_uid.stdout.strip().isdigit(), 'could not read runtime UID mapping')
        boundary = uid_boundary(int(runtime_uid.stdout.strip()), runtime_map.stdout, storage['hostUsers'])
        record('runtime-user-boundary', f'the live workspace Pod has hostUsers={str(storage["hostUsers"]).lower()}; its runtime UID mapping was recorded and is nonidentity when user namespaces are required', hostUsers=storage['hostUsers'], **boundary)

        token = exec_in(ns, pod, ['sh', '-c', 'test ! -e /var/run/secrets/kubernetes.io/serviceaccount/token'], 'runtime'); expect(token.returncode == 0, 'a ServiceAccount token is mounted')
        sa = f'system:serviceaccount:{ns}:workspace'
        can = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as={sa}']).stdout
        # Baseline: an identity with no bindings at all, in the same namespace. Whatever the cluster
        # grants every authenticated identity appears in both; anything else is workspace authority.
        baseline = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as=system:serviceaccount:{ns}:ok175-unbound']).stdout
        rows = lambda text: {re.sub(r'\s+', ' ', line.strip()) for line in text.splitlines() if line.strip()}
        expect(rows(can) == rows(baseline), f'workspace ServiceAccount authority differs from an unbound identity: {sorted(rows(can) ^ rows(baseline))}')
        # Beyond equality, the rows themselves must be discovery only: OK-174's allowlist plus the one
        # read Kubernetes >= 1.33 grants every authenticated identity (public ClusterTrustBundles).
        strict = lambda text: spike.rbac_list_denied('\n'.join(l for l in text.splitlines() if not re.match(r'\s*clustertrustbundles\.certificates\.k8s\.io\s+\[\]\s+\[\]\s+\[get list watch\]\s*$', l)))
        expect(strict(can), 'workspace ServiceAccount holds more than discovery authority')
        provider_sa = 'system:serviceaccount:crossplane-system:developer-workspace-provider-kubernetes'
        provider = kubectl(['auth', 'can-i', '--list', '-n', ns, f'--as={provider_sa}']).stdout
        expect(rows(provider) != rows(baseline) and not strict(provider), 'control: the comparison cannot tell a privileged identity from the baseline')
        bindings = get_json(['get', 'rolebindings', '-n', ns])['items']; expect(not bindings, f'RoleBindings exist in {ns}')
        record('kubernetes-authority-denied', 'no token mounted; can-i --list equals an unbound identity and is discovery-only; no RoleBindings; the provider identity fails both checks', baselineRows=len(rows(baseline)), providerRows=len(rows(provider)))

        api = exec_in(ns, pod, ['curl', '-ksS', '-o', '/dev/null', '--connect-timeout', '3', '--max-time', '3', KUBE_API], 'runtime')
        expect(spike.denied_egress(api.returncode, api.stderr), f'runtime reached the Kubernetes API (curl rc={api.returncode})')
        reach = exec_in(PROOF_NS, 'control', ['curl', '-ksS', '-o', '/dev/null', '-w', '%{http_code}', '--connect-timeout', '3', '--max-time', '5', KUBE_API])
        expect(reach.returncode == 0 and reach.stdout.strip() in ('401', '403'), 'control: Kubernetes API transport not reachable from the proof namespace')
        record('kubernetes-api-unreachable', 'runtime API connection refused or timed out; control reaches API transport', runtimeCurlExit=api.returncode, controlHttp=reach.stdout.strip())

        env = get_json(['get', 'deployment/workspace', '-n', ns])['spec']['template']['spec']
        expect(not spike.runtime_has_credential({'spec': {'template': {'spec': env}}}), 'runtime container holds the source credential')
        config = exec_in(ns, pod, ['git', '-C', '/workspace', 'config', '--list', '--show-origin'], 'runtime')
        expect(config.returncode == 0 and not re.search(r'extraheader|credential|askpass|token', config.stdout, re.I), 'workspace git config carries a credential setting')
        runtime_env = exec_in(ns, pod, ['sh', '-c', 'env | cut -d= -f1'], 'runtime').stdout.split()
        expect(not [v for v in runtime_env if re.search(r'TOKEN|PASSWORD|SECRET|CREDENTIAL', v)], f'runtime environment names a credential: {runtime_env}')
        # TLS verification is off for this probe only, so the result is the source's answer, not a CA failure.
        push = exec_in(ns, pod, ['sh', '-c', f'GIT_TERMINAL_PROMPT=0 git -c http.sslVerify=false -C /workspace push {GIT_URL} {known}:refs/heads/main {known}:refs/heads/agent-probe'], 'runtime')
        expect(push.returncode != 0 and re.search(r'could not read Username|Authentication failed|401', push.stderr) and 'SSL' not in push.stderr, f'runtime push was not refused for lack of a credential: {push.stderr.strip()[:200]}')
        record('runtime-push-denied', 'the runtime holds no source credential (git config, environment) and the source refuses its push to main and a new branch for lack of one', exit=push.returncode)

        auth = lambda var: f'-c http.extraHeader="Authorization: Bearer ${var}"'
        heads_of = lambda text: {line.split()[1]: line.split()[0] for line in text.splitlines() if line.strip()}
        tip_heads = heads_of(exec_in(PROOF_NS, 'control', ['sh', '-c', f'git {auth("GIT_READ_TOKEN")} ls-remote {GIT_URL}']).stdout)
        # Command-scoped -c only: `git clone -c` would persist the header into the clone and send it on every push.
        tmp = f'rm -rf /tmp/r && git {auth("GIT_READ_TOKEN")} clone -q --bare {GIT_URL} /tmp/r && cd /tmp/r && ! git config --get-all http.extraHeader'
        denied = exec_in(PROOF_NS, 'control', ['sh', '-c', f'{tmp} && git {auth("GIT_READ_TOKEN")} push {GIT_URL} {known}:refs/heads/main {known}:refs/heads/agent-probe'])
        expect(denied.returncode != 0 and '403' in denied.stderr, f'workspace credential push was not refused with 403 (rc={denied.returncode})')
        allowed = exec_in(PROOF_NS, 'control', ['sh', '-c', f'{tmp} && git {auth("GIT_WRITE_TOKEN")} push {GIT_URL} {known}:refs/heads/control-probe'])
        expect(allowed.returncode == 0, f'control: write-credential push failed: {allowed.stderr.strip()[:200]}')
        refs = exec_in(PROOF_NS, 'control', ['sh', '-c', f'git {auth("GIT_READ_TOKEN")} ls-remote {GIT_URL}']).stdout
        heads = heads_of(refs)
        expect('refs/heads/agent-probe' not in heads and heads.get('refs/heads/control-probe') == known, f'unexpected source refs {sorted(heads)}')
        expect({k: v for k, v in heads.items() if k.startswith('refs/heads/') and k != 'refs/heads/control-probe'} == {k: v for k, v in tip_heads.items() if k.startswith('refs/heads/')}, 'a branch moved')
        record('workspace-credential-push-denied', 'source refuses push with the workspace credential (403); write-credential control push succeeds; no denied ref exists', refs=sorted(heads))

        stored = [base64.b64decode(v).decode(errors='replace') for s in get_json(['get', 'secrets', '-n', ns])['items'] for v in (s.get('data') or {}).values()]
        expect(write_token not in stored and not any(write_token in v for v in stored), 'the write credential is present in the workspace namespace')
        record('write-credential-absent', 'no Secret in the workspace namespace carries the write credential', secrets=len(stored))

        # ---- OK-176: resource bounds, enforced by the kernel and the API server -------------------
        cpu_limit, mem_limit = doc['spec']['resources']['cpu'], doc['spec']['resources']['memory']
        cg = lambda f: exec_in(ns, pod, ['cat', f'/sys/fs/cgroup/{f}'], 'runtime')
        stat = lambda: {k: int(v) for k, v in (line.split() for line in cg('cpu.stat').stdout.splitlines())}
        quota_us, period_us = (int(x) for x in cg('cpu.max').stdout.split())
        rendered_cg = spike.cgroup_limits({'cpu': cpu_limit, 'memory': mem_limit})  # [memory.max, cpu quota, cpu period]
        expect([str(quota_us), str(period_us)] == rendered_cg[1:], f'cpu.max {quota_us} {period_us} does not encode {cpu_limit}')
        before, started_cpu = stat(), time.monotonic()
        # Demand of three busy loops, well above the limit; the CFS quota must hold usage to it.
        burn = exec_in(ns, pod, ['sh', '-c', 'for i in 1 2 3; do timeout 20 sh -c "while :; do :; done" & done; wait; true'], 'runtime')
        after, wall = stat(), time.monotonic() - started_cpu
        cores = (after['usage_usec'] - before['usage_usec']) / 1e6 / wall
        limit_cores = quota_us / period_us
        expect(burn.returncode == 0 and after['nr_throttled'] > before['nr_throttled'] and after['throttled_usec'] > before['throttled_usec'], 'CPU demand above the limit was not throttled')
        expect(cores <= limit_cores * 1.15, f'CPU usage {cores:.2f} cores exceeds the {limit_cores} limit')
        expect(cores >= limit_cores * 0.6, f'control: the burn used only {cores:.2f} cores, so the limit was not reached')
        record('cpu-bound-enforced', f'three busy loops for 20s used {cores:.2f} cores against a {cpu_limit} limit; the kernel throttled the container', limitCores=limit_cores, usedCores=round(cores, 2), throttledPeriods=after['nr_throttled'] - before['nr_throttled'])

        mem_bytes = int(cg('memory.max').stdout.strip()); expect(str(mem_bytes) == rendered_cg[0], f'memory.max {mem_bytes} does not encode {mem_limit}')
        # Kubernetes sets memory.oom.group, so an OOM kills the whole runtime container: the evidence is
        # kubelet's record of the termination, not the exec's exit code or the new cgroup's counters.
        runtime_status = lambda: next(c for c in get_json(['get', f'pod/{pod}', '-n', ns])['status']['containerStatuses'] if c['name'] == 'runtime')
        allocate = lambda mib: exec_in(ns, pod, ['node', '-e', f'const a=[];for(let i=0;i<{mib // 64};i++)a.push(Buffer.alloc(64*1024*1024,1));console.log("allocated", a.length*64)'], 'runtime')
        restarts = runtime_status()['restartCount']
        fits = allocate(mem_bytes // 2**20 // 2)
        expect(fits.returncode == 0 and 'allocated' in fits.stdout and runtime_status()['restartCount'] == restarts, f'control: half the memory limit could not be allocated (rc={fits.returncode})')
        over = allocate(mem_bytes // 2**20 * 3 // 2)
        expect('allocated' not in over.stdout, 'allocation above the memory limit completed')
        wait_until('kubelet to record the OOM kill', lambda: runtime_status()['restartCount'] > restarts, timeout=120, interval=2)
        terminated = runtime_status().get('lastState', {}).get('terminated', {})
        expect(terminated.get('reason') == 'OOMKilled' and terminated.get('exitCode') == 137, f'runtime was not OOM-killed: {terminated}')
        wait_until('the runtime to restart', lambda: runtime_status().get('ready') is True, timeout=180, interval=3)
        record('memory-bound-enforced', f'allocating 1.5x the {mem_limit} limit got the runtime OOMKilled (exit 137) and restarted; 0.5x succeeded', reason=terminated['reason'], exitCode=terminated['exitCode'])

        extra = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': 'over-quota', 'namespace': ns},
                 'spec': {'storageClassName': profile['spec']['storageClassName'], 'accessModes': ['ReadWriteOnce'], 'resources': {'requests': {'storage': doc['spec']['storage']['size']}}}}
        hard = get_json(['get', 'resourcequota/workspace-bounds', '-n', ns])['status']
        expect(hard['used'].get('requests.storage') == hard['hard'].get('requests.storage') == doc['spec']['storage']['size'], f'control: quota is not fully used by the workspace PVC: {hard}')
        rejected = kubectl(['apply', '-f', '-'], input_text=yaml.safe_dump(extra), check=False)
        expect(rejected.returncode != 0 and 'exceeded quota' in rejected.stderr and 'requests.storage' in rejected.stderr, f'a second PVC beyond the declared size was admitted: {rejected.stderr.strip()[:200]}')
        record('storage-quota-enforced', f'a second {doc["spec"]["storage"]["size"]} PVC was rejected: the quota requests.storage equals the declared size and is fully used', hard=hard['hard'].get('requests.storage'))

        limit = quantity_bytes(doc['spec']['storage']['size'])
        if storage['mode'] == 'enforced':
            reset = project_reset_probe(ns, pod)
            record('file-project-reset-rejected', 'the runtime file had a nonzero project ID; resetting it to zero was rejected with EINVAL (errno 22) and the ID stayed unchanged', tool=reset['tool'], projectIDBefore=reset['before'], projectIDAfter=reset['after'], errno=reset['errno'])
            capacity = capacity_probe(ns, pod, limit); validate_enforced_capacity(capacity, limit)
            boundaries = {'declaredBytes': limit, 'writeChunkBytes': WRITE_CHUNK, 'toleranceBytes': WRITE_CHUNK, **capacity}
            record('persistent-capacity-enforced', f'a 1 MiB-write runtime probe filled the declared {doc["spec"]["storage"]["size"]} allocation and was rejected with {capacity["error"]}', **boundaries)
        else:
            # Negative evidence (OK-176): local-path does not enforce PVC capacity at runtime. Recorded, not asserted as a bound.
            size_mib = int(doc['spec']['storage']['size'].rstrip('Gi')) * 1024
            over_fill = exec_in(ns, pod, ['sh', '-c', f'dd if=/dev/zero of=/workspace/.ok176-overfill bs=4M count={size_mib * 5 // 4 // 4} 2>/dev/null; rc=$?; du -sm /workspace/.ok176-overfill | cut -f1; rm -f /workspace/.ok176-overfill; exit $rc'], 'runtime')
            written = int((over_fill.stdout.split() or ['0'])[0])
            expect(over_fill.returncode == 0 and written > size_mib, f'expected the overfill to show local-path does not enforce capacity (rc={over_fill.returncode}, {written} MiB)')
            results.append({'name': 'persistent-capacity-not-enforced', 'status': 'observed', 'detail': f'{written} MiB were written into a {doc["spec"]["storage"]["size"]} local-path PVC: persistent capacity is bounded at admission (quota), not at write time', 'observed': {'writtenMiB': written, 'declared': doc['spec']['storage']['size']}})
            print(f'OBSERVED persistent-capacity-not-enforced: {written} MiB written into a {doc["spec"]["storage"]["size"]} PVC', flush=True)

        volumes = delete_and_confirm_gone(PERSISTENT[0], ns, count)
        expect(volumes == 1, f'persistent workspace had {volumes} PVCs')
        record('persistent-cleanup', f'deleting the XR removed its Namespace, all {count} composed Objects and the PersistentVolume')

        # These IDs collided under the former 40-bit Object-name hash. Reduced requests keep
        # this a concurrent Ready proof on the disposable single-worker profile.
        workspaces = []
        for identity in DISTINCT:
            edoc, ens, _ = bring_up_workspace(*identity, 'ephemeral', resources={'cpu': '100m', 'memory': '256Mi'})
            expected = expected_objects(edoc, profile, pulls)
            ecount = readback(ens, expected)
            volumes = {v['name']: v for v in get_json(['get', 'deployment/workspace', '-n', ens])['spec']['template']['spec']['volumes']}
            expect('emptyDir' in volumes['workspace'] and not get_json(['get', 'pvc', '-n', ens])['items'], f'{identity[0]} is not emptyDir-backed')
            workspaces.append({'name': identity[0], 'namespace': ens, 'doc': edoc, 'expected': expected,
                               'count': ecount, 'snapshot': owner_snapshot(identity[0], ens, expected)})
        for item in workspaces:
            ready = {c['type']: c['status'] for c in get_json(['get', f'developerworkspace/{item["name"]}'])['status']['conditions']}
            expect(ready.get('Ready') == 'True', f'{item["name"]} was not Ready while both distinct workspaces existed: {ready}')
        disjoint = assert_distinct_workspace_snapshots(workspaces[0]['snapshot'], workspaces[1]['snapshot'])
        record('ephemeral-reconcile', 'both former-hash-collision workspaces are concurrently Ready; each rendered readback is emptyDir-backed with no PVC',
               workspaces=[{'name': item['name'], 'namespace': item['namespace'], 'objects': item['count']} for item in workspaces], resources={'cpu': '100m', 'memory': '256Mi'})

        second = workspaces[1]
        second_volumes = delete_and_confirm_gone(second['name'], second['namespace'], second['count'])
        expect(second_volumes == 0, f'{second["name"]} unexpectedly had PersistentVolumes')
        first = workspaces[0]
        readback(first['namespace'], first['expected'])
        first_after = owner_snapshot(first['name'], first['namespace'], first['expected'])
        first_unchanged = assert_owner_unchanged(first['snapshot'], first_after, strict_object_rv=False, strict_resource_rv=False)
        record('distinct-workspace-isolation', 'ws-c69924 and ws-cd9634 are concurrently Ready with disjoint Namespaces/Object identities; deleting ws-cd9634 leaves ws-c69924 UIDs, desired Object specs and rendered-resource readback unchanged',
               deleted=second['name'], survivor=first['name'], disjoint=disjoint, survivorBeforeAndAfter=first_unchanged)
        first = workspaces[0]
        edoc, ens = first['doc'], first['namespace']
        epod = workspace_pod(ens); limit = edoc['spec']['storage']['size']; limit_mib = int(limit.rstrip('Mi'))
        small = exec_in(ens, epod, ['sh', '-c', f'dd if=/dev/zero of=/workspace/.ok176-fill bs=1M count={limit_mib // 2} 2>/dev/null && rm -f /workspace/.ok176-fill'], 'runtime')
        expect(small.returncode == 0, 'control: writing half the emptyDir limit failed')
        exec_in(ens, epod, ['sh', '-c', f'dd if=/dev/zero of=/workspace/.ok176-fill bs=1M count={limit_mib * 2} 2>/dev/null; sleep 60'], 'runtime')
        def evicted():
            p = kubectl(['get', f'pod/{epod}', '-n', ens, '-o', 'json'], check=False)
            if p.returncode: return None
            st = json.loads(p.stdout)['status']; return st if st.get('reason') == 'Evicted' else None
        wait_until('the overfilled ephemeral pod to be evicted', lambda: evicted() is not None, timeout=240, interval=3)
        message = evicted()['message']
        expect('workspace' in message and limit in message, f'eviction does not name the workspace volume and its {limit} limit: {message[:200]}')
        # The XR can still report Ready from before the eviction, so wait for the replacement Pod
        # itself: Running, not terminating, and not the evicted one.
        def replacement_running():
            pods = [p for p in get_json(['get', 'pods', '-n', ens])['items']
                    if p.get('status', {}).get('phase') == 'Running' and not p['metadata'].get('deletionTimestamp')
                    and p['metadata']['name'] != epod
                    and any(c.get('name') == 'runtime' and c.get('ready') is True
                            for c in p.get('status', {}).get('containerStatuses', []))]
            return len(pods) == 1
        wait_until('a running replacement for the evicted ephemeral pod', replacement_running, timeout=240, interval=3)
        wait_ready(first['name']); replacement = workspace_pod(ens); expect(replacement != epod, 'no replacement pod')
        record('ephemeral-storage-enforced', f'writing 2x the {limit} emptyDir limit evicted the pod (kubelet names the workspace volume); half the limit was fine; the reconciler brought a replacement up', limit=limit)

        ephemeral_collision = copy.deepcopy(edoc)
        ephemeral_collision['metadata']['name'] = 'ws-c69924-collision-xr'
        readback(ens, first['expected'])
        ephemeral_before = owner_snapshot(first['name'], ens, first['expected'])
        _, ephemeral_denied = gated_xr_request(['create', '-f', '-'], ephemeral_collision, check=False)
        ephemeral_refused = assert_noncanonical_name_refused(ephemeral_denied, ephemeral_collision['metadata']['name'])
        readback(ens, first['expected'])
        ephemeral_after = owner_snapshot(first['name'], ens, first['expected'])
        ephemeral_collision_owner = assert_owner_unchanged(ephemeral_before, ephemeral_after)
        first_volumes = delete_and_confirm_gone(first['name'], first['namespace'], first['count'])
        expect(first_volumes == 0, f'{first["name"]} unexpectedly had PersistentVolumes')
        kubectl(['delete', f'developerworkspace/{ephemeral_collision["metadata"]["name"]}', '--ignore-not-found', '--wait=true'])
        deleted_ephemeral_candidate = kubectl(['get', f'developerworkspace/{ephemeral_collision["metadata"]["name"]}'], check=False)
        expect(is_not_found(deleted_ephemeral_candidate) and not composed_objects(ephemeral_collision['metadata']['name']),
               'rejected ephemeral collision gained an owner or Object references after owner cleanup')
        record('ephemeral-cleanup', f'deleting the remaining XR removed its Namespace and all {first["count"]} composed Objects')
        record('workspace-id-collision-delete-isolated', 'deleting a rejected name before its persistent owner leaves that owner unchanged; deleting the ephemeral owner before its rejected name removes only the owner',
               persistent={'order': 'rejected-first', 'ownerBeforeAndAfter': persistent_delete_isolation},
               ephemeral={'order': 'owner-first', 'candidate': ephemeral_refused,
                          'ownerBeforeAndAfterAttempt': ephemeral_collision_owner})
        profile_final = profile_readback(profile_config, profile_initial)
    finally:
        kubectl(['delete', 'namespace', 'dw-ok175-squat', '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        kubectl(['delete', 'namespace', STEERING_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        for binding in (OPERATOR_BINDING, OBSERVER_BINDING):
            kubectl(['delete', 'clusterrolebinding', binding, '--ignore-not-found', '--wait=true'], check=False)
        for name, _ in (*DISTINCT, *RECEIPT_PROBES, PERSISTENT, SQUAT, NO_PROFILE):
            kubectl(['delete', f'developerworkspace/{name}', '--ignore-not-found', '--wait=true', '--timeout=600s'], timeout=630, check=False)
        kubectl(['delete', 'namespace', PROOF_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--ignore-not-found'], check=False)
        def require_not_found(args, description):
            missing = kubectl(['get', *args], check=False)
            expect(is_not_found(missing),
                   f'cleanup did not confirm {description} absent: rc={missing.returncode} {missing.stderr.strip()[:300]}')
        require_not_found(['namespace', 'dw-ok175-squat'], 'squat Namespace')
        require_not_found(['namespace', STEERING_NS], 'provider steering proof Namespace')
        require_not_found(['namespace', PROOF_NS], 'proof services Namespace and its generated credentials')
        require_not_found(['environmentconfig', 'developer-workspace-profile'], 'profile EnvironmentConfig')
        for binding in (OPERATOR_BINDING, OBSERVER_BINDING):
            require_not_found(['clusterrolebinding', binding], f'ClusterRoleBinding/{binding}')
        cleanup_xrs = (*(name for name, _ in (*DISTINCT, *RECEIPT_PROBES)), PERSISTENT[0], SQUAT[0], NO_PROFILE[0])
        for name in cleanup_xrs:
            require_not_found(['developerworkspace', name], f'DeveloperWorkspace/{name}')
            expect(not composed_objects(name), f'cleanup left composed Objects for {name}')
        record('harness-cleanup', 'proof services, generated credentials, profile, temporary authority bindings, XRs and composed Objects are absent')

    expected_results = [*RESULTS[:RESULTS.index('CAPACITY')], *(['file-project-reset-rejected', 'persistent-capacity-enforced'] if storage['mode'] == 'enforced' else ['persistent-capacity-not-enforced']), *RESULTS[RESULTS.index('CAPACITY') + 1:]]
    expect([r['name'] for r in results] == expected_results, f'results out of order: {[r["name"] for r in results]}')
    evidence = {'apiVersion': 'workspace.openkubes.io/v1', 'kind': 'ReconcilerLiveEvidence', 'runID': run_id, 'startedAt': started, 'finishedAt': now(),
                'target': tgt, 'implementation': impl, 'images': {'runtime': runtime_image.split('@', 1)[1], 'fixture': fixture_image.split('@', 1)[1]},
                'crossplane': {'chart': CROSSPLANE_CHART[2], 'functions': 'tests/functions.yaml', 'provider': 'install/provider-kubernetes.yaml',
                               'admissionPolicies': list(ADMISSION_GUARDS),
                               'admissionLimits': ['policy equality and status are checked immediately before each harness XR request; an operator could change policy after a gate check',
                                                   'the label proof covers the selected profile value and the named provider identity; it does not certify other admission plugins or authorizers']},
                'persistentCapacity': {'declaration': storage['declaration'], 'profileReadback': {'initial': profile_initial, 'final': profile_final},
                                       'mode': storage['mode'], 'storageClassName': storage['storageClassName'], 'hostUsers': storage['hostUsers'],
                                       'boundaries': {'declared': doc['spec']['storage']['size'], 'writeChunkBytes': WRITE_CHUNK,
                                                      'toleranceBytes': WRITE_CHUNK if storage['mode'] == 'enforced' else None},
                                       'scope': (['capacity enforcement for another storage class, declared size, runtime image or without hostUsers=false', 'every quota bypass or filesystem operation', 'provisioner restart or node reboot durability', 'production readiness']
                                                        if storage['mode'] == 'enforced' else
                                                        ['persistent runtime capacity enforcement', 'behavior of storage classes other than local-path', 'production readiness'])},
                'knownCommit': known, 'sourceTip': tip, 'results': results}
    EVIDENCE.mkdir(exist_ok=True); out = EVIDENCE / f'live-{tgt["context"].split("@")[-1]}-{run_id}.json'
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n'); passed = sum(r['status'] == 'pass' for r in results); observed = len(results) - passed
    print(f'{passed} checks passed, {observed} observation(s) recorded; evidence {out.relative_to(REPO)}')

def optional_object(kind, name, namespace=None):
    # Only a successful empty response means absent; transport/RBAC errors fail closed.
    args = ['get', kind, name]
    if namespace: args.extend(['-n', namespace])
    text = kubectl([*args, '--ignore-not-found', '-o', 'json']).stdout.strip()
    return json.loads(text) if text else None


def hands_on_namespace():
    profile = storage_inputs()['profile']
    return profile['spec']['namespacePrefix'] + HANDS_ON[1].removeprefix('ws-')


def hands_on_state_path():
    value = os.environ.get('OK180_STATE_FILE', '')
    expect(value and Path(value).is_absolute(), 'OK180_STATE_FILE must name an explicit absolute path')
    path = Path(value)
    expect(path.parent.is_dir() and os.access(path.parent, os.W_OK),
           f'OK180_STATE_FILE parent is not a writable directory: {path.parent}')
    return path


def require_fresh_hands_on_ledger(path):
    expect(not path.exists(), f'ownership ledger already exists: {path}; run live-down before another live-up')


def write_hands_on_state(path, state, *, initial=False):
    """Atomically persist a private ownership ledger; initial creation never overwrites."""
    temp = path.with_name(f'.{path.name}.{secrets.token_hex(8)}.tmp')
    fd = None
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            fd = None
            json.dump(state, stream, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        if initial:
            try: os.link(temp, path)
            except FileExistsError: raise ProofError(f'ownership ledger already exists: {path}')
            temp.unlink()
        else:
            os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    except ProofError:
        raise
    except OSError as error:
        raise ProofError(f'cannot persist ownership ledger {path}: {error}') from error
    finally:
        if fd is not None: os.close(fd)
        try: temp.unlink()
        except FileNotFoundError: pass


def load_hands_on_state(path, tgt):
    expect(path.is_file(), f'ownership ledger is missing: {path}')
    try: state = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error: raise ProofError(f'cannot read ownership ledger {path}: {error}') from error
    expect(state.get('version') == 1 and re.fullmatch(r'[0-9a-f]{32}', state.get('nonce', '')),
           f'ownership ledger is invalid: {path}')
    expect(state.get('target') == {'context': tgt['context'], 'kubeSystemUidSha256': tgt['kubeSystemUidSha256']},
           'ownership ledger target context or cluster UID differs from the selected disposable cluster')
    expect(isinstance(state.get('resources'), dict), 'ownership ledger resources are invalid')
    return state


def journal_intent(path, state, key, kind, name, namespace=None):
    state['resources'][key] = {'kind': kind, 'name': name, 'namespace': namespace,
                               'intent': True, 'uid': None, 'resourceVersion': None}
    write_hands_on_state(path, state)


def mark_owned(path, state, key, obj):
    entry = state['resources'][key]
    metadata = obj.get('metadata', {})
    marker = metadata.get('annotations', {}).get(HANDS_ON_RUN)
    expect(marker == state['nonce'], f"{entry['kind']}/{entry['name']} is missing the current ownership marker")
    uid, rv = metadata.get('uid'), metadata.get('resourceVersion')
    expect(uid and rv, f"{entry['kind']}/{entry['name']} lacks UID/resourceVersion ownership evidence")
    expect(not entry.get('uid') or entry['uid'] == uid,
           f"{entry['kind']}/{entry['name']} UID changed while recording ownership")
    entry.update(uid=uid, resourceVersion=rv, intent=False, markerPending=False)
    write_hands_on_state(path, state)
    return entry


def require_profile_data_unchanged(obj, entry):
    expect(sha_json(obj.get('data')) == entry.get('dataSha256'),
           'environmentconfig/developer-workspace-profile profile data changed; leaving it untouched')


def refuse_foreign_workspaces(name):
    others = [o for o in get_json(['get', 'developerworkspaces'])['items'] if o['metadata']['name'] != name]
    expect(not others, 'other DeveloperWorkspaces exist; refusing to remove the shared profile/fixture')


def refuse_preexisting_hands_on_objects(namespace):
    expect(not get_json(['get', 'developerworkspaces'])['items'], 'DeveloperWorkspaces already exist on the target')
    for kind, name in (('namespace', PROOF_NS), ('namespace', namespace),
                       ('environmentconfig', 'developer-workspace-profile')):
        expect(optional_object(kind, name) is None, f'{kind}/{name} already exists; refusing adoption')


def delete_preconditioned(kind, name, uid, resource_version, namespace=None, refresh=None):
    expect(uid and resource_version, f'{kind}/{name} lacks UID/resourceVersion delete preconditions')
    api_paths = {
        'developerworkspace': f'/apis/workspace.openkubes.io/v0alpha1/developerworkspaces/{name}',
        'environmentconfig': f'/apis/apiextensions.crossplane.io/v1beta1/environmentconfigs/{name}',
        'namespace': f'/api/v1/namespaces/{name}', 'pv': f'/api/v1/persistentvolumes/{name}',
    }
    expect(kind in api_paths, f'no UID-preconditioned DELETE API path for {kind}/{name}')
    # Controllers (Crossplane status, the namespace controller) write between our read and DELETE.
    # Retry only a resourceVersion precondition conflict, from a fresh ownership-checked read; the
    # UID precondition never changes, so a replaced object is never deleted.
    for attempt in range(5):
        options = {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                   'preconditions': {'uid': uid, 'resourceVersion': resource_version}}
        done = kubectl(['delete', f'--raw={api_paths[kind]}', '-f', '-'], input_text=json.dumps(options), check=False)
        if done.returncode == 0:
            return
        stale = 'ResourceVersion in precondition' in done.stderr and 'UID in precondition' not in done.stderr
        expect(stale and refresh is not None and attempt < 4,
               f'{kind}/{name} preconditioned DELETE failed: {done.stderr.strip()[:300]}')
        current = refresh()
        expect(current is not None and current['metadata'].get('uid') == uid,
               f'{kind}/{name} changed identity during a preconditioned DELETE retry; leaving it untouched')
        resource_version = current['metadata']['resourceVersion']


def stamp_owned(kind, name, obj, nonce):
    metadata = obj['metadata']; uid, rv = metadata.get('uid'), metadata.get('resourceVersion')
    expect(uid and rv, f'{kind}/{name} lacks UID/resourceVersion before ownership stamp')
    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': uid},
             {'op': 'test', 'path': '/metadata/resourceVersion', 'value': rv}]
    if metadata.get('annotations') is None:
        patch.append({'op': 'add', 'path': '/metadata/annotations', 'value': {HANDS_ON_RUN: nonce}})
    else:
        patch.append({'op': 'add', 'path': '/metadata/annotations/workspace.openkubes.io~1hands-on-run', 'value': nonce})
    done = kubectl(['patch', f'{kind}/{name}', '--type=json', '-p', json.dumps(patch), '-o', 'json'])
    try: stamped = json.loads(done.stdout)
    except json.JSONDecodeError as error: raise ProofError(f'{kind}/{name} ownership patch returned no JSON identity: {error}') from error
    expect(stamped.get('metadata', {}).get('uid') == uid and
           stamped.get('metadata', {}).get('annotations', {}).get(HANDS_ON_RUN) == nonce,
           f'{kind}/{name} changed while ownership marker was being applied')
    return stamped


def owned_live(entry, nonce):
    kind, name = entry['kind'], entry['name']
    obj = optional_object(kind, name, entry.get('namespace'))
    if obj is None: return None
    marker = obj.get('metadata', {}).get('annotations', {}).get(HANDS_ON_RUN)
    expect(marker == nonce, f'{kind}/{name} has a missing or foreign ownership marker; leaving it untouched')
    live_uid = obj['metadata'].get('uid')
    require_recorded_uid(entry, kind, name, live_uid)
    return obj


def require_recorded_uid(entry, kind, name, live_uid):
    expect(entry.get('uid') and live_uid, f'{kind}/{name} has no recorded UID; leaving it untouched')
    expect(live_uid == entry['uid'], f'{kind}/{name} UID changed; leaving the replacement untouched')


def require_ledger_entry(entries, key, kind, name):
    expect(key in entries, f'{kind}/{name} exists without a ledger entry; leaving it untouched')
    entry = entries[key]
    expect(entry.get('kind') == kind and entry.get('name') == name,
           f'ownership ledger entry for {kind}/{name} names a different resource')
    return entry


def record_workspace_pv(path, state, namespace, xr_uid):
    """Persist the XR-composed PVC identity, then record only its UID-bound PV."""
    pvc = optional_object('pvc', 'workspace', namespace)
    if not pvc: return
    pvc_uid = pvc.get('metadata', {}).get('uid')
    volume = pvc.get('spec', {}).get('volumeName')
    expect(pvc_uid, f'PVC/{namespace}/workspace lacks UID evidence')
    objects = composed_object_items(HANDS_ON[0])
    matches = []
    for item in objects:
        manifest = item.get('spec', {}).get('forProvider', {}).get('manifest', {})
        refs = item.get('metadata', {}).get('ownerReferences', [])
        if (manifest.get('kind') == 'PersistentVolumeClaim' and
                manifest.get('metadata', {}).get('name') == 'workspace' and
                manifest.get('metadata', {}).get('namespace') == namespace and
                item.get('metadata', {}).get('labels', {}).get('crossplane.io/composite') == HANDS_ON[0] and
                any(ref.get('uid') == xr_uid and ref.get('controller') for ref in refs)):
            matches.append(item)
    expect(len(matches) == 1,
           f'PVC/{namespace}/workspace lacks one XR-owned composed provider Object')
    observed_manifest = (matches[0].get('status', {}).get('atProvider', {}).get('manifest') or
                         matches[0].get('status', {}).get('atProvider', {}).get('resource') or {})
    observed_metadata = observed_manifest.get('metadata', {})
    expect(observed_manifest.get('kind') == 'PersistentVolumeClaim' and
           observed_metadata.get('name') == 'workspace' and observed_metadata.get('namespace') == namespace and
           observed_metadata.get('uid') == pvc_uid,
           f"composed Object/{matches[0]['metadata']['name']} observed manifest UID does not match PVC/{namespace}/workspace")
    pvc_evidence = {'uid': pvc_uid, 'namespace': namespace, 'name': 'workspace',
                    'xrUid': xr_uid, 'objectName': matches[0]['metadata']['name'],
                    'objectUid': matches[0]['metadata']['uid']}
    expect(state.get('pvcOwnership') in (None, pvc_evidence),
           f'PVC/{namespace}/workspace or its composed Object UID changed during this run')
    state['pvcOwnership'] = pvc_evidence
    write_hands_on_state(path, state)
    if not volume: return
    pv = optional_object('pv', volume)
    expect(pv is not None, f'PV/{volume} for PVC/{namespace}/workspace is missing')
    claim = pv.get('spec', {}).get('claimRef', {})
    expect(claim.get('uid') == pvc_uid and claim.get('namespace') == namespace and claim.get('name') == 'workspace',
           f'PV/{volume} claimRef does not match the XR-composed PVC UID')
    key = f'pv:{volume}'
    if key not in state['resources']:
        journal_intent(path, state, key, 'pv', volume)
    entry = state['resources'][key]
    require_pv_marker_for_adoption(entry, pv, state['nonce'])
    if entry.get('uid'):
        expect(entry['uid'] == pv.get('metadata', {}).get('uid'), f'PV/{volume} UID changed; leaving the replacement untouched')
        marker = pv.get('metadata', {}).get('annotations', {}).get(HANDS_ON_RUN)
        expect(marker == state['nonce'] or (marker is None and entry.get('markerPending')),
               f'PV/{volume} has a missing or foreign ownership marker; leaving it untouched')
        if marker == state['nonce']:
            return
    else:
        entry.update(uid=pv['metadata'].get('uid'), resourceVersion=pv['metadata'].get('resourceVersion'),
                     intent=False, markerPending=True)
        expect(entry['uid'] and entry['resourceVersion'], f'PV/{volume} lacks UID/resourceVersion evidence')
        write_hands_on_state(path, state)
    # The provisioner PV is annotated only after both sides of the binding and XR ownership are proven.
    mark_owned(path, state, key, stamp_owned('pv', volume, pv, state['nonce']))


def composed_child_matches(name, kind, namespace, child, owner_uid):
    """Prove provider Object ownership and observed child UID before stamping a child."""
    metadata = child.get('metadata', {})
    found = []
    for item in composed_object_items(name):
        manifest = item.get('spec', {}).get('forProvider', {}).get('manifest', {})
        refs = item.get('metadata', {}).get('ownerReferences', [])
        if (manifest.get('kind') == kind and manifest.get('metadata', {}).get('name') == metadata.get('name') and
                (not namespace or manifest.get('metadata', {}).get('namespace') == namespace) and
                item.get('metadata', {}).get('labels', {}).get('crossplane.io/composite') == name and
                any(ref.get('uid') == owner_uid and ref.get('controller') for ref in refs)):
            observed = (item.get('status', {}).get('atProvider', {}).get('manifest') or
                        item.get('status', {}).get('atProvider', {}).get('resource') or {})
            if observed.get('kind') == kind and observed.get('metadata', {}).get('uid') == metadata.get('uid'):
                found.append(item)
    expect(len(found) == 1,
           f'{kind}/{metadata.get("name")} does not have one XR-owned provider Object with matching observed UID')
    return found[0]


def up(_args):
    path = hands_on_state_path()
    require_fresh_hands_on_ledger(path)
    storage = storage_inputs(); tgt = target(); composition = installed_matches_local()
    runtime_image, fixture_image = image('OK175_RUNTIME_IMAGE'), image('OK175_FIXTURE_IMAGE')
    namespace = hands_on_namespace()
    refuse_preexisting_hands_on_objects(namespace)
    pulls, registry, username, password = registry_inputs(runtime_image)
    tls = spike.tls_material(); read_token = secrets.token_urlsafe(32)
    state = {'version': 1, 'nonce': secrets.token_hex(16), 'workspaceNamespaceName': namespace,
             'target': {'context': tgt['context'], 'kubeSystemUidSha256': tgt['kubeSystemUidSha256']},
             'resources': {}}
    write_hands_on_state(path, state, initial=True)
    # Empty write token disables writer authentication; no control Pod or write Secret is created.
    journal_intent(path, state, 'fixtureNamespace', 'namespace', PROOF_NS)
    known, _ = fixture_setup(fixture_image, tls, read_token, '', pulls, registry, username, password,
                             hands_on=True, hands_on_nonce=state['nonce'],
                             on_namespace_created=lambda obj: mark_owned(path, state, 'fixtureNamespace', obj))
    profile = live_profile(runtime_image, storage)
    config = render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')
    config['metadata']['labels'] = {HANDS_ON_LABEL: 'true'}
    config['metadata'].setdefault('annotations', {})[HANDS_ON_RUN] = state['nonce']
    journal_intent(path, state, 'profile', 'environmentconfig', 'developer-workspace-profile')
    state['resources']['profile']['dataSha256'] = sha_json(config.get('data'))
    write_hands_on_state(path, state)
    created = kubectl(['create', '-f', '-', '-o', 'json'], input_text=yaml.safe_dump(config))
    try: created_config = json.loads(created.stdout)
    except json.JSONDecodeError as error: raise ProofError('EnvironmentConfig/developer-workspace-profile create returned no UID JSON') from error
    mark_owned(path, state, 'profile', created_config)
    # Reserve the Namespace ourselves: a GET-before-reconcile is not proof the provider created it.
    doc = workspace_inputs(*HANDS_ON, known, 'persistent')
    namespace_doc = next(obj for obj in render_profile.reference_render(doc, profile)['spec']['resources']
                         if obj['kind'] == 'Namespace')
    create_owned_namespace(path, state, namespace_doc)
    try:
        _, namespace, _ = bring_up(*HANDS_ON, 'persistent', known=known, profile=profile, read_token=read_token,
                                  tls=tls, pulls=pulls, registry=registry, username=username, password=password,
                                  composition=composition, hands_on=True,
                                  ownership={'path': path, 'state': state})
        pod = workspace_pod(namespace)
    except (ProofError, subprocess.TimeoutExpired):
        print('Hands-on setup incomplete; use live-down to clean up before retrying.', file=sys.stderr)
        raise
    print(f'Workspace: {HANDS_ON[0]}\nNamespace: {namespace}\nRuntime Pod: {pod}')
    command = ['kubectl', '--context', tgt['context'], 'exec', '-n', namespace, f'pod/{pod}', '-c', 'runtime', '--',
               'sh', '-c', "cd /workspace && opencode run --format json '<task>' && sh verify.sh"]
    print(shlex.join(command))


def create_owned_namespace(path, state, doc):
    name = doc['metadata']['name']
    doc = copy.deepcopy(doc)
    doc['metadata'].setdefault('annotations', {})[HANDS_ON_RUN] = state['nonce']
    journal_intent(path, state, 'workspaceNamespace', 'namespace', name)
    created = kubectl(['create', '-f', '-', '-o', 'json'], input_text=yaml.safe_dump(doc))
    try: obj = json.loads(created.stdout)
    except json.JSONDecodeError as error:
        raise ProofError(f'Namespace/{name} create returned no UID JSON; leaving it untouched') from error
    mark_owned(path, state, 'workspaceNamespace', obj)


def require_pv_marker_for_adoption(entry, pv, nonce):
    marker = pv.get('metadata', {}).get('annotations', {}).get(HANDS_ON_RUN)
    if not entry.get('uid'):
        expect(marker is None,
               f"PV/{pv['metadata']['name']} already has an ownership marker; refusing adoption")


def assert_no_unrecorded_pvs(state, namespace):
    # Namespace/nonce selects objects to REFUSE, never objects to adopt or delete.
    for pv in get_json(['get', 'pv'])['items']:
        metadata = pv['metadata']; name = metadata['name']
        claim = pv.get('spec', {}).get('claimRef', {})
        if (claim.get('namespace') != namespace and
                metadata.get('annotations', {}).get(HANDS_ON_RUN) != state['nonce']):
            continue
        entry = require_ledger_entry(state['resources'], f'pv:{name}', 'pv', name)
        require_recorded_uid(entry, 'pv', name, metadata.get('uid'))
        owned_live(entry, state['nonce'])
        pvc = state.get('pvcOwnership')
        if pvc:
            expect(claim.get('uid') == pvc['uid'] and claim.get('namespace') == pvc['namespace'] and
                   claim.get('name') == pvc['name'], f'PV/{name} claimRef differs from the recorded PVC UID')


def down(_args):
    path = hands_on_state_path()
    tgt = target(); installed_matches_local()
    state = load_hands_on_state(path, tgt); nonce = state['nonce']; entries = state['resources']
    name, workspace_id = HANDS_ON; namespace = state.get('workspaceNamespaceName')
    expect(isinstance(namespace, str) and namespace,
           'ownership ledger lacks the workspace Namespace name; leaving resources untouched')
    expected = {'xr': ('developerworkspace', name, None),
                'workspaceNamespace': ('namespace', namespace, None),
                'fixtureNamespace': ('namespace', PROOF_NS, None),
                'profile': ('environmentconfig', 'developer-workspace-profile', None)}
    for key, (kind, resource_name, resource_namespace) in expected.items():
        obj = optional_object(kind, resource_name, resource_namespace)
        if obj is not None:
            entry = require_ledger_entry(entries, key, kind, resource_name)
            if key == 'profile':
                require_profile_data_unchanged(obj, entry)
            owned_live(entry, nonce)
    xr = optional_object('developerworkspace', name)
    fixture = optional_object('namespace', PROOF_NS)
    config = optional_object('environmentconfig', 'developer-workspace-profile')
    ns = optional_object('namespace', namespace)
    if xr: expect(xr['spec'].get('workspaceID') == workspace_id, 'DeveloperWorkspace/ws-hands-on-xr workspaceID changed; leaving it untouched')
    refuse_foreign_workspaces(name)
    # Recover an interrupted PV journal only through the bound PVC and XR-composed provider Object chain.
    if xr:
        def pv_binding_recorded():
            record_workspace_pv(path, state, namespace, entries['xr']['uid'])
            return bool(state.get('pvcOwnership', {}).get('uid') and any(e['kind'] == 'pv' and e.get('uid') for e in entries.values()))
        if not any(e.get('kind') == 'pv' and e.get('uid') for e in entries.values()):
            wait_until(f'PVC/{namespace}/workspace to bind to its UID-proven PV', pv_binding_recorded, timeout=300, interval=3)
        else:
            record_workspace_pv(path, state, namespace, entries['xr']['uid'])
    for key, entry in list(entries.items()):
        if entry['kind'] == 'pv':
            live = owned_live(entry, nonce)
    assert_no_unrecorded_pvs(state, namespace)
    # All known ownership has been checked before the first destructive request.
    if xr:
        current = owned_live(entries['xr'], nonce)
        delete_preconditioned('developerworkspace', name, entries['xr'].get('uid'), current['metadata']['resourceVersion'],
                              refresh=lambda: owned_live(entries['xr'], nonce))
    wait_until(f'DeveloperWorkspace/{name} removal', lambda: optional_object('developerworkspace', name) is None, timeout=600)
    if not xr and ns:
        current = owned_live(entries['workspaceNamespace'], nonce)
        if current:
            delete_preconditioned('namespace', namespace, entries['workspaceNamespace']['uid'], current['metadata']['resourceVersion'],
                                  refresh=lambda: owned_live(entries['workspaceNamespace'], nonce))
    wait_until(f'namespace {namespace} removal', lambda: optional_object('namespace', namespace) is None, timeout=600)
    wait_until(f'composed Objects of {name} removal', lambda: not composed_objects(name), timeout=300)
    if ns and optional_object('namespace', namespace):
        expect(False, f'Namespace/{namespace} was replaced while workspace deletion was in progress')
    for key, entry in list(entries.items()):
        if entry['kind'] != 'pv': continue
        live = owned_live(entry, nonce)
        if live:
            expect(optional_object('pvc', 'workspace', namespace) is None,
                   f'PVC/{namespace}/workspace remains; leaving PV/{entry["name"]} untouched')
            delete_preconditioned('pv', entry['name'], entry.get('uid'), live['metadata']['resourceVersion'],
                                  refresh=lambda e=entry: owned_live(e, nonce))
        wait_until(f'PersistentVolume {entry["name"]} removal', lambda e=entry: optional_object('pv', e['name']) is None, timeout=300)
    assert_no_unrecorded_pvs(state, namespace)
    if config:
        current = owned_live(entries['profile'], nonce)
        delete_preconditioned('environmentconfig', 'developer-workspace-profile', entries['profile'].get('uid'), current['metadata']['resourceVersion'],
                              refresh=lambda: owned_live(entries['profile'], nonce))
    wait_until('EnvironmentConfig/developer-workspace-profile removal',
               lambda: optional_object('environmentconfig', 'developer-workspace-profile') is None, timeout=300)
    if fixture:
        current = owned_live(entries['fixtureNamespace'], nonce)
        delete_preconditioned('namespace', PROOF_NS, entries['fixtureNamespace'].get('uid'), current['metadata']['resourceVersion'],
                              refresh=lambda: owned_live(entries['fixtureNamespace'], nonce))
    wait_until(f'fixture Namespace {PROOF_NS} removal', lambda: optional_object('namespace', PROOF_NS) is None, timeout=600)
    assert_no_unrecorded_pvs(state, namespace)
    try: path.unlink()
    except FileNotFoundError: raise ProofError(f'ownership ledger disappeared before cleanup completed: {path}')
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(directory_fd)
    finally: os.close(directory_fd)
    print('Hands-on workspace, Namespace, PV, profile and fixture removed (or already absent).')


RESULTS = ('admission-policy-gate', 'admission-rules', 'canonical-name-rule', 'no-profile-fails-closed',
           'admission-receipt-gate', 'dedicated-namespace-enforced', 'reconcile-readback', 'workspace-id-immutable',
           'authority-boundary-rbac', 'namespaced-provider-steering-denied',
           'namespace-host-users-label-authority', 'provider-host-users-label-reconcile',
           'authority-who-can', 'authority-indirect-who-can', 'workspace-id-collision-refused',
           'workspace-id-duplicate-create-refused',
           'drift-restored', 'pod-user-namespace-admission', 'ephemeralcontainers-admission', 'source-checkout',
           'persistent-marker-survives-replacement', 'runtime-user-boundary', 'kubernetes-authority-denied',
           'kubernetes-api-unreachable', 'runtime-push-denied', 'workspace-credential-push-denied',
           'write-credential-absent', 'cpu-bound-enforced', 'memory-bound-enforced', 'storage-quota-enforced',
           'CAPACITY', 'persistent-cleanup', 'ephemeral-reconcile', 'distinct-workspace-isolation',
           'ephemeral-storage-enforced', 'ephemeral-cleanup', 'workspace-id-collision-delete-isolated',
           'harness-cleanup')

def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('install').set_defaults(fn=install); sub.add_parser('uninstall').set_defaults(fn=uninstall)
    r = sub.add_parser('run'); r.add_argument('--require-clean', action='store_true'); r.set_defaults(fn=run)
    sub.add_parser('up', help='Keep one persistent OpenCode workspace (no evidence)').set_defaults(fn=up)
    sub.add_parser('down', help='Remove only hands-on resources (no evidence)').set_defaults(fn=down)
    args = parser.parse_args()
    try: args.fn(args)
    except ProofError as error: print(f'FAIL {error}', file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
