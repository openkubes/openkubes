# 01 — VM and K3s in the ok-local profile

- Test IDs: Phase 2 (VM, K3s, kubeconfig, tunnel, inventory, baseline)
- Date (UTC): 2026-10-30T13:57:56Z – 2026-10-30T14:17Z
- Commit: `d487540` (scaffold) plus the fixes listed under "Deviations"
- Environment: see [00-preflight.md](00-preflight.md). Host memory available before `vm-up`: 6.37 GiB (STOP-8 formula), accepted by the human at CP1. Docker Desktop not running. No other Multipass instance exists.

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless kubectl-pin   # Phase 1, v1.35.10
make -C … preflight          # re-measure memory before vm-up
make -C … vm-up              # cloud-init → .local/, multipass launch 24.04 --name ok-knative-local --cpus 4 --memory 8G --disk 40G
make -C … k3s-install        # versioned install.sh (sha256 pinned) → scp → INSTALL_K3S_VERSION=v1.35.5+k3s1 --disable=traefik --tls-san=<vm-ip>
make -C … kubeconfig         # sudo cat k3s.yaml → .local/kubeconfig (600), renamed to ok211, server https://127.0.0.1:6450
make -C … tunnel             # ssh -F /dev/null -f -N -M -S .local/tun.sock … -L 127.0.0.1:6450:127.0.0.1:6443
make -C … guard-node         # all guard checks including the single-node check
make -C … vm-ssh CMD='…'     # read-only inventory inside the VM (ok211::vm_ssh)
scripts/kc.sh get pods -A -o wide; scripts/kc.sh get deploy,ds -A; scripts/kc.sh get storageclass
make -C … baseline           # 3 × kubectl top, 60 s apart, plus free -m / uptime in the VM
```

Access path used for every VM command: direct SSH via `ok211::vm_ssh` (`-F /dev/null`, `IdentitiesOnly=yes`, `BatchMode=yes`, `UserKnownHostsFile=.local/known_hosts`). `multipass exec` and `multipass shell` were not used.

## Observed

### VM

| Property | Value |
|---|---|
| Instance | `ok-knative-local`, state `Running` |
| IPv4 | `192.168.252.2` (only address before K3s) |
| Image | Ubuntu 24.04 LTS, `image_hash` `50e24e1fb79e89116e939d90aa7738f7af48c442fa1bc2510131e0b39c50348e`, release Ubuntu 24.04.5 LTS, kernel `6.8.0-147-generic` |
| Resources | 4 CPUs, memory total 8 303 710 208 B, disk 41 519 586 304 B |
| Driver | `qemu` (Multipass 1.16.4+mac) |
| cloud-init | `status: done`, datasource `NoCloud`; rendered file `.local/cloud-init.yaml` with key `SHA256:/IFc0mrbcsedgs+IWOWxarVPWB27MQfcIfBGgj1BURc` |
| Launch duration | 13:57:56Z → 14:11:05Z (≈ 13 min, dominated by the image download over a slow link) |

### K3s

| Check | Observed | Verdict |
|---|---|---|
| Install script | `install.sh` at tag `v1.35.5+k3s1`, SHA-256 `8598e002…6d91` = pin | PASS |
| Binary | install script downloaded `k3s-arm64` and `sha256sum-arm64.txt` for `v1.35.5+k3s1` and reported "Verifying binary download" | PASS |
| Flags (`systemctl cat k3s`) | `server '--disable=traefik' '--tls-san=192.168.252.2'` | PASS, identical to ok-local |
| Version | `k3s version v1.35.5+k3s1 (6a4781ad)`, go1.25.9; server `v1.35.5+k3s1` | PASS |
| Node | `ok-knative-local` `Ready`, role `control-plane`, containerd `2.2.3-k3s1`, InternalIP `192.168.252.2` | PASS |
| Install → Ready | `systemd: Starting k3s` → node Ready at 14:13:54Z | — |

### Kubeconfig and tunnel

| Check | Observed | Verdict |
|---|---|---|
| `.local/kubeconfig` | mode `600`, 1 cluster / 1 user / 1 context, all `ok211`, server `https://127.0.0.1:6450`; contents never printed | PASS |
| Tunnel | `127.0.0.1:6450 -> 192.168.252.2:6443`, listener `ssh/61662`, control socket `.local/tun.sock` | PASS |
| TLS | kubectl verifies the K3s CA without any insecure flag; the API certificate SAN list contains `IP Address:127.0.0.1` (also `192.168.252.2`, `10.43.0.1`, `localhost`, `ok-knative-local`) | PASS, confirms Annex A |
| `make guard-node` | `PASS guard: context=ok211 server=https://127.0.0.1:6450 kubectl=v1.35 node=ok-knative-local` | PASS |
| kubectl / server | client `v1.35.10`, server `v1.35.5+k3s1` (same minor) | PASS |

### What K3s brings (inventory, evidenced)

