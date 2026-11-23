# OpenKubes Security Assessment Contract — Candidate v0alpha3

**Status:** Research DRAFT. No deployed API, accepted normative contract, authority, production PASS, live Kubernetes access or HOTL. Based on [consolidated Codex/Claude findings](INDEPENDENT-REVIEW-CONSOLIDATION-v0.3.md) and [Specification v0.3](CAPABILITY-SPEC-v0.3.md).

## 1. P0 — one fixed offline byte bundle

P0 accepts **one bounded strict JSON object** over an explicitly supplied byte stream (stdin); no caller-supplied URLs, artifact URIs, file names, resolver settings, environment, Secret options, credentials, model prompts or executable scripts. Reject duplicate keys, unknown keys, invalid sizes/types and ambiguous or sensitive input. Any unclassifiable resource/field is rejected without echoing submitted bytes. Use a synthetic B-01 fixture only, with synthetic namespace and host identity.

No resolver exists in P0. A no-network input path is necessary but not sufficient for a security claim: run the evaluator in a verified unprivileged OS/container sandbox with disabled outbound network, no ambient filesystem/host mounts, token projection or credentials, read-only runtime and bounded CPU/memory/time. Verify enforcement with negative tests. A process that *could* inspect host files is **not proven isolated** just because its code does not do so.

## 2. Minimal current operation

`assess_declared_rbac_bundle` checks an allowlisted, synthetic Role/ClusterRole+RoleBinding/ClusterRoleBinding tuple and declares the existence of any scope-relevant binding/rule in the supplied bundle. A Role alone grants no access. It cannot say the real host can read Secrets, that another grant is absent, that a policy operates live or that a platform test is PASS. Incomplete inventory requires `INSUFFICIENT_EVIDENCE`.

An example of a *future* fixture envelope:

```json
{
  "schema": "openkubes.security-assessment.offline-bundle.v0alpha3",
  "fixture_id": "synthetic-b01",
  "catalog": {"version": "v0.2", "source_revision": "pinned-review-revision"},
  "control_id": "B-01",
  "scope": {"profile": "SYNTHETIC_BYOH", "namespace": "fixture-ns"},
  "completeness": {"grants_complete_for_scope": false},
  "resources": [
    {"kind":"Role","metadata":{"name":"fixture-role","namespace":"fixture-ns"},
     "rules":[{"apiGroups":[""],"resources":["secrets"],"verbs":["get"]}]},
    {"kind":"RoleBinding","metadata":{"name":"fixture-binding","namespace":"fixture-ns"},
     "roleRef":{"kind":"Role","name":"fixture-role"},
     "subjects":[{"kind":"User","name":"fixture-host"}]}
  ]
}
```

Here `pinned-review-revision` is a placeholder in this non-executable example, **not a valid runtime source SHA**. An implementation must reject unpinned catalog values and use a precisely declared trusted revision. The number of resources and byte count are bounded by implementation conformance tests.

## 3. Fixed advisory output vocabulary

```json
{
  "schema": "openkubes.security-assessment.offline-result.v0alpha3",
  "fixture_id": "synthetic-b01",
  "control_id": "B-01",
  "direct_finding_ids": ["F-01","F-25"],
  "required_test_ids": ["T-01","T-02","T-03","T-04"],
  "assessment_disposition": "INSUFFICIENT_EVIDENCE",
  "declared_binding_observed": true,
  "source_classification": "UNVERIFIED",
  "verification_disposition": "UNREVIEWED",
  "recorded_platform_test_outcome": "NOT_RUN",
  "current_applicability": "UNKNOWN",
  "profile_approval": "NOT_APPROVED",
  "severity": "UNASSESSED",
  "evidence_gaps": ["Actual-principal live API observations were not supplied"]
}
```

Only the trusted deterministic evaluator can populate catalog IDs or dispositions; user fields cannot create new findings, PASS records, approval or grant tokens. Fixed output cannot contain user-supplied untrusted text, executable remediation or secret-bearing bytes.

The following dimensions are *orthogonal*: source classification; producer/reviewer verification; historical recorded run outcome; present applicability/health; independently owned profile approval. **P0 platform-control test outcome is always NOT_RUN** even if the evaluator's own unit/conformance tests pass.

