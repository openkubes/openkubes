# 06 — Networking, ingress and TLS

- Test IDs: N1–N4
- Date (UTC): 2026-10-31T12:32Z – 12:50Z
- Commit: `be92a16` plus the Phase 7 changes in this commit
- Environment:
  - VM `ok-knative-local`, K3s `v1.35.5+k3s1` with ServiceLB, Knative Serving and net-kourier `1.24.0`.
  - Traefik chart `42.1.3` (appVersion `v3.7.16`) for N2.
  - cert-manager `v1.21.3` for N3.
  - Timeboxes: N2 2 h (≈ 15 min used), N3 2 h (≈ 5 min used).

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless exp-N1          # second LoadBalancer on 80/443, observed 20 s, deleted
make -C … exp-N4                                                       # ksvc podinfo-private, label visibility=cluster-local
# N2 (ADR-010 profile v1)
#   chart: curl https://traefik.github.io/charts/traefik/traefik-42.1.3.tgz -> .local/charts/ (sha256 = index.yaml digest, pinned)
#   image: docker.io/traefik:v3.7.16 -> Docker-Content-Digest sha256:1336e85a…7e65 (pinned, values image.digest)
make -C … ingress-render                                               # helm template, sha256 check, refuses kind: Secret (C7)
make -C … ingress-install                                              # namespace ingress, server-side apply (field manager traefik-chart)
make -C … kourier-clusterip                                            # knative/patch-kourier-clusterip.yaml, .local/n2-active
make -C … ingress-route                                                # ingress/kourier-ingress.yaml + test via NodePort 30080
make -C … measure-fortio ID=N2-warm-traefik KSVC=podinfo QPS=10 C=1 N=200 TARGET=http://192.168.252.2:30080
make -C … measure-fortio ID=N2-warm-direct  KSVC=podinfo QPS=10 C=1 N=200
make -C … measure-coldstart ID=N2-cold-traefik KSVC=podinfo N=5 TARGET=http://192.168.252.2:30080
make -C … measure-coldstart ID=N2-cold-direct  KSVC=podinfo N=5
make -C … exp-N2b && make -C … exp-N2b-restore                         # domain-template variant and back
# N3
make -C … tls-install                                                  # cert-manager (pinned manifest), tls/issuers.yaml
make -C … tls-enable                                                   # config-certmanager issuerRef, external-domain-tls Enabled, controller restart, HTTPS checks
# end of phase: back to the Phase 5/6 baseline
make -C … tls-disable exp-N2-restore knative-verify smoke
```

## Observed

### N1 — Kourier as installed ([raw/n1-servicelb-20261031T123234Z.txt](raw/n1-servicelb-20261031T123234Z.txt))

| Item | Observed |
|---|---|
| LoadBalancer Services | only `kourier-system/kourier`, EXTERNAL-IP `192.168.252.2` (the node) |
| NodePorts | `80 → 32500`, `443 → 32213` (targets 8080/8443) |
| ServiceLB | DaemonSet pod `kube-system/svclb-kourier-4dbecc97-785x7` with containers `lb-tcp-80` (**hostPort 80**) and `lb-tcp-443` (**hostPort 443**) |
| Second LoadBalancer `ok211-n1-second-lb` on 80/443 | **EXTERNAL-IP `<pending>`** after 20 s; its pod `svclb-ok211-n1-second-lb-…` is `Pending`, reason `Unschedulable`: "0/1 nodes are available: 1 node(s) didn't have free ports for the requested pod ports" |

On a K3s node, Kourier's release default (`type: LoadBalancer`) takes the node's 80/443, and any other LoadBalancer on those ports stays Pending. ADR-010 does not object to the ports as such. It objects to having two entry points: Kourier would become a second one beside `ok-ingress`, with its own hostnames and its own TLS.

### N2 — single entry point through Traefik (ADR-010 profile v1)

**Traefik as installed:**

- Rendered objects: 6, namely ServiceAccount, ClusterRole, ClusterRoleBinding, Deployment, Service, IngressClass. **No Secret** (C7).
- Image `docker.io/traefik@sha256:1336e85a…7e65`.
- Only the Kubernetes Ingress provider (`--providers.kubernetesingress`). The CRD and Gateway providers are off, so no Traefik CRDs are installed.
- Service `ingress/ok-ingress-traefik` is `NodePort`, `80:30080`, `443:30443`.
- IngressClass `ok-ingress` (controller `traefik.io/ingress-controller`) is **not** the default class.

**Wiring:**

- Kourier's Service was patched to `ClusterIP` (`knative/patch-kourier-clusterip.yaml`). That removes the `nodePort`s, `externalTrafficPolicy` and `allocateLoadBalancerNodePorts`.
- ServiceLB then removed `svclb-kourier`, so no LoadBalancer Service and no svclb pod remained.
- The Ingress `kourier-system/knative-via-ok-ingress` uses `ingressClassName: ok-ingress`, host `*.ok211-serving.ok211.internal`, backend `kourier:80`.

Results from ok211-probe ([raw/n2-entry-point-20261031T123618Z.txt](raw/n2-entry-point-20261031T123618Z.txt)):

| Request | Result |
|---|---|
| `http://192.168.252.2:30080/`, `Host: podinfo.ok211-serving.ok211.internal` | **`200`**, 1.82 s (first request, cold start) |
| Direct `kourier` (now ClusterIP), same host | `200`, 0.021 s |
| Traefik, unknown host `nope.example.internal` | `404` |

