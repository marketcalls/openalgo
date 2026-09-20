import {
  type Bar,
  CandleBuilder,
  comparisonController,
  createChart,
  DataLoadingController,
  ReplayGroup,
  type SeriesApi,
} from 'openalgo-charts'
import { parseExpression, type SymbolExpression } from 'openalgo-charts/transform'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'
import { WorkspaceReplayCoordinator } from './workspaceReplay'

// Exercise the terminal and chart together. Only canvas painting and the
// asynchronous broker boundary are replaced; replay and data writes are real.
type TerminalState = {
  chart: ReturnType<typeof createChart>
  price: SeriesApi
  volume: SeriesApi
  volumeMA: SeriesApi | null
  ctype: string
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
  updateLiveBar(bar: Bar): boolean
  chartSettingsSaved: Record<string, string | number | boolean>
  buildChart(): void
  beginReplayAt(index: number): Promise<void>
  runReconcile(): Promise<void>
  loadOlderHistory(): Promise<void>
  connectLive(): void
  connectExpressionLive(expr: SymbolExpression): void
  expr: SymbolExpression | null
  exprFeed: { legBars: Record<string, readonly Bar[]> } | null
  exprLegExchange: string
  legLtp: Map<string, number>
  replayPicking: boolean
  commitReplayPick(): void
  setVolumeVisible(visible: boolean): void
  onTick(event: { ltp: number; timeSec: number }): void
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
  state.volume = state.chart.addSeries('histogram', { priceScaleId: '' })
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

describe('workspace replay terminal ownership', () => {
  it('publishes picker availability and shades followers without giving them selection ownership', () => {
    const owner = mount()
    const follower = mount()
    const preview = vi.fn((time: number) => follower.terminal.setWorkspaceReplayPreview(time))
    owner.terminal.beginWorkspaceReplayPick(vi.fn(), vi.fn(), preview)
    expect(preview).toHaveBeenLastCalledWith(180)
    owner.terminal.moveReplayPick(2)
    expect(preview).toHaveBeenLastCalledWith(240)
    expect(follower.terminal.replayPickingBar()).toBe(false)
    const shades = (
      follower.state as unknown as { replayShades: { options: { index: number | null } }[] }
    ).replayShades
    expect(shades).toHaveLength(1)
    follower.terminal.setWorkspaceReplayPreview(null)
    owner.terminal.cancelReplayPick()
  })

  it('falls back to completed candles when finer history is not ordered', async () => {
    const { terminal, state } = mount()
    state.interval = '5m'
    state.rawBars = [bar(0, 100), bar(300, 110), bar(600, 120)]
    state.setPriceData()
    state.rest = { getBars: async () => [bar(60, 101), bar(0, 100)] }
    const prepared = await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: new AbortController().signal,
    })
    terminal.setReplayParticipation(1, true)
    const group = new ReplayGroup([prepared.member], { startTime: 300 })
    group.step()
    expect(state.price.getData().map((row) => row.close)).toEqual([100, 110])
    group.destroy()
    terminal.restoreReplayMember(1)
  })
  it('does not restore an active member before its group releases display ownership', async () => {
    const { terminal, state } = mount()
    const signal = new AbortController()
    const prepared = await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: signal.signal,
    })
    terminal.setReplayParticipation(1, true)
    const group = new ReplayGroup([prepared.member], { startTime: 180 })
    state.onTick({ ltp: 150, timeSec: 305 })
    signal.abort()
    expect(state.price.getData().at(-1)?.close).toBe(101)
    group.destroy()
    terminal.restoreReplayMember(1)
    expect(state.price.getData().at(-1)?.close).toBe(150)
  })

  it('restores current live data through the real workspace coordinator exit', async () => {
    const { terminal, state } = mount()
    const error = vi.fn()
    const coordinator = new WorkspaceReplayCoordinator({ onChange() {}, onError: error })
    coordinator.setMembers([{ id: 'p0', terminal }])
    coordinator.start('p0')
    terminal.moveReplayPick(1)
    terminal.commitReplayPick()
    await vi.waitFor(() => expect(coordinator.state().phase).toBe('active'))
    state.onTick({ ltp: 150, timeSec: 305 })
    coordinator.stop()
    expect(state.price.getData().at(-1)?.close).toBe(150)
    expect(coordinator.state().phase).toBe('idle')
    expect(error).not.toHaveBeenCalled()
    coordinator.destroy()
  })

  it('exports displayed OI, study and comparison data without future replay rows', async () => {
    const { terminal, state } = mount()
    await import('openalgo-charts/indicators')
    state.rawBars[1].oi = 0
    state.setPriceData()
    state.chart.addIndicator('sma', { length: 2 })
    comparisonController(state.chart, { mode: 'percentage', baseline: 'common' }).add({
      symbol: 'OTHER',
      bars: [bar(60, 10), bar(120, 11), bar(180, 12), bar(240, 13)],
    })
    await state.beginReplayAt(1)
    const rows = terminal.exportDataCsv().trim().split('\r\n')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toContain('volume,oi,indicator:')
    expect(rows[0]).toContain('comparison:1:OTHER:close')
    expect(rows[1]).toContain('60,99,102,98,100,100,,')
    expect(rows[2]).toContain('120,100,103,99,101,100,0,100.5,11')
    terminal.stopReplay()
  })
  it('refuses execution while a shared member owns the display even before the workspace callback', async () => {
    const { terminal, state } = mount()
    const place = vi.fn(async () => ({ orderId: 'fixture' }))
    Object.assign(state, { trade: { place } })
    await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: new AbortController().signal,
    })
    terminal.setReplayParticipation(1, true)
    await expect(
      terminal.placeTicket({
        symbol: 'BHEL',
        exchange: 'NSE',
        action: 'BUY',
        quantity: 1,
        product: 'MIS',
        pricetype: 'MARKET',
      })
    ).rejects.toThrow(/replay/i)
    expect(place).not.toHaveBeenCalled()
    terminal.restoreReplayMember(1)
  })
  it('commits the selected candle availability time and cancels exactly once', () => {
    const { terminal } = mount()
    const picked = vi.fn()
    const cancelled = vi.fn()
    expect(terminal.beginWorkspaceReplayPick(picked, cancelled)).toBe(true)
    terminal.moveReplayPick(2)
    terminal.commitReplayPick()
    expect(picked).toHaveBeenCalledWith(240)
    expect(cancelled).not.toHaveBeenCalled()
    expect(terminal.replayPickingBar()).toBe(false)
    expect(terminal.beginWorkspaceReplayPick(picked, cancelled)).toBe(true)
    terminal.cancelReplayPick()
    terminal.cancelReplayPick()
    expect(cancelled).toHaveBeenCalledOnce()
  })

  it('keeps live ticks out of a shared replay and restores their current values on exit', async () => {
    const { terminal, state } = mount()
    terminal.setWorkspaceReplayLocked(true)
    const prepared = await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: new AbortController().signal,
    })
    terminal.setReplayParticipation(1, true)
    const group = new ReplayGroup([prepared.member], {
      startTime: 180,
      onChange: (snapshot) => {
        for (const member of snapshot.members)
          terminal.setReplayParticipation(1, member.active, member.state)
      },
    })
    expect(state.price.getData().map((row) => row.time)).toEqual([60, 120])
    expect(terminal.replayActive()).toBe(true)
    expect(terminal.replayState()?.index).toBe(1)
    state.onTick({ ltp: 150, timeSec: 305 })
    expect(state.price.getData().at(-1)?.close).toBe(101)
    expect(state.rawBars.at(-1)?.close).toBe(150)
    group.destroy()
    terminal.restoreReplayMember(1)
    terminal.setWorkspaceReplayLocked(false)
    expect(terminal.replayActive()).toBe(false)
    expect(state.price.getData().at(-1)?.close).toBe(150)
  })

  it('recaptures an inactive member from its live series when scope expands', async () => {
    const a = mount()
    const b = mount()
    const signal = new AbortController().signal
    const first = await a.terminal.prepareReplayMember({ id: 'p0', sessionId: 1, signal })
    const second = await b.terminal.prepareReplayMember({ id: 'p1', sessionId: 1, signal })
    expect(second.member.options.bars).toBeUndefined()
    a.terminal.setReplayParticipation(1, true)
    const group = new ReplayGroup([first.member, second.member], {
      focusedId: 'p0',
      startTime: 180,
    })
    b.terminal.restoreReplayMember(1)
    b.state.onTick({ ltp: 160, timeSec: 305 })
    expect(b.state.price.getData()).toHaveLength(5)
    b.terminal.setReplayParticipation(1, true)
    group.setScope('all')
    group.seekTime(360)
    expect(b.state.price.getData().at(-1)?.close).toBe(160)
    group.destroy()
    a.terminal.restoreReplayMember(1)
    b.terminal.restoreReplayMember(1)
  })

  it('cancels pending preparation without letting an old completion release a newer session', async () => {
    const { terminal, state } = mount()
    state.interval = '5m'
    const history = deferred<Bar[]>()
    state.rest = { getBars: () => history.promise }
    const setPaused = vi.fn()
    Object.assign(state, { data: { setPaused, destroy() {} } })
    const old = new AbortController()
    const pending = terminal.prepareReplayMember({ id: 'p0', sessionId: 1, signal: old.signal })
    const refused = expect(pending).rejects.toThrow(/cancel|changed/i)
    expect(setPaused).toHaveBeenLastCalledWith(true)
    old.abort()
    terminal.restoreReplayMember(1)
    state.interval = '1m'
    await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 2,
      signal: new AbortController().signal,
    })
    terminal.setReplayParticipation(2, true)
    const count = setPaused.mock.calls.length
    history.resolve([])
    await refused
    terminal.restoreReplayMember(1)
    expect(setPaused).toHaveBeenCalledTimes(count)
    expect(terminal.replayActive()).toBe(true)
    terminal.restoreReplayMember(2)
    Object.assign(state, { data: null })
  })

  it('retains transformed candles without requesting raw intrabar replacements', async () => {
    const { terminal, state } = mount()
    state.ctype = 'heikin-ashi'
    state.interval = '5m'
    const getBars = vi.fn(async () => bars)
    state.rest = { getBars }
    const prepared = await terminal.prepareReplayMember({
      id: 'p0',
      sessionId: 1,
      signal: new AbortController().signal,
    })
    expect(getBars).not.toHaveBeenCalled()
    expect(prepared.member.options.subBars).toBeUndefined()
    terminal.restoreReplayMember(1)
  })

  it('invalidates the workspace before changing a terminal source', () => {
    const { terminal, state } = mount()
    const invalidate = vi.fn(() => {
      expect(state.interval).toBe('1m')
      terminal.setReplayInvalidationHandler(null)
    })
    terminal.setReplayInvalidationHandler(invalidate)
    terminal.setInterval('5m')
    expect(invalidate).toHaveBeenCalledOnce()
  })
})

