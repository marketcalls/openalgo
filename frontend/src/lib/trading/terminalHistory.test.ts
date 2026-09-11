import {
  type Bar,
  CandleBuilder,
  createChart,
  DataLoadingController,
  type SeriesApi,
} from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

// Exercise the terminal and chart together. Only canvas painting and the
// asynchronous broker boundary are replaced; replay and data writes are real.
type TerminalState = {
  chart: ReturnType<typeof createChart>
  price: SeriesApi
  volume: SeriesApi
  rawBars: Bar[]
  shownBars: Bar[]
  builder: CandleBuilder
  liveBucket: number
  sym: SymbolView
  interval: string
  loadTicket: number
  destroyed: boolean
  ws: unknown
  bookTimer: ReturnType<typeof setInterval> | null
  ltpPollTimer: ReturnType<typeof setInterval> | null
  loadingOlder: unknown
  noMoreHistory: boolean
  rest: { getBars: () => Promise<Bar[]> }
  data: {
    refresh(): Promise<readonly Bar[]>
    loadMore(): Promise<readonly Bar[]>
    bars(): readonly Bar[]
    getState(): {
      request: {
        symbol: string
        exchange: string
        interval: string
      } | null
      bars: readonly Bar[]
      status: string
      historyStatus: string
      hasMore: boolean | null
      reason: string
      paused: boolean
    }
    pushBar(bar: Bar): void
    setPaused(paused: boolean): void
    setVisible(visible: boolean): void
    destroy(): void
  } | null
  setPriceData(): void
  buildChart(): void
  beginReplayAt(index: number): Promise<void>
  runReconcile(): Promise<void>
  loadOlderHistory(): Promise<void>
  connectLive(): void
  replayPicking: boolean
  commitReplayPick(): void
  setVolumeVisible(visible: boolean): void
}

const bar = (time: number, close: number, volume = 100): Bar => ({
  time,
  open: close - 1,
  high: close + 2,
  low: close - 2,
  close,
  volume,
})
const bars = [bar(60, 100), bar(120, 101), bar(180, 102), bar(240, 103)]
const terminals: TradingTerminal[] = []

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  // Keep the real feed lifecycle; replace only its network transport.
  vi.stubGlobal(
    'WebSocket',
    class {
      readyState = 0
      send() {}
      close() {
        this.readyState = 3
      }
    }
  )
  const context = new Proxy(
    {
      measureText: (text: string) => ({ width: text.length * 7 }),
      createLinearGradient: () => ({ addColorStop() {} }),
      getImageData: () => ({ data: new Uint8ClampedArray([0, 0, 0, 255]) }),
    },
    { get: (target, key) => target[key as keyof typeof target] ?? (() => {}) }
  )
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(
    context as unknown as CanvasRenderingContext2D
  )
})

afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function mount() {
  const container = document.createElement('div')
  const legendEl = document.createElement('div')
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl,
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast() {},
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as TerminalState
  state.chart = createChart(container, {
    shortcuts: false,
    timeNavigator: false,
    raf: {
      schedule: (cb) => {
        cb()
        return 1
      },
      cancel() {},
    },
  })
  state.chart.applySize(800, 600)
  state.price = state.chart.addSeries('candlestick')
  state.volume = state.chart.addSeries('histogram')
  state.sym = {
    symbol: 'NIFTY29SEP26FUT',
    exchange: 'NFO',
    name: 'Nifty Futures',
    lotsize: 65,
    lots: true,
    tick: 0.05,
    freezeQty: 1800,
    quoteOnly: false,
    productOptions: ['MIS', 'NRML'],
    product: 'MIS',
  }
  state.interval = '1m' // Whole-bar replay has no finer history request.
  state.rawBars = bars.map((b) => ({ ...b }))
  state.liveBucket = 240
  state.builder = new CandleBuilder({ intervalSec: 60, volumeMode: 'ltq-sum' })
  state.builder.seed(state.rawBars[3])
  state.setPriceData()
  return { terminal, state, container, legendEl }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function pendingHistory(state: TerminalState) {
  const pending = deferred<Bar[]>()
  state.rest = { getBars: () => pending.promise }
  return pending
}

describe('history refresh while replay controls the chart', () => {
  it('routes repair and pagination through one data owner', async () => {
    const { state } = mount()
    const refresh = vi.fn(async () => [bar(120, 111), bar(240, 103, 4200)])
    const loadMore = vi.fn(async () => [bar(0, 99), ...state.rawBars])
    const snapshot = (reason: string, values: readonly Bar[]) => ({
      request: {
        symbol: state.sym.symbol,
        exchange: state.sym.exchange,
        interval: state.interval,
      },
      bars: values,
      status: 'ready',
      historyStatus: 'idle',
      hasMore: true,
      reason,
      paused: false,
    })
    let current = snapshot('load', state.rawBars)
    state.data = {
      refresh: async () => {
        const values = await refresh()
        current = snapshot('refresh', values)
        return values
      },
      loadMore: async () => {
        const values = await loadMore()
        current = snapshot('prepend', values)
        return values
      },
      bars: () => current.bars,
      getState: () => current,
      pushBar() {},
      setPaused() {},
      setVisible() {},
      destroy() {},
    }
    state.rest = { getBars: async () => Promise.reject(new Error('direct history bypass')) }

    await state.runReconcile()
    expect(refresh).toHaveBeenCalledOnce()
    expect(state.rawBars.find((item) => item.time === 120)?.close).toBe(111)
    expect(state.builder.current()?.volume).toBe(4200)

    await state.loadOlderHistory()
    expect(loadMore).toHaveBeenCalledOnce()
    expect(state.rawBars.map((item) => item.time)).toEqual([0, 120, 240])
  })

  it('pauses controller snapshots for replay and resumes the maintained live store', async () => {
    const { terminal, state } = mount()
    const setPaused = vi.fn()
    state.data = {
      refresh: async () => state.rawBars,
      loadMore: async () => state.rawBars,
      bars: () => state.rawBars,
      getState: () => ({
        request: {
          symbol: state.sym.symbol,
          exchange: state.sym.exchange,
          interval: state.interval,
        },
        bars: state.rawBars,
        status: 'ready',
        historyStatus: 'idle',
        hasMore: true,
        reason: 'state',
        paused: false,
      }),
      pushBar() {},
      setPaused,
      setVisible() {},
      destroy() {},
    }

    await state.beginReplayAt(1)
    expect(setPaused).toHaveBeenCalledWith(true)
    terminal.stopReplay()
    expect(setPaused).toHaveBeenLastCalledWith(false)
  })

  it.each([
    'before',
    'during',
  ] as const)('isolates a refresh started %s replay and restores updated live data on exit', async (when) => {
    const { terminal, state } = mount()
    const pending = pendingHistory(state)
    let refresh: Promise<void>
    if (when === 'before') refresh = state.runReconcile()
    await state.beginReplayAt(1)
    if (when === 'during') refresh = state.runReconcile()
    const price = [...state.price.getData()]
    const volume = [...state.volume.getData()]
    const replay = terminal.replayState()

    pending.resolve([bar(120, 111), bar(240, 999, 4200)])
    await refresh!

    expect(state.rawBars[1].close).toBe(111)
    expect(state.builder.current()?.volume).toBe(4200)
    expect(state.price.getData()).toEqual(price)
    expect(state.volume.getData()).toEqual(volume)
    expect(terminal.replayState()).toEqual(replay)

    terminal.replayStep()
    expect(state.price.getData()).toHaveLength(3)
    expect(state.price.getData()[1].close).toBe(101)
    terminal.stopReplay()
    expect(state.price.getData()).toHaveLength(4)
    expect(state.price.getData()[1].close).toBe(111)
    expect(state.price.getData()[3].close).toBe(103)
    expect(state.volume.getData()[3].close).toBe(4200)
  })

  it('keeps a pending older page out of the replay series and viewport', async () => {
    const { terminal, state } = mount()
    const pending = pendingHistory(state)
    const page = state.loadOlderHistory()
    await state.beginReplayAt(1)
    const range = state.chart.getVisibleLogicalRange()
    pending.resolve([bar(0, 99)])
    await page

    expect(state.rawBars).toHaveLength(5)
    expect(state.price.getData().map((b) => b.time)).toEqual([60, 120])
    expect(state.volume.getData().map((b) => b.time)).toEqual([60, 120])
    expect(state.chart.getVisibleLogicalRange()).toEqual(range)
    terminal.stopReplay()
    expect(state.price.getData().map((b) => b.time)).toEqual([0, 60, 120, 180, 240])
  })

  it('applies a refresh normally when replay exits before the response arrives', async () => {
    const { terminal, state } = mount()
    await state.beginReplayAt(1)
    const pending = pendingHistory(state)
    const refresh = state.runReconcile()
    terminal.stopReplay()
    pending.resolve([bar(120, 111)])
    await refresh
    expect(state.price.getData()).toHaveLength(4)
    expect(state.price.getData()[1].close).toBe(111)
  })

  it.each([
    'symbol',
    'interval',
    'reload',
    'destroy',
  ] as const)('discards a late refresh after a %s change', async (change) => {
    const { terminal, state } = mount()
    const pending = pendingHistory(state)
    const refresh = state.runReconcile()
    if (change === 'symbol') state.sym = { ...state.sym, symbol: 'BANKNIFTY29SEP26FUT' }
    if (change === 'interval') state.interval = '5m'
    if (change === 'reload') state.loadTicket++
    if (change === 'destroy') terminal.destroy()
    pending.resolve([bar(120, 999)])
    await refresh
    expect(state.rawBars[1].close).toBe(101)
    if (change === 'destroy') expect(vi.getTimerCount()).toBe(0)
  })
})

describe('live candle alignment', () => {
  it('anchors intraday buckets to the broker history session', () => {
    const { state } = mount()
    const sessionOpen = Date.UTC(2026, 8, 11, 3, 45) / 1000
    state.interval = '1h'
    state.rawBars = [bar(sessionOpen, 100)]
    state.ws = {
      onLtp: () => () => {},
      onDepth: () => () => {},
      subscribe() {},
    }

    state.connectLive()

    expect(state.builder.bucketStart(sessionOpen + 60 * 59)).toBe(sessionOpen)
    expect(state.builder.bucketStart(sessionOpen + 60 * 60)).toBe(sessionOpen + 60 * 60)
  })

  it('uses the exchange timestamp from depth without inventing trade volume', () => {
    const { state } = mount()
    const sessionOpen = Date.UTC(2026, 8, 11, 3, 45) / 1000
    let onDepth: ((symbol: string, exchange: string, depth: unknown) => void) | undefined
    const pushBar = vi.fn()
    state.interval = '1h'
    state.rawBars = [bar(sessionOpen, 100, 5000)]
    state.ws = {
      onLtp: () => () => {},
      onDepth: (cb: typeof onDepth) => {
        onDepth = cb
        return () => {}
      },
      subscribe() {},
    }
    state.data = { pushBar, destroy() {} } as unknown as NonNullable<TerminalState['data']>
    vi.setSystemTime(new Date('2030-01-01T00:00:00Z'))
    state.connectLive()

    onDepth?.(state.sym.symbol, state.sym.exchange, {
      bids: [],
      asks: [],
      ltp: 104,
      timeSec: sessionOpen + 60 * 61,
    })

    expect(state.rawBars.at(-1)).toMatchObject({
      time: sessionOpen + 60 * 60,
      close: 104,
      volume: 0,
    })
    expect(pushBar).toHaveBeenCalledWith(
      expect.objectContaining({ time: sessionOpen + 60 * 60, close: 104, volume: 0 })
    )
  })
})

describe('terminal listener ownership', () => {
  it('keeps one replay pointer handler across rebuilds and removes it on destroy', () => {
    const { terminal, state, container } = mount()
    state.buildChart()
    state.buildChart()
    const commit = vi.spyOn(state, 'commitReplayPick').mockImplementation(() => {})
    state.replayPicking = true

    container.dispatchEvent(new MouseEvent('pointerdown', { clientX: 10, clientY: 20 }))
    container.dispatchEvent(new MouseEvent('pointerup', { clientX: 10, clientY: 20 }))
    expect(commit).toHaveBeenCalledOnce()

    terminal.destroy()
    container.dispatchEvent(new MouseEvent('pointerdown', { clientX: 10, clientY: 20 }))
    container.dispatchEvent(new MouseEvent('pointerup', { clientX: 10, clientY: 20 }))
    expect(commit).toHaveBeenCalledOnce()
  })

  it('removes delegated legend actions on destroy', () => {
    const { terminal, state, legendEl } = mount()
    const setVolumeVisible = vi.spyOn(state, 'setVolumeVisible').mockImplementation(() => {})
    legendEl.innerHTML = '<button data-legend-action="volume">Volume</button>'
    const button = legendEl.querySelector('button')!

    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(setVolumeVisible).toHaveBeenCalledOnce()
    terminal.destroy()
    legendEl.innerHTML = '<button data-legend-action="volume">Volume</button>'
    legendEl.querySelector('button')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(setVolumeVisible).toHaveBeenCalledOnce()
  })
})

describe('older history session ownership', () => {
  it.each([
    'bars',
    'empty',
  ] as const)('discards a previous symbol page returning %s', async (outcome) => {
    const { terminal, state } = mount()
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: {} })
    const pending = pendingHistory(state)
    const page = state.loadOlderHistory()
    const newer = [bar(300, 200), bar(360, 201)]
    state.rest = { getBars: async () => newer }
    await terminal.loadSymbol({ ...state.sym, symbol: 'BANKNIFTY29SEP26FUT' })
    const completion = vi.spyOn(state.chart, 'historyLoadComplete')
    pending.resolve(outcome === 'bars' ? [bar(0, 99)] : [])
    await page

    expect(state.rawBars).toEqual(newer)
    expect(state.price.getData()).toEqual(newer)
    expect(state.noMoreHistory).toBe(false)
    expect(completion).not.toHaveBeenCalled()
  })

  it('keeps a newer page pending when an obsolete page finishes', async () => {
    const { terminal, state } = mount()
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: {} })
    const pending = pendingHistory(state)
    const oldPage = state.loadOlderHistory()
    const newer = [bar(300, 200), bar(360, 201)]
    state.rest = { getBars: async () => newer }
    await terminal.loadSymbol({ ...state.sym, symbol: 'BANKNIFTY29SEP26FUT' })
    const next = pendingHistory(state)
    const newPage = state.loadOlderHistory()
    const loading = state.loadingOlder
    pending.resolve([])
    await oldPage

    expect(state.loadingOlder).toBe(loading)
    expect(state.loadingOlder).toBeTruthy()
    expect(state.noMoreHistory).toBe(false)
    next.resolve([bar(240, 199)])
    await newPage
    expect(state.rawBars.map((b) => b.time)).toEqual([240, 300, 360])
    expect(state.loadingOlder).toBeFalsy()
  })

  it('does not call a destroyed chart when an older page completes', async () => {
    const { terminal, state } = mount()
    const pending = pendingHistory(state)
    const chart = state.chart
    const completion = vi.spyOn(chart, 'historyLoadComplete')
    const page = state.loadOlderHistory()
    terminal.destroy()
    const before = [...state.rawBars]
    pending.resolve([bar(0, 99)])
    await page

    expect(chart.isDestroyed).toBe(true)
    expect(completion).not.toHaveBeenCalled()
    expect(state.rawBars).toEqual(before)
  })
})

