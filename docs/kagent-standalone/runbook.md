# kagent Standalone Runbook

Operational procedures for the OK-129 lab cluster. Copy-pasteable, ordered, no
prior kagent knowledge assumed. If a step here does not work as written, the
runbook is wrong — fix it here rather than explaining it verbally. That is an
acceptance criterion of OK-129.

Conventions in this document:

- `$KUBECONFIG` always points at the **lab** cluster. Never at `ok-ai`,
  `ok-shared`, `ok-robotics`, `ok-mgmt`.
- Values written as `<FILL>` are environment-specific and must be resolved once
  and then recorded in this file.
- `VERIFY` marks something to confirm against the installed release before it is
  used in customer-facing material.

---

## 0. Prerequisites

| Item | Value |
|---|---|
| Cluster | `ok-kagent` (lab, disposable) |
| Kubeconfig | `~/.kube/ok-kagent.yaml` |
| Namespace | `kagent` |
| kagent version | `<FILL>` — pin it; upstream latest documented is `0.9.9` |
| Charts | `oci://ghcr.io/kagent-dev/kagent/helm/{kagent-crds,kagent}` |
| Local LLM | Ollama at `<FILL>`, model with **function calling** support |
| Cloud LLM | `<FILL>` provider + API key in a Secret |
| Tools | `kubectl`, `helm`, optionally the `kagent` CLI |

```bash
export CLUSTER=ok-kagent
export KUBECONFIG=$HOME/.kube/$CLUSTER.yaml
export NS=kagent
export KAGENT_VERSION=<FILL>
kubectl get nodes
```

### Guardrails for this lab

1. Write-capable agents exist **only** on this cluster.
2. No other cluster's kubeconfig is ever mounted or referenced here.
3. The cluster is disposable. If an agent breaks it, rebuild — do not repair by
   hand, and record what happened (it is evidence, see `evidence-protocol.md`).
4. No personal data, no external exposure.

---

## 1. Create the cluster

Scaffold with the ok-cluster tooling on the feature branch:

```bash
cd <ok-cluster>
git checkout -b feat/kagent-standalone
CLUSTER=ok-kagent TYPE=talos WORKERS=<FILL> make -f Makefile render CLUSTER=ok-kagent   # VERIFY target name
```

Before rendering, pick an LB-IP block that does **not** collide. The allocation
plan (ADR-Platform-010) gives guest clusters disjoint 5-IP blocks from
`192.168.100.210` upward. Check what is taken:

```bash
grep -rh "lbPool" <ok-cluster>/*/cluster-config.yaml
```

Record the chosen block here: `lbPool: <FILL>`.

Then follow the existing cluster bring-up procedure in the ok-cluster `README.md`
/ `new-cluster.sh`. When the cluster answers `kubectl get nodes`, continue.

> **Rebuild drill.** OK-129 requires one full from-zero rebuild in under 60
> minutes, documented. Do it *early*, while the environment is still simple —
> not at the end when you need it to work.

---

## 2. Install kagent

Two paths. Do both once, then pick one for the documented customer path.

### 2.1 Helm (the path we should recommend — reviewable, GitOps-able)

CRDs first (they include the kmcp subchart):

```bash
helm upgrade --install kagent-crds \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version "$KAGENT_VERSION" \
  --namespace "$NS" --create-namespace
```

Then kagent with the local model as default provider:

```bash
helm upgrade --install kagent \
  oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$KAGENT_VERSION" \
  --namespace "$NS" \
  --set providers.default=ollama \
  --set-string providers.ollama.model=<FILL> \
  --set-string providers.ollama.config.host=<FILL> \
  --set-string providers.ollama.config.options.num_ctx=32768
```

Prefer a values file over `--set` once the configuration stabilises — it is
reviewable and belongs in Git:

```yaml
# kagent-values.yaml
providers:
  default: ollama
  ollama:
    model: <FILL>
    config:
      host: <FILL>
      options:
        num_ctx: "32768"
rbac:
  namespaces: []          # [] = cluster-scoped. Decide deliberately.
controller:
  replicas: 1
  auth:
    mode: unsecure        # no authentication. Change before anyone else uses it.
database:
  postgres:
    bundled:
      enabled: true       # demo-grade; postgres:18, no pgvector
```

### 2.2 CLI (the path for a fast demo)

