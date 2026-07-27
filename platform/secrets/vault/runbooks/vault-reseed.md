# Vault re-seed runbook — recover from lost unseal custody (OK-113)

> **Outcome — executed 2026-07-27: SUCCESS.** ok-shared Vault re-seeded with fresh 5/3 Shamir and
> **decrypt-verified** custody (P2d gate). All three voters live-unsealed; audit + break-glass
> (reset + login-verified) + `ok-config-automation` + `kubernetes/ok-mgmt` seeded; root revoked.
> provider-vault auto-reconciled `kubernetes/ok-robotics` + policy from Git; `secret/` KV re-enabled
> and `observability-credentials` restored from the encrypted export; VSO on ok-robotics
> re-authenticated and `VaultStaticSecret` went `Synced/Healthy`. Fresh verified-custody backup
> taken. A stray break-glass mismatch was corrected via `vault operator generate-root` (using the
> verified unseal shares) — proving end-to-end recoverability.

**Why.** The ok-shared Vault's Shamir unseal-share custody passphrase was lost (OK-113). There is
no in-place fix — rekey / seal-migration both require the current unseal keys. The remedy is a
**fresh initialization** with new, **verified** custody, re-seeding the (small, reproducible) data.
Seal method decided: **fresh Shamir 5/3 + recorded, decrypt-verified custody** (auto-unseal remains
the tracked follow-up per ADR-025).

**Blast radius.** Only consumer is ok-robotics observability. Its materialised K8s Secret
`ok-observability-credentials` persists throughout (soft dependency), so observability keeps
running; only Vault control-plane functions pause during the window.

## Reconstruction sources (confirmed 2026-07-27, before any wipe)

| Piece | Source | Rebuild in |
|---|---|---|
| `kubernetes/ok-robotics` mount + role `sa-obs` + policy `okvc-ok-robotics-sa-obs` | provider-vault VaultConfig XR `ok-robotics` (SYNCED/READY) — auto-reconciles | P4 (automatic) |
| provider-vault auth: `kubernetes/ok-mgmt` mount + role `provider-vault` + policy `ok-config-automation` | manual ceremony seed (bootstrap/README §3c) | P3 |
| break-glass `userpass/breakglass` + `ok-admin` | manual (new password, recorded) | P3 |
| audit device | manual | P3 |
| `secret/` KV v2 engine | manual enable | P4 |
| secret `ok-robotics/obs/observability-credentials` | encrypted export `~/vault-backups/vault-kv-export-*.json.gpg` (+ materialised K8s Secret) | P4 |
| Server TLS + CA, ingress/reachability | cert-manager + Traefik — **unchanged by re-init** | n/a |
| Reviewer JWTs / CA on ok-mgmt | `crossplane-system` secrets `vault-reviewer-token`, `ok-robotics-reviewer-jwt`, `ok-shared-vault-ca` — present | P3/P4 |

## Prepare (before P2)

- New **break-glass password** → password manager.
- New **symmetric passphrase** for the share-custody file → password manager.
- `okb`/context note: contexts are unnamed — use `KUBECONFIG=~/.kube/{ok-shared,ok-mgmt}.yaml`.

---

## P2 — fresh init (destructive; custody GATE before proceeding)

### P2a — pause the composed Helm Release so Crossplane doesn't fight the wipe (on ok-mgmt)

```bash
KM() { KUBECONFIG=~/.kube/ok-mgmt.yaml kubectl "$@"; }
KM get releases.helm.crossplane.io | grep -i vault      # find the Vault Release MR name -> <REL>
KM annotate release.helm.crossplane.io <REL> crossplane.io/paused=true --overwrite
```

### P2b — wipe raft + audit data (on ok-shared)

```bash
KS() { KUBECONFIG=~/.kube/ok-shared.yaml kubectl -n vault "$@"; }
KS scale statefulset vault --replicas=0
KS wait --for=delete pod/vault-0 pod/vault-1 pod/vault-2 --timeout=120s
KS delete pvc data-vault-0 data-vault-1 data-vault-2 audit-vault-0 audit-vault-1 audit-vault-2
KS scale statefulset vault --replicas=3
KS rollout status statefulset/vault --timeout=180s || true   # pods come up NotReady (uninitialised) — expected
KS get pods -l app.kubernetes.io/name=vault
```

### P2c — initialize with NEW Shamir shares

```bash
# init on vault-0 (fresh cluster). Plain shares, then WE wrap them symmetrically ourselves.
KS exec -i vault-0 -- vault operator init -key-shares=5 -key-threshold=3 -format=json > ~/vault-init.NEW.json
```

### P2d — 🔒 CUSTODY GATE (do NOT continue until this passes)

