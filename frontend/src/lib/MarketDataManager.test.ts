import { afterEach, describe, expect, it, vi } from 'vitest'
import { MarketDataManager } from './MarketDataManager'

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

interface ManagerHarness {
  fallbackMode: boolean
  apiKey: string | null
  enableFallbackMode: () => Promise<void>
  fetchMarketDataViaRest: () => Promise<void>
  disableFallbackMode: () => void
  startFallbackPolling: () => void
  handleMessage: (event: MessageEvent) => void
}

describe('MarketDataManager fallback sequencing', () => {
  afterEach(() => {
    MarketDataManager.resetInstance()
    vi.unstubAllGlobals()
  })

  it('does not let an old REST fallback session replace a newer WebSocket tick', async () => {
    const response = deferred<Response>()
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        if (url === '/api/v1/multiquotes') return response.promise
        if (url === '/auth/csrf-token') {
          return Promise.resolve(
            new Response(JSON.stringify({ csrf_token: 'csrf' }), { status: 200 })
          )
        }
        if (url === '/api/websocket/apikey') {
          return Promise.resolve(
            new Response(JSON.stringify({ status: 'success', api_key: 'key' }), { status: 200 })
          )
        }
        return Promise.reject(new Error(`Unexpected fetch: ${url}`))
      })
    )

    const manager = MarketDataManager.getInstance()
    const received: number[] = []
    manager.subscribe('NIFTY13AUG2624600CE', 'NFO', 'Depth', (update) => {
      if (update.data.ltp !== undefined) received.push(update.data.ltp)
    })

    const harness = manager as unknown as ManagerHarness
    harness.fallbackMode = true
    harness.apiKey = 'key'
    const pendingFallback = harness.fetchMarketDataViaRest()

    harness.handleMessage(
      new MessageEvent('message', {
        data: JSON.stringify({
          type: 'market_data',
          symbol: 'NIFTY13AUG2624600CE',
          exchange: 'NFO',
          data: { ltp: 200 },
        }),
      })
    )
    harness.disableFallbackMode()
    const startFallbackPolling = vi
      .spyOn(harness, 'startFallbackPolling')
      .mockImplementation(() => {})
    await harness.enableFallbackMode()
    expect(startFallbackPolling).toHaveBeenCalledOnce()
    response.resolve(
      new Response(
        JSON.stringify({
          status: 'success',
          results: [
            {
              symbol: 'NIFTY13AUG2624600CE',
              exchange: 'NFO',
              data: { ltp: 100 },
            },
          ],
        })
      )
    )
    await pendingFallback

    expect(received).toEqual([200])
    expect(manager.getCachedData('NIFTY13AUG2624600CE', 'NFO')).toMatchObject({
      data: { ltp: 200 },
      updateSource: 'websocket',
    })
  })
})
