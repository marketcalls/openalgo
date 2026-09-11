import { type Bar, CandleBuilder, createChart, type SeriesApi } from 'openalgo-charts'
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
  setPriceData(): void
  beginReplayAt(index: number): Promise<void>
  runReconcile(): Promise<void>
  loadOlderHistory(): Promise<void>
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
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
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
  return { terminal, state }
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
