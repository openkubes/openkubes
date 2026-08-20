import type { PlatformSnapshot } from '../domain/contracts'
import { PRESENTATION_CONTRACT_VERSION } from '../domain/contracts'

export const platformFixture: PlatformSnapshot = {
  generatedAt: '2026-08-20T19:42:00Z',
  presentationVersion: PRESENTATION_CONTRACT_VERSION,
  clusters: [
    {
      id: 'cluster-ok-mgmt', name: 'ok-mgmt', role: 'Management plane', provider: 'Bare metal',
      profile: 'Talos management', version: 'v1.32.6', region: 'fra-dc1', readiness: 'Ready',
      compatibility: 'Supported', contractVersion: 'platform.openkubes.io/v1alpha1', revision: 'rev-7d2a9c',
      evidenceId: 'ev-mgmt-ready', capabilities: ['cap-identity', 'cap-gitops', 'cap-observability', 'cap-registry'],
      lifecycle: [
        { label: 'Declared', state: 'Ready', detail: 'Contract accepted · generation 14' },
        { label: 'Infrastructure', state: 'Ready', detail: '3 control-plane nodes healthy' },
        { label: 'Control plane', state: 'Ready', detail: 'API and controllers observed' },
        { label: 'Capabilities', state: 'Ready', detail: '4 of 4 required contracts conformant' },
      ],
    },
    {
      id: 'cluster-ok-ai', name: 'ok-ai', role: 'Workload cluster', provider: 'KubeVirt',
      profile: 'AI accelerated', version: 'v1.32.6', region: 'fra-gpu1', readiness: 'Ready',
      compatibility: 'Supported', contractVersion: 'platform.openkubes.io/v1alpha1', revision: 'rev-a812ef',
      evidenceId: 'ev-ai-ready', capabilities: ['cap-storage', 'cap-observability', 'cap-ingress'],
      lifecycle: [
        { label: 'Declared', state: 'Ready', detail: 'Contract accepted · generation 8' },
        { label: 'Infrastructure', state: 'Ready', detail: 'GPU worker placement verified' },
        { label: 'Control plane', state: 'Ready', detail: 'Endpoint reachable through management plane' },
        { label: 'Capabilities', state: 'Ready', detail: '3 of 3 required contracts conformant' },
      ],
    },
    {
      id: 'cluster-ok-shared', name: 'ok-shared', role: 'Workload cluster', provider: 'OpenStack',
      profile: 'Shared services', version: 'v1.31.9', region: 'ber-1', readiness: 'Pending',
      compatibility: 'Supported', contractVersion: 'platform.openkubes.io/v1alpha1', revision: 'rev-1c490d',
      evidenceId: 'ev-shared-pending', capabilities: ['cap-identity', 'cap-registry', 'cap-messaging'],
      lifecycle: [
        { label: 'Declared', state: 'Ready', detail: 'Contract accepted · generation 3' },
        { label: 'Infrastructure', state: 'Ready', detail: '5 nodes provisioned' },
        { label: 'Control plane', state: 'Ready', detail: 'API observed' },
        { label: 'Capabilities', state: 'Pending', detail: 'Messaging evidence is still converging' },
      ],
    },
    {
      id: 'cluster-edge-07', name: 'edge-07', role: 'Workload cluster', provider: 'Bare metal',
      profile: 'Constrained edge', version: 'v1.30.12', region: 'factory-07', readiness: 'Unknown',
      compatibility: 'Read only', contractVersion: 'platform.openkubes.io/v1alpha0', revision: 'rev-88e913',
      evidenceId: 'ev-edge-unknown', capabilities: ['cap-storage', 'cap-observability'],
      lifecycle: [
        { label: 'Declared', state: 'Ready', detail: 'Legacy contract recognized' },
        { label: 'Infrastructure', state: 'Ready', detail: '2 edge nodes registered' },
        { label: 'Control plane', state: 'Unknown', detail: 'Observation is older than freshness window' },
        { label: 'Capabilities', state: 'Unknown', detail: 'Read-only compatibility mode' },
      ],
    },
  ],
  capabilities: [
    { id: 'cap-identity', name: 'Identity', description: 'Federated identity and workload authentication', implementation: 'Keycloak', contractVersion: 'identity.openkubes.io/v1alpha1', coverage: 100, clusters: 2, readiness: 'Ready', evidenceId: 'ev-mgmt-ready' },
    { id: 'cap-storage', name: 'Persistent Storage', description: 'Provider-neutral persistent volume classes', implementation: 'Longhorn', contractVersion: 'storage.openkubes.io/v1alpha1', coverage: 75, clusters: 2, readiness: 'Ready', evidenceId: 'ev-ai-ready' },
    { id: 'cap-observability', name: 'Observability', description: 'Metrics, logs, traces, and contract gates', implementation: 'OTel + Prometheus', contractVersion: 'observability.openkubes.io/v1alpha1', coverage: 100, clusters: 3, readiness: 'Ready', evidenceId: 'ev-ai-ready' },
    { id: 'cap-ingress', name: 'Ingress', description: 'Portable application ingress contract', implementation: 'Traefik', contractVersion: 'ingress.openkubes.io/v1alpha1', coverage: 100, clusters: 1, readiness: 'Ready', evidenceId: 'ev-ai-ready' },
    { id: 'cap-registry', name: 'Artifact Registry', description: 'Sovereign OCI artifact distribution', implementation: 'zot', contractVersion: 'registry.openkubes.io/v1alpha1', coverage: 50, clusters: 2, readiness: 'Pending', evidenceId: 'ev-shared-pending' },
    { id: 'cap-messaging', name: 'Messaging', description: 'Broker-neutral pub/sub and streaming', implementation: 'NATS', contractVersion: 'messaging.openkubes.io/v1alpha1', coverage: 40, clusters: 1, readiness: 'Pending', evidenceId: 'ev-shared-pending' },
    { id: 'cap-gitops', name: 'GitOps', description: 'Desired-state delivery and reconciliation', implementation: 'Argo CD', contractVersion: 'gitops.openkubes.io/v1alpha1', coverage: 100, clusters: 1, readiness: 'Ready', evidenceId: 'ev-mgmt-ready' },
  ],
  claims: [
    { id: 'claim-private-ai', name: 'private-ai-workspace', kind: 'OpenWebUIClaim', owner: 'AI Platform Team', intent: 'Sovereign assistant with GPU inference', targetCluster: 'ok-ai', readiness: 'Ready', requiredCapabilities: ['Persistent Storage', 'Ingress', 'Observability'], decision: 'Placed on ok-ai · all required capabilities conform', evidenceId: 'ev-ai-ready' },
    { id: 'claim-event-bus', name: 'factory-event-bus', kind: 'MessagingClaim', owner: 'Edge Operations', intent: 'Durable factory event streaming', targetCluster: 'ok-shared', readiness: 'Pending', requiredCapabilities: ['Messaging', 'Observability'], decision: 'Placed on ok-shared · awaiting messaging receipt', evidenceId: 'ev-shared-pending' },
    { id: 'claim-registry', name: 'sovereign-registry', kind: 'ArtifactRegistryClaim', owner: 'Platform Engineering', intent: 'Internal OCI mirror for air-gapped sites', targetCluster: 'ok-shared', readiness: 'Pending', requiredCapabilities: ['Artifact Registry', 'Persistent Storage'], decision: 'Placement accepted · storage conformance pending', evidenceId: 'ev-shared-pending' },
  ],
  evidence: [
    { id: 'ev-mgmt-ready', title: 'Management plane readiness receipt', type: 'Transition', outcome: 'Ready', cluster: 'ok-mgmt', contract: 'OpenKubesCluster/v1alpha1', revision: 'sha256:71d4…9ab2', observedAt: '2026-08-20T19:41:22Z', source: 'ok-mgmt observer', summary: 'All management-plane invariants are satisfied for generation 14.', immutable: true },
    { id: 'ev-ai-ready', title: 'AI cluster capability conformance', type: 'Observation', outcome: 'Ready', cluster: 'ok-ai', contract: 'CapabilitySet/v1alpha1', revision: 'sha256:e503…14cf', observedAt: '2026-08-20T19:39:08Z', source: 'capability observer', summary: 'Storage, ingress, and observability contracts are currently conformant.', immutable: false },
    { id: 'ev-shared-pending', title: 'Shared services convergence', type: 'Observation', outcome: 'Pending', cluster: 'ok-shared', contract: 'CapabilitySet/v1alpha1', revision: 'sha256:103a…81de', observedAt: '2026-08-20T19:38:51Z', source: 'capability observer', summary: 'Messaging endpoint evidence has not entered the required freshness window.', immutable: false },
    { id: 'ev-edge-unknown', title: 'Edge observation freshness exceeded', type: 'Observation', outcome: 'Unknown', cluster: 'edge-07', contract: 'OpenKubesCluster/v1alpha0', revision: 'sha256:c11a…067f', observedAt: '2026-08-20T15:03:17Z', source: 'edge observer', summary: 'Last observation is outside the contract freshness window; no failure is inferred.', immutable: false },
    { id: 'ev-auth-32', title: 'CreateCluster authorization grant', type: 'Authorization', outcome: 'Approved', cluster: 'ok-ai', contract: 'CreateCluster/v1alpha1', revision: 'grant:single-use:32', observedAt: '2026-08-18T08:13:04Z', source: 'platform authority', summary: 'Single-use execution grant consumed for the reviewed payload digest.', immutable: true },
    { id: 'ev-auth-denied', title: 'Profile change denied', type: 'Authorization', outcome: 'Denied', cluster: 'edge-07', contract: 'ChangeClusterProfile/v1alpha1', revision: 'decision:policy:712', observedAt: '2026-08-19T12:31:44Z', source: 'platform policy', summary: 'Change denied because current evidence was outside the required freshness window.', immutable: true },
  ],
}
