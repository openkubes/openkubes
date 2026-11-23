# OpenKubes Security Evidence Matrix v0.2

**Status:** Proposed verification plan, **not an executed test report**. **Date:** 2026-11-23.  
**Source revisions inspected by Codex:** BYOH `15b668d4`, Scaleway Lab `68669ea6`, Architecture `05033fbb`, ok-cluster `16f9c1be`, CAPI v1.14.4 `4356c154`. A local uncommitted BYOH grant/claim candidate and CAPD evidence **must never be represented as merged, tested protected real-host upgrade**.

## 1. Test definitions and control traceability

**Test outcome notation:** `NOT-RUN` = no test was executed in producing this document; `SOURCE` = source behavior described in Codex review; `REPORTED-LAB` = prior live check reported in the discovery; neither counts as PASS in this matrix. A cell such as `positive + negative` means both must be demonstrated. Only an attached run artifact with pinned context can change a test to PASS.

| Test | Related baseline / finding | Enforcement / target | Positive and negative verification (proposed) | Evidence required | Current evidence |
|---|---|---|---|---|---|
| **T-01** | B-01/BYOH-01 F-01 | Host User RBAC | Two distinct real host credentials can `get` only their own named bootstrap and installer Secret while actually needed | Identity/cert subject, exact roles/bindings, live API results | SOURCE + REPORTED-LAB broad-grant exposure; **NOT-RUN** post-fix |
| **T-02** | B-01 F-01 | Host User RBAC | Host A `GET` on Host B's Secret, foreign namespace/cluster kubeconfig/CA and management secrets must be `Forbidden` | Live named `GET`, namespaces, user info, audit | NOT-RUN |
| **T-03** | B-01/02 F-01/25 | RBAC effective permissions | Host `LIST/WATCH secrets`, `LIST/WATCH byohosts` where not required, and alternative inherited/aggregate privileges are denied | SAR/impersonation + actual API list/watch + full binding dump | SOURCE default grants; NOT-RUN post-fix |
| **T-04** | B-01 F-01 | API read before and after scope change | Existing host allowed own named Secret; no permission to read arbitrary other named Secret in same namespace | Both allowed and denied API requests from **real cert** | NOT-RUN |
| **T-05** | B-02 F-02 | Provider artifact/install | Fresh install, dev `up`, repeated install, reinstall, provider upgrade: never an effective broad host grant, including transient stages | Rendered manifest hashes + continuous SAR sampling + reconciler health | SOURCE unsafe paths; NOT-RUN safe path |
| **T-06** | B-02/11 F-02/08 | Rollback/restore | Missing hardening marker, interrupted bootstrap, partial RBAC write, rollback and restored stale snapshots cannot regrant hosts | API audit + authorization time series + restored snapshot IDs | SOURCE marker gaps; NOT-RUN recovery |
| **T-07** | B-07 F-03/25 | BYOH controller SA | Exact controller identity is denied unrelated Secret read/write, CSR approval in manual mode, unrelated infrastructure writes | Effective SAR/API checks, live reconciliation metrics | SOURCE broad SA rights; NOT-RUN narrowed |
| **T-08** | B-07 F-03/17 | Controller reconcile/RoleBinding | Narrowed controller can successfully provision, reconcile, delete; unauthorized RBAC bind/escalation attempt rejected | E2E logs, permissions snapshot, negative bind requests | SOURCE SA manifest; NOT-RUN |
| **T-09** | B-03 F-04 | CSR approver/inventory | Approved inventory-bound host/CSR key succeeds; foreign hostname/namespace, token, wrong key, duplicate identity denied | Exact CSR UID, token ID, proof-of-possession logs, signed cert user | SOURCE manual lab helper; NOT-RUN in-cluster |
| **T-10** | B-03 F-04 | CSR concurrency | Token replay, duplicate CSR UID/replacement, simultaneous claims, expired token all denied after first accepted enrollment | Controlled concurrency and signer/audit evidence | SOURCE approval gaps; NOT-RUN |
| **T-11** | B-05 F-05 | Host grant writer | After suspension, Secret read denied across 5+ controller reconcile/watch/restarts | User, grant object history, SAR at each restart | SOURCE Lab regrant behavior; NOT-RUN fixed |
| **T-12** | B-05 F-05/22 | Secret generation/grants | Old certificate denied after old Secret deleted, **same-name** Secret recreated, ByoMachine recreated, and grant reconcile | Issuance generation, object UID, API get requests, guard evidence | NOT-RUN |
| **T-13** | B-03/04 F-06 | Assignment & placement | Legitimate authorized placement succeeds; self-applied agent control-plane label does **not** win privileged assignment | Real host credential, selected ByoMachine, owner-approved inventory | SOURCE host-controlled labels; NOT-RUN negative |
| **T-14** | B-06 F-07 | Host reset acceptance | Agent sends correct attached ByoMachine UID in `lastReset`, without independent wipe; controller must **not** release host to assignable pool | Host state before/after, assignment attempts, event/audit and independent wipe proof | SOURCE reset acceptance; NOT-RUN adversarial E2E |
| **T-15** | B-11/17 F-08 | Disaster restore/RBAC | Snapshot taken immediately **before** grant revocation; restore; old identity remains unauthorized before any reconcilers/non-recovery traffic resumes | Snapshot hash/time, external revocation source, first API read, audit | NOT-RUN |
| **T-16** | B-09/11/12/17 F-08 | Disaster restore/grants/authority | Snapshot before grant consumption and management ownership transfer; restore; spent grant unusable and stale writer rejected | External consumption/epoch record + API/host/provider negative tests | NOT-RUN |
| **T-17** | B-05 F-09/22 | X.509 generation | Same hostname/Node name re-enrolls safely; old cert cannot create ByoHost, update status, read new Secrets, while new cert works | Both x509 subjects, identity generation, Node/providerID continuity | SOURCE current CN mapping; NOT-RUN |
| **T-18** | B-05 F-10 | Host execution fence | Suspend after agent fetches payload but before execution; prove unauthorized queued effects cannot proceed | Agent execution logs, operation nonce/status, host-side audit | SOURCE fetch/execute pipeline; NOT-RUN |
| **T-19** | B-05 F-10/21 | Workload bootstrap tokens | Suspend after node join; validate actual workload token TTL, delete/revocation, ability to join unauthorized second node | Real CABPK token metadata + workload API test | TOKEN TTL UNVERIFIED; NOT-RUN |
| **T-20** | B-08 F-11 | Guard install/routing | Fresh deployment has active guard; protected Machine CREATE/DELETE denied by all relevant served API versions & paths | Webhook/VAP manifest, API audit denial, uid observation | SOURCE opt-in guard only; NOT-RUN deployed |
| **T-21** | B-08/09 F-11/14 | Protected BYOH upgrade | Actual kubeadm/kubelet upgrade: old/new versions, preservation of Machine/DockerMachine/Node identity, legitimate approval, no Machine replacement | Pre/post host versions, CAPI objects, audit, rollout traces | Local CAPD **no-op** only; NOT-RUN real protected BYOH |
| **T-22** | B-08/10 F-11/14 | CAPI fallback/MHC | Failed/declined in-place step and MHC attempt: no implicit Machine DELETE/CREATE; authorized recovery succeeds | CAPI/MHC event + admission denies + host restore result | NOT-RUN |
| **T-23** | B-10/13 F-12 | Webhook outage | Down endpoints, expired CA, CNI failure, API reachable: forbidden mutation denied, narrow guard repair completes | Outage injection, signed approved repair, auth/audit, recovery timing | SOURCE failurePolicy Fail; NOT-RUN recovery |
| **T-24** | B-08/13 F-12 | Namespace policy routing | Remove/change selector label as routine actor: denied; status, alternate API paths still protected | Effective API user info, admission audit, labels | SOURCE label-scoped local guard; NOT-RUN negative |
| **T-25** | B-12 F-13 | Cold handover | Reconnect old manager after promotion: workload API, BYOH host actions, SSH/BMC/provider calls all refused where supported | Each endpoint's effective-write denial, current owner record | SOURCE partial fencing; NOT-RUN integrated |
| **T-26** | B-12 F-13 | Offline edge target | Target disconnected during handover stays quarantined until rejects old owner; no old queued action executes on reconnect | Offline/online captures, host queue, endpoint enforcement | NOT-RUN |
| **T-27** | B-10 F-14 | Singleton etcd backup/restore | Crash during `kubeadm upgrade apply`, verify snapshot integrity, recover without unauthorized replacement and no security-state rollback | etcd snapshot hash, full restore/audit, UID continuity, T-15/16 | NOT-RUN |
| **T-28** | B-08/09 F-15 | CEL/webhook coverage | For each invariant, prove whether it is request-local or cross-object; negative foreign UID/registry/checksum mismatch reaches enforcing gate | Policy source + API denial + coverage matrix | DESIGN; NOT-RUN |
| **T-29** | B-09/11 F-15/20 | Grant binding | Invalid/stale/foreign caller or UID, replayed/expired grant, dry-run and concurrent claims cannot spend/forge authorization | CAS ledger state, API audit, operation effects | Local candidate exists; NOT-RUN E2E |
| **T-30** | B-13 F-16 | Policy administration | Installer, lifecycle controller and repair SA cannot delete/disable VAP/Binding or escalate to policy admin | Effective RBAC audit, API denial, policy digest | NOT-RUN |
| **T-31** | B-07 F-17 | RBAC delegation | Per-host RoleBinding reconciler can bind only allowed host Roles; no `bind`/`escalate` to higher privileges | API authz + successful legitimate reconciliation | NOT-RUN |
| **T-32** | B-14 F-18 | Evidence freshness | Change CAPI/BYOH/bundle version; previous PASS remains historical but affected gate reopens for new artifact | Version/digest impact graph, CI gate outcome | NOT-RUN |
| **T-33** | B-16 F-19 | Agent runtime | No standing admin equivalent reaches agent plane; direct mutation or gateway bypass denied | Deployment manifest, effective API requests, issue OK-105 status | Issue evidence NOT independently verified |
| **T-34** | B-09/11 F-20 | Stateful execution recovery | Crash after claim/before API write and after host side effect; avoid double execution, resolve uncertain results using observation | Atomic claim log, idempotency ID, host/target observations | NOT-RUN |
| **T-35** | B-15 F-23 | Multi-model isolation | For each model: break host/tenant boundary attempt, admin/host compromise blast-radius, data-path and recovery proof | Separate model-specific E2E artifact and threat model | No reviewed E2E |
| **T-36** | B-11/14/16/17 F-24 | Evidence integrity | With cluster-admin on protected cluster, try deleting/rewriting/truncating/rolling back historical outcome records; independent sink detects/rejects | Independent append-only signed record/reconciliation | NOT-RUN |

