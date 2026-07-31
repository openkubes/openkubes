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

### Local prerequisites

| Tool | Why |
|---|---|
| `kubectl` | everything |
| `helm` | the install path |
| `python3` with PyYAML | renders the private values file and the access profile |

`make -C <ok-cluster>/ok-kagent/kagent preflight` checks all of them plus the
repository layout, and fails with the missing name rather than a stack trace.

The Makefile targets use POSIX tools (`grep`, `sed`, `sort`) plus python3 only.
No ripgrep, no `envsubst`, no BSD-only `stat` flags — they behave the same on
macOS and Linux. If you add a step that needs something else, add it to
`preflight` in the same commit.

### Safety

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

Every `make` target re-checks the context itself before it changes anything, so a
switched kubeconfig aborts instead of hitting the wrong cluster.

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
make -C <ok-cluster>/ok-kagent/kagent preflight
make -C <ok-cluster>/ok-kagent/kagent install
```

The target:

1. checks local tools, the access config and the openkubes assets;
2. verifies the expected context;
3. renders the private endpoint into a mode-0600, Git-ignored values file, and
   deletes it again if any placeholder survived;
4. renders the access profile from `access-config.yaml` (§5);
5. installs the CRD chart first, then the application chart;
6. applies the read path and adds or removes the write path to match the profile;
7. verifies the resulting RBAC boundary and prints the active profile.

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
# portable on macOS and Linux — `stat` flags are not
test "$(python3 -c 'import os,sys;print(oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])' \
  <ok-cluster>/ok-kagent/kagent/.values.local.yaml)" = 600
git -C <ok-cluster> check-ignore ok-kagent/kagent/.values.local.yaml
```

## 4. Read-only cluster inspector

Apply the reusable fixtures and Agent:

```bash
kubectl --kubeconfig "$KUBECONFIG" apply -k \
  <openkubes>/research/kagent-standalone

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

`make verify-access` runs exactly these assertions plus the ones for whichever
write profile is active (§5), so use it routinely and keep the manual commands
for when you need to see a single answer.

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

## 5. Access profiles: read-only and scoped write

The deployment has two roles, selected at install time from one file:
`<ok-cluster>/ok-kagent/kagent/access-config.yaml`. RBAC, the write tool server
and the write Agent are all generated from it, so the documented boundary and the
deployed boundary cannot drift apart.

### Where the boundary is

| Layer | Constrains | Strength |
|---|---|---|
| `systemMessage` | intent | soft — a prompt |
| `toolNames` | which tools the model sees | medium — configuration |
| `requireApproval` | which calls wait for a human, on the Agent that declares it | medium — a per-Agent workflow gate |
| **tool-server ServiceAccount RBAC** | which API calls the identity may make | **hard — the only enforced boundary here.** Note: some permissions reach further than the verbs they name — see the caveat under "Configuring the write scope" |

Three things follow, and all three belong in a customer conversation:

1. **The Agent is not the identity.** Kubernetes calls are executed by the *tool
   server's* ServiceAccount. Auditing an Agent manifest tells you intent;
   `kubectl auth can-i --as=<tool SA>` tells you capability.
2. **Existence and use are separate.** The profile controls whether a write
   identity exists. Once a write tool server exists, any Agent in the cluster
   could reference it — nothing upstream prevents that. Treat an installed write
   path as a cluster-level fact, and switch it off when a drill ends.
3. **The approval gate is per-Agent, not server-side.** The generated operator
   Agent is approval-gated; the shared write tool server and its Kubernetes
   identity are not themselves protected by that approval policy. A hard approval
   boundary would need enforcement in the tool server or another server-side
   authorization mechanism.

### The two profiles

`mode: read-only` — cluster-wide read, no writes, no Secret permission, on the
chart's built-in tool server. Nothing is generated for a write path, and
re-installing in this mode *removes* a previously generated one.

`mode: read-write` — additionally deploys one scoped write path:

```
Agent cluster-operator-gated (namespace kagent)
  ├── reads  via kagent-tool-server   → SA kagent/kagent-tools          cluster read, no Secret permission
  └── writes via kagent-write-tools   → SA kagent-write/kagent-write-tools
                                         └── Role+RoleBinding per listed namespace
                                             (never a cluster-scoped binding)
```

The write tool server runs in its **own** namespace, never inside a namespace it
may change — otherwise the agent could patch the tool server it is using.

### Configuring the write scope

This is the whole v1 write surface. There is no wider option to choose:

```yaml
mode: read-write
write:
  scope: namespaces          # the only scope; `cluster` is refused
  namespaces: [kagent-lab]   # explicit, non-empty
  resources: [configmaps]    # the only renderable write kind
  requireApproval: true      # must be true
