# OK-141 M0a final preflight

Status: **ready for explicit decisions; NO-GO**

This additive checkpoint refreshes the `ok-mgmt` target identity and reduces
the CAAPH installation gate to four explicit decisions. It performs no
installation, credential issuance, target convergence, rollback, or failure
injection.

Verified on 2026-08-11:

```text
ok-mgmt incarnation:        unchanged / UID c3b45aab-d2a1-4e64-8f12-77b99186ad4a
Nodes:                      3/3 Ready
Kubernetes:                 v1.34.1 / linux-amd64
CAPI / CAPK:                v1.13.4 / v0.11.2
cert-manager:               v1.20.1
CAAPH:                      absent
CAPI lifecycle inventory:   empty
Installation set:           19 objects / digest verified
Evidence destination:       public digest-bound GHCR evidence / observer proven
```

The current `system:masters` kubeconfig is explicitly rejected for the
installation. A separate credential gate must create, audit, expire, and revoke
one bounded installer identity. Kubernetes RBAC cannot restrict `create` to an
exact content digest, so the trusted bounded installer and its digest checks
remain part of the submission-integrity boundary.

Four decisions are still required:

1. accept or reject the DEV-only CAAPH compatibility risk;
2. accept or reject the reviewed CAAPH controller RBAC boundary;
3. prepare and separately authorize the short-lived installer credential;
4. authorize the exact installation protocol for one bounded window.

No historical `P`, `R`, or `FixtureDigest` changes. No M0b-I or GO-1 authority.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0a-final-preflight/verify_m0a_final_preflight.py \
  --preflight architecture/spikes/ADR-Platform-030/m0a-final-preflight/m0a-final-preflight-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/m0a-final-preflight/m0a-final-preflight-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0a-final-preflight/tests \
  -p 'test_*.py' -v
```

```text
Credential issuance:  NOT AUTHORIZED
M0a-I:                 NOT GRANTED
M0b-I:                 NOT GRANTED
GO-1:                  NOT GRANTED
Infrastructure:        NO-GO
Failure Injection:     NO-GO
```