| **T-37** | B-11/17 F-08/24 | Independent monotonic security authority | Write revocation/consumption/epoch outside restore domain; restore pre-event snapshot; verify independent facts are available and current **before API non-recovery traffic/reconcilers**. Repeat with authority unavailable or incomplete: activation denied, or independently invalidate/reissue all affected authority with evidence | External authoritative record proof, committed ordering, restore barrier, API audit | NOT-RUN |
| **T-38** | B-18 F-26 | etcd/Velero backup protection | Verify full backup artifact encryption, access policy, storage permissions and separation from decryption keys; unauthorized principal cannot read protected snapshot or Secrets; approved restore can decrypt | Backup file hash, key custody, access-denial audit, encrypted artifact inspection, restore proof | NOT-RUN |
| **T-39** | B-18 F-26 | Backup crypto/key recovery | Lost/unreachable keys, leaked backup URL, revoked restore identity, old snapshot replay: fail safely; authorized offline key recovery tested | Key recovery runbook evidence, denied object-store read, recovered restore audit | NOT-RUN |
| **T-40** | B-19 F-27 | Control health/detection | Disable/remove guard/VAP/Binding, break webhook TLS and change watched manifest: independent monitoring raises alert within documented latency | Alert rule/delivery log, change audit, monitoring independent identity | NOT-RUN |
| **T-41** | B-19 F-27 | Denied-boundary detection | Host attempts foreign Secret GET and controller attempts prohibited grant; denial AND correctly attributed alert observed without leaking Secret values | API audit and alert evidence, identity binding, delivery timestamp | NOT-RUN |
| **T-42** | B-06 F-07 | Unverifiable remote-host reset | Agent reports correct reset UID but host/wipe proof unavailable; remain quarantined/unassignable; fresh identity alone cannot reactivate old assignment | Enrollment registry, host pool selection, denied subsequent Secret, operator decision | NOT-RUN |

