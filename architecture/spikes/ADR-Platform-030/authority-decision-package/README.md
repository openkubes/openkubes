# OK-141 authority-decision package

Status: **prepared, undecided, NO-GO**

This package turns the nine `EXPLICIT-AUTHORITY` obligations from the
installation-closure matrix into exact, reviewable decision questions. It is
local-only: preparing or verifying it contacts no Kubernetes API, creates no
credential, assigns no person, chooses no window, and authorizes no mutation.

```text
Decision questions prepared: 9
Decisions made:              0
Authorities assigned:       0
Windows bound:              0
Credential gates included:  0

M0a-I / M0b-I:              NOT GRANTED
GO-1:                       NOT GRANTED
Infrastructure:             NO-GO
Failure Injection:          NO-GO
```

The package records the accepted DEV risk model: HA and provider snapshots are
not required, total state loss is accepted, and recovery is intended to be a
rebuild. It also retains the necessary negative boundary: rebuild is not yet
proven, automatic adoption is forbidden, and no production DR or lifecycle
continuity claim is made.

`M0AI-INSTALLER-CREDENTIAL` and `M0BI-INSTALLER-CREDENTIAL` are deliberately
excluded. Each remains a separate mutation gate requiring its own protocol,
digest, preflight, explicit authority, issuance, revocation, and audit.

The checked-in YAML is an undecided checkpoint. A future decision must be a
new document revision and digest; the verifier intentionally rejects any
decision, authority assignment, time window, grant, or mutation in v1.

The [reviewer guide](reviewer-guide.md) defines the required review order and
the conditions that return a future decision session to `NO-GO`.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/authority-decision-package/verify_authority_decisions.py \
  --package architecture/spikes/ADR-Platform-030/authority-decision-package/authority-decisions-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/authority-decision-package/authority-decisions-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/authority-decision-package/tests \
  -p 'test_*.py' -v
```
