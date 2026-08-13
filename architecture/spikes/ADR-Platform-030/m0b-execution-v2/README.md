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

Create acceptance is deliberately distinct from readiness. The separate
read-only evaluator requires all 54 reviewed objects, three Established CRDs,
seven Ready workloads and Pods, exact runtime image identities, and zero Argo
target-state custom resources. Runtime evidence remains local under
`/private/tmp`; publication requires a separate grant.

Current state:

```text
Execution candidate:  READY-FOR-FINAL-PREFLIGHT-NO-GO
Final preflight:      PASS-POINT-IN-TIME-NO-GO
Grant candidate:      READY-FOR-EXPLICIT-GRANT / NO-GO
M0b-I:                NOT GRANTED
Target registration: NOT GRANTED
Platform convergence: NOT GRANTED
GO-1:                 NOT GRANTED
Failure injection:    NOT GRANTED
```

Offline verification:

```bash
python3 architecture/spikes/ADR-Platform-030/m0b-execution-v2/verify_m0b_execution_v2.py
python3 -m unittest discover \
  -s architecture/spikes/ADR-Platform-030/m0b-execution-v2/tests \
  -p 'test_*.py'
```
