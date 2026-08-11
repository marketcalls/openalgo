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
  fetchMarketDataViaRest: () => Promise<void>
  disableFallbackMode: () => void
  handleMessage: (event: MessageEvent) => void
}

describe('MarketDataManager fallback sequencing', () => {
  afterEach(() => {
    MarketDataManager.resetInstance()
    vi.unstubAllGlobals()
  })

  it('does not let an old REST fallback response replace a newer WebSocket tick', async () => {
    const response = deferred<Response>()
    vi.stubGlobal('fetch', vi.fn(() => response.promise))

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
