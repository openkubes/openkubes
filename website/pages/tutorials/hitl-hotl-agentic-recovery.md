# AI thinks. OpenKubes executes. Evidence proves.

**Hands-on tutorial: Human-in-the-Loop (HITL) and Human-on-the-Loop (HOTL) Kubernetes recovery**

> **Experimental local lab — not production automation.** This tutorial modifies only the explicitly named disposable workload in the local \`kind-wjax-demo\` cluster. It assumes that the existing W-JAX demo lab and dedicated credentials are already installed. Do not run these commands against shared or production Kubernetes clusters.

In this tutorial, you'll deliberately scale an nginx Deployment to zero, ask an LLM to propose recovery, and compare two ways to govern the actual change: **approval for one exact operation** (HITL), and **explicitly enabled, tightly bounded supervision** (HOTL). You will inspect Kubernetes independently of what the AI reports.

This is the preserved, security-hardened demo from **AI Tinkerers Düsseldorf, 25 November 2026** — not a general-purpose autonomous SRE or production authorization implementation.

## What you'll build and learn

| | HITL — human approves each operation | HOTL — human supervises bounded operations |
| --- | --- | --- |
| Trigger | Operator submits a recovery intent | Supervisor observes stable \`0/0\` drift |
| LLM's role | Propose structured recovery data | Propose the exact expected local recovery data |
| Authority | Policy plus explicit approval of the exact proposal | Explicit local opt-in plus deterministic allowlist and Kubernetes preconditions |
| Execution | Operator executes the approved transition | Foreground supervisor patches the one allowed Deployment |
| Proof | Separate HITL verifier checks approval/execution evidence and observed state | Supervisor read-back plus **mutable, unsigned local JSONL**; *not independent evidence* |
| Stop condition | No approved operation, no authorized execution | \`--once\` ends after recovery; \`--always\` requires Ctrl-C to stop future attempts |

**Architecture in one line:** the LLM suggests; trusted code constrains; Kubernetes reconciles; evidence must be checked independently of an agent's success claim.

## 0. Prepare an isolated lab

This guide starts from an **existing, healthy W-JAX local kind environment**. The W-JAX setup is not bootstrapped by the HOTL scripts. To build a new environment, follow the source [W-JAX demo setup and recovery documentation](https://github.com/openkubes/ok-console/tree/main/demos/wjax-2026) and [HOTL README](https://github.com/openkubes/ok-console/blob/main/demos/ai-thinkers/README.md) before continuing.

**Tools used:** macOS with Colima/Docker in the tested conference lab, \`kind\`, \`kubectl\`, Python 3, \`make\`, and a locally running Ollama server with \`llama3.2:latest\`. Other operating systems have not been established as an equivalent validated tutorial environment. Use the **merged \`ok-console/main\`**, not the archived conference branch.

\`\`\`bash
git clone https://github.com/openkubes/ok-console.git
cd ok-console
git switch main
git pull --ff-only origin main

export DOCKER_CONTEXT=colima
# Set this to the EXISTING private W-JAX runtime, not the repo root:
export WJAX_DEMO_RUNTIME_DIR="/absolute/path/to/existing/private/wjax-runtime"
\`\`\`

The runtime directory should be private (\`0700\`) and contain the dedicated demo executor kubeconfig created by the W-JAX authorization flow. **Never paste or commit its contents.** Do not run \`make wjax-demo-auth\` unless the lab actually needs credential rotation.

### Preflight — read-only first

\`\`\`bash
test -d "$WJAX_DEMO_RUNTIME_DIR" && echo "Runtime directory exists"
kubectl --context kind-wjax-demo get nodes
kubectl --context kind-wjax-demo -n wjax-demo get deploy wjax-nginx
make wjax-demo-check
make wjax-demo-status
curl -fsS http://127.0.0.1:11434/api/tags >/dev/null
ollama list
\`\`\`

Verify the **exact context** \`kind-wjax-demo\`, namespace \`wjax-demo\`, Deployment \`wjax-nginx\`, image \`nginx:1.27.5-alpine\`, and healthy **2/2** replicas. If the lab is not healthy, **stop**: don't improvise against another cluster. The base W-JAX services provide the Console at \`127.0.0.1:8790/#/wjax\` and HITL UI at \`127.0.0.1:8788/\`. If these are down, use the [W-JAX runbook](https://github.com/openkubes/ok-console/tree/main/demos/wjax-2026) to diagnose them; \`make wjax-demo\` starts services and is not a read-only check.

### Safety boundary

Only the **incident-simulation** and **explicit execution** steps below mutate the named disposable Deployment. For the HITL experiment, ensure **no HOTL supervisor is running**. Do not use global \`KUBECONFIG\` or your current default context for these examples: every mutation explicitly names \`kind-wjax-demo\`.

## 1. Experiment A — Human-in-the-Loop (HITL)

HITL requires a human to approve the *exact* candidate before the executor can apply it.

### A1. Create a known incident

Only after confirming the correct disposable cluster:

\`\`\`bash
kubectl --context kind-wjax-demo -n wjax-demo \
  scale deployment/wjax-nginx --replicas=0
kubectl --context kind-wjax-demo -n wjax-demo \
  get deployment wjax-nginx
\`\`\`

Observe \`0/0\`. Open the [local HITL UI](http://127.0.0.1:8788/) and optionally the [Console](http://127.0.0.1:8790/#/wjax) to refresh the workload observation.

### A2. Ask for a proposal

Enter this intent in the HITL interface:

\`\`\`text
Deploy nginx with two replicas to the demo cluster
\`\`\`

Choose **Generate candidate** and inspect the proposed typed values:

\`\`\`json
{
  "operation": "deploy",
  "workload": "nginx",
  "replicas": 2,
  "target": "demo"
}
\`\`\`

The LLM output is **candidate data**, not permission to execute. Confirm that policy permits this exact *demo* proposal and denies forbidden targets. Use **Try forbidden production request** to inspect the \`TARGET_NOT_ALLOWED\` rejection — no production execution should occur.

### A3. Review, approve, execute

Choose **Approve exact proposal**, then **Execute authorized operation**. The human approval is tied to the exact candidate/digest; approving one candidate must not authorize a different operation. Refresh the workload status.

### A4. Verify independently of the AI claim

\`\`\`bash
kubectl --context kind-wjax-demo -n wjax-demo \
  rollout status deployment/wjax-nginx --timeout=90s
make wjax-demo-verify
\`\`\`

For the current HITL session, check the verifier's \`HUMAN_APPROVED\`, \`EXECUTOR_APPLIED\` and recovery evidence, along with \`desired=2\`, \`ready=2\` and \`available=2\`. A manual admin scale-up is **not** HITL approval evidence. If the verifier reports \`ALREADY_VERIFIED\`, inspect which session was verified rather than interpreting an old receipt as a new result.

**HITL takeaway:** *AI proposes. Human approves. The executor acts. A separate verifier checks.*

## 2. Experiment B — Human-on-the-Loop (HOTL)

HOTL is **not HITL with the approval button hidden**. Here a human explicitly opts into a foreground supervisor, whose allowed operation is fixed in code. This local prototype is not a production standing mandate.

Before starting, ensure \`wjax-nginx\` is back at **2/2**, the HITL flow has finished, and the demo runtime from Section 0 remains configured. In every new terminal, set \`WJAX_DEMO_RUNTIME_DIR\` again.

### B1. Start the read-only dashboard — Terminal A

\`\`\`bash
cd ok-console  # or the absolute path to your local ok-console checkout
export WJAX_DEMO_RUNTIME_DIR="/absolute/path/to/existing/private/wjax-runtime"
python3 demos/ai-thinkers/dashboard.py \
  --runtime-dir "$WJAX_DEMO_RUNTIME_DIR"
\`\`\`

Open [127.0.0.1:8794](http://127.0.0.1:8794/). It reads the local HOTL event log and heartbeat; it **cannot approve or execute Kubernetes changes**. The last recorded \`VERIFIED\` means historical read-back, not live health or an independent signed receipt.

### B2. Give explicit, local-only consent — Terminal B

\`\`\`bash
cd ok-console
export DOCKER_CONTEXT=colima
export WJAX_DEMO_RUNTIME_DIR="/absolute/path/to/existing/private/wjax-runtime"
export AI_THINKERS_HOTL=I_ACCEPT_LOCAL_KIND_ONLY

make ai-thinkers-hotl-once
\`\`\`

Leave this process in the foreground. It checks the private runtime, dedicated executor kubeconfig and local kind target, holds an exclusive runtime lock, and waits for stable drift. **Do not start a second supervisor.** The source also provides \`make ai-thinkers-hotl-always\`, but this tutorial intentionally uses **one-shot** operation.

### B3. Trigger one bounded recovery — Terminal C

After checking the same disposable target once more:

\`\`\`bash
kubectl --context kind-wjax-demo -n wjax-demo \
  scale deployment/wjax-nginx --replicas=0
\`\`\`

The supervisor expects two consistent observations of \`0/0\` for the same Deployment UID/generation. It asks local Ollama for a candidate, accepts **only** the exact JSON values from Part 1, and then uses a Kubernetes JSON Patch with \`uid\`, \`resourceVersion\` and existing replicas \`0\` as preconditions. It may change **only \`spec.replicas\` from 0 to 2** on the named local Deployment.

Expected local event sequence:

\`\`\`text
HOTL_ENABLED
DRIFT_CONFIRMED
AI_PROPOSAL
HOTL_EXECUTED
HOTL_RECOVERY_VERIFIED
\`\`\`

A fail-closed error instead reports \`HOTL_FAILED_CLOSED\`; do not treat it as success or silently retry. After a verified one-shot recovery, the supervisor stops.

### B4. Inspect both views of the outcome

\`\`\`bash
kubectl --context kind-wjax-demo -n wjax-demo \
  get deployment wjax-nginx
\`\`\`

Expected: **2/2**. Inspect the HOTL dashboard's current session, timeline and terminal status. The JSONL log can be altered locally, and the supervisor checks readiness with its **own** credentials. It is therefore **not independent verification**. Do **not** run \`make wjax-demo-verify\` as if it validated HOTL: that verifier correctly expects a HITL \`HUMAN_APPROVED\` event.

**HOTL takeaway:** *A human enables a bounded mode; deterministic code authorizes a narrowly scoped operation; the AI does not receive Kubernetes credentials.*

## 3. Negative test — reject missing consent

First ensure the previous \`--once\` supervisor has stopped. In a terminal with the runtime variable configured:

\`\`\`bash
env -u AI_THINKERS_HOTL \
  python3 demos/ai-thinkers/hotl.py \
  --enable-hotl --once \
  --runtime-dir "$WJAX_DEMO_RUNTIME_DIR"
\`\`\`

Expected: **non-zero exit** with the message \`HOTL disabled; require --enable-hotl and explicit AI_THINKERS_HOTL consent\`. This denial is the expected **PASS**; it must not modify the Deployment.

Optional non-mutating code checks:

\`\`\`bash
python3 -m py_compile demos/ai-thinkers/hotl.py demos/ai-thinkers/dashboard.py
python3 -m unittest discover -s demos/ai-thinkers -p 'test_*.py' -v
\`\`\`

## 4. Recover safely if the demo fails

Stop any HOTL supervisor in its foreground terminal with **Ctrl-C** before manual recovery; Ctrl-C cannot revoke a Kubernetes patch already submitted. Only on your confirmed disposable context:

\`\`\`bash
kubectl --context kind-wjax-demo -n wjax-demo \
  scale deployment/wjax-nginx --replicas=2
kubectl --context kind-wjax-demo -n wjax-demo \
  rollout status deployment/wjax-nginx --timeout=120s
\`\`\`

Describe this as **manual recovery**, not agentic evidence. Never edit JSONL files to manufacture a successful event. Keep the runtime and its kubeconfig private.

## 5. What this experiment does — and does not — prove

- **Proven within the demo's limits:** exact candidate matching, explicit HOTL consent, pinned local target, conditional replica patch, session-aware display, and a visible Kubernetes read-back.
- **Not established for production:** revocable signed grants, autonomy budgets, maintenance detection, trusted GitOps intent, production RBAC, independent HOTL verification, tamper-evident evidence, multi-operator coordination, or a broadly validated E2E lifecycle.
- **Important distinction:** the larger OpenKubes Agentic Operations architecture describes a governed target design. This demonstration implements a **local experimental subset**, not the full proposed architecture.

## Continue exploring

- [OpenKubes Console and W-JAX demo](https://github.com/openkubes/ok-console)
- [HITL/HOTL live demo README](https://github.com/openkubes/ok-console/blob/main/demos/ai-thinkers/README.md)
- [Original Düsseldorf runbook](https://github.com/openkubes/ok-console/blob/main/demos/ai-thinkers/RUNBOOK.md) — historical timings and branches; use the merged \`main\` for this tutorial
- [Architecture: Agentic Operations](../ai/agentic-operations.md)
- [Research: Policy-Bounded Autonomy](../research/security/hitl-hotl-policy-bounded-autonomy.md)

**AI thinks. OpenKubes executes. Evidence proves — but only when the evidence really supports the claim.**
