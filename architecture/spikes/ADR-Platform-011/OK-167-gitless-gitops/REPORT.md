Source of truth is the repo: `architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/` at commit `5079d57`.

Proposed Confluence title: **OK-167 — Gitless GitOps with Argo CD and zot — Spike Report**
(Space `OpenKubes`).

---

# OK-167 — Gitless GitOps with Argo CD and zot

## 1. Summary

Argo CD v3.5.6 can take an OCI artifact in a zot registry as an `Application` source, and it
works well enough to recommend — with two named conditions. All four acceptance criteria that
could be tested locally passed: zot runs with TLS and enforced repository-scoped authorization,
a Bash pipeline packages manifests into a single-layer `tar+gzip` artifact with reproducible
digests, an `Application` with an `oci://` repoURL syncs it, and a push to an unchanged tag is
detected and reconciled with no human intervention in 83–182 seconds. No insecure flag was used
anywhere. Credentials never touch Git: Argo CD authenticates with a read-only identity whose
password is assembled in memory from an external store, which is exactly the shape ADR-011's
Secret Contract prescribes and which a Vault + VSO deployment would produce. Two gaps keep this
short of an unconditional recommendation: **Argo CD v3.5.6 performs no signature verification on
OCI sources at all** — it synced demonstrably unsigned content without raising a single
condition — and **it cannot consume zot's CloudEvents**, so push-based refresh needs a bridge
OpenKubes would have to build and own. Neither gap blocks adoption; both are closable, and the
first is closable today in CI without new components. The proposed outcome is therefore
**CONDITIONAL GO** for the `datacenter` envelope, conditional on a CI promotion gate that
verifies signatures, and on pinning digests *together with* a retention policy — because a
digest-pinned Application broke during this spike when the artifact it named was
garbage-collected after its tag moved away.

## 2. Context and question

