/**
 * A stand-in for the shared market data feed, for tests that stream.
 *
 * Anything that subscribes reaches `MarketDataManager`, and the real one opens
 * a WebSocket, fetches a CSRF token and an API key, and polls a REST endpoint
 * when it cannot. None of that exists in jsdom. Mocking the *hook* instead
 * would be easier and would test nothing: the whole point of a live card is
 * its subscription lifecycle, and the lifecycle lives in `useMarketData`.
 *
 * So this replaces the manager and leaves the real hook in place. A test can
 * then assert the two things that actually matter and are otherwise invisible:
 * which subscriptions a card opened, and that every one of them was closed
 * when the card went away.
 *
 * Use it with a module mock, which keeps one instance shared between the code
 * under test and the assertions:
 *
 * ```ts
 * vi.mock('@/lib/MarketDataManager', () => import('@/test/marketDataHarness'))
 * import { feed } from '@/test/marketDataHarness'
 * ```
 *
 * `feed.push` delivers a tick the way the real manager does, by merging into
 * the cache line and calling every callback registered for that instrument.
 * Wrap it in `act`.
 */

import type {
  ConnectionState,
  MarketData,
  StateListener,
  SymbolData,
} from '@/lib/MarketDataManager'

type Mode = 'LTP' | 'Quote' | 'Depth'

interface Subscription {
  key: string
  symbol: string
  exchange: string
  mode: Mode
  callback: (data: SymbolData) => void
}

interface State {
  connectionState: ConnectionState
  isConnected: boolean
  isAuthenticated: boolean
  isPaused: boolean
  isFallbackMode: boolean
  connectionEpoch: number
  error: string | null
}

function fresh(): State {
  return {
    connectionState: 'authenticated',
    isConnected: true,
    isAuthenticated: true,
    isPaused: false,
    isFallbackMode: false,
    connectionEpoch: 1,
    error: null,
  }
}

/** Everything a test reads or drives. One shared object, reset per test. */
export const feed = {
  /** Every subscription still open, in the order it was opened. */
  open: [] as Subscription[],
  /** Keys of every subscription ever opened, including closed ones. */
  opened: [] as string[],
  /** Keys of every subscription that was closed. */
  closed: [] as string[],
  /** How many times something asked the manager to connect. */
  connects: 0,
  cache: new Map<string, SymbolData>(),
  listeners: new Set<StateListener>(),
  state: fresh(),

  /** Forget everything. Call from `beforeEach`. */
  reset(): void {
    feed.open = []
    feed.opened = []
    feed.closed = []
    feed.connects = 0
    feed.cache.clear()
    feed.listeners.clear()
    feed.state = fresh()
  },

  /** The keys of the subscriptions that are open right now. */
  live(): string[] {
    return feed.open.map((entry) => entry.key)
  },

  /** Change the connection state and tell every listener, as the manager does. */
  setState(patch: Partial<State>): void {
    feed.state = { ...feed.state, ...patch }
    for (const listener of feed.listeners) listener(feed.state)
  },

  /**
   * Deliver one update for an instrument.
   *
   * @param symbol - The OpenAlgo symbol.
   * @param exchange - Its exchange.
   * @param data - The fields the feed carried. Merged over what is cached,
   *   exactly as the real manager merges a partial tick.
   * @param source - `websocket` for a real tick, `rest` for a fallback poll.
   * @param at - When it arrived. Defaults to now; pass a past moment to test
   *   what a card says about numbers that have stopped arriving.
   */
  push(
    symbol: string,
    exchange: string,
    data: MarketData,
    source: 'websocket' | 'rest' = 'websocket',
    at: number = Date.now()
  ): void {
    const key = `${exchange.toUpperCase()}:${symbol.toUpperCase()}`
    const existing = feed.cache.get(key)
    const updated: SymbolData = {
      symbol: symbol.toUpperCase(),
      exchange: exchange.toUpperCase(),
      data: { ...(existing?.data ?? {}), ...data },
      lastUpdate: at,
      updateSource: source,
      connectionEpoch: source === 'websocket' ? feed.state.connectionEpoch : undefined,
    }
    feed.cache.set(key, updated)
    for (const entry of feed.open) {
      if (entry.symbol === updated.symbol && entry.exchange === updated.exchange) {
        entry.callback(updated)
      }
    }
  },
}

/** The manager the application imports, replaced. */
export class MarketDataManager {
  private static instance: MarketDataManager | null = null

  static getInstance(): MarketDataManager {
    if (!MarketDataManager.instance) MarketDataManager.instance = new MarketDataManager()
    return MarketDataManager.instance
  }

  static resetInstance(): void {
    MarketDataManager.instance = null
  }

  setAutoReconnect(): void {}

  getAutoReconnect(): boolean {
    return true
  }

  addStateListener(listener: StateListener): () => void {
    feed.listeners.add(listener)
    listener(feed.state)
    return () => feed.listeners.delete(listener)
  }

  getState() {
    return feed.state
  }

  isFallback(): boolean {
    return feed.state.isFallbackMode
  }

  subscribe(
    rawSymbol: string,
    rawExchange: string,
    mode: Mode,
    callback: (data: SymbolData) => void
  ): () => void {
    const symbol = rawSymbol.toUpperCase()
    const exchange = rawExchange.toUpperCase()
    const key = `${exchange}:${symbol}:${mode}`
    const entry: Subscription = { key, symbol, exchange, mode, callback }
    feed.open.push(entry)
    feed.opened.push(key)
    const cached = feed.cache.get(`${exchange}:${symbol}`)
    if (cached) callback(cached)
    return () => {
      const index = feed.open.indexOf(entry)
      if (index < 0) return
      feed.open.splice(index, 1)
      feed.closed.push(key)
    }
  }

  getCachedData(symbol: string, exchange: string): SymbolData | undefined {
    return feed.cache.get(`${exchange.toUpperCase()}:${symbol.toUpperCase()}`)
  }

  getAllCachedData(): Map<string, SymbolData> {
    return new Map(feed.cache)
  }

  async connect(): Promise<void> {
    feed.connects += 1
  }

  disconnect(): void {}

  pauseConnection(): void {}

  async resumeConnection(): Promise<void> {}

  setFallbackPollingRate(): void {}
}
