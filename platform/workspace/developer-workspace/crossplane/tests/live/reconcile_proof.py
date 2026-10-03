#!/usr/bin/env python3
"""Live proof of the DeveloperWorkspace reconciler path (OK-175).

The OK-174 harness applied render() output itself. Here a DeveloperWorkspace XR is applied and
Crossplane, function-go-templating and provider-kubernetes reconcile it. The proof requires:
  - the reconciled Namespace objects equal the capability reference rendering for the same inputs;
  - the checkout is the declared revision and the XR is Ready only once the workspace runs;
  - no ambient Kubernetes authority (no token, discovery-only RBAC, API unreachable);
  - no push or merge authority: the runtime has no source credential, the workspace credential
    is refused for push by the source, and a write-credential control push succeeds;
  - deleting the XR removes the Namespace and every composed object.
Every denial has a control that shows the same check passes when the authority exists.

Actions: install | run | up | down | uninstall. Mutation requires an explicit KUBECONFIG whose current
context is TARGET_CONTEXT and one of the disposable targets below.
"""
from __future__ import annotations
import argparse, base64, copy, errno, hashlib, importlib.util, json, os, re, secrets, subprocess, sys, time
from datetime import datetime, timezone
from functools import partial
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
HOST_USERS_LABEL = 'workspace.openkubes.io/host-users'
PROOF_NS = 'ok174-proof-services'  # the reviewed live profile's source destination
PULL_SECRET = 'workspace-registry-pull'
PERSISTENT, EPHEMERAL = ('ok175-live-proof', 'ws-ok175-proof'), ('ok175-ephemeral-proof', 'ws-ok175-ephemeral')
HANDS_ON = ('ok-hands-on', 'ws-hands-on')
HANDS_ON_LABEL = 'workspace.openkubes.io/hands-on'
HANDS_ON_VOLUMES = 'workspace.openkubes.io/hands-on-volumes'
SQUAT = ('ok175-squat-proof', 'ws-ok175-squat')
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
def sha(data): return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def storage_inputs(environ=None):
    env = os.environ if environ is None else environ
    storage_class = env.get('OK176_STORAGE_CLASS', '')
    host_users_raw = env.get('OK176_HOST_USERS', '')
    mode = env.get('OK176_CAPACITY_MODE', '')
    labels = storage_class.split('.')
    valid_class = 0 < len(storage_class) <= 253 and all(re.fullmatch(r'[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?', label) for label in labels)
    expect(valid_class, 'OK176_STORAGE_CLASS must be a valid non-empty StorageClass name')
    expect(host_users_raw in ('true', 'false'), 'OK176_HOST_USERS must be literal true or false')
    expect(mode in ('enforced', 'observed-negative'), 'OK176_CAPACITY_MODE must be enforced or observed-negative')
    host_users = host_users_raw == 'true'
    if mode == 'enforced': expect(not host_users, 'OK176_CAPACITY_MODE=enforced requires OK176_HOST_USERS=false')
    else:
        expect(host_users, 'OK176_CAPACITY_MODE=observed-negative requires OK176_HOST_USERS=true')
        expect(storage_class == 'local-path', 'OK176_CAPACITY_MODE=observed-negative requires OK176_STORAGE_CLASS=local-path')
    return {'storageClassName': storage_class, 'hostUsers': host_users, 'mode': mode}

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

def kubectl(args, *, input_text=None, timeout=120, check=True):
    done = subprocess.run(['kubectl', *args], input=input_text, text=True, capture_output=True, timeout=timeout)
    if check and done.returncode: raise ProofError(f"kubectl {' '.join(args[:3])} failed ({done.returncode}): {done.stderr.strip()[:300]}")
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

