# OK-141 GHCR publisher durable correlation

Status: **implemented offline; inert; E0/W0/P0 remain NOT GRANTED**

This additive checkpoint closes the remaining offline source-correlation gap
from the v2 publisher candidate. The v3 candidate embeds a canonical
`source-run-correlation.json` in the deterministic transport. The transport
digest, OCI manifest digest, attestation subject, pull-back verification, and
v2 receipt therefore form one evidence chain.

The correlation binds the exact repository, source run, workflow, head SHA,
event, branch, completion outcome, protocol digest, and internal evidence
bundle digest. Wrong or stale source claims fail closed before publication.

The candidate remains under this inert spike directory. No active workflow,
GitHub environment, package, attestation, dispatch, or external write exists.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-publisher-durable-correlation/verify_publisher_durable_correlation.py \
  --checkpoint architecture/spikes/ADR-Platform-030/ghcr-publisher-durable-correlation/publisher-durable-correlation-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-publisher-durable-correlation/publisher-durable-correlation-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-publisher-durable-correlation/tests \
  -p 'test_*.py' -v
```

```text
Durable source correlation: IMPLEMENTED OFFLINE
Active workflow:            absent
E0 / W0 / P0:               NOT GRANTED
External write:             NO-GO
Infrastructure:             NO-GO
Failure Injection:          NO-GO
```
