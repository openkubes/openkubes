# OK-141 GHCR publisher deployment preflight

Status: **prepared offline; BLOCKED; all external writes remain NO-GO**

This checkpoint separates three mutations that the inert publisher prototype
previously listed together:

```text
E0  create and protect ok-141-evidence-publish
    -> observe exact protection state

W0  deploy the exact reviewed workflow bytes
    -> observe exact active workflow identity

P0  dispatch one exact source run and publish/attest/pull back
```

Each step requires a separate authorization and a newly bound digest. `E0` must
finish before `W0`: GitHub documents that running a workflow against a missing
environment can create that environment without protection rules or secrets.
Merging this checkpoint creates neither the environment nor the active workflow.

The environment candidate is deliberately DEV-SOLO:

- required reviewer: `github:arashkaffamanesh` / GitHub user ID `1782605`;
- self-review remains allowed because no independent human reviewer is claimed;
- only the exact `main` branch may deploy;
- no environment secret is required; publication uses the job-scoped
  repository `GITHUB_TOKEN`;
- administrator bypass is not claimed absent and must be recorded in the live
  E0 observation.

The workflow deployment candidate remains `workflow_dispatch` only. Deploying
it must not dispatch it, create a package, issue a reusable credential, create
an attestation, or create the observer's active index.

Two candidate amendments are still required before their respective gates can
be considered:

- W0 requires an in-workflow `refs/heads/main` guard before any write-capable
  job can start; environment branch policy is defense in depth, not the only
  source-ref check.
- P0 requires the requested source run to be correlated with the exact
  repository, workflow, head SHA, successful conclusion, artifact name, and
  authorized protocol before download and publication.

## Current observation

Observed read-only on `2026-08-11T16:26:24Z`:

```text
repository:                         public
default branch:                     main
main branch protection:             present
main required approvals:            0
main administrator enforcement:     false
ok-141-evidence-publish environment: absent (404)
active publisher workflow:          absent
```

## Verify

```bash
python3 architecture/spikes/ADR-Platform-030/ghcr-publisher-deployment-preflight/verify_publisher_deployment_preflight.py \
  --preflight architecture/spikes/ADR-Platform-030/ghcr-publisher-deployment-preflight/publisher-deployment-preflight-v1.yaml \
  --digest-file architecture/spikes/ADR-Platform-030/ghcr-publisher-deployment-preflight/publisher-deployment-preflight-v1.sha256

python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/ghcr-publisher-deployment-preflight/tests \
  -p 'test_*.py' -v
```

## Safety state

```text
E0 environment gate:  NOT GRANTED
W0 workflow gate:     NOT GRANTED
P0 publication gate:  NOT GRANTED
M0a-I / M0b-I:        NOT GRANTED
GO-1:                 NOT GRANTED
Infrastructure:       NO-GO
Failure Injection:    NO-GO
```

## Sources

- [GitHub: Managing environments for deployment](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- [GitHub: Deployment environments and protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)
- [GitHub: REST API for deployment environments](https://docs.github.com/en/rest/deployments/environments)
