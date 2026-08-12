import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
