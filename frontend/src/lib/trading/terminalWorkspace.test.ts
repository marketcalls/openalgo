import type { WorkspaceChartState } from 'openalgo-charts/workspace'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type TerminalCallbacks, type TerminalOptions, TradingTerminal } from './terminal'

const terminals: TradingTerminal[] = []
function terminal(preferences?: Pick<Storage, 'getItem' | 'setItem'> | null) {
  const callbacks: TerminalCallbacks = {
    onReady: vi.fn(),
    onToast: vi.fn(),
    onWsState: vi.fn(),
    onSymbolLoaded: vi.fn(),
    onLtp: vi.fn(),
  }
  const options = {
    apiKey: 'test',
    wsUrl: 'ws://test',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    storageKey: 'oa-trading-p0',
    getTheme: () => ({ mode: 'dark' as const, appMode: 'live' as const }),
    callbacks,
    ...(preferences === undefined ? {} : { preferences }),
  } satisfies TerminalOptions
  const instance = new TradingTerminal(options)
  terminals.push(instance)
  return { instance, callbacks }
}

beforeEach(() => localStorage.clear())
afterEach(() => {
  for (const instance of terminals.splice(0)) instance.destroy()
  vi.restoreAllMocks()
})

describe('workspace pane preference ownership', () => {
  it('announces changed chart configuration without treating execution preferences as workspace edits', () => {
    const { instance, callbacks } = terminal()
    callbacks.onWorkspaceChange = vi.fn()
    instance.setGrid(false, true)
    expect(callbacks.onWorkspaceChange).toHaveBeenCalledOnce()
    instance.setGrid(false, true)
    instance.setArmed(true)
    instance.setQty(10)
    instance.setProduct('MIS')
    expect(callbacks.onWorkspaceChange).toHaveBeenCalledOnce()
    instance.setDrawStay(true)
    expect(callbacks.onWorkspaceChange).toHaveBeenCalledTimes(2)
    instance.destroy()
    instance.setGrid(true, true)
    expect(callbacks.onWorkspaceChange).toHaveBeenCalledTimes(2)
  })
  it('locks every terminal order ticket throughout an external grid transition', async () => {
    const { instance } = terminal(null)
    const place = vi.fn(async () => ({ orderId: 'fixture-order' }))
    Object.assign(instance, { trade: { place } })
    const order = {
      symbol: 'BHEL',
      exchange: 'NSE',
      action: 'BUY',
      quantity: 1,
      product: 'MIS',
      pricetype: 'MARKET',
    } as const
    instance.setWorkspaceTransitionLocked(true)
    await expect(instance.placeTicket(order)).rejects.toThrow(/workspace.*loading/i)
    expect(place).not.toHaveBeenCalled()
    instance.setWorkspaceTransitionLocked(false)
    await expect(instance.placeTicket(order)).resolves.toEqual({ orderId: 'fixture-order' })
    expect(place).toHaveBeenCalledTimes(1)
  })

  it('locks order tickets while replay history is loading', async () => {
    const { instance } = terminal(null)
    const place = vi.fn(async () => ({ orderId: 'fixture-order' }))
    Object.assign(instance, { trade: { place }, replayLoading: true })
    await expect(
      instance.placeTicket({
        symbol: 'BHEL',
        exchange: 'NSE',
        action: 'BUY',
        quantity: 1,
        product: 'MIS',
        pricetype: 'MARKET',
      })
    ).rejects.toThrow(/replay/i)
    expect(place).not.toHaveBeenCalled()
  })

  it('announces the replay loading lock before awaiting finer history and releases it on cancellation', async () => {
    const { instance, callbacks } = terminal(null)
    const paused = vi.fn()
    let resolve!: (bars: unknown) => void
    const pending = new Promise((done) => {
      resolve = done
    })
    const bar = { time: 1000, open: 100, high: 100, low: 100, close: 100 }
    callbacks.onReplayChange = vi.fn()
    Object.assign(instance, {
      chart: { panes: () => [], destroy() {} },
      price: {},
      shownBars: [bar, { ...bar, time: 1060 }],
      data: { setPaused: paused, destroy() {} },
      loadReplaySubBars: () => pending,
    })
    const start = (
      instance as unknown as { beginReplayAt(index: number): Promise<void> }
    ).beginReplayAt(0)
    expect((instance as unknown as { replayLoading: boolean }).replayLoading).toBe(true)
    expect(callbacks.onReplayChange).toHaveBeenCalledWith(null)
    instance.stopReplay()
    resolve([])
    await start
    expect(instance.replayActive()).toBe(false)
    expect((instance as unknown as { replayLoading: boolean }).replayLoading).toBe(false)
    expect(paused).toHaveBeenLastCalledWith(false)
    Object.assign(instance, { chart: null, price: null, data: null })
  })

  it('refuses a stale ticket after its grid has been destroyed', async () => {
    const { instance } = terminal(null)
    const place = vi.fn(async () => ({ orderId: 'fixture-order' }))
    Object.assign(instance, { trade: { place } })
    instance.destroy()
    await expect(
      instance.placeTicket({
        symbol: 'BHEL',
        exchange: 'NSE',
        action: 'BUY',
        quantity: 1,
        product: 'MIS',
        pricetype: 'MARKET',
      })
    ).rejects.toThrow(/closed/i)
    expect(place).not.toHaveBeenCalled()
  })

  it('prepares a pane with isolated preferences without rewriting the visible grid', () => {
    localStorage.setItem('oa-trading-p0-magnet', '1')
    const staged = new Map([
      ['oa-trading-p0-magnet', '0'],
      ['oa-trading-p0-vol', '0'],
    ])
    const preferences = {
      getItem: (key: string) => staged.get(key) ?? null,
      setItem: (key: string, value: string) => {
        staged.set(key, value)
      },
    }
    const { instance } = terminal(preferences)
    expect(instance.drawStats().magnet).toBe(false)
    expect(instance.volumeVisible()).toBe(false)
    instance.setDrawStay(true)
    expect(staged.get('oa-trading-p0-stay')).toBe('1')
    expect(localStorage.getItem('oa-trading-p0-stay')).toBeNull()
    expect(localStorage.getItem('oa-trading-p0-magnet')).toBe('1')
  })

  it('keeps ordinary browser preferences and the existing primary-pane migration', () => {
    localStorage.setItem('-magnet', '1')
    const { instance } = terminal()
    expect(instance.drawStats().magnet).toBe(true)
    instance.setMagnet(false)
    expect(localStorage.getItem('oa-trading-p0-magnet')).toBe('0')
    expect(localStorage.getItem('-magnet')).toBe('1')
  })

  it('can explicitly disable preference persistence for a transient pane', () => {
    localStorage.setItem('oa-trading-p0-magnet', '1')
    const { instance } = terminal(null)
    expect(instance.drawStats().magnet).toBe(false)
    instance.setMagnet(true)
    instance.setDrawStay(true)
    expect(localStorage.getItem('oa-trading-p0-stay')).toBeNull()
  })

  it('keeps chart controls usable when browser preference reads are blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('Storage blocked')
    })
    const { instance, callbacks } = terminal()
    expect(instance.drawStats().magnet).toBe(false)
    expect(instance.volumeVisible()).toBe(true)
    expect(callbacks.onToast).toHaveBeenCalledTimes(1)
    expect(callbacks.onToast).toHaveBeenCalledWith(
      expect.stringMatching(/preferences.*unavailable/i),
      'err'
    )
  })

  it('reports failed writes once while keeping the in-memory controls usable', () => {
    const { instance, callbacks } = terminal()
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('Quota reached')
    })
    instance.setMagnet(true)
    instance.setDrawStay(true)
    expect(instance.drawStats()).toMatchObject({ magnet: true, stay: true })
    expect(callbacks.onToast).toHaveBeenCalledTimes(1)
    expect(callbacks.onToast).toHaveBeenCalledWith(
      expect.stringMatching(/preferences.*saved/i),
      'err'
    )
  })
})

