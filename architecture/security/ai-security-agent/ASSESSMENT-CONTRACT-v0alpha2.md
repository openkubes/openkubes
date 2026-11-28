# OpenKubes Security Assessment Contract — Candidate v0alpha2

- **Status:** Research draft, non-normative. No implementation, service, policy or production approval.
- **Source basis:** [AI Security Agent Specification v0.2](README.md), [source-reconciled control catalog](CONTROL-CATALOG-v0.2.md), ADR-Platform-000 (Accepted principles), ADR-Platform-021 (Draft diagnostic design), ADR-Platform-034/035 (Proposed).
- **Initial implementation:** A deterministic, offline single-bundle evaluator for one B-01 declared-RBAC test. **No model, network, API endpoint or privileged identity.**

## 1. Strict P0 offline assessment boundary — SA-01 / SA-09

P0 accepts exactly one **bounded synthetic fixture bundle** passed as bytes by the trusted test harness. Its identifiers resolve **only within the supplied package**. A bundle contains a pinned schema/catalog revision, resource documents, declared intended scope, and optional pre-existing synthetic observation records. The evaluator does not resolve `artifact://`, URLs, paths, symbolic links, process environment, Kubernetes API objects or external provider handles. There is no caller-set `allow_raw_secrets` switch.

The harness must run it as an unprivileged process with restricted memory/CPU/time, no network namespace access, no ambient Kubernetes credentials, no mounted host homes, Secrets or service-account tokens, a read-only runtime and only the explicit fixture bytes. Tests must verify these denials; *a documented setting is not evidence that the sandbox actually enforced it*. The offline parser must reject duplicate keys, ambiguous YAML/JSON, unknown schema/IDs, overlarge or malicious inputs, unsupported resource types, and instructions embedded in comments or fields.

P0 evaluates **declared resources**, not effective cluster authorization. A Role or ClusterRole alone does not grant rights; the fixture must contain bindings and enough contextual objects to make a bounded claim. Incomplete inventory yields `INSUFFICIENT_EVIDENCE`. No production control can receive a platform `PASS` in P0. No LLM is needed or called.

## 2. Fixed P0 operations and types

Initial operation: `assess_declared_rbac_bundle` — returns findings about **declared** RBAC binding and a separate inventory/evidence gap report. Inputs are strictly typed and allowlisted. Future candidate operations (`assess_security_posture`, `analyze_rbac_exposure`, `evaluate_operation_risk`, `verify_security_evidence`, `explain_security_finding`) are **NOT ACTIVATED** in P0. They need independent consumer, schema, ownership and access review. No arbitrary SAR, log, URI, Secret, environment, fleet inventory, tool or filesystem query is exposed.

Illustrative P0 input shape (not a live API or machine-verified schema):

```yaml
schema: openkubes.security-assessment.offline-bundle.v0alpha2
fixture_id: synthetic-b01-rolebinding
catalog:
  version: v0.2
  source_revision: "<trusted pinned source SHA>"
scope:
  profile: SYNTHETIC_BYOH
  tenant: fixture-tenant
  namespace: fixture-ns
controls: [B-01]
resources:
  - id: role-1
    kind: Role
    namespace: fixture-ns
    declared: {metadata: {name: fixture-role}, rules: []}
  - id: binding-1
    kind: RoleBinding
    namespace: fixture-ns
    declared: {metadata: {name: fixture-binding}, subjects: [], roleRef: {}}
completeness:
  grants_complete_for_scope: false
```

Do not treat scope strings in a fixture as an authenticated caller. In P0 the harness owns its fixture boundary, and all artifacts remain synthetic.

## 3. Assessment status — SA-02 / SA-07

Return separate fields rather than one ambiguous `status`:

| Dimension | Semantics |
| --- | --- |
| `source_classification` | `SOURCE_CONFIRMED / REPORTED_LAB / DESIGN_RISK / UNVERIFIED`; source claim provenance, not verification |
| `verification_disposition` | `UNREVIEWED / SOURCE_LINK_CHECKED / INDEPENDENTLY_VERIFIED / REJECTED`; record/producer trust, not current control health |
| `recorded_test_outcome` | `NOT_RUN / PASS / FAIL / INDETERMINATE`; retained historical run result, **platform-control NOT_RUN in P0** |
| `current_applicability` | `UNKNOWN / APPLICABLE / STALE / CONTRADICTED`; current target/version/dependency match |
| `profile_approval` | `NOT_APPROVED / SCOPED_APPROVAL`; imported from an independently trusted owner, **never emitted by assessor** |
| `assessment_disposition` | `OBSERVED_DECLARATION / INSUFFICIENT_EVIDENCE / REJECTED`; assessor's narrow result, not PASS or a policy decision |

A hash proves byte identity, not producer authorization, reviewer approval, log completeness or current security authority. Historical evidence, current health and **current revocation/grant/owner facts** must be referenced from separate trusted owners. Replayed, stale, missing, conflicting, truncated, unverifiable or compromised-producer evidence must not be silently promoted to verified/current. The assessor neither mints nor restores monotonic facts.

Illustrative P0 output:

