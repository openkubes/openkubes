# OK Console

The OpenKubes Platform Console is the contract-centred, evidence-backed UI for
viewing platform state and rehearsing guarded operations. The repository is
available at [openkubes/ok-console](https://github.com/openkubes/ok-console).

## Local Kind installation

This is a development and evaluation installation. It creates a disposable
[Kind](https://kind.sigs.k8s.io/) cluster on your workstation; it is not a
production deployment and does not connect to `ok-shared`.

### Prerequisites

- Docker
- Kind
- kubectl
- Node.js 20 or newer
- pnpm 9 or newer

Verify the tools are available:

```bash
docker --version
kind version
kubectl version --client
node --version
pnpm --version
```

### Run the complete local proof

```bash
git clone https://github.com/openkubes/ok-console.git
cd ok-console
pnpm install
pnpm verify:kind
```

The verifier builds the current revision, creates the bounded
`ok-console-ok169` cluster, loads the image, applies the local-only overlay,
checks the secure runtime and health endpoints, and removes the cluster when
the proof finishes. It refuses to modify an existing cluster with the same
name.

The local overlay deliberately uses deterministic fixture data and prototype
authentication. It does not contain production credentials, OIDC, PostgreSQL,
or a live observed-state connection.

### Keep the cluster for visual inspection

```bash
OK_CONSOLE_KEEP_CLUSTER=true pnpm verify:kind
kubectl --context kind-ok-console-ok169 \
  --namespace openkubes-console \
  port-forward service/ok-console 8787:8787
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787) in your browser.

When finished, remove the retained cluster explicitly:

```bash
kind delete cluster --name ok-console-ok169
```

### What this proves — and what it does not

The proof validates the local image, Kubernetes rollout, non-root/read-only
runtime settings, liveness/readiness, current-Pod port-forwarding and the
Console routes. It is an evidence-backed development gate, not a production
readiness approval. Production and shared-cluster deployment require the
reviewed overlays, secrets, network policies, identity provider and release
evidence described in the repository's
[Kubernetes deployment runbook](https://github.com/openkubes/ok-console/blob/main/deploy/kubernetes/README.md).

For implementation details and the evolving evidence record, see the
[OK-169 local proof](https://github.com/openkubes/ok-console/tree/main/docs/evidence/ok-169)
and [OK-200 verification evidence](https://github.com/openkubes/ok-console/tree/main/docs/evidence/ok-200).
