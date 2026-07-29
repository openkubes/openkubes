# Agentic AI PoC — UC-1 Evidence Protocol (OK-14)

Closing evidence for the OK-14 PoC. Requested in OK-14 (2026-07-28) after the
Go/No-Go was settled: the two remaining acceptance items are (1) the results of
the three defined troubleshooting scenarios and (2) the OpenClaw statelessness
restart test.

This document **defines** those scenarios. ADR-Platform-015 UC-1 requires
"minimum three defined scenarios" but never named them — that gap is what this
protocol closes. It complements `agentic-ai-poc-guideline.md` (guardrails) and
is subordinate to the Jira tickets, which remain the source of truth for
acceptance criteria.

Scope note: per the OK-14 Go/No-Go, diagnostics run **behind** the ADR-021
contract with kagent as the first provider profile. The scenarios therefore
exercise the contract, and — where the PoC claim depends on it — the full PoC
path Open WebUI → OpenClaw → MCP adapter → facade → kagent.

## What this protocol proves, and what it does not

| Proves | Does not prove |
|---|---|
| UC-1 works end to end on a real cluster | ADR-021 conformance (that is OK-89/OK-91: executable contract tests + Profile B) |
| OpenClaw loses no *user-visible* state on restart | OpenClaw is stateless in a stronger sense (HA, multi-replica) |
| The Talos capability delta is reported, not hidden | The delta holds for RKE2 too (that is OK-95) |

A green run here does **not** make OK-92 done. It makes OK-14 closable.

## Preconditions

- `ok-ai` reachable (VPN), `KUBECONFIG=~/.kube/ok-ai.yaml`
- Profile A deployed and healthy: `make -C <ok-cluster>/kagent/profile-a status`
- `make -C <ok-cluster>/kagent/profile-a verify-rbac` green (ADR-021 test 2)
- MCP adapter deployed (`platform-diagnostics-mcp` service in `platform-diagnostics`)
  — see the known gap below
- OpenClaw running in `openclaw`, registered in Open WebUI
- Local tools: `kubectl`, `jq`

> **Known gap at time of writing:** no Make target deploys
> `platform/ai/platform-diagnostics/contract/mcp-adapter/deploy.yaml`. Until one
> exists, apply it manually before S4. S1–S3 do not need the adapter (they call
> the facade directly); only the OpenClaw-path check does.

## The three scenarios

Each scenario names the contract function it exercises, the fixture, and hard
pass criteria. Pass criteria are written so that a *plausible-looking but
ungrounded* answer fails — that is the point of the PoC.

### S1 — Cluster health analysis

- **Function:** `get_platform_health`
- **Input:** `{"clusters":["ok-ai"]}`
- **Fixture:** none (live cluster)

**Pass:**

1. HTTP 200, response validates against `PlatformHealth`.
2. `clusters[0].status` ∈ {`healthy`, `degraded`, `unavailable`} —
   **`unknown` is a FAIL.** `unknown` is the facade's parse-fallback
   (`facade/app.py`, `get_platform_health` exception path); it means the agent
   reply could not be mapped, not that the cluster state is unknown.
3. `clusters[0].provider_capabilities` present and matches the deployed
   `providerCapabilities` values.
4. `summary` is non-empty and consistent with `signals`.

> This criterion is deliberately strict because the intermittent `unknown`
> fallback is a known open defect on the OK-92 branch. If S1 fails this way,
> record the run as FAIL and fix the mapping — do not soften the criterion.

### S2 — Pod/Deployment failure diagnosis

- **Function:** `investigate_workload`
- **Fixtures:** namespace `ok14-evidence`, two deliberately broken Deployments
  (`uc1-imagepull`, image tag that does not exist → `ImagePullBackOff`;
  `uc1-crashloop`, command exits non-zero → `CrashLoopBackOff`)
- **Input:** one call per fixture,
  `{"cluster":"ok-ai","namespace":"ok14-evidence","workload":"<fixture>","time_range":"PT1H"}`

**Pass, per fixture:**

1. HTTP 200, validates against `WorkloadInvestigation`.
2. `probable_causes` is **non-empty**.
3. The top hypothesis names the actual failure mode (registry/image-pull for
   `uc1-imagepull`; container exit/crash-loop for `uc1-crashloop`). An answer
   naming the wrong failure mode is a FAIL even if well-formed.
4. Every hypothesis has `confidence` ∈ {low, medium, high} and
   `counter_evidence_status` ∈ {`found`, `none_found`} —
   **`not_checked` is a FAIL** (ADR-021: a hypothesis without sought
   counter-evidence is a guess).
5. `evidence` is non-empty; every `EvidenceRef` carries `uri`
   **and no raw payload or secret** — references only.
6. Every `evidence_refs` / `contradicting_evidence_refs` entry resolves to an
   `EvidenceRef` in `evidence` (no dangling references).
7. `recommended_next_steps` contains only human actions; nothing was executed.

The fixtures are created by a human operator, not by the agent. The agent's
identity stays read-only throughout — that is what `verify-rbac` asserts.

### S3 — Root cause with log/event evidence, incl. capability delta

- **Function:** `collect_diagnostic_evidence`
- **Fixture:** `uc1-crashloop` from S2
- **Input:** `{"cluster":"ok-ai","namespace":"ok14-evidence","workload":"uc1-crashloop",`
  `"time_range":"PT1H","evidence_types":["events","logs","describe","host_journal"]}`

