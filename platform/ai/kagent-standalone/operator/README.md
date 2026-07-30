# Controlled write drill

This optional operating drill uses the upstream kagent Kubernetes tool image.
It does not build or publish a custom image.

The default `kagent-tools` ServiceAccount remains cluster-readable and
read-only. A second tool server runs as `kagent-lab-tools` and receives only a
namespace Role for ConfigMaps in `kagent-lab`.

Install the second tool server from `ok-cluster` first:

```bash
make -C ok-kagent/kagent operator-tools-install
```

Then apply the scoped RBAC, tool registration, and gated Agent:

```bash
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" apply -k \
  platform/ai/kagent-standalone/operator
```

Audit the ServiceAccount before invoking the Agent:

```bash
SUBJECT='system:serviceaccount:kagent-lab:kagent-lab-tools'
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i create configmaps \
  -n kagent-lab --as="$SUBJECT"
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i create configmaps \
  -n default --as="$SUBJECT"
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i get secrets \
  -n kagent-lab --as="$SUBJECT"
```

Expected results are `yes`, `no`, and `no`.

All three write tools require approval. Use only disposable ConfigMaps and
remove the Agent and separate tool server after the drill:

```bash
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" delete -k \
  platform/ai/kagent-standalone/operator
make -C ok-kagent/kagent operator-tools-uninstall
```
