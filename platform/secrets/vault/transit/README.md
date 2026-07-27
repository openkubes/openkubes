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

The Transit Vault's data (the transit key) is **critical** — if lost, ok-shared cannot auto-unseal.
Two independent safety nets exist: (a) the Transit backup below; (b) ok-shared's **recovery keys**
(the migrated Shamir shares, `~/vault-init.json.gpg`) — with those you can `generate-root` / re-key
ok-shared or migrate its seal back to Shamir even if the Transit Vault is permanently gone.

**Backup** (file-storage snapshot, encrypted to the operator key, off-host + registered):

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml GPG_RECIPIENT=<operator-key> OFFHOST_DIR=~/vault-backups \
  bash transit-backup.sh
```

Records to `transit-backup-register.md`. Recovery also needs the Transit **Shamir shares**
(`~/transit-init.json.gpg`, verified custody). Restore: recreate the Transit Vault (10-tls +
Helm), stop it, restore `/vault/data` from the decrypted tar, start, unseal with the Transit
shares. Re-run a backup after any change to the transit engine/keys.

## Seal-token lifecycle & rotation

The ok-shared seal token is **periodic** (`period=768h`, `renewable=true`, no `explicit_max_ttl`)
— Vault auto-renews it while running, so it does **not** expire in normal operation. Rotation is
only needed on compromise or policy change:

```bash
# 1. mint a fresh scoped token on the Transit Vault (root/admin)
NEW=$(kubectl -n vault-transit exec -i vault-transit-0 -- env VAULT_ADDR=https://127.0.0.1:8200 \
  VAULT_SKIP_VERIFY=true VAULT_TOKEN=<admin> vault token create -policy=autounseal -period=768h -orphan -field=token)
# 2. update the ok-shared seal secret
kubectl --context ok-shared -n vault create secret generic vault-transit-seal \
  --from-literal=token="$NEW" --from-file=ca.crt=<transit-ca> --dry-run=client -o yaml | kubectl apply -f -
unset NEW
# 3. roll ok-shared pods one at a time so they pick up the new env token (they auto-unseal)
#    kubectl -n vault delete pod vault-2 ; wait Ready ; vault-1 ; vault-0
# 4. revoke the old token on the Transit Vault
```
