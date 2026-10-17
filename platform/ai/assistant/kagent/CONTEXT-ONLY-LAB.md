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
  restrictive controller-only ingress and *deny-all egress* NetworkPolicy targeting the expected lab Agent
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
   metadata. The current deny-all egress policy blocks these dependencies and cannot
   be a functioning deployment. **Never invent or broaden egress rules.**
5. Confirm NetworkPolicy implementation/CNI enforcement and other additive
   policies. Kubernetes NetworkPolicies are additive; this deny-all does not
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
paths and CNI behavior have been verified. At this stage the controller-only ingress plus deny-all egress policy is a security-oriented placeholder, not a deployable allowlist.

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
**Do not infer effective egress filtering from this alone.** The new policy
intentionally remains `egress: []` until trusted inspection of external
routes, Cilium enforcement and other kagent dependencies. The policy does
not yet permit the model call, so it is not a usable deployed configuration.

If a future private Gateway bypasses the controller and connects directly to
the agent, the ingress design must be revisited using an authenticated and
observed Gateway source identity; do not broadly open ingress.

## Updated policy-only dry run

After updating the local feature branch, re-run the two server-side dry-runs
above; neither creates a persistent Agent or NetworkPolicy. Confirm that the
admitted policy retains `namespaceSelector` **and** `podSelector` in a single
`from` entry (logical AND), and that `egress` remains the empty list.
