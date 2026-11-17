# NVIDIA Confidential Containers Can Protect AI Inference. But Who Controls the Agent?

*Why confidential computing, governed tool access, and operational authority must remain separate.*

*OpenKubes Architecture · November 2026 · Architecture exploration*

> **Status: Architecture proposal — not an integration announcement.** NVIDIA Confidential Containers is an existing upstream reference architecture, **not a validated OpenKubes integration**. OpenShell (ADR-Platform-042, Proposed) and optional CMCP (ADR-Platform-044, Draft/Proposed) are also not production-qualified integrations. The end-to-end agent-to-execution-to-evidence path described here is a **target architecture**, not a demonstrated production workflow. No new deployment, pilot, repository, provider selection, or engineering budget is authorized by this article.

![Conceptual OpenKubes architecture showing hosted or external agents, two optional and independent boundaries for governed tool access and confidential inference, and a separate customer-owned trust domain for protected human approval, policy, deterministic execution, Kubernetes reconciliation, and independent evidence. All integrations are proposed or unvalidated.](nvidia-confidential-containers-agent-authority.svg)

*Figure: Responsibilities and trust boundaries — not an implemented integration map. Solid lines describe the intended operation path; dashed lines describe optional inference and direct-access paths. The confidence of a confidential-computing attestation is not evidence that a Kubernetes change succeeded.*

## An AI assistant investigates a banking incident

A payment application stops responding. Monitoring shows that several Kubernetes workloads are not becoming ready. The operator asks an AI assistant:

> Why is the payment application failing in the production cluster?

Using approved tools, an AI agent could retrieve workload status, events, relevant logs, the last deployment revision, and a runbook. It might identify an image-pull problem or a recently changed configuration and recommend a corrective action.

That sounds useful. But four independent questions now matter:

1. **Where can this agent run, and what can it reach?** A malicious instruction embedded in a log should not grant access to credentials or unrelated networks.
2. **Which tools and targets may it use?** A developer's diagnostic access to a test namespace must not expand into production-wide visibility.
3. **Who can see the context sent to the model?** Diagnostic data may expose architecture, internal identifiers, configuration, or accidentally logged secrets.
4. **Who decides whether the proposed fix can change production — and how will we verify the outcome?** A plausible recommendation and a successful tool call are not authority or evidence of convergence.

These are different problems. An MCP connection answers none of them by itself. A more capable model does not remove them either.

**Connecting an agent to Kubernetes is easy. Giving it authority to change Kubernetes is a separate, much harder engineering decision.**

## Four boundaries, four responsibilities

### 1. Isolate the agent runtime

Agents read documents and logs, call APIs, and sometimes execute code. Untrusted content can contain prompt-injection instructions that attempt to change the agent's behavior. Prompt instructions are not reliable security boundaries. Credentials, filesystem access, network egress, process isolation, and resource consumption need controls enforced outside the model.

[OpenShell](https://github.com/NVIDIA/OpenShell) is a **candidate**, under [ADR-Platform-042](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-042-openshell-hosted-external-agentic-operations.md), for a platform-hosted agent runtime with constrained execution and access. Its suitability, tenant isolation, failure modes, and lifecycle have not been validated in OpenKubes.

We also intend to support **external agents** running in independently managed environments. They must be able to use the same bounded platform interfaces without installing OpenShell. A safe runtime can constrain what the agent reaches; it cannot decide whether an operational change is justified.

### 2. Govern access to tools and information

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) gives agents a standard way to discover and invoke tools. It helps interoperability but does not, by itself, solve authorization for each customer, cluster, namespace, or operation.

Our proposed **CMCP** design ([ADR-Platform-044](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-044-cmcp.md)) is an **optional**, provider-neutral access layer over approved OpenKubes capabilities. It could help with scoped tool discovery, routing, and request correlation. A gateway such as Obot is one evaluation candidate, not a selected dependency.

Crucially, OpenKubes-owned HTTP/OpenAPI contracts remain normative where defined. MCP is a bounded projection, not a second platform API or a source of execution truth. Backends must still authenticate and authorize the exact caller, tenant, target, and operation — including when a client connects directly instead of using a gateway.

Neither an MCP server nor a gateway gets a privileged shortcut to the Contract Executor, protected approval, or authoritative desired state.

