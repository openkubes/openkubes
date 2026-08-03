# Access profiles — one config decides what kagent may do

`render-access.py` turns a single declarative config into every object that grants
a standalone kagent installation its permissions: read-only diagnosis, or
additionally one approval-gated ConfigMap write path in `kagent-lab`. All of it
comes from `access-config.yaml`.

The namespace is not an operator choice in v1. `kagent-lab` is the one target the
recorded drill in `evidence-protocol.md` was run against, so
`EVIDENCED_WRITE_NAMESPACES` in the renderer is exactly that set and any other or
mixed list fails closed. This restriction lives here, in the shared renderer,
rather than only in an installer-side guard — otherwise the guarantee would hold
only for consumers that happen to re-implement it, which is not a guarantee.

Why a generator instead of a few static manifests: RBAC that has to stay in sync
with a prompt, a tool allow-list and a Helm value across two repositories drifts.
It drifted here once already — a widened Role shipped while the documentation
still described the narrow one. Generating removes the class of bug.

## v1 renders only what has been evidenced

The renderer's executable surface is deliberately smaller than what kagent can
do. It renders exactly the write profile that was exercised on a live cluster and
recorded in
[`docs/kagent-standalone/evidence-protocol.md`](../../../docs/kagent-standalone/evidence-protocol.md):

```yaml
mode: read-write
write:
  scope: namespaces
  namespaces: [kagent-lab]
  resources: [configmaps]
  requireApproval: true
```

Everything wider is **candidate work**: recognised by the renderer, refused with
the reason, and documented below. Not "off by default" — refused. A PoC does not
need production-grade completeness, but every boundary it claims has to hold for
every configuration it can actually produce, and the fastest way to guarantee
that is to not produce the configurations whose boundary has not been
demonstrated.

## Where the boundary actually is

This is the part to understand before changing anything, and the part to say out
loud in a customer conversation.

| Layer | Constrains | Strength | Configured by |
|---|---|---|---|
| `systemMessage` | intent | **soft** — a prompt | generated from the config |
| `toolNames` allow-list | which tools the model can see | **medium** — configuration | `read.tools` / `write.tools` |
| `requireApproval` | which calls wait for a human *on the Agent that declares it* | **medium** — a per-Agent workflow gate, not a server-side policy | `write.requireApproval` |
| **tool-server ServiceAccount RBAC** | which API calls the executing identity may make | **hard — the only enforced boundary here.** Some permissions reach further than the verbs they name; see "What withholding those verbs does and does not prove" | not config — the `EVIDENCED_WRITE_NAMESPACES` and `WRITABLE_RESOURCES` allow-lists in the renderer |

Three consequences that surprise people:

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
3. **The approval gate is a property of the generated Agent, not of the tool
   server.** `requireApproval` is set on `cluster-operator-gated`'s reference to
   the write `RemoteMCPServer`. Neither that `RemoteMCPServer` nor the write
   ServiceAccount enforces it. Stated precisely, and this is the sentence to use:

   > The generated operator Agent is approval-gated. The shared write tool server
   > and its Kubernetes identity are not themselves protected by that approval
   > policy.

   If approval has to be a hard capability boundary rather than a workflow
   convenience, it must be enforced by the tool server or by another server-side
   authorization mechanism. That does not exist here, which is why the RBAC scope
   is kept small enough that an unapproved caller is still bounded.

## The two profiles

**`mode: read-only`** — the diagnostic path only. The chart's built-in tool
server keeps `rbac.readOnly: true` and `allowSecrets: false`: cluster-wide read,
no write verbs, no Secret permission. Nothing is generated for the write path, and
re-rendering in this mode *removes* a previously generated one instead of
orphaning it.

**`mode: read-write`** — additionally deploys one scoped write path:

```
Agent cluster-operator-gated  (namespace: kagent)
  ├── reads via  kagent-tool-server      → SA kagent/kagent-tools        (cluster read, no Secret permission)
  └── writes via kagent-write-tools      → SA kagent-write/kagent-write-tools
                                            └── Role + RoleBinding in kagent-lab
                                                (never a cluster-scoped binding)
```

