# OpenKubes Security Assessment Contract — Candidate v0alpha1

- **Status:** Research DRAFT — no accepted API, deployed service, authorization or implementation.
- **Related:** [Capability Specification](README.md), [Control Catalog](CONTROL-CATALOG-v0.1.md), ADR-Platform-000 (Accepted principle), ADR-Platform-021 (Draft diagnostics interface), ADR-Platform-035 (Proposed strict HITL).
- **Transport:** Undecided. Do not infer that a publicly reachable HTTP endpoint exists.

## 1. Scope

Propose a replaceable, **read-only** assessment boundary, initially deterministic over explicitly supplied sanitized offline manifests, source references and test artifacts. Reuse the existing Platform Diagnostics Contract to obtain permitted observations *if* a later reviewed integration needs live data. Do not create a second Kubernetes credentials or mutations path.

Contract ownership is OpenKubes, not any model provider. No evaluator can assign its own roles, rewrite control sources or declare approval.

## 2. Candidate operations

| Operation | Purpose | Required safe input | Return |
| --- | --- | --- | --- |
| `assess_security_posture` | Compare named scope with allowed control set | Authenticated principal reference, tenant/cluster/profile, control IDs, sanitized artifact refs | Scoped assessment with gaps, not a compliance certificate |
| `analyze_rbac_exposure` | Inspect declared/effective RBAC evidence | RBAC manifests or authorized SAR/evidence refs, exact principal and version | Allowed/denied observations, unverifiable areas, proposed negative tests |
| `evaluate_operation_risk` | Advisory review of an SRE candidate | Immutable candidate hash, reviewed canonical transition reference *if available*, expected predecessor and scope | Risk findings **only**; no grants, approval or admitted mutations |
| `verify_security_evidence` | Check supplied artifacts against control/test criteria | Control/test IDs, evidence URI/digest, environment, revision, reviewer context | Completeness/freshness report; actual PASS only for independently validated run |
| `explain_security_finding` | Explain evidence-linked finding and possible safer paths | Finding ID, bounded references, recipient scope | Cited explanation plus uncertainty and recommended investigation |

The operation name `evaluate_operation_risk` must never be conflated with the Policy Authority's authoritative decision. Any live observation adapter remains lower trust than the protected authority chain.

## 3. Common request envelope (illustrative)

```yaml
schema: openkubes.security-assessment.request.v0alpha1
request_id: example-001
caller:
  authenticated_principal_ref: "external-verifier-supplied"
  tenant_id: "tenant-example"
scope:
  environment_id: "offline-sanitized-fixture"
  cluster_id: "cluster-example"
  namespace: "demo"
  deployment_profile: "BYOH-DEV"
operation: analyze_rbac_exposure
controls: [B-01, B-02]
inputs:
  manifest_refs:
    - uri: "artifact://sanitized/rbac.yaml"
      sha256: "<digest supplied by trusted artifact handler>"
  evidence_refs: []
privacy:
  allow_raw_secrets: false
```

Identity must be attested by the trusted ingress, **not** by accepting caller-provided strings as authentication. The example is a shape proposal, not a working service schema or permit to fetch arbitrary `artifact://` URLs. Only an allowlisted artifact resolver may supply the referenced bytes after independent access checks.

## 4. Common assessment and finding envelopes

```yaml
schema: openkubes.security-assessment.result.v0alpha1
request_id: example-001
assessment_id: example-result-001
scope:
  tenant_id: "tenant-example"
  deployment_profile: "BYOH-DEV"
catalog:
  source_revision: "<pinned git SHA>"
  catalog_version: "v0.1"
status: INDETERMINATE
findings:
  - finding_id: "generated-assessment-item-1"
    capability: SEC-CAP-01
    control_ids: [B-01]
    discovery_finding_ids: [F-01]
    severity: "UNASSESSED"
    provenance_class: "DESIGN_RISK"
    confidence_statement: "Fixture suggests broad role; no live credential test"
    observed_fact: "Manifest declares named-Secret get binding"
    inferred_risk: "Scope could exceed intended host authorization"
    source_refs: ["artifact://sanitized/rbac.yaml#sha256=<digest>"]
    required_negative_test_ids: [T-02, T-03]
    test_outcome: NOT_RUN
    maturity: PROPOSED
    recommended_next_action: "Verify effective RBAC with bounded principal identity"
    authorized_to_execute: false
evidence_refs: []
review:
  independently_reviewed: false
  reviewer_ref: null
```

All example values are illustrative. A production-target scan must never emit a fabricated PASS, CVSS number, live vulnerability, or reviewer approval. The model may propose severity but it remains `UNASSESSED` until supported by a separately defined scoring and verification procedure.

## 5. Required error and uncertainty semantics

- `UNAUTHORIZED_SCOPE`: caller cannot inspect requested tenant, cluster, namespace or artifact.
- `INVALID_SOURCE`: malformed, ambiguous or unpinned source; duplicate IDs/keys cannot be silently repaired.
- `EVIDENCE_MISSING`: no relevant run artifact or provenance for a claimed proof.
- `EVIDENCE_STALE`: evidence tied to a different manifest, configuration, identity or deployment revision.
- `INDETERMINATE`: plausible concern but not provable from supplied data; not interchangeable with PASS or FAIL.
- `UNAVAILABLE_PROVIDER`: live diagnostic provider unavailable; no fallback to privileged direct Kubernetes access.
- `REDACTION_REQUIRED`: sensitive material detected; must sanitize before optional AI summarization.

Failure in an advisory assessor must not create an unconditional cluster-wide mutation blockade. Separate operational enforcement/recovery decisions remain with trusted platform owners.

## 6. Credential, tool and data constraints

- P0: no network, Kubernetes credentials, host mount, Secret retrieval, SSH/BMC, write-capable MCP tool or executing user-supplied commands.
- P1+: enforce distinct agent and provider identities and explicit no-Secret/get/list/watch scope; negative tests use the **actual identities and APIs**, not only prompt behavior.
- Treat all manifests, logs, Markdown, model output and external evidence as untrusted data. A prompt-injection instruction must not change source mappings, evidence status, authorization or code execution.
- No shared privileged tool-server ServiceAccount. Backend authorization must remain effective even when the optional MCP/CMCP gateway is bypassed.
- Audit, provider trace, normalized assessment and raw evidence must have separate access controls and retention; redact secret-bearing payloads from central audit.
- Any cross-tenant data movement or public vulnerability disclosure requires an independently reviewed route.

## 7. Mandatory contract tests before live adoption

1. Valid offline fixture produces stable, cited findings, identical on replay.
2. Missing or changed source revision cannot produce PASS.
3. Unknown control/finding/test identifiers and attacker-controlled source IDs are rejected.
4. Cross-tenant artifact reference is denied before content retrieval.
5. Sensitive Secret, token, certificate or kubeconfig sample is redacted before model context and logs.
6. Agent/model prompt requesting mutation or policy override results in no action.
7. Actual agent/tool-server identities cannot mutate or read excluded Secrets (once live provider exists).
8. Security Agent result cannot be accepted as Policy Authority grant, human approval or admission token.
9. Shared-provider outage returns explicit uncertainty, not implicit PASS or automatically broadened credentials.
10. Review proposal after digest change: prior advisory result cannot claim a new candidate was assessed.

**Exit rule:** Phase-0 tests can validate the *assessment software*, not the production status of OpenKubes platform controls.

## 8. Open design decisions

Schema location, transport, evidence resolver, cryptographic provenance format, retention, severity method, adapter scope and review ownership remain open. A future normative ADR may govern security-assessment contracts, but this document does not authorize any agent-based approval or HOTL mutation.