describe('terminal comparison workspace integration', () => {
  it('releases primary resources when comparison cleanup reports an error', async () => {
    const { terminal, state } = mount()
    state.rest = { getBars: async () => bars }
    await terminal.addComparison('OTHER', 'NSE')
    const helper = (terminal as unknown as { comparisons: { destroy(): void } }).comparisons
    const release = helper.destroy.bind(helper)
    const failure = new Error('comparison cleanup failed')
    vi.spyOn(helper, 'destroy').mockImplementation(() => {
      release()
      throw failure
    })
    const destroyData = vi.fn()
    const closeSocket = vi.fn()
    Object.assign(state, { data: { destroy: destroyData }, ws: { close: closeSocket } })
    state.bookTimer = setInterval(() => {}, 5000)
    const chart = state.chart
    const destroyChart = vi.spyOn(chart, 'destroy')

    expect(() => terminal.destroy()).toThrow(failure)
    expect(destroyData).toHaveBeenCalledOnce()
    expect(closeSocket).toHaveBeenCalledOnce()
    expect(destroyChart).toHaveBeenCalledOnce()
    expect(state.bookTimer).toBeNull()
    expect(state.chart).toBeNull()
    await vi.runOnlyPendingTimersAsync()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not rebind queued comparisons while a newer symbol lookup is pending', async () => {
    const { terminal, state } = mount()
    const getBars = vi.fn(async () => bars)
    state.rest = { getBars }
    await terminal.addComparison('OTHER', 'NSE')
    getBars.mockClear()
    const lookup = deferred<{ data: Record<string, unknown> }>()
    vi.spyOn(terminal, 'api').mockReturnValue(lookup.promise)
    const bindings = terminal as unknown as {
      installComparisons(): void
      comparisonLoad: Promise<void>
    }
    bindings.installComparisons()
    const load = terminal.loadSymbol({ symbol: 'NEW', exchange: 'NSE' })
    try {
      await bindings.comparisonLoad
      expect(getBars).not.toHaveBeenCalled()
    } finally {
      terminal.destroy()
      lookup.resolve({ data: {} })
      await load
    }
  })

  it('marks comparison configuration dirty without treating history refreshes as workspace edits', async () => {
    const { terminal, state } = mount()
    state.rest = { getBars: async () => bars }
    const changed = vi.fn()
    const callbacks = (terminal as unknown as { cb: { onWorkspaceChange?: () => void } }).cb
    callbacks.onWorkspaceChange = changed
    await terminal.addComparison('OTHER', 'NSE')
    changed.mockClear()
    await terminal.addComparison('THIRD', 'NSE')
    expect(changed).toHaveBeenCalledOnce()
    terminal.setComparisonMode('price')
    expect(changed).toHaveBeenCalledTimes(2)
    await (
      terminal as unknown as { comparisons: { refresh(): Promise<void> } }
    ).comparisons.refresh()
    expect(changed).toHaveBeenCalledTimes(2)
    terminal.removeComparison(terminal.comparisonState().items[0].id)
    expect(changed).toHaveBeenCalledTimes(3)
  })

  it('refuses a comparison if replay starts while its chart binding is pending', async () => {
    const { terminal, state } = mount()
    const getBars = vi.fn(async () => bars)
    state.rest = { getBars }
    const pending = terminal.addComparison('OTHER', 'NSE')
    terminal.startReplay()
    await expect(pending).rejects.toThrow(/replay/i)
    expect(getBars).not.toHaveBeenCalled()
    expect(terminal.comparisonState().items).toHaveLength(0)
    terminal.cancelReplayPick()
  })

  it('refuses CSV while a replay start is being picked', () => {
    const { terminal } = mount()
    terminal.startReplay()
    expect(() => terminal.exportDataCsv()).toThrow(/select|replay|loading/i)
    terminal.cancelReplayPick()
    expect(terminal.exportDataCsv().trim().split('\r\n')).toHaveLength(5)
  })

  it('owns multiple comparisons, their common mode and complete workspace capture', async () => {
    const { terminal, state } = mount()
    state.rest = { getBars: async () => bars.map((row) => bar(row.time, row.close / 10)) }
    state.chart.setDataContext({
      symbol: state.sym.symbol,
      exchange: state.sym.exchange,
      interval: state.interval,
    })
    await terminal.addComparison('OTHER', 'NSE')
    await terminal.addComparison('THIRD', 'NSE')
    terminal.setComparisonMode('percentage')
    expect(terminal.comparisonState()).toMatchObject({
      mode: 'percentage',
      items: [
        { symbol: 'OTHER', exchange: 'NSE', status: 'ready' },
        { symbol: 'THIRD', exchange: 'NSE', status: 'ready' },
      ],
    })
    const before = terminal.captureWorkspacePane('p0')
    expect(before.comparisonMode).toBe('percent')
    expect(before.chart.panes?.[0].priceScale.mode).toBe('linear')
    expect(before.comparisons.map((item) => item.symbol)).toEqual(['OTHER', 'THIRD'])
    terminal.removeComparison(terminal.comparisonState().items[0].id)
    const after = terminal.captureWorkspacePane('p0')
    expect(after.comparisons.map((item) => item.symbol)).toEqual(['THIRD'])
    expect(before.comparisons).toHaveLength(2)
    expect(terminal.exportDataCsv().split('\r\n')[0]).toContain('comparison:1:THIRD:close')
    expect(state.price.getData().map((row) => row.close)).toEqual([100, 101, 102, 103])
  })
})

