# OK-141 GO1-L administrator identity C0 grant v1

Status: **READY-FOR-C0-DECISION-NO-GO**

This artifact binds one proposed, local-only credential-identity inspection
window. It is a grant candidate and does not authorize the inspection.

```text
GrantCandidateDigest: sha256:5a77f10a76a9b2386f3fe967bb26b6a6821f4ac7f08b9ed74f2ec3a5b35e3c76
Grant ID:             ok141-go1-l-c0-20260813-01
Authority:            github:arashkaffamanesh
Window:               2026-08-13T16:00:00Z–2026-08-13T16:10:00Z
Scope:                one local read of two admin kubeconfig identities
C0:                   NOT GRANTED
Credential inspection:not performed
Cluster contact:      forbidden
Mutation:             forbidden
GO1-L:                NOT GRANTED
GO-1:                 NOT GRANTED
```

The proposed grant permits one local read of exactly
`/Users/arash/.kube/ok-infra.yaml` and
`/Users/arash/.kube/ok-mgmt.yaml`. Only the target plane, HTTPS API server,
CA SHA-256 fingerprint, and credential identity digest may be written to the
private raw-evidence file. It permits no Kubernetes client, network contact,
credential copy or change, preflight, submission, or infrastructure mutation.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-grant-v1/verify_c0_grant_candidate_v1.py

python3 -m unittest architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-grant-v1/test_c0_grant_candidate_v1.py
```

Only an explicit authority statement that binds the exact candidate digest,
grant ID, and UTC window may grant C0. Expiry or any changed field requires a
new candidate and digest.
