export const PRESENTATION_CONTRACT_VERSION = 'console.openkubes.io/v0alpha1' as const

export type Readiness = 'Ready' | 'Pending' | 'Failed' | 'Unknown'
export type Compatibility = 'Supported' | 'Read only' | 'Incompatible'

export interface EvidenceRef {
  id: string
  title: string
  type: 'Observation' | 'Transition' | 'Authorization'
  outcome: Readiness | 'Approved' | 'Denied'
  cluster: string
  contract: string
  revision: string
  observedAt: string
  source: string
  summary: string
  immutable: boolean
}

export interface Capability {
  id: string
  name: string
  description: string
  implementation: string
  contractVersion: string
  coverage: number
  clusters: number
  readiness: Readiness
  evidenceId: string
}

export interface Cluster {
  id: string
  name: string
  role: 'Management plane' | 'Workload cluster'
  provider: string
  profile: string
  version: string
  region: string
  readiness: Readiness
  compatibility: Compatibility
  contractVersion: string
  revision: string
  evidenceId: string
  capabilities: string[]
  lifecycle: Array<{ label: string; state: Readiness; detail: string }>
}

export interface WorkloadClaim {
  id: string
  name: string
  kind: string
  owner: string
  intent: string
  targetCluster: string
  readiness: Readiness
  requiredCapabilities: string[]
  decision: string
  evidenceId: string
}

export interface PlatformSnapshot {
  generatedAt: string
  presentationVersion: typeof PRESENTATION_CONTRACT_VERSION
  clusters: Cluster[]
  capabilities: Capability[]
  claims: WorkloadClaim[]
  evidence: EvidenceRef[]
}

export interface ConsoleDataPort {
  getSnapshot(): Promise<PlatformSnapshot>
  getCluster(id: string): Promise<Cluster | undefined>
  getEvidence(id: string): Promise<EvidenceRef | undefined>
}
