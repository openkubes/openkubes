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
    for (const label of ['Platform Overview', 'Clusters', 'Workloads', 'Capabilities', 'Evidence & Audit', 'Create Cluster']) {
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
})