## 4. No hidden authority, no implicit gating

Assessor output is advisory-only. It is never a Policy Authority decision, human approval, grant, admission token, mutation request, stop/pause/revoke operation, break-glass pass or required controller/CI/recovery predicate. The assessor cannot write controller-watched resources or approval stores. A human-facing advisory must remain separate from any canonical semantic approval rendering, never able to alter its reviewed digest.

Unknown/stale/unverifiable evidence must be `INSUFFICIENT_EVIDENCE` or `REJECTED`, not `PASS`. Assessor absence does not affect independent protected mutation authorization, whose own fail-closed/recovery properties remain in force.

## 5. Future live observation interfaces (separate review)

The three existing **ADR-021** functions (`get_platform_health`, `investigate_workload`, `collect_diagnostic_evidence`) are **not** a general RBAC/SAR/CSR or Secret-scope interface. Do not add `create subjectaccessreviews`, impersonation, wildcard list or permission to read Secrets to the ADR-021 get/list/watch ServiceAccount and call that read-only. Effective authorization must be proven using actual principals and real API denials, not source manifests or SubjectAccessReview alone.

A future security-diagnostics provider requires its **own OpenKubes-owned, capability-declared, narrowly typed observation contract**, or a separately reviewed scoped provider, backed by independent authorization at ingress, direct-backend path, object lookup, cache and output. Audience-bound delegated caller, actual provider/workload identity, tenant, immutable target, observed resource and authorized recipient must be checked at every hop. No arbitrary SAR, file, URI, log, fleet, Secret or tool-server proxy.

If a network service is approved, OpenKubes owns the versioned normative **HTTP/OpenAPI** schema; MCP/CMCP is an optional thin projection, never the sole semantic contract. Offline P0 has no transport choice to make.

## 6. Future external evidence verification

A SHA-256 digest proves byte identity only. External evidence judged verified/current must have an independently authenticated/authorized producer and reviewer, exact resource/profile/dependency/operation binding, expected and observed effects, time window, protected sequence/completeness and **independent tamper-evident provenance** outside the evaluated cluster's compromise/restore domain (or independently justified equivalent trust). Do not claim any specific ledger/signing service already exists.

Historical receipts, present health, current validity and **current monotonic revocation/consumption/ownership facts** come from different authority owners. If provenance, integrity, producer authorization, sequence, freshness or required independent anchor is unavailable, return `INSUFFICIENT_EVIDENCE` or `REJECTED`; never infer current PASS from a signed historical record.

## 7. Future AI SRE advisory review

Preliminary advice on an *untrusted candidate* binds to candidate digest only and cannot be presented as a canonical-transition review. The latter requires a trusted, immutable, versioned reviewed semantic projection bound to canonicalization profile/version, review renderer/version, review artifact digest, exact canonical digest, original principal, tenant/target, predecessor, target revision, transition identity, action and execution profile binding. No arbitrary advisories may alter the canonical human review artifact; all displayed findings are attributed and distinct from protected approval.

Review records are **non-redeemable references**; neither agent input nor findings can mint Policy grants, claim, acceptance or stop authority. HOTL remains a separate research topic requiring a new Accepted normative ADR.

## 8. Disclosure, gates and test obligations

Sanitize **before any model input, output, exception, audit, cache, notification, export or publication**. Classify unknown content as potentially sensitive and reject safely. A private, security-owner-operated intake validates suspected vulnerabilities and decides coordinated public release; public source hosting alone is not a vulnerability or reason to change visibility.

P0 acceptance requires documented **zero critical safety misses in the bounded adversarial corpus**, including unknown/duplicate fields, oversize inputs, traversal/external refs, attempted instruction injection, sensitive data, privileged output fields, catalog drift and repeatability. Publish exact scope and counts rather than claiming general safety from a number. Execution in a verified restricted sandbox is a separate required proof.

Later phases separately validate actual Kubernetes identity isolation, provider swaps and denial, trusted evidence replay/rollback, authorized recovery with the assessor unavailable, and exact transition review/integrity; none of these can be closed by P0 conformance.
