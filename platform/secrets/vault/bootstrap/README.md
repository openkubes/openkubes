# Vault bootstrap ceremony — datacenter secret backend (OK-110, ADR-Platform-025)

**Supervised, once, out of band.** This is the Phase-1 attended-Shamir ceremony
from ADR-025 §"Seal / unseal" and §"Vault configuration — phase 1". It runs
**after** the Composition has installed the Vault server (Helm `Release =
deployed`) and **before** any consumer onboarding.

> This is a **runbook, not a script.** It handles unseal key shares and the root
> token — material that must never touch stdout logs, shell history, unencrypted
> files, or a second automated system. Every secret is PGP-encrypted end to end.
> Do not wrap these steps in CI.

## Bootstrap-without-Vault-recursion invariant (check first)

ADR-025 blocker: *Vault and VSO must never be required to establish the
credentials or trust material needed to bootstrap Vault itself.* Everything this
ceremony depends on has a **Vault-independent origin**:

| Dependency | Origin | Vault-independent? |
|---|---|---|
| TLS trust for the endpoint | cert-manager internal CA (`ok-shared-internal-ca`, `reachability.yaml`) | ✅ not issued by Vault |
| Unseal key custody | offline PGP keypairs, one per custodian | ✅ human custody, offline |
| Initial root token | PGP-encrypted to a dedicated custodian key | ✅ ceremony-only, revoked |
| Kubernetes API access to the pods | operator kubeconfig | ✅ |

If any of these were sourced from Vault/VSO, **stop** — the invariant is broken.

## Decisions to confirm before you start (do not default silently)

- **Shamir shares / threshold.** Recommendation: **5 shares, threshold 3**, five
  distinct custodians, no custodian holding two shares. Records as versioned
  production config (not a chart default).
- **Root-token custodian.** One dedicated PGP key holds the (encrypted) root
  token; it is used once and revoked.
- **Break-glass admin.** A minimal `userpass` break-glass identity with a strong
  password held in the same offline custody — used only when automation is
  unavailable.
- **Automation identity is reconciler-dependent.** The Day-1/2 config reconciler
  is **still open (ADR-025 item 13)**. This ceremony creates the *least-privilege
  policy skeleton* only; the automation **auth method** (AppRole vs. Kubernetes
  auth vs. short-lived token) is created when item 13 is decided. Do not mint a
  broad standing credential here.

## Preflight

```bash
# The CA is the Vault-independent trust root (from cert-manager). Export it once.
kubectl -n vault get secret ok-shared-internal-ca \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ok-shared-ca.crt

export VAULT_ADDR=https://127.0.0.1:8200
export VAULT_CACERT=$PWD/ok-shared-ca.crt

# Talk to a specific pod (not the ingress) — bootstrap is intra-cluster/supervised.
kubectl -n vault port-forward pod/vault-0 8200:8200 &   # PF_PID=$!

vault status   # expect: Initialized=false, Sealed=true
```

Gate check — expect `TLSReady PASS`, `Initialized FAIL`, `Unsealed FAIL`:

```bash
VAULT_ADDR=$VAULT_ADDR VAULT_CACERT=$VAULT_CACERT VAULT_SNI=vault.ok-shared.internal \
  bash ../gate/vault-health-gate.sh
```

## Custody prep

Each custodian generates a GPG keypair **on their own machine** and sends only
the **public** key:

```bash
gpg --quick-generate-key "custodian-N <n@openkubes>" default default 2y
gpg --armor --export "custodian-N <n@openkubes>" > custN.asc     # public only
```

Collect `cust1.asc … cust5.asc` and `root.asc` (root-token custodian). The
private keys never leave their owners.

## Step 1 — initialize (once, PGP-encrypted output)

```bash
vault operator init \
  -key-shares=5 -key-threshold=3 \
  -pgp-keys="cust1.asc,cust2.asc,cust3.asc,cust4.asc,cust5.asc" \
  -root-token-pgp-key="root.asc" \
  -format=json > vault-init.json
```

`vault-init.json` now contains **only PGP-encrypted** material: each
`unseal_keys_b64[i]` is encrypted to `custN.asc`, and `root_token` is encrypted
to `root.asc`. Distribute each encrypted share to its custodian, hand the
encrypted root token to the root custodian, then **do not keep `vault-init.json`
centrally** (see Wipe). A custodian decrypts only their own share:

```bash
# on custodian N's machine:
jq -r '.unseal_keys_b64[<N-1>]' vault-init.json | base64 -d | gpg -dq   # → their share
```

## Step 2 — unseal all three Raft voters

