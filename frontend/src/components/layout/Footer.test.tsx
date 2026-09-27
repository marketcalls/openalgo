import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/stores/sessionStore'
import { Footer } from './Footer'

function mockAppInfoResponse(data: unknown) {
  const json = vi.fn().mockResolvedValue(data)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      json,
    })
  )
  return json
}

function separatorCount() {
  return Array.from(screen.getByRole('contentinfo').querySelectorAll('span')).filter(
    (element) => element.textContent === '|'
  ).length
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
    const json = mockAppInfoResponse({ status: 'success' })

    render(<Footer />)

    await waitFor(() => expect(json).toHaveBeenCalled())
    expect(screen.queryByText(/session/)).not.toBeInTheDocument()
    expect(screen.getByText('Open Source Algo Platform for Everyone')).toBeInTheDocument()
    expect(separatorCount()).toBe(1)
  })

  it('renders sessions without a version badge when version is absent', async () => {
    const json = mockAppInfoResponse({ status: 'success' })
    useSessionStore.setState({ activeSessionCount: 3 })

    render(<Footer />)

    await waitFor(() => expect(json).toHaveBeenCalled())
    expect(screen.getByText('3 sessions')).toBeInTheDocument()
    expect(screen.queryByText('v')).not.toBeInTheDocument()
    expect(separatorCount()).toBe(2)
  })

  it('survives a failed app-info request', async () => {
    const request = Promise.reject(new Error('network error'))
    vi.stubGlobal('fetch', vi.fn().mockReturnValue(request))

    render(<Footer />)

    await request.catch(() => undefined)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/auth/app-info'))
    expect(screen.getByText('Copyright 2026')).toBeInTheDocument()
    expect(screen.getByText('Open Source Algo Platform for Everyone')).toBeInTheDocument()
    expect(separatorCount()).toBe(1)
  })
})
