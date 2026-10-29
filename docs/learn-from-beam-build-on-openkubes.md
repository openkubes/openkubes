# Learn from BEAM. Build on OpenKubes.

*What Erlang/OTP can teach us about fault-tolerant agentic operations*

*OpenKubes Architecture Exploration · October 2026*

> **Status: Architecture exploration — not an implementation announcement.** The patterns below are proposals for evaluation. OpenKubes has not committed to adopting Erlang, Elixir, or the BEAM runtime, and the suggested Agent Operation Supervisor is not a claim of an existing production capability.

## Intelligent agents are not automatically reliable operators

AI agents are getting better at investigating failures, interpreting telemetry, and suggesting infrastructure changes. But a good suggestion is only the beginning.

Imagine an agent proposing a deployment change. A human approves the exact change, policy authorizes it, and a trusted executor begins work. Then the executor crashes. Kubernetes restarts its Pod.

Did the change happen? Was it partly applied? Is a retry safe? Has the authorization expired? What evidence would let an operator verify the outcome?

These questions are not solved by a more capable language model. They are questions about **fault isolation, supervision, authority, and durable state**.

This is where an older ecosystem has something to teach us.

**Learn from BEAM. Build on OpenKubes.**

## Why BEAM?

The BEAM virtual machine powers Erlang and Elixir. Erlang/OTP established a well-developed approach to concurrency and resilient services built around independently running processes, asynchronous message passing, and supervisors that monitor child processes.