### 3. Protect sensitive AI inference

Now we reach a security concern that is easy to overlook.

The agent may have legitimate permission to read Kubernetes events and logs. Yet, to reason about them, it often sends a prompt and retrieved context to an inference service. This can include internal network names, deployment configurations, troubleshooting details, regulated data inadvertently present in logs, or sensitive incident timelines.

**Data minimization must come first.** The platform should avoid retrieving unnecessary data, redact secrets, enforce source permissions, and avoid forwarding sensitive content simply because a model requests it. Even after these precautions, some valid diagnostic context may remain confidential.

Transport encryption protects data on the way to the inference service; encryption at rest protects stored data. During ordinary computation, however, plaintext is typically accessible to the application and, depending on the environment and threat model, potentially to privileged infrastructure components.

**Confidential Computing aims to reduce that exposure *while the data is being processed*.** It introduces hardware-enforced isolation, measurable execution environments, and mechanisms for verifying a workload before releasing protected resources.

This does not make a model truthful, immune to prompt injection, or automatically compliant with every regulatory requirement. It addresses a different question: *Who must be trusted with the data during inference?*

### 4. Keep operational authority separate

An isolated agent, a scoped tool call, and confidential inference may all work exactly as designed — and the agent may still recommend the wrong action.

OpenKubes therefore proposes a strict separation between **reasoning** and **authority**. Agents may investigate and submit **non-authoritative candidates**. The trusted platform owns identity, provenance, canonicalization, protected human approval, policy evaluation, transition-bound authorization, deterministic execution, desired-state acceptance, controller reconciliation, and independently sourced evidence.

No model output, inference attestation, gateway audit event, or agent success message can substitute for those responsibilities.

**AI proposes. Trusted systems authorize and execute. Independent evidence verifies.**

## Why NVIDIA Confidential Containers is an interesting reference architecture

