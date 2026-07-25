#!/usr/bin/env bash
# Finish Phase 4 (OK-110, ADR-025 item 13): apply the first real VaultConfig
# for ok-robotics. Run this once the ok-mgmt API is reachable again.
#
# Preconditions already done (this session):
#   - ok-robotics: reviewer SA kube-system/vault-reviewer (+ system:auth-delegator),
#     token secret kube-system/vault-reviewer-token, workload SA observability/sa-obs.
#   - Reachability ok-shared(Vault) -> ok-robotics API 192.168.100.204:6443 : OPEN.
#   - provider-vault healthy on ok-mgmt; kubernetes/ok-mgmt auth mount seeded.
# This script re-derives the reviewer JWT + CA from ok-robotics (idempotent),
# creates the reviewer-JWT secret on ok-mgmt, and applies the VaultConfig XR.
set -euo pipefail

RMF_KUBECONFIG="${RMF_KUBECONFIG:-$HOME/.kube/ok-robotics.yaml}"
MGMT_KUBECONFIG="${MGMT_KUBECONFIG:-$HOME/.kube/ok-mgmt.yaml}"

echo "==> deriving ok-robotics reviewer JWT + CA"
RMF_JWT=$(kubectl --kubeconfig "$RMF_KUBECONFIG" -n kube-system \
  get secret vault-reviewer-token -o jsonpath='{.data.token}' | base64 -d)
kubectl --kubeconfig "$RMF_KUBECONFIG" config view --minify --raw \
  -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > /tmp/ok-robotics-ca.crt
echo "    jwt len=${#RMF_JWT}  ca bytes=$(wc -c < /tmp/ok-robotics-ca.crt)"

echo "==> ok-mgmt API preflight"
kubectl --kubeconfig "$MGMT_KUBECONFIG" get --raw='/readyz' >/dev/null

echo "==> creating reviewer-JWT secret on ok-mgmt"
kubectl --kubeconfig "$MGMT_KUBECONFIG" -n crossplane-system \
  create secret generic ok-robotics-reviewer-jwt --from-literal=token="$RMF_JWT" \
  --dry-run=client -o yaml | kubectl --kubeconfig "$MGMT_KUBECONFIG" apply -f -

echo "==> applying ok-robotics VaultConfig"
kubectl --kubeconfig "$MGMT_KUBECONFIG" apply -f - <<EOF
apiVersion: platform.openkubes.ai/v1alpha1
kind: VaultConfig
metadata:
  name: ok-robotics
spec:
  clusterName: ok-robotics
  kubernetesHost: https://192.168.100.204:6443
  reviewerJwtSecretRef:
    namespace: crossplane-system
    name: ok-robotics-reviewer-jwt
    key: token
  caCert: |
$(sed 's/^/    /' /tmp/ok-robotics-ca.crt)
  roles:
    - name: sa-obs
      serviceAccountNames: [sa-obs]
      serviceAccountNamespaces: [observability]
      policyPaths:
        - secret/data/ok-robotics/obs/*
      ttlSeconds: 1200
EOF

cat <<'NOTE'

==> watch the reconcile:
  kubectl get vaultconfig ok-robotics
  kubectl get managed | grep -iE 'backend|authbackend|policy'

==> verify in Vault (auth/kubernetes/ok-robotics mount + role/policy):
  export KUBECONFIG=~/.kube/ok-shared.yaml
  BGT=$(kubectl -n vault exec vault-0 -- env VAULT_BG="$BG" \
    sh -c 'vault login -no-store -token-only -method=userpass username=breakglass password="$VAULT_BG"')
  kubectl -n vault exec vault-0 -- env VAULT_TOKEN="$BGT" vault auth list | grep ok-robotics
  kubectl -n vault exec vault-0 -- env VAULT_TOKEN="$BGT" vault policy read ok-robotics-sa-obs

==> health gate (from repo root):
  VAULT_ADDR=https://127.0.0.1:8200 VAULT_CACERT=$PWD/ok-shared-ca.crt \
    VAULT_SNI=vault.ok-shared.internal VAULT_TOKEN="$BGT" \
    VAULT_EXPECT_REPLICAS=3 VAULT_EXPECT_AUTH_MOUNTS=ok-robotics \
    bash platform/secrets/vault/gate/vault-health-gate.sh --require-auth
NOTE