def installed_matches_local():
    """The objects that ran must be the files the evidence hashes, not an earlier install."""
    local = lambda path: yaml.safe_load((CAPABILITY / path).read_text())
    composition = get_json(['get', 'composition', local('composition.yaml')['metadata']['name']])
    expect(composition['spec']['pipeline'] == local('composition.yaml')['spec']['pipeline'], 'installed Composition differs from composition.yaml')
    xrd = get_json(['get', 'compositeresourcedefinition', local('xrd.yaml')['metadata']['name']])
    expect(xrd['spec']['versions'][0]['schema'] == local('xrd.yaml')['spec']['versions'][0]['schema'], 'installed XRD schema differs from xrd.yaml')
    role = next(d for d in yaml.safe_load_all((CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml').read_text()) if d['kind'] == 'ClusterRole')
    expect(get_json(['get', 'clusterrole', role['metadata']['name']])['rules'] == role['rules'], 'installed ClusterRole differs from rbac/')
    for path in ('install/namespace-guard.yaml', 'install/pod-user-namespace-guard.yaml'):
        policy, binding = yaml.safe_load_all((CAPABILITY / path).read_text())
        live_policy = get_json(['get', 'validatingadmissionpolicy', policy['metadata']['name']])['spec']
        expect(canonical_admission_spec(live_policy) == canonical_admission_spec(policy['spec']), f'installed admission policy differs from {path}')
        live_binding = get_json(['get', 'validatingadmissionpolicybinding', binding['metadata']['name']])['spec']
        expect(canonical_admission_spec(live_binding, binding=True) == canonical_admission_spec(binding['spec'], binding=True), f'installed admission policy binding differs from {path}')
    return composition

def revision_matches(xr_name, composition):
    ref = get_json(['get', f'developerworkspace/{xr_name}'])['spec']['crossplane']['compositionRevisionRef']['name']
    revision = get_json(['get', 'compositionrevision', ref])
    expect(revision['spec']['pipeline'] == composition['spec']['pipeline'], f'{xr_name} runs CompositionRevision {ref}, which differs from composition.yaml')
    return ref

def image(name):
    value = os.environ.get(name, ''); expect(bool(re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', value)), f'{name} must be a digest reference'); return value

def install(_args):
    target()
    repo, chart, version = CROSSPLANE_CHART
    subprocess.run(['helm', 'upgrade', '--install', 'crossplane', chart, '--repo', repo, '--version', version, '-n', 'crossplane-system', '--create-namespace', '--wait', '--timeout', '10m'], check=True)
    apply_file(CAPABILITY / 'tests/functions.yaml'); apply_file(CAPABILITY / 'install/provider-kubernetes.yaml')
    kubectl(['wait', '--for=condition=Healthy', 'function.pkg.crossplane.io/function-go-templating', 'function.pkg.crossplane.io/function-auto-ready', 'provider.pkg.crossplane.io/provider-kubernetes', '--timeout=600s'], timeout=630)
    apply_file(CAPABILITY / 'rbac/provider-kubernetes-clusterrole.yaml'); apply_file(CAPABILITY / 'install/namespace-guard.yaml')
    apply_file(CAPABILITY / 'install/pod-user-namespace-guard.yaml'); apply_file(CAPABILITY / 'install/providerconfig.yaml')
    apply_file(CAPABILITY / 'xrd.yaml')
    kubectl(['wait', '--for=condition=Established', 'compositeresourcedefinition/developerworkspaces.workspace.openkubes.io', '--timeout=300s'], timeout=330)
    apply_file(CAPABILITY / 'composition.yaml')
    print('installed Crossplane', version, 'with the DeveloperWorkspace capability')

def uninstall(_args):
    target()
    listed = kubectl(['get', 'developerworkspaces', '-o', 'json'], check=False)
    expect(listed.returncode != 0 and 'the server doesn' in listed.stderr or listed.returncode == 0 and not json.loads(listed.stdout)['items'], 'DeveloperWorkspaces still exist; delete them first')
    for path in ('composition.yaml', 'xrd.yaml', 'install/providerconfig.yaml', 'install/pod-user-namespace-guard.yaml', 'install/namespace-guard.yaml', 'rbac/provider-kubernetes-clusterrole.yaml', 'install/provider-kubernetes.yaml', 'tests/functions.yaml'):
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

def wait_ready(name):
    kubectl(['wait', '--for=condition=Ready', f'developerworkspace/{name}', '--timeout=600s'], timeout=630)

def composed_objects(name): return [o['metadata']['name'] for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items'] if o['metadata'].get('labels', {}).get('crossplane.io/composite') == name]

def delete_and_confirm_gone(name, namespace, expected_count):
    # Counting first keeps the "none left" check from passing on a label that never matched.
    expect(len(composed_objects(name)) == expected_count, f'{name} has {len(composed_objects(name))} composed Objects, expected {expected_count}')
    volumes = [c['spec'].get('volumeName') for c in get_json(['get', 'pvc', '-n', namespace])['items']]
    expect(all(volumes), f'unbound PVC in {namespace}')
    kubectl(['delete', f'developerworkspace/{name}', '--wait=true', '--timeout=600s'], timeout=630)
    wait_until(f'namespace {namespace} removal', lambda: kubectl(['get', 'namespace', namespace], check=False).returncode != 0, timeout=600)
    # The XR is gone before its composed Objects finish deleting; wait for them, bounded.
    wait_until(f'composed Objects of {name} to be deleted', lambda: not composed_objects(name), timeout=300)
    for volume in volumes: wait_until(f'PersistentVolume {volume} removal', lambda: kubectl(['get', 'pv', volume], check=False).returncode != 0, timeout=300)
    return len(volumes)

def registry_inputs(runtime_image):
    username = os.environ.get('OK175_REGISTRY_USERNAME', ''); pulls = bool(username)
    password = os.read(int(os.environ['OK175_REGISTRY_PASSWORD_FD']), 4096).decode().strip() if pulls else ''
    expect(not pulls or password, 'registry password descriptor is empty')
    registry = runtime_image.split('/', 1)[0]
    return pulls, registry, username, password


def live_profile(runtime_image, storage):
    profile = render_profile.load_profile(LIVE / 'profile/namespace-profile-live.yaml')
    profile['spec']['runtimeProfiles']['opencode']['image'] = runtime_image
    profile['spec']['storageClassName'] = storage['storageClassName']; profile['spec']['hostUsers'] = storage['hostUsers']
    return profile


def fixture_setup(fixture_image, tls, read_token, write_token, pulls, registry, username, password, hands_on=False):
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': PROOF_NS}}
    if hands_on:
        namespace['metadata']['labels'] = {HANDS_ON_LABEL: 'true'}
        kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(namespace))
    else: kubectl(['create', 'namespace', PROOF_NS])
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


def bring_up(name, workspace_id, mode, *, known, profile, read_token, tls, pulls, registry, username, password, composition, hands_on=False):
    doc = workspace_inputs(name, workspace_id, known, mode); namespace = profile['spec']['namespacePrefix'] + workspace_id.removeprefix('ws-')
    # Dedicated: the reconciler would adopt an existing Namespace, so require that none exists.
    absent = optional_object('namespace', namespace) is None if hands_on else kubectl(['get', 'namespace', namespace], check=False).returncode != 0
    expect(absent, f'namespace {namespace} already exists')
    if hands_on:
        doc['metadata'].setdefault('labels', {})[HANDS_ON_LABEL] = 'true'
        kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(doc))
    else: apply([doc])
    wait_until(f'namespace {namespace}', lambda: kubectl(['get', 'namespace', namespace], check=False).returncode == 0, timeout=300)
    # Per-run values the contract only references: the source credential, CA and pull Secret.
    support = [{'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'workspace-git-auth', 'namespace': namespace}, 'type': 'Opaque', 'stringData': {'token': read_token}},
               {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'git-fixture-ca', 'namespace': namespace}, 'data': {'ca.crt': tls['ca']}}]
    if pulls: support.append(pull_secret(namespace, registry, username, password))
    apply(support)
    wait_ready(name)
    revision = revision_matches(name, composition)
    xr, created = get_json(['get', f'developerworkspace/{name}']), get_json(['get', 'namespace', namespace])
    expect(created['metadata']['creationTimestamp'] >= xr['metadata']['creationTimestamp'], f'namespace {namespace} predates its DeveloperWorkspace')
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
    known, tip = fixture_setup(fixture_image, tls, read_token, write_token, pulls, registry, username, password)
    composition = installed_matches_local()

    # Admission: the XRD's CEL rules reject an inconsistent lifecycle; the same document made consistent passes.
    bad = workspace_inputs('ok175-cel-probe', 'ws-ok175-cel', known, 'persistent'); bad['spec']['storage']['mode'] = 'ephemeral'
    rejected = kubectl(['apply', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(bad), check=False)
    expect(rejected.returncode != 0 and 'persistent lifecycle requires persistent storage' in rejected.stderr, 'XRD admitted a persistent lifecycle with ephemeral storage')
    kubectl(['apply', '--dry-run=server', '-f', '-'], input_text=yaml.safe_dump(workspace_inputs('ok175-cel-probe', 'ws-ok175-cel', known, 'persistent')))
    record('admission-rules', 'the API server rejects a persistent lifecycle with ephemeral storage and admits the consistent document')
    # Without the profile EnvironmentConfig a workspace must compose nothing and must not be Ready.
    probe = workspace_inputs('ok175-no-profile', 'ws-ok175-no-profile', known, 'persistent'); apply([probe])
    def no_profile_settled():
        conditions = {c['type']: c for c in get_json(['get', 'developerworkspace/ok175-no-profile']).get('status', {}).get('conditions', [])}
        return conditions.get('Synced', {}).get('status') == 'False' and 'developer-workspace-profile not found' in conditions['Synced'].get('message', '')
    wait_until('the no-profile workspace to report the missing profile', no_profile_settled, timeout=180, interval=3)
    conditions = {c['type']: c['status'] for c in get_json(['get', 'developerworkspace/ok175-no-profile'])['status']['conditions']}
    expect(conditions.get('Ready') != 'True' and not composed_objects('ok175-no-profile') and kubectl(['get', 'namespace', 'dw-ok175-no-profile'], check=False).returncode != 0, f'no-profile workspace composed or became Ready: {conditions}')
    kubectl(['delete', 'developerworkspace/ok175-no-profile', '--wait=true', '--timeout=300s'], timeout=330)
    record('no-profile-fails-closed', 'without the profile EnvironmentConfig the workspace reports it missing, composes nothing and is not Ready', ready=conditions.get('Ready'))

    profile = live_profile(runtime_image, storage)
    apply([render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')])

    bring_up_workspace = partial(bring_up, known=known, profile=profile, read_token=read_token, tls=tls, pulls=pulls,
                                 registry=registry, username=username, password=password, composition=composition)

    try:
        # Dedicated Namespace: a workspace whose Namespace already exists must not adopt it.
        squat = 'dw-ok175-squat'
        apply([{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': squat}},
               {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'owner-data', 'namespace': squat}, 'data': {'k': 'v'}}])
        apply([workspace_inputs(SQUAT[0], SQUAT[1], known, 'persistent')])
        def refused():
            for o in get_json(['get', 'objects.kubernetes.crossplane.io'])['items']:
                if o['metadata'].get('labels', {}).get('crossplane.io/composite') == SQUAT[0] and o['spec']['forProvider']['manifest']['kind'] == 'Namespace':
                    return any('only Namespaces it created' in c.get('message', '') for c in o.get('status', {}).get('conditions', []))
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

        # One workspace at a time: a single small worker cannot schedule two.
        edoc, ens, _ = bring_up_workspace(*EPHEMERAL, 'ephemeral')
        ecount = readback(ens, expected_objects(edoc, profile, pulls))
        volumes = {v['name']: v for v in get_json(['get', 'deployment/workspace', '-n', ens])['spec']['template']['spec']['volumes']}
        expect('emptyDir' in volumes['workspace'] and not get_json(['get', 'pvc', '-n', ens])['items'], 'ephemeral workspace is not emptyDir-backed')
        record('ephemeral-reconcile', f'{ecount} reconciled objects equal capability reference rendering; workspace volume is emptyDir, no PVC', namespace=ens)
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
        wait_ready(EPHEMERAL[0]); replacement = workspace_pod(ens); expect(replacement != epod, 'no replacement pod')
        record('ephemeral-storage-enforced', f'writing 2x the {limit} emptyDir limit evicted the pod (kubelet names the workspace volume); half the limit was fine; the reconciler brought a replacement up', limit=limit)

        delete_and_confirm_gone(EPHEMERAL[0], ens, ecount)
        record('ephemeral-cleanup', f'deleting the XR removed its Namespace and all {ecount} composed Objects')
    finally:
        kubectl(['delete', 'namespace', 'dw-ok175-squat', '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        for name, _ in (EPHEMERAL, PERSISTENT, SQUAT, ('ok175-no-profile', '')):
            kubectl(['delete', f'developerworkspace/{name}', '--ignore-not-found', '--wait=true', '--timeout=600s'], timeout=630, check=False)
        kubectl(['delete', 'namespace', PROOF_NS, '--ignore-not-found', '--wait=true'], timeout=600, check=False)
        kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--ignore-not-found'], check=False)

    expected_results = [*RESULTS[:RESULTS.index('CAPACITY')], *(['file-project-reset-rejected', 'persistent-capacity-enforced'] if storage['mode'] == 'enforced' else ['persistent-capacity-not-enforced']), *RESULTS[RESULTS.index('CAPACITY') + 1:]]
    expect([r['name'] for r in results] == expected_results, f'results out of order: {[r["name"] for r in results]}')
    evidence = {'apiVersion': 'workspace.openkubes.io/v1', 'kind': 'ReconcilerLiveEvidence', 'runID': run_id, 'startedAt': started, 'finishedAt': now(),
                'target': tgt, 'implementation': impl, 'images': {'runtime': runtime_image.split('@', 1)[1], 'fixture': fixture_image.split('@', 1)[1]},
                'crossplane': {'chart': CROSSPLANE_CHART[2], 'functions': 'tests/functions.yaml', 'provider': 'install/provider-kubernetes.yaml',
                               'admissionPolicies': ['install/namespace-guard.yaml', 'install/pod-user-namespace-guard.yaml']},
                'persistentCapacity': {'mode': storage['mode'], 'storageClassName': storage['storageClassName'], 'hostUsers': storage['hostUsers'],
                                       'boundaries': {'declared': doc['spec']['storage']['size'], 'writeChunkBytes': WRITE_CHUNK,
                                                      'toleranceBytes': WRITE_CHUNK if storage['mode'] == 'enforced' else None},
                                       'doesNotProve': (['capacity enforcement for another storage class, declared size, runtime image or without hostUsers=false', 'every quota bypass or filesystem operation', 'provisioner restart or node reboot durability', 'production readiness']
                                                        if storage['mode'] == 'enforced' else
                                                        ['persistent runtime capacity enforcement', 'behavior of storage classes other than local-path', 'production readiness'])},
                'knownCommit': known, 'sourceTip': tip, 'results': results}
    EVIDENCE.mkdir(exist_ok=True); out = EVIDENCE / f'live-{tgt["context"].split("@")[-1]}-{run_id}.json'
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n'); passed = sum(r['status'] == 'pass' for r in results); observed = len(results) - passed
    print(f'{passed} checks passed, {observed} observation(s) recorded; evidence {out.relative_to(REPO)}')

def optional_object(kind, name):
    # Only a successful empty response means absent; transport/RBAC errors fail closed.
    text = kubectl(['get', kind, name, '--ignore-not-found', '-o', 'json']).stdout.strip()
    return json.loads(text) if text else None


def hands_on_namespace():
    profile = render_profile.load_profile(LIVE / 'profile/namespace-profile-live.yaml')
    return profile['spec']['namespacePrefix'] + HANDS_ON[1].removeprefix('ws-')


def require_hands_on(obj):
    if obj:
        expect(obj['metadata'].get('labels', {}).get(HANDS_ON_LABEL) == 'true',
               f"refusing unowned {obj['kind']}/{obj['metadata']['name']}")


def up(_args):
    storage = storage_inputs(); tgt = target(); composition = installed_matches_local()
    runtime_image, fixture_image = image('OK175_RUNTIME_IMAGE'), image('OK175_FIXTURE_IMAGE')
    namespace = hands_on_namespace()
    expect(not get_json(['get', 'developerworkspaces'])['items'], 'DeveloperWorkspaces already exist on the target')
    for kind, name in (('namespace', PROOF_NS), ('namespace', namespace),
                       ('environmentconfig', 'developer-workspace-profile')):
        expect(optional_object(kind, name) is None, f'{kind}/{name} already exists; refusing adoption')
    pulls, registry, username, password = registry_inputs(runtime_image)
    tls = spike.tls_material(); read_token = secrets.token_urlsafe(32)
    # Empty write token disables writer authentication; no control Pod or write Secret is created.
    known, _ = fixture_setup(fixture_image, tls, read_token, '', pulls, registry, username, password, hands_on=True)
    profile = live_profile(runtime_image, storage)
    config = render_profile.profile_config(profile, 'in-cluster', PULL_SECRET if pulls else '')
    config['metadata']['labels'] = {HANDS_ON_LABEL: 'true'}
    kubectl(['create', '-f', '-'], input_text=yaml.safe_dump(config))
    try:
        _, namespace, _ = bring_up(*HANDS_ON, 'persistent', known=known, profile=profile, read_token=read_token,
                                  tls=tls, pulls=pulls, registry=registry, username=username, password=password,
                                  composition=composition, hands_on=True)
        pod = workspace_pod(namespace)
    except (ProofError, subprocess.TimeoutExpired):
        print('Hands-on setup incomplete; use live-down to clean up before retrying.', file=sys.stderr)
        raise
    print(f'Workspace: {HANDS_ON[0]}\nNamespace: {namespace}\nRuntime Pod: {pod}')
    command = ['kubectl', '--context', tgt['context'], 'exec', '-n', namespace, f'pod/{pod}', '-c', 'runtime', '--',
               'sh', '-c', "cd /workspace && opencode run --format json '<task>' && sh verify.sh"]
    print(shlex.join(command))


def down(_args):
    storage_inputs(); target(); installed_matches_local()
    name, workspace_id = HANDS_ON; namespace = hands_on_namespace()
    xr = optional_object('developerworkspace', name)
    fixture = optional_object('namespace', PROOF_NS)
    config = optional_object('environmentconfig', 'developer-workspace-profile')
    ns = optional_object('namespace', namespace)
    # Validate every ownership marker before the first deletion.
    for obj in (xr, fixture, config): require_hands_on(obj)
    if xr: expect(xr['spec']['workspaceID'] == workspace_id, 'hands-on workspaceID was changed')
    others = [o for o in get_json(['get', 'developerworkspaces'])['items'] if o['metadata']['name'] != name]
    expect(not others, 'other DeveloperWorkspaces exist; refusing to remove the shared profile/fixture')
    if ns:
        expect(ns['metadata'].get('labels', {}).get('workspace.openkubes.io/id') == workspace_id
               and (fixture is not None or xr is not None), f'refusing unowned namespace/{namespace}')
    volumes = {v['metadata']['name']: v['metadata']['uid'] for v in get_json(['get', 'pv'])['items']
               if v['spec'].get('claimRef', {}).get('namespace') == namespace}
    if fixture:
        saved = json.loads(fixture['metadata'].get('annotations', {}).get(HANDS_ON_VOLUMES, '{}'))
        expect(isinstance(saved, dict), 'invalid hands-on PV cleanup journal')
        for volume, uid in saved.items():
            expect(volume not in volumes or volumes[volume] == uid, f'PV {volume} was replaced; refusing deletion')
        volumes = {**saved, **volumes}
        # Keep the journal until PV removal finishes, so an interrupted down can retry after the Namespace is gone.
        kubectl(['annotate', 'namespace', PROOF_NS, f'{HANDS_ON_VOLUMES}={json.dumps(volumes)}', '--overwrite'])
    else:
        expect(not volumes or xr is not None, 'hands-on PVs remain without an ownership marker')
    if xr: kubectl(['delete', f'developerworkspace/{name}', '--wait=true', '--timeout=600s'], timeout=630)
    wait_until(f'namespace {namespace} removal', lambda: optional_object('namespace', namespace) is None, timeout=600)
    wait_until(f'composed Objects of {name} removal', lambda: not composed_objects(name), timeout=300)
    # A pending PVC may bind between the first PV snapshot and XR deletion.
    remaining = {v['metadata']['name']: v['metadata']['uid'] for v in get_json(['get', 'pv'])['items']
                 if v['spec'].get('claimRef', {}).get('namespace') == namespace}
    for volume, uid in remaining.items():
        expect(volume not in volumes or volumes[volume] == uid, f'PV {volume} was replaced')
    if remaining:
        volumes.update(remaining)
        if fixture: kubectl(['annotate', 'namespace', PROOF_NS, f'{HANDS_ON_VOLUMES}={json.dumps(volumes)}', '--overwrite'])
    for volume, uid in volumes.items():
        def removed(volume=volume, uid=uid):
            obj = optional_object('pv', volume)
            expect(obj is None or obj['metadata']['uid'] == uid, f'PV {volume} was replaced')
            return obj is None
        wait_until(f'PersistentVolume {volume} removal', removed, timeout=300)
    if config: kubectl(['delete', 'environmentconfig/developer-workspace-profile', '--wait=true'])
    if fixture: kubectl(['delete', 'namespace', PROOF_NS, '--wait=true', '--timeout=600s'], timeout=630)
    print('Hands-on workspace, Namespace, PV and fixture removed (or already absent).')


RESULTS = ('admission-rules', 'no-profile-fails-closed', 'dedicated-namespace-enforced', 'reconcile-readback', 'drift-restored', 'pod-user-namespace-admission', 'source-checkout', 'persistent-marker-survives-replacement', 'runtime-user-boundary',
           'kubernetes-authority-denied', 'kubernetes-api-unreachable', 'runtime-push-denied', 'workspace-credential-push-denied', 'write-credential-absent', 'cpu-bound-enforced', 'memory-bound-enforced', 'storage-quota-enforced', 'CAPACITY',
           'persistent-cleanup', 'ephemeral-reconcile', 'ephemeral-storage-enforced', 'ephemeral-cleanup')

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
