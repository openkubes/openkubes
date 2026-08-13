# OK-141 GO-1 protocol v5 — runtime-identity pause

Status: **structurally complete; BLOCKED; GO-1 NOT GRANTED**

Baseline: `main @ c2fc1c7d9900c414278cc1aa8b6868e238cc0057`

GO-1 v5 is an additive, read-only protocol amendment. It preserves the merged
GO-1 v4 checkpoint and binds the installed M0a/M0b control-plane closures to an
explicit runtime pause between lifecycle/enablement convergence and any GitOps
target mutation.

The pause exists because immutable workload identity is only observable after
the disposable cluster exists. No target-access object, TokenRequest,
registration object, or Application may be submitted until a completed runtime
binding has been independently reviewed and named by fresh, separate grants.

```text
GO1-L (not granted)
  -> lifecycle + one HCP
  -> observe CAPI / workload / E / NetworkReady
  -> capture immutable runtime binding
  -> STOP: independent review and new digest-bound grants
  -> target access (not granted)
  -> token + registration (not granted)
  -> three Applications (not granted)
  -> observe P / PlatformReady / evidence
```

All phases are disabled. The protocol does not contain a completed runtime
binding, grant ID, credential, or execution authority.

## Bound identities

```text
FixtureDigest:  sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6
R:              sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e
E:              sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300
P:              sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf
Prior GO-1 v4: sha256:2718d719c322190e36036f98730edcb9aaa679c434fb04f151f7f24fc2626705
Protocol v5:   sha256:685b7e142e9b2e67dcee89ef091df93e4b9aa5d43ff32c7becf6df743e3df2b9
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-v5/verify_go1_protocol_v5.py

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/go1-v5/tests \
  -p 'test_*.py' -v
```

## Safety state

```text
GO1-L:              NOT GRANTED
Runtime pause:      BLOCKED-NOT-ENTERED
M0B-R-TA/TR/RM:     NOT GRANTED
GO1-P:              NOT GRANTED
GO-1:               NOT GRANTED
Infrastructure:     NO-GO
Failure Injection:  NO-GO
```
