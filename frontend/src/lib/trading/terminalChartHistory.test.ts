/**
 * The chart-wide undo timeline and the study pane rows, against the real
 * chart, drawing tier and history: one Ctrl+Z takes back the latest change
 * of any kind, the chart type and interval switches are steps, and a pane's
 * order and fold come back with the saved studies while an old save opens
 * exactly as it did.
 */
import type { Bar, Chart } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { historyChord } from './chartHistory'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart | null
  draw: DrawingController | null
  sym: SymbolView | null
  interval: string
  ctype: string
  rawBars: Bar[]
  chartToolsReady: Promise<void>
  buildChart(): void
  loadIndicators(): Promise<void>
  loadIndicatorsFor(ids: readonly string[]): Promise<void>
  reloadCurrent(): void
  undoHistory: { following(chart: Chart | null): boolean }
}

const SK = 'oa-trading-h0'
const INFY: SymbolView = {
  symbol: 'INFY',
  exchange: 'NSE',
  name: 'INFY',
  lotsize: 1,
  lots: false,
  tick: 0.05,
  freezeQty: 1,
  quoteOnly: false,
  productOptions: ['MIS', 'CNC'],
  product: 'MIS',
}
const terminals: TradingTerminal[] = []

beforeEach(() => {
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
  vi.restoreAllMocks()
})

function mount() {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container,
    legendEl: document.createElement('div'),
    storageKey: SK,
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
  const state = terminal as unknown as State
  state.loadIndicators = async () => {}
  state.loadIndicatorsFor = async () => {}
  // The interval switch reloads from the broker; the bars here are fixed.
  state.reloadCurrent = () => {}
  state.interval = '5m'
  state.sym = INFY
  state.rawBars = Array.from({ length: 60 }, (_, i) => ({
    time: 60 * (i + 1),
    open: 1500 + i,
    high: 1510 + i,
    low: 1490 + i,
    close: 1502 + i,
    volume: 100,
  }))
  return { terminal, state }
}

/** Build the chart and wait until the timeline follows it. */
async function build(state: State) {
  state.buildChart()
  await settle(state)
}
async function settle(state: State) {
  await state.chartToolsReady
  await vi.waitFor(() => expect(state.undoHistory.following(state.chart)).toBe(true))
}
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))
const studies = (state: State) =>
  (state.chart?.indicators() ?? []).map((s) => [s.indicatorId, s.paneIndex])

describe('the undo chord', () => {
  it('reads Ctrl+Z as undo and Ctrl+Y or Ctrl+Shift+Z as redo, nothing else', () => {
    expect(historyChord({ key: 'z', ctrlKey: true })).toBe('undo')
    expect(historyChord({ key: 'Z', ctrlKey: true, shiftKey: true })).toBe('redo')
    expect(historyChord({ key: 'y', ctrlKey: true })).toBe('redo')
    expect(historyChord({ key: 'z', metaKey: true })).toBe('undo')
    expect(historyChord({ key: 'z' })).toBeNull()
    expect(historyChord({ key: 'z', ctrlKey: true, altKey: true })).toBeNull()
    expect(historyChord({ key: 'c', ctrlKey: true })).toBeNull()
  })
})