## 2. Gate-to-test minimum coverage

| Gate | Required test IDs | Exit condition |
|---|---|---|
| **G-BYOH-ENROLL** | T-01..14, T-17, T-19, T-31, T-42 | No broad host access on any supported install path; inventory/placement/reset/revocation E2E; legitimate provisioning works |
| **G-UPGRADE** | T-20..24, T-27..29, T-34, T-38/39 | Protected **real** BYOH host operation + deny fallback + independently authorized recovery; CAPD no-op is insufficient |
| **G-DR** | T-06, T-15/16, T-18, T-23, T-25..27, T-36..39, T-42 | Pre-revocation restore does not resurrect authority; stale-plane/edge/host/provider writes denied |
| **G-AGENTIC-WRITE** | T-29/30, T-32..34, T-36/37, T-40/41 | Protected human/policy approval and independent execution/evidence verified end-to-end |
| **G-MODEL-{VCLUSTER,VNC,HCP}** | T-35 plus common applicable tests, T-40/41 | Model-specific evidence, no inherited BYOH claims |

**Global cross-gate controls:** T-32 evidence-freshness applies to *every* gate on material dependency/manifest drift. T-40/T-41 control health and detection apply to every **production** profile where the respective controls are used.

Passing all tests in a gate is necessary, **not automatically sufficient**, for production approval: reviewers must also inspect ownership, failure-domain coverage, supported configuration and drift/version impact.

