# Vault consumer-cluster onboarding (ADR-Platform-025, Category A)

**Repeatable, reviewable, no break-glass.** Gives one consumer cluster its own Vault
Kubernetes auth mount so the Vault Secrets Operator running *on that cluster* can
materialise a Secret from central Vault on ok-shared.

Manifest: `crossplane/examples/consumer-vaultconfig.template.yaml`
Realised instance to compare against: `crossplane/examples/ok-robotics-vaultconfig.yaml`

Identities involved — see `runbooks/vault-breakglass-ceremony.md` for the full table. Nothing
here needs `userpass/breakglass`; if you find yourself reaching for it, stop and re-read §Known gap.

---

## Precondition — registration does NOT create the auth mount

ADR-013 cluster registration (`make register-cluster` in ok-cluster) applies a kubeconfig Secret
and a provider-helm `ProviderConfig`. It contains **no Vault logic**. Onboarding a consumer to
Vault is a **separate, explicit step** — the `VaultConfig` XR below, applied by hand.

Verify before assuming a cluster is already onboarded:

```bash
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml get vaultconfigs.platform.openkubes.ai -A
# a cluster absent from this list has NO auth mount, however long it has been registered
```

> Older wording in ADR-Platform-025 criterion 7 and in the Confluence onboarding page describes
> registration as reconciling the auth mount/policy/role. That is the intended end state, not
> current behaviour. Treat this runbook as the operative procedure.

## 1. Mint the reviewer JWT (on the consumer cluster)

Vault validates consumer ServiceAccount tokens by calling `TokenReview` on the consumer's API
server, authenticated as a dedicated reviewer identity.

```bash
KO=~/.kube/<cluster>.yaml
kubectl --kubeconfig "$KO" -n kube-system create sa vault-token-reviewer
kubectl --kubeconfig "$KO" create clusterrolebinding vault-token-reviewer-auth-delegator \
  --clusterrole=system:auth-delegator \
  --serviceaccount=kube-system:vault-token-reviewer
```

The JWT must **not** expire, so request a legacy long-lived token Secret rather than using
`kubectl create token` — a bounded token silently stops working later and the mount then fails
authentication for reasons that look nothing like an expired credential:

```bash
kubectl --kubeconfig "$KO" apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: vault-token-reviewer
  namespace: kube-system
  annotations:
    kubernetes.io/service-account.name: vault-token-reviewer
type: kubernetes.io/service-account-token
EOF
```

Verify the identity can actually perform the review — do this now, not after Vault fails:

```bash
kubectl --kubeconfig "$KO" auth can-i create tokenreviews.authentication.k8s.io \
  --as=system:serviceaccount:kube-system:vault-token-reviewer          # -> yes
kubectl --kubeconfig "$KO" auth can-i create subjectaccessreviews.authorization.k8s.io \
  --as=system:serviceaccount:kube-system:vault-token-reviewer          # -> yes
```

## 2. Collect the endpoint and CA

```bash
kubectl --kubeconfig "$KO" config view --minify -o jsonpath='{.clusters[0].cluster.server}'
kubectl --kubeconfig "$KO" config view --minify --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > /tmp/<cluster>-ca.crt
```

`kubernetesHost` must be reachable **from the Vault pods on ok-shared**, not merely from your
workstation. The CA is a public certificate; inline is fine.

## 3. Place the reviewer JWT on ok-mgmt

Credential invariant (ADR-Platform-024): the JWT must not appear in argv, shell history, tracing,
logs, or a world-readable file. Use a `0600` file and `--from-file`, never `--from-literal`.

```bash
umask 077; TMP="$(mktemp -d)"
kubectl --kubeconfig "$KO" -n kube-system get secret vault-token-reviewer \
  -o jsonpath='{.data.token}' | base64 -d > "$TMP/token"

kubectl --kubeconfig ~/.kube/ok-mgmt.yaml -n crossplane-system \
  create secret generic <cluster>-reviewer-jwt --from-file=token="$TMP/token" \
  --dry-run=client -o yaml | kubectl --kubeconfig ~/.kube/ok-mgmt.yaml apply -f -
rm -rf "$TMP"
```

## 4. Render and apply the VaultConfig XR

Render from the template (explicit envsubst variable list — see its header), splice the PEM into
`caCert`, then **dry-run against the live XRD before applying**:

```bash
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml apply --dry-run=server -f <cluster>-vaultconfig.yaml
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml apply -f <cluster>-vaultconfig.yaml
```

## 5. Verify Vault actually reconciled

```bash
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml get vaultconfig <cluster> \
  -o jsonpath='{range .status.conditions[*]}{.type}={.status} {end}'   # Synced=True Ready=True
# and in-pod, that the mount/role/policy exist:
kubectl --kubeconfig ~/.kube/ok-shared.yaml -n vault exec vault-0 -- \
  vault read auth/kubernetes/<cluster>/role/<role-name>
```

Synced=True means Crossplane accepted the XR. It is **not** evidence a workload can log in —
that requires a real VSO sync (step 6).

## 6. Consumer-side prerequisites

In the workload namespace on the consumer cluster: the ServiceAccount named in the role, and a
Secret holding the Vault endpoint CA so VSO trusts it (`caCertSecretRef`, key **`ca.crt`**):

```bash
kubectl --kubeconfig ~/.kube/ok-shared.yaml -n vault get secret ok-shared-internal-ca \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > /tmp/vault-ca.crt
kubectl --kubeconfig "$KO" -n <workload-ns> create secret generic vault-ca \
  --from-file=ca.crt=/tmp/vault-ca.crt
```

## Known gap — seeding the credential itself

This runbook grants a consumer **read** access to its own KV subtree. It does **not** put the
credential *into* Vault, and today **no identity can**:

- the `VaultConfig` composition emits `capabilities = ["read"]` on every declared path, so the
  XR cannot grant write by construction;
- `ok-config-automation` — the provider-vault identity that performs routine auth-mount, policy
  and role configuration — has **no KV-data paths** at all;
- `userpass/breakglass` is scoped to manual admin when automation is unavailable, and is
  explicitly not the automation path. A first-time credential seed is neither an emergency nor
  an automation outage, so it is out of scope for break-glass.

Until a scoped per-cluster KV write exists (**OK-115**), the first write to
`<kv-mount>/<cluster>/obs/<name>` has no sanctioned route. Every new consumer onboarding hits
this, so it is a platform gap rather than a per-cluster inconvenience.

## Hygiene

- The reviewer JWT is a credential: `0600` files, `--from-file`, never argv or history.
- The cluster CA and the Vault CA are public certificates — no special handling.
- One `VaultConfig` per cluster; the auth mount name is derived from `clusterName`, so a typo
  creates a second, silently unused mount rather than failing.
- Removing a consumer: delete the XR (which removes mount/policy/role), then the reviewer-JWT
  Secret on ok-mgmt, then the consumer-side SA and CRB.
