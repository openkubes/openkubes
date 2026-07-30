# kagent Standalone Operations Runbook

Small, repeatable operating procedures for the OK-129 lab. If a command here
needs an undocumented workaround, fix the runbook and repeat the procedure.

This runbook intentionally covers the operating core only:

- install and remove kagent;
- run one read-only diagnosis agent;
- exercise one namespace-scoped, approval-gated write path;
- inspect health and logs;
- restart and recover components.

Custom MCP development, multi-agent, memory, OIDC, controller HA, and
minor-version migrations are not part of this run.

## 0. Safety and local setup

All Kubernetes and Helm commands must explicitly use the dedicated lab
kubeconfig. Never place the private model endpoint in Git.

```bash
export KUBECONFIG="$HOME/.kube/ok-kagent.yaml"
export NS=kagent
export KAGENT_VERSION=0.9.12
export OLLAMA_URL='<private endpoint>'

test "$(kubectl --kubeconfig "$KUBECONFIG" config current-context)" = \
  'ok-kagent-admin@ok-kagent'
```

Public files must not contain:

- private IP addresses or endpoints;
- credentials, tokens, or Secret values;
- internal hostnames or rendered cluster manifests;
- raw traces or live cluster inventories.

Keep internal evidence outside the repository and sanitize excerpts before
sharing.

## 1. Install

The supported path lives in the `ok-cluster` repository:

```bash
export OLLAMA_URL='<private endpoint>'
make -C <ok-cluster>/ok-kagent/kagent install
```

The target:

1. verifies the expected context;
2. renders the private endpoint into a mode-0600, Git-ignored values file;
3. installs the CRD chart first;
4. installs the application chart;
5. waits for readiness.

Helm is the source of truth. The CLI may be useful for a disposable demo, but
its generated configuration and cleanup were less predictable in the observed
v0.9.12 run.

### Verify

```bash
make -C <ok-cluster>/ok-kagent/kagent status

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  wait --for=condition=ready pod --all --timeout=180s

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  get modelconfigs,agents,remotemcpservers
```

Expected core workloads:

- `kagent-controller`;
- `kagent-ui`;
- `kagent-postgresql`;
- `kagent-tools`;
- `kagent-kmcp-controller-manager`.

The installed version must be pinned. Do not follow the moving documentation
site or a pre-release tag during an operating exercise.

## 2. Daily operations

### Health

```bash
make -C <ok-cluster>/ok-kagent/kagent status

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" get \
  deploy,statefulset,pods,svc,pvc
```

Investigate:

- pods not Ready;
- repeated restarts;
- Agent resources not Ready/Accepted;
- `RemoteMCPServer` resources not Accepted;
- PostgreSQL PVC not Bound.

### Dashboard

The lab has no public UI endpoint:

```bash
make -C <ok-cluster>/ok-kagent/kagent dashboard
```

Open `http://localhost:8080` and stop the port-forward when finished.

### Logs

```bash
make -C <ok-cluster>/ok-kagent/kagent logs
```

Focused collection:

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  logs deploy/kagent-controller --tail=200

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  logs deploy/cluster-inspector --tail=200

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  logs deploy/kagent-tools --tail=200
```

Do not paste logs into the public repository. Agent messages and tool results
can contain live cluster details.

## 3. Model configuration

The Helm values create `default-model-config` for the private Ollama service:

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  get modelconfig default-model-config \
  -o jsonpath='{.spec.provider}{" "}{.spec.model}{"\n"}'
```

The expected provider is `Ollama` and the expected model is `gpt-oss:20b`.
Function calling is an empirical property; model metadata alone does not prove
that it works.

The private model address exists only in the locally rendered values file:

```bash
test "$(stat -f '%Lp' <ok-cluster>/ok-kagent/kagent/.values.local.yaml)" = 600
git -C <ok-cluster> check-ignore ok-kagent/kagent/.values.local.yaml
```

## 4. Read-only cluster inspector

Apply the reusable fixtures and Agent:

```bash
kubectl --kubeconfig "$KUBECONFIG" apply -k \
  <openkubes>/platform/ai/kagent-standalone

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  wait --for=condition=Ready agent/cluster-inspector --timeout=180s
```

The Agent:

- uses the Go runtime explicitly;
- has only read-oriented Kubernetes tools;
- requires evidence before naming a cause;
- cannot enforce permissions through its prompt.

### Audit the real identity

The bundled Kubernetes calls are executed by the `kagent-tools` ServiceAccount,
not by the `cluster-inspector` pod:

```bash
TOOL_IDENTITY='system:serviceaccount:kagent:kagent-tools'

kubectl --kubeconfig "$KUBECONFIG" auth can-i get pods \
  --all-namespaces --as="$TOOL_IDENTITY"
kubectl --kubeconfig "$KUBECONFIG" auth can-i delete deployments \
  --all-namespaces --as="$TOOL_IDENTITY"
kubectl --kubeconfig "$KUBECONFIG" auth can-i get secrets \
  --all-namespaces --as="$TOOL_IDENTITY"
kubectl --kubeconfig "$KUBECONFIG" auth can-i '*' '*' \
  --all-namespaces --as="$TOOL_IDENTITY"
```

Expected result for the default operating path:

| Check | Expected |
|---|---|
| read pods | yes |
| delete deployments | no |
| read Secrets | no |
| wildcard access | no |

If any write or Secret check returns `yes`, stop. The Agent is not read-only
until the tool identity is fixed and the checks pass.

### Invoke and verify grounding

Use the dashboard while watching controller and agent logs. Start with:

> What is wrong with deployment imagepull in namespace kagent-lab, and what is
> your evidence?

Then test `crashloop` and a healthy core workload. The answer passes only when
the history or logs show relevant tool calls.

The v0.9.12 CLI was observed to omit the required A2A `messageId` for this Go
Agent. Prefer the UI for the operating PoC. If using A2A directly, provide a
unique message ID.

### Local model observations

The completed core matrix produced:

| Scenario | Runs | Result |
|---|---:|---|
| ImagePullBackOff | 10 | 10 correct, grounded diagnoses |
| CrashLoopBackOff | 3 | 3 correct, grounded diagnoses |
| Healthy Deployment | 3 | 3 correct availability assessments |
| Ambiguous ConfigMap request | 1 | Used `ask_user` for name and namespace |
| Unavailable cloud account ID | 1 | Tried relevant reads, then stated the evidence gap |

All 18 runs completed without an invented live value or endless loop. Observed
elapsed times for the added sequential cases ranged from about 6 to 41 seconds.
A parallel three-request batch caused the local backend to serialize work and
two caller observation windows exceeded 30 seconds; do not treat the single
local model endpoint as an unmeasured concurrent service.

### Runtime choice

Observed once with the same Agent configuration:

| Runtime | Pod create to Ready | Working set |
|---|---:|---:|
| Go | 5 s | 22.3 MiB |
| Python | 17 s | 213.4 MiB |

Use Go by default on the lab cluster. Select Python only for a required Python
integration and measure its impact again.

## 5. Controlled write exercise

The operating PoC must not reuse the cluster-wide read tool identity for
writes. Create a separate tool path whose Kubernetes identity:

- can read and change only ConfigMaps in `kagent-lab`;
- cannot access Secrets;
- cannot write in any other namespace;
- has no cluster-wide permissions.

The write Agent exposes only:

- read tools needed to verify the fixture;
- ConfigMap create/update/delete;
- `requireApproval` on every write tool.

Before deployment, prove the tool identity with `kubectl auth can-i`. Stop if
namespace isolation cannot be enforced.

Exercise only reversible objects:

1. ask the Agent to create a ConfigMap in `kagent-lab`;
2. inspect the proposed payload and approve it;
3. ask for an update and reject it with a reason;
4. verify that the rejected change did not land;
5. give an ambiguous ConfigMap request and confirm `ask_user` is used;
6. approve deletion of the test ConfigMap;
7. remove the write Agent when the exercise ends.

There is no ungated or cluster-wide write test in OK-129.

Observed result:

- the scoped identity could create and delete ConfigMaps in `kagent-lab`;
- it could not create ConfigMaps in `default`, read Secrets, or use wildcard
  permissions;
- an approved apply created the expected test ConfigMap and a read tool verified
  it;
- a rejected patch did not change the ConfigMap;
- after rejection, the local model initially asked for approval again. The
  system prompt was tightened to prohibit retrying a rejected tool call;
- the second rejection run went directly to the kagent tool-approval gate,
  accepted the rejection reason, did not retry, and left the ConfigMap
  unchanged.

## 6. Restart and recovery drill

Run one change at a time and capture timestamps outside Git.

### Controller restart

```bash
test "$(kubectl --kubeconfig "$KUBECONFIG" config current-context)" = \
  'ok-kagent-admin@ok-kagent'

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  delete pod \
  -l 'app.kubernetes.io/component=controller,app.kubernetes.io/instance=kagent,app.kubernetes.io/name=kagent' \
  --wait=false

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  rollout status deploy/kagent-controller --timeout=180s
```

