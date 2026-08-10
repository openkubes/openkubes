# OK-141 M0a-I — CAAPH installation gate

Status: **structurally complete; BLOCKED; M0a-I NOT GRANTED**

Baseline: `main @ 489903b9f84386cb5f2b904c917b9f6747ae3a61`

This read-only checkpoint defines the bounded installation gate for CAAPH
v0.6.4 on `ok-mgmt`. It does not install the controller, create credentials,
submit a `HelmChartProxy`, access a workload cluster, or grant GO-1.

The official `addon-components.yaml` release asset is retained locally so the
future installation set can be verified without trusting a mutable download:

```text
raw digest:       sha256:a70f4eb77eac626231daca1e2a046b4b069bb84320efa327cc8c56a9c4ca03e6
semantic digest:  sha256:01fc13d694da3304385a7bae0d1bd662d7c8c3d336b8a4d44da5324439d59095
size:             55263 bytes
objects:          19
```

`M0a-I` is installation-only:

```text
Allowed by a future M0a-I grant
  -> apply exactly the reviewed 19-object CAAPH control-plane set
  -> observe API, webhook, controller, image, and evidence readiness
  -> invoke only the separately bound safe rollback path on STOP

Not allowed
  -> submit HelmChartProxy or HelmReleaseProxy
  -> access or mutate a workload cluster
  -> prove E or NetworkReady
  -> inject restart/retry failure
  -> grant M0a target convergence or GO-1
```

Restart/retry injection remains a separately gated failure scenario. Normal
Kubernetes scheduling during installation is not treated as proof of restart
or retry semantics.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0a-installation/verify_m0a_installation.py \
  --protocol architecture/spikes/ADR-Platform-030/m0a-installation/m0a-installation-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/m0a-installation/m0a-installation-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0a-installation/tests \
  -p 'test_*.py' -v
```

## Safety state

```text
M0a-I protocol:    BLOCKED
M0a-I:             NOT GRANTED
M0a target work:   NOT GRANTED
GO-1:              NOT GRANTED
Infrastructure:    NO-GO
Failure Injection: NO-GO
```