**Latency of the second hop:** fortio as in S5 (10 qps, 1 connection, 200 requests, 30 s warm-up), and cold starts as in S3 (B11 zero state, `window: 6s`). The runs were alternated in one session.

| Series | Path | n | min | p50 / median | p90 | p99 | max |
|---|---|---|---|---|---|---|---|
| N2-warm-traefik | probe → Traefik NodePort → Kourier → pod | 200 | – | **2.37 ms** | 4.80 ms | 7.0 ms | 10.7 ms |
| N2-warm-direct | probe → Kourier → pod | 200 | – | **1.75 ms** | 3.47 ms | 6.0 ms | 7.3 ms |
| N2-cold-traefik | via Traefik | 5 | 1294 ms | 1606 ms | – | – | 2749 ms |
| N2-cold-direct | direct | 5 | 967 ms | 2036 ms | – | – | 2444 ms |

- Warm, the extra hop costs **≈ 0.6 ms at p50 and ≈ 1.3 ms at p90**.
- Cold, it is **not measurable**: with n = 5 the cold-start spread (≈ 1–2.7 s) is far larger than the hop. The Traefik median happened to be lower.
- Raw data: [n2-warm-traefik](raw/n2-warm-traefik-fortio-20261031T123703Z.json), [n2-warm-direct](raw/n2-warm-direct-fortio-20261031T123800Z.json), [n2-cold-traefik](raw/n2-cold-traefik-coldstart-20261031T123825Z.tsv), [n2-cold-direct](raw/n2-cold-direct-coldstart-20261031T124251Z.tsv).

**N2b — hostname schema** ([raw/n2b-domain-template-20261031T124749Z.txt](raw/n2b-domain-template-20261031T124749Z.txt)):

`config-network` `domain-template: "{{.Name}}-{{.Namespace}}.{{.Domain}}"` with an Ingress on `*.ok211.internal`:

| Item | Observed |
|---|---|
| ksvc URLs | `podinfo-ok211-serving.ok211.internal`, `podinfo-fail-ok211-events.ok211.internal`, `event-display-ksvc-ok211-events.ok211.internal` (cluster-local `podinfo-private` unchanged) |
| New host via Traefik | **`200`** |
| Old host `podinfo.ok211-serving.ok211.internal` via Traefik | `404` |
| Restore (key removed, `*.ok211.internal` Ingress deleted) | URLs back to `<name>.<namespace>.ok211.internal`, old host `200` again |

Which hostname schema fits ADR-010 (`<app>.<cluster>.internal`):

- **Knative's default** `<name>.<namespace>.<domain>` produces two labels below the cluster domain. A single Ingress wildcard covers exactly one label, so ADR-010 would need **one Ingress per namespace** (`*.<namespace>.<cluster>.internal`), and the hostname does not match `<app>.<cluster>.internal`.
- **N2b's template** `<name>-<namespace>.<domain>` matches the ADR-010 pattern. `<app>` becomes `<name>-<namespace>`, and **one** `*.ok211.internal` Ingress covers every Knative Service in the cluster. The cost: that wildcard also catches non-Knative apps under the same cluster domain, so they need more specific Ingress rules, which Traefik ranks above the wildcard. This ranking was not tested here.

**N2 and server-side apply (finding):**

- While N2 is active, `kubectl-patch` owns `kourier.spec.type`.
- `make knative-dry-run TO=1.24` then fails for `1.24/kourier.yaml`: "conflict with "kubectl-patch" using v1: .spec.type" ([raw/n2-dry-run-1.24-while-n2-active.log](raw/n2-dry-run-1.24-while-n2-active.log)).
- The approach in `knative.sh apply_overrides` (re-apply the ClusterIP patch after a release apply) therefore cannot work, because the apply fails first.
- Operating N2 declaratively needs either a fourth derivation rule (drop `spec.type` and the port fields of `kourier-system/kourier` from the release apply set) or a GitOps overlay that owns the field.
- After `exp-N2-restore` the value equals the release value again, and the dry run is clean.

**Alternative `net-gateway-api`** (not tested):