```

```bash
make -C <ok-cluster>/ok-kagent/kagent access-summary   # what would this grant?
make -C <ok-cluster>/ok-kagent/kagent install          # apply it
make -C <ok-cluster>/ok-kagent/kagent verify-access    # prove it
```

Refused by the renderer whatever the config says: Secrets in any scope; RBAC
objects, ServiceAccounts, Namespaces, Nodes, CRDs, webhooks; `*` as a resource;
the `kagent` install namespace, the tool server's own namespace, `kube-*` and
`default` as write targets; `scope: cluster`; `requireApproval: false`; a mutating
tool name in the ungated `read.tools` reference; and every write kind beyond
ConfigMaps — workload kinds, Services, Ingresses and Pod deletion are candidate
work. It exits non-zero and generates nothing. Target namespaces are never created
by the profile — a missing one is an error, not an invitation.

Two of those refusals exist because the boundary itself is missing, not because a
test is missing: a `ClusterRoleBinding` cannot exclude `kagent`, `kube-*` or a
namespace created tomorrow; and **pod-template mutation on a Deployment,
StatefulSet, DaemonSet or Job can reach existing Secrets or a more privileged
ServiceAccount in the same namespace** without touching the Secret API — RBAC
alone does not stop that, admission control does. So the claim to make is *no
direct Secret or RBAC API permission is granted*, not "cannot reach Secrets".

Full reference: `research/kagent-standalone/access/README.md`.

### Verify the identity, not the manifest

```bash
make -C <ok-cluster>/ok-kagent/kagent verify-access
```

Asserts against the API server: the read identity reads but cannot write, is
denied on Secrets and has no wildcard; the write identity can patch ConfigMaps
inside its configured namespaces, is denied outside them, is denied on workload
controllers for *every* verb including `get`, and cannot create RoleBindings; and
in read-only mode the write Agent, its `RemoteMCPServer` and the `kagent-write`
namespace do not exist. A chart upgrade that quietly widens RBAC fails this target.

The write identity's own read context is Pods, Pod logs and Events in its
namespaces — enough to verify a change it just made. Everything else it reads, it
reads through the separate read identity.

### The drill

Exercise reversible objects only:

1. ask the Agent to create a ConfigMap in a configured write namespace;
2. inspect the proposed payload and approve it;
3. ask for an update and reject it with a reason;
4. verify that the rejected change did not land;
5. give an ambiguous request and confirm `ask_user` is used;
6. approve deletion of the test object;
7. switch back to `mode: read-only` and re-install.

There is no ungated or cluster-wide write test in OK-129, and no way to configure
one: the renderer refuses both.

### Observed results

The recorded drill ran against the **ConfigMap-only** profile in `kagent-lab` —
which is now also the only profile the renderer can produce:

- the scoped identity could create and delete ConfigMaps there;
- it was denied creating ConfigMaps in `default`, denied on Secrets, and had no
  wildcard permission;
- an approved apply created the expected ConfigMap and a read tool verified it;
- a rejected patch did not change the ConfigMap;
- after the first rejection the local model asked for approval again; the system
  prompt was tightened to prohibit retrying a rejected tool call;
- the second rejection run went straight to the approval gate, accepted the
  reason, did not retry, and left the object unchanged.

> **Candidate work, not shipped capability.** Workload kinds, Services, Ingresses,
> Pod deletion, ungated writes and `scope: cluster` are *refused* by the renderer.
> Two things have to happen before any of them becomes a real option: the boundary
> has to exist (typed repair tools with fixed editable fields, or a tested
> admission policy; for cluster scope, something that can express a namespace
> exclusion), and the drill above has to be re-run and recorded for it. The
> renderer's tests prove the *RBAC shape* — never the agent's behaviour with a
> rollout it can break.

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
  <openkubes>/research/kagent-standalone/agents/cluster-inspector.yaml
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
| Agent has excess power | `make verify-access`, then `kubectl auth can-i --as=...` | Tool-server RBAC is broader than the profile intends |
| Write tools missing after a profile change | `make access-summary`, `make status` | Profile is still `read-only`, or the re-install was not run |
| Install aborts on a missing write namespace | the namespace list in `access-config.yaml` | Target namespaces are never created by the profile — create it, or drop it from the list |
| RoleBindings bind nothing | ServiceAccount in the write namespace | The tools chart stopped creating the SA; the installer fails on this deliberately |

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
  <openkubes>/research/kagent-standalone
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
- [ ] `make verify-access` passes for the active profile, and the operator can
      say which file decides it.
- [ ] Switching `mode` in `access-config.yaml` and re-installing visibly adds or
      removes the write path.
- [ ] One namespace-scoped ConfigMap write flow passes Approve, Reject, and
      `ask_user`.
- [ ] Controller and Agent restart timings are recorded.
- [ ] An invalid Agent configuration is diagnosed and restored.
- [ ] PostgreSQL persistence and backup limits are understood.
- [ ] Clean uninstall and reinstall use only the documented commands.
- [ ] A second operator completes the daily operating path from this runbook.
