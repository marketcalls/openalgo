/**
 * The trader's scripts on the terminal: applying one, its alerts, and the note
 * about a study with nothing to plot.
 *
 * The terminal, the chart, the compiler and the language's chart adapter are
 * all real. Only the server is replaced, by a `fetch` serving the script list,
 * each script's source and the instrument facts, so what a test changes between
 * two applies is the file on the "server", exactly as an edit in the panel is.
 */

import {
  type Bar,
  type Chart,
  type IndicatorDescriptor,
  registerIndicator,
  type SeriesApi,
} from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearInstrumentFacts } from './instrumentFacts'
import { forgetOpenScriptStudies } from './openscriptStudies'
import { type SymbolView, TradingTerminal } from './terminal'

type State = {
  chart: Chart
  price: SeriesApi
  chartToolsReady: Promise<void>
  sym: SymbolView
  interval: string
  rawBars: Bar[]
  buildChart(): void
}

/** 09:13 IST on Monday 21 September 2026. */
const T0 = Date.UTC(2026, 8, 21, 3, 43) / 1000

const bar = (time: number, close: number): Bar => ({
  time,
  open: close,
  high: close,
  low: close,
  close,
  volume: 100,
})

/** What the "server" holds: each script's source and modification time. */
let scripts: Record<string, { source: string; mtime: number }> = {}
/** The facts answer, held back until a test lets it through. */
let factsGate: Promise<void> = Promise.resolve()

/** The parts of a response the code under test reads. */
interface Served {
  ok: boolean
  json?: () => Promise<unknown>
  text?: () => Promise<string>
}

function factsReply(lotSize: number) {
  return {
    status: 'success',
    contractFound: true,
    instrument: {
      exchange: 'NFO',
      timezone: 'Asia/Kolkata',
      tickSize: 0.05,
      lotSize,
      instrumentType: 'future',
      hasVolume: true,
      hasOpenInterest: true,
      session: { start: '09:15', end: '15:30', days: [1, 2, 3, 4, 5] },
    },
    today: { date: '2026-09-21', open: true, isSpecial: false },
  }
}

const terminals: TradingTerminal[] = []

beforeEach(() => {
  vi.useFakeTimers()
  // Inside the newest bar of every test, so it is still forming.
  vi.setSystemTime((T0 + 3 * 60 + 10) * 1000)
  localStorage.clear()
  forgetOpenScriptStudies()
  clearInstrumentFacts()
  scripts = {}
  factsGate = Promise.resolve()
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
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string): Promise<Served> => {
      const u = new URL(String(url), 'http://host.invalid')
      if (u.pathname === '/openscript/index.json') {
        return {
          ok: true,
          json: async () =>
            Object.entries(scripts).map(([file, one]) => ({ file, mtime: one.mtime, bytes: 1 })),
        }
      }
      if (u.pathname === '/openscript/instrument') {
        await factsGate
        return { ok: true, json: async () => factsReply(65) }
      }
      if (u.pathname.startsWith('/openscript/')) {
        const file = decodeURIComponent(u.pathname.replace('/openscript/', ''))
        return { ok: true, text: async () => scripts[file]?.source ?? '' }
      }
      // The custom indicator folder, the alert log and anything else: absent.
      return { ok: false, json: async () => ({}), text: async () => '' }
    })
  )
})

afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function mount() {
  const onToast = vi.fn()
  const onIndicatorSettings = vi.fn()
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test.invalid',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks: {
      onReady() {},
      onToast,
      onWsState() {},
      onSymbolLoaded() {},
      onLtp() {},
      onIndicatorSettings,
    },
  })
  terminals.push(terminal)
  const state = terminal as unknown as State
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
  state.rawBars = [0, 1, 2, 3].map((i) => bar(T0 + i * 60, 99))
  state.buildChart()
  await state.chartToolsReady
  return { terminal, state, onToast, onIndicatorSettings }
}

function save(file: string, source: string) {
  const mtime = (scripts[file]?.mtime ?? 0) + 1
  scripts[file] = { source, mtime }
}

const studyOf = (plotted: string) => `version 1

study("Probe", overlay = true)

plot(${plotted}, "Value")
`

describe('applying a script', () => {
  it('applies a script already on the chart again instead of adding a second copy', async () => {
    const { terminal, state } = await mount()
    save('probe.oscript', studyOf('1'))
    await terminal.addIndicatorById('openscript:probe')
    const first = state.chart.indicators()
    expect(first).toHaveLength(1)
    const id = first[0].id

    await terminal.addIndicatorById('openscript:probe')
    expect(state.chart.indicators().map((one) => one.id)).toEqual([id])

    // Only a script. A built-in added twice from the picker is two studies on
    // purpose, three moving averages being the ordinary case.
    await terminal.addIndicatorById('ema')
    await terminal.addIndicatorById('ema')
    expect(state.chart.indicators().map((one) => one.indicatorId)).toEqual([
      'openscript:probe',
      'ema',
      'ema',
    ])
  })

  it('draws an applied edit under the same instance, and keeps a copy the edit cannot replace', async () => {
    // A recompute alone would run the program the copy on the chart was built
    // from. The instance id is kept because an alert on one of its plots is
    // bound to it.
    const { terminal, state, onToast } = await mount()
    save('probe.oscript', studyOf('1'))
    await terminal.addIndicatorById('openscript:probe')
    const id = state.chart.indicators()[0].id

    // Compiles, and stops on the first bar: a history index is never negative.
    // Rebuilding the chart's studies with it would stop part way and lose the
    // ones after it, so it is tried first and the working copy stays.
    save('probe.oscript', studyOf('close[close * 0 - 1]'))
    await terminal.addIndicatorById('openscript:probe')
    expect(state.chart.indicators()).toHaveLength(1)
    expect(state.chart.indicators()[0].values().p0).toEqual([1, 1, 1, 1])
    expect(onToast).toHaveBeenCalledWith(expect.stringMatching(/OS4001/), 'err')

    save('probe.oscript', studyOf('2'))
    await terminal.addIndicatorById('openscript:probe')
    const [study] = state.chart.indicators()
    expect(state.chart.indicators()).toHaveLength(1)
    expect(study.id).toBe(id)
    expect(study.values().p0).toEqual([2, 2, 2, 2])
  })
})

