# OK-141 GO1-L credential boundary v1

Status: **ANALYZED-BLOCKED-NO-GO**

The bounded submitter uses top-level Create requests. Kubernetes RBAC cannot
restrict those requests to an exact `resourceName`, and RBAC does not validate
the submitted object content. A digest-bound submitter therefore improves
submission integrity but does not turn a broad Create permission into an exact
authorization rule.

The namespace bootstrap adds a second boundary: a namespaced Role cannot exist
before its namespace, while creation of the Namespace itself needs
cluster-scoped authority.

This checkpoint records three possible models without selecting one:

1. accept a one-run DEV administrator content boundary;
2. add temporary exact-content admission plus scoped short-lived Create access;
3. replace Create with named server-side PATCH plus admission in a new candidate.

The first model is operationally smallest but has the weakest API-enforced
boundary. The second retains Create-only semantics but adds prerequisite
mutations. The third invalidates the current submitter identity and needs a new
protocol amendment.

Primary Kubernetes reference:
<https://kubernetes.io/docs/reference/access-authn-authz/rbac/#referring-to-resources>

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/go1-l-credential-boundary-v1/verify_go1_l_credential_boundary_v1.py

python3 architecture/spikes/ADR-Platform-030/go1-l-credential-boundary-v1/test_go1_l_credential_boundary_v1.py -v
```

```text
BoundaryDigest:      sha256:ba2d8fdcc773ab333af2560436ad48f27dbb6c7222a627add44ed03b3ce8fa38
Selected model:      UNRESOLVED
Credential issuance: NOT AUTHORIZED
Admission install:   NOT AUTHORIZED
Administrator use:   NOT AUTHORIZED
GO1-L:               NOT GRANTED
GO-1:                NOT GRANTED
Infrastructure:      NO-GO
Failure Injection:   NO-GO
```
