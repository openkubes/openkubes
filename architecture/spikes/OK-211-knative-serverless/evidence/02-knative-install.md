# 02 — Knative 1.23 install

- Test IDs: Phase 3 (install, verify, Kourier on K3s, smoke test, snapshot for U3)
- Date (UTC): 2026-10-30T14:17:54Z – 2026-10-30T14:23:40Z
- Commit: `825b685` plus the Phase 3 changes in this commit
- Environment: VM `ok-knative-local`, K3s `v1.35.5+k3s1`, Knative Serving `knative-v1.23.0`, net-kourier `knative-v1.23.0`, Eventing `knative-v1.23.1`; see [00-preflight.md](00-preflight.md), [01-vm-k3s.md](01-vm-k3s.md)

## Steps

```bash
make -C architecture/spikes/OK-211-knative-serverless knative-install VERSION=1.23
#   per file: sha256 vs versions.env, then kubectl apply --server-side --field-manager=knative-release -f .local/manifests/1.23/<file>
#   serving-crds → wait Established → serving-core → wait webhook, controller Available
#   kourier.yaml → patch config-network (knative/patch-config-network.yaml) → patch config-domain (knative/patch-config-domain.yaml)
#   eventing-crds → wait Established → eventing-core → wait eventing-webhook → in-memory-channel → mt-channel-broker → wait all Available
make -C … knative-verify
make -C … probe-up apps-serving smoke
#   smoke: kubectl exec ok211-probe -- curl -H 'Host: podinfo.ok211-serving.ok211.internal' http://kourier.kourier-system.svc.cluster.local/
make -C … down; make -C … vm-snapshot NAME=knative-1-23; make -C … vm-start tunnel   # U3 preparation
make -C … knative-verify smoke                                                      # after the restart
```

`serving-default-domain.yaml` was not applied (and never downloaded). No conflict occurred, so `--force-conflicts` was never needed.

## Observed

### Install timeline ([raw/knative-install-1.23-steps.log](raw/knative-install-1.23-steps.log))

| Step | Start → end (UTC) | Duration |
|---|---|---|
| `serving-crds.yaml` apply + Established | 14:17:55 → 14:17:56 | 1 s |
| `serving-core.yaml` apply | 14:17:56 → 14:17:57 | 1 s |
| wait `webhook` Available | 14:17:57 → 14:18:04 | 7 s |
| wait `controller` Available | 14:18:04 → 14:18:12 | 8 s |
| `kourier.yaml` + both patches | 14:18:12 | < 1 s |
| `eventing-crds.yaml` + Established | 14:18:12 → 14:18:17 | 5 s |
| `eventing-core.yaml` + wait `eventing-webhook` | 14:18:17 → 14:18:34 | 17 s |
| `in-memory-channel.yaml`, `mt-channel-broker.yaml`, wait all Available | 14:18:34 → 14:19:10 | 36 s |
| **Total** | 14:17:55 → 14:19:10 | **75 s** |

Image pulls from `gcr.io/knative-releases` were fast. The slow link seen in Phase 2 affected `dl.k8s.io` and the Multipass image only.

### `make knative-verify` — all PASS (14:19:20Z)

| Namespace | Deployments `Available`, label `app.kubernetes.io/version` |
|---|---|
| `knative-serving` | `activator`, `autoscaler`, `controller`, `net-kourier-controller`, `webhook`: all `1.23.0` |
| `kourier-system` | `3scale-kourier-gateway`: `1.23.0` |
| `knative-eventing` | `eventing-controller`, `eventing-webhook`, `imc-controller`, `imc-dispatcher`, `job-sink`, `mt-broker-controller`, `mt-broker-filter`, `mt-broker-ingress`, `pingsource-mt-adapter` (0 replicas until a PingSource exists): all `1.23.1`; plus StatefulSet `request-reply` 1/1 |

Webhooks `knative-serving/webhook` and `knative-eventing/eventing-webhook` have ready endpoints. `kubectl get ksvc -A` works. Overrides: `config-network` `ingress-class: kourier.ingress.networking.knative.dev`, and `config-domain` has the key `ok211.internal`. 30 Knative CRDs are installed.