describe('the settings form of a script', () => {
  it('carries the group and help text of each input to the dialog', async () => {
    // The dialog draws a group heading and a line of help under the row, and
    // the adapter declares both. The terminal's field shape dropped the help,
    // so the line never appeared in the app.
    const { terminal, state, onIndicatorSettings } = await mount()
    save(
      'bands.oscript',
      `version 1

study("Bands", overlay = true)

mult = input(2.0, "Width", min = 0.5, group = "Bands",
             tooltip = "Standard deviations either side.")

plot(close * mult, "Upper")
`
    )
    await terminal.addIndicatorById('openscript:bands')
    terminal.openIndicatorSettings(state.chart.indicators()[0].id)
    await vi.waitFor(() => expect(onIndicatorSettings).toHaveBeenCalled())

    const [request] = onIndicatorSettings.mock.calls[0]
    expect(request.inputs).toEqual([
      expect.objectContaining({
        label: 'Width',
        group: 'Bands',
        tooltip: 'Standard deviations either side.',
      }),
    ])
  })
})

describe('a script alert on a live chart', () => {
  it('reaches the trader when the bar closes, once', async () => {
    const { terminal, state, onToast } = await mount()
    save(
      'probe.oscript',
      `version 1

study("Probe", overlay = true)

plot(close, "Close")

if close > 100
    alert("Above " + text(close, 2), id = "above")
`
    )
    await terminal.addIndicatorById('openscript:probe')
    onToast.mockClear()
    const last = T0 + 3 * 60

    // A tick lifts the forming bar above 100, and the language waits for the
    // close before it says anything.
    vi.setSystemTime((last + 30) * 1000)
    state.price.update(bar(last, 101))
    state.chart.indicators()
    expect(onToast).not.toHaveBeenCalledWith(expect.stringContaining('Above'), 'ok')

    vi.setSystemTime((last + 61) * 1000)
    state.price.update(bar(last + 60, 99))
    state.chart.indicators()
    expect(onToast).toHaveBeenCalledWith('Above 101.00', 'ok')

    vi.setSystemTime((last + 121) * 1000)
    state.price.update(bar(last + 120, 99))
    state.chart.indicators()
    expect(onToast.mock.calls.filter(([said]) => said === 'Above 101.00')).toHaveLength(1)
  })
})

describe('the note about a study with nothing to plot', () => {
  it('says what is known, and offers more history only as something to try', async () => {
    const { terminal, onToast } = await mount()
    await terminal.addIndicatorById('sma')
    const notes = onToast.mock.calls.filter(([, kind]) => kind === '').map(([said]) => said)
    expect(notes).toHaveLength(1)
    expect(notes[0]).toMatch(/has nothing to plot on the 4 bars loaded/)
    expect(notes[0]).not.toMatch(/needs more history/)
  })

  it('says nothing about a study that plots no line at all', async () => {
    // Its values carry an alert condition, which is not a line. It has no plot
    // to be empty and is short of nothing.
    registerIndicator({
      id: 'probe-alert-only',
      name: 'Alert only',
      placement: 'onchart',
      inputs: [],
      plots: [],
      alerts: [{ id: 'never', title: 'Never', when: () => false }],
      calc: (bars) => ({ condition: bars.map(() => null) }),
    } as IndicatorDescriptor)
    const { terminal, onToast } = await mount()
    await terminal.addIndicatorById('probe-alert-only')
    expect(onToast.mock.calls.filter(([, kind]) => kind === '')).toEqual([])
  })

  it('waits for a script to hear its instrument before describing it', async () => {
    // The lot size arrives after the study is first drawn. Until then it has
    // nothing to plot, and saying so then would be wrong a moment later.
    let open = () => {}
    factsGate = new Promise((resolve) => {
      open = resolve
    })
    const { terminal, state, onToast } = await mount()
    save('lot.oscript', studyOf('chart.lotSize'))

    const adding = terminal.addIndicatorById('openscript:lot')
    await vi.waitFor(() => expect(state.chart.indicators()).toHaveLength(1))
    expect(onToast.mock.calls.filter(([, kind]) => kind === '')).toEqual([])

    open()
    await adding
    expect(state.chart.indicators()[0].values().p0).toEqual([65, 65, 65, 65])
    expect(onToast.mock.calls.filter(([, kind]) => kind === '')).toEqual([])
  })
})
