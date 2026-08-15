# OK-141 publisher token-environment amendment

Status: **reviewed source amendment; no publisher run authorized**

P1 proved that OCI publication, attestation and digest pull-back all work. Its
final step failed before receipt creation because `gh attestation verify`
requires `GH_TOKEN` in the process environment.

This amendment adds exactly:

```yaml
env:
  GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

to the final verification step. It introduces no new secret, credential or
permission: the same ephemeral job token was already used in earlier workflow
steps, and the workflow permissions remain unchanged. GitHub masks the value;
it is never persisted in evidence.

The amended workflow digest is:

```text
sha256:26cd4a5c964159d5920a8bd0b1596ded1d9248e35f752878f409203f23917b7b
```

The workflow remains manual-only. Merging this source amendment does not
dispatch it and does not authorize another package, attestation or run.

```text
Publisher run:       NOT AUTHORIZED
P1 retry:            CONSUMED / CLOSED
GO-1:                NOT GRANTED
Infrastructure:      NO-GO
Failure injection:   NO-GO
```
