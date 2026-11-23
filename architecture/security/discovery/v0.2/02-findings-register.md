# OpenKubes Security Findings Register v0.2

**Status:** Research register, not a vulnerability disclosure, accepted severity assessment or production incident report. **Date:** 2026-11-23.  
**Assessment basis:** Codex source review of BYOH `15b668d4ced7fae2ee78b9175f23cf23c031f90a`, Scaleway Lab `68669ea6ad7522f827cca59fe71ed5979827ae44`, OpenKubes architecture `05033fbb27c68f4e84440e8b4825a9cfe58e37b8`, ok-cluster `16f9c1be03cfb83688ba6aef7d1350d9f25cde7f`, and CAPI v1.14.4 `4356c154f4a76b8939748ef7ebc2d0793ffe47e8`. Codex **did not run** new tests or query a live API. Prior live impersonation is *reported* in discovery input. Claude/Gemini are independent architecture challenges, not independent runtime reproductions.

## Reading guide

- **C** = source-confirmed behavior at pinned revision, given attack preconditions. **L** = prior lab result reported, not re-executed in this work. **D** = design risk, technical possibility or missing acceptance evidence; must not be labeled exploited. **U** = requires additional source/API verification.
- **P0/P1/P2** = proposed remediation/release-gate priority, **not** a calculated CVSS severity.
- Rows may combine code finding and inferred impact; evidence column names which part is confirmed. `OPEN` means not proven closed at review revision, not proof no later work exists.
- Control IDs are in `01-security-baseline.md`; test IDs in `03-evidence-matrix.md`.

