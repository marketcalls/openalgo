import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useOptionChainLive } from './useOptionChainLive'

const marketDataCapture = vi.hoisted(() => ({
  symbols: [] as Array<{ symbol: string; exchange: string }>,
  data: new Map(),
  isConnected: false,
  isAuthenticated: false,
  isPaused: false,
  connectionEpoch: 0,
}))

vi.mock('./useMarketData', () => ({
  useMarketData: ({ symbols }: { symbols: Array<{ symbol: string; exchange: string }> }) => {
    marketDataCapture.symbols = symbols
    return {
      data: marketDataCapture.data,
      isConnected: marketDataCapture.isConnected,
      isAuthenticated: marketDataCapture.isAuthenticated,
      isPaused: marketDataCapture.isPaused,
      connectionEpoch: marketDataCapture.connectionEpoch,
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
    marketDataCapture.isConnected = false
    marketDataCapture.isAuthenticated = false
    marketDataCapture.isPaused = false
    marketDataCapture.connectionEpoch = 0
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
    expect(result.current.dataIdentity).toEqual({
      exchange: 'CRYPTO',
      underlying: 'BTC',
      expiry: '28AUG26',
    })
    expect(result.current.lastStreamUpdate).toBeNull()
  })

  it('binds data to the derivative exchange that initiated its poll', async () => {
    const requestBodies: Record<string, unknown>[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        requestBodies.push(JSON.parse(String(init?.body)))
        return new Response(JSON.stringify(optionChainResponse()), { status: 200 })
      })
    )

    const { result, rerender } = renderHook(
      ({ optionExchange }) =>
        useOptionChainLive('key', 'BTC', 'CRYPTO', optionExchange, '28AUG26', 20, {
          enabled: true,
        }),
      { initialProps: { optionExchange: 'NFO' } }
    )
    await waitFor(() => expect(result.current.dataIdentity?.exchange).toBe('NFO'))

    rerender({ optionExchange: 'BFO' })

    await waitFor(() => expect(requestBodies).toHaveLength(2))
    await waitFor(() => expect(result.current.dataIdentity?.exchange).toBe('BFO'))
  })

  it('tracks only WebSocket provenance as stream freshness', async () => {
    marketDataCapture.isConnected = true
    marketDataCapture.isAuthenticated = true
    marketDataCapture.connectionEpoch = 1
    marketDataCapture.data = new Map([
      [
        'CRYPTO:BTCUSD',
        {
          exchange: 'CRYPTO',
          symbol: 'BTCUSD',
          lastUpdate: 1_796_000_000_000,
          updateSource: 'rest',
          data: { ltp: 100_050 },
        },
      ],
    ])

    const { result, rerender } = renderHook(() =>
      useOptionChainLive('key', 'BTC', 'CRYPTO', 'CRYPTO', '28AUG26', 20, { enabled: true })
    )
    await waitFor(() => expect(result.current.data).not.toBeNull())

    expect(result.current.isStreaming).toBe(true)
    expect(result.current.lastStreamUpdate).toBeNull()

    marketDataCapture.data = new Map([
      [
        'CRYPTO:BTCUSD',
        {
          exchange: 'CRYPTO',
          symbol: 'BTCUSD',
          lastUpdate: 1_796_000_000_001,
          updateSource: 'websocket',
          connectionEpoch: 1,
          data: { ltp: 100_075 },
        },
      ],
    ])
    rerender()

    await waitFor(() =>
      expect(result.current.lastStreamUpdate?.getTime()).toBe(1_796_000_000_001)
    )
  })

  it('requires a WebSocket tick from the current authentication epoch', async () => {
    marketDataCapture.isConnected = true
    marketDataCapture.isAuthenticated = true
    marketDataCapture.connectionEpoch = 1
    marketDataCapture.data = new Map([
      [
        'CRYPTO:BTCUSD',
        {
          exchange: 'CRYPTO',
          symbol: 'BTCUSD',
          lastUpdate: 1_796_000_000_010,
          updateSource: 'websocket',
          connectionEpoch: 1,
          data: { ltp: 100_080 },
        },
      ],
    ])

    const { result, rerender } = renderHook(() =>
      useOptionChainLive('key', 'BTC', 'CRYPTO', 'CRYPTO', '28AUG26', 20, { enabled: true })
    )
    await waitFor(() =>
      expect(result.current.lastStreamUpdate?.getTime()).toBe(1_796_000_000_010)
    )

    marketDataCapture.isConnected = false
    marketDataCapture.isAuthenticated = false
    rerender()
    await waitFor(() => expect(result.current.lastStreamUpdate).toBeNull())

    marketDataCapture.isConnected = true
    marketDataCapture.isAuthenticated = true
    marketDataCapture.connectionEpoch = 2
    rerender()
    expect(result.current.lastStreamUpdate).toBeNull()

    marketDataCapture.data = new Map([
      [
        'CRYPTO:BTCUSD',
        {
          exchange: 'CRYPTO',
          symbol: 'BTCUSD',
          lastUpdate: 1_796_000_000_020,
          updateSource: 'websocket',
          connectionEpoch: 2,
          data: { ltp: 100_090 },
        },
      ],
    ])
    rerender()
    await waitFor(() =>
      expect(result.current.lastStreamUpdate?.getTime()).toBe(1_796_000_000_020)
    )
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
