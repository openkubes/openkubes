# ADR-Platform-010: Ingress for OpenKubes Workload Clusters

**Status:** Accepted (Arash / Claude; GPT review deferred to repo-level review of ok-cluster + openkubes)
**Date:** 2026-07-06
**Related:** OK-56 (Step 2), ADR-Platform-009 (storage contract, OK-55), ADR-Platform-011 candidate (Capability → Contract → Implementation Profile → Provider Values)

## Context

With OK-56 Step 1, all Talos workload clusters run Cilium as the sole CNI
(`cni: none`, `proxy.disabled: true`, `kubeProxyReplacement=true`). Workloads
such as Open WebUI are currently reached via raw MetalLB LoadBalancer IPs
(e.g. `192.168.100.202:11434` for Ollama). There is no HTTP(S) routing layer:
no hostname-based routing, no TLS termination, no single entry point per
cluster.

Constraints:

- MetalLB pool `ok-pool` (`192.168.100.200–254`) is the only LB mechanism;
  one LoadBalancer IP per cluster ingress is affordable, many are not.
- Clusters are internal-only (WireGuard/vSwitch); no public exposure yet.
- OpenKubes principle: **contracts over components** — the ingress mechanism
  must be swappable without breaking application manifests.

## Decision

### Contract (stable)

1. Every workload cluster MAY expose HTTP(S) workloads through **one**
   ingress entry point: a single `LoadBalancer` Service drawing one IP from
   `ok-pool`.
2. Applications bind to the contract via the standard Kubernetes
   **Ingress API** (`networking.k8s.io/v1`) with
   `ingressClassName: ok-ingress`.
3. Hostname convention: `<app>.<cluster>.internal`
   (e.g. `open-webui.ok1-talos.internal`).
4. TLS is terminated at the ingress entry point. How certificates are
   issued is an implementation-profile concern, not part of the contract.
5. `ok-ingress` is **not** the default IngressClass: applications must set
   `ingressClassName: ok-ingress` explicitly. Contract binding is visible,
   never implicit.
6. LB-IP allocation: the host MetalLB pool `ok-pool` (`.200–.209`) is the
   sole LB mechanism. Each guest cluster gets one IP from this pool via a
   **host-cluster proxy Service** — no MetalLB or LB implementation inside
   guest clusters required.

### Implementation Profile v1: Traefik + Host-Cluster Proxy

Traffic path (discovered 2026-07-07, validated on ok1-talos):

```
client → <host-lb-ip>:80  (MetalLB on RKE2 host cluster)
       → virt-launcher pod:<nodePort>  (KubeVirt VM pod on RKE2)
       → Traefik NodePort in guest cluster
       → Ingress routing → app pod
```

- **Traefik** installed via Helm in guest cluster, `service.type=NodePort`
  (ports 30080/30443). IngressClass `ok-ingress`, not default.
  Namespace `ingress`.
- **Host proxy Service** (`<cluster>-ingress`) created in the cluster
  namespace on RKE2, `type: LoadBalancer`, selector
  `cluster.x-k8s.io/role=worker` — MetalLB assigns one IP from `ok-pool`.
  Routes `:80→30080`, `:443→30443` into the KubeVirt virt-launcher pods.
- Both steps automated via `make install-ingress CLUSTER=<name>` (opt-in,
  not part of `make bootstrap`).
- TLS v1: Traefik default self-signed certificate; cert-manager follow-up
  is a profile change, no ADR amendment.

**Why not Cilium LB-IPAM + L2 Announcements?** CAPK-deployed VMs have a
single `eth0` in the Cilium overlay — no direct vSwitch interface. Cilium
cannot ARP-announce an IP that has no L2 presence on the host network.
The host-proxy pattern reuses the same mechanism as the CAPI-managed
control-plane LB (`<cluster>-lb`) and requires no changes to VM networking.
This is the correct v1 approach; Cilium Gateway API (v2) remains the
migration path once Multus NADs are added to CAPK templates (OK-57).

### Migration Path: Cilium Gateway API (v2, deferred)

- Cilium already runs with `kubeProxyReplacement=true`, the prerequisite for
  Cilium Gateway API — the runway is clear.
- Migration means: enable `gatewayAPI.enabled=true` in the Cilium Helm
  values, introduce `Gateway`/`HTTPRoute` alongside existing `Ingress`
  objects, migrate apps, then retire Traefik.
- The contract evolves (Ingress → Gateway API resources), but hostname and
  single-IP conventions remain unchanged.

## Alternatives Considered

- **ingress-nginx** — rejected. Upstream entered maintenance mode
  (announced Nov 2025) with retirement planned for March 2026; adopting a
  retiring component contradicts the swappability principle. *(Verify
  current upstream status before final acceptance — post knowledge cutoff.)*
- **Cilium Gateway API now** — rejected for v1. Technically attractive
  (zero additional components), but Traefik is already proven in
  capi-platform-v4.2; Gateway API adds a new resource model to debug during
  the same change window as the CNI switch. Sequencing risk, not capability
  doubt. Explicitly scheduled as v2.
- **HAProxy Ingress** — rejected; no existing operational experience in the
  stack, no differentiating advantage over Traefik here.

## Consequences

- Apps depend only on `ingressClassName: ok-ingress` and the hostname
  convention — Traefik is replaceable per the contract principle.
- One IP from `ok-pool` is consumed per cluster with ingress installed
  (pool sizing: 55 IPs, currently ~3 in use — no pressure).
- DNS for `*.<cluster>.internal` must resolve for clients on the WireGuard
  network — operational follow-up (dnsmasq on ok-vpn or /etc/hosts interim);
  out of scope for this ADR.
- `make install-ingress` becomes the third opt-in capability target
  (cni, storage, ingress) — reinforcing the ADR-Platform-011 candidate
  pattern (Capability → Contract → Implementation Profile → Provider
  Values).
