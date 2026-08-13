# OK-141 M0b v2 execution candidate

This checkpoint prepares one bounded, two-phase, create-only installation of the
Argo CD v3.4.2 non-HA namespace profile on `ok-shared`. It does not authorize
the installation.

The reviewed target set contains 54 objects:

- phase 1: one Namespace and three CRDs;
- phase 2: 50 objects explicitly projected into `argocd`;
- desired runtime: six Deployments, one StatefulSet, and seven Pods;
- excluded: target credentials, registration, AppProjects, Applications,
  ApplicationSets, platform convergence, GO-1, and failure injection.

The final point-in-time preflight observed the bound `ok-shared` incarnation,
four Ready amd64 Nodes, all 54 target identities absent, the accepted
`system:masters` administrator identity, and all three locked linux/amd64 image
digests. The executor writes raw local evidence with `O_EXCL` and mode `0600`
before the first create and after each accepted phase. It never retries or rolls
back automatically.

Create acceptance is deliberately distinct from readiness. The initial v2
evaluator failed closed because Kubernetes CRI reports the pulled multi-arch
index digest, not the selected platform-child digest. Runtime also proved that
Argo CD natively creates `AppProject/argocd/default` during server bootstrap.
The additive v2.2 evaluator binds both image identities and accepts exactly that
native object while requiring zero OpenKubes-submitted target-state objects.
Runtime evidence remains local under `/private/tmp`; publication requires a
separate grant.

Current state:

```text
Execution candidate:  CONSUMED-EXACTLY-ONCE
Create phases:        4 + 50 ACCEPTED
Runtime readiness:    PASS (v2.2)
M0b-I:                COMPLETE LOCALLY
Native default project risk: ACCEPTED WHILE NO TARGET STATE IS SUBMITTED
Evidence publication: NOT GRANTED
Target registration: NOT GRANTED
Platform convergence: NOT GRANTED
GO-1:                 NOT GRANTED
Failure injection:    NOT GRANTED
```

Offline verification:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-execution-v2/verify_m0b_execution_v2.py
python3 architecture/spikes/ADR-Platform-030/m0b-execution-v2/verify_m0b_v2_runtime_closure.py --with-raw
python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0b-execution-v2/tests \
  -p 'test_*.py'
```
