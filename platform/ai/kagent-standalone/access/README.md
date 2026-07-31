# Access profiles — one config decides what kagent may do

`render-access.py` turns a single declarative config into every object that grants
a standalone kagent installation its permissions. Read-only or read-write,
cluster-wide or a maintained list of namespaces, gated or not — all of it comes
from `access-config.yaml`.

Why a generator instead of a few static manifests: RBAC that has to stay in sync
with a prompt, a tool allow-list and a Helm value across two repositories drifts.
It drifted here once already — a widened Role shipped while the documentation
still described the narrow one. Generating removes the class of bug.

## Where the boundary actually is

This is the part to understand before changing anything, and the part to say out
loud in a customer conversation.

| Layer | Constrains | Strength | Configured by |
|---|---|---|---|
| `systemMessage` | intent | **soft** — a prompt | generated from the config |
| `toolNames` allow-list | which tools the model can see | **medium** — configuration | `read.tools` / `write.tools` |
| `requireApproval` | which calls wait for a human | **medium** — a workflow gate | `write.requireApproval` |
| **ServiceAccount RBAC** | what the executing identity *can* do | **hard — the only real boundary** | `write.scope`, `write.namespaces`, `write.resources` |

Two consequences that surprise people:

1. **The Agent is not the identity.** Kubernetes calls are executed by the *tool
   server's* ServiceAccount, not by the Agent pod. Auditing an Agent manifest
   tells you what it intends; `kubectl auth can-i --as=<tool SA>` tells you what
   it can do. Only the second one matters.
2. **Existence and use are different questions.** This deployment controls
   *existence*: in read-only mode there is no write identity to bind to. Once a
   write tool server exists, any Agent in the cluster could reference it —
   nothing upstream prevents that. Keep the write profile off unless a drill
   needs it, and treat an installed write path as a cluster-level fact rather
   than a per-agent detail.

## The two profiles

**`mode: read-only`** — the diagnostic path only. The chart's built-in tool
server keeps `rbac.readOnly: true` and `allowSecrets: false`: cluster-wide read,
no writes, no Secrets. Nothing is generated for the write path, and re-rendering
in this mode *removes* a previously generated one instead of orphaning it.

**`mode: read-write`** — additionally deploys one scoped write path:

```
Agent cluster-operator-gated  (namespace: kagent)
  ├── reads via  kagent-tool-server      → SA kagent/kagent-tools        (cluster read, no Secrets)
  └── writes via kagent-write-tools      → SA kagent-write/kagent-write-tools
                                            └── Role/RoleBinding per target namespace
                                                or ClusterRole/ClusterRoleBinding
```

The write tool server deliberately runs in its **own** namespace
(`write.toolServer.namespace`, default `kagent-write`), never inside a namespace
it may change. Otherwise the agent could patch the Deployment of the tool server
it is using.

## Write scope

```yaml
# A maintained list of namespaces — the preferred shape.
write:
  scope: namespaces
  namespaces: [kagent-lab, team-a, team-b]
```

One `Role` + `RoleBinding` per namespace. Adding a namespace is one line;
removing one removes its Role on the next install. Namespaces are **never
created** by the profile — if a target does not exist, the installer fails with
that message rather than inventing it.

```yaml
# Every namespace, including ones created later.
write:
  scope: cluster
  namespaces: []
```

One `ClusterRole` + `ClusterRoleBinding`. Requires `requireApproval: true`; an
unattended cluster-wide writer is refused outright.

## What can never be granted

The renderer refuses, regardless of config:

- `secrets` — in any scope, read or write, for any identity;
- `roles`, `rolebindings`, `clusterroles`, `clusterrolebindings`,
  `serviceaccounts` — the privilege-escalation path;
- `namespaces`, `nodes`, `persistentvolumes`, `customresourcedefinitions`,
  webhook configurations — cluster infrastructure;
- `*` as a resource;
- the kagent install namespace as a write target — an agent that can write there
  can rewrite its own Agent and tool definitions;
- `kube-*` namespaces;
- `requireApproval: false` together with `scope: cluster`.

These are not defaults to be overridden. They are refusals: the renderer exits
non-zero and generates nothing.

Grantable resources: `configmaps`, `deployments`, `statefulsets`, `daemonsets`,
`replicasets`, `services`, `ingresses`, `jobs`, `cronjobs`, and `pods`
(delete only — an agent restarts a workload, it does not hand-build Pods).

Every write profile also gets read-only context in its own scope — pods, pod
logs, events, replicasets — so the agent can verify the change it just made
instead of asserting success.

## Usage

Normally through the cluster-specific installer, which renders and applies in one
step and then verifies the result:

```bash
make -C <ok-cluster>/ok-kagent/kagent access-summary   # what would this grant?
make -C <ok-cluster>/ok-kagent/kagent install          # apply it
make -C <ok-cluster>/ok-kagent/kagent verify-access    # prove it
```

Directly, for inspection or for another cluster:

```bash
./render-access.py --config access-config.yaml --out /tmp/profile --summary
```

Outputs in `--out`:

| File | Purpose |
|---|---|
| `values-access.yaml` | Helm values fragment pinning the built-in tool server to read-only |
| `tools-values.yaml` | Helm values for the scoped write tool server (write mode only) |
| `manifests/10-namespace.yaml` | the write tool server's own namespace |
| `manifests/20-rbac.yaml` | Role(s)+RoleBinding(s), or ClusterRole+ClusterRoleBinding |
| `manifests/30-tool-server.yaml` | `RemoteMCPServer` pointing at the scoped tool server |
| `manifests/40-agent.yaml` | the write Agent, with `requireApproval` on every write tool |
| `profile.env` | shell-sourceable facts, so the installer asserts the same boundary it generated |
| `SUMMARY.md` | what this profile grants, as a reviewable table |

Only `manifests/` is meant for `kubectl apply`. The output is generated: keep it
out of Git and re-render rather than editing it. A stale manifest from a wider
profile is a security bug, not clutter — the renderer clears the directory on
every run for exactly that reason.

## Verifying instead of trusting

`SUMMARY.md` ends with the `kubectl auth can-i` calls for the profile it just
rendered, and `make verify-access` runs the same assertions against the API
server: reads work, writes and Secrets are denied for the read identity, the
write identity works inside its scope and is denied outside it, and in read-only
mode no write objects exist at all. A chart upgrade that quietly widens RBAC
fails that target.

## Tests

```bash
python3 render_access_test.py
```

Static, no cluster. Asserts the properties that matter: read-only generates no
write path, namespace scope produces no cluster-scoped RBAC, forbidden resources
never appear in a generated rule, `requireApproval` covers every exposed write
tool, downgrading removes the previous manifests, and each refused config is
actually refused.

## Extension points

- **Namespaced read scope** is deliberately *not* implemented. It would mean
  taking over the chart's built-in tool RBAC, which needs to be tested against a
  live cluster rather than assumed. `read.scope: namespaces` is refused with that
  explanation instead of silently doing nothing.
- **Tool names** are config, not code. They must exist in the installed tool
  server — check with
  `kubectl get remotemcpserver kagent-tool-server -o yaml`. The renderer does not
  invent names.
- **More resource kinds**: add them to `WRITABLE_RESOURCES` with their apiGroup
  and verbs, and add a test. Anything in `FORBIDDEN_RESOURCES` needs a written
  decision first, not a code change.
