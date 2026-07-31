# Standalone kagent lab assets (OK-129)

Reusable manifests for the dedicated standalone evaluation. This directory is
independent of the OK-92 Profile A contract and does not change that profile.

Prerequisites:

- kagent 0.9.12 installed in namespace `kagent`
- `default-model-config` points at the private Ollama `gpt-oss:20b` endpoint
- the `kagent-tool-server` deployment is configured read-only with no Secret
  access in the cluster-specific `ok-cluster` values

```bash
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" apply -k \
  platform/ai/kagent-standalone
```

The `kagent-lab` fixtures are intentionally unhealthy. They provide stable,
known failure modes for grounded diagnosis tests.

The Agent is hardened with the numeric UID/GID 1001 used by the v0.9.12 Python
image; the same manifest also runs with the Go image. Kubernetes reads are
executed by the separate `kagent-tools` ServiceAccount, so enforce and audit
read-only access on that identity rather than relying on the Agent prompt.

`operator/` is the optional `read-write` profile. It uses the upstream tool
image with a second ServiceAccount that can change only ConfigMaps and
Deployments in `kagent-lab`; all writes require human approval. It is
intentionally not part of the default Kustomization. The cluster-specific
installer in `ok-cluster/ok-kagent/kagent` adds or removes this profile through
`ACCESS_MODE=read-write` or `ACCESS_MODE=read-only`.