The write tool server deliberately runs in its **own** namespace
(`write.toolServer.namespace`, default `kagent-write`), never inside a namespace
it may change. Otherwise the agent could patch the Deployment of the tool server
it is using.

## Write scope — the evidenced namespace only

```yaml
write:
  scope: namespaces
  namespaces: [kagent-lab]
```

v1 renders one `Role` + `RoleBinding` in `kagent-lab`. Any other namespace — by
itself or added to the list — is refused until it has a recorded drill and a
reviewed boundary. The write **target** is never created by the profile; if
`kagent-lab` does not exist, the installer fails rather than inventing it. The one
namespace the profile does create is the write tool server's own
(`10-namespace.yaml`), which is not a write target.

`scope: cluster` is **refused**, and not because it is untested. A normal
`ClusterRoleBinding` applies in every namespace — `kagent`, `kagent-write`,
`kube-system`, and every namespace created after the install — and RBAC has no
way to express an exclusion. An allow-list can be checked one entry at a time; a
cluster-scoped binding has no entries to check, so no additional condition makes
the namespace guarantees hold for it. Cluster-wide write is
candidate work until there is both a forcing consumer and an enforceable
boundary; in this lab there is neither.

## What can never be granted

The renderer refuses, regardless of config:

- `secrets` — in any scope, read or write, for any identity;
- `roles`, `rolebindings`, `clusterroles`, `clusterrolebindings`,
  `serviceaccounts` — the direct privilege-escalation API path;
- `namespaces`, `nodes`, `persistentvolumes`, `customresourcedefinitions`,
  webhook configurations — cluster infrastructure;
- `*` as a resource;
- the kagent install namespace as a write target — an agent that can write there
  can rewrite its own Agent and tool definitions;
- the write tool server's own namespace as a write target;
- `kube-*` namespaces, and `default`;
- **any write target other than `kagent-lab`** — v1 requires exactly the evidenced
  set, so a different namespace or a mixed list is refused, not merely warned about;
- `write.scope: cluster`;
- `requireApproval: false`;
- a mutating or Secret-flavoured tool name in `read.tools` — that reference is
  rendered ungated, so only read tools belong in it. (A substring heuristic, and a
  consistency check on the config: RBAC is what denies the call.)

These are not defaults to be overridden. They are refusals: the renderer exits
non-zero and generates nothing.

It also fails closed on input that is merely *odd*, because every one of these has
a way of turning into a quietly false claim:

- **an unknown key**, at any level. `install: {namespaces: ai}` — a plural typo —
  used to leave `install.namespace` at its default, silently disabling the
  install-namespace protection that the summary advertises;
- **a namespace or object name that is not a clean DNS label**, checked with
  `fullmatch`. `re.match` with `$` accepts a trailing newline, and `"kagent\n"`
  passing that check was enough to slip past the install-namespace comparison;
- **shell metacharacters in `agentName`, `releaseName`, `install.namespace`,
  `toolServer.namespace` or a tool name.** Every one of those reaches
  `profile.env`, which is documented as shell-sourceable, so an unvalidated name
  there is command execution in the installer rather than a broken manifest. They
  are validated *and* single-quoted — and validated again on the render path, so
  the guarantee holds for an importer of this module and not only for callers of
  `load_config`;
- a duplicate namespace, tool or resource; a metrics port equal to the tool port;
  a `toolServer.port` other than `CHART_TOOLS_PORT`, because this renderer
  templates only the metrics port and any other value would put a port the tool
  server is not serving into the generated `RemoteMCPServer` URL; and a port
  that is not an actual integer — `true` would otherwise become port 1 and
  `8084.9` would be truncated, because `bool` is a subclass of `int` in Python and
  `int()` coerces silently.

Grantable resources in v1: **`configmaps`, and nothing else.**

The write identity also gets read-only context in `kagent-lab` — Pods, Pod logs
and Events — so the agent can verify the change it just made instead of
asserting success. Deliberately *not* included: any `apps` resource. Granting the
write identity even a read verb on a workload controller would make the
"no permission on workload kinds" claim false, and cluster-wide read already
exists on the separate read identity.

