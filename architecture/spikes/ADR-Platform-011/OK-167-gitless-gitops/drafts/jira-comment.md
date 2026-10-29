<!-- POSTED to OK-167 on 2026-10-29. Do not post again. -->

**Spike complete — proposed recommendation: CONDITIONAL GO (datacenter envelope).**

Everything is in the repo on branch `spike/OK-167-gitless-gitops`, under
`architecture/spikes/ADR-Platform-011/OK-167-gitless-gitops/`. Full report: `REPORT.md`.

**Acceptance criteria**

| AC | Result |
|---|---|
| AC1 — zot instance | PASS — TLS, htpasswd machine identities, enforced repository-scoped authorization (V1–V8) |
| AC2 — package manifests with oras as `tar+gzip` | PASS — single-layer artifacts, reproducible layer **and** manifest digests |
| AC3 — Application with zot as `repoURL` | PASS — `Synced`/`Healthy`, revision equals the pushed digest |
| AC4 — changes detected and reconciled live | PASS — new digest under an unchanged tag detected in 83/119/182 s with no intervention |
| AC5 — Confluence documentation | PENDING — `REPORT.md` is ready to publish |

**Core questions, one sentence each**

- **Q1 Authentication:** a Secret with `argocd.argoproj.io/secret-type: repository` and
  `type: oci` works, and a `repo-creds` credential template matching a URL **prefix** also works
  for OCI — so production needs one credential per prefix, not one per repository; TLS trust for
  our private CA comes from `argocd-tls-certs-cm` keyed by hostname without port, which we
  confirmed by removing it and watching the pull fail with x509.
- **Q2 Artifact structure:** exactly one content layer whose media type is on an allowlist —
  that is the entire constraint; the artifact type is free, extra referrers are ignored,
  Kustomize renders from a subdirectory, and the allowlist is configurable at runtime.
- **Q3 Caching and webhooks:** OCI runs on the same reconciliation loop as Git, so latency is
  83–182 s at the defaults against ~0 s for an on-demand refresh, and zot's CloudEvents cannot
  drive Argo CD — v3.5.6 answers `400 Unknown webhook event` and supports GHCR only.
- **Q4 Signing:** cosign signs into zot offline and verification correctly breaks when a tag is
  moved to other content, but **Argo CD performs no signature verification on OCI sources** — we
  pointed a tag at unsigned content and it synced with zero conditions.

**Proposed recommendation: CONDITIONAL GO**, conditional on

1. a CI promotion gate that verifies the signature and promotes by digest (closes the only
   security-relevant gap, needs no new cluster components),
2. digest-pinned Applications in operation rather than mutable tags, and
3. a decision on push-based refresh: accept ~3 minutes of polling latency, or build and own a
   CloudEvent bridge.

All four Must criteria (M1–M4) are met. K1 (push refresh without a self-built bridge) and K2
(signature verification that prevents a sync) are not — which is what makes this conditional
rather than an unconditional go.

**Three findings worth your attention beyond the spike**

1. **`registry-default` is fine** — the zot chart documents an `authHeader` for probes when
   htpasswd is on without anonymous access, and `values-ok-shared.yaml` sets none. We deployed
   the same configuration and measured: zot v2.1.20 exempts `/livez`, `/readyz`, `/startupz`
   from access control (200 anonymously, `/v2/` 401). No latent probe problem.
2. **Legacy cosign signatures are silently lost in transfer.** They are tags, not referrers, so
   `oras cp -r` drops them and the copy then fails verification with nothing reporting a problem
   at copy time. This bears on ADR-028 §4.6. Awkwardly, zot only *verifies* that legacy format,
   while only the bundle format survives transfer.
3. **`platform/gitops/README.md` recommends Flux while ADR-011 proposes Argo CD.** We tested
   Argo CD because the ADR names it, but a published README contradicting an ADR while the
   profile is being decided is worth fixing.

**Next steps:** three-way review of the recommendation (Gawenda / Arash), publish `REPORT.md`
to Confluence to close AC5, and decide which of the proposed follow-ups in §13 become tickets.