`host_journal` is requested **on purpose**: ok-ai runs Talos, which declares
`host_journal: false` and `node_shell: false`.

**Pass:**

1. HTTP 200, validates against `EvidenceBundle`.
2. At least one `events` and one `logs` ref with `status: available` and a `uri`.
3. The requested-but-unsupported `host_journal` appears with
   `status: unavailable` **and a non-empty `reason`** — silent omission is a
   FAIL (ADR-021 test 5, capability delta).
4. No `EvidenceRef` embeds a payload; no secret material anywhere in the bundle.
5. `provider_capabilities` present and consistent with (3).

## S4 — OpenClaw path check (provenance)

Not a fourth UC-1 scenario; it verifies the PoC claim that OpenClaw reaches
diagnostics *only* through the contract, and does not answer from model
knowledge.

- Ask via Open WebUI (OpenClaw model): *"What is the state of workload
  uc1-crashloop in namespace ok14-evidence on cluster ok-ai?"*

**Pass:**

1. The answer ends with `Source: platform-diagnostics/<tool-name>` (the
   provenance rule from the OpenClaw `AGENTS.md`).
2. The MCP adapter and facade logs show the matching call for that request —
   provenance confirmed at the server, not just claimed in the reply.
3. The stated symptoms match S2's `WorkloadInvestigation`; nothing invented.
4. OpenClaw holds no cluster credentials: `make -C platform/ai/openclaw
   verify-kubectl` (or `rbac.create=false` on the release once diagnostics run
   through the contract).

## T4 — Statelessness restart test

Verifies the ADR-015 assumption: *Open WebUI owns chat persistence; the agent
backend may lose all local state on pod restart.* The acceptance wording is
**no user-visible state loss**, not "OpenClaw keeps nothing".

**Steps:**

1. In Open WebUI, hold a conversation of at least three turns with the OpenClaw
   model, including one diagnostics question (reuse S4). Note the conversation
   title.
2. Assert no persistent volume: the `openclaw` Deployment must have only
   `emptyDir` and `configMap` volumes, no PVC.
3. Record the pod name and start time, then delete the pod
   (`kubectl -n openclaw delete pod -l app.kubernetes.io/name=openclaw`) and
   wait for rollout.
4. Confirm a genuinely new pod: different pod name, restart count 0, fresh
   start time.
5. Reload Open WebUI **without clearing browser state**: the conversation and
   its full history must still be listed and readable.
6. Continue the same conversation with a follow-up diagnostics question.

**Pass:**

1. No PVC on the Deployment (step 2).
2. New pod, not a restarted container (step 4).
3. Conversation and history fully intact in Open WebUI after the restart
   (step 5) — this is the acceptance criterion.
4. The follow-up answer succeeds and again carries a
   `Source: platform-diagnostics/...` line (step 6): the backend recovered its
   ability to serve, with no operator action.
5. Expected and **not** a failure: OpenClaw's own local state
   (`/home/node/.openclaw` beyond the init-copied config) is empty again. Record
   it — it is the evidence that statelessness holds rather than being untested.

## Running it

```bash
# from the openkubes repo root
CLUSTER=ok-ai platform/ai/openclaw/scripts/uc1-evidence.sh
```

The script runs S1–S3 against the facade and the mechanical parts of T4
(fixtures, no-PVC assertion, pod replacement, post-restart contract call),
evaluates every machine-checkable pass criterion, and writes a filled evidence
report to `platform/ai/openclaw/.evidence/uc1-evidence-<timestamp>.md`.

S4 and the Open WebUI half of T4 are UI actions. The script prints them as an
explicit operator checklist and leaves blanks in the report for them — it never
records a PASS for a step it did not observe.

Useful flags: `--keep-fixtures` (leave the broken Deployments up for manual
inspection), `--skip-restart` (S1–S3 only), `--namespace` (default
`ok14-evidence`), `--out DIR` (report directory).

Reports contain live cluster detail and are evidence, not source: add
`.evidence/` to `platform/ai/openclaw/.gitignore` (next to `.token`) or write
them elsewhere with `--out`. Attach the report to the ticket rather than
committing it.

Exit code is 0 only if every machine-checkable criterion passed; MANUAL items
never count as passed.

## Recording the evidence

1. Run the script; review the report — it is a draft, not a verdict.
2. Fill in the S4 and T4 UI sections from your own observation.
3. Attach the report to OK-14 and add a comment referencing it, listing any
   FAIL and where it is tracked.

A FAIL is not a blocker for OK-14 as such — the Go/No-Go is already decided. It
belongs on the ticket that owns the defect (e.g. the `unknown` fallback and the
missing adapter deploy path are OK-92; executable contract tests are OK-91).

## Cleanup

```bash
kubectl -n ok14-evidence delete deploy uc1-imagepull uc1-crashloop
kubectl delete namespace ok14-evidence
```

The script does this automatically unless `--keep-fixtures` is given.

## References

- OK-14 — PoC: OpenClaw + Open WebUI tandem architecture
- ADR-Platform-015 — Agentic AI (UC-1, state handling assumption)
- ADR-Platform-021 — Read-Only Platform Diagnostics Contract (tests 2, 3, 5, 6)
- `docs/agentic-ai-poc-guideline.md` — Part A guardrails, Part C stop rule
- `platform/ai/platform-diagnostics/contract/openapi.yaml` — normative schemas
