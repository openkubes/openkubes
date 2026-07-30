# kagent Reference — standalone operation

What kagent is, what it can do, how every piece is configured, and where it
stops. Written for the standalone case: kagent as the *whole* system, not as a
provider behind a contract.

Source: [kagent.dev/docs](https://kagent.dev/docs/kagent) as of **2026-07-30**,
release line **0.9.x**. Every YAML shape below is taken from upstream docs for
that line. Anything marked **VERIFY** must be checked against the installed CRDs
with `kubectl explain` before it goes into customer-facing material.

> **PoC scope:** This reference describes more features than OK-129 deploys.
> The core operating PoC uses one controller, bundled PostgreSQL, the built-in
> read-only Kubernetes tool server, one read-only Agent, and one separately
> scoped approval-gated write exercise. Custom MCP servers, multi-agent, skills,
> memory, OIDC, HA, and upgrades require separately approved follow-up work.

---

## 1. What kagent is

kagent is a Kubernetes-native framework for running AI agents *inside* the
cluster. Its defining property: **agents are Kubernetes resources.** An agent is
a CRD, its model is a CRD, its tools are CRDs. That means agents are subject to
the same lifecycle you already own — GitOps, RBAC, admission control, audit,
drift detection.

- Origin: Solo.io. Now a **CNCF Sandbox** project under LF Projects, LLC.
- Sub-project **kmcp**: CLI + control plane for building and running MCP servers.
  Installed with kagent by default since 0.7.
- A commercial **Solo Enterprise for kagent** distribution exists. Relevant for
  customer conversations: what do we recommend, and who carries support?

### Why this matters commercially

The pitch is not "an AI chatbot for Kubernetes". The pitch is: *your operational
knowledge becomes a declarative, reviewable, version-controlled cluster object.*
A customer who already runs GitOps can put agents in the same pipeline as
everything else. That is the differentiator against a hosted assistant.

The counter-argument a customer will raise — and we must answer, not dodge — is
that CNCF Sandbox means no stability guarantee. See §11.

---

## 2. Architecture

Four components, three of which run in the cluster:

| Component | Role |
|---|---|
| **Controller** | Go Kubernetes controller. Reconciles the CRDs into running agents. Serves the HTTP API, the A2A endpoint, and an MCP endpoint. |
| **App / Engine** | Runs the agent conversation loop. Two selectable runtimes (see §5). |
| **UI / Dashboard** | Web interface for chatting with agents, editing them, approving tool calls. |
| **CLI** (`kagent`) | Runs outside the cluster. Install, manage resources, invoke agents, scaffold and run agents locally without a cluster. |

Plus **PostgreSQL** — mandatory since 0.8 (see §8).

Request path for a normal conversation:

```
user ──► UI or CLI or A2A/MCP client
           │
           ▼
      controller (HTTP API, default A2A port 8083, MCP on /mcp)
           │
           ▼
      agent pod (Python ADK or Go ADK runtime)
           ├──► LLM provider (ModelConfig)
           ├──► MCP tool servers (built-in / kmcp / remote / Service)
           └──► other agents (A2A delegation)
           │
           ▼
      PostgreSQL (sessions, events, memory vectors)
```

The Python runtime is built on Google ADK and supports Google ADK-native
features plus integrations with the CrewAI, LangGraph and OpenAI frameworks.
BYO agents are a separate mechanism (§5.8) and do not depend on it.

---

## 3. The CRD map

This is the mental model to hand a new engineer. Everything you configure is one
of these.

| Kind | API group/version | What it is |
|---|---|---|
| `Agent` | `kagent.dev/v1alpha2` | An agent. `spec.type` selects `Declarative` (YAML-defined) or `BYO` (your own container). |
| `SandboxAgent` | `kagent.dev/v1alpha2` | Same spec as `Agent`, but runs gVisor-sandboxed on Agent Substrate. Go runtime only; no `spec.skills`, no BYO. |
| `ModelConfig` | `kagent.dev/v1alpha2` | An LLM binding: provider, model, credentials, TLS, provider-specific options. |
| `ModelProviderConfig` | `kagent.dev/v1alpha2` | Provider-level configuration shared by model configs. |
| `RemoteMCPServer` | `kagent.dev/v1alpha2` | An MCP server reachable over HTTP/SSE. Supports `spec.tls` for private CAs (since 0.9.6). |
| `MCPServer` | `kagent.dev/v1alpha1` (kmcp) | An MCP server that kagent *deploys* for you — from your own image, or from an `npx`/`uvx` package. Replaces the old stdio `ToolServer`. |
| `Memory` | `kagent.dev/v1alpha1` | Persisted long-term-memory entries managed by kagent. |
| `AgentHarness` | `kagent.dev/v1alpha2` | Runs on Agent Substrate; requires the substrate integration to be enabled on the controller. |
| `ToolServer` | `kagent.dev/v1alpha1` | Legacy compatibility CRD still installed by the 0.9.12 CRD chart. Do not use for new integrations. |

Plus plain Kubernetes objects used as configuration surfaces:

- **`Service`** with `appProtocol: mcp` — turns any in-cluster service into a
  tool source. Discovery via label `kagent.dev/mcp-service: "true"`; path, port
  and protocol via `kagent.dev/mcp-service-*` annotations.
- **`ConfigMap`** — prompt template fragments.
- **`Secret`** — API keys, TLS material, tool auth headers, DB URL.

> **Do not build new integrations on `ToolServer`.** Upstream moved stdio tool
> servers to kmcp `MCPServer` and HTTP/streamable servers to
> `RemoteMCPServer` in 0.6. However, the installed 0.9.12 CRD chart still serves
> a Helm-managed `toolservers.kagent.dev/v1alpha1` compatibility CRD. Presence
> in API discovery is therefore not evidence that it is the current integration
> path. The built-in tool server in this run is connected by
> `RemoteMCPServer`.

---

## 4. Configuring the model — `ModelConfig`

### Supported providers

OpenAI · Anthropic · Azure OpenAI · Gemini · Google Vertex AI · Amazon Bedrock ·
**Ollama** · xAI (Grok) · SAP AI Core · **BYO OpenAI-compatible endpoint**.

The BYO OpenAI-compatible option is the strategic one for sovereign
deployments: anything that speaks the OpenAI API — vLLM, TGI, an internal
gateway — can be the model backend without kagent needing explicit support.

### Ollama (local, sovereign)

```yaml
apiVersion: kagent.dev/v1alpha2
kind: ModelConfig
metadata:
  name: default-model-config
  namespace: kagent
spec:
  provider: Ollama
  model: gpt-oss:20b
  ollama:
    host: http://ollama.ollama.svc.cluster.local
    options:
      num_ctx: "32768"        # string map
```

Two things bite here, and both are model problems rather than kagent problems:

1. **The model must support function calling.** kagent is a tool-calling
   framework; a model that cannot emit tool calls produces an agent that talks
   confidently and does nothing. Upstream states this requirement explicitly.
2. **Context window.** Agent loops with tool output are token-hungry. Set
   `num_ctx` deliberately and pair it with event compaction (§5.6).

At Helm-install time the default provider can be set directly, which creates a
`default-model-config` for you:

```bash
--set providers.default=ollama \
--set-string providers.ollama.model=gpt-oss:20b \
--set-string providers.ollama.config.host=http://<ollama>:11434 \
--set-string providers.ollama.config.options.num_ctx=32768
```

### Model scope in OK-129

No hosted reference model is configured. The Product Owner required the same
private Ollama `gpt-oss:20b` used by the rest of the platform. Quality is
therefore characterized with repeated identical requests, not a local/cloud
comparison.

Observed with the fixed `imagepull` diagnosis on the Go runtime: **10/10**
completed requests emitted well-formed, relevant tool calls and returned the
correct failure mode; no run had zero calls, looped, chose an irrelevant tool,
or invented an answer without a call. This supports bounded read-only diagnosis
with a narrow allow-list and hard RBAC. It is not evidence for unattended
writes; ten trials are a characterization, not an SLA.

Operational nicety: kagent **restarts agents automatically** when a referenced
Secret changes — API keys, TLS certs, `secretKeyRef` env vars. No manual rollout
to pick up a rotated key.

---

## 5. Configuring an agent — `Agent`

### 5.1 Skeleton

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: cluster-ops-agent
  namespace: kagent
spec:
  description: Inspects and (with approval) repairs workloads in this cluster.
  type: Declarative
  declarative:
    runtime: go                       # always set it explicitly — see §5.2
    modelConfig: default-model-config
    systemMessage: |
      You are an operations agent for a single Kubernetes cluster.
      Always gather evidence before proposing a cause.
      Never claim a state you have not read from the cluster.
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
```

Anatomy, in the order it matters:

1. **`systemMessage`** — the agent's behaviour. This is where most of the quality
   lives, and where most of the failure lives too.
2. **`tools`** — what it can actually do. The reviewed surface.
3. **`modelConfig`** — which brain.
4. **`runtime`** — Python or Go.
5. **skills, memory, context, deployment** — refinements.

### 5.2 Runtime: Python vs Go

| | Python ADK | Go ADK |
|---|---|---|
| Startup on `ok-kagent` | 17 s | 5 s |
| Working set on `ok-kagent` | 223,784,960 B (213.4 MiB) | 23,396,352 B (22.3 MiB) |
| Ecosystem | Google ADK, LangGraph, CrewAI, OpenAI frameworks | native Go |
| MCP / HITL / memory | yes | yes |
| Extra built-in tools | — | `SkillsTool`, `BashTool`, `ReadFile`, `WriteFile`, `EditFile` |

The installed 0.9.12 CRD reports **Python as the default** in
`kubectl explain agent.spec.declarative.runtime`. The latest generated API
reference reported `go` when checked, so documentation remained contradictory.
Set `runtime` explicitly on every agent; no manifest in this work relies on the
default.

Choose **Go** for anything that scales or restarts often; choose **Python** when
you need a framework integration. These measurements used the same agent and
declared resources; they replace the upstream estimates for this lab.

The Python image declares a named user and Kubernetes cannot verify
`runAsNonRoot` from that name. The v0.9.12 image defines UID/GID 1001; set both
numerically. A Python tool call is tagged `kagent_type` in A2A history, while Go
uses `adk_type`; evidence collectors must recognize both.

Note the Go runtime's built-in `BashTool`, `WriteFile`, `EditFile`: that is
arbitrary command execution and filesystem write inside the agent pod. If you
enable them, the pod's identity and security context *are* your security
boundary. See §7.

### 5.3 System prompts and prompt templates

System messages support Go `text/template` syntax, so shared fragments live once
in a ConfigMap and are pulled in by reference:

```yaml
spec:
  type: Declarative
  declarative:
    modelConfig: default-model-config
    promptTemplate:
      dataSources:
        - kind: ConfigMap
          name: kagent-builtin-prompts
          alias: builtin
        - kind: ConfigMap
          name: our-house-rules
    systemMessage: |
      You are {{.AgentName}}, operating in {{.AgentNamespace}}.
      {{include "builtin/safety-guardrails"}}
      {{include "builtin/kubernetes-context"}}
      {{include "our-house-rules/evidence-discipline"}}
      Tools available: {{.ToolNames}}
```

Shipped fragments in `kagent-builtin-prompts`: `skills-usage`,
`tool-usage-best-practices`, `safety-guardrails`, `kubernetes-context`,
`a2a-communication`.

Variables: `{{.AgentName}}`, `{{.AgentNamespace}}`, `{{.Description}}`,
`{{.ToolNames}}`, `{{.SkillNames}}`.

**Secrets are deliberately not allowed as a template data source** — upstream
excludes them so secret material cannot leak into a prompt sent to an LLM
provider. Good design; say so in customer conversations.

This is the mechanism that makes house rules enforceable rather than aspirational:
one reviewed `evidence-discipline` fragment, included by every agent.

### 5.4 Skills

Skills describe *capabilities* — they orient the agent toward goals and guide
tool use and planning. Three flavours:

| Kind | Where it lives | What it is |
|---|---|---|
| **A2A skills** | inline in `a2aConfig.skills` | Metadata only: id, name, description, tags, examples, input/output modes. No code — a machine-readable catalogue entry. |
| **Container skills** | OCI image, `spec.skills.refs` | Executable: scripts, procedures, behaviour modules, loaded at agent start. |
| **Git skills** | `spec.skills.gitRefs` | Same content, cloned from a repo instead of pulled as an image. |

```yaml
spec:
  skills:
    gitAuthSecretRef:
      name: git-credentials      # Secret with a `token` key
    gitRefs:
      - url: https://github.com/kubernauts/kagent-skills.git
        ref: main
        path: skills/kubernetes
```

Git and OCI can be combined on one agent. Both are discoverable through the
built-in `SkillsTool`. Container/Git skills work with **any** provider — they are
not tied to a specific model vendor.

Practically: skills are how you version operational know-how. A runbook the
agent can actually read is worth more than a runbook only humans read.

### 5.5 Memory

Opt-in, vector-backed long-term memory over the same PostgreSQL. Enabled by
pointing the agent at a `ModelConfig` whose **embedding** provider generates the
memory vectors — it need not be the agent's main LLM:

```yaml
spec:
  type: Declarative
  declarative:
    modelConfig: default-model-config
    memory:
      modelConfig: <embedding-model-config>
      ttlDays: 30                  # defaults to 15 when unset
```

- Adds three tools: `save_memory`, `load_memory`, `prefetch_memory`.
- Automatically extracts key information (intent, learnings, preferences) **every
  5th user message**.
- Requires **pgvector**. The bundled `postgres:18` does *not* have it — you need
  an external PostgreSQL with pgvector and `database.postgres.vectorEnabled: true`,
  or an overridden bundled image.

Upstream limits to know before promising anything: **no per-memory deletion, no
cross-agent memory sharing, not pluggable.**

Privacy consequence worth stating plainly: memory persists what users said,
including things they said carelessly, and there is no way to delete a single
entry. In a customer environment that is a data protection question, not a
feature toggle.

### 5.6 Context management (compaction)

Long conversations overflow the context window. Compaction summarises or drops
older events:

```yaml
spec:
  type: Declarative
  declarative:
    modelConfig: default-model-config
    context:
      compaction:
        compactionInterval: 5     # user invocations between compactions
        overlapSize: 2            # preceding invocations kept for continuity
        eventRetentionSize: 20    # most recent events always retained
        tokenThreshold: 24000     # post-invocation trigger
        summarizer:
          modelConfig: default-model-config # without this, compacted events are discarded
```

Without `summarizer`, compacted events are **discarded** — information is lost,
silently. With it, an LLM call produces a summary instead. On a small local
model, enable compaction *and* keep `tokenThreshold` well under `num_ctx`.

### 5.7 Deployment-level settings

Security context and pod security context are set on the agent itself:

```yaml
spec:
  type: Declarative
  declarative:
    deployment:
      podSecurityContext:
        runAsNonRoot: true
        runAsUser: 1001
        runAsGroup: 1001
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: false
```

A custom ServiceAccount per agent is supported (added in 0.8) — this is the hook
for per-agent RBAC scoping, and it is the *only* enforcement that actually holds
(§7).

### 5.8 BYO agents

`spec.type: BYO` runs your own container. The contract is the wire, not the
framework: kagent deploys the image and expects it to **serve the agent over the
A2A protocol on port 8080**. Upstream documents ADK, CrewAI and LangGraph BYO
paths.

```yaml
spec:
  description: Our own agent implementation.
  type: BYO
  byo:
    deployment:
      image: ghcr.io/kubernauts/our-agent:0.1.0
      env:
        - name: GOOGLE_API_KEY
          valueFrom:
            secretKeyRef:
              name: kagent-google
              key: GOOGLE_API_KEY
```

Why it matters: it keeps kagent from being a dead end. If the declarative model
runs out of expressiveness, you keep the Kubernetes-native lifecycle and swap
only the agent's internals.

---

## 6. Tools

### 6.1 Sources of tools

| Source | Reference shape | Use when |
|---|---|---|
| Built-in tool server | `kind: RemoteMCPServer`, `name: kagent-tool-server` | Standard Kubernetes/Helm/Argo/Prometheus/Grafana tooling |
| kmcp-deployed server | `kind: MCPServer` | You built the tool yourself and want kagent to run it |
| Remote MCP server | `kind: RemoteMCPServer` | Server lives elsewhere; supports `spec.tls` for private CAs |
| Kubernetes Service | `kind: Service` | An existing in-cluster service exposes MCP |
| HTTP / OpenAPI | discovery | An OpenAPI-compliant service in the cluster |
| Another agent | `type: Agent` | Delegation (§6.4) |

```yaml
tools:
  - type: McpServer
    mcpServer:
      name: kagent-tool-server
      namespace: tools            # cross-namespace: separate field, not "ns/name"
      kind: RemoteMCPServer
      apiGroup: kagent.dev
      toolNames:
        - k8s_get_resources
    headersFrom:
      - name: Authorization
        valueFrom:
          type: Secret
          name: tool-api-secret
          key: api-key
```

`toolNames` is the allow-list: only the named tools are exposed to the model.
`headersFrom` injects auth headers per request, resolved from Secrets/ConfigMaps
in the agent's namespace.

Since 0.6, cross-namespace references use a **separate `namespace` field** —
the old `namespace/name` string form fails. (The upstream *Tools* concepts page
prose still claims `namespace/name` works, while its own example uses the
separate field. The prose is stale; the release notes and API reference agree
with what is written here.)

### 6.2 Building your own tools with kmcp

kmcp gives you scaffolding for an MCP server, a local dev loop, and a control
plane to deploy it as an `MCPServer`. This is the extension point that decides
whether kagent fits a specific customer: their tooling — a CMDB, a ticket
system, a proprietary CLI — becomes an MCP server and the agent can use it.

If you plan to front kmcp servers with agentgateway, label the `MCPServer` with
`kagent.dev/discovery=disabled` so kagent does not discover it directly.

### 6.3 Human-in-the-Loop

Two mechanisms, both worth demonstrating to a customer within the first ten
minutes:

**Tool approval** — `requireApproval` lists the tools that must pause:

```yaml
tools:
  - type: McpServer
    mcpServer:
      name: kagent-tool-server
      kind: RemoteMCPServer
      apiGroup: kagent.dev
      toolNames:
        - k8s_get_resources        # runs immediately
        - k8s_describe_resource    # runs immediately
        - k8s_get_pod_logs         # runs immediately
        - k8s_apply_manifest       # pauses for approval
        - k8s_patch_resource       # pauses for approval
        - k8s_delete_resource      # pauses for approval
      requireApproval:
        - k8s_apply_manifest
        - k8s_patch_resource
        - k8s_delete_resource
```

The UI shows Approve/Reject with the payload the agent wants to apply. **A
rejection reason is passed back to the LLM as context**, so the agent adapts
rather than retrying blindly. Toggleable in the UI since 0.9.

**`ask_user`** — built into *every* agent, no configuration. The agent pauses
and asks, with single-select, multi-select or free-text answers. This is what
turns a guessing agent into a collaborating one.

Important framing for customers: `requireApproval` is a **workflow gate, not a
security boundary.** It constrains what the agent does *on purpose*. It does not
constrain what the agent's ServiceAccount *can* do. Both are needed.

### 6.4 Multi-agent

Any agent can be a tool of another agent:

```yaml
tools:
  - type: Agent
    agent:
      name: promql-agent
      namespace: observability
```

A2A-enabled agents are additionally exposed as **MCP servers** by the
controller, at `/mcp` on the A2A port (default 8083). So an agent is consumable
by any MCP client, not only by other kagent agents — that is the interop story.

Recommended shape for a customer demo: one fronting agent with a clear
description, delegating to two or three narrow specialists. It performs better
than one agent with twenty tools, and it *explains* better — you can point at
which specialist answered.

---

## 7. Security and permissions

This section decides whether we can responsibly deploy kagent at a customer.

### 7.1 What actually constrains an agent

| Layer | What it constrains | Strength |
|---|---|---|
| `systemMessage` | intent | **soft** — a prompt, nothing more |
| `toolNames` allow-list | which tools the model sees | **medium** — configuration, not enforcement |
| `requireApproval` | which tool calls need a human | **medium** — workflow gate; depends on a human paying attention |
| ServiceAccount RBAC | what the executing identity *can* do against the API server | **hard** — the only real boundary |
| `SandboxAgent` / gVisor + network allowlist | process and network isolation | **hard** for the runtime, orthogonal to RBAC |

Rule to carry into every customer conversation: **audit the executing identity,
not the agent definition.** An agent whose SA can delete deployments is a
delete-capable agent, whatever its prompt says.

### 7.2 RBAC scoping (changed in 0.9)

`rbac.clusterScoped` was **removed**. Scope now derives from `rbac.namespaces`:

| `rbac.namespaces` | Result | Watched |
|---|---|---|
| `[]` (default) | `ClusterRole` + `ClusterRoleBinding` | all namespaces |
| non-empty list | `Role` + `RoleBinding` per listed namespace | that list, unless `controller.watchNamespaces` overrides |

The chart **fails** if `rbac.clusterScoped` is still present, or if
`rbac.namespaces` is non-empty but omits the install namespace.

Default is cluster-wide. For a customer install, decide the namespace list
deliberately.

### 7.3 Authentication — and the gap

0.9 added OIDC via an `oauth2-proxy` subchart:

```yaml
controller:
  auth:
    mode: proxy            # default is "unsecure" — no auth at all
oauth2-proxy:
  enabled: true
  extraEnv:
    - name: OIDC_ISSUER_URL
      value: "https://idp.example.com"
    - name: OIDC_REDIRECT_URL
      value: "https://kagent.example.com/oauth2/callback"
```

With auth enabled, NetworkPolicies restrict UI and controller access to
oauth2-proxy, and `/api/me` returns the identity extracted from JWT claims.

> **The gap, stated plainly:** upstream says this release adds
> **"authentication only. Access control is not yet implemented."** It does not
> spell out the resulting visibility semantics — so assume any authenticated
> user can reach any agent until we have tested otherwise (**VERIFY** in the
> lab). Either way, any multi-tenancy claim we make must be built on our own
> layer, or not made. Default mode is `unsecure`, i.e. no authentication at all.

This is the single most important limitation for enterprise adoption. Lead with
it rather than being caught by it.

### 7.4 Sandboxing

`SandboxAgent` runs on **Agent Substrate**: the controller runs the agent as a
gVisor-sandboxed actor instead of a Deployment, snapshots it to object storage
when idle, and rehydrates it on demand. Network allowlists restrict which
external endpoints it may reach.

Prerequisites and traps:

- Install Agent Substrate (`oci://ghcr.io/kagent-dev/substrate/helm/{substrate-crds,substrate}`)
  and enable `controller.substrate.*` plus a `substrateWorkerPool` on the kagent
  chart.
- **Chart version matters.** Upstream requires kagent **0.9.7 or later**;
  against an older chart a `SandboxAgent` is *silently ignored* and the
  controller starts without the substrate integration. Easy to lose a day to.
- Go runtime only, no `spec.skills`, no BYO. (Upstream is inconsistent here: the
  0.9 release notes say network allowlists work "for both Go and Python
  runtimes", while the substrate example states Python ADK is not supported on
  substrate today. Treat Go-only as the working assumption — **VERIFY**.)

Use it for agents you do not fully trust — especially anything with `BashTool`
or write capability.

### 7.5 Egress

Agents talk to LLM providers. With a cloud provider, **cluster state, logs and
events leave the customer's network**. That is the data-protection conversation,
and it is why the local-Ollama path exists. Have both answers ready:

- sovereign: Ollama or a BYO OpenAI-compatible endpoint on-prem, no egress;
- convenient: hosted model, better quality, with a documented data flow.

`proxy.url` routes agent-to-agent and agent-to-MCP traffic through a gateway
(the controller rewrites internal URLs and sets `x-kagent-host`). External URLs
are not rewritten.

---

## 8. Persistence and day-2

### 8.1 PostgreSQL is mandatory

SQLite was removed in 0.8. Reasons given upstream: no pgvector, single-writer
prevents scaling the controller, and divergent SQL dialects.

| Setup | `bundled.enabled` | `url`/`urlFile` | Controller connects to |
|---|---|---|---|
| Default (dev/eval) | `true` | unset | bundled |
| Production | `false` | set | external |
| Migration | `true` | set | external (bundled kept for data movement) |
| Broken | `false` | unset | error |

Precedence: `urlFile` > `url` > bundled.

The bundled instance is `postgres:18`, credentials hardcoded to `kagent` in a
Secret, **no pgvector**. Fine for a demo; not a production database. For
production use an external PostgreSQL, keep the URL in a Secret and reference it
via `urlFile`.

### 8.2 High availability

`controller.replicas > 1` enables **leader election automatically** (Kubernetes
leases). One leader reconciles; the rest stand by and take over on failure. HA
requires PostgreSQL — which you now always have.

### 8.3 Upgrades

Since 0.9, schema changes are versioned migrations (golang-migrate + sqlc),
tracked in `schema_migrations` and `vector_schema_migrations`.

- Minimum prior version for 0.9 is **0.8.0**.
- **Back up the database first.** A fresh install on a fresh DB is the cleanest
  path.
- Failed migrations roll back automatically before the controller exits non-zero.
- A session-level advisory lock means only one replica migrates at a time.
- With `vectorEnabled: true`, pgvector availability is pre-checked.

Walk this path once in the lab. An upgrade you have never performed is not a
capability you can offer.

### 8.4 Observability

Three surfaces upstream: the **UI**, **prompt auditing**, and **tracing**.

Together they answer "what did the agent actually do?" — which in a write-capable
setup is not optional. Wire tracing into our observability stack
(ADR-Platform-018 territory when this ever comes back to the platform) and
confirm the trace shows tool calls, not just request spans.

---

## 9. Interfaces — what you hand to whom

| Interface | Who | Notes |
|---|---|---|
| **UI / dashboard** | operators, demos | `kubectl port-forward -n kagent svc/kagent-ui 8080:8080`, or `kagent dashboard` (prints `http://localhost:8082`). Approve/Reject lives here. |
| **CLI** | engineers | manage resources, `kagent invoke`, `--token` passthrough, local development without a cluster |
| **A2A endpoint** | other agents, integrations | default port 8083 |
| **MCP endpoint** | any MCP client | `/mcp` on the A2A port |
| **Integrations** | end users | documented examples for Slack and Discord over A2A, plus a Telegram bot |

The installed 0.9.12 chart exposes `svc/kagent-ui` on port 8080. The architecture
page's `svc/kagent 8001:80` example is stale for this release.

There is **no OpenAI-compatible `/v1/chat/completions`** in this list. kagent
speaks its own API plus A2A and MCP. That is exactly why Profile A needed a
facade — and, in the standalone case, why the UI *is* the product.

---

## 10. What kagent does not do

Honest limits, so a customer hears them from us first:

1. **No authorization.** Authentication exists; access control does not (§7.3).
2. **No OpenAI-compatible chat endpoint.** Fronting it with an existing chat UI
   requires an adapter.
3. **Quality is the model's, not the framework's.** kagent orchestrates. A small
   local model that cannot reliably emit tool calls yields a broken-looking agent.
4. **`requireApproval` is not a security control.** RBAC is.
5. **Memory needs pgvector**, which the bundled database does not have.
6. **CNCF Sandbox.** Breaking changes are documented and real: `v1alpha1` →
   `v1alpha2`, `ToolServer` removed, SQLite removed, `rbac.clusterScoped`
   removed — all within 0.6→0.9.
7. **No cost governance.** Nothing here budgets tokens. Bound iterations and
   timeouts yourself; an unbounded agent loop on a shared GPU starves every other
   consumer, and on a metered API it bills.

---

## 11. Reading the maturity honestly

CNCF **Sandbox** is the entry tier: it signals "worth watching", not "safe to
depend on". Combined with the observed rate of breaking changes, the responsible
customer position is:

- pin the version and treat upgrades as projects, not chores;
- own the deployment (charts, values, RBAC) in Git so an upgrade is reviewable;
- keep the agent definitions portable — descriptions, prompts and tool
  allow-lists are the assets, the CRD wrapper is replaceable;
- be explicit about who supports it: us, Solo's enterprise distribution, or
  nobody.

Before any customer commitment, re-check the current state — releases, open
issues, CNCF tier — rather than relying on this document. Requirement carried
over from the existing PoC guideline, and it is a good one.

---

## 12. References

- [kagent docs](https://kagent.dev/docs/kagent) — architecture, concepts, providers, operations
- [Release notes](https://kagent.dev/docs/kagent/resources/release-notes) — read before every upgrade
- [Helm chart configuration](https://kagent.dev/docs/kagent/resources/helm)
- [Tools ecosystem](https://kagent.dev/docs/kagent/resources/tools-ecosystem)
- [Human-in-the-Loop tutorial](https://kagent.dev/docs/kagent/examples/human-in-the-loop)
- [Operational considerations](https://kagent.dev/docs/kagent/operations/operational-considerations)
- [kagent releases on GitHub](https://github.com/kagent-dev/kagent/releases)
- Local: [`runbook.md`](runbook.md), [`evidence-protocol.md`](evidence-protocol.md)