`default` is refused as a write target. The generated summary asserts that writes
in `default` are denied, and a warning-only check would have turned that assertion
into a false claim for anyone who ignored the warning.

### What withholding those verbs does and does not prove

Accurate claim: **no direct Secret, ServiceAccount or RBAC API permission is
granted to the write identity.** That is a statement about the generated rules,
and `kubectl auth can-i` confirms it.

Not a supportable claim: that no privilege escalation is *reachable*. Withholding
the Secret verbs closes the direct API path, not every path. **Pod-template
mutation on a Deployment, StatefulSet, DaemonSet or Job can reach existing Secrets
or a more privileged ServiceAccount in the same namespace** — by setting a
different `serviceAccountName`, mounting a Secret that already exists, or changing
the image and command — none of which requires calling the Secret API. Nothing in
RBAC alone prevents that; it takes admission control.

This is the main reason workload kinds are candidate work here rather than a
config option: the honest version of the guarantee would have to be much weaker
than the one the documentation used to make.

## Candidate work — recognised, refused, and why

Each entry is refused with its reason at render time, so nobody has to read this
table to find out.

| Capability | Why it is not a v1 option |
|---|---|
| `deployments`, `statefulsets`, `daemonsets`, `replicasets`, `jobs`, `cronjobs` | pod-template write reaches Secrets and other ServiceAccounts indirectly. Needs narrowly typed repair tools with fixed editable fields, or a documented and tested admission-policy boundary. |
| `services`, `ingresses` | traffic-path write. No drill, and no tested bound on blast radius. |
| `pods` (delete) | a disruption primitive. No recorded drill. |
| `write.scope: cluster` | `ClusterRoleBinding` cannot exclude namespaces; no forcing consumer in this lab. |
| any write namespace other than `kagent-lab` | no recorded drill for it. Multi-namespace RBAC is the same *shape*, but shape is not evidence, and `EVIDENCED_WRITE_NAMESPACES` is the renderer's own boundary rather than a downstream consumer's. |
| `requireApproval: false` | no drill, and no compensating server-side control. |
| namespaced **read** scope | would mean taking over the chart's built-in tool RBAC; needs live testing, not a config flag. |

Promoting one of these is a specific piece of work: implement the boundary, run
E4b in `evidence-protocol.md` for it, record the result, *then* widen the
allow-list — `WRITABLE_RESOURCES` for a kind, `EVIDENCED_WRITE_NAMESPACES` for a
namespace. Editing either constant is a claim that this already happened, and the
tests assert the current contents so the edit cannot pass unnoticed.

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
| `manifests/20-rbac.yaml` | one Role + RoleBinding in `kagent-lab` — never a cluster-scoped object |
| `manifests/30-tool-server.yaml` | `RemoteMCPServer` pointing at the scoped tool server |
| `manifests/40-agent.yaml` | the write Agent, with `requireApproval` on every write tool it references |
| `profile.env` | shell-sourceable facts, so the installer asserts the same boundary it generated |
| `SUMMARY.md` | what this profile grants, as a reviewable table |

Only `manifests/` is meant for `kubectl apply`. The output is generated: keep it
out of Git and re-render rather than editing it. A stale manifest from a wider
profile is a security bug, not clutter — the renderer empties `manifests/` on every
run for exactly that reason, every file and not only `*.yaml`, and removes the
directory entirely for a read-only profile so `kubectl apply -f manifests/` cannot
quietly apply nothing.

## Verifying instead of trusting

`SUMMARY.md` ends with the `kubectl auth can-i` calls for the profile it just
rendered, and `make verify-access` runs the same assertions against the API
server: reads work, writes and Secret reads are denied for the read identity, the
write identity can patch ConfigMaps inside its scope and is denied outside it and
on workload kinds, and in read-only mode no write objects exist at all. A chart
upgrade that quietly widens RBAC fails that target.

## Tests

