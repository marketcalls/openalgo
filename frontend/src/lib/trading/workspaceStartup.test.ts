import { DataLoadingController, OpenAlgoWsFeed } from 'openalgo-charts'
import type { WorkspacePane } from 'openalgo-charts/workspace'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type TerminalOptions, TradingTerminal } from './terminal'

function saved(): WorkspacePane {
  return {
    id: 'p0',
    symbol: 'BHEL',
    exchange: 'NSE',
    interval: '15m',
    chartType: 'candlestick',
    chart: {
      version: 1,
      viewport: { from: 10, to: 40 },
      indicators: [],
      drawings: { version: 2, drawings: [] },
    },
    settings: {},
    volume: false,
    magnet: 'weak',
    stay: true,
    comparisons: [],
    comparisonMode: 'price',
  }
}
const terminals: TradingTerminal[] = []
function create(initialWorkspacePane = saved()) {
  const callbacks = {
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
    storageKey: 'staged-p0',
    getTheme: () => ({ mode: 'dark' as const, appMode: 'live' as const }),
    callbacks,
    initialWorkspacePane,
  }
  const terminal = new TradingTerminal(options as TerminalOptions)
  terminals.push(terminal)
  const chart = {
    on: vi.fn(() => () => {}),
    emit: vi.fn(),
    primaryBars: () => [],
    timezone: () => 'Asia/Kolkata',
    alertState: () => initialWorkspacePane.chart.alerts,
    setAlertState: vi.fn(),
    panes: () => [{}],
    getDataContext: () => ({ symbol: 'BHEL', exchange: 'NSE', interval: '15m' }),
    restoreState: vi.fn(() => ({
      applied: true,
      indicators: 0,
      series: initialWorkspacePane.chart.series ?? [],
    })),
    destroy: vi.fn(),
  }
  Object.assign(terminal, {
    loadIndicators: vi.fn(async () => {}),
    restoreChartSettings: vi.fn(async () => {}),
    syncIndicators: vi.fn(),
    pollBook: vi.fn(),
  })
  const api = vi.spyOn(terminal, 'api').mockResolvedValue({ data: { minutes: ['5m', '15m'] } })
  const search = vi
    .spyOn(terminal, 'search')
    .mockResolvedValue([{ symbol: 'BHEL', exchange: 'NSE' }])
  const load = vi.spyOn(terminal, 'loadSymbol').mockImplementation(async () => {
    Object.assign(terminal, { chart, sym: { symbol: 'BHEL', exchange: 'NSE' } })
    return true
  })
  return { terminal, callbacks, chart, api, search, load }
}
beforeEach(() => {
  localStorage.clear()
  vi.spyOn(OpenAlgoWsFeed.prototype, 'connect').mockImplementation(() => {})
  vi.spyOn(OpenAlgoWsFeed.prototype, 'subscribeOrders').mockImplementation(() => {})
})
afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('prepared terminal startup', () => {
  it('restores host series styles while keeping volume and its average switched off', async () => {
    const input = saved()
    input.chart.series = [
      { type: 'candlestick', paneIndex: 0, priceScaleId: 'right', style: { upColor: '#008800' } },
      {
        type: 'histogram',
        paneIndex: 0,
        priceScaleId: '',
        style: { color: '#ff8800', visible: true },
      },
      { type: 'line', paneIndex: 0, priceScaleId: '', style: { color: '#0088ff', visible: true } },
    ]
    const { terminal } = create(input)
    const price = { applyOptions: vi.fn() },
      volume = { applyOptions: vi.fn() },
      volumeMA = { applyOptions: vi.fn() }
    Object.assign(terminal, { price, volume, volumeMA })
    await terminal.init()
    expect(price.applyOptions).toHaveBeenCalledWith({ upColor: '#008800' })
    expect(volume.applyOptions).toHaveBeenLastCalledWith({ visible: false })
    expect(volumeMA.applyOptions).toHaveBeenLastCalledWith({ visible: false })
  })

  it('refuses an order during preparation with the reason for this lock', async () => {
    const { terminal } = create()
    const place = vi.fn()
    Object.assign(terminal, { trade: { place } })
    await expect(
      terminal.placeTicket({
        symbol: 'BHEL',
        exchange: 'NSE',
        action: 'BUY',
        quantity: 1,
        product: 'MIS',
        pricetype: 'MARKET',
      })
    ).rejects.toThrow(/workspace.*loading/i)
    expect(place).not.toHaveBeenCalled()
  })

  it('releases each prepared data owner, socket and timer on failure', async () => {
    vi.useFakeTimers()
    const close = vi.spyOn(OpenAlgoWsFeed.prototype, 'close')
    const dispose = vi.spyOn(DataLoadingController.prototype, 'destroy')
    const remove = vi.spyOn(document, 'removeEventListener')
    const { terminal, load } = create()
    load.mockResolvedValue(false)
    await expect(terminal.init()).rejects.toThrow(/history/)
    terminal.destroy()
    expect(close).toHaveBeenCalledTimes(1)
    expect(dispose).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
  })

  it('requires authoritative metadata for the requested symbol before fetching history', async () => {
    const { terminal, api, load } = create()
    load.mockRestore()
    const history = vi.fn()
    Object.assign(terminal, { rest: { getBars: history } })
    api.mockRejectedValueOnce(new Error('Symbol unavailable'))
    await expect(
      terminal.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' }, { strict: true })
    ).rejects.toThrow(/Symbol unavailable/)
    api.mockResolvedValueOnce({ data: { symbol: 'OTHER', exchange: 'NSE' } })
    await expect(
      terminal.loadSymbol({ symbol: 'BHEL', exchange: 'NSE' }, { strict: true })
    ).rejects.toThrow(/metadata/)
    expect(history).not.toHaveBeenCalled()
  })

  it('restores a valid drawing against the chart pane list', async () => {
    const input = saved()
    input.chart.drawings = {
      version: 2,
      drawings: [
        {
          id: 'line1',
          tool: 'trend-line',
          paneIndex: 0,
          zIndex: 0,
          style: {},
          points: [
            { time: 100, price: 10 },
            { time: 200, price: 12 },
          ],
        },
      ],
    }
    const { terminal } = create(input)
    const attach = vi.fn(async () => {
      Object.assign(terminal, { draw: { toJSON: () => input.chart.drawings } })
    })
    Object.assign(terminal, { attachDrawing: attach })
    try {
      await terminal.init()
      expect(attach).toHaveBeenCalledTimes(1)
    } finally {
      Object.assign(terminal, { draw: null })
    }
  })

  it('uses a detached initial pane and keeps writes out of browser preferences', async () => {
    const input = saved()
    const { terminal, chart } = create(input)
    input.interval = '5m'
    input.chart.viewport!.from = 100
    await terminal.init()
    expect(chart.restoreState).toHaveBeenCalledWith(
      expect.objectContaining({ viewport: { from: 10, to: 40 } })
    )
    expect(terminal.volumeVisible()).toBe(false)
    expect(terminal.drawStats()).toMatchObject({ magnet: true, stay: true })
    terminal.setDrawStay(false)
    expect(localStorage.getItem('staged-p0-stay')).toBeNull()
  })

  it('rejects malformed state and unavailable chart types before registering DOM listeners', () => {
    const listen = vi.spyOn(HTMLElement.prototype, 'addEventListener')
    expect(() => create({ ...saved(), chart: { version: 99 } })).toThrow()
    expect(() => create({ ...saved(), chartType: 'missing' })).toThrow(/chart type/i)
    expect(listen).not.toHaveBeenCalled()
  })

  it('refuses unavailable intervals without substituting a default', async () => {
    const { terminal, load, callbacks } = create({ ...saved(), interval: '3m' })
    await expect(terminal.init()).rejects.toThrow(/interval/i)
    expect(load).not.toHaveBeenCalled()
    expect(callbacks.onReady).not.toHaveBeenCalled()
  })

  it('does not invent supported intervals when broker discovery fails', async () => {
    const { terminal, api, load } = create()
    api.mockRejectedValue(new Error('Discovery unavailable'))
    await expect(terminal.init()).rejects.toThrow(/Discovery unavailable/)
    expect(load).not.toHaveBeenCalled()
  })

  it('refuses an unavailable study before loading a replacement instrument', async () => {
    const input = saved()
    input.chart.indicators = [
      { indicatorId: 'unavailable-custom-study', settings: {}, paneIndex: 1 },
    ]
    const { terminal, load } = create(input)
    await expect(terminal.init()).rejects.toThrow(/unavailable-custom-study/)
    expect(load).not.toHaveBeenCalled()
  })

  it('rejects a missing symbol without falling back to another instrument', async () => {
    const { terminal, search, load } = create({ ...saved(), symbol: 'MISSING' })
    search.mockResolvedValue([])
    await expect(terminal.init()).rejects.toThrow(/symbol/i)
    expect(search).toHaveBeenCalledTimes(1)
    expect(search).toHaveBeenCalledWith('MISSING', 'NSE')
    expect(load).not.toHaveBeenCalled()
  })

  it('rejects empty or failed history instead of trying a default instrument', async () => {
    const { terminal, load, search } = create()
    load.mockResolvedValue(false)
    await expect(terminal.init()).rejects.toThrow(/history/i)
    expect(search).toHaveBeenCalledTimes(1)
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('reports cancellation after interval discovery and does not recreate resources', async () => {
    const { terminal, api, load } = create()
    let finish!: (value: { data: { minutes: string[] } }) => void
    api.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve
        })
    )
    const init = terminal.init()
    terminal.destroy()
    finish({ data: { minutes: ['15m'] } })
    await expect(init).rejects.toThrow(/cancel/i)
    expect(load).not.toHaveBeenCalled()
    expect(OpenAlgoWsFeed.prototype.connect).not.toHaveBeenCalled()
  })

  it('rejects an incomplete engine restore and releases the prepared chart', async () => {
    const { terminal, chart } = create()
    chart.restoreState.mockReturnValue({ applied: false, indicators: 0, series: [] })
    await expect(terminal.init()).rejects.toThrow(/restore/i)
    expect(chart.destroy).toHaveBeenCalledTimes(1)
  })

  it('waits for settings restoration and rejects a superseded chart', async () => {
    const { terminal, chart } = create()
    let resume!: () => void
    const restore = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resume = resolve
        })
    )
    Object.assign(terminal, { restoreChartSettings: restore })
    const init = terminal.init()
    await vi.waitFor(() => expect(restore).toHaveBeenCalled())
    expect(chart.restoreState).not.toHaveBeenCalled()
    terminal.destroy()
    resume()
    await expect(init).rejects.toThrow(/cancel|changed/i)
    expect(chart.restoreState).not.toHaveBeenCalled()
  })
})