function configuredPane() {
  const state: WorkspaceChartState = {
    version: 1,
    timezone: 'Asia/Kolkata',
    viewport: { from: 5, to: 80 },
    grid: { vertLines: false, horzLines: true },
    crosshairSnapToBar: true,
    indicators: [
      {
        indicatorId: 'ema',
        settings: { period: 9, 'plot.ema.color': '#f80' },
        paneIndex: 0,
        visible: true,
      },
      {
        indicatorId: 'ema',
        settings: { period: 9, 'plot.ema.color': '#f80' },
        paneIndex: 0,
        visible: false,
      },
    ],
  }
  const context = { symbol: 'BHEL', exchange: 'NSE', interval: '15m' }
  const fields = {
    chart: { getState: () => structuredClone(state), getDataContext: () => context },
    sym: { symbol: 'BHEL', exchange: 'NSE' },
    interval: '15m',
    ctype: 'candlestick',
    chartSettingsSaved: { 'volume.showMA': true, 'volume.maPeriod': 20, apiKey: 'private' },
    volumeOn: true,
    drawMagnet: true,
    drawStay: false,
    draw: null,
    drawEnabled: false,
    drawLegacy: null,
    drawJson: {
      version: 2,
      drawings: [
        {
          id: 'line1',
          tool: 'trend',
          anchors: [{ time: 100, price: 10 }],
          style: { color: '#08f' },
        },
      ],
    },
    restoringIndicatorsOn: null,
    destroyed: false,
    replay: null,
    replayPicking: false,
    apiKey: 'private',
    armed: true,
    qty: 50,
    product: 'MIS',
    orderLines: new Map([['live', {}]]),
  }
  const pane = Object.assign(Object.create(TradingTerminal.prototype), fields) as TradingTerminal
  return { pane, fields, state, context }
}