```yaml
schema: openkubes.security-assessment.offline-result.v0alpha2
fixture_id: synthetic-b01-rolebinding
control_id: B-01
scope: {profile: SYNTHETIC_BYOH, tenant: fixture-tenant, namespace: fixture-ns}
assessment_disposition: INSUFFICIENT_EVIDENCE
observations:
  - kind: DECLARED_ROLE_BINDING
    source_resource_id: binding-1
    description: "Declared binding present; complete effective access is not established"
recorded_platform_test_outcome: NOT_RUN
current_applicability: UNKNOWN
profile_approval: NOT_APPROVED
required_test_ids: [T-01, T-02, T-03, T-04]
source_catalog_revision: "<trusted pinned SHA>"
evidence_gaps:
  - "Full set of effective grants and real-principal authorization observations not supplied"
findings:
  - finding_class: DECLARED_RBAC_SCOPE_REVIEW
    severity: UNASSESSED
    advisory_text: "Verify effective scope with a separately authorized identity-specific test"
```

No `authorized_to_execute`, `approved`, `allow`, `deny`, grant, redeemable token, signer/private-key field or policy-decision response belongs in this schema. **Do not let an advisory assessment become an implicit mutation input.**

## 4. Future scoped live observation — SA-04 / SA-08

Only a separate approved P1+ adapter may introduce live reads. It must demonstrate a forcing consumer, reuse ADR-021's provider-neutral diagnostics and capability-limited surfaces where suitable, and use authenticated, audience-bound delegation. The backend intersects **original caller, workload/service identity, provider capability, tenant, immutable cluster/target, observation class, current policy, and recipient** at each hop. Enforce authorization again on evidence lookup, cache reads, delivery and exports. Neither an untrusted caller-supplied principal string nor an agent's prompt provides identity or access.

Allow only typed pre-authorized observation classes. Opaque, scope-bound references may point to evidence already accessible to the principal. No general file, URI, SAR, log, Secret, credential, fleet-wide search or write/impersonation proxy. Test real effective tool-server ServiceAccounts and direct backend paths: a read-only prompt is not an RBAC control. Keep `get/list/watch secrets` excluded and apply an independent safe projection for ConfigMaps, log lines, annotations and other sensitive sources before **any model input, UI, export, error, cache or telemetry**. All recipients are independently authorized.

## 5. Future AI SRE advisory interface — SA-05 / SA-06

A raw SRE candidate may receive **preliminary candidate-only advice**, bound to its candidate digest and scope. It must never be described as a review of an authorized canonical transition.

Canonical-transition assessment is possible only when the assessor receives a **trusted, immutable, non-redeemable read-only review reference** whose verified binding includes: effective predecessor and requested revision, immutable caller/tenant/target, exact semantic operation, `transitionID`, `fromRevision`, `toRevision | DESIRED_ABSENT`, canonical request digest, review artifact digest, canonicalizer and renderer versions, and profile-specific execution binding. A modified or stale binding invalidates the applicability of old advisory findings; it does **not** modify or reissue protected human approval.

The trusted human-approval, Policy Authority, Contract Executor, claim and acceptance paths remain independent. The Security Agent cannot write their stores, influence their grants, act as an admission approver, hold stop/revoke/pause/break-glass credentials, publish controller-watched resource changes, or return an authority-shaped record. **Assessment availability and findings must not be dependencies of mutations, approvals, lifecycle reconciliation or authorized recovery** absent a separately accepted architecture amendment and its own liveness tests. Human readers may view explicitly attributed advisory findings **outside** the protected semantic approval artifact.

## 6. Trusted evidence and public disclosure — SA-02 / SA-07 / SA-08

For a later `verify_security_evidence` consumer, each externally verified record needs source repository/revision, rendered artifact digest, dependency versions, immutable target/profile, actual principal and operation, test ID, expected and observed result, observation window, independently authorized producer, authenticated reviewer, signed/otherwise protected artifact reference, sequence/completeness and relevant freshness policy.

Historic test outcome, current target applicability, current health and rollback-resistant authority remain separate. A signed receipt alone neither proves fresh current status nor establishes revocation, owner fencing or grant consumption.

Findings default to restricted access. Safe output projection applies to **reports, model context, logs, traces, cache keys, errors, exports, notifications and public pages**, not just final summaries. Sensitive vulnerabilities use a private security-maintainer intake with source/affected-version/impact and confidence, independent validation, a coordinated disclosure decision and an explicitly reviewed publication artifact. Do not expose tokens, kubeconfigs, sensitive Secret names/values, private URLs, identifiable topology, live exploit recipes or reusable evidence handles. Fixed P0 finding classes use `UNASSESSED` severity; LLM-generated severity is not an approved scoring method.

## 7. Separate evidence and implementation gates — SA-09

**P0 contract conformance:** deterministic parser, bounded input, one B-01 synthetic RoleBinding assessment, omitted/incomplete binding inventories, source-ID mismatch, duplicate YAML keys, malicious text, sensitive projections, no ambient filesystem/network/credential access, stable repeatable output. Platform-control tests remain `NOT_RUN`.

**P1+ platform-control validation:** separately authorized real API identities, real effective read/Secret/mutation denials, provider failure and tenant isolation with pinned artifacts. An offline RBAC declaration is insufficient to prove a real principal's permissions.

**Named-profile production approval:** independent, version-specific reviewer decision after E2E, outage, restore, trust and recoverability evidence. A passed contract unit test never implies this gate is closed.

**Research boundary:** HOTL eligibility and action remain future work under a new accepted normative ADR. The assessor may analyze such evidence but never enables the action.
