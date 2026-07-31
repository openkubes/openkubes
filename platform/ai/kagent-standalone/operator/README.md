# Controlled write drill

This optional operating drill uses the upstream kagent Kubernetes tool image.
It does not build or publish a custom image.

The default `kagent-tools` ServiceAccount remains cluster-readable and
read-only. A second tool server runs as `kagent-lab-tools` and receives a
namespace Role for ConfigMaps and Deployments in `kagent-lab`. This is enough
to repair the standalone CrashLoop and ImagePull fixtures without granting
cluster-admin, Secret, RBAC, or cross-namespace access.

Select the profile during the cluster-specific installation from `ok-cluster`:

```bash
export OLLAMA_URL='<private endpoint>'
make -C ok-kagent/kagent install ACCESS_MODE=read-write
```

The installer applies these public manifests and verifies the RBAC boundary.
For an installation with a nonstandard repository layout, also pass
`OPENKUBES_DIR=/path/to/openkubes`.

Audit the ServiceAccount independently before invoking the Agent:

```bash
SUBJECT='system:serviceaccount:kagent-lab:kagent-lab-tools'
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i patch deployments \
  -n kagent-lab --as="$SUBJECT"
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i patch deployments \
  -n default --as="$SUBJECT"
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" auth can-i get secrets \
  -n kagent-lab --as="$SUBJECT"
```

Expected results are `yes`, `no`, and `no`.

All three write tools require approval. Inspect the proposed namespace,
resource kind, name, and patch or manifest before approving. Suitable UI tests
for `cluster-operator-gated` are:

- `Diagnose the crashloop Deployment in kagent-lab and propose the smallest fix.`
- `Diagnose the imagepull Deployment in kagent-lab and propose the smallest fix.`
- `Create a ConfigMap named approval-test in kagent-lab with test=approved.`

Reject the first proposed write once to verify that the Agent stops without
retrying. On a second run, approve only when the target is `kagent-lab` and the
resource is a ConfigMap or Deployment.

Switch back to the read-only profile after the drill:

```bash
export OLLAMA_URL='<private endpoint>'
make -C ok-kagent/kagent install ACCESS_MODE=read-only
```
