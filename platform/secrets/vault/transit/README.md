# Transit Vault — auto-unseal provider for ok-shared (OK-114)

A small, dedicated Vault on **ok-mgmt** that provides a Transit key to auto-unseal the ok-shared
Vault (removes the attended-Shamir / memorized-passphrase recovery dependency, OK-113 lesson).
Mechanism proven end-to-end in the local lab — see `runbooks/vault-transit-autounseal.md`.

**Independence:** runs on ok-mgmt (not ok-shared); only needed at ok-shared unseal time. NOT a
`VaultInstance` XR (the crit. 14 singleton guard name-pins `ok-shared-vault`) — a standalone Helm
release.

## Layout / apply order

| File | Cluster | What |
|---|---|---|
| `10-tls.yaml` | ok-mgmt | cert-manager selfSigned → CA → server cert (IP SAN 192.168.100.208) |
| `20-helm-values.yaml` | ok-mgmt | `helm install vault-transit hashicorp/vault -n vault-transit -f ...` |
| `30-nodeport.yaml` | ok-mgmt | fixed NodePort 31820 for the transit service |
| `40-ok-infra-lb.yaml` | **ok-infra** | LoadBalancer 192.168.100.208 → ok-mgmt CP VM :31820 (existing pattern) |

## Apply

```bash
KM() { KUBECONFIG=~/.kube/ok-mgmt.yaml kubectl "$@"; }
KI() { KUBECONFIG=~/.kube/ok-infra.yaml kubectl "$@"; }
KM apply -f 10-tls.yaml
KM -n vault-transit get certificate            # wait vault-transit-tls Ready=True
helm repo add hashicorp https://helm.releases.hashicorp.com && helm repo update
KUBECONFIG=~/.kube/ok-mgmt.yaml helm install vault-transit hashicorp/vault \
  -n vault-transit -f 20-helm-values.yaml
KM apply -f 30-nodeport.yaml
KI apply -f 40-ok-infra-lb.yaml
```

Then: init the transit Vault **out of band** with a **decrypt-verified** custody (same gate as
OK-113), enable `transit`, create key `autounseal-ok-shared` + a scoped token, and wire ok-shared's
`seal "transit"` (address `https://192.168.100.208:8200`, `tls_ca_cert` = the `transit-ca`, the
token via a Secret). Migration + restart proof per the runbook.

## Backups / recovery

The Transit Vault's data (the transit key) is **critical** — persist it (local-path PVC) and back
it up (Raft/file snapshot + verified custody). If it is lost, ok-shared cannot auto-unseal (restore
Transit from backup, or use ok-shared's **recovery keys** — the migrated Shamir shares — to
`generate-root` / re-migrate).