**Gateway digest (CP1 decision a):** the `kourier-gateway` container reports `imageID` `docker.io/envoyproxy/envoy@sha256:7765ad61185fca9c9a770c9e2cad640d085d708ae9c22f3741345e88331472a4`, equal to `KOURIER_GATEWAY_EXPECTED_DIGEST` (= `v1.37.11`). PASS.

### Running images and resources per component

Full record with image references, `imageID`s and resource specs: [raw/knative-1.23-components.json](raw/knative-1.23-components.json).

| Namespace | Component | Image (digest prefix) | Requests CPU / mem | Limits CPU / mem |
|---|---|---|---|---|
| knative-serving | activator | `activator@sha256:e5ab46f3b73f` | 300m / 60Mi | 1 / 600Mi |
| knative-serving | autoscaler | `autoscaler@sha256:879da127b23d` | 100m / 100Mi | 1 / 1000Mi |
| knative-serving | controller | `controller@sha256:ca5062ece032` | 100m / 100Mi | 1 / 1000Mi |
| knative-serving | net-kourier-controller | `kourier@sha256:eedfe3938f1e` | 200m / 200Mi | 1 / 500Mi |
| knative-serving | webhook | `webhook@sha256:3846e9a41666` | 100m / 100Mi | 500m / 500Mi |
| kourier-system | 3scale-kourier-gateway | `envoy:v1.37-latest` → `sha256:7765ad61185f` | 200m / 200Mi | 1 / 800Mi |
| knative-eventing | eventing-controller | `controller@sha256:1564af0477c2` | 100m / 100Mi | – |
| knative-eventing | eventing-webhook | `webhook@sha256:e704da77e122` | 100m / 50Mi | 200m / 200Mi |
| knative-eventing | imc-controller | `channel_controller@sha256:66651c97ad0d` | – | – |
| knative-eventing | imc-dispatcher | `channel_dispatcher@sha256:edb4e71bc823` | – | – |
| knative-eventing | job-sink | `jobsink@sha256:160774931add` | 125m / 64Mi | 1 / 2Gi |
| knative-eventing | mt-broker-controller | `mtchannel_broker@sha256:7b495357d0c4` | 100m / 100Mi | – |
| knative-eventing | mt-broker-filter | `filter@sha256:77e9e439b3e7` | 100m / 100Mi | – |
| knative-eventing | mt-broker-ingress | `ingress@sha256:42d4a916017f` | 100m / 100Mi | – |
| knative-eventing | request-reply (StatefulSet) | `requestreply@sha256:475930152913` | – | – |

Sum of **requests**: Serving 800m / 560Mi, Kourier 200m / 200Mi, Eventing 625m / 514Mi, **total 1625m CPU and 1274Mi memory** on a 4-CPU node. This is a scheduling reservation, not consumption. Consumption is measured in S10.

### Kourier on K3s (ServiceLB)

| Item | Observed |
|---|---|
| Service `kourier-system/kourier` | `LoadBalancer`, ClusterIP `10.43.179.87`, **EXTERNAL-IP `192.168.252.2`** (the node IP, assigned by ServiceLB), ports `80:32500/TCP`, `443:32213/TCP` (targets 8080/8443) |
| Service `kourier-internal` | `ClusterIP` `10.43.5.182`, 80/443 |
| ServiceLB | DaemonSet `kube-system/svclb-kourier-4dbecc97`, image `rancher/klipper-lb:v0.4.17`, containers `lb-tcp-80` (hostPort 80) and `lb-tcp-443` (hostPort 443), pod `10.42.0.9` |
| Host ports 80/443 | no listening socket in the VM (`ss -ltnp`). Instead, iptables DNAT rules in `CNI-DN-…`: `--dport 80 -j DNAT --to-destination 10.42.0.9:80`, the same for 443 |

So Kourier, as installed, occupies the node's ports 80 and 443 through the first and only LoadBalancer. N1 shows the consequence.

### Smoke test — PASS (14:19:54Z)

`make apps-serving` created the ksvc `podinfo` (`6.16.0` by digest). The webhook printed a warning: *"Kubernetes default value is insecure, Knative may default this to secure in a future release: …allowPrivilegeEscalation, …capabilities, …runAsNonRoot, …seccompProfile"* (input for X1).

