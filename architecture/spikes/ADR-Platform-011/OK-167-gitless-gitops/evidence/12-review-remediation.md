# 12 — PR #462 review remediation and independent retest

- Date (UTC): 2026-10-30
- Original reviewed head: `a41d913b3febb591b0b9ca264fa692eb61edca36`
- Runtime implementation baseline: `689f1b073aad8f3c1b640d3604e3c82d78c35577`
- Environment: macOS arm64; Docker 10 CPUs / 12,528,381,952 bytes; kind v0.33.0;
  Kubernetes v1.36.4; Argo CD v3.5.6/chart 10.11.6; zot v2.1.20/chart 0.1.122;
  oras 1.3.6; cosign 3.1.4; GNU tar 1.35; bash 3.2.57.
- Final packaging/regression update: `537bdb6c17bfadb9cfc84c21dee793bc8dc70e29`
- Cluster: `kind-ok167`; other existing clusters were not modified. The read-only isolation
  violation below is recorded separately.

## Steps

The guarded commands are committed in the Makefile and `scripts/experiments.sh`.
The README and report list the ordered reproduction. Tests run only in the isolated kind
cluster or disposable Git fixtures under ignored `.local/`. Secret-bearing output is never
copied into this evidence directory.

## Review finding closure

| Finding | Correction | Verification |
|---|---|---|
| 1 — guard URL escape | Full authority/port check; no proxy/plugin/external key references | Offline adversarial cases |
| 2 — insecure API | `server.insecure: false` | Verified HTTPS success plus untrusted-certificate failure |
| 3 — false provenance guarantee | Package the committed tree; complete directory comparison | Ignored/index-hidden rejection and fetched layer comparison |
| 4 — staged secrets missed | Scan index blobs separately, even if worktree file is removed | Staged-only regression cases |
| 5 — `$`/bracket exemptions | Explicit documented reference handling | Literal credential regressions |
| 6 — password arguments/output | Password through stdin; admin-printing target removed | Argument-recording regression and live authenticated pull |
| 7 — mode nondeterminism | Normalize committed archive modes | Same digest after a read-only working-file change |
| 8 — unsupported timings | Retain absolute timestamps, sampling data and push phase timings | Fresh raw records; old unsupported numbers withdrawn |
| 9 — wrong GC chronology | Correct T6/Q4.c ordering; narrow causal claim | Historical push/measurement timestamps; pinned source |
| 10 — missing guarded targets | Commit mutation/restoration, signing, transfer and retest targets | Fresh experiment outputs; unexecuted cases remain NOT RUN |
| 11 — CI tar binary mismatch | `GTAR=tar` in inactive workflow | actionlint and GNU tar check; production CI not executed |

## Observed

The regression record is [review-regressions-20261030.jsonl](raw/review-regressions-20261030.jsonl):
**39 passed, 0 failed**. Each row names its case and records the actual exit status. This is
regression coverage for the repair, not a claim that the acceptance criteria all pass.

