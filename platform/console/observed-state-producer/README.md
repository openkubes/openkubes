# OpenKubes Console observed-state producer

This small service is the read-only producer for the Console BFF query contract
`observed.openkubes.io/v0alpha1`.

It exposes one GET resource:

```text
GET /api/console-observed-state/v0alpha1
```

## Honest semantic boundary

The producer has two explicit source modes. It never discovers or switches a
mode automatically:

- `kubevirt-claims` reads only namespaced `KubeVirtClusterClaim` resources for
  the first OpenKubes management-plane adapter;
- `hosting-cluster` reads only Kubernetes `/version`, the bounded Node list and
  one explicitly named Console Deployment for the OK-170 Phase B1 path.

The hosting source projects its target as a read-only workload cluster with the
profile `Console hosting cluster`. It keeps `ok-mgmt` separate and `Unknown`,
because it observes neither the OpenKubes control plane nor Compositions. Node
names, addresses, labels, pod data and Deployment templates are discarded.

The current OpenKubes implementation provides cluster Claims and Crossplane
Conditions, but not a complete Fleet, Capability, workload-placement, findings,
or historical Evidence read model. Consequently the producer:

- maps only a Claim's `Ready` Condition to workload-cluster readiness;
- never treats Kubernetes API reachability as management-plane readiness;
- reports the management plane and unavailable lifecycle semantics as `Unknown`;
- returns empty Capability/workload/finding projections with `partial: true`;
- emits redaction-safe Evidence references derived from resource identity,
  resourceVersion, Condition status and transition time;
- ignores backend Condition messages and reasons; and
- performs no mutation and never returns Secrets, kubeconfigs, tokens, raw
  Kubernetes objects, or unrestricted Evidence payloads.

This deliberate partial result prevents the prototype UI from inventing
platform readiness. Later normative Contracts can extend or replace the source
projection without changing the Console BFF Presentation Contract.

## Runtime

The service uses only the Python standard library. In-cluster configuration is
read from the standard ServiceAccount token and CA mounts. Important values:

The runtime image removes `pip`, packaging tools and all third-party
`site-packages`; dependencies must not be installed dynamically at startup.

| Variable | Default |
| --- | --- |
| `OK_OBSERVER_SOURCE_MODE` | `kubevirt-claims` |
| `OK_OBSERVER_NAMESPACE` | `openkubes-system` |
| `OK_OBSERVER_MANAGEMENT_NAME` | `ok-mgmt` |
| `OK_OBSERVER_ENVIRONMENT_ID` | `openkubes-management` |
| `OK_OBSERVER_ENVIRONMENT_NAME` | `OpenKubes management plane` |
| `OK_OBSERVER_HOSTING_NAME` | `ok-shared` |
| `OK_OBSERVER_HOSTING_NAMESPACE` | `openkubes-console` |
| `OK_OBSERVER_HOSTING_DEPLOYMENT` | `ok-console` |
| `OK_OBSERVER_HOSTING_REGION` | `unknown` |
| `OK_OBSERVER_API_TIMEOUT_SECONDS` | `5` |
| `OK_OBSERVER_PORT` | `8443` |
| `OK_OBSERVER_TLS_CERT_FILE` | required mounted server certificate chain |
| `OK_OBSERVER_TLS_KEY_FILE` | required mounted server private key |
| `OK_OBSERVER_TLS_CLIENT_CA_FILE` | required mounted CA for Console BFF identities |
| `OK_OBSERVER_TLS_CLIENT_IDENTITY` | required exact SPIFFE URI SAN for the Console BFF |

The remaining management-plane display fields may be supplied through the
`OK_OBSERVER_MANAGEMENT_*` environment variables. They are descriptive only and
do not change readiness.

The `hosting-cluster` deployment identity requires only `get/list` on Nodes,
`get` on the exact Console Deployment, and `get` on the `/version`
non-resource URL. It must not receive Secret, Pod, mutation, exec, log or broad
discovery permissions.

Build and test:

```bash
make -C platform/console/observed-state-producer verify
podman build -f platform/console/observed-state-producer/Containerfile \
  platform/console/observed-state-producer
```

GitHub Actions runs the same deterministic verification and builds the non-root
container without publishing it.

The separate OK-171 trusted-tag workflow publishes reviewed development
candidates to `ghcr.io/openkubes/observed-state-producer`. Its immutable image,
supply-chain, signing and verification contract is documented in
`OK-171-EVIDENCE.md`. Deployment manifests must use the recorded digest, never
only the discovery tag.

Before deployment, replace the image placeholder in `manifests.yaml` with a
reviewed immutable digest and provision `Secret/observed-state-producer-tls`
with `tls.crt`, `tls.key`, and `client-ca.crt`. Private keys are mounted read
only; they are never accepted through environment-variable values. The supplied
NetworkPolicy permits ingress only from pods labelled
`app.kubernetes.io/name=ok-console-bff` in the same namespace.

The server accepts TLS 1.2 or newer. `/healthz` is an HTTPS-only, non-sensitive
probe and does not require client identity. The versioned observed-state query
requires a client certificate that chains to the explicit client CA and carries
the exact configured SPIFFE URI SAN. Missing or different identity returns a
bounded 403 and an untrusted certificate fails the TLS handshake. NetworkPolicy
is defense in depth and is not used as identity.

## Console BFF connection

Configure the BFF with:

```text
OK_CONSOLE_OBSERVED_STATE_MODE=openkubes
OK_CONSOLE_OBSERVED_STATE_URL=https://observed-state-producer.openkubes-console.svc:8443/api/console-observed-state/v0alpha1
```

The corresponding Console profile must trust the issuing server CA and present
its own narrowly issued client certificate. Certificate issuance, CA custody,
rotation overlap, revocation strategy, and recovery exercises remain deployment
responsibilities; this repository does not mint or embed production credentials.
Fixture rollback remains explicit on the Console side and must never occur
silently after an identity or TLS failure.
