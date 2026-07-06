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
6. LB-IP allocation: the host MetalLB pool `ok-pool` is shrunk to
   `.200–.209`; each guest cluster owns a disjoint 5-IP block from `.210`
   upward (`lbPool` in cluster-config.yaml — ok1-talos `.210–.214`,
   ok-mgmt `.215–.219`). The guest-cluster LB implementation (v1: Cilium
   LB-IPAM + L2 announcements) assigns Service IPs exclusively from its
   block — no MetalLB inside guest clusters.

### Implementation Profile v1: Traefik

- Installed via Helm through `make install-ingress CLUSTER=<name>`
  (opt-in, analogous to `make install-storage` — **not** part of
  `make bootstrap`; ingress is an application-layer capability, not a
  cluster-lifecycle requirement).
- IngressClass `ok-ingress` → Traefik controller; Traefik values proven in
  capi-platform-v4.2 are the baseline.
- Namespace `ingress`, one `LoadBalancer` Service, MetalLB assigns the IP.
- TLS v1: Traefik default self-signed certificate; cert-manager with a
  cluster-local CA is a follow-up (profile change, no ADR amendment).

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
