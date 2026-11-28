# OpenKubes Security Capability — Wazuh + Kubescape Integration Proposal v0.1

**Status:** Research Draft, 2026-11-24. **No integration implemented, no tests run, no deployment, no change of PR #545 Draft status.** This is a short **Build-vs-Integrate revision** to the earlier standalone “AI Security Agent” research, not a new Accepted ADR.

**Working hypothesis:** Use **both** Wazuh (host/security events, FIM, host inventory/vulnerabilities) and Kubescape (Kubernetes posture, RBAC, workload vulnerabilities, runtime signals) as **complementary replaceable providers** behind a thin OpenKubes-owned Security Capability. The optional LLM-powered **AI Security Analyst** belongs to the existing AI/Diagnostic user experience and **does not scan, authenticate as a cluster administrator, determine enforcement truth or mutate resources**. Neither a new agent runtime nor a second scanner is required from OpenKubes.

**References:** [Integration & Trust Boundaries](INTEGRATION-TRUST-BOUNDARIES-v0.1.md), [Data & Evidence Model](DATA-EVIDENCE-MODEL-v0.1.md), [Control Catalog](CONTROL-CATALOG-v0.2.md), [Assessment Contract](ASSESSMENT-CONTRACT-v0alpha3.md), ADR-Platform-000 (Accepted principles), ADR-021 (Draft; **three existing diagnostics functions, not a generic security API**), ADR-035 (Proposed; agent untrusted and advisory). The existing synthetic offline P0 scope remains a **research alternative**; adoption of this dual-provider design does **not** retroactively approve or replace it.

## 1. Provider responsibility, not duplication

| Concern | Wazuh primary | Kubescape primary | OpenKubes responsibility |
| --- | --- | --- | --- |
| Bare-metal OS/package vulnerabilities | Host software inventory and vulnerability state | Not a replacement for host OS inventory | Map host identity and observation freshness |
| SSH/security alerts, file integrity, host configuration | Events, FIM, SCA, agent status | Kubernetes workload runtime signals may overlap | Keep source facts distinct and correlate cautiously |
| Kubernetes RBAC, posture and workload misconfiguration | Log signals, possibly custom detection | RBAC and framework/configuration scan results | Retain target namespace/workload, control/version and completeness |
| Container-image vulnerabilities and runtime exposure | Possible correlated host signals | Vulnerability manifests / exposure and runtime profile | Deduplicate only when the same exact CVE + image digest + target is proven |
| Admission/policy enforcement | Not an assessor function | Not an assessor function | Kyverno/independent Policy systems remain separate |
| BYOH enrollment/upgrade grants, pivot, DR authority | No native lifecycle proof | No native lifecycle proof | Read-only, profile-specific lifecycle Evidence; independently enforced authority remains elsewhere |

**No fixed deployment promise:** Two **strategic provider interfaces** do not imply both privileged agents must run on every node. Installation footprint, kernel/eBPF permissions, placement, supported clusters and costs require separate operations review.

## 2. Verified upstream interfaces (read-only candidate subset)

### Wazuh adapter

- **Server API**: authenticated REST API, Wazuh RBAC, relevant GET-only information for agent inventory, SCA, syscollector and syscheck/FIM. The API also supports **mutating operations**, including agent management and active response; the adapter must therefore allowlist individual read endpoints, not expose the raw API or admin role.
- **Indexer API**: separate read-only scoped queries over `wazuh-alerts-*` and `wazuh-states-vulnerabilities-*` for alerts and vulnerability records. These must have separately configured index permissions, query limits and redaction.
- **Identity**: Wazuh agent IDs are **not** OpenKubes Machine, BYOH host, Kubernetes Node or Cluster UIDs. Any mapping needs an authorized, time-bound inventory link; ambiguous identities stay unresolved.
- **Privacy**: event payloads may include commands, usernames, paths, IPs and sensitive values. Never hand the raw event stream directly to an LLM. Avoid *active response*, write/manager actions and high-volume unrestricted search.

