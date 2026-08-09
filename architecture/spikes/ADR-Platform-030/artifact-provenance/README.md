# Artifact provenance follow-up

**Ticket:** OK-141

**Baseline:** `main` at `437d723610595fb5dcff68af0c1aa888402cf03a`

**Evaluation date:** 2026-08-09

```text
Evaluation:         read-only
M0a / M0b:          NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure injection:  NO-GO
```

## Question

Can the immutable-artifact blockers discovered by M0a and M0b be handled by
one deterministic supply-chain invariant without introducing an OpenKubes
reconciler?

## Result

Yes at the policy/evidence level; no artifact is execution-authorized yet.

```text
Common invariant                    Defined and fail-closed
Artifact Lock                       Experimental evidence format only
OpenKubes control loop              Not required

E' content integrity                Proven
E' OCI graph closure                Proven
E' signature authenticity           Available upstream; not verified locally
E' CAAPH digest enforcement         Unsupported
E' authorization readiness          BLOCKED

P'' Git root identity               Proven
P'' current transitive closure      Missing from Git
P'' three-package vendor candidate  Reproduces exact prior render
P'' package origin authenticity     Not verified
P'' authorization readiness         BLOCKED
```

## Common invariant

Every artifact used to compute or converge a semantic revision must satisfy:

```text
immutable root identity
AND complete transitive content graph
AND content integrity for every external root
AND reviewed origin/authenticity evidence
AND consumer addresses or is constrained to that exact root
AND raw resolution evidence is retained
```

The transport may differ:

- OCI closes the graph through a manifest digest and content-layer digest.
- Git closes the graph only when every required byte is reachable from the
  pinned commit. A version in `Chart.yaml` is not enough.

The Artifact Lock records proof; it does not reconcile packages, admit
requests, sign artifacts, or grant execution authority.

## Enablement `E'`

The official Cilium 1.19.6 OCI chart resolves to:

```text
coordinate       quay.io/cilium/charts/cilium:1.19.6
manifest         sha256:b8d600c542c97dc8652429e12487ecce922d73de9785505457a8f653833e75f9
config           sha256:37382acb87fb9ca83cd57cb8d6939d2954b16142b4dd94d1b19456efc32cc635
chart layer      sha256:21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179
fixture artifact sha256:21c43cf53841f9ab0375047d95aa4c64051ea52bbd2c679416e6408f5f1c9179
```

The content graph is closed and the layer equals the fixture artifact. Cilium
documents cosign signatures and digest-based installation. This run did not
have cosign installed and therefore did not create local signature evidence.

CAAPH v0.6.4 accepts repository, chart, and version but no expected digest.
Consequently a later authorization must either:

1. use a reviewed mechanism that addresses the digest natively; or
2. prove registry immutability plus pre/post resolution to the same digest and
   explicitly accept that the controller itself does not enforce it.

An annotation asserting a digest is not enforcement.

## Platform `P''`

The pinned `ok-observability` commit does not contain `Chart.lock` or vendored
dependencies. The local workstation has three complete wrapper packages:

```text
ok-observability-prometheus-0.1.0.tgz sha256:241acee7...fe94f0
ok-observability-grafana-0.1.0.tgz    sha256:1d80132e...77e5d8
ok-observability-opensearch-0.1.0.tgz sha256:c9c8eaf2...b609d7
```

Each wrapper contains its transitive upstream chart content. An isolated proof
starts from only the pinned Git archive, adds exactly these three packages to
the root chart's `charts/` directory, and renders with the bound values:

```text
M0b observed raw render   sha256:2adb637ca1b4bfd528abc660c102019057cdad5389b989ea1a2d7a5e9c5b7ecf
vendor-candidate render   sha256:2adb637ca1b4bfd528abc660c102019057cdad5389b989ea1a2d7a5e9c5b7ecf
```

This proves feasibility, not current provenance. Closing the graph requires a
new `ok-observability` commit containing the reviewed packages (and preferably
the dependency lock) or an equivalent immutable OCI root. Because the source
commit is part of `P''`, that change necessarily creates new `P`, `R`, and
execution-fixture identities. Existing digests must not be reinterpreted.

The current package bytes are locally generated/obtained; their upstream
signature/provenance has not been verified. Vendoring proves future content
identity after commit, not historical publisher authenticity by itself.

## Decision boundary

```text
deterministic lock/verifier      acceptable existing-function approach
Git vendoring or OCI digest      existing source mechanism
signature verification          supply-chain evidence operation
new OpenKubes reconciler         not justified
new admission component         not justified by this evidence
```

Before any M0 authorization, the selected resolution path must close integrity,
authenticity, graph closure, and consumer binding. Until then both gates remain
blocked.

References:

- [Cilium OCI signing and digest pinning](https://docs.cilium.io/en/stable/installation/k8s-install-helm/)
- [Argo CD OCI sources accept a tag or digest](https://argo-cd.readthedocs.io/en/release-3.2/user-guide/oci/)
- [Helm dependency behavior](https://docs.helm.sh/docs/helm/helm_dependency/)
