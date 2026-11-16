# If We Built Kubernetes Today, Would We Build Kubernetes?

**From deterministic infrastructure to intelligent, human-governed autonomous operations.**

*OpenKubes · Architecture & Vision · November 2026*

---

## A question worth asking

In 2014, Google introduced Kubernetes to the world.

Its idea was powerful: instead of telling machines exactly what to do, developers could describe a desired state, and Kubernetes would continuously work to make it happen.

This fundamentally changed how we build and operate software.

But imagine something different.

**What if the engineers who designed Kubernetes in 2014 had access to the AI technology we have today?**

Would they still build Kubernetes? Or would they create an intelligent, self-driving cloud operating system where AI agents directly manage infrastructure?

Our answer is simple:

**Yes, we would still build Kubernetes. But we would rethink how humans, AI, and infrastructure make operational decisions together.**

Intelligence should guide infrastructure, not replace the deterministic foundations that make it reliable.

## Kubernetes got something fundamentally right

One of Kubernetes' greatest innovations is its declarative architecture.

You describe the desired state. Kubernetes observes the actual state and continuously works to reconcile the difference.

A failed container can be restarted. Workloads can be rescheduled when nodes become unavailable. Deployments converge toward their requested replica counts.

These mechanisms do not require artificial intelligence. They require predictable, reliable engineering.

And that is exactly why Kubernetes works.

Putting a probabilistic language model into the critical execution path of a cluster would introduce uncertainty precisely where determinism matters most.

Instead, AI can help answer questions Kubernetes was never designed to answer.

## From desired state to desired outcomes

Kubernetes understands instructions such as:

*Run five replicas of this application.*

But developers and operators ultimately care about outcomes:

*Keep this application available, maintain fast response times, respect security requirements, and stay within budget.*

Achieving those outcomes requires correlating telemetry, investigating failures, evaluating trade-offs, and deciding whether an intervention could help.

This is where AI can contribute.

But understanding an objective is not the same as having permission to modify infrastructure.

**That distinction is at the heart of our OpenKubes vision.**

## The missing link is not another controller

Kubernetes already provides powerful building blocks.

Autoscalers such as HPA and KEDA adjust capacity. Policy engines such as OPA and Kyverno enforce rules. GitOps tools reconcile changes. AI-assisted tools such as K8sGPT help engineers investigate incidents.

We do not need to reinvent these capabilities.

What we want to address is the connection between them:

**How does an evidence-backed diagnosis become an authorized operational decision, how is that decision executed within human-approved boundaries, and how do we independently verify its outcome?**

Each capability can exist independently. Our goal is to connect them through open, versioned contracts, with consistent authorization, traceability, and verification.

This is the architectural direction we are exploring with OpenKubes.

## AI Thinks. OpenKubes Executes. Evidence Proves.

Our approach separates three responsibilities.

### AI Thinks.

AI-powered diagnostic agents observe infrastructure, correlate metrics, logs, and events, investigate incidents, and propose possible actions.

With **Kubernautic**, our emerging Agentic Operations experience, we aim to make this operational intelligence accessible to engineering and platform teams.

But an AI-generated explanation is not automatically the truth.

A diagnosis is initially a hypothesis. It must be grounded in verifiable observations and challenged against alternative explanations.

### OpenKubes Executes.

OpenKubes provides the sovereign platform foundation, versioned contracts, governance boundaries, and deterministic execution architecture.

Agents do not receive unrestricted write access to production clusters.

Proposed changes must pass through trusted authorization, policy checks, and controlled execution mechanisms.

We build on Kubernetes and established open-source controllers rather than introducing a parallel AI control plane.

Our engineering principle remains:

**Own the contracts, not the components.**

### Evidence Proves.

An operation is not successful simply because an API call returns `200 OK`.

Independent verification, separate from the agent that proposed the action, must establish what actually happened through observable system state, telemetry, and deterministic checks.

Did latency improve? Did the workload recover? Were the approved limits respected?

Evidence demonstrates observed outcomes and compliance with defined conditions. It does not automatically prove that an AI identified the only possible root cause.

And when the result is uncertain, the platform must acknowledge that uncertainty rather than claim success.

**AI may propose. Policies authorize. Deterministic systems execute. Independent evidence verifies.**

## Humans Govern. Agents Operate Within Contracts.

Should a human approve every operational action?

Imagine an unexpected traffic surge at 3:00 AM.

An application experiences elevated latency. A diagnostic agent identifies insufficient capacity as a plausible cause and proposes increasing its replicas from three to four.

Must an administrator wake up, inspect several dashboards, and manually approve this small adjustment?

At scale, requiring human approval for every action creates another risk: **approval fatigue**.

Engineers overwhelmed by plausible-sounding AI recommendations may begin approving them without meaningful review.

Human involvement remains, but effective oversight disappears.

We believe the better approach is **Human-on-the-Loop**, with explicitly bounded autonomy.

### From Human Authority to Verifiable Execution

A technical permission answers whether an agent **can execute** an action. Platform policy determines whether it **may execute** it. Human authority decides when explicit approval or a pre-approved operational boundary is required. And independent verification—separate from the agent that proposed the action—establishes what actually happened.