```bash
curl https://raw.githubusercontent.com/kagent-dev/kagent/refs/heads/main/scripts/get-kagent | bash
# or: brew install kagent

kagent install --profile minimal     # or --profile demo for the sample agents
kagent dashboard
```

`--profile demo` preloads sample agents and MCP tools. Useful for a first look,
misleading for evaluation — the demo agents are not ours and carry kagent's
default permissions. Use `minimal` for anything we intend to reason about.

### 2.3 Verify the install

```bash
kubectl -n "$NS" get pods
kubectl -n "$NS" get svc
kubectl api-resources | grep -Ei 'kagent|mcp'
kubectl -n "$NS" get modelconfigs,agents,remotemcpservers
kubectl wait --for=condition=ready pod --all -n "$NS" --timeout=180s
```

Record the actual CRD list — this is where you confirm whether a legacy
`ToolServer` kind is present (upstream removed it in 0.6) and which API versions
are served:

```bash
kubectl explain agent --api-version=kagent.dev/v1alpha2 | head -30
kubectl explain modelconfig --api-version=kagent.dev/v1alpha2 | head -30
kubectl explain remotemcpserver --api-version=kagent.dev/v1alpha2 | head -30
```

Open the UI. `svc/kagent-ui` on 8080 is what upstream's installation guide and
examples use; the architecture page still shows `svc/kagent 8001:80`, which
looks stale — confirm from `get svc` rather than trusting either:

```bash
kubectl -n "$NS" get svc
kubectl -n "$NS" port-forward svc/kagent-ui 8080:8080
# CLI alternative: `kagent dashboard` (prints http://localhost:8082)
```

Also resolve the runtime default once, since upstream is contradictory (concepts
page says Python, CRD reference says `go`) — then set `runtime` explicitly on
every agent so it stops mattering:

```bash
kubectl explain agent.spec.declarative.runtime
```

Controller logs, for everything that follows:

```bash
kubectl -n "$NS" logs deploy/kagent-controller -f --tail=100
```

---

## 3. Configure models

### 3.1 Local (Ollama)

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: local-ollama
  namespace: kagent
spec:
  provider: Ollama
  model: <FILL>              # MUST support function calling
  ollama:
    host: <FILL>
    options:
      num_ctx: "32768"
```

Confirm the model can actually call tools before blaming kagent for anything:

```bash
curl -s <OLLAMA_HOST>/api/tags | jq -r '.models[].name'
```

### 3.2 Cloud reference

```bash
kubectl -n "$NS" create secret generic kagent-cloud \
  --from-literal=<KEY_NAME>=<FILL>
```

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: cloud-reference
  namespace: kagent
spec:
  provider: <FILL>           # Anthropic | OpenAI | AzureOpenAI | ...
  model: <FILL>
  apiKeySecret: kagent-cloud
  apiKeySecretKey: <KEY_NAME>
```

```bash
kubectl -n "$NS" get modelconfigs
```

Secret rotation needs no rollout: kagent restarts agents that reference a
changed Secret automatically.

---

## 4. Build your first agent

```yaml
# agents/cluster-inspector.yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: cluster-inspector
  namespace: kagent
spec:
  description: Read-only inspector for this cluster. Explains what it sees.
  type: Declarative
  declarative:
    runtime: go
    modelConfig: local-ollama
    systemMessage: |
      You are a read-only Kubernetes inspector for a single cluster.

      Rules:
      - Read before you conclude. Never state a resource state you have not
        retrieved with a tool in this conversation.
      - When you cannot determine something, say so and name the tool that
        would answer it.
      - Report findings as: observation, then interpretation, clearly separated.
      - Never include secret values in an answer, even if a tool returns them.
    tools:
      - type: McpServer
        mcpServer:
          name: kagent-tool-server
          kind: RemoteMCPServer
          apiGroup: kagent.dev
          toolNames:
            - k8s_get_resources
            - k8s_describe_resource
            - k8s_get_events
            - k8s_get_pod_logs
            - k8s_get_resource_yaml
```

```bash
kubectl apply -f agents/cluster-inspector.yaml
kubectl -n "$NS" get agent cluster-inspector -o wide
kubectl -n "$NS" describe agent cluster-inspector | tail -30   # conditions tell you why it is not Accepted
```

Test in the UI with a question whose answer you already know, e.g. *"Which pods
in namespace kagent are not Ready, and why?"*

Then switch the same agent to `modelConfig: cloud-reference`, ask the identical
question, and record both answers side by side. This one comparison separates
framework problems from model problems for the rest of the project.