| Component | Evidence | Note |
|---|---|---|
| CoreDNS | pod `coredns-8db54c48d-…` Running, image `rancher/mirrored-coredns-coredns:1.14.3` | — |
| metrics-server | pod `metrics-server-786d997795-…` Running (Ready ≈ 60 s after start), image `rancher/mirrored-metrics-server:v0.8.1` | `kubectl top` works (baseline) |
| local-path-provisioner | pod Running, image `rancher/local-path-provisioner:v0.0.36`; StorageClass `local-path (default)`, `WaitForFirstConsumer` | — |
| ServiceLB (klipper-lb) | `/var/lib/rancher/k3s/server/etc/cloud-config.yaml`: `"lbEnabled":true,"lbImage":"rancher/klipper-lb:v0.4.17","lbNamespace":"kube-system"`; the embedded cloud-controller-manager runs (`--cloud-provider=k3s`). No `svclb` pods yet: they appear with the first `LoadBalancer` Service (Phase 3) | enabled, as in ok-local |
| NetworkPolicy controller | `journalctl -u k3s`: "Starting network policy controller version v2.6.3-k3s1"; `iptables -S` holds 33 `KUBE-ROUTER` rules, chains `KUBE-ROUTER-FORWARD`, `-INPUT`, `-OUTPUT`. It runs inside the k3s process, not as a pod | enforced (relevant for X3) |
| Traefik | absent (no pod, no HelmChart manifest; `server/manifests/` holds `ccm.yaml coredns.yaml local-storage.yaml metrics-server rolebindings.yaml runtimes.yaml`) | disabled, as in ok-local |
| Flannel | pod CIDR `10.42.0.0/16` (pod IPs `10.42.0.x`), cluster CIDR from the CCM flags | — |

VM after K3s start (`free -m`): total 7919 MiB, used 820 MiB, available 7098 MiB; swap 0.

### Baseline (empty cluster)

Raw: [raw/resources-baseline-20261030T141511Z.txt](raw/resources-baseline-20261030T141511Z.txt), JSON line `resources-baseline` in [raw/resources.jsonl](raw/resources.jsonl). Samples at 14:15:12Z, 14:16:12Z, 14:17:12Z, starting ≈ 60 s after metrics-server became Ready (Annex C).

| Scope | CPU (mean / max) | Memory (mean / max) | Requests CPU / memory | Limits memory |
|---|---|---|---|---|
| Node `ok-knative-local` (`kubectl top nodes`) | 60m / 73m (1 %) | 638 Mi / 645 Mi (7–8 %) | — | — |
| Namespace `kube-system` (sum of pods) | 11m / 12m | 35 Mi / 38 Mi | 200m / 140 Mi | 170 Mi |

VM `free -m` at the start of the baseline: used 778 MiB, available 7140 MiB. Disturbance factors: Mac load average 4.27 4.28 4.46; VM load 0.30; no other Multipass instance; Docker Desktop not running.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| P2-vm | PASS | `ok-knative-local` Running, 4 CPU / 8 GiB / 40 GiB, Ubuntu 24.04.5 | — |
| P2-k3s | PASS | `v1.35.5+k3s1`, flags identical to ok-local | versioned install script |
| P2-access | PASS | context `ok211`, server `https://127.0.0.1:6450`, exactly one context, guard incl. node check green | — |
| P2-inventory | PASS | CoreDNS, metrics-server, local-path as pods; ServiceLB enabled (cloud-config); NetworkPolicy controller in-process (log + iptables) | — |
| P2-baseline | PASS | node 60m CPU, 638 Mi memory (mean of 3) | `kubectl top` returns values; saved for S10 |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| A K3s node identical in version and flags to the ok-local profile runs in an isolated VM, reachable only through the guarded tunnel | That ok-local's own VMs behave identically (they were not touched and do not exist on this host) |
| ServiceLB and the NetworkPolicy controller are active, read from configuration and logs | That NetworkPolicies are enforced as expected for Knative traffic (X3) |
| TLS to the API is verified through the tunnel without insecure flags | Anything about Knative yet |

## Deviations from BRIEF

1. **VM launch before the Phase 1 commit.** It was started early to overlap two slow downloads; no Phase 1 check used VM state.
2. **Fixes found while running Phase 2** (in the Phase 2 commit):
   - `scripts/tunnel.sh`: `lsof` exits 1 when the port is free, which under `set -e -o pipefail` aborted `make tunnel` silently. It is now handled as the normal "free" case.
   - `Makefile` `probe`/`vm-ssh`: `CMD` was expanded into the recipe text, which broke on quotes and pipes. It is now read from the environment.
   - New target `vm-ssh CMD=…` for read-only inspection, so VM commands do not need an ad-hoc `ssh`. An ad-hoc `source scripts/lib.sh` from zsh computed a wrong spike root (`BASH_SOURCE` is bash-only), so `known_hosts` could not be written; nothing was written outside the spike. VM commands now go only through `make vm-ssh`.
3. `kubectl-pin` resumes interrupted downloads (`curl -C -`); dl.k8s.io delivered ≈ 150 KB/s.
