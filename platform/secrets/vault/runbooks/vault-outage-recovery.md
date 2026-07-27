# Vault outage + recovery runbook — ADR-Platform-025 crit. 8 / ADR-018 autonomy

**What this proves (OK-110 criterion 8):** Vault is a **soft runtime dependency** but a
**hard bootstrap-and-recovery dependency**. Concretely:

1. A single `vault-0` pod restart is absorbed by Raft HA (quorum holds) — no consumer impact.
2. During a **full** Vault outage, the already-materialised consumer Secret
   `ok-observability-credentials` is **still served**, running workloads **and a pod restart
   survive**, and a **rotation does NOT propagate** (soft-dependency boundary).
3. After Vault returns (scale up + attended re-unseal), the reconciler/VSO **resync** and a
   rotation **propagates again** — recovery is complete.

This is the ADR-018 autonomy evidence too (the edge/offline profile is unaffected; this is the
datacenter profile's declared failure behaviour).

---

## ⚠️ Blast radius & safety (read before starting)

- Scaling the ok-shared Vault StatefulSet to `0` is a **real outage of the central secret
  backend for every datacenter consumer**. Today the only consumer is **ok-robotics**, so the
  blast radius is bounded — still, run this in a **scheduled window**.
- Recovery requires an **attended re-unseal** (Phase-1 Shamir, AR-025-1). **Have the unseal
  shares in hand** (`~/vault-init.json.gpg`, custody per the bootstrap ceremony) **before** you
  scale down. Without them you cannot bring Vault back.
- Raft data lives on PVCs; scaling the StatefulSet to 0 **does not delete data** (the composed
  Release is `deletionPolicy: Orphan` and this is a `kubectl scale`, not a delete). Pods return
  **sealed** and rejoin the existing Raft.
- Do **not** delete PVCs, the StatefulSet, or the XR. This runbook only `scale`s.
- Abort at any point: `kubectl -n vault scale sts vault --replicas=3` and re-unseal.

## Preconditions

- Contexts/kubeconfigs: `~/.kube/ok-shared.yaml` (Vault), `~/.kube/ok-robotics.yaml` (consumer).
- Vault healthy 3/3 before start; consumer Secret present and workloads green.
- Unseal shares available; break-glass (`userpass/breakglass`) known.
- `platform/secrets/vault/conformance/outage-evidence.sh` present (evidence capture).

## Topology recap

| Thing | Value |
|---|---|
| Vault | ok-shared, ns `vault`, StatefulSet `vault`, Raft HA **3/3**, v1.20.1 |
| Consumer | ok-robotics, ns `ok-observability` |
| Materialised Secret | `ok-observability-credentials` (4 keys) |
| VSO | `VaultConnection` + `VaultAuth` (mount `kubernetes/ok-robotics`, role `sa-obs`) + `VaultStaticSecret` |
| Consumers of the Secret | Grafana (`admin.existingSecret`), OpenSearch (`secretKeyRef`), Fluent Bit (`OPENSEARCH_PASSWORD`) |

Set once per shell:

```bash
export VAULT_CONTEXT=ok-shared
export CONSUMER_CONTEXT=ok-robotics
export CONSUMER_NS=ok-observability
export SECRET_NAME=ok-observability-credentials
export VSS_NAME=ok-observability-credentials      # VaultStaticSecret name (adjust if different)
export WORKLOADS="statefulset/opensearch-cluster-master deployment/grafana"   # a pod that mounts the Secret
export EV=./crit8-evidence.log                     # evidence log
EVID() { bash platform/secrets/vault/conformance/outage-evidence.sh --phase "$1" --out "$EV"; }
```

---

## Phase 0 — baseline

```bash
kubectl --context "$VAULT_CONTEXT" -n vault get pods -l app.kubernetes.io/name=vault
kubectl --context "$VAULT_CONTEXT" -n vault exec vault-0 -- vault status | grep -E "Sealed|HA Mode|Raft"
EVID baseline
```

Expect: 3/3 Ready & unsealed; Secret present; `VaultStaticSecret` `SecretSynced=True`; workloads Ready.
Record the **baseline Secret content hash** printed by `EVID baseline` — you will compare it later.

---

## Test A — single pod restart (HA quorum holds)

```bash
kubectl --context "$VAULT_CONTEXT" -n vault delete pod vault-0
kubectl --context "$VAULT_CONTEXT" -n vault rollout status sts/vault --timeout=180s
# vault-0 returns SEALED (Shamir). Unseal just this pod:
kubectl --context "$VAULT_CONTEXT" -n vault exec -i vault-0 -- vault operator unseal   # x3 shares (stdin)
EVID after-pod-restart
```

Expect: quorum never lost (vault-1/vault-2 stayed leader/voter); consumer Secret **unchanged**
(same hash); `VaultStaticSecret` stays `True`; no workload disruption. This shows a single-node
restart is transparent to consumers.

> Note: with attended Shamir, the restarted pod is sealed until unsealed — that is the accepted
> Phase-1 recovery SLO (AR-025-1). Quorum from the other two voters keeps Vault serving throughout.

---

## Test B — full outage (scale to 0)

### B1. Cut Vault

```bash
kubectl --context "$VAULT_CONTEXT" -n vault scale sts vault --replicas=0
kubectl --context "$VAULT_CONTEXT" -n vault rollout status sts/vault --timeout=120s || true
kubectl --context "$VAULT_CONTEXT" -n vault get pods -l app.kubernetes.io/name=vault   # → none
EVID outage-start
```

Expect at `outage-start`: **Secret still present and unchanged** (same hash as baseline);
`VaultStaticSecret` now reports a source/connection error (expected); **workloads still Ready**
(they read the materialised K8s Secret, not Vault).

### B2. Pod restart survives the outage

Kill a consumer pod that mounts the Secret and prove it returns from the **existing** K8s Secret
while Vault is down:

```bash
kubectl --context "$CONSUMER_CONTEXT" -n "$CONSUMER_NS" delete pod \
  -l app.kubernetes.io/name=opensearch --wait=false     # adjust selector to a Secret consumer
kubectl --context "$CONSUMER_CONTEXT" -n "$CONSUMER_NS" rollout status statefulset/opensearch-cluster-master --timeout=300s
EVID outage-after-consumer-restart
```

Expect: the pod reaches Ready **while Vault is down** — the Secret mount resolves from etcd, not
Vault. This is the crux of "soft runtime dependency".

### B3. (Optional) rotation does NOT propagate during outage

If you want the negative half of the soft-dependency proof, bump a *test* KV value — it cannot be
written (Vault is down), so nothing propagates. Skip if you prefer to keep the window short.

---

## Recovery — scale up + attended re-unseal

```bash
kubectl --context "$VAULT_CONTEXT" -n vault scale sts vault --replicas=3
kubectl --context "$VAULT_CONTEXT" -n vault rollout status sts/vault --timeout=300s || true
# each pod comes back SEALED — unseal each to threshold (Shamir, stdin), see bootstrap/README.md:
for p in vault-0 vault-1 vault-2; do
  kubectl --context "$VAULT_CONTEXT" -n vault exec -i "$p" -- vault operator unseal   # x3 shares each
done
kubectl --context "$VAULT_CONTEXT" -n vault exec vault-0 -- vault status | grep -E "Sealed|HA Mode"
# RaftHealthy 3/3:
make -C platform/secrets/vault health-gate GATE_ARGS=""   # or: VAULT_TOKEN=… --require-auth
EVID recovered
```

Expect: 3/3 unsealed, Raft quorum restored; `VaultStaticSecret` returns to `SecretSynced=True`
within its `refreshAfter`.

## Phase R — reconciliation proof (rotation propagates again)

Prove the store→consumer path is live again with an **actually rotatable** value (the OK-110 A7
`rotation-demo` pattern — NOT the OpenSearch bootstrap password):

```bash
# break-glass write of a new value:
kubectl --context "$VAULT_CONTEXT" -n vault exec -i vault-0 -- \
  env VAULT_TOKEN="$BGT" vault kv put secret/ok-robotics/obs/rotation-demo token=v3-charlie
# force/await VSO refresh, then confirm the consumer sees it:
EVID reconciled
```

Expect: `VaultStaticSecret` `SecretSynced=True`, and (for the rotation-demo consumer) the new
value lands after `rolloutRestartTargets`. Recovery is complete.

---

## Expected-results matrix

| Phase | Vault | Consumer Secret | Secret hash | VaultStaticSecret | Workloads |
|---|---|---|---|---|---|
| baseline | 3/3 unsealed | present | H0 | SecretSynced=True | Ready |
| after-pod-restart | 3/3 (1 re-unsealed) | present | **H0** | True | Ready |
| outage-start | 0 pods | **present** | **H0** | error (expected) | Ready |
| outage-after-consumer-restart | 0 pods | present | H0 | error | **Ready (restarted)** |
| recovered | 3/3 unsealed | present | H0 | True | Ready |
| reconciled | 3/3 unsealed | present | H1 (rotated) | True | Ready (rolled) |

The invariant that must **never** break: the consumer Secret is **present at every phase**
(hash unchanged until the deliberate rotation in Phase R). `outage-evidence.sh` fails if the
Secret is ever absent while Vault is down.

## Abort / rollback

```bash
kubectl --context "$VAULT_CONTEXT" -n vault scale sts vault --replicas=3
for p in vault-0 vault-1 vault-2; do kubectl --context "$VAULT_CONTEXT" -n vault exec -i "$p" -- vault operator unseal; done
```

## Sign-off

- Attach `crit8-evidence.log` to `ADR-Platform-025-crit8-outage-recovery-acceptance-record.md`.
- Closes ADR-025 criterion 8 **and** the ADR-018 autonomy outage evidence.
- Three-way review (Arash / Claude / GPT), then tick crit. 8 in the OK-110 thread.
