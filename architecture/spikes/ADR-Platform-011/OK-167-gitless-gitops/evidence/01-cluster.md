# 01 — Local kind cluster

> Historical record from 2026-10-29. Review findings and the 2026-10-30 retest are documented in [12-review-remediation.md](12-review-remediation.md). Original observations below are retained; they do not certify the revised implementation.

- Test IDs: Phase 2 (cluster isolation, pinned node image, storage class)
- Date (UTC): 2026-10-29T11:43Z
- Worktree commit: `47d4d4d` (Phase 1 scaffold)
- Environment: see `00-preflight.md` — macOS 27.0.1 arm64, Docker Desktop 29.5.3 (11.67 GiB),
  kind v0.33.0

## Steps

```bash
make up            # kind create cluster --name ok167 --config kind/cluster.yaml
                   #   --image kindest/node:v1.36.4@sha256:099e0493... --kubeconfig .local/kubeconfig
make up            # again, to prove idempotency
make cluster-info  # versions, nodes, node image, storage classes, API server
make guard

# Port binding, read from Docker and from the host
docker port ok167-control-plane
docker inspect ok167-control-plane --format '{{json .HostConfig.PortBindings}}'
lsof -nP -iTCP:30500 -sTCP:LISTEN
lsof -nP -iTCP:54192 -sTCP:LISTEN

# Port binding, proved by connection attempt rather than by reading configuration
nc -z -w 3 127.0.0.1 54192
nc -z -w 3 192.168.178.118 54192      # the host's LAN address
nc -z -w 3 192.168.178.118 30500
nc -z -w 3 127.0.0.1 30500
```

## Observed

### Creation

Cluster created in **62 s** wall clock, control plane Ready after 16 s. No warnings.

### Pass criteria

| Criterion | Expected | Observed | Verdict |
|---|---|---|---|
| Node Ready | `Ready` | `ok167-control-plane  Ready  control-plane  v1.36.4` | PASS |
| Context | `kind-ok167` | `kind-ok167` | PASS |
| API server | `https://127.0.0.1:<port>` | `https://127.0.0.1:54192` | PASS |
| Exactly one context | 1 | `contexts=kind-ok167`, `clusters=kind-ok167` | PASS |
| Default StorageClass | present | `standard (default)`, provisioner `rancher.io/local-path`, `WaitForFirstConsumer` | PASS |
| Kubernetes version | v1.36.4 (pin) | server `v1.36.4` | PASS |
| Node image digest | pin from `versions.env` | `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed` — exact match | PASS |
| kubectl skew | ≤ 1 minor | client `v1.37.0`, server `v1.36.4` → 1 | PASS |
| Idempotency | second run changes nothing, exit 0 | "cluster 'ok167' already exists — nothing to do", exit 0 | PASS |
| Kubeconfig permissions | 600 | `600 .local/kubeconfig` | PASS |

### Environment detail

| Property | Value |
|---|---|
| OS image | Debian GNU/Linux 13 (trixie) |
| Kernel | 6.12.76-linuxkit (arm64) |
| Container runtime | containerd://2.3.4 |
| Node internal IP | 172.18.0.3 |

The arm64 kernel confirms the node runs natively rather than under emulation, which matters
for the latency figures collected in Phase 7 and 10.

### Network exposure — loopback only

Docker publishes both ports on the loopback interface alone:

```text
6443/tcp  -> 127.0.0.1:54192
30500/tcp -> 127.0.0.1:30500
```

`HostConfig.PortBindings` gives `"HostIp": "127.0.0.1"` for both, and `lsof` shows
`com.docke` listening on `127.0.0.1:30500` and `127.0.0.1:54192` — nothing on `0.0.0.0` and
nothing on the host's LAN address.

Reading the configuration only proves intent, so the binding was also tested by connecting.
The host's LAN address at the time of the test was `192.168.178.118`:

| Target | Expected | Result |
|---|---|---|
| `127.0.0.1:54192` (API server) | reachable | **succeeded** |
| `192.168.178.118:54192` (API server via LAN) | refused | **refused** |
| `192.168.178.118:30500` (NodePort via LAN) | refused | **refused** |
| `127.0.0.1:30500` (NodePort via loopback) | TCP accepted | **succeeded** — Docker's proxy is listening; there is no Service behind it yet |

BRIEF B4 rule 8 is therefore satisfied by observation, not by configuration alone.

## Verdict

**PASS.** All Phase 2 criteria met. The cluster is pinned to the intended Kubernetes version
by digest, holds exactly one context, is reachable only over loopback, and `make up` is
idempotent.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| The cluster runs Kubernetes v1.36.4 from the exact pinned node-image digest | That Argo CD v3.5.6 works correctly on it — only that the pair is inside the tested range |
| The API server and NodePort 30500 are bound to loopback and refuse connections from the host's LAN address | That they would be unreachable from another host under a different Docker network configuration, or over IPv6 — only IPv4 was tested |
| The guard passes against a real kind-generated kubeconfig, not just synthetic ones | That it would catch every way a kubeconfig could later be modified |
| A default StorageClass named `standard` exists, so zot's PVC will bind | That a 2 GiB PVC will actually provision — Phase 3 shows that |
| `make up` is idempotent and exits 0 on a second run | That it recovers from a half-created cluster — not tested |
| The node runs an arm64 kernel natively | Anything about performance under load; Phase 10 measures that |
