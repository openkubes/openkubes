# Experiments & Evidence

**Research is not certification.** This area connects OpenKubes architecture hypotheses to reproducible lab procedures, explicit negative tests, scoped outcomes and unresolved findings. An agent saying *done* is a claim; an independently checked result is stronger evidence — and even that result applies only to the tested scope.

## Experiment registry

| Experiment | Status | Scope and evidence boundary | Start here |
| --- | --- | --- | --- |
| AI Tinkerers Düsseldorf — Kubernetes HITL recovery | Historical local demo; documented validation | Exact human-approved proposal, disposable `kind-wjax-demo`, separate HITL verifier. Historical runbook records a successful demo; evidence does **not** certify production operation. | [Reproduce HITL](../../tutorials/hitl-hotl-agentic-recovery.md#1-experiment-a-human-in-the-loop-hitl) |
| AI Tinkerers Düsseldorf — bounded HOTL recovery | Experimental implementation; local validation only | Explicit opt-in, one-shot replica recovery, local unsigned JSONL and same-process read-back — **not independent HOTL verification**. | [Reproduce HOTL](../../tutorials/hitl-hotl-agentic-recovery.md#2-experiment-b-human-on-the-loop-hotl) |
| kagent HITL/HOTL Security Lab | In progress / acceptance criteria under investigation | Proposed protected approvals, identity boundaries, revocation and negative security tests. **No completed kagent lab results are asserted here.** | [Security & Trust](../security/index.md) |
| Risk-Based Autonomy & Asynchronous Approval | Architecture research; not validated operational authority | Standing mandates, single-use grants, races, revocation ordering, failure handling and restore-safe authority are research questions, not deployed capabilities. | [Research Paper 001](../security/hitl-hotl-policy-bounded-autonomy.md) |

## Case study — AI thinks. OpenKubes executes. Evidence proves.

The [AI Tinkerers Düsseldorf HITL/HOTL tutorial](../../tutorials/hitl-hotl-agentic-recovery.md) documents two intentionally different authority models using the **same** disposable local Kubernetes Deployment:

- **HITL:** an LLM proposes `nginx` with two replicas; a policy checks the target; a person approves the *exact* proposal; an executor performs the operation; a separate verifier checks authorization/execution evidence and observed readiness.
- **HOTL:** an operator explicitly starts a foreground supervisor; it observes stable `0/0` drift, requests the narrowly expected LLM proposal, applies deterministic target and resource preconditions, then records an unsigned local event sequence and reads Kubernetes state back. No per-transition approval occurs in that mode.

Both are educational **local kind** experiments, not general-purpose production SRE agents. The LLM never receives the Kubernetes executor kubeconfig.

### Scope and traceability

| Field | Documented demo scope |
| --- | --- |
| Event | AI Tinkerers Düsseldorf, 25 November 2026 |
| Source repository | [openkubes/ok-console](https://github.com/openkubes/ok-console) |
| Historical snapshot | [`ai-tinkerers-duesseldorf-2026`](https://github.com/openkubes/ok-console/tree/ai-tinkerers-duesseldorf-2026) |
| Integrated implementation | [HITL/HOTL showcase PR #184](https://github.com/openkubes/ok-console/pull/184); [UI links PR #185](https://github.com/openkubes/ok-console/pull/185) |
| Lab profile | macOS, Colima, kind Kubernetes v1.37.0 and local Ollama (`llama3.2:latest`) in the historical conference runbook |
| Pinned resources | Context `kind-wjax-demo`, namespace `wjax-demo`, Deployment `wjax-nginx`; expected image `nginx:1.27.5-alpine` |
| Controlled transition | Deliberately set `spec.replicas` to 0; restore exactly 2 replicas |
| Source of observed historical results | [Archived demo runbook](https://github.com/openkubes/ok-console/blob/main/demos/ai-thinkers/RUNBOOK.md) — historical report, not a fresh independent re-run |

### Reported results and their limits

The historical demo runbook reports **two HOTL E2E passes**, a missing-opt-in denial, **2/2 readiness** after recovery, and healthy local diagnostics. Those are **reported historical lab results**, not a newly repeated E2E run on every subsequent commit. The runbook's original six HOTL unit tests refer to its earlier frozen version; the later merged implementation contains further security-hardening and additional tests. Avoid interpreting the historical test counts as current CI coverage.

For independent assessment, keep these evidence types separate:

| Signal | What it supports | What it does not establish |
| --- | --- | --- |
| LLM response | What the model proposed | Authorization, execution or recovery |
| HITL approval and executor events | That a particular proposal was approved and an execution was recorded in that session | A live workload is currently healthy without a fresh observation |
| HITL separate verifier | Session-specific checks of approval, execution and Kubernetes readiness under the lab procedure | Production-grade, tamper-proof or universally transferable evidence |
| HOTL JSONL timeline and supervisor read-back | The supervisor recorded an attempt and observed the requested local state | Independent attestation, signed evidence, irreversible action revocation or production HOTL safety |
| `kubectl` observation | Kubernetes' reported current Deployment/Pod state at observation time | Why the state changed, who authorized it or whether the state remains healthy later |

A workload at `0/0` after being scaled to zero is not automatically a Kubernetes fault. The *experiment* deliberately defines two replicas as the expected state and introduces controlled drift.

### Reproducibility and negative tests

Use the [step-by-step tutorial](../../tutorials/hitl-hotl-agentic-recovery.md) with an **already configured disposable W-JAX lab**. Verify the context and namespace before mutations, run HITL and HOTL **sequentially** rather than in competition, and never use a shared or production cluster.

The documented negative boundaries include: production-target proposal denial for HITL, missing explicit HOTL consent, exact candidate matching, pinned local target, concurrency/UID/resourceVersion preconditions and fail-closed behavior. Negative-case checks do not replace an independent red-team evaluation.

### Open findings before a production claim

- HOTL lacks separately authorized and independently attested execution evidence.
- No production-scoped, revocable signed grants, durable authorization or autonomy budgets have been validated here.
- Operational safeguards such as maintenance-aware suppression, robust retries, multi-operator coordination, narrower production RBAC and complete failover/rollback remain out of scope.
- A newly configured, fully reproducible cross-platform E2E exercise — with fresh evidence artifacts for the merged revision — has **not** been reported on this page.

## Other active research

### kagent HITL/HOTL Security Lab

**In progress.** Investigates identity and authority separation, protected Ingress approvals, bounded remediation and stop/revocation mechanisms on an isolated kind cluster. This work must not be conflated with the separately implemented AI Tinkerers Ollama/HOTL local supervisor.

### Risk-Based Autonomy & Asynchronous Approval

**In progress.** Explores standing mandates, protected human review, single-use transition grants, approval races, persistence and restore-safe revocation semantics. [Research Paper 001](../security/hitl-hotl-policy-bounded-autonomy.md) is an architecture investigation, not proof that a production HOTL controller exists.

## Evidence publishing checklist

Each future experiment should publish a traceable record that explicitly states:

1. **Question and expected behavior:** including what a denial or failure should look like.
2. **Exact scope:** repository commit, image digests, OS, cluster topology, versions, model, namespace and authorization boundary.
3. **Procedure and inputs:** reproducible commands, test cases and explicit operator actions.
4. **Observed outcomes:** pass/fail/not proven per test, fresh timestamps and any deviations.
5. **Artifacts:** redacted logs, evidence hashes, independent verification results and links to immutable revision references where available.
6. **Outstanding risks:** limitations, validity period, negative tests not run and follow-up owners.

Never publish kubeconfigs, API tokens, personal identifiers or raw secrets as evidence.

**Research-to-implementation boundary:** lab evidence can inform architecture reviews and ADRs; it does not independently approve a production implementation, confer agent authority or prove continuous correctness.

[Back to Research](../index.md) · [Hands-on HITL/HOTL tutorial](../../tutorials/hitl-hotl-agentic-recovery.md)
