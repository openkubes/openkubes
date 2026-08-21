import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { consoleData } from './data/fixtureAdapter'
import type { Capability, Cluster, EvidenceRef, PlatformSnapshot, Readiness, WorkloadClaim } from './domain/contracts'

type Page = 'overview' | 'clusters' | 'workloads' | 'capabilities' | 'evidence' | 'create'
type IconName = Page | 'search' | 'bell' | 'chevron' | 'shield' | 'cube' | 'arrow' | 'menu' | 'x' | 'check' | 'clock' | 'external' | 'code' | 'terminal' | 'spark'

const NAV: Array<{ id: Page; label: string; caption: string }> = [
  { id: 'overview', label: 'Platform Overview', caption: 'Fleet & posture' },
  { id: 'clusters', label: 'Clusters', caption: 'Lifecycle contracts' },
  { id: 'workloads', label: 'Workloads', caption: 'Claims & placement' },
  { id: 'capabilities', label: 'Capabilities', caption: 'Contract catalog' },
  { id: 'evidence', label: 'Evidence & Audit', caption: 'Receipts & provenance' },
]

const pageFromHash = (): Page => {
  const value = window.location.hash.replace('#/', '').split('/')[0] as Page
  return [...NAV.map((item) => item.id), 'create'].includes(value) ? value : 'overview'
}

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
    clusters: <><path d="m12 3 8 4.5-8 4.5-8-4.5L12 3Z"/><path d="m4 12 8 4.5 8-4.5"/><path d="m4 16.5 8 4.5 8-4.5"/></>,
    workloads: <><path d="M4 5h16v14H4z"/><path d="M4 9h16M8 3v4M16 3v4"/></>,
    capabilities: <><path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3m13 5h3a2 2 0 0 0 2-2v-3"/><circle cx="12" cy="12" r="4"/></>,
    evidence: <><path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13l2 2 4-5"/></>,
    create: <><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    shield: <><path d="M12 3 20 6v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3Z"/><path d="m9 12 2 2 4-5"/></>,
    cube: <><path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 7 9 5v10l-9-5V7Zm18 0-9 5v10l9-5V7Z"/></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
    x: <path d="m6 6 12 12M18 6 6 18"/>,
    check: <path d="m5 12 4 4L19 6"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    external: <><path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6H5V6h6"/></>,
    code: <><path d="m8 9-4 3 4 3m8-6 4 3-4 3m-2-9-4 12"/></>,
    terminal: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3m6 0h4"/></>,
    spark: <><path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4L12 3Z"/><path d="m18 15 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z"/></>,
  }
  return <svg aria-hidden="true" className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>
}

function StatusBadge({ status }: { status: Readiness | 'Approved' | 'Denied' | 'Supported' | 'Read only' | 'Incompatible' }) {
  const icon = status === 'Ready' || status === 'Approved' || status === 'Supported' ? 'check' : status === 'Pending' ? 'clock' : 'x'
  return <span className={`status status-${status.toLowerCase().replace(' ', '-')}`}><Icon name={icon} size={13}/>{status}</span>
}

function Metric({ label, value, note, tone = 'blue' }: { label: string; value: string | number; note: string; tone?: string }) {
  return <article className={`metric metric-${tone}`}><div className="metric-top"><span>{label}</span><span className="metric-mark"/></div><strong>{value}</strong><small>{note}</small></article>
}