### Runtime comparison

```bash
# measure startup for both runtimes with the same agent
kubectl -n "$NS" patch agent cluster-inspector --type=merge \
  -p '{"spec":{"declarative":{"runtime":"python"}}}'
kubectl -n "$NS" get pods -w
```

Record measured startup times. Do not quote upstream's ~2 s / ~15 s at a
customer without your own numbers.

---

## 5. Add write capability (lab only)

Two agents, deliberately: one gated, one not. The contrast is the deliverable.

### 5.1 Gated agent — HITL

```yaml
# agents/cluster-operator-gated.yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: cluster-operator-gated
  namespace: kagent
spec:
  description: Repairs workloads in this cluster, with human approval for writes.
  type: Declarative
  declarative:
    runtime: go
    modelConfig: local-ollama
    systemMessage: |
      You are a Kubernetes operations agent.

      Before any change: state what you will change, why, and what you expect
      to happen. Prefer the smallest reversible action.
      If the request is ambiguous, use ask_user instead of guessing.
      After a change, verify the result with a read tool.
    tools:
      - type: McpServer
        mcpServer:
          name: kagent-tool-server
          kind: RemoteMCPServer
          apiGroup: kagent.dev
          toolNames:
            - k8s_get_resources
            - k8s_describe_resource
            - k8s_get_events
            - k8s_get_pod_logs
            - k8s_apply_manifest
            - k8s_patch_resource
            - k8s_delete_resource
          requireApproval:
            - k8s_apply_manifest
            - k8s_patch_resource
            - k8s_delete_resource
```

Exercise all three HITL paths in the UI and capture each:

1. **Read** — no approval prompt appears.
2. **Approve** — payload is shown, you approve, the change lands.
3. **Reject with reason** — the agent receives the reason and *changes its
   approach*. If it simply retries the same call, that is a finding.
