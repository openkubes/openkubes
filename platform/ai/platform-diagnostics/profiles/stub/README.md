# Profile B — deterministic non-LLM conformance stub

Profile B is the backend-swap proof for ADR-Platform-021. It implements the same
three HTTP operations as Profile A using only deterministic Python code. It has
no LLM, agent runtime, Kubernetes client, kubeconfig, or credentials.

It is a **test provider**, not a production diagnostics implementation. The
responses are synthetic fixtures whose only purpose is to exercise the public
contract and consumer behavior independently of a concrete backend.

## Run

```bash
python3 server.py --port 8080
```

Or build the dependency-free container:

```bash
docker build -t openkubes/platform-diagnostics-profile-b:dev .
docker run --rm -p 8080:8080 openkubes/platform-diagnostics-profile-b:dev
```

The default RBAC manifest grants the ServiceAccount **no Kubernetes API
permissions** (`rules: []`). This is stricter than the Phase-1 maximum of
`get`/`list`/`watch` and makes the absence of a hidden cluster dependency
explicit.

## Contract suite

From `platform/ai/platform-diagnostics`:

```bash
make verify
```

The suite launches this server on an ephemeral loopback port. To run the exact
same tests against another provider:

```bash
DIAGNOSTICS_BASE_URL=http://127.0.0.1:8080 \
DIAGNOSTICS_RBAC_PATH=profiles/kagent/rbac.yaml \
make verify
```