[OK-167](https://kubernauts.atlassian.net/browse/OK-167) asks whether Kubernetes manifests can
be packaged by CI as OCI artifacts, stored in zot, and synchronised from there by Argo CD —
relevant to air-gapped, edge and restricted-network scenarios.

"Gitless GitOps" names the **delivery channel, not the source of truth**. Git remains the source
of truth (ADR-Platform-011 §1); the registry becomes the transport. That framing produces the
spike's central requirement: every artifact must be traceable back to a Git commit.

Three ADRs set the yardstick:

- **ADR-Platform-011** (Proposed) proposes Argo CD as the GitOps profile, and carries an
  **Accepted** Secret Contract: Git never holds plaintext secret material, and the secret tool is
  a per-envelope Implementation Profile (datacenter: Vault + VSO, ADR-025).
- **ADR-Platform-028** (Draft) defines the Artifact Registry Contract: digests are the canonical
  identity (§4.3), machine identities must be separate and least-scope (§4.5), supply-chain
  metadata attaches through the Referrers API and must survive transfer (§4.6), released
  artifacts must be protected against mutation (§4.7).
- **ADR-Platform-001** (Accepted) is the test of whether any of this belongs in a contract:
  OpenKubes owns contracts, not components.

## 3. Setup

![Architecture](diagrams/architecture.svg)

*Rendered from [`diagrams/architecture.mmd`](diagrams/architecture.mmd) with a pinned
mermaid-cli container, so no tooling was installed on the host. Confluence does not render
Mermaid, which is why the SVG is committed alongside the source.*

Everything ran on one laptop, in a kind cluster reachable only over loopback. Verified by
connection attempt, not only by reading the configuration: the API server and the registry
NodePort accept connections on `127.0.0.1` and **refuse** them on the host's LAN address.

| Component | Version | Note |
|---|---|---|
| kind | v0.33.0 | — |
| Kubernetes | v1.36.4 (`kindest/node@sha256:099e0493…`) | deliberately **not** kind's default v1.37.0: Argo CD 3.5 is tested only against v1.33–v1.36 |
| Argo CD | v3.5.6, chart `argo-cd-10.11.6` | all images digest-pinned; install fails if any is not |
| zot | v2.1.20 (`@sha256:542e25be…`), chart `zot-0.1.122` | **identical pins to `registry-default`** |
| oras | 1.3.6 | |
| cosign | 3.1.4 | |
| podinfo | 6.16.0 / 6.17.0, both by digest | |

Every deviation from `platform/registry/zot/values-ok-shared.yaml` is listed with its reason in
[`zot/DEVIATIONS.md`](zot/DEVIATIONS.md) — thirteen of them, the substantive ones being NodePort
instead of ClusterIP, no OIDC, a narrowed repository prefix, three extra extensions
(`search`, `trust`, `events`), and kind's `standard` StorageClass.

## 4. Results per acceptance criterion

| AC | Verdict | Evidence |
|---|---|---|
| **AC1** — provide a zot instance | **PASS** | [`02-zot.md`](evidence/02-zot.md) — V1–V8 all pass |
| **AC2** — package manifests with oras as `tar+gzip` | **PASS** | [`03-pipeline.md`](evidence/03-pipeline.md) |
| **AC3** — Application with zot as `repoURL` | **PASS** | [`05-application.md`](evidence/05-application.md) |
| **AC4** — changes detected and reconciled live | **PASS** | [`06-sync.md`](evidence/06-sync.md) — T1, T3, T4 |
| **AC5** — documentation in Confluence | **PENDING** | this report; AC5 is met when a human publishes it |

The two checks that make AC1 meaningful are the negative ones: the read-only identity **cannot
push** (401), and the publisher is **refused outside its repository prefix** (403). A registry
that accepted everything would have passed every positive check unchanged.

For AC3 and AC4 the pass criterion deliberately includes the **resource count**, because
**Argo CD reports `Synced` even when it found no resources at all** — a wrong `path`, or files in
a subdirectory without `directory.recurse`, produces a green Application that deployed nothing.

## 5. Answers to the core questions

### Q1 — How do we give Argo CD credentials for a private zot?

**A Kubernetes Secret labelled `argocd.argoproj.io/secret-type: repository` with `type: oci`, and
for anything beyond a single repository, a `repo-creds` credential template keyed on a URL
prefix — which was confirmed to work for OCI in v3.5.6.** The Kustomize Application and, later,
the imported repository both synced with no exact Secret of their own. Operationally that is the
difference between one credential per repository and one per prefix, and it is what makes the
Vault + VSO path practical.

TLS trust for a private CA comes from `argocd-tls-certs-cm`, keyed by **hostname without port**.
This was an open question from the research notes and is now settled by removing the entry and
watching the pull fail with `x509: certificate signed by unknown authority`. The ConfigMap
reaches the repo-server only on restart, so a CA rotation needs a rollout.

A wrong password produces an exact, actionable error naming the URL and `401: Unauthorized`, and
recovery needs nothing but fixing the credential. Workload ServiceAccounts cannot read the
registry Secret — and neither can the repo-server's own ServiceAccount, because Argo CD passes
credentials over gRPC rather than letting it read the API.

Evidence: [`07-q1-auth.md`](evidence/07-q1-auth.md).

### Q2 — What constraints does Argo CD put on artifact structure?

**Exactly one content layer, whose media type is on an allowlist.** That is the whole
constraint. Reproduced verbatim:

```text
expected only a single oci content layer, got 2
expected only a single oci content layer, got 0
oci layer media type application/vnd.openkubes.manifests.layer.v1.tar+gzip is not in the list of allowed media types
```

Everything else is flexible: the artifact type is free and does not affect acceptance, extra
referrers (SBOM, signature) are ignored, uncompressed `tar` works, Kustomize renders from a
subdirectory via `path`, and the allowlist itself is configurable at runtime through
`reposerver.oci.layer.media.types`.

The constraint is narrow and the errors are precise, which makes it easy to build a pipeline
against. Evidence: [`08-q2-structure.md`](evidence/08-q2-structure.md).

### Q3 — How does OCI detection compare to Git polling, and can zot push to Argo CD?

**It is the same reconciliation loop, so it inherits the same latency — and no, zot cannot push
to Argo CD.**

| Path | Detection |
|---|---|
| Polling at defaults (120 s + 60 s jitter) | **83 / 119 / 182 s** (min/median/max, n=3) |
| Refresh on demand | **0 s** |
| Cluster drift (self-heal) | **1 s** |

These are three different mechanisms and should never be quoted as one number. The spread in the
polling row is the jitter: latency depends on where in the cycle the push lands, so the honest
statement is "up to about three minutes", not an average. Git polling was **not measured** —
there was no Git source to compare against — so the comparison is structural, not numerical.

zot emits well-formed CloudEvents on push, promptly, carrying repository, tag, digest and the
pushing identity. Argo CD v3.5.6 rejects them:

```text
POST /api/webhook  ->  HTTP 400   Unknown webhook event
```

Its only OCI webhook support is GHCR. Closing the gap means a small bridge that receives the
CloudEvent and annotates matching Applications with `argocd.argoproj.io/refresh=normal`. That is
feasible — the event carries everything needed — but it is custom code OpenKubes would own, and
it needs `patch` on Applications, which is a privilege worth thinking about.

Evidence: [`09-q3-detection.md`](evidence/09-q3-detection.md).

### Q4 — Does the combination make signature verification easy?

**Signing is easy. Enforcement does not exist.**

cosign v3.1.4 signs into zot offline without touching a public transparency log, the signature
lands as a referrer, and verification behaves exactly as content addressing demands: it succeeds
by digest, succeeds by tag while the tag points at the signed digest, and fails with
`no signatures found` once the tag is moved to other content.

Then:

> The `v1.1.0` tag was pointed at **unsigned** content and the Application refreshed.
> Result: `Synced`, `Healthy`, 2 resources, **zero conditions**. `oras discover` confirms the
> synced digest carries no signature at all.

Argo CD v3.5.6's "Source Integrity" covers Git GPG only. **Nothing in the path from registry to
cluster checks a signature.** Signing today produces evidence, not enforcement.

Two further findings:

- **zot verifies only the legacy signature format.** With cosign's default bundle format zot
  reports `IsSigned: true, IsTrusted: false` — it sees a signature it cannot check. With
  `--new-bundle-format=false` it reports `IsTrusted: true` and the author key.
- **The two flags that keep cosign signing offline are both deprecated**
  (`--use-signing-config`, `--tlog-upload`) with no stable replacement yet. An air-gapped
  pipeline on cosign v3 depends on deprecated behaviour today.

Evidence: [`10-q4-signing.md`](evidence/10-q4-signing.md).

## 6. Performance impressions

Laptop, kind, one node. These are impressions, not benchmarks.

| Measure | Value |
|---|---|
| Artifact size (2 manifests, `tar+gzip`) | **1.0 KB** |
| Artifact size (Kustomize base + 2 overlays) | **1.6 KB** |
| Package + validate + push, 3 runs | **168 / 174 / 264 ms** |
| Detection, polling at defaults | **83 / 119 / 182 s** |
| Detection, refresh on demand | **0 s** |
| Sync to `Healthy` after detection | **5–23 s** |
| Rollout complete (pods on the new image) | **+4 s** after Healthy |
| Self-heal (cluster drift) | **1 s** |
| Recovery after a registry outage | **77 s**, unattended |
| Repo-server / controller CPU and memory | **not measured** — metrics-server was not installed |

Artifacts are small enough that transfer time is irrelevant; the entire latency budget is the
reconciliation interval.

One registry-load detail worth knowing: zot's counters show roughly as many `401` responses as
`200`s for `HEAD` (96 vs 100). That is the standard registry auth challenge — clients request
without credentials, receive 401, and retry with them — so **each authenticated poll costs two
requests**. Any capacity estimate should double the naive count.

## 7. Hurdles and gotchas

Worth carrying forward, because each cost time and none is obvious:

| # | Hurdle | Resolution |
|---|---|---|
| 1 | **`oras` sends plain HTTP to a registry called `localhost`** and a TLS-only zot answers `400`. The obvious fix, `--plain-http`, silently abandons TLS. | Use `127.0.0.1` (in the certificate SANs) or `--resolve` with a real hostname. Confirmed TLS is genuinely in play by omitting the CA and observing the x509 error. |
| 2 | **macOS ships bash 3.2**, so `mapfile` and associative arrays do not exist. | All scripts written for bash 3.2 — which also makes them portable to CI. |
| 3 | **macOS `tar` is bsdtar** and cannot sort archive members, so digests would depend on directory order. | GNU `gtar` asserted, not merely preferred; the script refuses to run without it. |
| 4 | **Host port 5000 is taken by the AirPlay Receiver** on macOS. | NodePort 30500 on both sides. |
| 5 | **`applicationSet.enabled` does not exist in chart 10.11.6.** The deployment has no template gate, so that line would have looked correct and done nothing. | `applicationSet.replicas: 0`, with the reason written down. |
| 6 | **A single `*` in an AppProject `sourceRepos` entry does not cross a `/`.** The symptom is "repo is not permitted in project", which looks nothing like a path-depth problem. | `**`. |
| 7 | **Helm `--set-string` treats commas as list separators**, so a comma-separated parameter value fails with `key "tar+gzip" has no value`. | Escape every comma (`\,`). |
| 8 | **Legacy cosign signatures are tags, not referrers**, so `oras cp -r` drops them and the copy then fails verification — with nothing reporting a problem at copy time. | Copy the `sha256-<digest>.sig` tag explicitly, or use the bundle format. |
| 9 | **The zot chart's example htpasswd** carries `admin:admin` and `user:user`. | Inert by default (`mountSecret` is already `false`), but set explicitly anyway; the install fails if the chart renders any Secret. |

## 8. Configuration snippets

**Application (the main example, `argocd/application-tag.yaml`):**

```yaml
spec:
  project: ok167
  source:
    repoURL: oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops/podinfo-manifests
    targetRevision: v1.0.0      # a digest in production — see §10
    path: .
  destination:
    server: https://kubernetes.default.svc
    namespace: ok167-demo
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```

**Credential template, one per prefix (values from the secret store, never from Git):**

```yaml
metadata:
  labels:
    argocd.argoproj.io/secret-type: repo-creds
stringData:
  type: oci
  url: oci://zot.zot.svc.cluster.local:5000/openkubes/machine/gitops
  username: gitops-puller
  password: <from Vault via VSO>
```

**zot access control (the part that matters):**

```json
"accessControl": {
  "repositories": {
    "openkubes/machine/gitops/**": {
      "policies": [
        { "users": ["gitops-publisher"], "actions": ["read","create","update"] },
        { "users": ["gitops-puller"],    "actions": ["read"] }
      ],
      "defaultPolicy": []
    },
    "**": { "defaultPolicy": [] }
  }
}
```

**Push:**

```sh
scripts/package-and-push.sh \
  --source app/podinfo-plain \
  --repository openkubes/machine/gitops/podinfo-manifests \
  --tag v1.0.0
```

A full GitHub Actions variant is in [`ci/github-actions-example.yaml`](ci/github-actions-example.yaml)
— validated with `actionlint`, deliberately outside `.github/workflows/` so it cannot run.

## 9. Security and the Secret Contract

Three machine identities, as ADR-028 §4.5 requires, and the separation is enforced server-side,
not merely declared:

| Identity | Scope | Verified |
|---|---|---|
| `gitops-publisher` | read/create/update on `openkubes/machine/gitops/**`, **no delete** | refused outside the prefix with **403** |
| `gitops-puller` | read only — this is what Argo CD holds | push **denied** |
| `ok167-admin` | adminPolicy; only for the trust-key upload | — |

**No secret value exists in Git.** The repository Secret is assembled in memory from an external
store and piped into `kubectl`; the tracked template carries placeholders only. In production,
Vault + VSO (ADR-025) renders the same Secret from the same reference, which is precisely
ADR-011's Secret Contract §2 — Git holds the reference and the reconciliation configuration, not
the value.

TLS is enforced end to end with no insecure flag anywhere, and proved by removing trust and
observing the failure rather than by asserting success.

One residual observation: had the zot chart's `authHeader` been needed, Kubernetes would have
stored a base64 credential in plaintext in the StatefulSet pod spec, readable by anyone with
`get statefulsets` in the namespace. It was **not** needed — see §10.

## 10. Fit with OpenKubes architecture

**ADR-001 (contracts, not components).** Nothing product-specific needs to enter a contract. What
this spike exercises is the existing Artifact Registry Contract plus Argo CD's OCI source
support. If Argo CD were replaced, the contract-level statement — "manifests are delivered as
OCI artifacts identified by digest, traceable to a commit" — would survive unchanged. That is
the right shape.

**ADR-011 §1 (Git is the source of truth).** Preserved, and now mechanically checked. Every
artifact carries `org.opencontainers.image.source` and `.revision`, and the check went further
than the annotation's presence: `git diff` between the annotated commit and the packaged
directory is **empty**. The pipeline refuses to package uncommitted content precisely so that the
annotation cannot become a lie; `--allow-dirty` exists and records
`io.openkubes.source.dirty=true` rather than omitting the fact.

**ADR-028 §4.3 and §4.7 (digests are identity; tags must not mutate).** The mutable tag in T1 is
a **test case, not a recommendation**. Q4.c shows exactly what a mutable tag costs: the signature
verified on Monday says nothing about what the tag points at on Tuesday. For operations the
choice is digest-pinned Applications (T4 held still through two full polling cycles while four
tags moved) or genuinely immutable tags. The spike recommends digest pinning, because it also
puts every change in Git with an author and a review.

**ADR-028 §4.5 (separate identities).** Honoured and enforced — see §9.

**ADR-028 §4.6 (referrers must survive transfer).** Mostly honoured, with a real gap. Bundle-format
signatures are referrers and survive an offline round trip intact. **Legacy-format signatures are
tags, not referrers, so the contract clause does not protect them** — `oras cp -r` drops them
silently and the copy then fails verification. And the formats pull in opposite directions: the
one that transfers is the one zot cannot verify. Any air-gap procedure must pick a format
explicitly and say which.

**ADR-017 (constraint envelopes).** This work is scoped to `datacenter`. For `constrained-edge`,
T8 is the governing result: running workloads survive a registry outage untouched, but once the
repo-server's cache is cold and the registry is unreachable, **no reconciliation is possible at
all**. A cluster that cannot reach the registry cannot converge — it can only keep running what
it already has. That is the same reconcilability rule ADR-017 §4 applies to secrets, and it
applies here unchanged.

**Nothing here creates an air-gapped envelope.** ADR-017 defines none, and ADR-028 §4.9 says
explicitly that an offline-transfer proof does not create one. One 28 KB artifact was moved
between two repositories on one host.

**An inconsistency to resolve elsewhere:** `platform/gitops/README.md` recommends **Flux** as the
GitOps engine, while ADR-011 proposes **Argo CD** and records Flux as the rejected alternative.
This spike tested Argo CD because the ADR names it. The contradiction is reported, not resolved —
resolving it is not this spike's job, but it should not stay unresolved while a GitOps profile is
being decided.

**A second, smaller one:** ADR-028 §4.4 describes a logical namespace of
`openkubes/{platform,cluster,…}/`, while the deployed `registry-default` profile uses
`openkubes/{human,machine}/**`. This spike followed the deployed profile.

**A finding in `registry-default`'s favour.** The zot chart documents an `authHeader` value
"needed when htpasswd authentication is enabled, but the anonymous access policy is not" — which
is exactly `values-ok-shared.yaml`'s configuration, and it sets none. Rather than assume, this
spike deployed the same configuration and measured: `/livez`, `/readyz` and `/startupz` return
**200 anonymously** while `/v2/` returns **401**. zot v2.1.20 exempts its health endpoints from
access control. **`registry-default` has no latent probe problem.**

## 11. What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Argo CD v3.5.6 syncs from an OCI artifact in zot over TLS with an authenticated read-only identity, no insecure flags | That it scales — one Application, one repository, one node, one laptop |
| A push to an unchanged tag is detected and reconciled with no intervention in 83–182 s | What the latency is with many Applications sharing a repo-server |
| Identical input yields an identical layer **and** manifest digest | That it does so on another OS or another GNU tar build |
| Every artifact names a commit whose content is byte-identical to the artifact | That anything verifies this at pull time — nothing does |
| Credentials never enter Git, and identity separation is enforced server-side | That Vault + VSO integration works — it was described, not built |
| Signatures work end to end and break correctly when a tag moves | That anything prevents an unsigned sync — **it does not** |
| Artifacts and bundle-format signatures survive an offline round trip | That OpenKubes can operate air-gapped; no workload image was ever pulled from zot |
| Workloads survive a registry outage with zero restarts | That a *new* workload could start — image pull from zot is an explicit non-goal |
| zot's health endpoints need no credentials under `defaultPolicy: []` | That this holds for other zot versions or auth configurations |
| An untagged manifest is garbage-collected even while an Application pins it by digest | What a correctly configured retention policy would do — none was configured, here or in `registry-default` |

**Not run, with reasons** (recorded as gaps, not as passes): S-D (Helm chart mirroring — Helm 4's
`push`/`registry login` flags were not verified against a private-CA TLS registry, and guessing
would have broken the spike's own rule); Q1.e (deliberate insecure-flag demonstration — Q1.d
already proves what the CA is load-bearing for, without ever disabling verification); Q3.a and
Q3.e (alternative reconciliation settings and tag-list cache timing — they sharpen numbers that
do not change the recommendation); Q3.d (bridge prototype — Q3.b and Q3.c already establish both
halves of the case).

## 12. Recommendation

| ID | Criterion | Type | Verdict |
|---|---|---|---|
| **M1** | AC1–AC4 pass, with TLS verification and authenticated pull, no insecure flags | Must | **MET** |
| **M2** | No secret value in Git; Argo CD's credential is compatible with the Secret Contract | Must | **MET** |
| **M3** | Every artifact traceable to a Git commit through annotations | Must | **MET** (verified in substance, not only in form) |
| **M4** | Changes detected without manual intervention inside the reconciliation window | Must | **MET** |
| **K1** | Push-based refresh without a self-built bridge | Can | **NOT MET** — `400 Unknown webhook event` |
| **K2** | Signature verification that prevents a sync | Can | **NOT MET** — unsigned content synced with zero conditions |
| **K3** | Deterministic digests for identical input | Can | **MET** |
| **K4** | Offline transfer including referrers | Can | **MET** |

All four Must criteria are met; K1 and K2 are not. By the decision rule fixed in advance, the
outcome is:

### Proposed: **CONDITIONAL GO**

for OCI artifacts from `registry-default` as an Argo CD source in the ADR-011 GitOps profile,
in the `datacenter` envelope.

**Conditions**, each becoming a proposed follow-up:

1. **A CI promotion gate that verifies the signature and promotes by digest.** This closes K2
   where the key material already lives, needs no new cluster components, and works today. Until
   it exists, a signature in the registry is evidence that something was signed once — not a
   guarantee of what gets deployed.
2. **Digest-pinned Applications in operation, *and* a retention policy that keeps what is
   deployed.** T4 shows digest pins hold, and Q4.c shows what mutable tags cost — but the pin
   alone is not enough. A digest-pinned Application in this spike broke because the artifact was
   garbage-collected after its tag moved away (§10). `registry-default` currently runs with
   `gc: true` and no retention policy at all, which ADR-028 §4.7 asks the profile to define.
3. **A decision on push-based refresh.** Either accept up to ~3 minutes of polling latency, which
   is the same latency a Git source has, or build the CloudEvent bridge and own it. The spike
   measured what it is worth: 83–182 s versus 0 s.

**Explicitly not recommended yet:** anything beyond `datacenter`. For `constrained-edge` the T8
result is the open question — a cluster that cannot reach the registry cannot reconcile at all
once its cache is cold. That needs its own evaluation against the envelope, not an extrapolation
from this one.

The recommendation is a proposal. The decision is Gawenda's and Arash's in the three-way review.

## 13. Proposed follow-ups

Suggestions only — no tickets were created.

| Title | Why | Rough size |
|---|---|---|
| CI promotion gate: verify signature, promote by digest | Closes K2, the only Must-adjacent gap; needs no new cluster components | S–M |
| Decide Flux vs Argo CD and fix `platform/gitops/README.md` | A published README contradicts an ADR while the profile is being decided | S |
| CloudEvent → Argo CD refresh bridge | Closes K1; measured benefit is 83–182 s → 0 s. Needs an RBAC design for `patch` on Applications | M |
| Mirror upstream Helm charts into `registry-default` (the unfinished S-D) | The air-gap story needs a chart path, and Helm 4 behaviour against a private-CA registry is unverified | S |
| Evaluate OCI GitOps against `constrained-edge` | T8 shows reconciliation stops when the registry is unreachable and the cache is cold | M |
| Define the retention policy ADR-028 §4.7 requires for `registry-default` | A digest-pinned Application broke in this spike because the artifact was garbage-collected after its tag moved; `Retention.Policies` is `null` today | S–M |
| Pin the zot chart's `helm test` images, or document the gap upstream | `registry-default` inherits an unpinned `alpine` in the chart's test hooks | XS |
| Containerd trust for zot on workload clusters | Out of scope here; without it, workloads still pull images from public registries | M |

## 14. Reproduction

From `architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/`:

```sh
export KUBECONFIG="$PWD/.local/kubeconfig"

make preflight                      # tools, versions, architecture, ports, pins
make up                             # kind cluster, loopback only
make namespaces pki identities      # PKI and machine identities into .local/
make events-install                 # CloudEvents sink (before zot, on purpose)
make zot-install                    # asserts the image pin and that no chart Secret renders
make zot-verify                     # V1-V8
make argocd-install                 # asserts every image is digest-pinned
make argocd-repo REPO=podinfo-manifests
make argocd-project

make push VARIANT=plain TAG=v1.0.0  # package + push
make app-tag                        # the Application
make app-wait APP=ok167-podinfo-tag
make probe-version NS=ok167-demo    # podinfo reports its own version

make determinism                    # P4-DET
make lint scan-secrets
make down                           # delete the cluster; .local/ is kept
```

`make help` lists every target. Each tool resolves through its own Make variable, so any of them
can be replaced by a pinned container wrapper without touching a target:

```sh
make lint YAMLLINT='docker run --rm -v "$PWD":/w -w /w <pinned-image> yamllint'
```

## 15. References

- Ticket: <https://kubernauts.atlassian.net/browse/OK-167>
- In this repository: `ADR-Platform-001`, `-011`, `-012`, `-017`, `-028`;
  `platform/registry/zot/`; `CONTRIBUTING.md`; `docs/agentic-ai-poc-evidence-protocol.md`
- Argo CD OCI sources: <https://argo-cd.readthedocs.io/en/latest/user-guide/oci/>
  (for v3.5.6, read `docs/` at the `v3.5.6` tag of `argoproj/argo-cd`)
- Argo CD Helm chart: <https://github.com/argoproj/argo-helm>, tag `argo-cd-10.11.6`
- zot: <https://github.com/project-zot/zot>, tag `v2.1.20`
- zot Helm chart: <https://github.com/project-zot/helm-charts>, tag `zot-0.1.122`
- Harbor as a universal OCI hub (comparison): <https://goharbor.io/blog/harbor-as-universal-oci-hub/>
- Evidence index: [`evidence/`](evidence/) — `00-preflight` through `11-offline-transfer`
