# OK-202: Documentation MCP image risk assessment (draft)

Date: 2026-10-14  
Scope: read-only, public-document `docs_search` MCP adapter on `ok-kagent`, **not** the kagent LLM or the `ok-infra` Ollama service.  
Status: **Open — no release approval, no registry push, no Kubernetes deployment.**

## Reproducible evidence (developer-run)

- Python Slim: 57,014,881 bytes; 87 Debian 13.7 packages; Trivy v0.69.3 HIGH/CRITICAL: **44 HIGH / 0 CRITICAL** (package findings).
- Distroless candidate: 36,351,990 bytes; 38 Debian 13.7 packages; Trivy v0.69.3 HIGH/CRITICAL: **31 HIGH / 0 CRITICAL**, 15 distinct CVE IDs; no findings at those severities for Python third-party dependencies. This is not an all-severity clean bill of health.
- Refreshed distroless: pull `gcr.io/distroless/python3-debian13:nonroot` resolved to `sha256:83aa8d4f74a4d7f7cf2d472054139bef71a927b76c680c0f2e1021d6b1d6d732`; build-stage `python:3.13-slim-trixie` resolved to `sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f`. Rescanning refreshed local image still yielded **31 HIGH / 0 CRITICAL**.
- Refreshed image executes Python **3.13.5**, and real Streamable HTTP MCP client passed initialize, tools/list (exactly `docs_search`), tools/call (`ok-local` beginner guide first, 3 results). Hardened local Docker flags: unprivileged UID, read-only root, capabilities dropped, no-new-privileges, /tmp tmpfs, local-only mapped port, reviewed index read-only mount.
- Developer's CycloneDX SBOM and vulnerability JSON are local untracked files; no artifacts attached to PR. The SBOM generation command did not include vulnerability findings.

## Initial CVE triage — evidence vs. unverified exploitability

| Family | Distinct HIGH CVEs | Potential attack surface in this workload | Required next check |
| --- | --- | --- | --- |
| Debian Python 3.13 | CVE-2026-15308, CVE-2026-19445, CVE-2026-19553, CVE-2026-7210, CVE-2026-82049 | HTML/XML parsers, SSL context and tar processing could matter if invoked through the MCP SDK, dependencies, or runtime; **reachability unverified**. SSL validation should receive priority. | Check upstream/Debian advisories and effective call paths; exercise untrusted inputs; review Python interpreter/package versions. |
| `libexpat1` | CVE-2026-66046, CVE-2026-76956, CVE-2026-76957, CVE-2026-77214, CVE-2026-93990 | XML parsing may be reachable transitively despite a JSON-facing API; **not established**. | Trace XML parser use in Python runtime and dependencies; verify vendor fixes. |
| `libuuid1` / util-linux | CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | Descriptions largely concern privileged mount / namespace commands; constrained read-only runtime likely reduces practical access but is **not a formal non-reachability proof**. | Check whether vulnerable commands/code are present and callable; review OS vendor status. |
| `ncurses` | CVE-2025-69720 | Interactive terminal processing not expected in the HTTP MCP endpoint; actual library and code path access **not tested**. | Verify dependency loading, package need and exposure. |

Vendor-fixed versions were empty in the local Trivy output. **No fixed version listed does not mean no fix exists.** The 31 count represents package/vulnerability pairs (some repeated CVEs), not 31 distinct exploits. Scanner reported 15 distinct HIGH CVE IDs.

## Controls already demonstrated vs. not validated in Kubernetes

**Demonstrated locally:** UID 10001:10001, read-only root filesystem, capability drop, no-new-privileges, local-only published port, read-only public-document index, MCP tool surface restricted to docs_search, successful actual MCP calls.

**Not yet demonstrated in cluster:** restrictive PodSecurity admission, NetworkPolicy enforcement and kagent-to-MCP reachability, no unnecessary Kubernetes API permissions or tokens, strict egress and private Ollama boundary, rate/time/resource limits and adversarial MCP-input tests. Local flags do not prove cluster policy enforcement.

## Release decision and exit criteria

**Decision: HOLD** for GHCR release and `ok-kagent` deployment pending security-owner review. Distroless is the **preferred comparison candidate**, not an approved production base.

1. Recheck vendor security advisories and remediations with current image digests/updated scanner database; classify each distinct CVE's applicability and available fix. Retain evidence for any proposed risk exception; do not blanket suppress scanner IDs.
2. Pin both build-stage and runtime digests, verify native dependencies with the Python 3.13 runtime, and hash-lock package wheels. Refresh SBOM and provenance; run all severity bands and HIGH/CRITICAL release gates.
3. Add reproducible container MCP runtime test (using the freshly built image, not just the checked-in Python unit suite). Validate boundary assumptions against malicious/untrusted query text, and resource/time limits.
4. Review and test Kubernetes NetworkPolicy and PodSecurity in a tightly controlled nonproduction cluster; **no anonymous external MCP listener**. Verify immutable GHCR image digest and pull rights before attempting deployment.
5. Record explicit approver, date, severity, impacted functionality, compensating controls and expiration/revisit conditions for each accepted exception. Until then status remains HOLD.

Files `ok202-distroless-sbom.json` and `ok202-distroless-vulnerabilities.json` are developer-local evidence. Keep local reports and tar archives out of Git; ignore patterns should be considered before further work.
