# OK AI Context-only Agent — private LAB manifest review

**Status: Draft; manifest review ONLY. No installation, no rollout, no
production readiness. Public Beta HOLD.**

This slice follows the approved gateway-owned retrieval architecture
(PR #390) and offline Gateway Context Envelope (PR #391).

## Artifacts

- `kagent/openkubes-docs-agent-context.lab.yaml`: independent
  `openkubes-docs-agent-context-lab` kagent Agent using existing
  `docs-ollama` ModelConfig and Go ADK runtime, with `tools: []`.
- `kagent/deploy/networkpolicy-context-agent.lab.yaml`: separate
  restrictive controller-only ingress and *Ollama-only egress* NetworkPolicy targeting the expected lab Agent
  pod label. **Do not apply it** until selector has been verified.
- Neither file is included in the existing Kustomization. Existing docs
  Agents, MCP Server, ModelConfig and production website are unaffected.

## Verification before even considering deployment

1. Confirm with the installed CRD that `spec.declarative.tools: []` is
   accepted as a valid no-configured-tools Agent. Admission may default or
   mutate tool lists; inspect server-side dry-run output.
2. **Runtime tool injection warning:** in kagent v0.9.12,
   `go/adk/pkg/agent/agent.go` calls `buildAgentTools`, which adds
   the built-in `ask_user` tool even when configured tools are empty.
   Thus `tools: []` does **not** prove the agent has literally zero runtime
   tools. Assess whether this affects the no-tools threat model.
3. Confirm generated Pod selectors for this Agent. A NetworkPolicy with
   a wrong podSelector does not isolate anything. Verify the actual Pod's
   `app.kubernetes.io/name` label (and any controller defaults).
4. Confirm kagent's required DNS, A2A and Ollama endpoints, namespaces,
   ports, and appropriate scoped label selectors from live trusted cluster
   metadata. The current single-destination Ollama egress policy may block other runtime dependencies and cannot be considered ready for deployment until checked. **Never invent or broaden egress rules.**
5. Confirm NetworkPolicy implementation/CNI enforcement and other additive
   policies. Kubernetes NetworkPolicies are additive; this proposal does not
   cancel an independent policy that already allows traffic to lab pods.
   Check isolation by effective policies, not YAML inspection alone.
6. Do not rely only on the system message for prompt-injection prevention.
   The Gateway must strictly validate all answer sources and render only
   canonical indexed links. No model-generated evidence receipts.

## Server-side dry run (operator only, NO persisted objects)

From `platform/ai/assistant`:

```sh
kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n openkubes-assistant \
  apply --dry-run=server -f kagent/openkubes-docs-agent-context.lab.yaml

kubectl --kubeconfig "$HOME/.kube/ok-kagent.yaml" \
  --context ok-kagent-admin@ok-kagent \
  -n openkubes-assistant \
  apply --dry-run=server -f kagent/deploy/networkpolicy-context-agent.lab.yaml
```

Server-side dry-run does **not** prove runtime network isolation,
injected tools, deployed generated Pod labels, or absence of side effects
from unusual admission webhooks. These require separate review.

## Operator hold

**Do not run real `kubectl apply` or update the existing kagent
Kustomization.** Wait for an explicit separate deployment approval after
the CRD check, actual pod selectors, runtime tool assessment, all network
paths and CNI behavior have been verified. At this stage the controller-only ingress plus Ollama-only egress policy is a security-oriented **unverified proposal**, not a deployable allowlist.

A later separate PR should wire the private gateway's existing validated
context envelope into a dedicated allowlisted loopback A2A path and report
retrieval/delivery/format checks separately from semantic grounding.

## Observed A2A controller identity (operator evidence, 2026-10-17)

Hubble on the worker hosting both existing JSON Agent and controller observed
`kagent/kagent-controller-6b9444b6f7-h6dsh` (`10.36.1.53`) initiate TCP
traffic to `openkubes-docs-agent-json` (`10.36.1.9:8080`) concurrently with
a private A2A probe. Cilium reported `FORWARDED` for SYN/ACK/data packets.
This grounds the draft ingress rule selecting **both** namespace `kagent`
and pod labels `app.kubernetes.io/name=kagent` plus
`app.kubernetes.io/component=controller`, TCP 8080. The A2A response was
`REJECT / invalid_sources`, an independent answer-quality issue.

ModelConfig `docs-ollama` uses `192.168.100.202:11434`. This address is not
equal to any reported Kubernetes Node InternalIP. Cilium config reports
`enable-policy=default`, `routing-mode=tunnel`, `kube-proxy-replacement=true`.
**Do not infer effective egress filtering from this alone.** The new policy now proposes a single `ipBlock: 192.168.100.202/32` TCP 11434
Ollama egress allowance. This has **not been applied or enforcement-tested**.
Additional runtime dependencies and Cilium effective-policy verification
remain deployment blockers.

If a future private Gateway bypasses the controller and connects directly to
the agent, the ingress design must be revisited using an authenticated and
observed Gateway source identity; do not broadly open ingress.

## Updated policy-only dry run

After updating the local feature branch, re-run the two server-side dry-runs
above; neither creates a persistent Agent or NetworkPolicy. Confirm that the
admitted policy retains `namespaceSelector` **and** `podSelector` in a single
`from` entry (logical AND), and that `egress` permits only `192.168.100.202/32:11434` TCP.

## Observed Ollama flow (operator evidence, 2026-10-17)

Live Hubble on `cilium-rc5zz` observed the existing JSON Agent connect to
`192.168.100.202:11434` over TCP (SYN, ACK, PSH; `FORWARDED`). Cilium
reported both the agent-to-destination flow and an egress flow using Node
IP `10.44.1.237` as source. This demonstrates the **current Agent's traffic
path and source NAT**, not enforcement of the proposed policy for a new Pod.
A later authorized isolated trial must confirm permitted Ollama traffic and
denial of docs MCP, Kubernetes API and unrelated destinations. Cilium's
`enable-host-firewall=false` is not itself proof of Pod egress failure.

The concurrently executed private structured probe returned
`REJECT / unsupported_text` with one retrieved chunk. This is a separate
model-output format failure; do not weaken the answer validator or classify
it as an egress problem.

## Deployment security review — 2026-10-17

**Decision: rollout is NOT authorized by this review.** The operator approved
preparation and review, not a cluster deployment.

### Reviewed source behavior (upstream kagent tag v0.9.12)

- `go/adk/pkg/agent/agent.go` builds configured HTTP/SSE MCP toolsets from
  `agentConfig.HttpTools`/`SseTools`, remote A2A tools from
  `RemoteAgents`, and local memory/skills tools when those capabilities
  are configured. The Context Lab manifest configures none of them.
- `buildAgentTools()` unconditionally creates `ask_user`. Its implementation
  in `go/adk/pkg/tools/ask_user.go` requests user confirmation, suspends the
  task and later formats provided answers. **It cannot itself retrieve docs,
  run shell commands or access Kubernetes.** It is still a tool: never assert
  the runtime is completely tool-free.
- The existing A2A `extract_answer()` accepts only completed tasks. A
  paused task for `ask_user`, or invalid/extra JSON, must fail closed.
  Verify pending-task behavior during the isolated integration test.
- A no-tools manifest and a deny-by-policy network profile are different
  safeguards. No external tool access is configured, but runtime behaviors
  and injected components must be checked against the generated Deployment.

### Risk matrix

| Risk | Current evidence | Required for isolated rollout |
| --- | --- | --- |
| API/CRD acceptance | Both agent and policy server-side dry-run PASS | None for admission; compare actual admitted manifest |
| Controller ingress | Hubble confirmed controller to existing JSON Agent:8080 | Verify effective policy for new Agent labels |
| Ollama egress | Hubble confirmed existing JSON Agent to 192.168.100.202:11434 with SNAT | Prove new policy allows this and rejects other destinations |
| Implicit ask_user | Source code confirmed; no external tools in handler | Reject non-completed/interactive task, never forward confirmations |
| Additional tools | No configured MCP/remote/memory/skills in manifest | Inspect generated Deployment and runtime logs without raw user data |
| Pod identity | Existing generated Agents have app.kubernetes.io/name labels | Inspect new generated Pod labels after explicitly authorized rollout |
| NetworkPolicy isolation | Cilium active; current only two policies select docs-search | Positive and negative Cilium verdicts for selected new Pod |
| Prompt injection | System message asks model to ignore untrusted snippets | Offline/online adversarial tests and deterministic gateway checks |
| Production readiness | No gateway integration or semantic validation | NOT in scope; Public Beta HOLD |

### Preconditions before separate authorization

1. Confirm from the operator that the deployment is **private lab only** and
   that the exact Agent and NetworkPolicy manifests are approved. No changes
   to `docs-ollama`, existing Agents or MCP server.
2. Confirm the server-side dry-run still succeeds on the reviewed commit.
3. Check with the operator that applying a new Agent CRD and NetworkPolicy
   does not violate cluster change-control or allocate unexpected resources.
4. Plan explicit rollback of **only** the named context-lab Agent and named
   lab NetworkPolicy. Do not delete namespaces, shared ModelConfigs or other
   Agents. Record status and compare existing agent readiness before/after.
5. When authorized, apply the policy **before** creating the lab Agent to
   avoid an interval with unrestricted Pod egress; verify label selection.
   If Cilium does not select the generated Pod or network behavior differs,
   terminate the lab experiment and roll back only new lab resources.
6. On the isolated runtime, positively test Ollama and controller A2A, then
   test denial of docs MCP, Kubernetes API and unrelated Internet destinations
   from the lab Pod. Do not rely on a single successful Ollama call as proof
   of default-deny isolation.
7. **No raw user prompt, document content, model reply or credentials in
   shared logs.** Hubble network metadata and sanitized status labels only.

### Non-goals

No signed gateway retrieval receipt yet; no proven model consumption;
no semantic-grounding guarantee; no production/public availability.
