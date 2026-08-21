import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'

describe('OpenKubes Console', () => {
  beforeEach(() => { window.location.hash = '#/overview' })

  it('renders the management plane first with evidence-backed status', async () => {
    render(<App />)
    expect(await screen.findByText('Good evening, Arash.')).toBeInTheDocument()
    const managementMarkers = screen.getAllByText('Management plane')
    expect(managementMarkers.length).toBeGreaterThan(0)
    expect(screen.getAllByText('ok-mgmt').length).toBeGreaterThan(0)
  })

  it('exposes all curated product areas in navigation', async () => {
    render(<App />)
    await screen.findByText('Good evening, Arash.')
    for (const label of ['Platform Overview', 'Clusters', 'Workloads', 'AI Agents', 'Capabilities', 'Evidence & Audit', 'Create Cluster']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })

  it('keeps prototype authorization disabled until review is confirmed', async () => {
    window.location.hash = '#/create'
    render(<App />)
    await screen.findByText('Declare cluster intent')
    fireEvent.click(screen.getByRole('button', { name: /Generate contract/i }))
    fireEvent.click(screen.getByRole('button', { name: /Continue to authorization/i }))
    const authorize = screen.getByRole('button', { name: /Authorize prototype/i })
    expect(authorize).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(authorize).toBeEnabled())
  })

  it('opens a cluster-scoped shell and blocks mutating commands', async () => {
    window.location.hash = '#/clusters'
    render(<App />)
    await screen.findByRole('heading', { name: 'Clusters' })
    fireEvent.click(screen.getByRole('button', { name: 'Open ok-mgmt' }))
    fireEvent.click(await screen.findByRole('button', { name: /Open Shell/i }))

    expect(await screen.findByRole('heading', { name: 'Shell · ok-mgmt' })).toBeInTheDocument()
    expect(screen.getByText(/No credential, kubeconfig, WebSocket, or backend connection/i)).toBeInTheDocument()

    const input = screen.getByPlaceholderText(/read-only command or ask why/i)
    fireEvent.change(input, { target: { value: 'kubectl delete node ok-mgmt-cp-01' } })
    fireEvent.click(screen.getByRole('button', { name: /^Run$/ }))
    expect(await screen.findByText(/BLOCKED · This read-only prototype/i)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'why is this cluster ready?' } })
    fireEvent.click(screen.getByRole('button', { name: /^Run$/ }))
    expect(await screen.findByText(/explanation resolves to the observed contract revision/i)).toBeInTheDocument()
    expect(screen.getByText(/Suggested read-only command/i)).toBeInTheDocument()
  })

  it('deploys a verified Agent only through a conformant Worker Cluster review', async () => {
    window.location.hash = '#/agents'
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'AI Agents' })).toBeInTheDocument()
    expect(screen.getByText('Kagent Platform Operator')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: /Deploy Agent/i })[0])
    expect(await screen.findByRole('heading', { name: /Deploy Kagent Platform Operator/i })).toBeInTheDocument()
    const target = screen.getByRole('radio', { name: /ok-ai/i })
    expect(target).toBeChecked()
    expect(screen.queryByRole('radio', { name: /ok-mgmt/i })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Review permissions/i }))
    expect(await screen.findByText('Review tools and permissions')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Generate claim/i }))
    expect(await screen.findByText('Review the generated AgentDeploymentClaim')).toBeInTheDocument()
    const simulate = screen.getByRole('button', { name: /Simulate deployment/i })
    expect(simulate).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    expect(simulate).toBeEnabled()
    fireEvent.click(simulate)
    expect(await screen.findByText('Deployment journey validated')).toBeInTheDocument()
    expect(screen.getByText(/No Agent, namespace, credential, workload, or backend resource was created/i)).toBeInTheDocument()
  })
})
