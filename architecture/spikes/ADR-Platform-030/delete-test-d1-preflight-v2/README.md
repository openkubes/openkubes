# OK-141 delete D1 Application-semantics amendment v2

Status: **OFFLINE-AMENDED / EXPLICIT READ GRANT REQUIRED / NO-GO**

The first D1 preflight stopped fail-closed because all three Argo Applications
kept their UIDs but changed resourceVersion and generation after D0. A bounded
diagnostic then proved:

- all three remained in the expected project and Synced/Healthy;
- all three UIDs remained stable;
- the Core Application matched the authoritative v9 fixture exactly; and
- Alerting and Dashboards differed only at
  `spec.source.directory.recurse`, where the fixture binds `false` and the API
  omits the false-valued field.

V2 introduces `argocd-application-c14n/v1`: a missing directory `recurse`
field is normalized to `false`. It then compares the complete projected
Application against the three immutable digests in `minimal-observability-v9`.
Application UID remains strict; resourceVersion and generation may advance
only when the full normalized semantics still match. The current
resourceVersion is bound for the later D1 delete.

The AppProject and registration Secret remain strict D0 metadata matches.
This amendment authorizes neither another preflight nor any deletion.