```bash
# wrap with the NEW symmetric passphrase (loopback, so exactly what you type is used)
read -rs NEWPW
printf '%s' "$NEWPW" | gpg --batch --yes --symmetric --cipher-algo AES256 \
  --pinentry-mode loopback --passphrase-fd 0 \
  -o ~/vault-init.json.NEW.gpg ~/vault-init.NEW.json
# VERIFY the wrap decrypts with the SAME passphrase (this is the step that was skipped last time)
printf '%s' "$NEWPW" | gpg --batch --no-symkey-cache --pinentry-mode loopback --passphrase-fd 0 \
  -d ~/vault-init.json.NEW.gpg | jq -e '.unseal_keys_b64 | length == 5' && echo "CUSTODY OK" || echo "STOP"
unset NEWPW
```

Only if `CUSTODY OK`: store `~/vault-init.json.NEW.gpg` + the passphrase in the password manager,
then `shred -u ~/vault-init.NEW.json` (the plaintext), and replace the old dead file:
`mv ~/vault-init.json.NEW.gpg ~/vault-init.json.gpg`.

### P2e — unseal all three voters

```bash
for p in vault-0 vault-1 vault-2; do
  for i in 0 1 2; do
    KS exec -i "$p" -- vault operator unseal "$(jq -r ".unseal_keys_b64[$i]" ~/vault-init.NEW.json)"
  done
done
KS exec vault-0 -- vault status | grep -E 'Sealed|HA Mode'   # Sealed false; one active
```

(If you already shredded the plaintext, decrypt the .gpg to a tmp for the unseal loop, then shred.)

---

## P3 — ceremony seed (new root is the P2 init root token)

Follow `bootstrap/README.md` Steps 3a–3c with the NEW root token, then revoke it:

```bash
export ROOT="$(jq -r .root_token ~/vault-init.NEW.json)"
VXR() { KS exec -i vault-0 -- env VAULT_TOKEN="$ROOT" vault "$@"; }
# 3a audit
VXR audit enable file file_path=/vault/audit/audit.log
# 3b break-glass (NEW recorded password)
VXR auth enable userpass
VXR policy write ok-admin - <<'HCL'
path "*" { capabilities = ["create","read","update","delete","list","sudo"] }
HCL
read -rs BGNEW; VXR write auth/userpass/users/breakglass password="$BGNEW" policies="ok-admin"; unset BGNEW
# 3c automation policy + kubernetes/ok-mgmt seed (reviewer-JWT model)
#   ok-config-automation policy: copy verbatim from bootstrap/README.md §3c.
#   Then: vault auth enable -path=kubernetes/ok-mgmt kubernetes
#         vault write auth/kubernetes/ok-mgmt/config kubernetes_host=... kubernetes_ca_cert=@... token_reviewer_jwt=@...
#         vault write auth/kubernetes/ok-mgmt/role/provider-vault bound_service_account_names=provider-vault \
#            bound_service_account_namespaces=crossplane-system policies=ok-config-automation ttl=20m
#   Inputs: token_reviewer_jwt = crossplane-system/vault-reviewer-token (.data.token, base64 -d);
#           kubernetes_ca_cert  = ok-mgmt cluster CA; kubernetes_host = https://<ok-mgmt-api>:6443.
```

Then revoke root: `VXR token revoke -self; unset ROOT`.

## P4 — reconcile + restore data

```bash
# 1. provider-vault reconciles ok-robotics automatically once kubernetes/ok-mgmt is seeded.
KM annotate release.helm.crossplane.io <REL> crossplane.io/paused-           # unpause (P2a)
KM get vaultconfig.platform.openkubes.ai ok-robotics -w                      # wait SYNCED/READY again
# (force a retry if needed: KM annotate <the 4 MRs> or the XR to reconcile)

# 2. KV engine + restore the secret from the export (break-glass token)
BGT=... # break-glass login as usual
VXP() { KS exec -i vault-0 -- env VAULT_TOKEN="$BGT" vault "$@"; }
VXP secrets enable -path=secret -version=2 kv
gpg -d ~/vault-backups/vault-kv-export-<latest>.json.gpg \
  | jq -r '.data.data | to_entries | map("\(.key)=\(.value)") | .[]' \
  | xargs KS exec -i vault-0 -- env VAULT_TOKEN="$BGT" vault kv put secret/ok-robotics/obs/observability-credentials
```

## P5 — verify + close

```bash
# consumer VSO re-auth + secret unchanged
KUBECONFIG=~/.kube/ok-robotics.yaml kubectl -n ok-observability get vaultstaticsecret,secret
# health gate
KUBECONFIG=~/.kube/ok-shared.yaml VAULT_TOKEN=<bg> make -C platform/secrets/vault health-gate --require-auth
# fresh backup with the NEW verified custody, then a restore rehearsal THROUGH FULL UNSEAL
make -C platform/secrets/vault raft-snapshot
```

Then: mark restore-tested in the register with a full-unseal date, **close OK-113**, remove the
crit. 8 BLOCKED banner, and schedule crit. 8 execution.

## Rollback thinking

The wipe is only safe because reconstruction is fully sourced (table above). If P3/P4 fails, the
data is still recoverable from Git (auth/policies) + the encrypted export + the materialised K8s
Secret — re-run P3/P4. The old (lost-key) Vault is not recoverable and is not a rollback target.