- [Install Serving with YAML](https://knative.dev/docs/install/yaml-install/serving/install-serving-with-yaml/) lists Gateway API as a networking layer: "This component is in beta." It adds: "The Knative team currently tests the Istio, Contour, and Envoy-Gateway implementations of Gateway API."
- With `net-gateway-api`, Knative would program a shared Gateway instead of running its own Envoy. That would remove the second proxy and the double-TLS question.
- Traefik is not among the tested implementations, and ADR-010 profile v1 uses the Ingress API, not the Gateway API.

### N3 — TLS with cert-manager ([raw/n3-tls-20261031T124842Z.txt](raw/n3-tls-20261031T124842Z.txt))

**Checked against the 1.24 manifests and docs** ([external-domain-tls](https://knative.dev/docs/serving/encryption/external-domain-tls/), [configure-certmanager-integration](https://knative.dev/docs/serving/encryption/configure-certmanager-integration/), read 2026-10-31):

- The cert-manager bridge is **built into Serving 1.24**.
- `config-certmanager` ships in `serving-core.yaml`, labelled `networking.knative.dev/certificate-provider: cert-manager`, with keys `issuerRef`, `clusterLocalIssuerRef` and `systemInternalIssuerRef`.
- `config-network` has `certificate-class: "cert-manager.certificate.networking.knative.dev"` as its default.
- Only cert-manager itself had to be installed. The docs require ≥ 1.0.0.

**cert-manager:**

- `v1.21.3` from the pinned manifest. The images are referenced by tag in the release manifest; their `imageID`s were `controller@sha256:9f4f96a3…`, `cainjector@sha256:083d0e90…` and `webhook@sha256:055ac8e9…`.
- `tls/issuers.yaml` defines:
  - ClusterIssuer `ok211-selfsigned`;
  - Certificate `cert-manager/ok211-ca` (`isCA`, ECDSA P-256, 90 days);
  - ClusterIssuer `ok211-ca-issuer` (CA from secret `ok211-ca`). Both issuers reached `Ready` within 17 s of the install.

**Knative configuration, as merge patches:**

- `config-certmanager.issuerRef = {kind: ClusterIssuer, name: ok211-ca-issuer}`.
- `config-network.external-domain-tls = Enabled`.
- `rollout restart deploy/controller`, as the docs say.

What followed:

- The URL of `podinfo` became `https://podinfo.ok211-serving.ok211.internal`.
- Knative created `certificates.networking.internal.knative.dev/route-5259c5a4-…`, and cert-manager issued `certificates.cert-manager.io/route-5259c5a4-…` (Ready, issuer `ok211-ca-issuer`) within seconds.

**Checks** from a Job in `cert-manager` that mounts **only** `ca.crt` of `ok211-ca` (`items: [{key: ca.crt, path: ca.crt}]`; `tls.key` is neither mounted nor read):

| # | Request | Result |
|---|---|---|
| 1 | `curl --connect-to podinfo.ok211-serving.ok211.internal:443:kourier.kourier-system.svc.cluster.local:443 --cacert /ca/ca.crt https://podinfo.ok211-serving.ok211.internal/` | **`200`**, TLSv1.3, ALPN h2, subject `CN=podinfo.ok211-serving.ok211.internal`, issuer `CN=ok211 lab CA`, SAN matches, `ssl_verify_result=0` |
| 2 | Same without `--cacert` | **curl exit 60** ("unable to get local issuer certificate") |
| 3 | Same host through Traefik websecure (`--connect-to …:443:192.168.252.2:30443`) with `--cacert` | Traefik presents **`CN=TRAEFIK DEFAULT CERT`** (self-issued), curl exit 60: "no alternative certificate subject name matches" |
| 4 | Plain HTTP through Kourier after enabling TLS | `200` (`http-protocol: Enabled` is the default; `Redirected` would answer `302`) |

**Against ADR-010** ("TLS is terminated at the ingress entry point"):

- Knative's cert-manager integration terminates TLS **at Kourier**, with one certificate per route, stored as a Secret in the route's namespace.
- With Traefik as the single entry point, Traefik terminates TLS with its own certificate. Case 3 shows it does not know Knative's certificates.
- An Ingress in `kourier-system` cannot reference a Secret in `ok211-serving`, and TLS passthrough would need Traefik's `IngressRouteTCP` CRD, which profile v1 does not enable.

So under ADR-010 there are two consistent options:

- **(a)** TLS at Traefik only, with a cert-manager certificate for `*.ok211.internal` (N2b schema) on the Ingress. Knative stays at `external-domain-tls: Disabled`, and Kourier gets plain HTTP behind it.
- **(b)** A Gateway-API-based layer where Knative programs the entry point itself.

Running both, as tested here, gives double termination and two certificate chains.

### N4 — cluster-local visibility ([raw/n4-cluster-local-20261031T123300Z.txt](raw/n4-cluster-local-20261031T123300Z.txt))

| Item | Observed |
|---|---|
| Label on ksvc `podinfo-private` | `networking.knative.dev/visibility: cluster-local` (label, not annotation) |
| `status.url` | `http://podinfo-private.ok211-serving.svc.cluster.local` |
| KIngress rule | hosts `podinfo-private.ok211-serving`, `….svc`, `….svc.cluster.local`; `visibility: ClusterLocal` |
| Service `podinfo-private` | `ExternalName` → `kourier-internal.kourier-system.svc.cluster.local` |
| Through `kourier` with `Host: podinfo-private.ok211-serving.ok211.internal` | **`404`** |
| `http://podinfo-private.ok211-serving.svc.cluster.local/` from the probe pod | **`200`** |

### State at the end of the phase

- `external-domain-tls` is back at `Disabled`, and the URLs are `http://` again.
- Kourier is a `LoadBalancer` again with EXTERNAL-IP `192.168.252.2`, and `.local/n2-active` was removed.
- `knative-verify` passed, `smoke` returned `200`, and `knative-dry-run TO=1.24` was clean.
- Still installed, idle:
  - Traefik (`ingress`), 1m CPU and 22 Mi;
  - cert-manager, 3 pods with 1m CPU each and 58 Mi in total;
  - the issuers, the IngressClass `ok-ingress`, and `podinfo-private`.

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| N1 | PASS | Kourier holds hostPorts 80/443 via `svclb`; a second LoadBalancer stays `Pending` (no free ports) | conflict with ADR-010 = second entry point |
| N2 | PASS | `200` through exactly one entry point (Traefik NodePort 30080, `ok-ingress`); warm +0.6 ms p50; cold not distinguishable | N2b schema fits `<app>.<cluster>.internal`; N2 needs SSA handling for `kourier.spec.type` |
| N3 | PASS | HTTPS with a valid chain from the lab CA (`200`, verify 0); without `--cacert` exit 60 | Traefik presents its default certificate: TLS at Kourier ≠ TLS at the ADR-010 entry point |
| N4 | PASS | external host `404`, cluster-local name `200` | — |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Knative can sit behind ADR-010 profile v1 (Traefik, `ok-ingress`, NodePort) as one route to a ClusterIP Kourier, with ≈ 0.6 ms extra p50 latency | Behaviour behind the RKE2 host-cluster proxy of profile v1 (`:80→30080` via KubeVirt), or with more than one node |
| A domain template exists that makes Knative hostnames match `<app>.<cluster>.internal`, so one wildcard Ingress covers all namespaces | How Traefik ranks that wildcard against specific app Ingresses |
| The cert-manager integration is built into Serving 1.24 and issues per-route certificates from a ClusterIssuer within seconds | TLS at the ADR-010 entry point for Knative hosts (option a above), DNS-01 wildcard certificates, or certificate rotation |
| Keeping Kourier's Service patched conflicts with a server-side release apply | That a GitOps overlay or a fourth derivation rule resolves it (not built) |
| `net-gateway-api` is documented as beta with three tested Gateway implementations | Anything about it in practice (not installed) |

## Deviations from BRIEF

1. **Traefik is installed with `helm template` + server-side apply** (field manager `traefik-chart`), not with `helm install`. There is no Helm release object, but the chart is pinned by version and SHA-256 (= repo index digest) and the image by digest. Nothing was run outside make. The Helm config stayed in `.local/helm/`, and `~/Library/Preferences/helm` was not touched (its newest entry is from 2026-10-21).
2. **New pins in `versions.env`:** `TRAEFIK_CHART_SHA256`, `TRAEFIK_APP_VERSION`, `TRAEFIK_IMAGE_DIGEST`. The image digest was read from Docker Hub's registry API (`Docker-Content-Digest` of the OCI index for `v3.7.16`). These are first-fetch pins; there was no earlier independent reference besides the chart index.
3. **cert-manager's images are referenced by tag** in its release manifest (as published). Their `imageID`s are recorded above.
4. **The N3 check Job runs in namespace `cert-manager`,** because a Secret volume must be in the pod's namespace and the CA secret of a CA ClusterIssuer lives in cert-manager's cluster resource namespace. It mounts only `ca.crt`.
5. **`measure-serving.sh` accepts `OK211_TARGET`,** so S3/S5-style series can run through another entry point. Series recorded before this change have no `entry_point` field in their config. For them it was `http://kourier.kourier-system.svc.cluster.local`.
6. **After N2b, the old host returned `404` through Traefik.** It is not verified whether Traefik or Kourier answered.
7. **At the end of the phase, N2 and N3 were restored to the Phase 5/6 baseline**, so later phases (security, GitOps) start from the release state. Traefik, cert-manager and the issuers stay installed.
