# OK-141 GO1-L administrator identity C0 v1

Status: **OFFLINE-PROVEN-BLOCKED-NO-GO**

This candidate defines one local-only inspection of:

```text
/Users/arash/.kube/ok-infra.yaml
/Users/arash/.kube/ok-mgmt.yaml
```

The inspection derives only each target plane's HTTPS API server, CA SHA-256
fingerprint, and a digest of the context/cluster/user/server/CA identity tuple.
It emits no context, cluster, or user name and no token, certificate, private
key, password, raw CA, kubeconfig content, or kubeconfig digest.

The tool contains no Kubernetes client call. It rejects insecure TLS, proxy
redirection, external credential plugins/files, symlinks, repository-local
files, and modes other than `0600`.

```text
CandidateDigest:      sha256:3ed89d8f9792e53068f424d23f609ba3cad31620d7ce4f1a8001a9bf3089db89
Credential files:     2
Inspection performed: no
Inspection grant:     NOT GRANTED
Cluster contact:      forbidden
Mutation:             forbidden
GO1-L:                NOT GRANTED
GO-1:                 NOT GRANTED
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-v1/verify_go1_l_admin_identity_c0_v1.py

python3 architecture/spikes/ADR-Platform-030/go1-l-admin-identity-c0-v1/test_inspect_admin_identity_c0_v1.py -v
```

A future C0 grant must bind this candidate digest, one single-run scope, and a
maximum ten-minute window. It authorizes local identity derivation only—not
credential use against either API server.
