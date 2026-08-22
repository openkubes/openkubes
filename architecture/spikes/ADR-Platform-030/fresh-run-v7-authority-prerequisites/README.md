# OK-147 Fresh-Run-v7 authority prerequisites

This offline, non-authorizing checkpoint closes the two writer gaps found by
the live Fresh-Run-v7 preflight:

- the existing `ok-mgmt` management writer can create the bound Namespace but
  does not yet have the namespaced lifecycle and Enablement permissions; and
- `ok-shared` has no dedicated GitOps writer for the exact AppProject,
  registration Secret and three Applications.

The generated packages add only `get` and `create`. They contain no wildcard,
update, patch, delete, bind, escalate, impersonate, credential or token. Each
create boundary is paired with a fail-closed ValidatingAdmissionPolicy that
restricts the exact service-account subject, namespace, resource and object
name. The existing Namespace-only authority on `ok-mgmt` remains separate.

```text
ok-mgmt package:   ClusterRole + ClusterRoleBinding + policy + binding
ok-shared package: ServiceAccount + Role + RoleBinding + policy + binding

authorization:     NO-GO
cluster contact:   false
credentials:       absent
mutation:          false
```

Generate and verify:

```bash
python3 generate_authority_prerequisites.py
python3 verify_authority_prerequisites.py
python3 -m unittest -v test_authority_prerequisites.py
```

The package is bound to Fresh-Run-v7 Plan
`sha256:4f61e81b3f3dba5a2819e5be93764486d5a936f3fb2ba153a80d5866801af19c`.
Installation, TokenRequests, activation and stage execution remain separate
live decisions.