4. **`ask_user`** — give it a deliberately vague request ("set up a namespace for
   my app") and confirm it asks instead of inventing.

### 5.2 Ungated agent — blast radius

Same tools, **no** `requireApproval`. Name it so nobody mistakes it:

```bash
sed -e 's/cluster-operator-gated/cluster-operator-UNGATED-lab-only/' \
    -e '/requireApproval:/,+3d' \
    agents/cluster-operator-gated.yaml > agents/cluster-operator-ungated.yaml
kubectl apply -f agents/cluster-operator-ungated.yaml
```

Then create a broken fixture and let it act:

```bash
kubectl create ns kagent-lab
kubectl -n kagent-lab create deployment crashloop \
  --image=busybox:1.36 -- /bin/sh -c 'exit 1'
kubectl -n kagent-lab create deployment imagepull \
  --image=ghcr.io/kubernauts/does-not-exist:0.0.0
```

Record: what did it change, was the change correct, was it reversible, and what
would have stopped it if it had been wrong. **The failure case is the valuable
one** — an agent that deletes the wrong thing is the result the customer needs to
see, not an embarrassment.

### 5.3 Audit the real permission boundary

The prompt is not the boundary. Check the executing identity:

```bash
# which ServiceAccount actually runs the tool calls
kubectl -n "$NS" get deploy -o custom-columns=NAME:.metadata.name,SA:.spec.template.spec.serviceAccountName

SA=<FILL>
kubectl auth can-i --as=system:serviceaccount:$NS:$SA delete deployments -A
kubectl auth can-i --as=system:serviceaccount:$NS:$SA get secrets -A
kubectl auth can-i --as=system:serviceaccount:$NS:$SA '*' '*' -A
```

If a read-only agent's SA can delete deployments, the agent is delete-capable.
Fix it with a per-agent ServiceAccount and a scoped Role, then re-run the checks.

---

## 6. Tools and MCP

### 6.1 Inspect what is available

```bash
kubectl -n "$NS" get remotemcpservers
kubectl -n "$NS" get remotemcpserver kagent-tool-server -o yaml
kubectl -n "$NS" get mcpservers -A            # kmcp-managed
```

### 6.2 Own tool server with kmcp

```bash
kmcp --help                    # VERIFY CLI name/flags for the installed version
# scaffold -> implement -> build -> push -> deploy as MCPServer
```

Then reference it:

```yaml
tools:
  - type: McpServer
    mcpServer:
      name: <our-tool-server>
      kind: MCPServer
      toolNames:
        - <our_tool>
```

Aim for one genuinely useful tool rather than a toy — that is what proves the
extension point to a customer.

### 6.3 Cross-namespace reference

```yaml
tools:
  - type: McpServer
    mcpServer:
      name: kagent-tool-server
      namespace: tools          # separate field; "ns/name" strings fail since 0.6
      kind: RemoteMCPServer
      toolNames: [k8s_get_resources]
```

---

## 7. Multi-agent

One fronting agent, narrow specialists behind it.

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: ops-frontdesk
  namespace: kagent
spec:
  description: Single entry point. Routes to specialists.
  type: Declarative
  declarative:
    runtime: go
    modelConfig: local-ollama
    systemMessage: |
      You are the entry point for cluster questions. Decide which specialist
      can answer, delegate, and present the result. Do not answer from your own
      knowledge; if no specialist fits, say so.
    tools:
      - type: Agent
        agent:
          name: cluster-inspector
      - type: Agent
        agent:
          name: logs-agent
```

Prove delegation actually happened — controller logs and the specialist pod's
logs, not just a plausible answer:

```bash
kubectl -n "$NS" logs deploy/kagent-controller --tail=200 | grep -i -E 'a2a|delegat|agent'
```

A2A agents are also reachable as MCP servers at `/mcp` on the A2A port (default
8083) — worth demonstrating with an external MCP client.

---

## 8. Memory and long conversations

Memory needs **pgvector**, which the bundled `postgres:18` lacks. Point kagent
at an external PostgreSQL first:

```yaml
database:
  postgres:
    urlFile: /var/secrets/db-url
    vectorEnabled: true
    bundled:
      enabled: false
controller:
  volumes:
    - name: db-secret
      secret:
        secretName: kagent-db-url
  volumeMounts:
    - name: db-secret
      mountPath: /var/secrets
      readOnly: true
```

```bash
kubectl -n "$NS" create secret generic kagent-db-url --from-file=db-url=<FILL>
helm upgrade kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$KAGENT_VERSION" -n "$NS" -f kagent-values.yaml
```

Then enable memory on one agent. Memory is switched on by referencing a
`ModelConfig` whose **embedding** provider produces the vectors — it does not
have to be the agent's main LLM:

```yaml
spec:
  type: Declarative
  declarative:
    modelConfig: local-ollama
    memory:
      modelConfig: <FILL>        # embedding ModelConfig
      ttlDays: 30                # defaults to 15 when unset
```

Confirm `save_memory` / `load_memory` / `prefetch_memory` appear and are used
(extraction happens every 5th user message). Record the upstream limits while
you are here — no per-memory deletion, no cross-agent sharing, not pluggable —
because they are data-protection answers, not footnotes.

Compaction, for small context windows:

```yaml
context:
  compaction:
    compactionInterval: 5
    overlapSize: 2
    eventRetentionSize: 20
    tokenThreshold: 24000
    summarizer:
      modelConfig: local-ollama    # without this, compacted events are DISCARDED
```

---

## 9. Day-2

### 9.1 High availability

```bash
helm upgrade kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$KAGENT_VERSION" -n "$NS" --reuse-values \
  --set controller.replicas=3

kubectl -n "$NS" get leases            # leader election is automatic above 1 replica
kubectl -n "$NS" delete pod <leader>   # confirm failover
```

### 9.2 Upgrade

```bash
# 1. back up the database FIRST
kubectl -n "$NS" exec deploy/<postgres> -- pg_dump -U kagent kagent > kagent-$(date +%F).sql

# 2. read the release notes for every version you cross
# 3. remove values removed upstream (e.g. rbac.clusterScoped — the chart now fails on it)
# 4. upgrade CRDs, then the app
helm upgrade --install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version "$NEW_VERSION" -n "$NS"
helm upgrade --install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version "$NEW_VERSION" -n "$NS" -f kagent-values.yaml

# 5. verify migrations
kubectl -n "$NS" logs deploy/kagent-controller | grep -i migrat
```

Minimum prior version for 0.9 is 0.8.0. Migrations roll back automatically on
failure and are guarded by an advisory lock across replicas.

### 9.3 Authentication

Default is `controller.auth.mode: unsecure` — **no authentication**. Do not leave
it there once anyone else can reach the UI.

```yaml
controller:
  auth:
    mode: proxy
oauth2-proxy:
  enabled: true
  extraEnv:
    - name: OIDC_ISSUER_URL
      value: <FILL>
    - name: OIDC_REDIRECT_URL
      value: <FILL>
```

Remember: this gives authentication only. Upstream states access control is not
yet implemented, so assume any authenticated user can reach any agent — and test
it, since upstream does not describe the resulting visibility.

### 9.4 Observability

Enable tracing and prompt auditing per the upstream Observability docs, then
answer one question concretely: *given an agent action, where does an auditor
read what happened?* Write the answer down — in a write-capable setup it is the
first question a customer's security team asks.

---

## 10. Troubleshooting

| Symptom | First check | Likely cause |
|---|---|---|
| Agent stuck not Accepted | `kubectl describe agent <name>` conditions | Referenced `ModelConfig`, `RemoteMCPServer` or sub-agent does not exist yet |
| Agent answers but never calls tools | Model capability | Model lacks function calling, or the tool is not in `toolNames` |
| Tool calls fail with connection errors | `kubectl get remotemcpserver -o yaml`, tool server pod logs | Wrong URL/port/transport. Since 0.9, MCP connection errors are returned to the LLM as context instead of raising — so the agent may *narrate* a failure instead of erroring |
| Answers degrade in long conversations | token usage | Context window exhausted — enable compaction with a `summarizer` |
| Memory tools missing or erroring | `database.postgres.vectorEnabled`, pgvector present | Bundled `postgres:18` has no pgvector |
| Helm upgrade fails immediately | values file | `rbac.clusterScoped` still set, or `rbac.namespaces` omits the install namespace |
| Agent has more power than intended | `kubectl auth can-i --as=system:serviceaccount:...` | Default cluster-scoped RBAC; prompt restrictions are not enforcement |
| UI unreachable | `kubectl -n kagent get svc` | Service name differs by release — **VERIFY** |
| Slow first response after idle | pod startup, `spec.declarative.runtime` | Python runtime (~15 s vs ~2 s for Go). Set `runtime: go` explicitly — do not rely on the default, upstream documents it inconsistently |
| Everything slow, other GPU consumers suffering | shared GPU | Unbounded agent loop. Bound iterations and timeouts |

Standard collection when opening an issue or asking for help:

```bash
kubectl -n "$NS" get pods,svc,agents,modelconfigs,remotemcpservers
kubectl -n "$NS" logs deploy/kagent-controller --tail=300
kubectl -n "$NS" describe agent <name>
kubectl -n "$NS" logs deploy/<agent-deployment> --tail=200
helm -n "$NS" get values kagent
```

See also upstream [Debug kagent](https://kagent.dev/docs/kagent/operations/debug).

---

## 11. Uninstall

```bash
helm uninstall kagent -n "$NS"
helm uninstall kagent-crds -n "$NS"
kubectl delete namespace "$NS" --ignore-not-found

# confirm nothing survived
kubectl api-resources | grep -Ei 'kagent|mcp' || echo "clean"
kubectl get crd | grep -Ei 'kagent|mcp' || echo "clean"
kubectl get clusterrole,clusterrolebinding | grep -i kagent || echo "clean"
```

Deleting the CRD chart deletes the CRDs and therefore **all agents, model
configs and tool servers**. The database PVC may survive — check and remove it
deliberately.

A clean uninstall is part of what we sell. A customer who cannot cleanly remove
a tool will not adopt it.

---

## 12. Handover checklist

Before OK-129 is closed:

- [ ] Full rebuild from zero performed and timed (< 60 min), documented here
- [ ] One documented install path, verified end to end, including uninstall
- [ ] ≥ 3 own agents, prompts and tool choices explained
- [ ] Multi-agent delegation proven from logs, not from the answer
- [ ] ≥ 1 own kmcp tool server built and used
- [ ] Same agent tested on local and cloud model, difference recorded
- [ ] HITL: approve, reject-with-reason, and `ask_user` each demonstrated
- [ ] Ungated write and blast-radius scenario recorded, including a failure
- [ ] RBAC audited via `kubectl auth can-i` for every agent identity
- [ ] HA, upgrade with DB migration, external PostgreSQL + pgvector all exercised
- [ ] Tracing/prompt audit enabled; "where does an auditor look?" answered
- [ ] OIDC configured or deferred with a written reason; missing authorization
      documented as a customer risk
- [ ] Someone uninvolved built a working agent from this runbook alone
- [ ] 30-minute internal walkthrough survived the hard questions
- [ ] All `<FILL>` resolved and all `VERIFY` items confirmed