## 3. Evidence record format — proposal

```yaml
schema: openkubes.security-evidence.v0alpha1
control_id: B-01
finding_ids: [F-01]
test_id: T-02
gate: G-BYOH-ENROLL
outcome: NOT_RUN # PASS | FAIL | INDETERMINATE | NOT_RUN
execution_environment: "<cluster/profile; no production secrets>"
source:
  repository: openkubes/ok-baremetal-byoh
  git_sha: "15b668d4ced7fae2ee78b9175f23cf23c031f90a"
  rendered_manifest_sha256: null
  byoh_version: null
  capi_version: v1.14.4
  kubernetes_version: null
principal:
  authenticated_username: null
  certificate_fingerprint: null
  enrollment_generation: null
operation:
  verb: get
  resource: secrets
  namespace: null
  resource_name: null
  expected: Forbidden
observation:
  http_status: null
  api_audit_event_ref: null
  result_hash: null
  timestamp_utc: null
artifact:
  uri: null
  sha256: null
reviewer: null
notes: "Template only; no execution claimed."
```

## 4. Evidence acceptance and invalidation policy

1. **Never infer actual Secret exposure** from `can-i`: it proves authorization, not secret access or exfiltration.
2. **Test actual requests**, not SAR alone, for key denials and positives; watch for other additive bindings, object names, user groups and denied `list/watch`.
3. **Observe transient intervals** during fresh install, upgrade and restore; after-the-fact successful denial can miss earlier exposure.
4. **Differentiate authorized grant, admission decision, host action and completed outcome.** No single log replaces the other three.
5. **Fail closed on incomplete or conflicting evidence** for promotion, not necessarily by halting unrelated platform operations.
6. **Store historical artifacts outside the protected compromise/restore domain** or verify them through an independent tamper-evident mechanism; protect the metadata mapping versions, tests and evidence.
7. **Invalidate promotion scope on material drift**, not the historical evidence: CAPI version, Kubernetes version, provider changes, policy/manifest digest, controller permissions and deployment shape. Define requalification by affected invariant.
8. **No tests executed for this document.** Every row remains `NOT-RUN` for a new baseline acceptance decision.