describe('symbol load lifecycle', () => {
  it('stops controller polling while hidden and releases it on teardown', async () => {
    const { terminal } = mount()
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    const setVisible = vi.spyOn(DataLoadingController.prototype, 'setVisible')
    const destroy = vi.spyOn(DataLoadingController.prototype, 'destroy')
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: { minutes: ['1m'] } })
    vi.spyOn(terminal, 'search').mockResolvedValue([])
    await terminal.init()

    visibility.mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(setVisible).toHaveBeenLastCalledWith(false)

    terminal.destroy()
    expect(destroy).toHaveBeenCalledOnce()
    const calls = setVisible.mock.calls.length
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(setVisible).toHaveBeenCalledTimes(calls)
  })

  it('does not create a socket or book poller after destruction during interval lookup', async () => {
    const { terminal, state } = mount()
    const intervals = deferred<{ data: { minutes: string[] } }>()
    vi.spyOn(terminal, 'api').mockReturnValue(intervals.promise)
    const init = terminal.init()
    terminal.destroy()
    intervals.resolve({ data: { minutes: ['1m'] } })
    await init

    expect(state.ws).toBeNull()
    expect(state.bookTimer).toBeNull()
    expect(state.chart).toBeNull()
  })

  it('does not restart quote polling when teardown closes the socket', async () => {
    const { terminal, state } = mount()
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: { minutes: ['1m'] } })
    await terminal.init()
    terminal.destroy()

    expect(state.ltpPollTimer).toBeNull()
    expect(state.ws).toBeNull()
  })

  it('does not resume a destroyed terminal after symbol lookup', async () => {
    const { terminal, state } = mount()
    const lookup = deferred<{ data: Record<string, unknown> }>()
    vi.spyOn(terminal, 'api').mockReturnValue(lookup.promise)
    state.rest = { getBars: async () => [bar(300, 999)] }
    const before = [...state.rawBars]
    const load = terminal.loadSymbol(state.sym)
    terminal.destroy()
    lookup.resolve({ data: {} })

    expect(await load).toBe(false)
    expect(state.rawBars).toEqual(before)
    expect(state.chart).toBeNull()
  })

  it('does not apply history or rebuild after the terminal is destroyed', async () => {
    const { terminal, state } = mount()
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: {} })
    const pending = pendingHistory(state)
    const before = [...state.rawBars]
    const load = terminal.loadSymbol(state.sym)
    await Promise.resolve() // The metadata response starts the history request.
    terminal.destroy()
    pending.resolve([bar(300, 999)])

    expect(await load).toBe(false)
    expect(state.rawBars).toEqual(before)
    expect(state.chart).toBeNull()
  })

  it.each([
    'success',
    'failure',
  ] as const)('keeps the newer symbol when old history returns a %s', async (outcome) => {
    const { terminal, state } = mount()
    vi.spyOn(terminal, 'api').mockResolvedValue({ data: {} })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const pending = pendingHistory(state)
    const first = terminal.loadSymbol(state.sym)
    await Promise.resolve()
    const newer = [bar(300, 200), bar(360, 201)]
    state.rest = { getBars: async () => newer }
    const second = terminal.loadSymbol({ ...state.sym, symbol: 'BANKNIFTY29SEP26FUT' })
    expect(await second).toBe(true)
    const chart = state.chart
    if (outcome === 'success') pending.resolve([bar(300, 999)])
    else pending.reject(new Error('old request failed'))

    expect(await first).toBe(false)
    expect(state.rawBars).toEqual(newer)
    expect(state.price.getData()).toEqual(newer)
    expect(state.sym.symbol).toBe('BANKNIFTY29SEP26FUT')
    expect(state.chart).toBe(chart)
  })
})
