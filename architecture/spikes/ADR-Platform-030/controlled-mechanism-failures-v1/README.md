# OK-141 controlled mechanism failures v1

This checkpoint specifies, but does not authorize, two controlled and
reversible DEV failure scenarios after the successful Happy Run.

The purpose is to prove the ownership boundary:

```text
OpenKubes runner/evaluator
  observes + correlates + fails closed

CAAPH/Helm
  owns Enablement convergence

Argo CD
  owns Platform convergence
```

The runner must never repair Cilium, CAAPH, Argo CD, or Platform resources as
a second owner.

## Scenario E1: Enablement / NetworkReady

The exact `HelmChartProxy/disposable-ok141-cilium` on `ok-mgmt` is changed
temporarily from Cilium `1.19.6` to the deliberately nonexistent version
`0.0.0-ok141-controlled-failure`.

Acceptance requires all of the following:

1. the bound E projection no longer evaluates as current;
2. `NetworkReady` fails closed even if the already installed Cilium runtime
   remains healthy;
3. CAAPH/Helm, not the OpenKubes runner, reports and owns convergence;
4. the existing workload Nodes and Cilium DaemonSet remain available;
5. the exact baseline HCP spec is restored with optimistic concurrency; and
6. HCP/HRP plus `NetworkReady` return to the original healthy state.

The invalid chart cannot render, so it cannot supply an alternative release
to Helm. The existing release is not deleted by this scenario. Nevertheless,
this is a live failure injection and requires a separate explicit grant.

## Scenario P1: Platform / PlatformReady

Only `Application/disposable-ok141-observability-dashboards` on `ok-shared`
is changed temporarily from `dashboards` to the deliberately absent path
`dashboards/ok141-controlled-failure-missing` at the same immutable Git
revision.

Acceptance requires all of the following:

1. Argo CD reports manifest-generation failure for the changed generation;
2. `PlatformReady` fails closed;
3. the core and alerting Applications remain `Synced/Healthy`;
4. the existing dashboard ConfigMap remains present and unchanged;
5. the runner does not repair the Application or target resources;
6. the exact baseline Application spec is restored with optimistic
   concurrency; and
7. all three Applications return to `Synced/Healthy` at the bound revision.

Because manifest generation fails before a new desired object set exists,
the existing dashboard object must not be pruned. This remains a live failure
injection and requires a separate explicit grant.

## Execution boundary

Each scenario is an independent single run:

```text
exact preflight
  -> UID/resourceVersion-guarded fault replace
  -> bounded observation
  -> exact UID/resourceVersion-guarded restore
  -> bounded recovery observation
  -> redacted evidence
```

The fault and its exact restore must be authorized together. Unexpected
partial state, identity drift, a second failure domain, credential exposure,
or any required delete/force/finalizer action is a stop condition.

Not authorized by this checkpoint:

- any live mutation;
- retry beyond the one bound fault/restore sequence;
- delete, prune, force delete, or finalizer mutation;
- Secret, token, Kubeconfig, or credential publication;
- changing Cilium runtime resources directly;
- changing Argo CD controller configuration;
- changing core or alerting Platform Applications;
- general cleanup, outage, or management-plane failure injection.

Current state:

```text
E1:             PREPARED / NO-GO
P1:             PREPARED / NO-GO
Infrastructure: unchanged
```

The executable E1 candidate is defined separately in
`enablement-e1-execution-candidate-v1.yaml`. Its default grant template is
non-authorizing. The bounded runner refuses execution without a matching,
active, single-run grant that explicitly authorizes both the fault and the
exact restore.
