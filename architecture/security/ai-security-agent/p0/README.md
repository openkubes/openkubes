# P0 — synthetic B-01 offline assessor prototype

**Research-only executable proof of concept**. **NOT** a hardened sandbox, a general Kubernetes RBAC analyzer, an authorized security agent or a platform-control test result.

- No LLM, HTTP client, Kubernetes credentials, API server or remediation operation is used by the code.
- Accepts **strict JSON on stdin only** (maximum 8192 bytes); exact two-resource Role/RoleBinding synthetic fixture; no caller-controlled URI, path, arbitrary principal or user-defined code.
- A single fixed, pinned reviewed source revision and B-01 mapping are embedded; the source pin is for research fixture consistency, **not** a runtime verification of Git source, independent signature or control health.
- Emits constant, advisory-only `INSUFFICIENT_EVIDENCE`, `NOT_RUN`, `UNKNOWN`, `NOT_APPROVED`, `UNASSESSED`. A Role/RoleBinding declaration is **not** effective-permission proof.
- Rejects non-matching inputs without echoing caller content. It does not parse general YAML, arbitrary namespaces, ClusterRoleBindings or aggregated permissions; those are **future design subjects** and must not be assumed supported.
- Python interpreter and imports may still have ambient filesystem/network capability in a normal shell. **Run it only inside an appropriately restricted externally verified environment** when evaluating the promised P0 isolation boundary; this simple program does not establish sandbox security.

## Development-only tests

From this folder, with Python 3 available:

```sh
python3 -m unittest -v test_offline_assessor
```

The test script invokes the proof of concept as a child process with crafted synthetic stdin. It exercises one positive deterministic output case and a bounded list of negative malformed, unknown-field, wrong-binding, attempted-injection, sensitive-field and oversized cases. Tests deliberately set a fake environment secret and assert the evaluator does not echo it, but **do not prove** the evaluator could never read ambient environment variables or make network requests. That requires an isolated runtime test with enforcement observation.

**Evidence terminology:** Passing these unit/fixture cases means P0 program tests passed, not B-01 is enforced by Kubernetes. Discovery T-01…T-04 remain `NOT_RUN` for this research work.

See [Spec v0.3](../CAPABILITY-SPEC-v0.3.md), [Contract v0alpha3](../ASSESSMENT-CONTRACT-v0alpha3.md), and [Independent Review Consolidation](../INDEPENDENT-REVIEW-CONSOLIDATION-v0.3.md).