| ID | Priority | Finding / threat boundary | Confidence & precondition | Baseline | Proof needed | State |
|---|---|---|---|---|---|---|
| **F-01** | P0 | Default BYOH group has cluster-wide **named** Secret `get`; stolen host cert + network access can read known-name foreign management-cluster Secrets. No verified disclosure. | **C+L** (bundle; earlier impersonation) | B-01/02, BYOH-01 | T-01/02/03/04 | OPEN |
| **F-02** | P0 | Default install/reinstall, missing marker, rollback, interrupted hardening can restore broad host bindings; some lab paths verify only existence or report drift. | **C** (installer/rollback paths); no full live reenactment | B-02, BYOH-02 | T-05/06 | OPEN |
| **F-03** | P0 | BYOH controller SA has management-wide Secret create/delete/get/list/patch/update/watch, CSR approve rights and wildcard infrastructure resource verbs; controller compromise has larger blast radius than host compromise. | **C** permissions; exploitation untested | B-07, BYOH-04 | T-07/08 | OPEN |
| **F-04** | P0 | Default CSR auto-approver validates CSR structure but does not verify independent approved host ownership. Valid bootstrap token may lead to unintended named identity. Stronger manual lab approval exists outside default path. | **C** approval logic; live exploit untested | B-03, BYOH-03 | T-09/10 | OPEN |
| **F-05** | P0 | Per-host Secret `revoke-secrets` is not durable: subsequent lab `watch`/`apply` can recreate the grant if assignment still qualifies. | **C** Lab grant writer | B-05, BYOH-06 | T-11/12 | OPEN |
| **F-06** | P0 | Agent-controlled non-reserved ByoHost labels influence Machine selectors; compromised eligible host could attract privileged assignment and then receive formally valid bootstrap grant. | **C** label/selector mechanics; scenario untested | B-03/04 | T-13 | OPEN |
| **F-07** | P0 | Agent's own ByoHost reset status with matching ByoMachine UID can trigger detach/finalizer release, **without independent proof host was wiped**; reuse can expose later assignment material. | **C** webhook/controller acceptance; malicious E2E absent | B-06 | T-14 | OPEN |
| **F-08** | P0 | etcd restore from pre-revocation/pre-consumption snapshot may resurrect RBAC, suspensions, previously spendable grants and stale authority. Cold single-writer handover does not fix historic authorization state. | **D** strong snapshot-state reasoning; no restore E2E | B-05/11/12/17 | T-15/16/37 | OPEN |
| **F-09** | P1 | Host X.509 username is namespace+hostname; new ByoHost UID does not distinguish old unexpired cert on same-name reenrollment. Standard K8s lacks general client-cert CRL/OCSP. | **C** username; **D** reenrollment exposure dependent on matching new grants | B-05, BYOH-05 | T-17 | OPEN |
| **F-10** | P1 | Revoked management Secret read does not retract downloaded installer/bootstrap payloads, workload join credentials or queued host actions; local uninstall script persists. | **C** data-fetch/execute order; effect on specific lifecycle paths untested | B-05 | T-18/19 | OPEN |
| **F-11** | P1 | Committed No-Replacement handler exists but default webhook bundle does not register it; opt-in/local guard and CAPD no-op do not prove protected real BYOH upgrade. | **C** manifest/source; local CAPD evidence limitations | B-08/09 | T-20/21/22 | OPEN |
| **F-12** | P1 | Webhook `failurePolicy: Fail`, one manager replica and mutable namespace routing may create outage stalls or enforcement bypass. Scope of matched operations, protected routing and recovery paths require real tests. | **C** config; **D** outage effects | B-08/10/13 | T-23/24 | OPEN |
| **F-13** | P1 | Management fence implementation is partial; old management plane may retain effective workload, host, BMC/provider or SSH write paths after restore/handover. Offline edge target cannot be assumed fenced. | **C** partial CLI/Lab guards; **D** full split-brain impact | B-12 | T-25/26 | OPEN |
| **F-14** | P1 | Policy-only forward version checks do not authorize an upgrade or guarantee reversibility. Failed singleton CP upgrade needs tested snapshot/restore; upgrade fallback must not silently replace Machine. | **C** known CAPI/BYOH mechanics; **D** untested recovery | B-08/09/10 | T-21/22/27 | OPEN |
| **F-15** | P1 | VAP request-local CEL cannot freely join trusted cross-object resources, atomically consume approval, or directly implement arbitrary signature verification and current-time expiry. Missing joins could leave critical invariants unenforced. | **D** K8s API design constraint; implementation design not selected | B-08/09/13 | T-28/29 | OPEN |
| **F-16** | P1 | VAP policy/binding administration is separate from VAP admission: policy cannot be assumed to protect its own removal. Installer/recovery privilege escalation must be tested. | **D** platform control-plane boundary | B-13 | T-30 | OPEN |
| **F-17** | P1 | Per-host RoleBinding reconciliation by controller is constrained by Kubernetes RBAC bind/escalation checks and the controller's own required Secret access. A naïve privilege reduction could break legitimate provisioning. | **D** design constraint; evaluate role and bind privileges against live manifests | B-07, BYOH-04 | T-08/31 | OPEN |
| **F-18** | P1 | Security Evidence is version-specific: a CAPI/Kubernetes/provider or rendered-policy change can invalidate coverage. Production-approved status must not silently carry over to an untested build. | **D** governance risk grounded in alpha in-place behavior | B-14 | T-32 | OPEN |
| **F-19** | P1 (**P0 if privileged credential confirmed**) | Agent-adjacent privileged kubeconfig (OK-105 per Claude's review) may collapse agent/executor trust boundary; actual deployment, access and issue status not independently audited in this work. | **U** issue/corpus assertion only | B-16 | T-33 | VERIFY |
| **F-20** | P1 | Grant claiming and admission can race with retries, crashes, revocation and multi-object effects; partial local implementation does not prove one-use transactional execution. | **C** local candidate exists; **D** end-to-end guarantee | B-09/11 | T-29/34 | OPEN |
| **F-21** | P1 | Workload-cluster kubeadm bootstrap token lifetime and deletion after join are separately scoped from management Secret grants. Gemini's example of a 24-hour token is **not measured for this OpenKubes deployment**. | **U** concrete token TTL and credential retention require inspection | B-05 | T-19 | VERIFY |
| **F-22** | P1 | Host-specific grants can apply to a newly created Secret with the same name; an old identity can re-use access unless generation and state are independently fenced. | **C** RBAC name semantics, Lab grant shape; scenario untested | B-05 | T-12/17 | OPEN |
| **F-23** | P1 | Model isolation and blast-radius equivalence cannot be asserted between BYOH, vCluster, VNC/KubeVirt and HCP. | **D** profile-level evidence absent | B-15 | T-35 | OPEN |
| **F-24** | P2 | Independent historical evidence should resist alteration/deletion/rollback by the system it evaluates; current evidence-store trust boundaries and protections require verification. | **D** no store-integrity E2E | B-11/14/16/17 | T-36/37 | OPEN |
| **F-25** | P2 | RBAC escalation/alternate binding and implicit resource wildcard drift can defeat a named permission audit; check effective permissions, not only deletion of two known bindings. | **C** wildcard/controller source; **D** future paths | B-01/02/07 | T-03/07 | OPEN |

| **F-26** | P1 | etcd/Velero backup files can contain sensitive management Secrets, authorization objects and/or encryption key material; Kubernetes resource encryption alone does not protect the entire exported artifact. | **D** design requirement; actual encryption/backup profile unverified | B-18 | T-38/39 | VERIFY |
| **F-27** | P1 | A guard/VAP/webhook may be missing, disabled or misconfigured without independent detection; cross-boundary denial events may be unobserved. | **D** detection coverage not independently audited | B-19 | T-40/41 | VERIFY |

## Primary source pointers (review reports, not independently rerun here)

**Codex (Round 1), BYOH pinned Git revision:**

- `config/rbac/secret_reader_clusterrole.yaml`, `secret_reader_clusterrolebinding.yaml`, `kustomization.yaml` — F-01. Git origin: VMware Tanzu `829f22718180a4aaf38d01528bf024ca973d877a` (2022-06-10), preserved through superbrothers baseline `5ea71bf4ed5d7e592d66252d62c1613334c296af`.
- `Makefile`, `hack/dev/byoh-controller.sh`, Lab `scripts/mgmt/kind-up.sh`, `lib/byoh_grants.py` — F-02, F-05.
- `config/rbac/role.yaml`, `main.go`, `controllers/infrastructure/byoadmission_controller.go` — F-03/F-04.
- `apis/infrastructure/v1beta1/byohost_webhook.go`, `controllers/infrastructure/byomachine_controller.go` — F-06/F-07/F-09.
- `agent/reconciler/host_reconciler.go`, CAPI CABPK controller — F-10/F-21.
- `config/webhook/manifests.yaml`, `internal/safety/noreplacement/{admission.go,update.go}`, local `config/webhook/no-replacement/machine-webhook.yaml` — F-11/F-12.
- `ok-cluster/internal/bootstrapauthority/kubernetes_store.go`, `internal/desiredauthority/domain_fence.go`; ADR-CAPI-003/006/007 — F-13.

**Reviewer contributions:** Claude's final challenge N-1 to N-7 supports F-08/F-02/F-15/F-14/F-09/F-13/F-18. Codex final five issues supports F-07/F-08/F-10/F-09/F-16. Gemini final supports F-17/F-21/F-15/F-13/F-18; some suggested implementation mechanisms and token TTLs remain hypotheses, not adopted facts.

## Triage and next actions (read-only discovery outcomes)

1. **Containment first:** F-01/02/03/04/05/06/07 plus effective live permissions and actual enrollment pathway; no enrollment expansion until G-BYOH-ENROLL closes.
2. **Recovery correctness:** F-08 and F-10/13/14 before promoting G-DR/G-UPGRADE. Restore from **before** revocation and grant consumption is a mandatory attack test, not an ordinary happy-path recovery drill.
3. **Engineering spikes, not premature commitments:** F-09 identity generation, F-15 CEL/webhook coverage, F-17 controller grant delegation, F-20 claim sequence and F-21 workload token TTL.
4. **Evidence lifecycle:** F-18 and F-24. Require exact scope and immutable digests in the matrix before advancing any maturity label.

**CAPI ADR reconciliation:** See `04-capi-adr-crosswalk.md` for source-confirmed accepted architecture targets (001–007), not implementation proof.

**Important boundary:** Some P0 findings represent a *release-blocking design risk* rather than a vulnerability reproduced in a live cluster. Fixing one finding does not establish the absence of others. These findings are not authorization to change systems or publicize vulnerabilities.
