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

## P0 hardening regression and OS isolation status

Run the deterministic fixtures (this only tests the evaluator logic):

```sh
cd architecture/security/ai-security-agent/p0
python3 -m unittest discover -v -p 'test_*.py'
```

`test_hardening.py` exercises synthetic credential canaries, nested unexpected fields, type confusion, prompt-like instructions, duplicate keys, nonstandard JSON, authority-shaped outputs, and repeatability. Sensitive data is expected to be **rejected without echo**, not treated as valid input and then passed through a redaction engine.

For a **separate Linux Bubblewrap isolation trial**, install and independently verify `bwrap` and `timeout` (and user namespace support) on a disposable test host, then run:

```sh
LEAK_TEST_SECRET=probe-canary sh sandbox_runner.sh --probe
python3 -m unittest discover -v -p 'test_*.py'
python3 -c 'import json, test_offline_assessor as t; print(json.dumps(t.BASE))' | sh sandbox_runner.sh
```

`sandbox_runner.sh` is **fail closed** when Bubblewrap or timeout is missing, or the kernel cannot establish the requested namespaces. It binds only the system Python runtime read-only plus one fixed program, clears the environment, attempts a new network/mount/PID namespace, and supplies no host home, Kubernetes token, management kubeconfig or secret mounts. The `--probe` mode evaluates representative denials: host paths, `/etc/passwd`, an environment canary, workspace writes and an outbound TCP connection. A successful probe is still only a *bounded representative isolation test*, not proof against kernel/container escapes.

**Recorded execution limitation (2026-11-23):** In the available Linux execution environment, `unshare -n true` returned `Operation not permitted`, and `bwrap` and Docker were unavailable. Running the sandbox script correctly returned exit **78** (refused execution). **No successful Bubblewrap isolation test has occurred.** Execute the trial on a host supporting rootless namespaces or a purpose-built sandbox profile, and record tool versions, host/kernel/container settings, network observations, mounts, and independent reviewer before claiming the P0 isolation gate is closed.

The unit/adversarial suites and the sandbox trial are **separate gates**. Neither indicates a Kubernetes B-01 security control PASS; Discovery T-01…T-04 remain NOT_RUN.