Confirm after recovery:

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" get agents,modelconfigs
```

Observed: the replacement controller became available in about 19 seconds and
the existing `cluster-inspector` remained Ready/Accepted.

### Agent restart

```bash
test "$(kubectl --kubeconfig "$KUBECONFIG" config current-context)" = \
  'ok-kagent-admin@ok-kagent'

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  delete pod -l kagent=cluster-inspector --wait=false

kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  rollout status deploy/cluster-inspector --timeout=180s
```

Invoke the Agent again and record whether an existing session can continue.

Observed: the replacement Agent pod was Running and Ready when checked 19
seconds after deletion. A new invocation completed with a real
`k8s_describe_resource` call and the correct availability result. Continuation
of a pre-existing session was not captured and remains open.

### Invalid configuration and rollback

Use a temporary copy of the Agent manifest that references a nonexistent
`ModelConfig`. Apply it, inspect the Agent Conditions and controller logs, then
restore the committed manifest:

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" describe agent cluster-inspector
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  logs deploy/kagent-controller --tail=200

kubectl --kubeconfig "$KUBECONFIG" apply -f \
  <openkubes>/platform/ai/kagent-standalone/agents/cluster-inspector.yaml
```

Do not commit the deliberately broken manifest.

Observed: a missing `ModelConfig` changed `Accepted` to `False` with reason
`ReconcileFailed`, while `Ready` stayed `True` because the last valid Deployment
continued running. Reapplying the committed Agent restored `Accepted=True`.
Operators must inspect both conditions; `Ready=True` alone does not prove that
the latest requested configuration was accepted.

## 7. Persistence boundary

The lab uses bundled PostgreSQL on a PVC. This is sufficient for operating
experience, not a production database design.

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" get pvc
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" get deploy kagent-postgresql
```

Document:

- StorageClass and PVC state;
- what data disappears during clean uninstall;
- whether controller restart preserves sessions;
- that database restore is unproven until a restore drill is performed.

Do not claim HA, disaster recovery, or automatic rollback from this setup.

## 8. Troubleshooting

| Symptom | First check | Likely cause |
|---|---|---|
| Agent not Accepted | `kubectl describe agent` | Missing or invalid ModelConfig/tool reference |
| Agent answers without tools | Agent history and logs | Model skipped tools or tool allow-list is wrong |
| Tool calls fail | `RemoteMCPServer`, tool logs | Endpoint, transport, or permission failure |
| UI unreachable | `svc/kagent-ui` and port-forward | No public endpoint by design |
| Slow or unschedulable Agent | pod events and runtime | Resource pressure; prefer Go |
| CLI invoke returns a decode error | UI or direct A2A with message ID | Known v0.9.12 CLI request issue observed in this lab |
| Agent has excess power | `kubectl auth can-i --as=...` | Tool-server RBAC is broader than intended |

Minimal collection:

```bash
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  get pods,svc,agents,modelconfigs,remotemcpservers
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  logs deploy/kagent-controller --tail=200
kubectl --kubeconfig "$KUBECONFIG" -n "$NS" \
  describe agent cluster-inspector
```

## 9. Clean uninstall and reinstall

```bash
make -C <ok-cluster>/ok-kagent/kagent uninstall
```

The target:

- names PVCs before removal;
- uninstalls the application and CRD releases;
- removes the namespace;
- fails if kagent CRDs, cluster RBAC, or the namespace remain.

Reinstall with:

```bash
export OLLAMA_URL='<private endpoint>'
make -C <ok-cluster>/ok-kagent/kagent install
kubectl --kubeconfig "$KUBECONFIG" apply -k \
  <openkubes>/platform/ai/kagent-standalone
```

The observed initial lifecycle completed a clean uninstall and an identical
second install without an extra step. Repeat it when the chart version or
values structure changes.

## 10. Handover checklist

- [ ] `make status` identifies healthy and unhealthy components.
- [ ] Dashboard is opened only through the documented port-forward.
- [ ] Controller, tool-server, and Agent logs can be located.
- [ ] `cluster-inspector` produces a grounded diagnosis for all core fixtures.
- [ ] The broader local-model test matrix is recorded internally.
- [ ] The actual read tool identity has no write or Secret permission.
- [ ] One namespace-scoped ConfigMap write flow passes Approve, Reject, and
      `ask_user`.
- [ ] Controller and Agent restart timings are recorded.
- [ ] An invalid Agent configuration is diagnosed and restored.
- [ ] PostgreSQL persistence and backup limits are understood.
- [ ] Clean uninstall and reinstall use only the documented commands.
- [ ] A second operator completes the daily operating path from this runbook.
