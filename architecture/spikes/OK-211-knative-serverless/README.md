# OK-211 — Knative as an optional serverless and event capability (spike)

Spike for [OK-211](https://kubernauts.atlassian.net/browse/OK-211): evaluate Knative Serving
and Eventing as an optional, GitOps-managed OpenKubes platform capability, without changing
the core platform or the Console. The binding work order is [`BRIEF.md`](BRIEF.md) (German);
everything this spike produces is in English.

> **Status: in progress.** See [Progress](#progress). Nothing here is a production rollout
> or an implementation commitment (ticket constraint).

## What runs where

- A dedicated Multipass VM `ok-knative-local` that mirrors the ok-local profile
  (Ubuntu 24.04, K3s `v1.35.5+k3s1`, Traefik disabled, 4 CPUs, 8 GiB, 40 GiB).
- The K3s API is reached only through an SSH tunnel on `127.0.0.1:6450`
  (kubeconfig context `ok211`). The existing ok-local VMs and their tunnels
  (6443/6444) are never touched.
- Knative Serving + Kourier + Eventing, first `1.23`, then upgraded to `1.24` (done in Phase 4).
- All pins, digests and checksums live in [`versions.env`](versions.env).

## Safety model

| Rule | Where it is enforced |
|---|---|
| Every change to VM or cluster runs through `make` | [`Makefile`](Makefile) |
| Only context `ok211`, server `https://127.0.0.1:6450`, kubectl from `.local/bin/`, single node `ok-knative-local` | [`scripts/guard.sh`](scripts/guard.sh), tested by `make test-guard` |
| Multipass/SSH/SCP only to `ok-knative-local`, own `known_hosts`, no `~/.ssh/config` | `ok211::vm_*` in [`scripts/lib.sh`](scripts/lib.sh) |
| Ad-hoc reads only through the guard, never Secret data | [`scripts/kc.sh`](scripts/kc.sh) |
| Release manifests only from `.local/manifests/`, checksum-verified | [`scripts/fetch-manifests.sh`](scripts/fetch-manifests.sh) |
| Release manifests applied server-side without `--force-conflicts`; runtime-owned fields removed by three checked derivation rules; `make knative-dry-run` before an upgrade | `derive_apply_set` in [`scripts/knative.sh`](scripts/knative.sh), [03-upgrade.md](evidence/03-upgrade.md) |
| No credentials in Git | [`scripts/scan-secrets.sh`](scripts/scan-secrets.sh) before every commit |
| Credentials, sockets, downloads, tool config | `.local/` (gitignored, mode 600 for secrets) |

## Reproduction

```bash
cd architecture/spikes/OK-211-knative-serverless
make help
make preflight          # read-only host/tool/pin check
make kubectl-pin        # kubectl v1.35.10 into .local/bin/, SHA-256 verified
make test-guard         # guard negative tests
make lint scan-secrets
```

The full path from zero to a running Knative installation (`make install`) and the
teardown are added phase by phase below and completed in Phase 11.

## Progress

| Phase | Content | Status | Evidence |
|---|---|---|---|
| 0 | Orientation and preflight | done (CP1 passed 2026-10-30) | [00-preflight.md](evidence/00-preflight.md) |
| 1 | Scaffold: guard, lib, scan, Makefile | done | [00-preflight.md § Guard negative tests](evidence/00-preflight.md) |
| 2 | VM in the ok-local profile | done | [01-vm-k3s.md](evidence/01-vm-k3s.md) |
| 3 | Knative 1.23 install | done | [02-knative-install.md](evidence/02-knative-install.md) |
| 4 | Upgrade to 1.24 under load | done (3 runs, CP3 decisions B/B2/B3) | [03-upgrade.md](evidence/03-upgrade.md) |
| 5 | Serving PoC | open | — |
| 6 | Eventing PoC | open | — |
| 7 | Networking, ingress, TLS | open | — |
| 8 | Security, tenancy, policy, observability | open | — |
| 9 | GitOps lifecycle | open | — |
| 10 | Architecture assessment | open | — |
| 11 | Report and management summary | open | — |
| 12 | Close-out | open | — |

## Deviations from ok-local

Recorded as they arise.

- The K3s install script is fetched from the versioned tag
  (`k3s-io/k3s/v1.35.5+k3s1/install.sh`, SHA-256 pinned) instead of the unversioned
  `get.k3s.io`, and copied into the VM rather than piped from the network.
- SSH runs with `-F /dev/null`, `IdentitiesOnly=yes`, `BatchMode=yes` and
  `UserKnownHostsFile=.local/known_hosts` instead of the user's `~/.ssh/config`.
- The API tunnel uses port `6450` and a control socket (`.local/tun.sock`) and is
  stopped through that socket, never with `pkill`.