OTP supervision strategies include `one_for_one`, `one_for_all`, and `rest_for_one`. They define which processes are restarted after a failure. Restart intensity limits help prevent an endless crash/restart cycle. See the [official Erlang/OTP supervision documentation](https://www.erlang.org/doc/system/sup_princ.html).

These are not AI-specific ideas. That is precisely their appeal: infrastructure operations need dependable failure handling whether or not an AI agent initiated a proposal.

But there is an essential distinction:

> **Restarting a worker is not the same as safely retrying an infrastructure operation.**

A BEAM supervisor can restart a failed process. A Kubernetes Pod can also restart. Neither restart alone establishes whether a remote side effect occurred, whether an operation can be repeated, or whether its original authorization remains valid.

## Where BEAM ideas could meet OpenKubes

The [OpenKubes Agentic Operations Reference Architecture](./agentic-operations-reference-architecture.md) proposes a clear separation of responsibility:

**AI thinks. OpenKubes executes. Evidence proves.**

Agents interpret information and prepare **non-authoritative candidate proposals**. The trusted platform validates and canonicalizes the requested transition. Human review and independent policy authorization govern whether that exact change may proceed. Existing controllers remain the owners of reconciliation. Evidence is evaluated independently of what the agent claims.

Fault-tolerant agentic operations should strengthen these boundaries, not bypass them.

| BEAM / OTP principle | Potential OpenKubes interpretation | Important limitation |
| --- | --- | --- |
| Independent processes | Isolate operation workers and agent sessions by workload or trust boundary | Go goroutines alone are **not** equivalent to isolated BEAM processes |
| Message passing | Use typed, versioned operation and status contracts | Messages require provenance, validation, ordering and deduplication rules |
| Supervision trees | Separate a deterministic operation supervisor from execution workers | Restart decisions must consider external side effects |
| Restart intensity | Introduce bounded retries, backoff and escalation | Some operations must never be blindly retried |
| Fault containment | Keep a failing agent or operation from degrading unrelated workspaces | Isolation must cover identity, credentials, capacity and tenancy |
| Explicit recovery | Reconstruct operation status from authoritative observations | A process-local mailbox or volatile state is insufficient after a crash |

The most useful learning is **not** to reproduce OTP literally. It is to express the same intent with the primitives already present in our platform: Go services, durable operation records, Kubernetes APIs, controllers, and bounded executor contracts.

## A thought experiment: the executor fails mid-operation

Consider a hypothetical operation to update a Kubernetes-managed resource.

1. An agent generates a candidate. It does not receive direct cluster mutation authority.
2. Trusted platform logic resolves the exact semantic transition, presents it for human review, and evaluates policy.
3. A bounded, single-use authorization permits the trusted executor to act on the approved transition.
4. The executor submits the change, but crashes before recording a terminal outcome.
5. Kubernetes restarts the executor.

**What should happen next?**

A naive implementation immediately retries step 4. A safer design first reconstructs what actually happened from authoritative state and the persisted execution record.

The proposed **Agent Operation Supervisor** would be a *logical*, deterministic component — not a second AI agent and not necessarily a separate microservice. It would:

- correlate the operation ID, expected revision, authorization scope and observed resource state;
- distinguish **not started**, **in progress**, **accepted**, **completed**, **failed** and **outcome unknown**, rather than treating a timeout as proof of failure;
- reconcile the outcome using existing responsible controllers and authoritative observations;
- permit a continuation only where the operation contract explicitly supports it;
- escalate ambiguous or non-repeatable outcomes to human review;
- record evidence of the decision, including why a retry was allowed, blocked, or unnecessary.

A restart must not replay an expired or consumed authorization. If the intended action needs fresh authority, the platform must obtain it through the trusted review and policy path. Idempotency keys and deduplication help, but do not magically guarantee exactly-once effects across external systems.

There is no shortcut around those semantics.

## Borrow the supervision mindset, not a new runtime

Could OpenKubes implement a supervisor in Erlang or Elixir? Potentially. BEAM may be valuable for systems with large numbers of independently supervised actors and demanding concurrency requirements.

But every additional runtime introduces costs: operating expertise, deployment and supply-chain management, observability integration, security review, contract translation, and another production failure domain.

We already have a Go- and Kubernetes-oriented architecture. Before adding BEAM, we should ask whether a narrow, deterministic Go-native prototype can demonstrate the properties we need.

**Our initial preference is to borrow OTP design principles, not to rewrite existing OpenKubes components.**

This is also consistent with a core OpenKubes principle: **contracts over components**. The platform's authority and evidence guarantees should remain independent of the chosen implementation technology.

## What we propose to test

After W-JAX 2026, we propose a timeboxed **architecture spike** — not a product commitment.

The primary experiment: terminate an execution worker after a mutation may have been submitted, restart it, and determine whether it can reconstruct the correct outcome without duplicating side effects or bypassing governance.

A minimal proof of concept should establish:

1. **Crash recovery:** an interrupted worker can reconstruct operation state from durable, authoritative information.
2. **Safe continuation:** repeated messages or worker restarts cannot cause unintended repeated mutations.
3. **Approval integrity:** the approved semantic change and authorization conditions remain binding; recovery cannot silently expand authority.
4. **Failure containment:** retry budgets and escalation prevent an individual failing operation from destabilizing unrelated work.
5. **Evidence:** the final result and every recovery decision can be independently verified.

We will compare this Go/Kubernetes-native approach against an optional BEAM-based alternative only if evidence shows a concrete gap that BEAM could fill.

The spike should end with a documented **go/no-go decision**, not an automatic commitment to build a new subsystem.

## Who supervises the AI agents?

Fault-tolerant execution is only one part of the bigger question.

As agents become more autonomous, they may diagnose problems, coordinate specialist agents and propose recovery strategies. A supervisor for *those processes* is useful, but it should not become an unchecked super-agent with blanket cluster access.

The separation still applies:

- **AI may reason and propose.**
- **Trusted policy and approved authority determine what is permissible.**
- **Deterministic execution and existing controllers carry out bounded changes.**
- **Independent evidence establishes what happened.**

Autonomy should increase only when the boundaries remain understandable, testable and enforceable.

## An invitation across communities

This exploration was inspired in part by a conversation at **Sovereign Cloud Days 2026 in Saarbrücken**, where we connected with **Alistair Woodman**, a board member of the Erlang Ecosystem Foundation.

We would welcome a technical exchange between Erlang/Elixir practitioners and the Kubernetes, platform-engineering and AI-agent communities.

A question for a joint meetup:

> **Can we bring Erlang-grade fault-tolerance thinking to AI-driven infrastructure operations without adopting the BEAM runtime?**

We think that question is worth investigating — openly, pragmatically, and with working failure scenarios rather than architecture diagrams alone.

**Learn from BEAM. Build on OpenKubes.**

---

### Further reading

- [Erlang/OTP — Supervisor Behaviour](https://www.erlang.org/doc/system/sup_princ.html)
- [Erlang/OTP — supervisor module](https://www.erlang.org/doc/apps/stdlib/supervisor.html)
- [OpenKubes — Agentic Operations Reference Architecture](./agentic-operations-reference-architecture.md)
- [OpenKubes — Public Architecture Decisions](https://github.com/openkubes/openkubes/tree/main/architecture/decisions)
