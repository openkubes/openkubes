# OK-141 live-observation closure

Status: **nine live obligations evaluated; all installation gates remain NOT GRANTED**

Baseline: `main @ 5dd71198c9aa90ed669d790abe8366d5183e6161`

This checkpoint evaluates the nine `LIVE-OBSERVATION` obligations from the
installation closure matrix. The bounded observer uses explicit kubeconfigs and
only `kubectl get`. The independent provider inventory also uses read-only
`get` operations. No resource was created, patched, deleted, applied, restored,
or restarted.

## Result

```text
OBSERVED-REPEATABLE-PREFLIGHT: 3
OBSERVED-PARTIAL:              2
OBSERVED-NO-RECOVERY-EVIDENCE: 2
UNRESOLVED:                    2

Source blockers closed:       0
Installation gates granted:   0
```

The repeatable observations establish the current `ok-mgmt` and `ok-shared`
incarnations and correlate `ok-shared` Kubernetes v1.34.1/amd64 with the prior
Argo CD evidence. They must be refreshed immediately before an installation
decision.

The accepted DEV availability profile is:

```text
High availability:        not required
Provider snapshots:       not required
Total cluster-state loss: accepted
Recovery mode:            rebuild, not restore/adoption
Production claims:        forbidden
```

The single-control-plane topology and missing provider snapshots are therefore
not treated as defects. They still cannot be presented as production DR or
lifecycle continuity. In particular, loss of `ok-mgmt` leaves existing workload
Clusters running but without authoritative CAPI reconciliation; automatic
adoption by a rebuilt management plane is not claimed.

The partial observations remain intentionally fail closed:

- the exact CAAPH/Kubernetes/CAPI/cert-manager interoperability tuple still has
  no authoritative tested upstream matrix;
- `ok-shared` capacity, requests, limits, and its single control-plane Node are
  observed, but direct etcd membership is not.

Both planes lack bound immutable evidence-destination proof. `ok-infra` exposes
three ready `ok-mgmt` VMs and four ready `ok-shared` VMs, but no
`VirtualMachineSnapshot`, `VirtualMachineRestore`, or `VolumeSnapshot`. This is
accepted for DEV. The intended rebuild path is nevertheless not yet execution-
proven, so no restore, adoption, continuity, or production-DR claim is emitted.

## Important live findings

```text
ok-mgmt:
  Kubernetes:       v1.34.1 / linux-amd64
  Nodes:            1 control plane + 2 workers, all Ready
  CAPI:             v1.13.4
  CAPK:             v0.11.2
  cert-manager:     v1.20.1
  CAAPH:            absent
  CAPI objects:     0 Clusters / 0 Machines

ok-shared:
  Kubernetes:       v1.34.1 / linux-amd64
  Nodes:            1 control plane + 3 workers, all Ready
  Cilium:           4/4 Ready
  Storage:          local-path / Delete / WaitForFirstConsumer
  CSI drivers:      none
  Argo CD:          absent
  Production HA:    intentionally not provided or claimable
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/live-observation-closure/verify_live_closure.py \
  --results architecture/spikes/ADR-Platform-030/live-observation-closure/live-closure-results-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/live-observation-closure/live-closure-results-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/live-observation-closure/tests \
  -p 'test_*.py' -v
```

## Gate state

```text
M0a-I:             NOT GRANTED
M0b-I:             NOT GRANTED
GO-1:              NOT GRANTED
Infrastructure:    NO-GO
Failure Injection: NO-GO
```
