# Independent Architecture Review — AI Security Agent v0.1

**Use this same prompt and the same exact source revisions for Claude, Codex and Gemini.**

## Review objective

Challenge the draft OpenKubes AI Security Agent architecture, not just its prose. Determine whether the proposed read-only assessor can be implemented without becoming a hidden authorization authority, a privileged tool proxy, a source of false PASS claims or a production blocking dependency.

## Part A — Required sources

Read **all** of:
1. `architecture/security/ai-security-agent/README.md`
2. `architecture/security/ai-security-agent/CONTROL-CATALOG-v0.1.md`
3. `architecture/security/ai-security-agent/ASSESSMENT-CONTRACT-v0alpha1.md`
4. `architecture/decisions/ADR-Platform-000-security-first.md` (Accepted principles)
5. `architecture/security/discovery/v0.2/README.md`
6. `architecture/security/discovery/v0.2/01-security-baseline.md`
7. `architecture/security/discovery/v0.2/02-findings-register.md`
8. `architecture/security/discovery/v0.2/03-evidence-matrix.md`
9. ADR-Platform-021, 030, 031, 034, 035, 037, 042, 043, 044, 047, 048 in `architecture/decisions/`
10. `website/pages/research/security/hitl-hotl-policy-bounded-autonomy.md`

Where CAPI crosswalk claims matter, read `architecture/security/discovery/v0.2/04-capi-adr-crosswalk.md` and original Accepted CAPI ADRs in `openkubes/ok-cluster` as available. **Do not claim direct source verification if you did not access it.** Distinguish source-reading conclusions from outside security expertise.

## Part B — Questions

- Does P0 avoid runtime privileges, arbitrary file/network access, prompt injection, credential exposure, and implicit model-based scoring authority?
- Are controls faithfully mapped to the stated B/F/T IDs, or does the seed invent associations, maturity and evidence certainty?
- Does the proposed contract preserve ADR-021 provider neutrality and genuinely separated agent/tool-server/tenant identities? Is any read-only API too broad?
- Can the Security Agent influence mutation via recommendation injection, emergency-stop misuse, gatekeeping outage or fake approval?
- Is the SRE/Policy Authority split cryptographically and operationally preserved through exact canonicalized transition identities, grant and evidence references?
- What happens when evidence is missing, stale, restored from an older snapshot, forged or held in a compromised storage domain?
- Are HOTL standing mandates explicitly research-only and separate from ADR-035's human approval baseline?
- Are findings safe to publish? What information must be redacted and what vulnerability-disclosure process is needed?
- Which acceptance tests can truly run offline and which require API, multi-tenant, real host, failure and recovery E2E?
- Is the phased plan incremental, realistic, minimal, and recoverable? What would be the **smallest useful P0**?

## Part C — Required response format

A. **Verdict:** ACCEPT / REVISE / BLOCK, with brief rationale  
B. **Findings table:** ID, severity, exact file/section, evidence, required correction  
C. **ADR and normative conflicts:** accepted vs proposed vs discovery vs implementation status  
D. **Threat/failure scenarios:** at least six, with preventative and detective controls  
E. **Phase-by-phase assessment:** P0–P4 with blockers, realistic tests and exit gates  
F. **Precise edit suggestions:** text/replacement and file/section  
G. **Open architecture questions:** blockers versus future work  
H. **Confidence / inspected sources / sources not available / tests actually run**

Do **not** manufacture PASS results, cite private Jira issue numbers as public evidence, recommend expanding agent RBAC or treat Security Agent findings as mutation authority. Do not propose implementation writes or publication until the review is consolidated.