For the confidential inference boundary, our **first reference candidate** is [NVIDIA Confidential Containers](https://docs.nvidia.com/confidential-computing/containers/overview). NVIDIA documents a Kubernetes deployment architecture combining upstream open-source building blocks with supported NVIDIA Confidential Computing technology. Its initial generally available reference architecture was released in April 2026.

Here is the idea in practical terms:

- **Kubernetes** schedules and manages the workload, but Kubernetes admission or a pod being `Running` does not by itself establish confidential execution.
- **Kata Containers** runs a pod inside a lightweight virtual machine, rather than sharing the ordinary container host kernel boundary.
- **Supported confidential CPUs and NVIDIA GPUs** provide hardware-backed isolation and measurements for the CPU/GPU workload, subject to particular hardware, firmware, runtime, and topology requirements.
- **Trustee** coordinates attestation and conditional key release. It checks evidence against independently configured trust and reference-value policies before sensitive resources are released to a verified environment.
- **The application and its client** must still establish a secure, correctly bound data path. Hardware attestation alone does not prevent a badly designed application from logging or exfiltrating plaintext.

### A concrete example: verify before releasing sensitive context

Imagine an organization has an encrypted model artifact or a protected inference secret. Before releasing it, a trusted component requests cryptographic attestation evidence about the confidential workload. The configured verifier checks that evidence against approved platform measurements and policy. If verification fails or the trust context is incomplete, the secret must **not** be released.

The protected workload can then process authorized context inside the measured environment, provided the entire data path and application configuration satisfy the intended security profile.

This is more meaningful than simply believing the words *"running in a secure container."* It offers a technical mechanism for verifying certain properties of the computing environment.

But attestation must be interpreted precisely: **it establishes bounded properties of an execution environment; it does not prove that an AI answer is correct, that prompts contain no sensitive information, or that a Kubernetes operation has converged.**

### What NVIDIA Confidential Containers does not solve

Confidential Containers is not a drop-in capability for arbitrary Kubernetes clusters. NVIDIA's documented deployment requires specific supported hardware/software configurations; the reference implementation also has restrictions around GPU allocation, container runtime, and virtualization. Teams must evaluate capacity, drivers, patching, upgrades, recovery, and price/performance.

It also combines **open-source components with NVIDIA-specific hardware and software**. We should not describe the entire stack as vendor-neutral or entirely open source.

OpenKubes has **not** validated this integration. The reason to study it is architectural: it illustrates a possible *self-hosted, Kubernetes-native Confidential Inference profile* that may give an enterprise more deployment control than a managed API.

For technical detail, see [NVIDIA's reference architecture](https://docs.nvidia.com/confidential-computing/containers/overview), [supported features and limitations](https://docs.nvidia.com/confidential-computing/containers/overview#limitations-and-restrictions), and [Confidential Containers Trustee attestation](https://confidentialcontainers.org/docs/attestation/).

## What about Privatemode AI and Tinfoil?

Self-hosting confidential GPUs is not the right operational choice for every organization. It may require specialized infrastructure, an inference operations team, model lifecycle management, and ongoing capacity investment.

A managed confidential inference service may be a better fit for some workloads. [Privatemode AI](https://docs.privatemode.ai/) by Edgeless Systems and [Tinfoil](https://tinfoil.sh/inference) are two alternatives worth evaluating. They offer different approaches to privacy-preserving inference and verification without requiring every customer to operate a full GPU infrastructure stack.

**Neither is selected, integrated, independently validated, or qualified for regulated OpenKubes deployments.** We also do not assume that the services provide identical threat models or equivalent verification. Each needs separate assessment of attestation, data paths, identity, retention, data residency, licenses, operational availability, audit rights, and exit arrangements.

For OpenKubes, the architectural target is a replaceable **inference-provider profile**. An organization may choose an approved self-hosted implementation or a managed service, subject to its own security requirements. Switching providers must not silently downgrade mandatory attestation, data handling, or other trust conditions. If a required protection cannot be established, that inference request should fail closed instead of falling back to an unverified provider.

**Own the contracts, not the components.**

## A safe incident journey: from observation to independently verified outcome

Let's return to the failing payment application. The following sequence describes our **proposed end-to-end architecture**, not an implemented OpenKubes workflow.

**1. Observe.** An operator or monitoring signal identifies an incident. The request has an authenticated identity and a permitted investigation target.

**2. Investigate.** The agent uses approved read-only diagnostics — optionally exposed through CMCP/MCP — to retrieve scoped events, workload conditions, and source-linked runbooks. The backend enforces the actual resource scope. The agent may use an approved inference provider to interpret minimized context; if confidential inference is required, its verification profile must pass.

**3. Propose.** The agent suggests a configuration change as a **candidate only**. The candidate has no authority to modify Kubernetes, protected Git references, policy, or grants.

**4. Protected review.** Trusted mechanisms attach provenance and deterministically canonicalize the proposed transition against the authoritative predecessor revision. A permitted human reviews and approves the **exact semantic transition**, including target and effective defaults. The current proposed agent-originated mutation design requires this protected per-transition human approval.

**5. Authorize and execute.** Independent policy checks evaluate the transition. A constrained, short-lived, single-use grant binds authorization to that exact transition. A deterministic Contract Executor verifies the grant and uses compare-and-swap semantics for desired-state acceptance. Existing CAPI, GitOps, or other Kubernetes controllers own reconciliation.

**6. Independently verify.** Independent observation and properly bound execution records establish whether a **historical outcome** can be verified, rejected, or remains insufficiently evidenced. An agent saying *"done"* or a tool returning HTTP 200 is not proof of convergence. **Current cluster health** is a separate, changing observation and must not be confused with the historical transition result.

An uncertain acceptance or execution result is not a license to retry blindly. Fail-closed handling and the existing recovery protocol are essential.

This separation means that neither the hosted agent nor an external agent, the inference provider, CMCP, or an optional gateway becomes the source of operational authority.

## What is implemented, proposed, and still unvalidated?

The distinctions matter more than the attractiveness of the diagram.

| Capability | Current characterization |
| --- | --- |
| Read-only diagnostics HTTP/OpenAPI contracts and selected MCP adapters | **Existing foundations**, not complete end-user multi-tenant authorization or an agent-to-mutation path |
| Documentation retrieval and source references | **Existing adapter/PoC foundations**, not a complete operations-knowledge guarantee |
| Bounded authorization, Runner, and receipt building blocks | **Existing partial implementations**; integration and supported live execution contracts require confirmation |
| OpenShell hosted-agent integration (ADR-042) | **Proposed and unvalidated** |
| CMCP optional access/evidence contracts (ADR-044) | **Draft/Proposed**; gateway and live integration undecided |
| NVIDIA Confidential Containers in OpenKubes | **External reference architecture; integration not implemented or validated** |
| Privatemode AI and Tinfoil in OpenKubes | **Alternative candidates; not selected or validated** |
| Complete agent → approval → execution → evidence path | **Proposed end-to-end target**, not a demonstrated production capability |
| CMCP offline contract proof (Step A) and subsequent live proof (Step B) | **Deferred**, each requiring explicit authorization and acceptance gates |

The first CMCP offline-contract proof, if separately authorized, would establish only a limited fixture and verifier profile. It would **not** prove a live, multi-tenant Kubernetes mutation workflow or confidential inference. A live integration requires separately reviewed contracts, protected approval, security tests, and operational ownership.

## What must be validated before production claims?

- **Agent runtime:** blocked network and credential paths, tenant isolation, lifecycle, upgrade/rollback, and direct-authority bypass tests.
- **MCP/CMCP:** authenticated end-user and target scope, gateway bypass denial, tool permissions, audit redaction, failure behavior, and portability without a mandatory gateway.
- **Confidential inference:** supported CPU/GPU profiles, verifiable attestation and trust anchors, key-release policy, secure client data path, logging and retention, failure handling, and operational performance.
- **Trusted operations:** server-attested candidate origin, exact human approval, independent policy authorization, single-use and replay protection, CAS acceptance, controller observation, and independent evidence verification.
- **Regulated deployment:** contractual, organizational, data-residency, auditing, availability, and exit requirements appropriate to the actual customer and workload. Confidential computing is not an automatic compliance certification.

Availability also matters. Confidential Computing does not by itself guarantee uptime, and an optional AI integration must not become a dependency for ordinary Kubernetes operations.

## How autonomous should AI agents really be?

Different actions carry different risks. Reading approved documentation is not the same as changing a production workload, and changing a workload is not the same as modifying a Kubernetes control plane.

The current proposed agent-originated mutation path requires protected human approval of the exact transition. The research topic **Risk-Based Autonomy & Durable Asynchronous Approval for Agentic Operations** explores future options, but these are **not accepted exceptions** to that rule. Any narrower pre-authorization model would need its own normative decision, threat model, bounded scope, revocation semantics, and independent acceptance evidence.

Our guiding principle is simple:

**The organization defines acceptable risk. The platform enforces the boundaries. AI agents operate within them.**

## The architecture we are building toward

A confidential runtime is not an operational permission. MCP connectivity is not an approval. Remote attestation of an inference workload is not a Kubernetes outcome receipt. And a successful agent message is not evidence that the system is healthy.

These boundaries are complementary precisely because they answer different questions:

**Isolate the agent. Govern its tools. Protect sensitive inference. Keep operational authority independent. Verify the outcome.**

Our goal is not to own every sandbox, gateway, AI model, or GPU stack. It is to preserve **open, versioned, replaceable contracts** for the operations that must remain trustworthy when those technologies change.

**Own the contracts, not the components.**

**AI thinks. Trusted systems execute. Evidence proves.**

**What level of authority would you give an AI agent in your production Kubernetes environment — and how would you prove that it stayed within its boundaries?**

---

### Architecture sources and further reading

- [ADR-Platform-042: Hosted and External Agentic Operations with OpenShell (Proposed)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-042-openshell-hosted-external-agentic-operations.md)
- [ADR-Platform-044: Optional CMCP Access and Evidence Contracts (Draft/Proposed)](https://github.com/openkubes/openkubes/blob/main/architecture/decisions/ADR-Platform-044-cmcp.md)
- [OpenKubes Agentic Operations Reference Architecture](https://openkubes.org/agentic-operations-reference-architecture/)
- [Securing Agentic Operations: OpenShell Meets OpenKubes](https://openkubes.org/openshell-meets-openkubes/)
- [NVIDIA Confidential Containers Reference Architecture](https://docs.nvidia.com/confidential-computing/containers/overview)
- [Confidential Containers: Trustee Attestation](https://confidentialcontainers.org/docs/attestation/)
- [Privatemode AI](https://docs.privatemode.ai/) and [Tinfoil](https://tinfoil.sh/inference) (unvalidated alternatives)

*The CMCP architecture builds on the technical analysis and draft contributed by Tim Stellfeldt.*