In our conceptual architecture, **OpenKubes** provides the open, replaceable contracts for governance, authorization, capabilities, and evidence. **Kubernautic** brings those contracts together in an enterprise Agentic Operations experience. Tools may be reached through **MCP**, while a proposed **CMCP** coordination/context layer remains subordinate to platform policy and never becomes an independent source of execution authority. Trusted execution and Kubernetes controllers remain separate from AI reasoning. Evidence flows back from infrastructure into governance so that outcomes can be verified and unsafe autonomy can be suspended.

![Conceptual OpenKubes target architecture showing Humans Govern, OpenKubes contracts and governance, Kubernautic agentic operations, trusted execution with MCP and proposed CMCP, Kubernetes infrastructure, and independent evidence feeding back into governance.](media/human-governance-cmcp-mcp-architecture.svg)

*Conceptual target architecture—not a fully implemented solution. MCP provides tool interfaces, not authorization; proposed CMCP does not override platform authority or human governance.*

Instead of approving every routine action individually, humans approve the rules under which selected actions may occur.

We call these rules **Autonomy Contracts**.

### What could an Autonomy Contract look like?

Consider this simplified example for a single application:

```yaml
# Illustrative concept — not an implemented OpenKubes API

workload: payment-api

allowedAction: scale-replicas

boundaries:
  minReplicas: 2
  maxReplicas: 8
  maxActionsPerHour: 2

preconditions:
  diagnosticEvidence: verified
  scalingBenefit: independently-validated

verification:
  metric: p99_latency
  target: below-500ms
  onFailure: suspend-and-alert

governance:
  approval: human-pre-authorized
  expiresAfter: 90d
```

This is not a new Kubernetes resource definition or a claim of existing functionality. It illustrates the kind of narrowly scoped, human-approved operational agreement we are exploring.

Even in this simple example, high latency alone would not justify scaling. The platform would first need evidence that additional replicas are an appropriate intervention.

The contract defines what is permitted, how frequently an action may occur, what evidence is required, and how success is evaluated.

The agent cannot expand these boundaries or authorize itself.

**Human control does not require human approval of every action. It requires human authority over the boundaries within which autonomous systems operate.**

## Autonomy must know when to stop

The real challenge of autonomous infrastructure is not making an agent perform an action.

It is preventing an autonomous action from making a bad situation worse.

What happens when two agents recommend conflicting changes? When telemetry becomes unavailable? Or when an operation times out and nobody knows whether the cluster accepted the change?

When multiple agents propose conflicting actions, the governance layer must prevent competing changes to the same resources and enforce the approved operational priorities. Resolving such conflicts safely is part of our ongoing architecture work.

Blindly retrying could amplify an outage.

Our approach is deliberately conservative:

**Fail closed. Never guess.**

When an autonomous operation has an uncertain outcome, further autonomous interventions for the affected workload should stop until the situation has been independently assessed.

If post-execution verification shows that an intervention was ineffective or harmful, the system should suspend autonomy and alert an operator.

Time-critical security containment must remain the responsibility of deterministic runtime-security mechanisms that can operate independently of AI availability.

And Kubernetes' existing controllers must continue functioning even when the AI layer is unavailable.

Autonomy should improve resilience, not introduce another critical dependency.

## Sovereignty means retaining control

For us, sovereign infrastructure is not simply about running workloads in a particular country or data center.

It means retaining control over **where infrastructure runs, where operational data is processed, which AI models are used, and who has authority to change the platform**.

OpenKubes is designed around open interfaces, replaceable components, and deployment choices across bare metal, private infrastructure, public cloud, and edge environments.

This matters even more when AI enters operations.

Organizations should be able to choose their models, control their telemetry, define their governance policies, and operate without becoming dependent on a single infrastructure or AI provider.

**Sovereignty is not the absence of technology providers. It is the freedom to choose, replace, and govern them.**

## What we are building toward

OpenKubes is an open-source Kubernetes meta-framework for building sovereign infrastructure platforms.

Kubernautic builds on that foundation as our emerging Agentic Operations experience, connecting AI-assisted diagnostics with platform knowledge and operational workflows.

Our goal is to bring together:

**Intelligent diagnosis. Contract-governed execution. Independent verification.**

We are not replacing Kubernetes schedulers or reconciliation loops. We are exploring how existing platform contracts and trusted execution paths can support intelligent, accountable operational decisions.

Our next milestone is deliberately modest: demonstrate one limited operational scenario in which a diagnostic agent identifies a problem, produces an evidence-backed proposal, and passes it through controlled authorization and execution.

The longer-term objective is to support narrowly scoped, human-approved autonomy for selected low-risk actions.

**Broad autonomous remediation is a direction we are investigating, not a production capability we claim to have delivered.**

## So, would we build Kubernetes again?

Yes.

We would still want its declarative model, reconciliation loops, stable APIs, and distributed-systems foundations.

These are not limitations to overcome. They are the foundations that make modern infrastructure dependable.

But we would build a more intelligent operational experience around them.

One where people describe the outcomes they need.

One where AI helps engineers understand complex systems.

One where humans govern the boundaries of autonomous behavior.

And one where independent evidence verifies what actually worked.

The next generation of cloud infrastructure does not need to make Kubernetes less predictable.

**It needs to make intelligent operations as accountable as the infrastructure beneath them.**

---

### AI Thinks. OpenKubes Executes. Evidence Proves.

**Humans Govern. Agents Operate Within Contracts.**

*Open by default. Declarative by design. Sovereign by architecture.*

Explore [OpenKubes](https://openkubes.org/) and discover our evolving [Kubernautic Agentic Operations experience](https://kubernautic.com/).
