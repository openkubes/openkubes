# OK-141 M0b-I — Argo CD installation gate

Status: **structurally complete; BLOCKED; M0b-I NOT GRANTED**

Baseline: `main @ 4a86e55bd181dd4313286edcfa6ce2540e5a8378`

This read-only checkpoint defines the bounded installation gate for an Argo CD
v3.4.2 control plane on the `ok-shared` placement candidate. It does not
authorize that placement, install Argo CD, create target credentials, register
a workload cluster, submit an `AppProject` or `Application`, or grant GO-1.

The installation source is bound as four exact upstream files plus one local
Namespace object. The upstream files total about 1.94 MB and are intentionally
represented by a fail-closed source lock rather than duplicated in this
evidence checkpoint. Before any later installation decision they must be
materialized again and match both raw and semantic digests.

```text
HA namespace manifest: 61 objects
CRDs:                   3 objects
Namespace:              1 object
Combined:               65 objects
Combined semantic ID:   sha256:811b07f7…b2fd9d8
```

`M0b-I` is installation-only:

```text
Allowed by a future M0b-I grant
  -> apply exactly the verified 65-object Argo control-plane set
  -> observe CRD, workload, image, and evidence readiness
  -> invoke only the separately bound safe rollback path on STOP

Not allowed
  -> register any workload target
  -> create target credentials or RBAC
  -> submit AppProject, Application, or ApplicationSet desired state
  -> claim P or PlatformReady
  -> inject restart/retry failure
  -> grant M0b target convergence or GO-1
```

The reviewed HA workload shape does not establish production HA while
`ok-shared` still has a single control-plane/etcd member. Placement authority,
capacity evidence, and recovery independent of Argo remain explicit blockers.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-installation/verify_m0b_installation.py \
  --protocol architecture/spikes/ADR-Platform-030/m0b-installation/m0b-installation-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/m0b-installation/m0b-installation-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0b-installation/tests \
  -p 'test_*.py' -v
```

## Safety state

```text
M0b-I protocol:    BLOCKED
M0b-I:             NOT GRANTED
Target registration: NOT GRANTED
GO-1:              NOT GRANTED
Infrastructure:    NO-GO
Failure Injection: NO-GO
```
