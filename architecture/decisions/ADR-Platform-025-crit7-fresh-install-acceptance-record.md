# ADR-Platform-025 — Criterion 7 Fresh Datacenter Install Acceptance Record

**Scope:** ADR-Platform-025 acceptance **criterion 7** — a **fresh** datacenter install receives the
credentials Secret from **Vault via a `VaultStaticSecret` (VSO)** **before** the observability Helm
release. This is the one situation where the Secret cannot already exist, so it is the only case
that proves the *ordering* rather than a migration (which is criterion 6, already proven on
ok-robotics).

**Status:** **Verified — 2026-07-29** on `ok-obs-verify`, ok-cluster-driven per the ADR's
§Implementation & placement table (OK-117). Not a hand-assembled ordering.

---

## Consumed revisions

| Repo | Revision | Working tree |
|---|---|---|
| `ok-cluster` | `f03ed6f04b2d1d866496922a7058e4af1189325d` | clean |
| `ok-observability` | `c0cdc046e6589c431d7e2a46db06a4ec742cfffb` | clean, and equal to the `ok-observability.ref` pin |

Command — a single ok-cluster entry point, no manual wiring:

```bash
make install-observability CLUSTER=ok-obs-verify OBSERVABILITY_SECRET_SOURCE=vault
```

## Freshness — why this is criterion 7 and not criterion 6

Criterion 7 requires that the Secret **cannot already exist**. Established before the run:

| Precondition | Evidence |
|---|---|
| No Helm release | `helm history` → `Error: release: not found` |
| No namespace | `namespaces "ok-observability" not found` |
| No credentials Secret | `secrets "ok-observability-credentials" not found` |
| No reusable OpenSearch data | all four PVs (`reclaim=Delete`, `local-path`) confirmed deleted; 0 PVs bound to the namespace |

The install then reported `Release "ok-observability-standard" does not exist. Installing it now.`
and **`REVISION: 1`** / `Install complete` — a single-revision history, not an upgrade.

## The ordering, as emitted by the run

```
  [2/6] Secret ok-observability-credentials via VaultStaticSecret (VSO, datacenter profile)
        vault=https://192.168.100.207:443 mount=kubernetes/ok-obs-verify
        kv=secret/ok-obs-verify/obs/observability-credentials
        vaultconnection/ok-shared-vault created
        vaultauth/ok-obs-verify created
        vaultstaticsecret/ok-observability-credentials created
        waiting for VaultStaticSecret to report SecretSynced (before helm)
        vaultstaticsecret … condition met
        ✅ ok-observability-credentials materialised by VSO
  [3/6] helm dependency build (no repo refresh) + install
        Release "ok-observability-standard" does not exist. Installing it now.
        REVISION: 1
```

Vault materialised the Secret at `[2/6]`, **before** the Helm release at `[3/6]`.

## The decisive check — OpenSearch bootstrapped *from* the Vault value

Ordering alone is not sufficient: it must be shown that the workload actually consumed the
Vault-supplied credential. OpenSearch 2.12+ honours `OPENSEARCH_INITIAL_ADMIN_PASSWORD` only at
first security-index bootstrap, so its live admin password is a direct witness of which value was
present when the release started. Identical request, HTTP status only, no values recorded:

| Credential offered to the running OpenSearch | Result |
|---|---|
| `opensearch-admin-password` from Vault (KV **version 2**) | **HTTP 200** |
| the earlier file-profile password from the prior install | **HTTP 401** |

The inversion is the proof: the pre-existing value no longer authenticates, and the Vault value
does. The security index was bootstrapped from Vault.

The materialised Secret is VSO-owned — `ownerReferences: VaultStaticSecret/ok-observability-credentials` —
with keys `grafana-admin-password`, `grafana-admin-user`, `opensearch-admin-password` plus VSO's
harmless `_raw`. Compare the three *named* keys against the oracle, not the key count.

## Gate result

`tests/contract-test.sh`, invoked by the installer as `[6/6]`:
**`CONTRACT TEST: PASS — all five guarantees verified`**, `make` exit **0** (the exit code is the
normative machine contract per ADR-Platform-024).

| Guarantee | Result |
|---|---|
| 1 ServiceMonitor registered | ok |
| 2 metric ingested by Prometheus | ok |
| 3 metric visible via Grafana datasource (`uid PBFA97CFB590B2093`) | ok |
| 4 log marker searchable in OpenSearch | ok |
| 5 synthetic alert reached Alertmanager | ok — **fired-only**, see limits |

Repo-generated block (`make evidence`, not hand-written): `make verify` **PASS**,
`make conformance` **PASS**, commit `c0cdc04` on `main`.

CNI precondition (ADR-Platform-027): cilium `4/4` ready, `cilium-operator 1/1`, and cluster DNS
resolves from a pod in the namespace. Without this the gate result would be *unclassified* rather
than evidence, because every gate check reaches its service by port-forward and never traverses the
pod network.

## What this record does NOT prove

- **Alert delivery.** Guarantee 5 is the documented **fired-only** form;
  `CONTRACT_TEST_RECEIVER_CAPTURE_URL` was not set, so no receiver actually received the alert.
- **How the credential got into Vault.** The KV seed was a supervised break-glass Tier-A write,
  the sanctioned interim until **OK-115** delivers a scoped per-cluster KV write. Criterion 7's
  claim is the VSO-before-Helm ordering, not the provenance of the seed — that gap is orthogonal
  and documented.
- **Registration-driven onboarding.** The `VaultConfig` XR is an explicit onboarding step
  (`runbooks/vault-consumer-onboarding.md`); ADR-013 registration creates no Vault objects.
  Registration auto-reconciling the mount remains future work, out of scope here.
- **Rotation.** The OpenSearch bootstrap password is not rotatable by Secret replacement; generic
  rotation is criterion 9 with an actually-rotatable consumer.
- **`make evidence` in isolation.** Its `conformance` step cannot authenticate unless the caller
  supplies `GRAFANA_PASSWORD` / `OPENSEARCH_PASSWORD` — the installer does this via shell prefix
  assignments. Run standalone it reports FAIL for want of credentials, not for want of a working
  capability.

## Prior invalid attempt — recorded so it is not mistaken for evidence

An earlier run the same day on the same cluster **failed**, and would not have counted even had it
passed. It ran against an existing pass-1 (file-profile) install: helm reported `UPGRADED` /
`REVISION: 3` and VSO merely *adopted* the pre-existing Secret via `overwrite: true`, so the
"Secret cannot already exist" condition never occurred. Its gate failed guarantees 3 and 4 because
the seeded Vault values differed from the ones OpenSearch and Grafana had bootstrapped with — the
Vault value returned 401 while the pass-1 value returned 200, the exact inverse of the table above.
It was not criterion-6 evidence either, since criterion 6 requires migration *without* credential
change. Detail on OK-117.

## Sign-off

Evidence produced by the party running the install; **acceptance is the human reviewer's**, not
self-accepted. Relates: OK-117, OK-110, OK-109 (Part 1, file profile), OK-115, OK-79,
ADR-Platform-024, ADR-Platform-027.