describe('selected candle readout', () => {
  it.each([
    false,
    true,
  ])('explains absent OI without claiming a warmup shortage (capability %s)', async (supported) => {
    const { state, terminal } = mount()
    state.sym.hasOpenInterest = supported
    const toast = vi.fn()
    const host = terminal as unknown as {
      cb: { onToast: typeof toast }
      warnIfStarved(inst: unknown): void
    }
    host.cb.onToast = toast
    await import('openalgo-charts/indicators')
    const study = state.chart.addIndicator('open-interest', {})
    host.warnIfStarved(study)

    expect(toast).toHaveBeenCalledWith(
      supported
        ? 'The loaded history contains no open interest readings.'
        : 'Open interest is not available for this instrument.',
      ''
    )
  })

  it('treats zero OI as a reading and retains ordinary study warmup feedback', async () => {
    const { state, terminal } = mount()
    state.rawBars = state.rawBars.map((row) => ({ ...row, oi: 0 }))
    state.setPriceData()
    const toast = vi.fn()
    const host = terminal as unknown as {
      cb: { onToast: typeof toast }
      warnIfStarved(inst: unknown): void
    }
    host.cb.onToast = toast
    await import('openalgo-charts/indicators')
    host.warnIfStarved(state.chart.addIndicator('open-interest', {}))
    expect(toast).not.toHaveBeenCalled()
    host.warnIfStarved(state.chart.addIndicator('sma', { length: 100 }))
    expect(toast).toHaveBeenCalledWith(expect.stringMatching(/needs more history/), '')
  })

  it('repaints the saved OI readout after asynchronous settings restoration', async () => {
    const { state, terminal, legendEl } = mount()
    state.rawBars = state.rawBars.map((bar) => ({ ...bar, oi: 12000 }))
    state.buildChart()
    await terminal.applyChartSettings({ 'statusLine.openInterest': true })
    expect(legendEl.textContent).toContain(' OI 12.00K')
    state.buildChart()
    await vi.dynamicImportSettled()
    expect(legendEl.textContent).toContain(' OI 12.00K')
  })

  it('retains OI capability and the selected reading through live gaps and rebuilds', async () => {
    const { state, terminal, container, legendEl } = mount()
    state.rawBars = state.rawBars.map((bar, i) => ({ ...bar, oi: i === 1 ? 0 : 1000 + i }))
    state.builder.seed(state.rawBars[3])
    state.buildChart()
    state.chart.applySize(800, 600)
    expect(state.chart.hasOpenInterest).toBe(true)
    expect(legendEl.textContent).not.toContain(' OI ')
    await terminal.applyChartSettings({ 'statusLine.openInterest': true })
    expect(legendEl.textContent).toContain(' OI 1.00K')
    container.dispatchEvent(
      new MouseEvent('pointermove', {
        clientX: state.chart.timeScale.indexToX(1),
        clientY: 200,
      })
    )
    expect(legendEl.textContent).toContain(' OI 0')
    state.onTick({ ltp: 150, timeSec: 245 })
    expect(legendEl.textContent).toContain(' OI 0')
    container.dispatchEvent(new MouseEvent('pointerleave'))
    expect(legendEl.textContent).not.toContain(' OI ')
    expect(state.price.getData().at(-1)?.oi).toBeUndefined()
    state.buildChart()
    expect(state.chart.hasOpenInterest).toBe(true)
    await vi.dynamicImportSettled()
    expect(state.chart.statusLineOptions().openInterest).toBe(true)
    state.sym = { ...state.sym, symbol: 'NIFTY', exchange: 'NSE_INDEX', quoteOnly: true }
    state.buildChart()
    expect(state.chart.hasOpenInterest).toBe(false)
    const settings = await terminal.chartSettings()
    const field = settings?.tabs
      .flatMap((tab) => tab.inputs)
      .find((field) => field.key === 'statusLine.openInterest')
    expect(field).toHaveProperty('unavailable', 'Open interest is unavailable for this instrument.')
    expect(settings?.values['statusLine.openInterest']).toBe(true)
  })

  it('does not move the replay picker in response to a linked readout', () => {
    const { state, terminal } = mount()
    state.buildChart()
    state.chart.applySize(800, 600)
    terminal.startReplay()
    const selected = terminal.replayPickBar()
    state.chart.setLinkedCrosshairIndex(2)
    expect(terminal.replayPickBar()).toEqual(selected)
  })

  it('keeps the hovered candle through ticks and history replacement, then follows latest on leave', () => {
    const { state, container, legendEl } = mount()
    state.buildChart()
    state.chart.applySize(800, 600)
    const move = (index: number) =>
      container.dispatchEvent(
        new MouseEvent('pointermove', {
          clientX: state.chart.timeScale.indexToX(index),
          clientY: 200,
        })
      )
    move(1)
    expect(legendEl.textContent).toContain('C 101.00')
    state.onTick({ ltp: 150, timeSec: 245 })
    expect(legendEl.textContent).toContain('C 101.00')
    state.rawBars = [
      bar(0, 99),
      ...state.rawBars.map((b) => (b.time === 120 ? { ...b, close: 111 } : b)),
    ]
    state.setPriceData()
    expect(legendEl.textContent).toContain('C 111.00')
    container.dispatchEvent(new MouseEvent('pointerleave'))
    expect(legendEl.textContent).toContain('C 150.00')
  })

  it('uses only displayed replay bars when the pointer is outside the data', async () => {
    const { state, terminal, legendEl } = mount()
    await state.beginReplayAt(1)
    expect(legendEl.textContent).toContain('C 101.00')
    terminal.replayStep()
    expect(legendEl.textContent).toContain('C 102.00')
    terminal.stopReplay()
    expect(legendEl.textContent).toContain('C 103.00')
  })
})

