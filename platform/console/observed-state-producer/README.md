# OpenKubes Console observed-state producer

This small management-plane service is the read-only producer for the Console
BFF query contract `observed.openkubes.io/v0alpha1`.

It reads only `KubeVirtClusterClaim` resources from `openkubes-system` through a
namespaced ServiceAccount Role and exposes one GET resource:

```text
GET /api/console-observed-state/v0alpha1
```

## Honest semantic boundary

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

| Variable | Default |
| --- | --- |
| `OK_OBSERVER_NAMESPACE` | `openkubes-system` |
| `OK_OBSERVER_MANAGEMENT_NAME` | `ok-mgmt` |
| `OK_OBSERVER_ENVIRONMENT_ID` | `openkubes-management` |
| `OK_OBSERVER_ENVIRONMENT_NAME` | `OpenKubes management plane` |
| `OK_OBSERVER_API_TIMEOUT_SECONDS` | `5` |
| `OK_OBSERVER_PORT` | `8080` |

The remaining management-plane display fields may be supplied through the
`OK_OBSERVER_MANAGEMENT_*` environment variables. They are descriptive only and
do not change readiness.

Build and test:

```bash
make -C platform/console/observed-state-producer verify
podman build -f platform/console/observed-state-producer/Containerfile \
  platform/console/observed-state-producer
```

GitHub Actions runs the same deterministic verification and builds the non-root
container without publishing it.

Before deployment, replace the image placeholder in `manifests.yaml` with a
reviewed immutable digest. The supplied NetworkPolicy permits ingress only from
pods labelled `app.kubernetes.io/name=ok-console-bff` in the same namespace.

## Console BFF connection

Configure the BFF with:

```text
OK_CONSOLE_OBSERVED_STATE_MODE=openkubes
OK_CONSOLE_OBSERVED_STATE_URL=http://observed-state-producer.openkubes-console.svc:8080/api/console-observed-state/v0alpha1
```

The BFF currently permits plaintext HTTP only for loopback. Therefore in-cluster
service DNS requires TLS before this producer can become a shared deployment.
That live TLS and workload-identity boundary belongs with OK-163; do not weaken
the BFF's HTTPS requirement to deploy this prototype.
