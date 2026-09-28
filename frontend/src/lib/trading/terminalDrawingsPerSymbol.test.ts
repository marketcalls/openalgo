/**
 * Drawings belong to the instrument, not to the pane showing it.
 *
 * They were saved under the pane's own `draw` key, which outlives the symbol
 * in it. Trend lines drawn on one instrument came back on every instrument
 * loaded into that pane afterwards, anchored at the same times and prices, and
 * deleting them anywhere deleted them everywhere (issue #2131).
 *
 * The swap happens in `buildChart`, between the snapshot that ends the old
 * chart and the restore that fills the new one, so these drive that seam
 * rather than the drawing tier itself: what is asserted is which symbol each
 * document is filed under.
 */

import type { createChart } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { type SymbolView, TradingTerminal } from './terminal'

type Doc = { version: number; drawings: { id: string; tool: string }[] }

type TerminalState = {
  sym: SymbolView
  chart: ReturnType<typeof createChart>
  drawJson: Doc
  drawOwner: string | null
  drawEnabled: boolean
  syncDrawingsToSymbol(): void
  buildChart(): void
}

const ENGINERSIN: SymbolView = {
  symbol: 'ENGINERSIN',
  exchange: 'NSE',
  name: 'Engineers India',
  lotsize: 1,
  lots: false,
  tick: 0.05,
  freezeQty: 1,
  quoteOnly: false,
  productOptions: ['MIS', 'CNC'],
  product: 'MIS',
}
const ACMESOLAR: SymbolView = { ...ENGINERSIN, symbol: 'ACMESOLAR', name: 'Acme Solar' }

const triangle = (): Doc => ({
  version: 2,
  drawings: [
    { id: 'a', tool: 'trendline' },
    { id: 'b', tool: 'trendline' },
  ],
})
const single = (id: string): Doc => ({ version: 2, drawings: [{ id, tool: 'trendline' }] })

const KEY = 'oa-trading'
const drawKey = (sym: SymbolView) => `${KEY}-draw-${sym.exchange}:${sym.symbol}`
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
  return { terminal, state: terminal as unknown as TerminalState, container }
}

/** Seed the pane as if it had been left showing `sym`. */
function seedPane(sym: SymbolView, doc?: Doc, legacy?: Doc) {
  localStorage.setItem(
    `${KEY}-symbol`,
    JSON.stringify({ symbol: sym.symbol, exchange: sym.exchange })
  )
  if (doc) localStorage.setItem(drawKey(sym), JSON.stringify(doc))
  if (legacy) localStorage.setItem(`${KEY}-draw`, JSON.stringify(legacy))
}

describe('drawings follow the symbol', () => {
  it('restores the saved symbol’s own drawings on startup', () => {
    seedPane(ENGINERSIN, triangle())

    const { state } = mount()

    expect(state.drawJson.drawings).toHaveLength(2)
    expect(state.drawOwner).toBe(`draw-${ENGINERSIN.exchange}:${ENGINERSIN.symbol}`)
  })

  it('leaves one symbol’s drawings behind when another is loaded', () => {
    seedPane(ENGINERSIN, triangle())
    const { state } = mount()
    state.sym = ACMESOLAR

    state.syncDrawingsToSymbol()

    // The new symbol starts clean...
    expect(state.drawJson.drawings).toEqual([])
    // ...and the old symbol keeps its own.
    expect(JSON.parse(localStorage.getItem(drawKey(ENGINERSIN)) as string).drawings).toHaveLength(2)
  })

  it('brings them back when the first symbol is loaded again', () => {
    seedPane(ENGINERSIN, triangle())
    const { state } = mount()

    state.sym = ACMESOLAR
    state.syncDrawingsToSymbol()
    state.sym = ENGINERSIN
    state.syncDrawingsToSymbol()

    expect(state.drawJson.drawings).toHaveLength(2)
  })

  it('keeps two symbols’ drawings apart', () => {
    seedPane(ENGINERSIN, single('engineers'))
    const { state } = mount()

    state.sym = ACMESOLAR
    state.syncDrawingsToSymbol()
    state.drawJson = single('acme')
    state.sym = ENGINERSIN
    state.syncDrawingsToSymbol()

    expect(state.drawJson.drawings[0].id).toBe('engineers')
    expect(JSON.parse(localStorage.getItem(drawKey(ACMESOLAR)) as string).drawings[0].id).toBe(
      'acme'
    )
  })

  it('does nothing when the rebuild is not a symbol change', () => {
    seedPane(ENGINERSIN, triangle())
    const { state } = mount()
    state.sym = ENGINERSIN

    // An interval or chart-type switch rebuilds the chart on the same symbol.
    state.syncDrawingsToSymbol()

    expect(state.drawJson.drawings).toHaveLength(2)
  })

  it('holds them until the first symbol lands', () => {
    // A rebuild can precede the first load, and the restored document belongs
    // to the symbol about to arrive - not to a pane with no symbol at all.
    seedPane(ENGINERSIN, triangle())
    const { state } = mount()

    state.syncDrawingsToSymbol()

    expect(state.drawJson.drawings).toHaveLength(2)
    expect(state.drawOwner).toBe(`draw-${ENGINERSIN.exchange}:${ENGINERSIN.symbol}`)
  })

  it('is wired into the chart rebuild, not only callable on its own', () => {
    seedPane(ENGINERSIN, triangle())
    const { state } = mount()
    state.sym = ACMESOLAR

    state.buildChart()

    expect(state.drawJson.drawings).toEqual([])
    expect(state.drawOwner).toBe(`draw-${ACMESOLAR.exchange}:${ACMESOLAR.symbol}`)
  })
})

describe('upgrading from pane-level drawings', () => {
  it('adopts an existing pane entry for the symbol it was drawn on', () => {
    seedPane(ENGINERSIN, undefined, triangle())

    const { state } = mount()

    expect(state.drawJson.drawings).toHaveLength(2)
    expect(state.drawOwner).toBe(`draw-${ENGINERSIN.exchange}:${ENGINERSIN.symbol}`)
  })

  it('files them under the symbol once it moves off it', () => {
    seedPane(ENGINERSIN, undefined, triangle())
    const { state } = mount()
    state.sym = ACMESOLAR

    state.syncDrawingsToSymbol()

    expect(JSON.parse(localStorage.getItem(drawKey(ENGINERSIN)) as string).drawings).toHaveLength(2)
    expect(state.drawJson.drawings).toEqual([])
  })

  it('does not hand the pane entry to a second symbol', () => {
    seedPane(ENGINERSIN, undefined, triangle())
    const { state } = mount()

    state.sym = ACMESOLAR
    state.syncDrawingsToSymbol()

    // The legacy key is only ever read for the symbol the pane was left on.
    expect(state.drawJson.drawings).toEqual([])
  })

  it('starts empty when the pane has no saved symbol at all', () => {
    const { state } = mount()

    expect(state.drawJson.drawings).toEqual([])
    expect(state.drawOwner).toBe('draw')
  })
})
