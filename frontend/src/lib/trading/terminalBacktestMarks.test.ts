import type { AlertController, Bar, Chart, SeriesApi } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart
  price: SeriesApi
  draw: DrawingController
  alerts: AlertController
  chartToolsReady: Promise<void>
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  btMarkers: { setMarkers(markers: unknown[]): void } | null
  ctype: string
  volume: SeriesApi
  buildChart(): void
  loadIndicators(): Promise<void>
  syncIndicators(): void
  beginReplayAt(index: number): Promise<void>
  loadReplaySubBars(): Promise<Bar[] | null>
}

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
})
const terminals: TradingTerminal[] = []
beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
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
})

async function mount(preferences?: null) {
  const onToast = vi.fn()
  const onContextMenu = vi.fn()
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    preferences,
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast,
      onContextMenu,
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
  // Replace the custom-module network lookup, keeping built-in calculations real.
  state.loadIndicators = async () => {}
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
  state.interval = '1m'
  state.rawBars = [bar(60, 100), bar(120, 100), bar(180, 100), bar(240, 100)]
  state.buildChart()
  await state.chartToolsReady
  return { terminal, state, onToast, onContextMenu }
}

describe('backtest marks follow their strategy', () => {
  const MARK = [{ time: 120, position: 'belowBar', shape: 'arrowUp', color: '#0a0', text: 'Long' }]

  it('stay while the strategy is still registering, and go when it is removed', async () => {
    const { state, terminal } = await mount()
    const onCleared = vi.fn()
    // The Backtest action marks the chart before the study has registered.
    expect(terminal.setBacktestMarkers(MARK as never, { indicatorId: 'ema', onCleared })).toBe(true)
    const layer = state.btMarkers
    if (!layer) throw new Error('no marker layer')
    const setMarkers = vi.spyOn(layer, 'setMarkers')
    // Another study changing first must not take them down.
    const other = state.chart.addIndicator('rsi')
    state.syncIndicators()
    expect(setMarkers).not.toHaveBeenCalled()
    // The strategy arrives, and is later removed.
    const strategy = state.chart.addIndicator('ema', { length: 3 })
    state.syncIndicators()
    expect(setMarkers).not.toHaveBeenCalled()
    state.chart.removeIndicator(strategy.id)
    state.syncIndicators()
    expect(setMarkers).toHaveBeenLastCalledWith([])
    expect(onCleared).toHaveBeenCalledOnce()
    // Removing an unrelated study afterwards does nothing more.
    state.chart.removeIndicator(other.id)
    state.syncIndicators()
    expect(onCleared).toHaveBeenCalledOnce()
  })

  it('leave marks with no strategy behind them alone', async () => {
    const { state, terminal } = await mount()
    terminal.setBacktestMarkers(MARK as never)
    const layer = state.btMarkers
    if (!layer) throw new Error('no marker layer')
    const setMarkers = vi.spyOn(layer, 'setMarkers')
    const study = state.chart.addIndicator('ema')
    state.syncIndicators()
    state.chart.removeIndicator(study.id)
    state.syncIndicators()
    expect(setMarkers).not.toHaveBeenCalled()
  })
})
