/**
 * Drawings belong to the instrument, not to the pane showing it.
 *
 * They were saved under the pane's own `draw` key, which outlives the symbol
 * in it: trend lines drawn on one instrument came back on every instrument
 * loaded into that pane afterwards, at the same prices, and deleting them
 * anywhere deleted them everywhere (issue #2131).
 *
 * The swap happens in `buildChart`, between the snapshot that ends the old
 * chart and the restore that fills the new one, so these drive that seam with
 * the real draw tier attached and assert what the controller ends up holding.
 *
 * The upgrade is pinned against `PREVIOUS_SAVE`: the exact text the previous
 * build wrote to `localStorage` for three drawings on INFY, captured from it.
 */
import type { Bar } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import 'openalgo-charts/indicators'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  draw: DrawingController | null
  drawOwner: string | null
  sym: SymbolView | null
  interval: string
  rawBars: Bar[]
  chartToolsReady: Promise<void>
  buildChart(): void
  loadIndicators(): Promise<void>
}

const PREVIOUS_SAVE =
  '{"version":2,"drawings":[{"tool":"trend-line","paneIndex":0,"points":[{"time":60,"price":1490},{"time":240,"price":1510}],"style":{"extendLeft":false,"extendRight":false,"color":"#2962ff","lineWidth":2},"id":"d1","zIndex":0,"createdAt":1790854571340},{"tool":"rectangle","paneIndex":0,"points":[{"time":120,"price":1495},{"time":180,"price":1505}],"style":{"fill":true},"text":{"value":"Demand zone"},"id":"d2","zIndex":0,"createdAt":1790854571341},{"tool":"fib-retracement","paneIndex":0,"points":[{"time":60,"price":1490},{"time":240,"price":1510}],"style":{"showLabels":true,"levels":[{"ratio":0,"color":"#787b86"},{"ratio":0.236,"color":"#f23645"},{"ratio":0.382,"color":"#ff9800"},{"ratio":0.5,"color":"#4caf50"},{"ratio":0.618,"color":"#089981"},{"ratio":0.786,"color":"#00bcd4"},{"ratio":1,"color":"#787b86"}],"fill":true,"fillOpacity":0.06},"locked":true,"id":"d3","zIndex":0,"createdAt":1790854571341}]}'

/** A 1.9.x save: a bare array, the label's text still on the style bag. */
const LEGACY_SAVE = JSON.stringify([
  {
    id: 'old1',
    tool: 'text',
    paneIndex: 0,
    points: [{ time: 120, price: 1500 }],
    style: { color: '#e4e8f4', text: 'Supply zone', fontSize: 14 },
  },
])

const SK = 'oa-trading-p0'
const sym = (symbol: string): SymbolView => ({
  symbol,
  exchange: 'NSE',
  name: symbol,
  lotsize: 1,
  lots: false,
  tick: 0.05,
  freezeQty: 1,
  quoteOnly: false,
  productOptions: ['MIS', 'CNC'],
  product: 'MIS',
})
const INFY = sym('INFY')
const TCS = sym('TCS')
const keyOf = (s: SymbolView) => `${SK}-draw:NSE:${s.symbol}`
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
  state.interval = '5m'
  state.rawBars = [60, 120, 180, 240].map((time) => ({
    time,
    open: 1500,
    high: 1510,
    low: 1490,
    close: 1500,
    volume: 100,
  }))
  return { terminal, state }
}

/** Show `s` in the pane, as a symbol load does, and wait for its drawings. */
async function show(terminal: TradingTerminal, state: State, s: SymbolView) {
  state.sym = s
  state.buildChart()
  await state.chartToolsReady
  await terminal.setDrawTool(null)
}

/** The pane left showing `s` by an earlier visit. */
function leftOn(s: SymbolView) {
  localStorage.setItem(`${SK}-symbol`, JSON.stringify({ symbol: s.symbol, exchange: s.exchange }))
}

const ids = (state: State) => state.draw?.drawings().map((d) => d.id) ?? []

