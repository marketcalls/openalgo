import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BROKER_BUSY_SENTENCE } from '@/test/axiosAnswer'
import { useOptionChainPolling } from './useOptionChainPolling'

describe('useOptionChainPolling request identity', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('clears loading when an in-flight request is invalidated and polling is disabled', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    const { result, rerender } = renderHook(
      ({ expiry, enabled }) =>
        useOptionChainPolling('key', 'NIFTY', 'NSE_INDEX', expiry, 20, {
          enabled,
          derivativeExchange: 'NFO',
        }),
      { initialProps: { expiry: '13AUG26', enabled: true } }
    )

    await waitFor(() => expect(result.current.isLoading).toBe(true))
    act(() => rerender({ expiry: '20AUG26', enabled: false }))

    await waitFor(() => expect(result.current.isLoading).toBe(false))
  })
})

describe('useOptionChainPolling failure text', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const poll = (status: number, body: string) => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () => new Response(body, { status, headers: { 'Content-Type': 'application/json' } })
      )
    )
    return renderHook(() =>
      useOptionChainPolling('key', 'NIFTY', 'NSE_INDEX', '13AUG26', 20, {
        enabled: true,
        derivativeExchange: 'NFO',
        // Long enough that only the first request runs during the test.
        refreshInterval: 60_000,
      })
    )
  }

  it('shows the sentence a busy refusal carries instead of its status code', async () => {
    const { result } = poll(429, JSON.stringify({ status: 'error', message: BROKER_BUSY_SENTENCE }))
    await waitFor(() => expect(result.current.error).toBe(BROKER_BUSY_SENTENCE))
    expect(result.current.isLoading).toBe(false)
  })

  it('keeps the text it always had for any other failure', async () => {
    const { result } = poll(500, JSON.stringify({ status: 'error', message: 'internal' }))
    await waitFor(() => expect(result.current.error).toBe('HTTP error! status: 500'))
  })

  it('keeps the text it always had for a 429 without a JSON message', async () => {
    const { result } = poll(429, '<html>Too Many Requests</html>')
    await waitFor(() => expect(result.current.error).toBe('HTTP error! status: 429'))
  })
})