describe('built-in volume and average', () => {
  it.each([
    'NSE_INDEX',
    'BSE_INDEX',
    'MCX_INDEX',
    'GLOBAL_INDEX',
  ])('hides index volume and its average on %s without losing the user preference', async (exchange) => {
    const { terminal, state } = mount()
    state.sym.exchange = exchange
    state.sym.quoteOnly = true
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 2 })
    terminal.setVolumeVisible(true)
    expect(
      state.chart
        .getState()
        .series.filter((s) => s.priceScaleId === '')
        .every((s) => s.style.visible === false)
    ).toBe(true)
    expect(terminal.volumeVisible()).toBe(true)
    state.sym.exchange = 'NFO'
    state.sym.synthetic = true
    terminal.setVolumeVisible(true)
    expect(
      state.chart
        .getState()
        .series.filter((s) => s.priceScaleId === '')
        .every((s) => s.style.visible === true)
    ).toBe(true)
  })

  it('follows candle colours and corrects direction on a live replacement', () => {
    const { state } = mount()
    state.price.applyOptions({ upColor: '#00aa00', downColor: '#aa0000' })
    state.rawBars[1] = { ...state.rawBars[1], open: 105, close: 101 }
    state.setPriceData()
    expect(state.volume.getData().map((b) => b.color)).toEqual([
      '#00aa00',
      '#aa0000',
      '#00aa00',
      '#00aa00',
    ])
    const update = { ...state.rawBars[3], open: 105, close: 102 }
    state.rawBars[3] = update
    state.updateLiveBar(update)
    expect(state.volume.getData()[3].color).toBe('#aa0000')
  })

  it('exposes volume controls and updates a configurable average on the volume scale', async () => {
    const { terminal, state } = mount()
    state.rawBars = state.rawBars.map((b, i) => ({ ...b, volume: [10, 20, 30, 60][i] }))
    state.setPriceData()
    const settings = await terminal.chartSettings()
    expect(settings?.tabs.find((tab) => tab.id === 'volume')).toBeDefined()
    expect(settings?.defaults['volume.showMA']).toBe(false)
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 3 })
    expect(state.volumeMA).toBeTruthy()
    const average = () => state.volumeMA!.getData().map((b) => b.close)
    expect(average().slice(0, 3)).toEqual([NaN, NaN, 20])
    expect(average()[3]).toBeCloseTo(110 / 3)
    expect(state.volumeMA!.priceScale()).toBe(state.volume.priceScale())
    state.rawBars[3] = { ...state.rawBars[3], volume: 90 }
    state.updateLiveBar(state.rawBars[3])
    expect(average()[3]).toBeCloseTo(140 / 3)
    terminal.setVolumeVisible(false)
    const lines = state.chart
      .panes()[0]
      .series()
      .filter((series) => series.type === 'line')
    expect(lines.some((series) => series.style.visible === false)).toBe(true)
  })

  it('recomputes settings against only the replay prefix and restores live volume on exit', async () => {
    const { terminal, state } = mount()
    state.rawBars = state.rawBars.map((b, i) => ({ ...b, volume: [10, 20, 30, 600][i] }))
    state.setPriceData()
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 2 })
    await state.beginReplayAt(1)
    expect(state.volumeMA?.getData().map((b) => b.close)).toEqual([NaN, 15])
    await terminal.applyChartSettings({ 'volume.maPeriod': 1 })
    expect(state.volumeMA?.getData().map((b) => b.close)).toEqual([10, 20])
    terminal.replayStep()
    expect(state.volumeMA?.getData().map((b) => b.close)).toEqual([10, 20, 30])
    terminal.stopReplay()
    expect(state.volumeMA?.getData().map((b) => b.close)).toEqual([10, 20, 30, 600])
  })

  it('follows custom candle colours after settings changes without refetching history', async () => {
    const { terminal, state } = mount()
    await terminal.applyChartSettings({ 'symbol.upColor': '#112233' })
    expect(state.volume.getData()[0].color).toBe('#112233')
    state.price.applyOptions({
      colorByPreviousClose: true,
      upColor: '#00aa00',
      downColor: '#aa0000',
    })
    state.rawBars[1] = { ...state.rawBars[1], open: 90, close: 99 }
    state.setPriceData()
    expect(state.volume.getData()[1].color).toBe('#aa0000')
  })

  it.each([
    'heikin-ashi',
    'renko',
  ])('preserves transformed volume and colours for %s', async (ctype) => {
    const { terminal, state } = mount()
    state.ctype = ctype
    state.rawBars = state.rawBars.map((b, i) => ({ ...b, volume: [10, 20, 30, 60][i] }))
    state.setPriceData()
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 1 })
    const prices = state.price.getData()
    const volumes = state.volume.getData()
    expect(volumes.length).toBeGreaterThan(1)
    expect(volumes.reduce((total, b) => total + b.close, 0)).toBe(120)
    expect(volumes.map((b) => b.time)).toEqual(prices.map((b) => b.time))
    const style = state.chart.primarySeriesInfo()!.style
    const theme = state.chart.theme()
    expect(volumes.map((b) => b.color)).toEqual(
      prices.map((b) =>
        b.close >= b.open ? (style.upColor ?? theme.upColor) : (style.downColor ?? theme.downColor)
      )
    )
    await state.beginReplayAt(1)
    expect(state.volumeMA!.getData().map((b) => b.close)).toEqual(
      volumes.slice(0, 2).map((b) => b.close)
    )
  })

  it('uses only the formed sub-bars for replay volume and its average', async () => {
    const { terminal, state } = mount()
    state.interval = '5m'
    state.rawBars = [bar(300, 101, 50), bar(600, 102, 500), bar(900, 103, 5000)]
    state.rest = {
      getBars: async () =>
        Array.from({ length: 15 }, (_, i) =>
          bar(300 + i * 60, 100 + i, i < 5 ? 10 : i < 10 ? 100 : 1000)
        ),
    }
    state.setPriceData()
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 2 })
    await state.beginReplayAt(0)
    terminal.replayStep()
    expect(terminal.replayState()?.subSteps).toBe(5)
    expect(state.volume.getData().map((b) => b.close)).toEqual([50, 100])
    expect(state.volumeMA!.getData().map((b) => b.close)).toEqual([NaN, 75])
    terminal.replayStep()
    expect(state.volume.getData().map((b) => b.close)).toEqual([50, 200])
    expect(state.volumeMA!.getData().map((b) => b.close)).toEqual([NaN, 125])
    terminal.replaySeek(0)
    expect(state.volume.getData().map((b) => b.close)).toEqual([50])
    expect(state.volumeMA!.getData().map((b) => b.close)).toEqual([NaN])
  })

  it('appends live averages and clears stored overrides when resetting defaults', async () => {
    const { terminal, state } = mount()
    await terminal.applyChartSettings({ 'volume.showMA': true, 'volume.maPeriod': 2 })
    const next = bar(300, 101, 400)
    state.rawBars.push(next)
    state.updateLiveBar(next)
    expect(state.volumeMA!.getData().at(-1)?.close).toBe(250)
    await terminal.applyChartSettings({ 'volume.colorByDirection': false })
    expect(state.volume.getData().every((b) => b.color === undefined)).toBe(true)
    const defaults = (await terminal.chartSettings())!.defaults
    await terminal.applyChartSettings(
      Object.fromEntries(Object.entries(defaults).filter(([key]) => key.startsWith('volume.')))
    )
    expect(
      Object.keys(state.chartSettingsSaved).filter((key) => key.startsWith('volume.'))
    ).toEqual([])
    expect(state.volumeMA!.getData()).toEqual([])
  })
})

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
    // The seed was the previous bar and this tick opened the next bucket, so
    // the open is only the first price seen: history keeps the true one.
    expect(pushBar).toHaveBeenCalledWith(
      expect.objectContaining({ time: sessionOpen + 60 * 60, close: 104, volume: 0 }),
      { provisional: true }
    )
  })
})