describe('upgrading a pane saved by the previous build', () => {
  it('files the save under the symbol it was drawn on, exactly as written', () => {
    leftOn(INFY)
    localStorage.setItem(`${SK}-draw`, PREVIOUS_SAVE)

    mount()

    expect(localStorage.getItem(keyOf(INFY))).toBe(PREVIOUS_SAVE)
    // Untouched, so an older build opened on this browser still has it.
    expect(localStorage.getItem(`${SK}-draw`)).toBe(PREVIOUS_SAVE)
  })

  it('opens with every drawing as it was: anchors, text, levels and lock', async () => {
    leftOn(INFY)
    localStorage.setItem(`${SK}-draw`, PREVIOUS_SAVE)
    const { terminal, state } = mount()

    await show(terminal, state, INFY)

    expect(ids(state)).toEqual(['d1', 'd2', 'd3'])
    const saved = JSON.parse(PREVIOUS_SAVE).drawings
    for (const d of saved) {
      const live = state.draw?.get(d.id)
      expect(live?.points).toEqual(d.points)
      expect(live?.style).toMatchObject(d.style)
    }
    expect(state.draw?.get('d2')?.text?.value).toBe('Demand zone')
    expect(state.draw?.get('d3')?.locked).toBe(true)
  })

  it('never hands the old save to another symbol, even after a reload', async () => {
    leftOn(INFY)
    localStorage.setItem(`${SK}-draw`, PREVIOUS_SAVE)
    const first = mount()
    await show(first.terminal, first.state, INFY)
    await show(first.terminal, first.state, TCS)
    leftOn(TCS)
    first.terminal.destroy()

    // Reopened on TCS: the pane-level save is still in storage, and must not
    // be adopted a second time for whatever symbol the pane now shows.
    const second = mount()
    await show(second.terminal, second.state, TCS)
    expect(ids(second.state)).toEqual([])
    await show(second.terminal, second.state, INFY)
    expect(ids(second.state)).toEqual(['d1', 'd2', 'd3'])
  })

  it('does not bring back drawings the trader deleted after the upgrade', async () => {
    leftOn(INFY)
    localStorage.setItem(`${SK}-draw`, PREVIOUS_SAVE)
    const first = mount()
    await show(first.terminal, first.state, INFY)
    first.terminal.removeDrawings(true)
    first.terminal.destroy()

    const second = mount()
    await show(second.terminal, second.state, INFY)
    expect(ids(second.state)).toEqual([])
  })

  it('adopts a save for the first symbol when the pane had none recorded', async () => {
    localStorage.setItem(`${SK}-draw`, PREVIOUS_SAVE)
    const { terminal, state } = mount()

    await show(terminal, state, INFY)

    expect(ids(state)).toEqual(['d1', 'd2', 'd3'])
    expect(JSON.parse(localStorage.getItem(keyOf(INFY)) ?? 'null').drawings).toHaveLength(3)
  })

  it('carries a 1.9.x array through the tier migration on its symbol', async () => {
    leftOn(INFY)
    localStorage.setItem(`${SK}-draw`, LEGACY_SAVE)
    const { terminal, state } = mount()
    expect(localStorage.getItem(keyOf(INFY))).toBe(LEGACY_SAVE)

    await show(terminal, state, INFY)

    expect(ids(state)).toEqual(['old1'])
    expect(state.draw?.get('old1')?.text?.value).toBe('Supply zone')
  })
})

describe('drawings follow the symbol', () => {
  it('leaves one symbol’s drawings behind and brings them back', async () => {
    leftOn(INFY)
    localStorage.setItem(keyOf(INFY), PREVIOUS_SAVE)
    const { terminal, state } = mount()
    await show(terminal, state, INFY)

    await show(terminal, state, TCS)
    expect(ids(state)).toEqual([])
    state.draw?.add({
      tool: 'horizontal-line',
      paneIndex: 0,
      points: [{ time: 120, price: 1500 }],
      style: {},
    })
    await show(terminal, state, INFY)

    expect(ids(state)).toEqual(['d1', 'd2', 'd3'])
    expect(JSON.parse(localStorage.getItem(keyOf(TCS)) ?? 'null').drawings).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem(keyOf(INFY)) ?? 'null').drawings).toHaveLength(3)
  })

  it('keeps them through a rebuild on the same symbol', async () => {
    leftOn(INFY)
    localStorage.setItem(keyOf(INFY), PREVIOUS_SAVE)
    const { terminal, state } = mount()
    await show(terminal, state, INFY)

    state.interval = '15m'
    await show(terminal, state, INFY)

    expect(ids(state)).toEqual(['d1', 'd2', 'd3'])
    expect(state.drawOwner).toBe('draw:NSE:INFY')
  })

  it('leaves no entry behind for a symbol that was only looked at', async () => {
    leftOn(INFY)
    const { terminal, state } = mount()
    await show(terminal, state, INFY)
    await show(terminal, state, TCS)
    await show(terminal, state, INFY)

    expect(localStorage.getItem(keyOf(TCS))).toBeNull()
    expect(localStorage.getItem(keyOf(INFY))).toBeNull()
  })
})
