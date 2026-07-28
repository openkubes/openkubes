# Vault break-glass ceremony — datacenter secret backend (OK-110, ADR-Platform-025)

**Supervised, rare, evidenced.** Break-glass is the *last-resort* administrative path
into the central Vault on ok-shared when the normal paths are unavailable. It is **not**
the day-to-day admin path and **not** the automation path.

Three distinct identities — do not conflate them:

| Identity | Who/what | When |
|---|---|---|
| `provider-vault` (Kubernetes auth, short-lived) | the Crossplane Day-1/2 config reconciler on ok-mgmt | all routine auth-mount / policy / role config |
| `userpass/breakglass` (policy `ok-admin`) | a human operator | manual admin when automation is unavailable |
| **root** (generated, then revoked) | a human ceremony, 3-of-5 shares | only to *re-establish* break-glass, or an action only root can do |

Governing invariant (ADR-025): **there is no standing root token.** Root is minted from
the Shamir shares for one action and revoked immediately after. The initial init root token
was already revoked; `~/vault-init.json.gpg` holds only the (revoked) initial token + the
five Shamir shares — do **not** decrypt it except to supply shares in Tier B below.

**Custody reality (Phase 1, Accepted Risk AR-025-1):** the five shares are GPG-encrypted
under *single-operator* custody — no true separation of duties yet. This runbook documents
the intended 3-of-5 multi-custodian ceremony; until the PGP-custody rekey lands, one
operator holds all shares and the "three custodians" steps collapse to one person. Record
that fact honestly in the evidence.

---

## Tier A — normal break-glass (password known)

Use this first. No shares, no root.

UI: **Method** = Userpass, **Username** = `breakglass`, **Password** = the break-glass
password set at bootstrap/re-seed.

CLI (in-pod, TLS via the pod's own `VAULT_ADDR`/`VAULT_CACERT` — prompts for the password,
never on argv):

```bash
kubectl -n vault exec -it vault-0 -- vault login -method=userpass username=breakglass
```

Verify the identity carries `ok-admin`:

```bash
kubectl -n vault exec -it vault-0 -- vault token lookup -format=json | jq -r '.data.policies'
```

If login succeeds, you are done — do the admin action, then let the token expire. Go no
further.

---

## Tier B — full ceremony (break-glass password lost, or a root-only action)

Runs `generate-root` from 3 of 5 shares, performs exactly **one** action, and revokes root.

### 0. Roles & preconditions

- **Ceremony lead** — runs the commands, records evidence. Does **not** hold a share alone
  in the target multi-custodian model.
- **Three share-holders** — each supplies one Shamir share (Phase 1: the single operator,
  per AR-025-1).
- Vault reachable and **unsealed** (`vault status` → `Sealed=false`); if sealed, unseal
  first (`runbooks/vault-outage-recovery.md`).
- State the **reason** for break-glass before starting — it goes in the evidence.

### 1. Start generate-root — capture the nonce + OTP

```bash
kubectl -n vault exec -it vault-0 -- vault operator generate-root -init
# records: Nonce, and a one-time OTP (OTP is safe to hold briefly; it only decodes the token)
```

### 2. Each share-holder submits one share (×3, threshold 3)

```bash
kubectl -n vault exec -it vault-0 -- vault operator generate-root -nonce=<nonce>
# prompts for a share — a DIFFERENT holder each time; shares NEVER go on argv or into logs
```

The third submission prints an **encoded** root token.

### 3. Decode the root token with the OTP

```bash
kubectl -n vault exec -it vault-0 -- vault operator generate-root \
  -decode=<encoded-token> -otp=<otp>
# -> the working root token. Hold it in memory only; do not echo it into a file or history.
```

### 4. Do exactly ONE action

Log in with the decoded root (prompted, not on argv) and perform only the action that
justified break-glass. The common case — reset the break-glass password (`password=-`
reads stdin, so it never appears in argv / `ps` / shell tracing, per the ADR-024 credential
invariant):

```bash
kubectl -n vault exec -it vault-0 -- sh -c \
  'VAULT_TOKEN=<root> vault write auth/userpass/users/breakglass password=- policies=ok-admin'
# type the new password at the prompt; store it in the same offline custody as the shares
```

### 5. Audit evidence

The `file/` audit device is enabled, so every action is already logged. Record in the
crit-appropriate acceptance/evidence note: **who** ran it, **when**, the **reason**, the
**one action** taken, the root token's **accessor** (before revoke), and a pointer to the
audit-log lines.

```bash
kubectl -n vault exec -it vault-0 -- sh -c 'VAULT_TOKEN=<root> vault token lookup -format=json' \
  | jq '{accessor:.data.accessor, policies:.data.policies, ttl:.data.ttl}'
```

### 6. Functional test — the new break-glass works

```bash
kubectl -n vault exec -it vault-0 -- vault login -method=userpass username=breakglass
kubectl -n vault exec -it vault-0 -- vault token lookup -format=json | jq -r '.data.policies'  # ok-admin
```

### 7. Revoke root — and PROVE it is gone

```bash
kubectl -n vault exec -it vault-0 -- sh -c 'VAULT_TOKEN=<root> vault token revoke -self'
# verify: this MUST now fail (permission denied / invalid token)
kubectl -n vault exec -it vault-0 -- sh -c 'VAULT_TOKEN=<root> vault token lookup' || \
  echo "OK: root token no longer valid"
```

The ceremony is complete only when step 7 shows the root token is **invalid**. No standing
root may remain.

---

## Hygiene (non-negotiable)

- Shares, OTP, root token, break-glass password: **never** on argv, in shell history, in
  logs, or in a committed file. Use prompts / `password=-` / in-memory only.
- Do not decrypt `~/vault-init.json.gpg` except to read shares for step 2; re-secure it after.
- One action per ceremony. If a second action is needed, that is a second ceremony with its
  own evidence.
- Prefer Tier A. Reach Tier B only when the break-glass password is genuinely lost or the
  action truly requires root.

## Follow-up

Retiring **AR-025-1** (single-operator custody) via a PGP-custody rekey to distinct
custodian keys turns the "three share-holders" steps into real separation of duties. Until
then this runbook is correct but the custody is concentrated — state it in every evidence
record.
