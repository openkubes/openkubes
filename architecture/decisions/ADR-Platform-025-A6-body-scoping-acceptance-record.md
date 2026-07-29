# ADR-Platform-025 — A6 Body-Scoping Acceptance Record (criterion 13, least-privilege scope)

**Scope:** the A6 amendment's least-privilege claim for the Day-1/2 config reconciler
(`ok-config-automation` / `provider-vault`). A6 narrowed the policy to **reserved prefixes**
(`sys/policies/acl/okvc-*`, `sys/auth/kubernetes/*`, `auth/kubernetes/*`, `auth/token/create`)
with an explicit **deny** on its own seed mount. This record answers the question A6's own text
left open: *is that boundary least-privilege, or only name-scoped?*

**Status:** **Resolved — 2026-07-29.** Live probe confirms the boundary is **name-scoped, not
content-scoped**. Consumer read-only is a property of the composition template, not of the policy
boundary. Recorded as **Accepted Risk AR-025-2**; the least-privilege wording in ADR-025
criterion 13 is qualified to *"bounded Vault-config administrator within `okvc-*`"*.

Tool: `platform/secrets/vault/tooling/a6-policy-test.sh` (body-scoping section, hardened in
openkubes #34 / #39 / #40 — it distinguishes an explicit `permission denied` / `child policies
must be subset of parent` from a non-permission failure, so a collapsed error cannot read as a
clean bill; cf. OK-124).

---

## What was tested

Holding only a token that carries the narrowed `ok-config-automation` policy, attempt to escalate
a consumer from read to **write** on KV — the capability A6 is supposed to preclude:

1. **Author** an `okvc-`-named policy whose **body** grants `create`/`update` on a KV path.
2. **Confer** it directly (`vault token create -policy=<okvc-…>`).
3. **Confer** it via an `AuthBackendRole`'s `token_policies` on a throwaway auth mount.

All temp objects (`okvc-a6-escalation-probe`, `kubernetes/a6-esc-probe`, …) are created under the
break-glass token, asserted absent first, and cleaned up. Fail-closed.

## Result — FINDING (name-scoped, not content-scoped)

| Step | Outcome |
|---|---|
| (1) write an `okvc-` policy with a WRITE body | **accepted** — `sys/policies/acl/okvc-*` scopes the policy NAME; nothing scopes its CONTENTS |
| (2) direct token mint carrying it | **denied** — `child policies must be subset of parent` (the direct route is closed by the parent-subset rule, not by A6) |
| (3) confer it via an `AuthBackendRole` `token_policies` | **succeeded** — the role carries the write policy; a bound ServiceAccount logging in there would receive KV **write** |

The decisive step is (3): the reconciler identity **can** grant a consumer KV write within
`okvc-*`, by authoring a write-bodied `okvc-` policy and binding it from an auth role. Read-only is
enforced only because the `VaultConfig` composition emits `capabilities=["read"]` — a **template**
choice, not a boundary the policy imposes.

## Decision — Accepted Risk AR-025-2 (option B), not a Vault-side control (option A) now

Per the pre-authored clause in ADR-025 §"Least-privilege scope", the honest wording is **bounded
Vault-config administrator within `okvc-*`**, with the residual recorded as **AR-025-2**. Option A
(a Vault-side content control that scopes policy *contents*) was considered and **deferred**:

- Native content-scoping is **Sentinel = Vault Enterprise**; OpenKubes runs Community. A
  Community control would be a bespoke admission controller over HCL policy bodies — its own spike,
  brittle, no native mechanism.
- **No forcing consumer:** exactly one reconciler (`provider-vault`), platform-controlled, single
  reconcile loop. Anyone who could exploit this already holds cluster-admin on ok-mgmt and controls
  the Composition. Per "no structure without a forcing consumer", A is premature.

### AR-025-2 (residual, accepted for Phase 1)

`provider-vault` can confer **any KV capability within `okvc-*`** by authoring a write-bodied
policy and binding it from an auth role. Accepted because:

- **Single authoring path** — the `VaultConfig` Composition, which hardcodes `capabilities=["read"]`
  and is three-way-reviewed; there is no other way an `okvc-` policy is produced in normal operation.
- **Cluster-admin-gated** — driving `provider-vault` (editing the Composition or applying arbitrary
  `VaultConfig` XRs) requires cluster-admin on ok-mgmt.
- **Audited** — the Vault `file/` audit device logs every policy write.

### Re-evaluation trigger → do option A when any of:

- a **second / less-trusted** `provider-vault` consumer appears;
- `VaultConfig` authoring is **opened beyond platform operators**;
- a move to **Vault Enterprise** (Sentinel makes content-scoping cheap).

## Sign-off

Evidence produced by the party running the probe; **acceptance is the human reviewer's**. Relates:
OK-110, OK-124 (the failure-mode-collapse defect whose discipline hardened this probe), ADR-025
(criterion 13, §Least-privilege scope), and the A6 ownership-migration record.
