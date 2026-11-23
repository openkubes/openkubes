# OpenKubes Security Architecture Discovery — Working Pack v0.2

**2026-11-23 — DISCOVERY / READ-ONLY / NOT AN ACCEPTED ADR**

Contents:

1. `01-security-baseline.md` — **B-01…B-19** working requirements (including monotonic authority, secret-equivalent backups and detection), BYOH contracts and production gates.
2. `02-findings-register.md` — **F-01…F-27** source-confirmed, reported-lab and unverified design findings.
3. `03-evidence-matrix.md` — **T-01…T-42** proposed security tests and production-gate links. All new-run outcomes are **NOT-RUN**.
4. `04-capi-adr-crosswalk.md` — direct source review of **Accepted ADR-CAPI-001…007** in `openkubes/ok-cluster`, overlap/implementation gaps, and pre-ADR decisions.

## Three independent axes — do not conflate

- **Finding confidence** (`02`): `C` source-confirmed; `L` prior reported lab; `D` design risk; `U` requires verification.
- **Test evidence/outcome** (`03`): `SOURCE`, `REPORTED-LAB`, `NOT-RUN` are *not* `PASS`. `PASS` needs a pinned run artifact.
- **Control maturity** (`01`): proposed intent, committed source, unit/envtest, isolated E2E/CAPD, real-host E2E, production-approved named profile. An accepted ADR is not equivalent to production proof.

## Review dispositions

Incorporates Claude CR-1…CR-13. CR-1 is B-17; CR-2 corrects T-13→F-06; CR-3 adds B-18/F-26/T-38/T-39; CR-4 clarifies B-06 and adds T-42; CR-5 adds B-19/F-27/T-40/T-41; CR-6 clarifies Secret access to named GET (list/watch denied). CR-7…13: taxonomy mapping, global evidence freshness, certificate-authority ambiguity, recovery-authority availability test, conditional F-19 P0, traceability mapping, alternative B-11 mechanism tested under T-37.

**Important nuance:** Kubernetes RBAC `resourceNames` *can* constrain `list`/`watch` only when clients provide a matching `metadata.name` field selector; this baseline chooses to deny Secret list/watch to host agents entirely.

No GitHub repository, infrastructure, issue tracker, ADR or website was modified. All source-review conclusions remain separate from completed E2E evidence.