```bash
python3 render_access_test.py    # renderer behaviour
python3 review_rc_check.py       # the five review points, incl. the documents
```

`review_rc_check.py` is the narrower one: it asserts that each point raised in the
PR review is true of this tree.

- cluster scope **and** the evidenced namespace refused at *every* render entry
  point, not only in `load_config` — the boundary must hold for an importer of this
  module, not only for callers that go through the loader;
- ConfigMaps-only and `kagent-lab`-only, in the code *and* in the shipped example;
- the exact approval-boundary sentence in all six documents and in the generated
  summary;
- the pod-template escalation caveat worded as the reviewer asked, naming
  Deployment/StatefulSet/DaemonSet/Job and a more privileged ServiceAccount;
- ports rejected unless they are actual integers — `bool` is a subclass of `int`,
  so `port: true` would otherwise render port 1;
- no stale `platform/ai/` reference in a tracked file.

A later edit that softens one of these fails a check instead of surfacing in
another review round.

Static, no cluster. Asserts the properties that matter:

- read-only generates no write path, and a read-only profile that still carries a
  populated write block is refused rather than summarised;
- the renderable write surface is ConfigMaps in `kagent-lab` only;
- **nothing `load_config` refuses is renderable.** Not as a second list of checks —
  those drifted from the first three times, and each time a reviewer found the one
  that had been missed. `_require_renderable_profile` converts the config back to
  its on-disk shape and re-runs `validate_raw_config`, the same validator the
  loader uses, so divergence is impossible by construction. The round trip must
  also be lossless, which is how a dropped or renamed field would surface. Every
  public renderer calls it — `render_read_values`, `render_namespace`,
  `render_rbac`, `render_tool_server`, `render_agent`, `render_tools_values`,
  `render_summary`, `render_profile_env`, `write_outputs` — and the test enumerates
  all nine, because a list that omits one cannot falsify a claim about all of them;
  that omission is exactly how `render_namespace` stayed unguarded for a round;
- anything unrenderable is a `ConfigError`, never a `TypeError` or `KeyError`: a
  valid *read-only* profile passed to a write renderer is refused with a message,
  not a traceback;
- no cluster-scoped **RBAC** object can be produced (`10-namespace.yaml` is a
  `Namespace`, which is cluster-scoped and intended — it is the tool server's own);
- a refusal anywhere in `write_outputs` leaves no partial profile behind; no shell
  metacharacter reaches `profile.env` through any field **in either mode** — the
  read-only case is asserted separately, because `KAGENT_ACCESS_MODE` and
  `KAGENT_INSTALL_NAMESPACE` are emitted before the write branch, and the test
  counts its own assertions so a loop that silently short-circuits fails;
- the config filename cannot inject a heading into `SUMMARY.md`, the one document
  whose purpose is to be the reviewable statement of the boundary;
- forbidden resources never appear in a generated rule; `requireApproval` covers
  every exposed write tool;
- the summary states the approval boundary as an Agent-level policy and avoids
  absolute Secret or escalation claims;
- downgrading removes the previous manifests, and each refused config is refused
  *for the reason its label names* — a bare "some error was raised" check would
  still pass with the named check deleted.

## Extension points

- **Namespaced read scope** is deliberately *not* implemented. It would mean
  taking over the chart's built-in tool RBAC, which needs to be tested against a
  live cluster rather than assumed. `read.scope: namespaces` is refused with that
  explanation instead of silently doing nothing.
- **Tool names** are config, not code. They must exist in the installed tool
  server — check with
  `kubectl get remotemcpserver kagent-tool-server -o yaml`. The renderer does not
  invent names.
- **More resource kinds** are not an extension point in the ordinary sense. See
  "Candidate work" above: the boundary has to exist and be evidenced before the
  kind moves from `CANDIDATE_RESOURCES` to `WRITABLE_RESOURCES`, and the tests
  assert the current split so widening it is a visible, reviewable change rather
  than a one-line edit. Anything in `FORBIDDEN_RESOURCES` needs a written
  decision first, not a code change.