function PageTitle({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <header className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</header>
}

function EvidenceLink({ id, evidence, onSelect }: { id: string; evidence: EvidenceRef[]; onSelect: (item: EvidenceRef) => void }) {
  const item = evidence.find((entry) => entry.id === id)
  if (!item) return null
  return <button className="evidence-link" onClick={() => onSelect(item)}><Icon name="evidence" size={15}/>{item.revision}<Icon name="chevron" size={14}/></button>
}

function EmptyLoading() {
  return <main className="loading"><img src="./openkubes-icon.png" alt=""/><p>Loading contract-aligned platform view…</p></main>
}

function Overview({ data, openCluster, openEvidence }: { data: PlatformSnapshot; openCluster: (c: Cluster) => void; openEvidence: (e: EvidenceRef) => void }) {
  const ready = data.clusters.filter((cluster) => cluster.readiness === 'Ready').length
  return <>
    <PageTitle eyebrow="Platform posture" title="Good evening, Arash." description="One evidence-backed view across your sovereign OpenKubes platforms." action={<span className="snapshot"><span className="live-dot"/>Fixture snapshot · {new Date(data.generatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}/>
    <section className="metrics-grid" aria-label="Platform metrics">
      <Metric label="Clusters" value={data.clusters.length} note={`${ready} ready · 1 management plane`} tone="blue"/>
      <Metric label="Capabilities" value={data.capabilities.length} note="5 conformant · 2 converging" tone="green"/>
      <Metric label="Workload claims" value={data.claims.length} note="1 ready · 2 in progress" tone="orange"/>
      <Metric label="Open findings" value="2" note="No critical policy violations" tone="red"/>
    </section>
    <section className="section-block">
      <div className="section-heading"><div><span className="eyebrow">Fleet</span><h2>Cluster posture</h2></div><button className="text-button" onClick={() => window.location.hash = '#/clusters'}>View all clusters <Icon name="arrow" size={16}/></button></div>
      <div className="cluster-grid">
        {data.clusters.slice(0, 3).map((cluster, index) => <article key={cluster.id} className={`cluster-card ${index === 0 ? 'management' : ''}`}>
          {index === 0 && <div className="management-ribbon"><Icon name="shield" size={13}/> Management plane</div>}
          <button className="card-main" onClick={() => openCluster(cluster)}>
            <div className="cluster-card-head"><div className="cluster-symbol"><Icon name="cube" size={21}/></div><StatusBadge status={cluster.readiness}/></div>
            <h3>{cluster.name}</h3><p>{cluster.profile}</p>
            <dl className="mini-spec"><div><dt>Provider</dt><dd>{cluster.provider}</dd></div><div><dt>Region</dt><dd>{cluster.region}</dd></div><div><dt>Version</dt><dd>{cluster.version}</dd></div></dl>
          </button>
          <footer><span>{cluster.capabilities.length} capabilities</span><EvidenceLink id={cluster.evidenceId} evidence={data.evidence} onSelect={openEvidence}/></footer>
        </article>)}
      </div>
    </section>
    <section className="two-column section-block">
      <article className="panel"><div className="panel-title"><div><span className="eyebrow">Claims</span><h2>Recent placements</h2></div><span className="count-badge">{data.claims.length}</span></div>{data.claims.map((claim) => <button className="activity-row" key={claim.id} onClick={() => window.location.hash = '#/workloads'}><span className="activity-icon"><Icon name="workloads" size={17}/></span><span className="activity-copy"><strong>{claim.name}</strong><small>{claim.owner} → {claim.targetCluster}</small></span><StatusBadge status={claim.readiness}/><Icon name="chevron" size={16}/></button>)}</article>
      <article className="panel trust-panel"><div className="panel-title"><div><span className="eyebrow">Trust model</span><h2>Why is the platform ready?</h2></div><Icon name="shield" size={22}/></div><p>Every status shown here resolves to a contract revision, current observation, or immutable receipt.</p><div className="trust-chain"><span>Intent</span><i/><span>Observed</span><i/><span>Evidence</span></div><button className="secondary-button" onClick={() => window.location.hash = '#/evidence'}>Explore evidence chain <Icon name="arrow" size={16}/></button></article>
    </section>
  </>
}

function Clusters({ data, openCluster, openEvidence }: { data: PlatformSnapshot; openCluster: (c: Cluster) => void; openEvidence: (e: EvidenceRef) => void }) {
  return <>
    <PageTitle eyebrow="Contract inventory" title="Clusters" description="Lifecycle posture without the Kubernetes object noise." action={<button className="primary-button" onClick={() => window.location.hash = '#/create'}><Icon name="create"/>Create Cluster</button>}/>
    <div className="filter-bar"><label className="search-field"><Icon name="search"/><span className="sr-only">Search clusters</span><input placeholder="Search clusters"/></label><button className="filter-chip active">All · {data.clusters.length}</button><button className="filter-chip">Ready · 2</button><button className="filter-chip">Attention · 2</button></div>
    <section className="table-panel">
      <div className="table-head cluster-columns"><span>Cluster</span><span>Role & profile</span><span>Provider</span><span>Readiness</span><span>Evidence</span><span/></div>
      {data.clusters.map((cluster, index) => <div className={`table-row cluster-columns ${index === 0 ? 'management-row' : ''}`} key={cluster.id}>
        <button className="cluster-name-cell" onClick={() => openCluster(cluster)}><span className="cluster-symbol small"><Icon name={index === 0 ? 'shield' : 'cube'} size={18}/></span><span><strong>{cluster.name}</strong><small>{cluster.version} · {cluster.region}</small></span></button>
        <span><strong>{cluster.role}</strong><small>{cluster.profile}</small></span><span>{cluster.provider}</span><span><StatusBadge status={cluster.readiness}/></span><EvidenceLink id={cluster.evidenceId} evidence={data.evidence} onSelect={openEvidence}/><button className="icon-button" aria-label={`Open ${cluster.name}`} onClick={() => openCluster(cluster)}><Icon name="chevron"/></button>
      </div>)}
    </section>
  </>
}

function ClusterDetail({ cluster, data, close, openEvidence, openShell }: { cluster: Cluster; data: PlatformSnapshot; close: () => void; openEvidence: (e: EvidenceRef) => void; openShell: (cluster: Cluster) => void }) {
  const [tab, setTab] = useState('Overview')
  const clusterCapabilities = data.capabilities.filter((capability) => cluster.capabilities.includes(capability.id))
  return <>
    <button className="back-button" onClick={close}>← All clusters</button>
    <PageTitle eyebrow={cluster.role} title={cluster.name} description={`${cluster.profile} · ${cluster.provider} · ${cluster.region}`} action={<div className="title-actions"><StatusBadge status={cluster.readiness}/><button className="shell-button" onClick={() => openShell(cluster)}><Icon name="terminal"/>Open Shell</button><button className="secondary-button">Propose change</button></div>}/>
    <div className="contract-strip"><div><span>Domain contract</span><strong>{cluster.contractVersion}</strong></div><div><span>Observed revision</span><strong>{cluster.revision}</strong></div><div><span>Console compatibility</span><StatusBadge status={cluster.compatibility}/></div></div>
    <div className="tabs" role="tablist">{['Overview', 'Lifecycle', 'Capabilities', 'Evidence', 'Changes'].map((item) => <button key={item} role="tab" aria-selected={tab === item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item}</button>)}</div>
    {tab === 'Overview' && <section className="detail-grid"><article className="panel"><div className="panel-title"><div><span className="eyebrow">Current observation</span><h2>Lifecycle posture</h2></div><span className="live-label"><span className="live-dot"/>Observed</span></div><div className="lifecycle">{cluster.lifecycle.map((step, index) => <div className="lifecycle-step" key={step.label}><div className={`step-dot ${step.state.toLowerCase()}`}>{step.state === 'Ready' ? '✓' : index + 1}</div><div><strong>{step.label}</strong><p>{step.detail}</p></div><StatusBadge status={step.state}/></div>)}</div></article><article className="panel"><div className="panel-title"><div><span className="eyebrow">Evidence</span><h2>Readiness basis</h2></div><Icon name="evidence"/></div>{data.evidence.filter((item) => item.cluster === cluster.name).map((item) => <button className="evidence-card" key={item.id} onClick={() => openEvidence(item)}><div><span>{item.type}</span><StatusBadge status={item.outcome}/></div><strong>{item.title}</strong><p>{item.summary}</p><small>{item.revision} · {new Date(item.observedAt).toLocaleString()}</small></button>)}</article></section>}
    {tab === 'Lifecycle' && <article className="panel wide-panel"><div className="panel-title"><div><span className="eyebrow">Intent → observation</span><h2>Lifecycle contract</h2></div></div><div className="timeline">{cluster.lifecycle.map((step) => <div key={step.label}><span className={`timeline-marker ${step.state.toLowerCase()}`}/><h3>{step.label}</h3><p>{step.detail}</p><StatusBadge status={step.state}/></div>)}</div></article>}
    {tab === 'Capabilities' && <CapabilityGrid capabilities={clusterCapabilities} data={data} openEvidence={openEvidence}/>} 
    {tab === 'Evidence' && <EvidenceList evidence={data.evidence.filter((item) => item.cluster === cluster.name)} onSelect={openEvidence}/>} 
    {tab === 'Changes' && <article className="empty-state panel"><Icon name="code" size={32}/><h2>No pending changes</h2><p>Changes remain proposals until review, authorization, and execution are independently recorded.</p><button className="secondary-button">Propose change</button></article>}
  </>
}

function Workloads({ claims, data, openEvidence }: { claims: WorkloadClaim[]; data: PlatformSnapshot; openEvidence: (e: EvidenceRef) => void }) {
  return <><PageTitle eyebrow="Intent & placement" title="Workloads" description="Follow each claim from team intent to capability fit and evidence."/><section className="claims-grid">{claims.map((claim) => <article className="claim-card" key={claim.id}><div className="claim-head"><span className="claim-kind">{claim.kind}</span><StatusBadge status={claim.readiness}/></div><h2>{claim.name}</h2><p>{claim.intent}</p><div className="placement-flow"><div><span>Owner</span><strong>{claim.owner}</strong></div><Icon name="arrow"/><div><span>Placed on</span><strong>{claim.targetCluster}</strong></div></div><div className="cap-tags">{claim.requiredCapabilities.map((item) => <span key={item}><Icon name="check" size={12}/>{item}</span>)}</div><div className="decision"><Icon name="shield"/><div><span>Placement decision</span><strong>{claim.decision}</strong></div></div><EvidenceLink id={claim.evidenceId} evidence={data.evidence} onSelect={openEvidence}/></article>)}</section></>
}

function CapabilityGrid({ capabilities, data, openEvidence }: { capabilities: Capability[]; data: PlatformSnapshot; openEvidence: (e: EvidenceRef) => void }) {
  return <section className="capability-grid">{capabilities.map((capability) => <article className="capability-card" key={capability.id}><div className="capability-head"><span className="capability-icon"><Icon name="capabilities"/></span><StatusBadge status={capability.readiness}/></div><h2>{capability.name}</h2><p>{capability.description}</p><dl><div><dt>Implementation</dt><dd>{capability.implementation}</dd></div><div><dt>Contract</dt><dd>{capability.contractVersion}</dd></div><div><dt>Cluster coverage</dt><dd>{capability.clusters} clusters</dd></div></dl><div className="coverage"><span style={{ width: `${capability.coverage}%` }}/></div><footer><span>{capability.coverage}% profile coverage</span><EvidenceLink id={capability.evidenceId} evidence={data.evidence} onSelect={openEvidence}/></footer></article>)}</section>
}

function Capabilities({ data, openEvidence }: { data: PlatformSnapshot; openEvidence: (e: EvidenceRef) => void }) {
  return <><PageTitle eyebrow="Global catalog" title="Capabilities" description="Contracts first. Implementations remain replaceable and provider-neutral."/><CapabilityGrid capabilities={data.capabilities} data={data} openEvidence={openEvidence}/></>
}

function EvidenceList({ evidence, onSelect }: { evidence: EvidenceRef[]; onSelect: (e: EvidenceRef) => void }) {
  return <section className="evidence-list">{evidence.map((item) => <button className="evidence-row" onClick={() => onSelect(item)} key={item.id}><span className={`evidence-type type-${item.type.toLowerCase()}`}><Icon name={item.type === 'Authorization' ? 'shield' : 'evidence'}/>{item.type}</span><span><strong>{item.title}</strong><small>{item.cluster} · {item.contract}</small></span><StatusBadge status={item.outcome}/><span className="revision">{item.revision}</span><span><strong>{new Date(item.observedAt).toLocaleDateString()}</strong><small>{new Date(item.observedAt).toLocaleTimeString()}</small></span><Icon name="chevron"/></button>)}</section>
}

function Evidence({ data, openEvidence }: { data: PlatformSnapshot; openEvidence: (e: EvidenceRef) => void }) {
  const [filter, setFilter] = useState<'All' | EvidenceRef['type']>('All')
  const items = filter === 'All' ? data.evidence : data.evidence.filter((item) => item.type === filter)
  return <><PageTitle eyebrow="Trust & provenance" title="Evidence & Audit" description="Current observations, immutable outcomes, and authority decisions remain distinct."/><div className="evidence-explainer"><div><span className="legend observation"/><strong>Observation</strong><small>Current, freshness-bound state</small></div><div><span className="legend transition"/><strong>Transition</strong><small>Immutable historical outcome</small></div><div><span className="legend authorization"/><strong>Authorization</strong><small>Explicit authority decision</small></div></div><div className="filter-bar">{(['All', 'Observation', 'Transition', 'Authorization'] as const).map((item) => <button className={`filter-chip ${filter === item ? 'active' : ''}`} onClick={() => setFilter(item)} key={item}>{item}</button>)}</div><EvidenceList evidence={items} onSelect={openEvidence}/></>
}

const createSteps = ['Draft', 'Review', 'Authorize', 'Execute', 'Evidence'] as const

function CreateCluster() {
  const [step, setStep] = useState(0)
  const [name, setName] = useState('ok-edge-berlin')
  const [provider, setProvider] = useState('Bare metal')
  const [profile, setProfile] = useState('Constrained edge')
  const [confirmed, setConfirmed] = useState(false)
  const contract = `apiVersion: platform.openkubes.io/v1alpha1\nkind: OpenKubesCluster\nmetadata:\n  name: ${name || 'cluster-name'}\nspec:\n  role: workload\n  implementationProfile:\n    provider: ${provider.toLowerCase().replace(' ', '-')}\n    profile: ${profile.toLowerCase().replace(' ', '-')}\n  capabilities:\n    required:\n      - observability\n      - persistent-storage`
  const next = () => setStep((current) => Math.min(current + 1, createSteps.length - 1))
  return <>
    <PageTitle eyebrow="Prototype journey" title="Create Cluster" description="A safe preview of the complete contract-governed flow. No backend mutation is possible." action={<span className="prototype-badge">Prototype · no-op</span>}/>
    <ol className="stepper">{createSteps.map((item, index) => <li className={index === step ? 'active' : index < step ? 'done' : ''} key={item}><span>{index < step ? '✓' : index + 1}</span><strong>{item}</strong></li>)}</ol>
    <div className="create-layout">
      <section className="panel create-main">
        {step === 0 && <><div className="panel-title"><div><span className="eyebrow">Step 1</span><h2>Declare cluster intent</h2></div></div><div className="form-grid"><label><span>Cluster name</span><input value={name} onChange={(event) => setName(event.target.value)}/><small>Lowercase DNS-compatible identity</small></label><label><span>Provider</span><select value={provider} onChange={(event) => setProvider(event.target.value)}><option>Bare metal</option><option>KubeVirt</option><option>OpenStack</option><option>Cloud</option></select><small>An implementation detail below the contract</small></label><label><span>Implementation profile</span><select value={profile} onChange={(event) => setProfile(event.target.value)}><option>Constrained edge</option><option>General purpose</option><option>AI accelerated</option><option>Shared services</option></select></label><label><span>Region / placement</span><input defaultValue="ber-edge-1"/></label></div><fieldset><legend>Required capabilities</legend><div className="check-grid"><label><input type="checkbox" defaultChecked/>Observability</label><label><input type="checkbox" defaultChecked/>Persistent Storage</label><label><input type="checkbox"/>Ingress</label><label><input type="checkbox"/>Artifact Registry</label></div></fieldset></>}
        {step === 1 && <><div className="panel-title"><div><span className="eyebrow">Step 2</span><h2>Review generated contract</h2></div><span className="digest">sha256:preview…7a21</span></div><div className="review-summary"><div><span>Requested identity</span><strong>{name}</strong></div><div><span>Profile</span><strong>{profile}</strong></div><div><span>Provider</span><strong>{provider}</strong></div></div><pre className="contract-preview"><code>{contract}</code></pre><div className="no-go"><Icon name="shield"/><div><strong>NO-GO checks</strong><p>Execution remains unavailable if identity, placement, capability prerequisites, policy, or evidence freshness cannot be proven.</p></div></div></>}
        {step === 2 && <><div className="authority-card"><div className="authority-icon"><Icon name="shield" size={32}/></div><span className="eyebrow">Step 3 · Authority boundary</span><h2>Authorize this exact review artifact</h2><p>This prototype illustrates a single-use grant bound to the reviewed payload digest. The browser is never the security boundary.</p><dl><div><dt>Operation</dt><dd>CreateCluster</dd></div><div><dt>Payload digest</dt><dd>sha256:preview…7a21</dd></div><div><dt>Grant</dt><dd>Single use · 10 minutes</dd></div></dl><label className="confirm-box"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)}/><span>I confirm that I reviewed the exact contract above.</span></label></div></>}
        {step === 3 && <><div className="execution-preview"><span className="pulse-ring"><Icon name="code" size={28}/></span><span className="eyebrow">Step 4</span><h2>Execution preview</h2><p>A production Console would now call the authoritative Contract Executor with the reviewed digest and single-use grant.</p><div className="boundary-stack"><div className="done"><Icon name="check"/><span><strong>Review artifact bound</strong><small>Digest and generation recorded</small></span></div><div className="done"><Icon name="check"/><span><strong>Authorization evaluated</strong><small>Exact operation and actor scope</small></span></div><div><Icon name="clock"/><span><strong>Contract Executor</strong><small>Deliberately disabled in this prototype</small></span></div></div><div className="prototype-warning"><strong>No request was sent.</strong> This screen does not connect to a backend or cluster.</div></div></>}
        {step === 4 && <><div className="success-state"><span><Icon name="check" size={32}/></span><div className="eyebrow">Step 5</div><h2>Evidence shape validated</h2><p>The prototype journey is complete. A production execution would create immutable transition evidence and current observations, correlated to this request.</p><div className="mock-receipt"><div><span>Result</span><StatusBadge status="Ready"/></div><div><span>Correlation</span><strong>create/{name}/generation-1</strong></div><div><span>Receipt</span><strong>prototype-only · not authoritative</strong></div></div></div></>}
        <footer className="form-actions"><button className="secondary-button" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</button>{step < 4 ? <button className="primary-button" disabled={step === 2 && !confirmed} onClick={next}>{step === 0 ? 'Generate contract' : step === 1 ? 'Continue to authorization' : step === 2 ? 'Authorize prototype' : 'Simulate evidence'}<Icon name="arrow"/></button> : <button className="primary-button" onClick={() => { setStep(0); setConfirmed(false) }}>Start another draft</button>}</footer>
      </section>
      <aside className="panel guardrail-panel"><span className="eyebrow">Guardrails</span><h2>What this UI guarantees</h2><ul><li><Icon name="check"/>Intent stays distinct from state.</li><li><Icon name="check"/>Review precedes authorization.</li><li><Icon name="check"/>Grant binds to exact payload.</li><li><Icon name="check"/>Evidence does not invent readiness.</li><li><Icon name="check"/>Unknown compatibility fails closed.</li></ul><div className="contract-meta"><span>Presentation mapping</span><strong>console.openkubes.io/v0alpha1</strong><span>Supported domain contract</span><strong>platform.openkubes.io/v1alpha1</strong></div></aside>
    </div>
  </>
}

type ShellEntry = {
  kind: 'system' | 'command' | 'output' | 'blocked' | 'ai' | 'proposal'
  content: string
}

const MUTATING_COMMAND = /\b(apply|create|delete|edit|patch|replace|scale|cordon|drain|uncordon|exec|rollout\s+restart|set\s+image)\b/i

function simulatedShellResponse(command: string, cluster: Cluster): ShellEntry[] {
  const normalized = command.trim().toLowerCase()
  if (MUTATING_COMMAND.test(normalized)) {
    return [{ kind: 'blocked', content: 'BLOCKED · This read-only prototype cannot invoke a mutating operation. A production request would enter Review → Authorization → Execution.' }]
  }
  if (normalized.includes('why') || normalized.includes('explain') || normalized.includes('pending')) {
    const pending = cluster.lifecycle.find((item) => item.state !== 'Ready')
    const explanation = pending
      ? `${cluster.name} is ${cluster.readiness.toLowerCase()} because ${pending.label.toLowerCase()} reports: ${pending.detail}. This is an explanation of fixture evidence, not a new readiness decision.`
      : `${cluster.name} currently reports Ready across all required lifecycle checks. The explanation resolves to the observed contract revision and does not infer state from Kubernetes objects.`
    return [
      { kind: 'ai', content: explanation },
      { kind: 'proposal', content: `Suggested read-only command · kubectl get clusterconditions -o wide` },
    ]
  }
  if (normalized === 'help') {
    return [{ kind: 'output', content: 'Allowed examples:\n  kubectl get nodes\n  kubectl get namespaces\n  kubectl get clusterconditions -o wide\n  ok evidence explain\n  why is this cluster pending?' }]
  }
  if (normalized.includes('get nodes')) {
    return [{ kind: 'output', content: `NAME                    STATUS   ROLE           VERSION\n${cluster.name}-cp-01     Ready    control-plane  ${cluster.version}\n${cluster.name}-worker-01 Ready    worker         ${cluster.version}` }]
  }
  if (normalized.includes('get namespaces')) {
    return [{ kind: 'output', content: 'NAME                  STATUS\ndefault               Active\nkube-system           Active\nopenkubes-system      Active\nobservability         Active' }]
  }
  if (normalized.includes('clusterconditions')) {
    return [{ kind: 'output', content: cluster.lifecycle.map((item) => `${item.label.padEnd(18)} ${item.state.padEnd(8)} ${item.detail}`).join('\n') }]
  }
  if (normalized.includes('evidence')) {
    return [{ kind: 'output', content: `EVIDENCE     ${cluster.evidenceId}\nCONTRACT     ${cluster.contractVersion}\nREVISION     ${cluster.revision}\nREADINESS    ${cluster.readiness}\nSOURCE       deterministic prototype fixture` }]
  }
  return [{ kind: 'blocked', content: 'UNKNOWN · This command is not in the prototype read-only allowlist. Type “help” to see supported diagnostics.' }]
}

function ClusterShell({ cluster, close }: { cluster: Cluster; close: () => void }) {
  const [namespace, setNamespace] = useState('all namespaces')
  const [command, setCommand] = useState('')
  const [entries, setEntries] = useState<ShellEntry[]>([
    { kind: 'system', content: `Read-only prototype session established for ${cluster.name}. No credential, kubeconfig, WebSocket, or backend connection was created.` },
  ])

  const run = (value = command) => {
    const nextCommand = value.trim()
    if (!nextCommand) return
    if (nextCommand === 'clear') {
      setEntries([])
      setCommand('')
      return
    }
    setEntries((current) => [...current, { kind: 'command', content: nextCommand }, ...simulatedShellResponse(nextCommand, cluster)])
    setCommand('')
  }

  return <div className="shell-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}>
    <section className="cluster-shell" role="dialog" aria-modal="true" aria-labelledby="shell-title">
      <header className="shell-header">
        <div className="shell-identity"><span className="shell-logo"><Icon name="terminal" size={22}/></span><div><span className="eyebrow">Cluster diagnostic session</span><h2 id="shell-title">Shell · {cluster.name}</h2></div></div>
        <div className="shell-session"><span className="live-dot"/><span><small>Read-only prototype</small><strong>14:37 remaining</strong></span></div>
        <button className="shell-close" onClick={close} aria-label="Close cluster shell"><Icon name="x"/></button>
      </header>
      <div className="shell-context">
        <div><span>Cluster</span><strong><Icon name={cluster.role === 'Management plane' ? 'shield' : 'cube'} size={14}/>{cluster.name}</strong></div>
        <label><span>Namespace</span><select aria-label="Shell namespace" value={namespace} onChange={(event) => setNamespace(event.target.value)}><option>all namespaces</option><option>openkubes-system</option><option>kube-system</option><option>observability</option></select></label>
        <div><span>Authority</span><strong>diagnostics.read</strong></div>
        <div><span>Session evidence</span><strong>shell/{cluster.name}/demo-01</strong></div>
      </div>
      {cluster.role === 'Management plane' && <div className="management-warning"><Icon name="shield"/><strong>Management Plane guardrail</strong><span>This session has the strictest diagnostic-only policy. Mutations and interactive exec are unavailable.</span></div>}
      <div className="shell-toolbar"><span>Try a safe diagnostic</span><div>{['kubectl get nodes', 'kubectl get clusterconditions -o wide', 'ok evidence explain'].map((item) => <button key={item} onClick={() => run(item)}>{item}</button>)}</div></div>
      <div className="terminal-output" role="log" aria-live="polite">
        {entries.map((entry, index) => <div className={`terminal-entry terminal-${entry.kind}`} key={`${entry.kind}-${index}`}>
          {entry.kind === 'command' && <span className="terminal-prompt">{cluster.name}<i>:</i>{namespace === 'all namespaces' ? '*' : namespace}<b>$</b></span>}
          {entry.kind === 'ai' && <span className="entry-label"><Icon name="spark" size={14}/>AI explanation</span>}
          {entry.kind === 'proposal' && <span className="entry-label"><Icon name="shield" size={14}/>Reviewable proposal</span>}
          {entry.kind === 'blocked' && <span className="entry-label"><Icon name="x" size={14}/>Guardrail</span>}
          {entry.kind === 'system' && <span className="entry-label"><Icon name="check" size={14}/>Session boundary</span>}
          <pre>{entry.content}</pre>
          {entry.kind === 'proposal' && <button onClick={() => run('kubectl get clusterconditions -o wide')}>Run proposed read-only command <Icon name="arrow" size={14}/></button>}
        </div>)}
      </div>
      <form className="terminal-command" onSubmit={(event) => { event.preventDefault(); run() }}>
        <label className="sr-only" htmlFor="cluster-shell-command">Command or question</label>
        <span><strong>{cluster.name}</strong>:{namespace === 'all namespaces' ? '*' : namespace}$</span>
        <input id="cluster-shell-command" autoFocus value={command} onChange={(event) => setCommand(event.target.value)} placeholder="Type a read-only command or ask why…" autoComplete="off"/>
        <button type="submit">Run <Icon name="arrow" size={15}/></button>
      </form>
      <footer className="shell-footer"><span><Icon name="shield" size={13}/>No live connection · no credentials · no mutation</span><span>Commands and explanations would be evidence-correlated in production.</span></footer>
    </section>
  </div>
}

function EvidenceDrawer({ item, close }: { item: EvidenceRef; close: () => void }) {
  return <div className="drawer-layer" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && close()}><aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-title"><header><div><span className="eyebrow">{item.type}</span><h2 id="evidence-title">{item.title}</h2></div><button className="icon-button" onClick={close} aria-label="Close evidence"><Icon name="x"/></button></header><StatusBadge status={item.outcome}/><p className="drawer-summary">{item.summary}</p><dl className="evidence-details"><div><dt>Cluster</dt><dd>{item.cluster}</dd></div><div><dt>Contract</dt><dd>{item.contract}</dd></div><div><dt>Revision / digest</dt><dd>{item.revision}</dd></div><div><dt>Source</dt><dd>{item.source}</dd></div><div><dt>Observed at</dt><dd>{new Date(item.observedAt).toLocaleString()}</dd></div><div><dt>Durability</dt><dd>{item.immutable ? 'Immutable receipt' : 'Current, freshness-bound observation'}</dd></div></dl><div className="provenance-box"><Icon name="shield"/><div><strong>Provenance visible</strong><p>This projection is redaction-safe fixture data. It does not expose credentials, kubeconfigs, or raw private evidence.</p></div></div><button className="secondary-button full-button" onClick={close}>Close</button></aside></div>
}

