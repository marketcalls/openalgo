/**
 * A finished alert keeps its record and loses its line.
 *
 * **The record is the part that must survive, and it is the reason this is an
 * engine option rather than a deletion.** This terminal restores an alert's
 * definition and its runtime state from two different places, so an alert
 * removed to be rid of its line comes back from its definition as armed and
 * fires again on the next reload, on a price it already reported.
 * `terminalAlerts.test.ts` holds that rule; this file holds the other half,
 * that the host asks the engine to stop drawing the line instead.
 *
 * Asserted at the point the controller is made, because that is the whole of
 * what this terminal does: `spentLines` is opt-in per controller, it is not
 * written into an alert document, and the default is to keep drawing. A host
 * that stops passing it has silently gone back to a chart that accumulates a
 * week of lines nothing is watching, and nothing else in the suite would say so.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Every option object the terminal handed to an AlertController this test. */
const passed: Record<string, unknown>[] = []

vi.mock('openalgo-charts', async (importOriginal) => {
  const real = await importOriginal<typeof import('openalgo-charts')>()
  class Recording extends real.AlertController {
    constructor(chart: ConstructorParameters<typeof real.AlertController>[0], options?: object) {
      // Recorded and then delegated, so the real controller is what the
      // terminal drives: a test double here would prove the terminal calls
      // something, not that it calls the engine.
      passed.push({ ...(options ?? {}) })
      super(chart, options as ConstructorParameters<typeof real.AlertController>[1])
    }
  }
  return { ...real, AlertController: Recording }
})

const { TradingTerminal } = await import('./terminal')

import type { Bar, SeriesApi } from 'openalgo-charts'
import type { SymbolView } from './terminal'

type State = {
  chartToolsReady: Promise<void>
  price: SeriesApi
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  buildChart(): void
  loadIndicators(): Promise<void>
}

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
})

const terminals: InstanceType<typeof TradingTerminal>[] = []

beforeEach(() => {
  passed.length = 0
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

async function mount() {
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast() {},
      onContextMenu() {},
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
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
  return { terminal, state }
}

describe('what the terminal asks of the alert engine', () => {
  it('asks it not to draw the line of an alert that has fired or expired', async () => {
    await mount()

    expect(passed.length).toBeGreaterThan(0)
    for (const options of passed) expect(options.spentLines).toBe('hide')
  })

  it('still hands the engine its drawings, so a drawing alert keeps working', async () => {
    // The option is added beside what was already passed, not instead of it: an
    // alert anchored to a drawing level needs the drawing tier to resolve it.
    await mount()

    expect(passed[0]).toHaveProperty('drawings')
  })

  it('asks again on every chart it builds', async () => {
    // A rebuild makes a new controller, and a symbol or interval change is a
    // rebuild. An option passed only on the first one would leave every chart
    // after the first drawing its finished lines again.
    const { state } = await mount()
    const first = passed.length

    state.buildChart()
    await state.chartToolsReady

    expect(passed.length).toBeGreaterThan(first)
    for (const options of passed) expect(options.spentLines).toBe('hide')
  })
})
