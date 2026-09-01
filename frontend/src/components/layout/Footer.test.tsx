import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/stores/sessionStore'
import { Footer } from './Footer'

function mockAppInfoResponse(data: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      json: () => Promise.resolve(data),
    })
  )
}

describe('Footer', () => {
  beforeEach(() => {
    useSessionStore.setState({ activeSessionCount: 0 })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders version and session information when app metadata loads', async () => {
    mockAppInfoResponse({ status: 'success', version: '2.5.0' })
    useSessionStore.setState({ activeSessionCount: 2 })

    render(<Footer />)

    expect(await screen.findByText('2.5.0')).toBeInTheDocument()
    expect(screen.getByText('2 sessions')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/auth/app-info')
  })

  it('uses the singular session label for one active session', async () => {
    mockAppInfoResponse({ status: 'success', version: '1.0.0' })
    useSessionStore.setState({ activeSessionCount: 1 })

    render(<Footer />)

    expect(await screen.findByText('1.0.0')).toBeInTheDocument()
    expect(screen.getByText('1 session')).toBeInTheDocument()
  })

  it('omits version and session badges when optional fields are missing', async () => {
    mockAppInfoResponse({ status: 'success' })

    render(<Footer />)

    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/auth/app-info'))
    expect(screen.queryByText(/session/)).not.toBeInTheDocument()
    expect(screen.getByText('Open Source Algo Platform for Everyone')).toBeInTheDocument()
  })

  it('renders sessions without a version badge when version is absent', async () => {
    mockAppInfoResponse({ status: 'success' })
    useSessionStore.setState({ activeSessionCount: 3 })

    render(<Footer />)

    expect(await screen.findByText('3 sessions')).toBeInTheDocument()
    expect(screen.queryByText('v')).not.toBeInTheDocument()
  })

  it('survives a failed app-info request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network error')))

    render(<Footer />)

    expect(screen.getByText('Copyright 2026')).toBeInTheDocument()
    expect(screen.getByText('Open Source Algo Platform for Everyone')).toBeInTheDocument()
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/auth/app-info'))
  })
})
