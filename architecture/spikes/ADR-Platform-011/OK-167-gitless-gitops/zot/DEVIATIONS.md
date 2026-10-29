# Deviations from the `registry-default` profile

`zot/values-poc.yaml` is derived from `platform/registry/zot/values-ok-shared.yaml`. Every
difference is listed here with its reason, so nothing about `registry-default` can be inferred
from the PoC by accident.

Reference: chart `zot-0.1.122`, image `ghcr.io/project-zot/zot:v2.1.20@sha256:542e25be…18234` —
both **identical** to `registry-default`.

## Deliberate differences

| # | `registry-default` | This PoC | Why |
|---|---|---|---|
| D1 | `service.type: ClusterIP` | `service.type: NodePort`, `nodePort: 30500` | The packaging pipeline runs on the host and must reach the registry. There is no ingress controller in this cluster. Host port 5000 is taken by the macOS AirPlay Receiver, hence 30500. kind maps it to `127.0.0.1` only. |
| D2 | OIDC provider (`openid`), `apikey: true`, `sessionKeysFile` | none of them | Out of scope (BRIEF B3 non-goals). Only machine identities are exercised; human access via OIDC is a production concern described in the report, not tested here. |
| D3 | `externalUrl: https://registry.ok-shared.internal` | absent | There is no external URL for a loopback-only PoC. Setting one would make zot advertise a name nothing can resolve. |
| D4 | `realm: registry-default` | `realm: ok167-gitops` | Cosmetic; keeps PoC log lines distinguishable from production ones. |
| D5 | `openkubes/human/**` and `openkubes/machine/**` policies with groups | `openkubes/machine/gitops/**` only, with users | No OIDC means no groups. The prefix is narrowed to the one this spike publishes to; `**` keeps `defaultPolicy: []` exactly as production does. |
| D6 | users `zot-machine`, `zot-puller`, group `platform-admins` | `gitops-publisher`, `gitops-puller`, `ok167-admin` | Separate, least-scope machine identities per ADR-028 §4.5. Publisher gets read/create/update (no delete); puller read only; admin exists solely for the cosign trust-key upload in Q4 and for cleanup. |
| D7 | `adminPolicy` by group | `adminPolicy` by user | Same reason as D5: htpasswd has no group concept. |
| D8 | extensions: `metrics`, `scrub` | plus `search`, `trust`, `events` | The spike's core questions need them: `search` for the trust GraphQL API, `trust` for Q4, `events` for Q3. `search` is deliberately configured **without** a `cve` block, so zot does not download a Trivy database from the internet — confirmed in the log: "cve config not provided, skipping cve-db update". |
| D9 | `pvc.storage: 20Gi`, `storageClassName: local-path` | `2Gi`, `standard` | kind's dynamic provisioner is named `standard`; `local-path` does not exist here and the PVC would stay `Pending`. 2 GiB is ample for a handful of small manifest artifacts. |
| D10 | `serviceAccount.create: false, name: zot` | `create: true` | In production a separate template owns the ServiceAccount. Here the chart creates it. |
| D11 | mounts `/tls`, `/auth`, `/oidc` | `/tls`, `/auth` | No OIDC (D2), so no `/oidc` secret exists to mount. |
| D12 | — | `mountSecret: false`, `secretFiles: null` set explicitly | Neutralises the chart's example `admin:admin` / `user:user` htpasswd. See "Verified, not assumed" below. |
| D13 | `metrics.serviceMonitor.enabled: false` (Prometheus operator present in production) | same, and no operator in this cluster | The `metrics` **extension** is on; only the chart's `ServiceMonitor` object is off. Phase 10 scrapes `/metrics` directly. |

## Unchanged, carried over on purpose

Image pin and digest; `podSecurityContext` and `securityContext` (non-root, `readOnlyRootFilesystem`,
all capabilities dropped, `RuntimeDefault` seccomp); `resources`; the storage block (`dedupe`, `gc`,
`gcDelay`, `gcInterval`); `mountConfig: true`; `httpGet.scheme: HTTPS`; the `externalSecrets` pattern;
`env: SSL_CERT_FILE=/tls/ca.crt`; and the nesting of zot's JSON config — `accessControl` under
`http`, `failDelay` under `http.auth`.

## Verified, not assumed

**The chart's example htpasswd is inert by default, but not for the reason the brief assumed.**
`templates/secret.yaml` is gated on `{{- if and .Values.mountSecret .Values.secretFiles }}` and
`mountSecret` already defaults to `false` in chart 0.1.122, so a default install renders no
`Secret` at all. Setting both keys explicitly (D12) is defence in depth: it states the intent and
stops a later values edit from switching the example users on. `make zot-install` fails if the
rendered output contains any `Secret`.

**`authHeader` is not required, and `registry-default` has no latent probe problem.** The chart
documents a top-level `authHeader` as *"needed when htpasswd authentication is enabled, but the
anonymous access policy is not"*, and injects it into `/livez`, `/readyz` and `/startupz`. This PoC
uses `defaultPolicy: []` — exactly that configuration — and sets **no** `authHeader`. The pod became
Ready, and anonymous probes confirm why:

```text
GET /livez    -> 200     GET /v2/ -> 401
GET /readyz   -> 200
GET /startupz -> 200
```

zot v2.1.20 exempts its health endpoints from access control. `values-ok-shared.yaml` therefore
does not need `authHeader` either — this closes finding F5 from `evidence/00-preflight.md` in
`registry-default`'s favour. Had it been required, the value would have had to be passed via
`--set` from `.local/`, and Kubernetes would have stored it in plaintext in the StatefulSet pod
spec, readable by anyone with `get statefulsets` in the namespace.

## Known gap, not fixed here

The chart ships `templates/tests/test-connection.yaml` and `test-connection-fails.yaml`, which use
an **unpinned `alpine` image**. They are rendered by `helm template` but only applied by
`helm test`, which this spike never runs. Pinning them would mean forking the chart, which is out
of scope. Flagged because `registry-default` inherits the same gap: anyone running `helm test`
against the production release pulls an unpinned image.

## Namespace model note

ADR-028 §4.4 describes the logical namespace as
`openkubes/{platform,cluster,observability,security,storage,ai,robotics,applications,third-party,staging,quarantine}/`,
while the deployed `registry-default` profile uses `openkubes/{human,machine}/**`. This spike
follows the deployed profile, because that is what it has to interoperate with. The discrepancy is
reported, not resolved — resolving it is not this spike's job.
