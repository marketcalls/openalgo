import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/stores/sessionStore'
import { Footer } from './Footer'

describe('Footer', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    useSessionStore.setState({ activeSessionCount: 0 })
  })

  it('renders version when fetch succeeds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: async () => ({ status: 'success', version: '1.2.3' }),
      })
    )

    render(<Footer />)

    await waitFor(() => {
      expect(screen.getByText('1.2.3')).toBeInTheDocument()
    })
  })

  it('does not render version badge as version number is missing', async () => {
    const jsonMock = vi.fn().mockResolvedValue({ status: 'success' })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: jsonMock }))

    render(<Footer />)

    await waitFor(() => {
      expect(jsonMock).toHaveBeenCalled()
    })

    expect(screen.queryByText('v')).not.toBeInTheDocument()
    expect(screen.queryByText(/session/)).not.toBeInTheDocument()
    expect(screen.getAllByText('|')).toHaveLength(3)
  })

  it('does not crash when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network Error')))

    render(<Footer />)

    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalled()
    })
    expect(screen.getByText('Copyright 2026')).toBeInTheDocument()
  })

  it('renders session count when active session exists', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: async () => ({ status: 'error' }),
      })
    )

    act(() => {
      useSessionStore.setState({ activeSessionCount: 2 })
    })
    render(<Footer />)
    expect(screen.getByText('2 sessions')).toBeInTheDocument()
  })

  it('renders singular session when only one session is active', () => {
    act(() => {
      useSessionStore.setState({ activeSessionCount: 1 })
    })

    render(<Footer />)

    expect(screen.getByText('1 session')).toBeInTheDocument()
  })
})