| Retest | Observed result | Retained output |
|---|---|---|
| Guard/scanner/packager/CLI regressions | 39/39; includes staged-only secrets, binary key path, ignored and index-hidden source, read-only permissions, secret argv and TIMEOUT behavior | [Regression JSONL](raw/review-regressions-20261030.jsonl) |
| Registry V1–V8 | TLS/auth/authz/referrers pass; final V7 sees search/trust but no new smoke event, recorded as allowed caveat | [Registry output](raw/retest-zot-20261030.txt) |
| API TLS / zot webhook replay | Trusted HTTPS 200, untrusted curl exit 60; webhook 400 | [TLS](raw/retest-api-tls-final-20261030.json), [webhook](raw/retest-webhook-20261030.json) |
| Q1.b prefix credentials | Kustomize Synced/Healthy, 2 resources, no exact Kustomize repository Secret | [Snapshot](raw/retest-q1b-20261030T115523Z.json) |
| Q1.c/Q1.d | Actual 401 and x509 errors, followed by populated recovery states | [Credentials](raw/retest-q1c-20261030T115730Z.json), [CA](raw/retest-q1d-20261030T115822Z.json) |
| Structure negatives | Rejected 2 and 0 allowed content layers | [Errors](raw/retest-structure-20261030T115924Z.json) |
| T1 unattended detection | 141 / 144 / 184s; third run exceeds the configured window | [All timing rows](raw/measurements.json), labels `retest-T1-*` |
| T2 requested refresh | 0 / 0 / 1s at whole-second resolution; supplemental only | [All timing rows](raw/measurements.json), labels `retest-T2-*` |
| T3/T4 | Retained exact tag and digest stayed Healthy and populated over 560s | [Before/after](raw/retest-latency-20261030T120040Z.json) |
| T7 self-heal | 1.079s after scale returned; 2 replicas restored | [Timing and snapshot](raw/retest-self-heal-20261030T115531Z.json) |
| T8 outage | Cache-cold ComparisonError; 168.400s recovery after registry readiness without refresh; same running pod, 0 restarts | [Error, timing and pods](raw/retest-recovery-20261030T121327Z.json) |
| Q4/K2 | Local bundle verifies; unsigned digest has no referrers or legacy signature tag and fails verification, yet Argo CD syncs 2 resources | [Signing and unsigned sync](raw/retest-signing-20261030T121247Z.json) |
| K4 transfer | Same digest, signature referrer and successful verification in imported repository; 2 resources synced | [Transfer and verification](raw/retest-offline-20261030T121301Z.json) |
| Determinism | 3 identical layers; changed worktree owner-write permission also covered by regressions | [Three runs](raw/retest-determinism-20261030.txt) |
| M3 independent reconstruction | Fetched plain, signed and Kustomize layers byte-identical to normalized Git-tree archives | [Plain](raw/retest-provenance-final-20261030.json), [signed](raw/retest-provenance-signed-20261030.json), [Kustomize](raw/retest-provenance-kustomize-20261030.json) |
| Final runtime checks | Node, pins, TLS, CA, read-only identity, AppProject, 3 populated Applications and provenance pass | [Checks](raw/retest-verify-20261030.txt) |
| CI action pins | Both upstream tag SHAs match the inactive example; actionlint passes | [Refs](raw/retest-action-pins-20261030.json) |
| History audit | All spike blobs and messages through the recorded head; 8 local credential/password literals and private-key bodies checked | [Bounded audit](raw/retest-history-audit-20261030.json) |
| Teardown | Only ok167 deleted; wjax-demo remains; test ports closed | [Teardown](raw/retest-teardown-20261030.txt) |

Three `perf-review-*` push records retain package/validation 168/130/133ms,
authentication 31/30/30ms, push 41/34/35ms and total 240/194/198ms. All three layers are
1,036 bytes. Other push records preserve the exact variants/digests used by the experiments.

The original 17 pushed artifacts were reconstructed during review and matched their annotated
commits. That supports those samples; the source-validation bypasses were still real.

## Verdict

**Proposed NO-GO.** B9 requires T1 detection within 180s plus measured tolerance. Run 3's last
nonmatching request began at t0+183.299s and first matching request at t0+184.374s; maximum
poll work was 157ms, with a 1s sleep and whole-second t0. This is not explained by sampling.
The raw result is retained; no favorable subset or new tolerance replaces it.

AC1–AC3 pass, AC4 is NOT MET under the fixed timing requirement, AC5 is the revised published
report. M1 and M4 are NOT MET, M2/M3 are supported within their stated checks, K1/K2 remain
NOT MET and K3/K4 pass locally. B13 therefore requires NO-GO. Successful functional delivery
is not evidence that the timing requirement passed. Review and adoption decisions remain
with the three-way review; no approval or merge was performed.

## Isolation-process violation during the retest

At 12:17 UTC, one ad-hoc read used `make guard && kubectl ...` without an exported caller
KUBECONFIG. Make's export applied to its own guard, not the subsequent caller process.
The read fell back to the caller's default Kubernetes configuration and failed with
`You must be logged in to the server`. No mutation or secret output occurred, and the fallback
configuration was not inspected further. This violates the brief's isolation process and is
not presented as a successful safety check.

The diagnostic was replaced by `make zot-status`, which runs both guard and read with Make's
explicit `.local/kubeconfig`. Guard comments now warn about this environment boundary.
All cluster mutations used the guarded Make environment. The existing wjax-demo cluster was
not modified. Git history alone cannot certify all filesystem reads in either agent session.

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Named adversarial inputs are rejected or handled correctly | Exhaustive correctness for all possible inputs |
| Retained local runtime outcomes for the revised configuration | Production readiness or scale |
| Artifact bytes are compared with a Git-tree reconstruction | Signature/provenance enforcement at pull time |
| Concrete mutation/restoration entry points now exist | That every optional experiment has been executed |

No retrospective claim is made about all commands in the original agent session. The revised
execution and evidence are separate from the historical `00`–`11` records. The German user
brief remains unchanged; all remediation artifacts are English.
