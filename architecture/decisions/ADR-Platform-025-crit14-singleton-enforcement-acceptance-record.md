# ADR-Platform-025 — Criterion 14 Singleton-Enforcement Acceptance Record

**Scope:** ADR-Platform-025 acceptance **criterion 14** — enforce the `VaultInstance`
singleton invariant so that no second production `VaultInstance` can exist while
`ok-shared-vault` is active. An internal XRD (no `claimNames`) does not enforce this by itself.

**Status:** Mechanism committed; **live evidence PENDING** the apply + negative-test run on
ok-mgmt (fill the placeholders below, then flip Status to *Enforced — verified*).

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
kubectl --context ok-mgmt version -o json | jq -r .serverVersion.gitVersion
# >= v1.30 → admissionregistration.k8s.io/v1 (as shipped). v1.28–1.29 → switch to v1beta1.
```
Server version: `__________`

**1. Apply the policy:**

```bash
kubectl --context ok-mgmt apply -f platform/secrets/vault/crossplane/singleton-admission.yaml
```
Output:
```
(paste: validatingadmissionpolicy... created / validatingadmissionpolicybinding... created)
```

**2. Conformance (read-only, must PASS):**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml make -C platform/secrets/vault singleton-conformance
```
Output:
```
(paste — expect: RESULT: PASS — singleton invariant is enforced (crit. 14))
```

**3. Negative test (must PASS = a 2nd VaultInstance is DENIED):**

```bash
KUBECONFIG=~/.kube/ok-mgmt.yaml make -C platform/secrets/vault singleton-negative-test
```
Output:
```
(paste — expect: PASS decoy '...neg-test' denied by the singleton policy;
 PASS allowed name 'ok-shared-vault' passes admission;
 RESULT: PASS — a second VaultInstance is rejected; the singleton holds (crit. 14))
```

## Sign-off

- Three-way review (Arash / Claude / GPT): `__________`
- Criterion 14 closed in ADR-025 / OK-110 review thread on: `__________`

## Notes / follow-ups

- The policy is fail-closed: if VAP is unavailable on ok-mgmt, `VaultInstance` CREATE is denied
  rather than silently admitted — deliberate (matches OK-110 mutating-step discipline).
- GitOps parity: if `singleton-admission.yaml` is later reconciled by Argo/Flux, admission still
  runs on the reconciler's apply, so the guard holds regardless of the apply path.