Objects created: Configuration `podinfo`, Revision `podinfo-00001`, Route `podinfo` with URL `http://podinfo.ok211-serving.ok211.internal`, PodAutoscaler and ServerlessService `podinfo-00001` (mode `Proxy`), KIngress `ok211-serving/podinfo`.

From `ok211-probe`, `curl -H 'Host: podinfo.ok211-serving.ok211.internal' http://kourier.kourier-system.svc.cluster.local/` returned `http_code=200 time_total=0.002770` with body `"version": "6.16.0"`, `"goarch": "arm64"`, hostname `podinfo-00001-deployment-…`.

### Snapshot for U3 and the restart window (finding)

`make down` → `make vm-snapshot NAME=knative-1-23` → `make vm-start tunnel`:

- The qemu driver supports snapshots of the stopped instance: `Snapshot taken: ok-knative-local.knative-1-23` (14:21:49Z, 40 GiB disk, 8 GiB memory, no parent). The VM IP stayed `192.168.252.2` after the restart.
- After the restart (VM started 14:22:09Z) `knative-verify` failed at first (`eventing-webhook`, `job-sink` not yet Available) and was green at 14:22:40Z.
- **The smoke test still returned `503` for about one minute after every deployment was `Available`** (4 requests between ≈ 14:22:40Z and 14:23:11Z, each after ≈ 3.1 s). Envoy reported `upstream connect error … delayed connect error: No route to host`, upstream `10.42.0.5:8012`.
- Cause, observed: the public endpoints of the ServerlessService `podinfo-00001` (mode `Proxy`, so they should list the activator) still held `10.42.0.5`, the activator's pod IP **before** the restart. The new activator had `10.42.0.33`. The activator also logged "Websocket connection could not be established … autoscaler … connection refused" until 14:22:24Z.
- The endpoints were corrected by 14:23:32Z without any intervention, and the next smoke request returned `200` (1.44 s, including the activator path).

## Verdict

| ID | Verdict | Key value | Note |
|---|---|---|---|
| P3-install | PASS | all components Available in 75 s; overrides set | server-side apply, no conflicts |
| P3-checksums | PASS | every applied file matched its pin immediately before apply | `knative.sh manifest()` |
| P3-gateway-digest | PASS | `imageID` = `sha256:7765ad61…72a4` | CP1 decision (a) works |
| P3-kourier-k3s | PASS | LoadBalancer via ServiceLB on node ports 80/443 | input for N1 |
| P3-smoke | PASS | `200`, version `6.16.0` | — |
| P3-snapshot | PASS | `ok-knative-local.knative-1-23` | enables practical U3 |
| P3-restart | PARTIAL | ≈ 1 min of `503` after a node restart despite all deployments `Available` | finding for Phase 10.6 (operations) |

## What this proves / What this does not prove

| Proves | Does not prove |
|---|---|
| Knative 1.23 installs declaratively from pinned, checksum-verified release YAMLs on K3s 1.35.5, with overrides that survive as merge patches | That the overrides survive a re-apply of the release manifests (G1, upgrade U1) |
| Kourier takes the node's 80/443 through ServiceLB without extra configuration | That this is acceptable under ADR-010 (N1/N2) |
| A Knative Service answers through Kourier from inside the cluster | External reachability, DNS, TLS (N2/N3) |
| After a full node restart the data path recovers by itself, within ≈ 1 min after the deployments are Available | How long the window is on a multi-node cluster or after an activator-only restart; whether a readiness gate could close it |

## Deviations from BRIEF

1. `pingsource-mt-adapter` runs with 0 replicas until a PingSource exists. `knative-verify` counts it as Available, which is what Kubernetes reports.
2. `request-reply` is a StatefulSet, not a Deployment. It was checked separately (1/1).
3. Probe pod: an `emptyDir` was added at `/work` (the root filesystem stays read-only). BusyBox `date` in the curl image has no `%N`, so millisecond timestamps for U1 come from `kubectl logs --timestamps` of a dedicated probe pod (B11 allows this time source).
4. `KNATIVE_WAIT` (default 900 s) replaces the fixed 300 s wait, to tolerate slow image pulls.