describe('complete workspace pane capture', () => {
  it('captures detached chart and host configuration without execution data', () => {
    const { pane, state } = configuredPane()
    const saved = pane.captureWorkspacePane('p0')
    expect(saved).toMatchObject({
      id: 'p0',
      symbol: 'BHEL',
      exchange: 'NSE',
      interval: '15m',
      chartType: 'candlestick',
      volume: true,
      magnet: 'strong',
      stay: false,
      comparisons: [],
    })
    expect(saved.chart).toMatchObject(state)
    expect(saved.chart.drawings).toMatchObject({ drawings: [{ id: 'line1' }] })
    expect(saved.settings).toEqual({ 'volume.showMA': true, 'volume.maPeriod': 20 })
    state.indicators![0].settings.period = 100
    expect(saved.chart.indicators![0].settings.period).toBe(9)
    expect(saved.chart.indicators).toHaveLength(2)
    expect(JSON.stringify(saved)).not.toMatch(/private|apiKey|armed|orderLines|product|"qty"/)
  })

  it('refuses a new instrument or interval while the old chart is still displayed', () => {
    const { pane, context } = configuredPane()
    context.interval = '5m'
    expect(() => pane.captureWorkspacePane('p0')).toThrow(/loading|changed/i)
    context.interval = '15m'
    context.symbol = 'OTHER'
    expect(() => pane.captureWorkspacePane('p0')).toThrow(/loading|changed/i)
  })

  it.each([
    { destroyed: true },
    { chart: null },
    { sym: null },
    { replay: {} },
    { replayPicking: true },
    { drawEnabled: true },
    { drawLegacy: [] },
  ])('refuses unavailable or transient configurations: %j', (patch) => {
    const { pane } = configuredPane()
    Object.assign(pane, patch)
    expect(() => pane.captureWorkspacePane('p0')).toThrow(/available|replay|loading/i)
  })

  it('waits for asynchronous study restoration before allowing a save', () => {
    const { pane, fields } = configuredPane()
    Object.assign(pane, { restoringIndicatorsOn: fields.chart })
    expect(() => pane.captureWorkspacePane('p0')).toThrow(/studies|loading/i)
  })
})
