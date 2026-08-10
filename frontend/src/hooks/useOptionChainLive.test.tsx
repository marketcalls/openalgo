import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useOptionChainLive } from './useOptionChainLive'

const marketDataCapture = vi.hoisted(() => ({
  symbols: [] as Array<{ symbol: string; exchange: string }>,
  data: new Map(),
}))

vi.mock('./useMarketData', () => ({
  useMarketData: ({ symbols }: { symbols: Array<{ symbol: string; exchange: string }> }) => {
    marketDataCapture.symbols = symbols
    return {
      data: marketDataCapture.data,
      isConnected: false,
      isAuthenticated: false,
      isPaused: false,
    }
  },
}))

let lastOptionChainBody: Record<string, unknown> = {}

function optionChainResponse() {
  return {
    status: 'success' as const,
    underlying: 'BTC',
    underlying_symbol: 'BTCUSD',
    underlying_exchange: 'CRYPTO',
    underlying_ltp: 100000,
    underlying_prev_close: 99000,
    expiry_date: '28AUG26',
    expiry_ts: 1797897600,
    server_ts: 1796000000,
    atm_strike: 100000,
    forward_price: 100100,
    chain: [],
  }
}

describe('useOptionChainLive', () => {
  beforeEach(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    marketDataCapture.symbols = []
    marketDataCapture.data = new Map()
    lastOptionChainBody = {}
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        lastOptionChainBody = JSON.parse(String(init?.body))
        return new Response(JSON.stringify(optionChainResponse()), { status: 200 })
      })
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('requests Greeks and subscribes to the backend-resolved reference', async () => {
    const { result } = renderHook(() =>
      useOptionChainLive('key', 'BTC', 'CRYPTO', 'CRYPTO', '28AUG26', 20, { enabled: true })
    )

    await waitFor(() => expect(result.current.data).not.toBeNull())

    expect(marketDataCapture.symbols).toContainEqual({ exchange: 'CRYPTO', symbol: 'BTCUSD' })
    expect(lastOptionChainBody.with_greeks).toBe(true)
    expect(result.current.forwardPrice).toBe(100100)
    expect(result.current.clockOffsetMs).toEqual(expect.any(Number))
  })

  it('resyncs the server clock immediately after visibility is restored', async () => {
    let requestCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        requestCount += 1
        return new Response(
          JSON.stringify({ ...optionChainResponse(), server_ts: 1_796_000_000 + requestCount }),
          { status: 200 }
        )
      })
    )

    const { result } = renderHook(() =>
      useOptionChainLive('key', 'BTC', 'CRYPTO', 'CRYPTO', '28AUG26', 20, { enabled: true })
    )
    await waitFor(() => expect(requestCount).toBe(1))
    const firstOffset = result.current.clockOffsetMs

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => document.dispatchEvent(new Event('visibilitychange')))

    await waitFor(() => expect(requestCount).toBe(2))
    await waitFor(() => expect(result.current.clockOffsetMs).not.toBe(firstOffset))
  })
})