describe('chart-wide undo', () => {
  it('takes back a study added and puts it back, and the save follows', async () => {
    const { terminal, state } = mount()
    await build(state)
    state.chart?.addIndicator('rsi', {})
    await flush()
    expect(terminal.historyReady('undo')).toBe(true)

    expect(terminal.historyPress('undo')).toBe(true)
    expect(studies(state)).toEqual([])
    expect(localStorage.getItem(`${SK}-indicators`)).not.toContain('"rsi"')

    expect(terminal.historyPress('redo')).toBe(true)
    expect(studies(state)).toEqual([['rsi', 1]])
    expect(localStorage.getItem(`${SK}-indicators`)).toContain('"rsi"')
  })

  it('walks drawings and studies as one timeline, latest first', async () => {
    const { terminal, state } = mount()
    await build(state)
    await terminal.setDrawTool(null)
    await vi.waitFor(() => expect(state.undoHistory.following(state.chart)).toBe(true))
    state.chart?.addIndicator('rsi', {})
    await flush()
    state.draw?.add({
      tool: 'trend-line',
      paneIndex: 0,
      points: [
        { time: 120, price: 1500 },
        { time: 600, price: 1530 },
      ],
    } as never)
    await flush()
    expect(state.draw?.drawings()).toHaveLength(1)

    terminal.historyPress('undo')
    expect(state.draw?.drawings()).toHaveLength(0)
    expect(studies(state)).toEqual([['rsi', 1]])
    terminal.historyPress('undo')
    expect(studies(state)).toEqual([])
    terminal.historyPress('redo')
    terminal.historyPress('redo')
    expect(studies(state)).toEqual([['rsi', 1]])
    expect(state.draw?.drawings()).toHaveLength(1)
  })

  it('records the interval and the chart type the toolbar switched', async () => {
    const { terminal, state } = mount()
    await build(state)

    expect(terminal.chooseInterval('15m')).toBe('15m')
    expect(terminal.historyPress('undo')).toBe(true)
    expect(state.interval).toBe('5m')
    expect(terminal.historyPress('redo')).toBe(true)
    expect(state.interval).toBe('15m')

    expect(terminal.chooseChartType('line')).toBe('line')
    await settle(state)
    expect(terminal.historyPress('undo')).toBe(true)
    expect(state.ctype).toBe('candlestick')
    await settle(state)
    expect(terminal.historyPress('undo')).toBe(true)
    expect(state.interval).toBe('5m')
  })
})

describe('study panes', () => {
  it('moves and folds a pane, keeps both with the save, and undoes each', async () => {
    const first = mount()
    await build(first.state)
    first.state.chart?.addIndicator('rsi', {})
    first.state.chart?.addIndicator('macd', {})
    await flush()
    expect(studies(first.state)).toEqual([
      ['rsi', 1],
      ['macd', 2],
    ])

    expect(first.terminal.moveStudyPane(2, -1)).toBe(true)
    await flush()
    expect(studies(first.state)).toEqual([
      ['rsi', 2],
      ['macd', 1],
    ])
    expect(first.terminal.setStudyPaneCollapsed(2, true)).toBe(true)
    await flush()
    expect(first.state.chart?.paneCollapsed(2)).toBe(true)

    // Reopened from the save: the order and the fold come back.
    first.terminal.destroy()
    const second = mount()
    await build(second.state)
    expect(studies(second.state).sort()).toEqual([
      ['macd', 1],
      ['rsi', 2],
    ])
    expect(second.state.chart?.paneCollapsed(2)).toBe(true)
    expect(second.state.chart?.paneCollapsed(1)).toBe(false)
    // Restoring is not a step of its own.
    expect(second.terminal.historyReady('undo')).toBe(false)

    second.terminal.setStudyPaneCollapsed(2, false)
    await flush()
    expect(second.terminal.historyPress('undo')).toBe(true)
    expect(second.state.chart?.paneCollapsed(2)).toBe(true)
  })

  it('opens a save from before panes could fold exactly as it was', async () => {
    localStorage.setItem(
      `${SK}-indicators`,
      JSON.stringify({
        version: 2,
        indicators: [
          { instanceId: 'a', indicatorId: 'rsi', settings: {}, visible: true, paneIndex: 1 },
          { instanceId: 'b', indicatorId: 'macd', settings: {}, visible: true, paneIndex: 2 },
        ],
      })
    )
    const { state } = mount()
    await build(state)
    expect(studies(state)).toEqual([
      ['rsi', 1],
      ['macd', 2],
    ])
    expect(state.chart?.paneCollapsed(1)).toBe(false)
    expect(state.chart?.paneCollapsed(2)).toBe(false)
    expect(localStorage.getItem(`${SK}-panes-folded`)).toBeNull()
  })
})
