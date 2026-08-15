# OK-141 M0a installer credential gate

Status: **protocol prepared; BLOCKED; no credential issued**

This protocol replaces the unsuitable long-lived `system:masters` installation
path with one short-lived ServiceAccount token. The temporary role can only
`get` and server-side-apply (`patch`) the 19 exact object names in the reviewed
CAAPH installation set. It grants no Secret access, impersonation, escalation,
binding, token issuance, list, watch, update, direct `create`, or delete verb.
Server-side apply can nevertheless materialize an absent object through its
authorized `patch` request; this is intentional and explicitly bounded.

The bootstrap identity may only create and revoke these three temporary objects:

```text
ServiceAccount      openkubes-system/ok141-m0a-installer
ClusterRole         ok141-m0a-installer
ClusterRoleBinding  ok141-m0a-installer
```

The requested token lasts at most 60 minutes, is never persisted or emitted,
and is revoked by deleting the ServiceAccount and its temporary RBAC immediately
after the bounded run. Credential creation and revocation remain mutations and
therefore require their own exact future authorization.

Kubernetes RBAC constrains request targets, not object content. Submission
integrity therefore still depends on the digest-bound bounded installer. This
limitation is explicit and is not presented as admission-policy enforcement.
Because `caaph-system` does not exist before installation, the temporary
ClusterRole also cannot namespace-limit same-named namespaced targets. The
preflight must prove that none exist outside `caaph-system`, and any appearance
or change causes immediate stop and revocation.

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/m0a-installer-credential/verify_m0a_installer_credential.py \
  --protocol architecture/spikes/ADR-Platform-030/m0a-installer-credential/m0a-installer-credential-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/m0a-installer-credential/m0a-installer-credential-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0a-installer-credential/tests \
  -p 'test_*.py' -v
```

```text
Credential gate:     NOT GRANTED
Credential issued:   no
M0a-I:               NOT GRANTED
M0b-I:               NOT GRANTED
GO-1:                NOT GRANTED
Infrastructure:      NO-GO
Failure Injection:   NO-GO
```
