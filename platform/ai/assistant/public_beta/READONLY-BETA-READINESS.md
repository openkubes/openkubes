# OK AI Documentation Assistant — read-only public beta readiness

**Status: HOLD — planning checklist, not a deployment approval (2026-10-18).**

## Beta v0.1 scope

Allow natural-language **questions about the reviewed, pinned, public OpenKubes documentation**, with citations derived from the verified index. Fail closed when the question cannot be supported, a citation is forged, or output violates the structured-answer contract.

**Not in scope:** shell/installation commands in assistant output, arbitrary markdown/URLs supplied by the model, document write operations, Kubernetes access/mutations, cluster diagnostics, tool execution, autonomous agents, file uploads, and general-purpose chat. An install question should safely decline to provide command text and instead refer to the reviewed public guide using a gateway-controlled link or a fixed informational response; that fallback **does not yet exist** and is a separate implementation/review gate.

A reference to public documentation does not by itself confer permission to execute or recommend every command there.

## Current evidence, strictly interpreted

| Gate | Evidence | Status |
| --- | --- | --- |
| Offline structural validation | Operator reported 173/173 tests PASS on stacked private lab + command-review branch; this includes more than the minimum read-only assistant scope | **PASS for the tested snapshot only** |
| Private end-to-end A2A transport | One live private question, `What is OpenKubes Local?`, produced `PASS` with eight source chunks and 11.305 seconds | **PASS for format/source IDs only** |
| Installation prompt safety | `How do I install OpenKubes Local on macOS?` returned `REJECT / unsupported_text / command`; validator did not leak rejected text | **PASS for rejection of that attempt; fallback unimplemented** |
| Actual response factuality and claim-to-source support | No human-reviewed gold answer / attribution evidence recorded for the real A2A response | **UNVERIFIED** |
| Same-request context use by model | No proof that the model consumed and faithfully used exactly the retrieved context | **UNVERIFIED** |
| Runtime no-mutation boundary | Context Agent configured with `tools: []` but kagent v0.9.12 runtime implicitly includes `ask_user`; actual full tool/identity/egress evidence and security sign-off outstanding | **HOLD** |
| Public API & perimeter | No reviewed authentication, rate limits, public gateway request limits, abuse handling, logging/redaction policy, and ingress enforcement | **NOT IMPLEMENTED / HOLD** |
| Public website and release | No public website switch or production readiness decision | **NOT IMPLEMENTED / HOLD** |

Do not turn a tool-reported `PASS` into a claim of verified semantics or security.

## Required gates before any external/public exposure

### G1. Functional and semantic evaluation (private only)

- Create a **versioned, non-sensitive evaluation set** for the exact pinned docs index: straightforward definitions, comparisons supported by source, ambiguous questions, unsupported topics, install-command requests, jailbreak/prompt-injection attempts inside the question, and follow-ups that require missing context.
- Each case specifies allowed source documents and human-checkable **required/forbidden factual claims**, not model-generated command text.
- Run an offline structured-answer/unit suite first, then a bounded *private* live A2A sample only with operator approval.
- Human reviewers inspect actual answers against pinned source passages in a controlled private review location; avoid raw prompts/answers/snippets in public CI or issue comments.
- **Gate:** all mandatory safety/negative cases rejected or handled by a reviewed safe fallback; factual claims in approved answers individually supported by their citations. Record case-by-case verdicts and reviewers. No numeric quality pass threshold is approved yet.

### G2. Trust, source and tool boundaries

- Verify the trusted gateway performs retrieval; **not** a model-selected repo/path/index or an agent-side undocumented tool call.
- Validate source IDs, repo/path allowlist, revision, original chunk hash and rendered citation URLs against *the same* pinned index/request.
- Verify the deployed Agent's effective tools, generated pod labels, service-account permissions and runtime identity. `tools: []` is **not** zero effective runtime tools: investigate implicit `ask_user` and reject paused/interactively requested tasks.
- Verify *actual* network traffic policies and ingress/egress destinations, including DNS, controller callback and the Ollama endpoint; never infer isolation from an unapplied or nonmatching NetworkPolicy.
- Reject command-like model answers; do not loosen `structured_answer.validate_and_render`.

### G3. Product fallback and user experience

- Implement a **gateway-owned**, fixed/same-revision guide reference for unsupported installation-command questions; do not rely on model-authored URLs or render unreviewed source commands.
- Document empty retrieval, stale/missing index, A2A transport failure, rejected answer and timeout behavior. Return bounded, non-sensitive user messages; never return raw model text on rejection.
- Check source-link correctness and accessibility on the website with a pre-release preview and manual mobile/desktop review.
- Document explicitly that beta supports **documentation Q&A only**, not installing, diagnosing or operating clusters.

### G4. Public gateway and operations security

- Review authentication/abuse controls, per-client rate limits, maximum request body/question size, timeouts, concurrency bounds, egress protections, audit event schema and retention/redaction.
- Prove logging/metrics cannot expose secrets, private retrieval chunks, unredacted model output or other sensitive payloads.
- Establish observability for accept/reject ratios, latency, model outages and safe fallback behavior without logging question/answer contents by default.
- Define emergency disable/rollback, responsible operator and documented on-call response.
- Do not expose the raw controller/Agent A2A port or private lab endpoint to the internet.

### G5. Release decision and reproducibility

- Re-run the complete relevant suite against the **exact commit SHAs** intended for release, preserving the fixed index revision and config.
- Complete human security and privacy review of public perimeter and deployed runtime; resolve all blocking findings.
- Validate private end-to-end test evidence after final changes, including one supported and one unsupported/negative question.
- Obtain explicit operator/product approval. First deploy a reviewed preview, inspect it, then separately approve production release.
- Keep public access disabled until **G1–G5** are met. A merged PR is not a release authorization.

## Work sequencing

1. **First:** implement and test a deterministic no-command fallback and a small reviewed factual/negative golden set on the read-only assistant branch, without stacking the shell-manifest/security-review PRs.
2. **Next:** operator-approved private test and claim-level human review; keep results private and record sanitized status in PR.
3. **Then:** public perimeter hardening + runtime/tool/network security review.
4. **Finally:** release-readiness evidence review, preview, and separate production go/no-go.

### Dependency and status

- Draft #392: isolated context-only lab Agent, based on `main`.
- Draft #394: private gateway-to-A2A probe, based on #392.
- Draft #401 / #403 / #404 / #405: **optional later command-feature spikes**, not required to merge for read-only v0.1.
- `openkubes/ok-local` draft #6: separate documentation hardening; not a blocker for a beta that does **not** display commands.

**Public Beta HOLD. No permission to deploy, merge or expose endpoints is implied by this document.**
