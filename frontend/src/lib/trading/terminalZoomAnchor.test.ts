/**
 * The wheel zooms about the latest bar.
 *
 * The engine's default holds the bar under the pointer still. With the pointer
 * in the middle of the chart, or over the empty space past the last bar, a zoom
 * out pushed the bars away from the right edge and the gap beside the latest
 * bar kept widening. The terminal asks for the right-edge anchor, so the latest
 * bar stays put while history compresses beside it; Ctrl or Cmd with the wheel
 * still zooms about the pointer, which the engine handles.
 *
 * Asserted at the point the chart is made, because the option is all this
 * terminal does about it, and a chart built without it looks fine until
 * someone zooms out.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** Every option object the terminal handed to createChart in this test. */
const passed: Record<string, unknown>[] = []

vi.mock('openalgo-charts', async (importOriginal) => {
  const real = await importOriginal<typeof import('openalgo-charts')>()
  return {
    ...real,
    // Recorded and then delegated, so the terminal still drives a real chart.
    createChart: (container: HTMLElement, options?: object) => {
      passed.push({ ...(options ?? {}) })
      return real.createChart(container, options as Parameters<typeof real.createChart>[1])
    },
  }
})

const { TradingTerminal } = await import('./terminal')

import type { Bar } from 'openalgo-charts'
import type { SymbolView } from './terminal'

type State = {
  chartToolsReady: Promise<void>
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

describe('how the terminal asks the chart to zoom', () => {
  it('anchors a wheel zoom on the latest bar', async () => {
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
      symbol: 'TCS',
      exchange: 'NSE',
      name: 'Tata Consultancy Services',
      lotsize: 1,
      lots: false,
      tick: 0.05,
      freezeQty: 100000,
      quoteOnly: false,
      productOptions: ['MIS', 'CNC'],
      product: 'CNC',
    }
    state.interval = '1m'
    state.rawBars = [bar(60, 100), bar(120, 100), bar(180, 100), bar(240, 100)]
    state.buildChart()
    await state.chartToolsReady

    expect(passed.length).toBeGreaterThan(0)
    for (const options of passed) expect(options.zoomAnchor).toBe('right')
  })
})
