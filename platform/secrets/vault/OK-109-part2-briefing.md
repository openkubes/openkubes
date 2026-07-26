# OK-109 Part 2 — VSO VaultStaticSecret consumer wiring (re-entry briefing)

> **STATUS: DONE (2026-07-26).** Implemented and verified on ok-robotics — VSO
> `VaultStaticSecret` produces `ok-observability-credentials`, OK-79 contract-test
> gate green, no chart change. Committed manifests + full how-to live in the
> **ok-observability** repo: `implementations/vault-secrets-operator/`.
>
> **Namespace correction:** the observability stack runs in namespace
> **`ok-observability`**, not `observability`. Everywhere below that says the
> `observability` namespace, read `ok-observability` (the Vault role was rebound
> accordingly via the VaultConfig XR). Kept as-is for history.

**Goal:** replace the "create Secret from provider-values file" step with a **Vault
Secrets Operator (VSO)** `VaultStaticSecret` that syncs from the central Vault on
ok-shared and produces the **same** `ok-observability-credentials` Secret.
**No chart change** — Grafana (`admin.existingSecret`), OpenSearch (`secretKeyRef`),
Fluent Bit (`${OPENSEARCH_PASSWORD}`) already consume that named Secret; only *who
populates it* changes. Tool decided = VSO (ADR-025). Was blocked by OK-110 → now unblocked.

Consumer target for the first run: **ok-robotics** (its auth mount already exists).

---

## Already in place (done in the OK-110 session)

- **Central Vault** on ok-shared, ns `vault`, Vault 1.20.1, Raft HA 3/3, unsealed.
- **Reachability (interim):** NodePort `30443` on an ok-shared node IP (`10.44.0.38`)
  + SNI `vault.ok-shared.internal`; TLS trust via CA secret `vault/ok-shared-internal-ca`
  (key `tls.crt`). (Canonical `:443` host-LB fix is a separate follow-up.)
- **ok-robotics auth mount (reconciled via provider-vault):**
  - mount `auth/kubernetes/ok-robotics`
  - role `sa-obs` → bound SA `observability/sa-obs`, tokenPolicies `[ok-robotics-sa-obs]`, ttl 20m
  - policy `ok-robotics-sa-obs` = `path "secret/data/ok-robotics/obs/*" { read }`
- **KV v2** engine enabled at `secret/` on Vault.
- Break-glass admin (`userpass/breakglass`) + unseal shares in custody
  (`~/vault-init.json.gpg`). Root revoked.

---

## Values to collect at re-entry (the only real unknowns)

1. **Secret shape** — what keys does `ok-observability-credentials` need? Read the
   ok-observability chart wiring: Grafana `admin.existingSecret` (key names for
   admin user/password), OpenSearch `secretKeyRef`, Fluent Bit `OPENSEARCH_PASSWORD`.
   → defines the KV payload + the VaultStaticSecret field mapping.
   Start points (ok-observability repo): chart values + `tests/contract-test.sh`.
2. **The actual credential values** (grafana admin pw, opensearch pw) to seed into Vault.
3. **ok-robotics → Vault reachability** confirm: `nc 10.44.0.38 30443` from an
   ok-robotics pod (same fabric as the ok-shared test — expected OK).
4. **VSO auth SA decision:** VaultStaticSecret's VaultAuth must present a token for
   an SA bound in the role. Role `sa-obs` is bound to `observability/sa-obs` → run
   VSO's VaultAuth with `serviceAccount: sa-obs` in ns `observability`
   (simplest — reuses the existing role). Alternative: add a VSO-dedicated role.

---

## Steps

1. **Seed the credentials into Vault** (break-glass), at the policy-scoped path:
   ```
   vault kv put secret/ok-robotics/obs/observability-credentials \
     admin-user=admin admin-password=<pw> opensearch-password=<pw> ...
   ```
   (exact keys per value #1).

2. **CA + host resolution on ok-robotics** for VSO to trust/reach Vault:
   - copy `ok-shared-internal-ca` (tls.crt) into ok-robotics as a ConfigMap/Secret
     VSO's VaultConnection can reference (`caCertSecretRef` / `tlsServerName`).
   - VSO pod must resolve `vault.ok-shared.internal` → node IP: `hostAliases` on the
     VSO deployment (Helm `extraArgs`/values) or use the node IP with `tlsServerName`.

3. **Install VSO** on ok-robotics (Helm `hashicorp/vault-secrets-operator`).

4. **VSO CRs** in ns `observability`:
   - `VaultConnection` → address `https://vault.ok-shared.internal:30443`, CA ref,
     `tlsServerName: vault.ok-shared.internal`.
   - `VaultAuth` → method `kubernetes`, `mount: kubernetes/ok-robotics`,
     `role: sa-obs`, `serviceAccount: sa-obs`.
   - `VaultStaticSecret` → `mount: secret`, `type: kv-v2`,
     `path: ok-robotics/obs/observability-credentials`,
     `destination.name: ok-observability-credentials` (+ field/template mapping to
     the exact keys the charts expect).

5. **Verify:**
   - `kubectl -n observability get secret ok-observability-credentials` materializes
     with the right keys.
   - observability stack still green; run `ok-observability/tests/contract-test.sh`
     (the OK-79 gate) — must stay green with no chart change.
   - health gate: `VAULT_EXPECT_AUTH_MOUNTS=ok-robotics` already PASSes.

6. **Record findings** as an OK-109 comment (existing evidence pattern); tick the
   Part-2 acceptance box.

---

## Notes / gotchas from the OK-110 session (likely to recur)

- Reviewer-JWT model is Category A (same-SDN); ok-robotics API `192.168.100.204:6443`.
- Provider observes auth backends via `sys/mounts/auth/*` — already granted.
- Interim NodePort + node-IP `hostAliases` pin is fragile; the host-LB follow-up
  (ok-mgmt-lb pattern) would also stabilise VSO's path.
- Assignee on OK-109 is Suchit — coordinate (this is also his guided code-study pass).