Upstream: [Wazuh Server API](https://documentation.wazuh.com/current/user-manual/api/index.html), [RBAC reference](https://documentation.wazuh.com/current/user-manual/api/rbac/reference.html), [Indexer indices](https://documentation.wazuh.com/current/user-manual/wazuh-indexer/wazuh-indexer-indices.html).

### Kubescape adapter

- Read *stored* `VulnerabilityManifest`, `WorkloadConfigurationScan` and, where available, runtime `ContainerProfile` outputs through narrowly authorized Kubernetes CRD reads / a vetted query interface.
- Its [MCP server](https://kubescape.io/docs/mcp-server/) includes both **stored-result readers and live scan tools** (`run_framework_security_scan`, `run_rbac_security_scan`, etc.). A tool called “scan” is not equivalent to reading a pre-existing assessment: it may cause new data collection and require broader Kubernetes permissions. Expose a **reviewed read-only allowlist** via the OpenKubes boundary; do not pass through the entire MCP server automatically.
- Treat image CVEs, RBAC declarations and runtime observations as separate evidence classes. The operator/node-agent privileges and supported deployment models must be assessed before deployment, especially on BYOH bare metal.

**No assumption:** Neither provider's API shape, Kubernetes watch permissions, production security health nor an actual cross-provider integration has been verified by running code in this PR.

## 3. Minimal OpenKubes-owned contract (concept only)

The *Security Capability* should expose only a narrow, provider-neutral **read-only findings query**, e.g. conceptual operations `list_security_findings(scope,filters)` and `get_security_finding(finding_id)`. These names are proposals, **not deployed endpoints and not additions to ADR-021**. Separate authorization and normative versioned HTTP/OpenAPI contract review are needed for a live service; optional MCP is only a bounded projection for the AI layer.

A normalized finding should preserve at minimum:

```yaml
# Illustrative fields, not a machine schema or API/CRD
finding_id: synthetic-example
provider: wazuh-or-kubescape
provider_record_ref: opaque-authorized-ref
finding_class: host-vulnerability-or-k8s-rbac-or-runtime-alert
subject:
  cluster_uid: independently-resolved-or-unknown
  machine_uid: independently-resolved-or-unknown
  host_identity: independently-resolved-or-unknown
  namespace: if-applicable
  workload_uid: if-applicable
  image_digest: if-applicable
  operations_model: CAPI-BYOH-or-another-explicit-profile
observed_at: source-provided-time
collected_at: authorized-collector-time
source_version: pinned-provider-and-rule-or-feed-revision
facts: sanitized-typed-source-observations
provenance_status: UNVERIFIED-until-independent-check
current_applicability: UNKNOWN-until-rechecked
evidence_gaps: [example-gap-code]
authority: NONE
```

The optional LLM analyzes a **recipient-safe projection** and may formulate hypotheses, explain severity **as reported by a source**, and propose investigations. It may **not** manufacture CVEs, claim actual access based on declarative RBAC, mark Discovery T-tests PASS, override confidence/provenance, authorize remediation or silently turn reported alerts into proven incidents.

### Identity correlation rule

`WazuhAgentID ↔ inventory host identity ↔ OpenKubes Machine UID ↔ Kubernetes Node UID ↔ immutable Cluster UID ↔ operations model / profile` is a **versioned mapping with evidence**, not a join on hostname, IP or display name. Include valid time interval, issuer/source, and conflict/unknown handling. Kubernetes workloads must also bind namespace + workload UID and, where relevant, exact image digest. Never conflate management and workload clusters.

## 4. One deliberately small evaluation scenario

**Question:** “Which relevant security findings were reported for the BYOH cluster/host around the last upgrade, and which are actually corroborated?”

A possible *later* proof sequence:

1. Obtain separately approved bounded read access to a **single identified test environment** and its time window (no production access by assumption).
2. Read a limited set of Wazuh host alerts/vulnerability records and Kubescape RBAC/vulnerability findings.
3. Resolve each source identity to one immutable OpenKubes cluster and host identity; mark unresolved matches explicitly.
4. Normalize source-provided timestamps, source-record IDs, affected component and observed/unknown revision; preserve both original facts and counter-evidence.
5. Show one read-only consolidated response and an optional LLM explanation with source links, limitations and possible SRE follow-up.
6. Confirm **in a later authorized test phase** that the integration cannot invoke write endpoints, grant authority, change Kyverno policies or retrieve cross-tenant evidence.

**Not in this first slice:** continuous SIEM pipeline, full alert ingestion, eBPF enforcement, auto-remediation, new kagent executor, Handover/Pivot or DR proof, implementation of monotonic authority, or a claim of production-ready lifecycle security.

## 5. Architecture and operating risks to resolve before running anything

| Risk | Proposed restraint |
| --- | --- |
| Wazuh server API is **not inherently read-only** | Dedicated per-action API RBAC, no admin role, allowlisted GET operations, separate restricted Indexer query credentials |
| Kubescape MCP exposes **live scan operations** | Explicit curated read-only tools or independently bounded CRD readers, never unrestricted MCP relay |
| Host and node agents increase attack surface | Assess privilege, kernel/eBPF permissions, supply-chain pinning, resource footprint and failure isolation per operating model |
| Wazuh agent ID/hostnames can change or be reused | Verified, time-bound UID-based inventory binding; uncertainty must remain visible |
| Vulnerability and alert semantics differ | Do not collapse CVE match, exploit observation, configuration risk and production control verification into one PASS |
| LLM might disclose security data | Recipient-specific redaction before context, logs, exports and model; no raw secrets or broad evidence handles |
| Missing/compromised evidence or engine outage | Advisory gap/unknown, never false green; Policy/Executor remain independently available and fail-closed |
| Two providers create duplicate scans and cost | Establish primary responsibilities, filter/TTL and provider opt-in per deployment profile |

## 6. Lightweight decisions and next step

Instead of expanding the earlier **27-decision research matrix**, propose only three questions for the next design review:

1. **Product scope:** Confirm *Security Capability + optional AI Security Analyst* rather than a standalone new security agent runtime.
2. **Provider scope:** Confirm Wazuh **and** Kubescape as complementary candidate providers; no mandatory installation everywhere and no unreviewed privilege expansion.
3. **Pilot boundary:** Choose one named isolated environment and an authorized future read-only evaluation; settle identity mapping and exact minimal output before implementing/testing.

**Review gate:** Independent source/architecture review of this short proposal; user sign-off before any implementation. PR #545 stays Draft. No tests, deployment, Jira edits, merge or website release.
