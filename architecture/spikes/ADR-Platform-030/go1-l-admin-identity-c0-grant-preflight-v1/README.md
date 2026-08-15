# OK-141 GO1-L administrator identity C0 grant preflight v1

Status: **TECHNICALLY-COMPLETE-WINDOW-UNRESOLVED-NO-GO**

This checkpoint defines the exact, local-only authorization boundary for a
future single C0 credential-identity inspection. It does not inspect either
kubeconfig and grants no authority.

```text
PreflightDigest:       sha256:0b1495ed3c216eb3246d9a43e98ce76eb664a9c6ed81241d866c4df33118b037
SourceCandidate:       sha256:3ed89d8f9792e53068f424d23f609ba3cad31620d7ce4f1a8001a9bf3089db89
SourceAcceptance:      sha256:1bedab96f582b3ca31f67c81b948263560c36fd0a113ec317442cb9c65d25fed
Maximum window:        10 minutes
Window:                unresolved
C0 grant:              NOT GRANTED
Credential inspection: not performed
Cluster contact:       forbidden
Mutation:              forbidden
GO1-L:                 NOT GRANTED
GO-1:                  NOT GRANTED
```

The future grant may authorize one read of exactly:

```text
/Users/arash/.kube/ok-infra.yaml
/Users/arash/.kube/ok-mgmt.yaml
```

Only the target plane, HTTPS API server, CA SHA-256 fingerprint, and credential
identity digest may be retained in local raw evidence. Context, cluster, and
user names and all credential material remain forbidden. The inspection may
not contact either cluster, alter or copy credentials, run a Kubernetes client,
perform a preflight, submit objects, or mutate infrastructure.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-grant-preflight-v1/verify_c0_grant_preflight_v1.py

python3 -m unittest architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-grant-preflight-v1/test_c0_grant_preflight_v1.py
```

A later finalized grant candidate must bind one future UTC window no longer
than ten minutes, a new candidate digest, a single-use grant ID, and the
existing C0 candidate digest. A draft or preflight digest grants no authority.