export default function App() {
  const [data, setData] = useState<PlatformSnapshot>()
  const [page, setPage] = useState<Page>(pageFromHash)
  const [selectedCluster, setSelectedCluster] = useState<Cluster>()
  const [shellCluster, setShellCluster] = useState<Cluster>()
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRef>()
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => { consoleData.getSnapshot().then(setData) }, [])
  useEffect(() => {
    const onHash = () => {
      setPage(pageFromHash())
      setSelectedCluster(undefined)
      setShellCluster(undefined)
      setMenuOpen(false)
      window.scrollTo({ top: 0, behavior: 'auto' })
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && (setSelectedEvidence(undefined), setShellCluster(undefined), setMenuOpen(false))
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const title = useMemo(() => selectedCluster?.name ?? (page === 'create' ? 'Create Cluster' : NAV.find((item) => item.id === page)?.label), [page, selectedCluster])
  useEffect(() => { document.title = `${title} · OpenKubes Console` }, [title])

  if (!data) return <EmptyLoading/>
  const view = selectedCluster ? <ClusterDetail cluster={selectedCluster} data={data} close={() => setSelectedCluster(undefined)} openEvidence={setSelectedEvidence} openShell={(cluster) => { setSelectedEvidence(undefined); setShellCluster(cluster) }}/> : page === 'overview' ? <Overview data={data} openCluster={setSelectedCluster} openEvidence={setSelectedEvidence}/> : page === 'clusters' ? <Clusters data={data} openCluster={setSelectedCluster} openEvidence={setSelectedEvidence}/> : page === 'workloads' ? <Workloads claims={data.claims} data={data} openEvidence={setSelectedEvidence}/> : page === 'capabilities' ? <Capabilities data={data} openEvidence={setSelectedEvidence}/> : page === 'evidence' ? <Evidence data={data} openEvidence={setSelectedEvidence}/> : <CreateCluster/>

  return <div className="app-shell">
    <a href="#main-content" className="skip-link">Skip to content</a>
    <aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
      <div className="brand"><img src="./openkubes-icon.png" alt="OpenKubes"/><div><strong>OpenKubes</strong><span>Platform Console</span></div><button className="menu-close" onClick={() => setMenuOpen(false)} aria-label="Close navigation"><Icon name="x"/></button></div>
      <div className="context-switcher"><span className="context-mark">OK</span><span><small>Distribution</small><strong>OpenKubes Platform</strong></span><Icon name="chevron" size={15}/></div>
      <nav aria-label="Primary navigation">{NAV.map((item) => <a href={`#/${item.id}`} className={page === item.id && !selectedCluster ? 'active' : ''} key={item.id}><Icon name={item.id}/><span><strong>{item.label}</strong><small>{item.caption}</small></span></a>)}</nav>
      <div className="sidebar-spacer"/>
      <a href="#/create" className={`create-nav ${page === 'create' ? 'active' : ''}`}><Icon name="create"/><span><strong>Create Cluster</strong><small>Draft a new contract</small></span></a>
      <div className="sidebar-footer"><div className="avatar">AK</div><span><strong>Arash Kaffamanesh</strong><small>Platform authority</small></span><button className="icon-button" aria-label="Account options">•••</button></div>
    </aside>
    {menuOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)}/>} 
    <div className="main-column">
      <header className="topbar"><button className="mobile-menu" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Icon name="menu"/></button><div className="breadcrumbs"><span>OpenKubes</span><Icon name="chevron" size={13}/><strong>{title}</strong></div><div className="top-actions"><label className="global-search"><Icon name="search"/><span className="sr-only">Search platform</span><input placeholder="Search contracts, clusters, evidence…"/><kbd>⌘ K</kbd></label><button className="icon-button notification" aria-label="Notifications"><Icon name="bell"/><span/></button><div className="environment"><span className="live-dot"/><span><small>Environment</small><strong>Community preview</strong></span></div></div></header>
      <main id="main-content" className="content" tabIndex={-1}>{view}<footer className="product-footer"><span>OpenKubes Console Prototype · OK-153</span><span>{data.presentationVersion} · deterministic fixtures</span></footer></main>
    </div>
    {selectedEvidence && <EvidenceDrawer item={selectedEvidence} close={() => setSelectedEvidence(undefined)}/>} 
    {shellCluster && <ClusterShell cluster={shellCluster} close={() => setShellCluster(undefined)}/>}
  </div>
}
