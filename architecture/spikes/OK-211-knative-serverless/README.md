# OK-211 — Knative as an optional serverless and event capability (spike)

Spike for [OK-211](https://kubernauts.atlassian.net/browse/OK-211): evaluate Knative Serving
and Eventing as an optional, GitOps-managed OpenKubes platform capability, without changing
the core platform or the Console. The binding work order is [`BRIEF.md`](BRIEF.md) (German);
everything this spike produces is in English.

> **Status: report delivered, awaiting review (CP2).** Proposed result **CONDITIONAL GO**:
> see [MANAGEMENT-SUMMARY.md](MANAGEMENT-SUMMARY.md) and [REPORT.md](REPORT.md).
> Nothing here is a production rollout or an implementation commitment (ticket constraint).

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

From zero to a running Knative 1.23 installation: `make install`, then
`make probe-up apps-serving smoke`. Every experiment and the teardown are listed in
[REPORT.md §19](REPORT.md#19-reproduction) (`make help` shows all targets). Teardown:
`make down` keeps the VM, `make clean CONFIRM=yes` deletes it and its local state.

## Progress

| Phase | Content | Status | Evidence |
|---|---|---|---|
| 0 | Orientation and preflight | done (CP1 passed 2026-10-30) | [00-preflight.md](evidence/00-preflight.md) |
| 1 | Scaffold: guard, lib, scan, Makefile | done | [00-preflight.md § Guard negative tests](evidence/00-preflight.md) |
| 2 | VM in the ok-local profile | done | [01-vm-k3s.md](evidence/01-vm-k3s.md) |
| 3 | Knative 1.23 install | done | [02-knative-install.md](evidence/02-knative-install.md) |
| 4 | Upgrade to 1.24 under load | done (3 runs, CP3 decisions B/B2/B3) | [03-upgrade.md](evidence/03-upgrade.md) |
| 5 | Serving PoC | done | [04-serving.md](evidence/04-serving.md) |
| 6 | Eventing PoC | done | [05-eventing.md](evidence/05-eventing.md) |
| 7 | Networking, ingress, TLS | done | [06-networking-tls.md](evidence/06-networking-tls.md) |
| 8 | Security, tenancy, policy, observability | done | [07-security.md](evidence/07-security.md) |
| 9 | GitOps lifecycle | done (G3 NOT RUN) | [08-gitops.md](evidence/08-gitops.md) |
| 10 | Architecture assessment | done | [09-architecture-assessment.md](evidence/09-architecture-assessment.md) |
| 11 | Report and management summary | done | [REPORT.md](REPORT.md), [MANAGEMENT-SUMMARY.md](MANAGEMENT-SUMMARY.md), [drafts/](drafts/) |
| 12 | Close-out | done, waiting at CP2 | [§ Close-out](#close-out-phase-12) |

## Deliverables

| File | Content |
|---|---|
| [MANAGEMENT-SUMMARY.md](MANAGEMENT-SUMMARY.md) | one page for decision makers |
| [REPORT.md](REPORT.md) | full report (B13), findings F1–F15, criteria M1–M6/K1–K5, effort WP1–WP10 |
| [evidence/](evidence/) | one file per phase, raw data in `evidence/raw/` (`measurements.json`) |
| [drafts/](drafts/) | Jira comment (German) and PR description; not posted |
| `diagrams/architecture.svg` | PENDING (needs mermaid-cli, approval required); Mermaid source in REPORT §3 |

## Deviations from ok-local


- The K3s install script is fetched from the versioned tag
  (`k3s-io/k3s/v1.35.5+k3s1/install.sh`, SHA-256 pinned) instead of the unversioned
  `get.k3s.io`, and copied into the VM rather than piped from the network.
- SSH runs with `-F /dev/null`, `IdentitiesOnly=yes`, `BatchMode=yes` and
  `UserKnownHostsFile=.local/known_hosts` instead of the user's `~/.ssh/config`.
- The API tunnel uses port `6450` and a control socket (`.local/tun.sock`) and is
  stopped through that socket, never with `pkill`.

## Close-out (Phase 12)

Run on 2026-10-31 between 14:08Z and 14:12Z.

| Check | Result |
|---|---|
| `make verify` | PASS, 7/7 checks: `knative-verify`, smoke `200`, release dry run 1.24 without SSA conflict, evidence and report files present, `measurements.json` lines carry the B11 fields, 28 required series present, `BRIEF.md` unchanged (sha256 `fd96141b…fac5`). Negative check: with `evidence/09-…` moved away, `verify` failed with "missing: evidence/09-architecture-assessment.md" |
| `make lint` | shellcheck clean (28 files), yamllint clean (43 files); kubeconform not installed (optional, reported at CP1) |
| `make lint-server` | 31 manifests behave as expected; `security/x1-tenant-a.yaml` is **expected to be rejected** (PSA `restricted`, see [07](evidence/07-security.md)); Helm values files excluded |
| `make scan-secrets`, `make scan-history` | clean (worktree, index, history `origin/main..HEAD`) |
| `make test-guard` | all guard cases behave as expected ([raw](evidence/raw/guard-negative-tests-20261031T140624Z.txt)) |
| Changes outside the spike folder | none: `git diff --stat origin/main...HEAD -- . ':(exclude)architecture/spikes/OK-211-knative-serverless'` is empty |
| `multipass list` before the spike (CP1) | `No instances found.` |
| `multipass list` now | `ok-knative-local Stopped` (Ubuntu 24.04 LTS), 1 snapshot (`knative-1-23`); created by this spike, no other instance; nothing caused by the human apart from installing Multipass before CP1 |
| Environment | `make down`: tunnel stopped (no listener on 6450, control socket removed), VM stopped and kept for review; `.local/` is 72 MB |
| Codex review (optional) | not run |
