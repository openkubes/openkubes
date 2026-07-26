# ADR-Platform-025 — Criterion 14 Singleton-Enforcement Acceptance Record

**Scope:** ADR-Platform-025 acceptance **criterion 14** — enforce the `VaultInstance`
singleton invariant so that no second production `VaultInstance` can exist while
`ok-shared-vault` is active. An internal XRD (no `claimNames`) does not enforce this by itself.

**Status:** **Enforced — verified (2026-07-26)** on ok-mgmt (k8s v1.34.1). Policy applied,
conformance PASS, negative test PASS (a second `VaultInstance` is denied at admission). Evidence
below.

---

## Mechanism (decided)

A Kubernetes-native **`ValidatingAdmissionPolicy`** on ok-mgmt **pins the name** of the
`VaultInstance` composite to `ok-shared-vault`. `VaultInstance` is cluster-scoped, so object
names are globally unique; permitting only that one name bounds the population to **at most one**.
This enforces the singleton with single-object admission evaluation — no fragile cross-object
counting, and **no external policy controller** (Kyverno/Gatekeeper), so no new platform
capability is introduced (consistent with ADR-025 §Implementation & placement).

- **fail-closed:** `failurePolicy: Fail`, binding `validationActions: [Deny]`.
- **CREATE-only:** a cluster-scoped object cannot be renamed, so no UPDATE rule is required.
- **Relocation path:** to move the singleton, change the pinned name in the policy (versioned,
  three-way-reviewed) — the invariant is code, not convention.

Artifacts:

| Item | Path |
|---|---|
| Policy + Binding | `platform/secrets/vault/crossplane/singleton-admission.yaml` |
| Conformance (read-only) | `platform/secrets/vault/conformance/singleton-conformance.sh` |
| Negative test (server dry-run) | `platform/secrets/vault/conformance/singleton-negative-test.sh` |
| Static invariants | `platform/secrets/vault/Makefile` → `make validate` |

## Static verification (already green, off-cluster)

- `make validate` → `OK: singleton-admission invariants (fail-closed VAP, CREATE on vaultinstances, name-pinned, Deny binding)`
- `shellcheck` clean on both conformance scripts.
- CEL expressions compile (validation + messageExpression).

## Live evidence (fill on ok-mgmt)

**Preflight — confirm the API supports VAP:**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml kubectl version -o json | jq -r .serverVersion.gitVersion
# >= v1.30 → admissionregistration.k8s.io/v1 (as shipped).
```
Server version: **v1.34.1** (ok-mgmt, Talos) → `admissionregistration.k8s.io/v1` used as-is.

**1. Apply the policy:**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml kubectl apply -f platform/secrets/vault/crossplane/singleton-admission.yaml
```
Output:
```
validatingadmissionpolicy.admissionregistration.k8s.io/vaultinstance-singleton.platform.openkubes.ai created
validatingadmissionpolicybinding.admissionregistration.k8s.io/vaultinstance-singleton.platform.openkubes.ai created
```

**2. Conformance (read-only, must PASS):**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml make -C platform/secrets/vault singleton-conformance
```
Output:
```
PASS  ValidatingAdmissionPolicy '...' present and fail-closed (failurePolicy: Fail)
PASS  policy pins the singleton name in a validation expression
PASS  Binding references policy '...'
PASS  Binding enforces validationActions: [Deny]
PASS  VaultInstance population = 1 (<= 1, singleton bound holds)
RESULT: PASS — singleton invariant is enforced (crit. 14)
```

**3. Negative test (must PASS = a 2nd VaultInstance is DENIED):**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml make -C platform/secrets/vault singleton-negative-test
```
Output:
```
PASS  decoy 'ok-shared-vault-neg-test' denied by the singleton policy.
      server: Error from server (Forbidden): ... vaultinstances.platform.openkubes.ai
      "ok-shared-vault-neg-test" is forbidden: ValidatingAdmissionPolicy
      'vaultinstance-singleton.platform.openkubes.ai' ... denied request:
      ADR-025 singleton (criterion 14): the only permitted VaultInstance is
      ok-shared-vault. A second production VaultInstance (ok-shared-vault-neg-test)
      is forbidden — Vault is a bounded singleton, not a self-service capability.
PASS  allowed name 'ok-shared-vault' passes admission (dry-run OK).
RESULT: PASS — a second VaultInstance is rejected; the singleton holds (crit. 14)
```

## Sign-off

- Three-way review: **waived by Arash (2026-07-26)** for this enforcement change.
- Criterion 14 **verified on ok-mgmt 2026-07-26**; to be ticked in the OK-110 thread.

## Notes / follow-ups

- The policy is fail-closed: if VAP is unavailable on ok-mgmt, `VaultInstance` CREATE is denied
  rather than silently admitted — deliberate (matches OK-110 mutating-step discipline).
- GitOps parity: if `singleton-admission.yaml` is later reconciled by Argo/Flux, admission still
  runs on the reconciler's apply, so the guard holds regardless of the apply path.
