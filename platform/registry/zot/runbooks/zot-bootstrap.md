# Bootstrap registry-default on ok-shared

This is the Increment-1 bootstrap ceremony. Run it from the workspace root in an attended shell. Each cluster command uses `oks` in the same shell expression; never export `KUBECONFIG` manually. Backup and recovery are a separate ceremony in [zot-backup-restore.md](zot-backup-restore.md).

Prerequisites:

- branch `feat/ok-138-registry-default-ok-shared` is already checked out in `openkubes`;
- the local chart checkout exists at `zot/charts/zot` at exact tag `zot-0.1.122` with clean runtime files. It is a workspace-local prerequisite, a sibling of the repositories rather than part of any of them — the same arrangement as the Keycloak and CNPG chart checkouts. Create it once from the workspace root:

  ```bash
  git clone --no-checkout https://github.com/project-zot/helm-charts zot
  git -C zot checkout tags/zot-0.1.122
  git -C zot describe --tags --exact-match   # expect: zot-0.1.122
  ```

  `make` refuses to run against a missing, mistagged or locally modified chart, so this is a hard prerequisite rather than a convenience;
- `kubectl`, Helm, Python 3 with PyYAML, jq, curl, OpenSSL, `htpasswd`, GNU Make and `rg` are installed;
- central Keycloak, ClusterIssuer `ok-shared-internal-ca`, Traefik and StorageClass `local-path` are live;
- `registry.ok-shared.internal` is tested through `curl --resolve` against this cluster's ingress address. No LoadBalancer Service is created. The tooling discovers that address rather than carrying it: `tooling/registry-defaults.sh` takes an explicit `REGISTRY_LB` first, then DNS for the registry hostname (which is what OK-57 will provide, after which the rest is unnecessary), then the LoadBalancer address the infrastructure cluster publishes for this cluster's ingress Service. Point `REGISTRY_LB_KUBECONFIG` at that cluster's kubeconfig, or set `REGISTRY_LB` yourself.

Set a shell-local shelf path and prove the target cluster:

```bash
ZOT_SHELF="$PWD/openkubes/platform/registry/zot"
oks && kubectl config current-context && kubectl get nodes
```

Expected effect: context `ok-shared-admin@ok-shared` and four Ready nodes. If the context differs, stop.

Render before mutation:

```bash
make -C "$ZOT_SHELF" render >/tmp/ok138-zot-rendered.yaml
python3 -c 'import sys,yaml; list(yaml.safe_load_all(open(sys.argv[1]))); print("rendered YAML parsed")' /tmp/ok138-zot-rendered.yaml
```

Expected effect: the chart guard reports no error and the rendered stream parses. The rendered file contains Secret references, not values.

Install in the reviewed order. The approval covers only client/groups/mapper/conformance-user reconciliation in the existing `openkubes` realm; it does not create a realm or touch `ok-mgmt`.

```bash
oks && make -C "$ZOT_SHELF" install \
  KUBECONFIG="$KUBECONFIG" APPROVE_OIDC_CLIENT=yes
```

Expected effects: namespace and bootstrap Secrets exist, Certificate becomes Ready, the central OIDC target prints a decoded `groups` claim, Helm reports the zot release, StatefulSet rollout completes, ServiceMonitor is admitted, and `post-check` ends in PASS. Secret values must not appear.

Re-run the read-only live baseline explicitly:

```bash
oks && make -C "$ZOT_SHELF" post-check KUBECONFIG="$KUBECONFIG"
```

Expected effects include:

- `POD_READY ... Ready=True`;
- `CERTIFICATE_READY ... Ready=True`;
- `TLS_ROUTE: GET /v2/ HTTP 200 distribution=registry/2.0 running=v2.1.20 ...`, ending with the `registry.ok-shared.internal:443:<discovered address>` it used;
- `METRICS_AUTH: unauthenticated=401|403 authenticated=200`;
- ServiceMonitor selector matches Service labels and port `zot`;
- Prometheus/PrometheusAgent count remains zero unless observability was installed separately.

Prove human OIDC and group-driven authorization. This temporarily removes the dedicated writer's group, proves a newly issued token and session lose access, and restores membership in a `finally` path.

```bash
RUN_ID="ok138-oidc-$(date -u +%Y%m%dT%H%M%SZ)"
oks && RUN_ID="$RUN_ID" make -C "$ZOT_SHELF" oidc-conformance \
  KUBECONFIG="$KUBECONFIG" APPROVE_OIDC_CLIENT=yes
```

Expected effects: writer token shows `registry-writers`; writer push/pull succeeds and outside-prefix returns 403; reader pull succeeds and push returns 403; the post-removal token omits `registry-writers` and granted-prefix upload returns 403; restored token carries the group and pulls successfully.

Prove the machine contract and authenticated push counter:

```bash
RUN_ID="ok138-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
oks && RUN_ID="$RUN_ID" make -C "$ZOT_SHELF" smoke KUBECONFIG="$KUBECONFIG"
```

Expected effects: machine push/pull and digest retrieval succeed; puller push is denied; Helm bytes match; Referrers index and discovered subject are asserted; `/metrics` is authenticated and `zot_repo_uploads_total` for this unique repository increases.

Run the dedicated in-cluster Job contract:

```bash
RUN_ID="ok138-job-$(date -u +%Y%m%dT%H%M%SZ)"
oks && RUN_ID="$RUN_ID" make -C "$ZOT_SHELF" contract-job KUBECONFIG="$KUBECONFIG"
```

Expected effects: the Job mounts `ca.crt` and the machine Secret, then reports byte-equal digest pull, a structurally asserted Referrers result, and HTTP 403 outside its prefix. Its output must say: `in-cluster OCI contract proven; kubelet image pull NOT proven`.

Inspect the registered scrape object and prove there is no consumer:

```bash
oks && kubectl get servicemonitor zot -n zot -o yaml
oks && kubectl get prometheus,prometheusagent -A
```

Expected effect: the ServiceMonitor carries Secret-backed `basicAuth`, TLS CA/serverName, selector labels and named port `zot`; there are no Prometheus resources to scrape it. Do not claim a scrape.

Finish with a drift check:

```bash
oks && make -C "$ZOT_SHELF" diff KUBECONFIG="$KUBECONFIG"
```

Expected effect: `no drift`. A `kubectl diff` exit 1 means the bootstrap is not complete; inspect the raw diff.

Do not run teardown as part of bootstrap. If rollback is required, `make help` lists individually gated reverse targets. Aggregate `teardown CONFIRM=yes` retains the PVC/data and central Keycloak objects. `teardown-data CONFIRM=yes` irreversibly destroys registry content and requires a separate operator decision.

Record every command's live output and any step whose expected effect did not occur. Do not tick ADR-Platform-028 §8 based on this runbook alone.
