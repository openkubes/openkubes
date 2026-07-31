# Standalone kagent lab assets (OK-129)

Reusable manifests for the dedicated standalone evaluation. This directory is
independent of the OK-92 Profile A contract and does not change that profile.

Prerequisites:

- kagent 0.9.12 installed in namespace `kagent`
- `default-model-config` points at the private Ollama `gpt-oss:20b` endpoint
- the built-in tool server is pinned read-only with no Secret access — that comes
  from the access profile (see below), not from a hand-edited value

```bash
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" apply -k \
  platform/ai/kagent-standalone
```

## Layout

| Path | Contents |
|---|---|
| `agents/cluster-inspector.yaml` | the read-only diagnosis Agent — always deployed |
| `fixtures.yaml` | `kagent-lab` namespace plus three fixtures: `crashloop`, `imagepull`, and a `healthy` control |
| `kustomization.yaml` | the read path: fixtures + inspector |
| `access/` | the access profile renderer — **the permission model lives here** |

The `crashloop` and `imagepull` fixtures are intentionally unhealthy: they give
stable, known failure modes for grounded diagnosis tests. The `healthy` fixture is
the control — an agent that calls everything broken must fail the matrix, and it
cannot fail without a known-good workload to be wrong about.

## Permissions come from one config

There are no static write manifests in this directory any more. Read-only versus
read-write, cluster-wide versus a maintained namespace list, gated versus not —
all of it is generated from a single `access-config.yaml` by
[`access/render-access.py`](access/README.md).

```bash
# what would this profile grant?
make -C <ok-cluster>/ok-kagent/kagent access-summary

# apply it, then prove it against the API server
make -C <ok-cluster>/ok-kagent/kagent install
make -C <ok-cluster>/ok-kagent/kagent verify-access
```

Start at [`access/README.md`](access/README.md) — it explains where the boundary
actually is, which is the part that matters and the part that is easy to get
wrong.

## Two facts worth repeating

**The Agent is not the identity.** Kubernetes calls are executed by the *tool
server's* ServiceAccount, not by the Agent pod. Enforce and audit read-only on
that identity (`kubectl auth can-i --as=system:serviceaccount:kagent:kagent-tools`),
never on the Agent's prompt.

**The Agent is hardened for the shipped images.** The manifests set numeric
UID/GID 1001, which the v0.9.12 Python image requires under `runAsNonRoot`
(Kubernetes cannot verify a named user). The same manifest runs on the Go image,
which is what these agents select explicitly.
