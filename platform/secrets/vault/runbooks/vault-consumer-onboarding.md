# Vault consumer-cluster onboarding (ADR-Platform-025, Category A)

**Repeatable and reviewable.** Gives one consumer cluster its own Vault Kubernetes auth mount so
the Vault Secrets Operator running *on that cluster* can materialise a Secret from central Vault
on ok-shared.

Manifest: `crossplane/examples/consumer-vaultconfig.template.yaml`
Realised instance to compare against: `crossplane/examples/ok-robotics-vaultconfig.yaml`

Identities involved — see `runbooks/vault-breakglass-ceremony.md` for the full table. Steps 1–6
need **no** break-glass. Scoped owner seeding is the target routine mechanism; supervised
break-glass remains the fallback until the updated XRD/Composition and each cluster's `seedRoles`
entry are applied and the OK-115 negative test passes.

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

> ADR-Platform-025 (criterion 7 and three other places) and the Confluence onboarding page both
> said registration reconciled the auth mount/policy/role. **Both were corrected on 2026-07-28** —
> they now describe the explicit XR step. Registration auto-reconciling the mount remains a
> legitimate future enhancement (out of scope for criterion 7, whose claim is the VSO-before-Helm
> ordering, not how the credential reached Vault).

## 1. Mint the reviewer JWT (on the consumer cluster)

Vault validates consumer ServiceAccount tokens by calling `TokenReview` on the consumer's API
server, authenticated as a dedicated reviewer identity.

```bash
KO=~/.kube/<cluster>.yaml
kubectl --kubeconfig "$KO" -n kube-system create sa vault-reviewer
kubectl --kubeconfig "$KO" create clusterrolebinding vault-reviewer-tr \
  --clusterrole=system:auth-delegator \
  --serviceaccount=kube-system:vault-reviewer
```

The JWT must **not** expire, so request a legacy long-lived token Secret rather than using
`kubectl create token` — a bounded token silently stops working later and the mount then fails
authentication for reasons that look nothing like an expired credential:

```bash
kubectl --kubeconfig "$KO" apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: vault-reviewer-token
  namespace: kube-system
  annotations:
    kubernetes.io/service-account.name: vault-reviewer
type: kubernetes.io/service-account-token
EOF
```

Verify the identity can actually perform the review — do this now, not after Vault fails:

```bash
kubectl --kubeconfig "$KO" auth can-i create tokenreviews.authentication.k8s.io \
  --as=system:serviceaccount:kube-system:vault-reviewer          # -> yes
kubectl --kubeconfig "$KO" auth can-i create subjectaccessreviews.authorization.k8s.io \
  --as=system:serviceaccount:kube-system:vault-reviewer          # -> yes
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
kubectl --kubeconfig "$KO" -n kube-system get secret vault-reviewer-token \
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

## Seeding the credential itself — scoped owner identity (OK-115)

Workload `roles` remain read-only. Seeding is a separate identity declared through `seedRoles`;
it does not add write capability to the VSO workload ServiceAccount. A seed entry accepts only:

- a DNS-label role `name` and `appName`;
- one dedicated ServiceAccount name and namespace; and
- an explicit 60–600 second token TTL.

There is no caller-supplied path or capability. The Composition derives:

```bash
policy: okvc-<cluster>-<app>-seed
path:   secret/data/<cluster>/<app>/*
caps:   create, update
```

KV v2 `vault kv put` calls only the `data/` endpoint, so metadata access is not required. The
seeder is intentionally write-only: it cannot read back a credential, list metadata, delete,
undelete, destroy, or metadata-delete it. Read-after-write would widen the separation-of-duties
boundary only to make verification convenient, so successful API writes are the evidence.

The role sets `tokenNoDefaultPolicy: true`; the token therefore receives only its derived seed
policy, not Vault's `default` self-inspection policy. Its TTL, max TTL, and explicit max TTL are
the same short value.

Before applying the Composition revision, confirm the field exists on the **installed** pinned
provider CRD. This is a deployment gate, not something repository-local validation can prove:

```bash
kubectl --kubeconfig ~/.kube/ok-mgmt.yaml get \
  crd/authbackendroles.kubernetes.vault.upbound.io -o json |
  jq -e '
    .spec.versions[]
    | select(.name == "v1alpha1")
    | .schema.openAPIV3Schema.properties.spec.properties.forProvider.properties
      .tokenNoDefaultPolicy.type == "boolean"
  '
```

Do not promote the Composition if this returns non-zero; without the field, define and review the
`default` policy's explicit `sys/*` exceptions instead of silently claiming literal denial.

### 7. Create the dedicated owner ServiceAccount and TokenRequest RBAC

Create a ServiceAccount that is used only for seeding. It **must not** be the ServiceAccount in
`roles[]` that VSO uses. Kubernetes RBAC decides which owner group may mint a bounded token for it:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vault-seed-obs
  namespace: ok-observability
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vault-seed-obs-token
  namespace: ok-observability
rules:
  - apiGroups: [""]
    resources: ["serviceaccounts/token"]
    resourceNames: ["vault-seed-obs"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: vault-seed-obs-token
  namespace: ok-observability
subjects:
  - kind: Group
    name: <cluster-owner-group>
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: vault-seed-obs-token
  apiGroup: rbac.authorization.k8s.io
```

Add the matching XR entry and apply it through the reviewed VaultConfig workflow:

```yaml
seedRoles:
  - name: obs-seed
    appName: obs
    serviceAccountName: vault-seed-obs
    serviceAccountNamespace: ok-observability
    ttlSeconds: 600
```

This repository change alone is **not deployment evidence**. Routine self-service starts only
after the XRD and Composition revision are applied/promoted, the consumer XR reconciles, and the
real owner-identity test below passes.

### 8. Run the owner-identity acceptance test, then seed

The test mints the ServiceAccount token, logs into the existing per-cluster Kubernetes auth mount,
creates then updates a unique probe key, checks the exact policy/short TTL, and executes the
negative API operations required by OK-115. It never asks for break-glass:

```bash
bash tooling/ok115-scoped-seed-test.sh \
  --consumer-kubeconfig ~/.kube/<cluster>.yaml \
  --shared-kubeconfig ~/.kube/ok-shared.yaml \
  --cluster <cluster> --app obs --role obs-seed \
  --service-account vault-seed-obs --namespace ok-observability
```

The identity cannot delete its positive probe. The script prints the exact `vault kv metadata
delete` command for a separately authorised cleanup step; do not add delete to the seed policy.

For the real credential, keep values out of argv. Prepare a `0600` HCL/JSON payload or use a
stdin-capable wrapper, mint a bounded ServiceAccount token, log in at
`auth/kubernetes/<cluster>/login`, and write only:

```text
secret/<cluster>/<app>/<credential-name>
```

## Fallback until scoped seeding is deployed and proven

If the updated XRD/Composition/consumer XR has not been deployed and the negative test has not
passed, use the supervised Tier-A break-glass ceremony in
`runbooks/vault-breakglass-ceremony.md`. This is a deployment fallback, not the routine end state.
Record that break-glass was used and why the scoped path was not yet available.

## Hygiene

- The reviewer JWT is a credential: `0600` files, `--from-file`, never argv or history.
- The cluster CA and the Vault CA are public certificates — no special handling.
- One `VaultConfig` per cluster; the auth mount name is derived from `clusterName`, so a typo
  creates a second, silently unused mount rather than failing.
- A seed role binds one dedicated SA and derives its KV path from `clusterName` + `appName`.
  Never reuse a workload/VSO SA for seeding.
- Removing a consumer: delete the XR (which removes mount/policy/role), then the reviewer-JWT
  Secret on ok-mgmt, then the consumer-side SA and CRB.
