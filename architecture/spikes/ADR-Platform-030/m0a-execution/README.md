# OK-141 combined M0A-C1 + M0a-I execution candidate

Status: **candidate verified; two explicit grants required; NO-GO**

This candidate joins the already-reviewed temporary credential gate and CAAPH
installation gate into one fail-closed process without merging their authority.
An external grant must contain two distinct grant IDs and explicitly authorize:

```text
M0A-C1  temporary credential bootstrap, TokenRequest, probes, and revocation
M0a-I   one exact 19-object CAAPH control-plane server-side apply
```

Both grants must bind this candidate digest and the same exact window. The
executor refuses mutation unless the grant is current and `--execute` is
present. It uses the administrator identity only for the exact credential
bootstrap and revocation; the CAAPH installation uses the 60-minute bounded
ServiceAccount credential.

The runtime sequence verifies target identity and absence first, runs positive
and negative authorization probes, installs no HCP/HRP target resources, waits
for CRDs/certificate/controller readiness, collects redacted UID evidence, and
revokes the temporary credential in `finally`. A CAAPH rollback is never
automatic and remains a separate decision.

Runtime evidence is prepared for the existing collector/publisher pipeline,
but this candidate grants neither collector dispatch nor publication. Those
remain separate post-run gates after evidence redaction and review.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0a-execution/verify_m0a_execution_candidate.py \
  --candidate architecture/spikes/ADR-Platform-030/m0a-execution/m0a-execution-candidate-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/m0a-execution/m0a-execution-candidate-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0a-execution/tests \
  -p 'test_*.py' -v
```

```text
Candidate digest:    sha256:67e2cb5fb2484292b4a8bfc3b138209af82f672fbc8ee0269421832d5a1a271a
M0A-C1:              NOT GRANTED
M0a-I:               NOT GRANTED
M0b-I / GO-1:        NOT GRANTED
Evidence publication: NOT GRANTED
Infrastructure:      NO-GO
Failure Injection:   NO-GO
```