describe('a combination stays live', () => {
  // The chart of `CE+PE` used to be static: legs fetched once, folded once, no
  // subscription. It now holds one LTP stream per leg and folds every tick
  // into the combined series through the same builder and pushBar path an
  // instrument uses, so the repair after each bar closes applies to it too.
  const T = Date.UTC(2026, 8, 16, 4, 15) / 1000 // 09:45 IST, a minute boundary
  const leg = (time: number, close: number) => ({
    time,
    open: close,
    high: close,
    low: close,
    close,
  })

  function wire() {
    const { state } = mount()
    const subscribe = vi.fn()
    const unsubscribe = vi.fn()
    let onLtp:
      | ((e: { symbol: string; exchange: string; ltp: number; timeSec: number }) => void)
      | undefined
    state.ws = {
      onLtp: (cb: typeof onLtp) => {
        onLtp = cb
        return () => {}
      },
      onDepth: () => () => {},
      subscribe,
      unsubscribe,
    }
    const pushBar = vi.fn()
    state.data = { pushBar, destroy() {} } as unknown as NonNullable<TerminalState['data']>
    state.interval = '1m'
    state.exprLegExchange = 'NFO'
    state.expr = parseExpression('NIFTY22SEP2623200CE+NIFTY22SEP2623200PE')
    state.exprFeed = {
      legBars: {
        NIFTY22SEP2623200CE: [leg(T - 60, 99), leg(T, 100)],
        NIFTY22SEP2623200PE: [leg(T - 60, 199), leg(T, 200)],
      },
    }
    state.sym = {
      ...state.sym,
      symbol: 'NIFTY22SEP2623200CE+NIFTY22SEP2623200PE',
      exchange: '',
      quoteOnly: true,
      synthetic: true,
    }
    return {
      state,
      subscribe,
      unsubscribe,
      pushBar,
      tick: (e: NonNullable<typeof onLtp> extends (e: infer E) => void ? E : never) => onLtp?.(e),
    }
  }

  it('subscribes LTP for every leg and folds each tick with the other legs latest price', () => {
    const { state, subscribe, pushBar, tick } = wire()
    state.rawBars = [leg(T - 60, 298), leg(T, 300)]
    state.connectExpressionLive(state.expr!)
    expect(subscribe.mock.calls).toEqual([
      ['LTP', 'NIFTY22SEP2623200CE', 'NFO'],
      ['LTP', 'NIFTY22SEP2623200PE', 'NFO'],
    ])
    // Only the call leg ticks: the put is still at the close its history ended on.
    tick({ symbol: 'NIFTY22SEP2623200CE', exchange: 'NFO', ltp: 101, timeSec: T + 10 })
    expect(pushBar).toHaveBeenLastCalledWith(
      expect.objectContaining({ time: T, close: 301, open: 300 })
    )
    tick({ symbol: 'NIFTY22SEP2623200PE', exchange: 'NFO', ltp: 205, timeSec: T + 20 })
    expect(pushBar).toHaveBeenLastCalledWith(
      expect.objectContaining({ time: T, close: 306, high: 306, low: 300 })
    )
    // A tick for an instrument that is not a leg is ignored.
    tick({ symbol: 'NIFTY29SEP26FUT', exchange: 'NFO', ltp: 23000, timeSec: T + 30 })
    expect(pushBar).toHaveBeenCalledTimes(2)
    expect(state.rawBars.at(-1)).toMatchObject({ time: T, close: 306 })
  })

  it('preserves reconciled combined volume when a price-only leg quote arrives', () => {
    const { state, tick } = wire()
    state.rawBars = [{ ...leg(T, 300), volume: 2500 }]
    state.connectExpressionLive(state.expr!)
    tick({ symbol: 'NIFTY22SEP2623200CE', exchange: 'NFO', ltp: 105, timeSec: T + 10 })
    expect(state.rawBars.at(-1)).toMatchObject({ close: 305, volume: 2500 })
    expect(state.price.getData().at(-1)).toMatchObject({ close: 305, volume: 2500 })
  })

  it('opens the current bucket provisionally when the folded history stopped one bar short', () => {
    const { state, pushBar, tick } = wire()
    state.rawBars = [leg(T - 120, 296), leg(T - 60, 298)]
    state.connectExpressionLive(state.expr!)
    tick({ symbol: 'NIFTY22SEP2623200PE', exchange: 'NFO', ltp: 210, timeSec: T + 5 })
    expect(pushBar).toHaveBeenLastCalledWith(
      expect.objectContaining({ time: T, open: 310, close: 310 }),
      { provisional: true }
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
    // Pointer identity is part of the gesture contract; MouseEvent omits it.
    const pointer = (type: 'pointerdown' | 'pointerup') =>
      new PointerEvent(type, {
        pointerId: 1,
        pointerType: 'mouse',
        isPrimary: true,
        button: 0,
        buttons: type === 'pointerdown' ? 1 : 0,
        clientX: 10,
        clientY: 20,
      })

    container.dispatchEvent(pointer('pointerdown'))
    container.dispatchEvent(pointer('pointerup'))
    expect(commit).toHaveBeenCalledOnce()

    terminal.destroy()
    container.dispatchEvent(pointer('pointerdown'))
    container.dispatchEvent(pointer('pointerup'))
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
