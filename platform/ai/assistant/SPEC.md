# OK AI Documentation Assistant — Gateway-owned RAG & Default Agent Specification

**Version:** Draft v1.0 (2026-10-17)  
**Status:** Proposed, non-normative until reviewed and accepted. **Public Beta: HOLD.**  
**Scope:** Documentation question answering only, not general-purpose Agentic Operations.  
**Tracking:** [OK-202](https://kubernauts.atlassian.net/browse/OK-202); [PR #392](https://github.com/openkubes/openkubes/pull/392).  
**Existing parent specification:** [OK-202 Confluence](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3168894977) — requires owner review and reconciliation.

## 1. Purpose and decision

The **Context-only Agent SHOULD become the default backend for OK AI Documentation Q&A only after all acceptance gates in this document pass**. It is **not** the universal default agent for cluster diagnostics or operations, and is **not** the current public default. The browser demo remains unconnected and unchanged.

The architecture uses **Option B: Gateway-owned Retrieval**. Trusted OpenKubes gateway code owns retrieval, context assembly, source allowlisting and response validation. The context-only kagent instance performs generation with a private Ollama model, without configured MCP or Kubernetes tools. The untrusted model is not an authority over sources, operations or evidence.

The exact implementation of OK AI's future gateway routing and default agent selection is **not yet deployed**. This document defines the target behavior, not a declaration of present readiness.

### Normative terms

**MUST**, **MUST NOT**, **SHOULD**, and **MAY** describe proposed requirements for the eventual accepted specification. Existing prototype behavior and future requirements are separately labeled below.

## 2. Architecture and responsibility boundaries

```text
Documentation question
        |
        v
Authenticated OK AI Gateway (future)
   |-- validate question, authorize/rate-limit (future public gateway)
   |-- load one reviewed, pinned documentation index
   |-- DocsRetriever.docs_search(question, limit <= 8) ONCE
   |-- construct + hash bounded Context Envelope v0.1
   |
   +--> allowlisted private A2A route via kagent Controller
                 |
                 v
          Context-only kagent Agent
          no configured external tools
                 |
                 v
          Ollama (private model endpoint)
                 |
                 v
          Structured Answer v0.1 JSON
                 |
                 v
   Gateway strict validation and deterministic link rendering
                 |
       acceptable reply / fail-closed response
```

**Indexing:** `indexer.py` builds the reviewed public GitHub documentation index at pinned commits; the index contains stable source IDs and content digests. Indexing contacts GitHub at build time and is not a per-question external fetch.

**Retrieval:** `docs_mcp.py` contains reusable `DocsRetriever` logic. In Option B the **trusted Gateway calls the retriever directly**; the context-only Agent MUST NOT call `docs_search` or choose additional documents. This baseline is lexical retrieval, **not yet quality-validated production RAG**. The original MCP-enabled Agent remains a separate PoC and is not a fallback that may silently bypass the gateway policy.

**Generation:** the context-only Agent receives only the bounded question and approved snippets as *untrusted data*. Prompt instructions are not a security boundary. No cluster changes are permitted through this documentation route.

**Validation and display:** the trusted Gateway validates answer structure, permitted source IDs and canonical URLs independently; model-authored links and arbitrary Markdown are not rendered. Passing syntactic/source validation does **not** prove every statement is supported.

## 3. Versioned contracts

| Contract | Current source of truth | Required behavior |
| --- | --- | --- |
| Document/index integrity | `indexer.py`, `docs_mcp.py` | Reviewed allowlist, pinned commit hashes, chunk SHA-256 and canonical URLs |
| Gateway retrieval | `public_beta/GATEWAY-OWNED-RETRIEVAL-SPIKE.md` | One authoritative retrieval per request, maximum 8 hits, empty retrieval fails closed |
| Context Envelope v0.1 | `public_beta/GATEWAY-CONTEXT-v0.1.md`, `public_beta/gateway_context.py` | Exact source IDs/snippets, content/index/retrieval digests, deterministic JSON and bounded payload (prototype maximum 24 KiB) |
| Private A2A transport | `public_beta/private_a2a_probe.py` (reference implementation only) | Fixed localhost allowlist, no redirects, timeouts, bounded response, only completed tasks accepted |
| Structured Answer v0.1 | `public_beta/STRUCTURED-ANSWER-v0.1.md`, `public_beta/structured_answer.py` | Strict JSON steps and source IDs; no arbitrary links, HTML, shell commands or invented references |
| Evidence | `public_beta/provenance_receipt.py` (MCP-only offline v0.2) | A future **distinct** gateway-retrieval evidence type; do not label trusted gateway retrieval as an MCP call |
| Agent isolation | `kagent/CONTEXT-ONLY-LAB.md`, `kagent/deploy/networkpolicy-context-agent.lab.yaml` | Enforced controller ingress and private Ollama-only egress, plus runtime/tool review |

Do not introduce a competing envelope schema in this SPEC. Changes to existing contracts require their own versioned review and regression tests.

### Proposed gateway request lifecycle

1. Validate question (current probe restricts to 1–500 characters); for public use authenticate and authorize the caller, apply quota and create a cryptographically random request identifier.
2. Pin **one** valid document index for the entire request. Invoke trusted retrieval **exactly once**; if no matches, return a fixed `NO_SOURCES` state.
3. Verify returned passages against the same pinned index and build the deterministic bounded Context Envelope, treating every snippet as untrusted.
4. Transmit to a **separately allowlisted context-only A2A endpoint** using a private/loopback route. A successful submission or completed A2A task is evidence of exchange, **not evidence of what the LLM consumed**.
5. Require a **completed** A2A task, a size-bounded text artifact and strictly parsed Structured Answer v0.1 JSON. Reject `ask_user` interruptions or pending/interactive task states; never forward confirmation prompts.
6. Validate with `validate_and_render(raw, retrieved, pinned_index)`; derive visible links exclusively from the pinned trusted index. Return a fixed fail-closed status on any mismatch.
7. Keep separate internal outcomes for retrieval integrity, context delivery, format/source validation and semantic grounding. Never produce a single ambiguous `PASS` attesting to all of them.

### Fail-closed outcomes

The Gateway MUST distinguish `NO_SOURCES`, transport/timeout errors, incomplete A2A tasks, malformed/unsupported JSON, unknown source IDs and policy-restricted output. Invalid responses MUST NOT be silently repaired, retried against a less-restricted tool-enabled agent or shown raw to users. Sanitized fixed reason codes only are permitted in ordinary logs; exact public error copy remains to be specified.

## 4. Default routing and future agents

**Proposed default after approval:** documentation and onboarding queries route to the Context-only Documentation Agent. The routing/gateway layer is responsible for selection, not the model itself. Other agent types (read-only diagnostics, operational proposals or authorized runner workflows) require **separate** declared capabilities, authorization and contracts. No execution permission is inherited from the docs route.

Before activation: existing `openkubes-docs-agent`, `openkubes-docs-agent-json` and the public static widget remain unchanged. Any promotion to default must be explicit, reversible and covered by regression tests; there is currently **no automatic default switch**.

**Platform interface alignment:** [ADR-Platform-015](../../../architecture/decisions/ADR-Platform-015-agentic-ai.md) identifies the Agent Interface Contract v1 as OpenAI Chat Completions + Tool Calling, with other transports as future evolution. The **private** kagent A2A hop specified here is an internal integration and does not silently redefine the public/platform interface. Contract-level alignment, including ownership of the frontend API, must be reviewed separately.

## 5. Security and trust boundaries

- **Documentation content is adversarial input.** A pinned hash identifies exact material; it does not make the content safe or truthful. Prompt injection, cross-document conflicts and malicious instructions require tests and rejection policies.
- The lab context-only Agent has `tools: []`, but upstream kagent **v0.9.12 injects `ask_user` unconditionally**. It has no configured docs MCP, Kubernetes, network, shell, skills, memory or remote subagent tools. Treat `ask_user` as an interactive state to reject, not proof of literal zero runtime tools.
- Egress NetworkPolicy allows `192.168.100.202/32:11434/TCP` and ingress selects the kagent controller in namespace `kagent` on TCP 8080. These are lab-specific observed endpoints, **not a portable production policy**.
- Cilium's observed implicit `allow-localhost-ingress` host identity exception means that an absolute 'controller is the only possible ingress source' claim is not yet proven. Review effective host-path behavior before any public release.
- Deny direct browser-to-kagent/browser-to-Ollama access; do not grant arbitrary tool or Kubernetes API permissions to the documentation agent.
- Public gateway needs authentication, authorization, abuse/rate controls, resource bounds, privacy and retention policy, vulnerability review and a secure transport boundary. None are implied by lab connectivity.
- No secrets, raw user prompts, source excerpts, raw model answers or signing keys in shared logs. Evidence signing keys reside only with a trusted issuer.
- The MCP-specific offline provenance receipt v0.2 MUST NOT be reused to certify gateway retrieval. A separate signed gateway-retrieval receipt with issuer, audience, request/index/context binding, expiry and replay protection is future work.

## 6. Status and observed lab evidence (2026-10-17)

**Implemented and observed:**
- Pinned index/retriever, deterministic Context Envelope v0.1 and strict Structured Answer v0.1 validator exist with offline tests.
- Private `openkubes-docs-agent-context-lab` has been installed and observed `Ready=True`, with a matching Cilium policy and ingress/egress enforcement enabled.
- A **temporary, separately labeled security probe Pod** successfully connected to private Ollama (`HTTP 200`) while Hubble independently confirmed `EGRESS DENIED`/`Policy denied DROPPED` to docs MCP, the translated kube-apiserver endpoint and an unrelated external address.
- That temporary probe Pod was **deleted** after the tests. Original and JSON documentation Agents and docs-search server remained Running.

**Not yet proven:** a complete trusted Gateway → Context Envelope → private A2A → Context-only Agent → Ollama → Structured Answer → Gateway rendering flow. The separate test Pod's enforcement does not prove the model's runtime behavior. Format failures (`invalid_sources`, `unsupported_text`) observed on the *JSON Agent* remain unresolved quality signals, not network faults.

**No semantic grounding proof:** Valid source IDs and transport completion are not evidence that a model read particular snippets or that every generated claim is correct.

## 7. Acceptance gates before default/private integration and public beta

### Gate A — private context-only end-to-end (next implementation PR)

- [ ] Dedicated allowlisted private A2A probe for the context-only Agent; do not modify existing JSON Agent probe's fixed endpoint allowlist ad hoc.
- [ ] Gateway selects a pinned index, retrieves once and sends the **exact encoded envelope** to the intended context-only Agent.
- [ ] Confirm actual Controller → context-only Agent flow and Agent → Ollama flow with Hubble, while preserving tested egress isolation.
- [ ] A completed task passes Structured Answer validation against the *same request's* gateway retrieval, or fails closed with a sanitized reason.
- [ ] Negative tests cover forged source IDs, malformed JSON, untrusted prompt injection and incomplete/paused `ask_user` tasks.
- [ ] Unit/regression and repeated private integration tests run without modifying the public widget or existing Agents.

### Gate B — correctness and operational readiness

- [ ] Representative, reviewed question set (at least the README's planned 30+ questions); retrieval recall, citation support and abstention measured.
- [ ] Separate semantic-grounding checks for every material factual/operational claim; demonstrate safe handling of unsupported instructions.
- [ ] Explain limitations of lexical retrieval, assess hybrid search only if evaluation warrants it.
- [ ] Implement explicit agent selection/default routing with rollback and deployment/monitoring guidance.
- [ ] Reconcile this document with OK-202 Confluence parent Spec and ADR-Platform-015 interface versioning.

### Gate C — public release (explicit later approval only)

- [ ] Authenticated public API, quotas, privacy/retention review, observability without raw content, ingress/TLS and dependency/CVE clearance.
- [ ] Independently review Cilium host exception, workload isolation and Gateway ingress/identity.
- [ ] Review versioned gateway provenance evidence and replay protection; do not overstate its semantic guarantees.
- [ ] Document release owner decision and rollback criteria, then separately approve any public website/chat integration.

**Until every applicable gate is met, the public website is unchanged and Public Beta remains HOLD.**

## 8. Implementation plan and ownership

1. **Current PR #392:** Context-only Agent private lab manifests and reviewed Cilium allow/deny evidence; this SPEC is a **draft review artifact**, not a readiness claim.
2. **Next separate PR:** a private Gateway-owned retrieval → deterministic envelope → context-only A2A probe and fail-closed structured response validation, with integration tests.
3. **Following work:** gateway-retrieval evidence type, semantic QA benchmark, default routing/rollback, and public gateway security gates.
4. **Review owners:** OK-202 maintainers and the OpenKubes architecture/security reviewers; final sign-off to be recorded in PR/Jira/Confluence. Specific individuals and dates are to be confirmed.

## 9. Related specifications and source of truth

- [OK-202 README](./README.md) and [PoC validation](./POC-VALIDATION.md)
- [Gateway-owned retrieval architecture](./public_beta/GATEWAY-OWNED-RETRIEVAL-SPIKE.md) (PR #390)
- [Gateway Context Envelope v0.1](./public_beta/GATEWAY-CONTEXT-v0.1.md) (PR #391)
- [Structured Answer Contract v0.1](./public_beta/STRUCTURED-ANSWER-v0.1.md)
- [Context-only Lab and Cilium evidence](./kagent/CONTEXT-ONLY-LAB.md) (PR #392)
- [ADR-Platform-015: Agentic AI](../../../architecture/decisions/ADR-Platform-015-agentic-ai.md)
- [OK-202 parent Confluence Spec](https://kubernauts.atlassian.net/wiki/spaces/OpenKubes/pages/3168894977)

This document integrates the above designs without superseding their actual
protocol definitions or retroactively claiming a production implementation.