Unseal `vault-0` first (it becomes the Raft leader); `vault-1` and `vault-2`
join and must each be unsealed too. Each node needs **threshold = 3** distinct
custodian shares.

```bash
# vault-0 (already port-forwarded): 3 custodians each run once with their share
vault operator unseal    # prompts for a share — repeat for 3 different custodians

# then per remaining node:
kubectl -n vault port-forward pod/vault-1 8200:8200   # new terminal
vault operator unseal    # x3 custodians
kubectl -n vault port-forward pod/vault-2 8200:8200
vault operator unseal    # x3 custodians
```

Gate check — expect `Initialized PASS`, `Unsealed PASS`, and (with a token, next
step) `RaftHealthy PASS` at `voters=3/3`.

## Step 3 — audit, admin, automation skeleton, then revoke root

Log in with the (decrypted) root token **only for these steps**:

```bash
export VAULT_TOKEN="$(jq -r '.root_token' vault-init.json | base64 -d | gpg -dq)"
```

```bash
# 3a. Audit device (AuditEnabled). auditStorage PVC is mounted at /vault/audit.
vault audit enable file file_path=/vault/audit/audit.log

# 3b. Break-glass admin (userpass) + admin policy.
vault auth enable userpass
vault policy write ok-admin - <<'HCL'
path "*" { capabilities = ["create","read","update","delete","list","sudo"] }
HCL
vault write auth/userpass/users/breakglass \
  password="$(gpg -dq breakglass-password.asc)" policies="ok-admin"

# 3c. Automation policy SKELETON only (least privilege). The auth METHOD is
#     created when the Day-1/2 config reconciler is chosen (ADR-025 item 13).
vault policy write ok-config-automation - <<'HCL'
# scoped to what the config reconciler needs: auth mounts, policies, roles.
path "sys/auth"            { capabilities = ["read"] }
path "sys/auth/*"          { capabilities = ["create","update","delete","sudo"] }
path "sys/policies/acl/*"  { capabilities = ["create","read","update","delete","list"] }
path "auth/kubernetes/*"   { capabilities = ["create","read","update","delete","list"] }
HCL

# 3d. Revoke the root token — EVIDENCED.
vault token lookup -format=json > root-before-revoke.json   # accessor + policies
vault token revoke -self
unset VAULT_TOKEN
vault login -method=userpass username=breakglass 2>/dev/null || true  # verify root is gone
```

Record `root-before-revoke.json` (accessor, not the token) as revocation
evidence, then encrypt/store it in custody.

Gate check (authenticated, break-glass token) — expect `Initialized`,
`Unsealed`, `RaftHealthy`, `TLSReady`, `AuditEnabled` all **PASS**; `Configured`
`SKIP` until the config reconciler lands:

```bash
VAULT_TOKEN=<breakglass-token> VAULT_EXPECT_REPLICAS=3 \
  bash ../gate/vault-health-gate.sh --require-auth  # RaftHealthy/AuditEnabled must PASS
```

## Step 4 — wipe

```bash
shred -u vault-init.json root-before-revoke.json 2>/dev/null || rm -f vault-init.json root-before-revoke.json
unset VAULT_TOKEN
kill %1 2>/dev/null    # stop port-forward(s)
history -c            # bootstrap ran in an interactive shell; clear it
```

Nothing unencrypted remains: shares live only in each custodian's GPG keyring;
the root token is revoked; `ok-shared-ca.crt` is public (the CA cert, not a key).

## Step 5 — cold-restart rehearsal (ADR-025 acceptance item 12)

Prove the manual-recovery SLO and that every Raft voter returns:

```bash
date +%s > /tmp/restart-start
kubectl -n vault delete pod vault-0 vault-1 vault-2   # full restart
# custodians re-unseal all three nodes (threshold 3 each), as in Step 2
# when the gate goes green:
echo "recovery seconds: $(( $(date +%s) - $(cat /tmp/restart-start) ))"
```

Record: achieved recovery time, that the 3-of-5 threshold was met under the
operating model, and that `voters=3/3` with a single leader (gate `RaftHealthy
PASS`). This is the recorded acceptance evidence for items 4 and 12.

## What is NOT done here (next on the acceptance path)

- **Backup/restore.** Raft snapshot (`vault operator raft snapshot save`) stored
  outside the cluster's failure domain, plus a **restore rehearsal** — ADR-025
  items 4 & 11.
- **Config reconciler + per-cluster auth mounts** — ADR-025 item 13; unblocks the
  gate's `Configured` state and consumer onboarding (OK-109 Part 2).
- **Vault outage test** (ADR-018) — item 8.
