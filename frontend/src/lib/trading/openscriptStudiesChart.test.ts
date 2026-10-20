/**
 * A saved script on a real chart, with nothing in between mocked.
 *
 * The compiler, the language's chart adapter and the chart are the installed
 * packages; only the server is replaced, by a `fetch` that serves the script
 * list, the source and the instrument facts. What is asserted is what the chart
 * ends up holding, because every defect this file pins was a descriptor that
 * looked right and a chart that drew something else:
 *
 * - a study registered once for every chart, so no chart told the engine its
 *   exchange, lot size or session, and every session fact was absent;
 * - a `"time"` input read as UTC, so 09:15 on an IST chart meant 14:45;
 * - an alert that waits for its bar to close, which the chart judged on the
 *   bar's first tick and never again, so it never fired live.
 */

import { type Bar, createChart } from 'openalgo-charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearInstrumentFacts, factsFor } from './instrumentFacts'
import {
  forgetOpenScriptStudies,
  loadOpenScriptStudies,
  SCRIPT_ALERT_EVENT,
  type ScriptAlertPayload,
} from './openscriptStudies'

/** Reads the three facts this change is about, and raises one alert. */
const PROBE = `version 1

study("Probe", overlay = true)

anchor = input("2026-09-21 09:15", "Anchor", kind = "time")

plot(chart.lotSize, "Lot")
plot(session.isFirstBar ? 1 : 0, "First")
plot(anchor / 1000, "Anchor")

if close > 100
    alert("Above " + text(close, 2), id = "above")
`

/** The same alert, allowed to fire on a bar that is still moving. */
const EAGER = `version 1

study("Eager", overlay = true, onUnconfirmed = true)

plot(close, "Close")

if close > 100
    alert("Above " + text(close, 2), id = "above")
`

const SOURCES: Record<string, string> = { 'probe.oscript': PROBE, 'eager.oscript': EAGER }

/** Monday 21 September 2026, 09:13 IST, as the chart holds a time. */
const MONDAY_0913 = Date.UTC(2026, 8, 21, 3, 43) / 1000

/** The facts route's answer for one instrument. */
function factsReply(exchange: string, lotSize: number) {
  return {
    status: 'success',
    contractFound: true,
    instrument: {
      exchange,
      timezone: 'Asia/Kolkata',
      tickSize: 0.05,
      lotSize,
      instrumentType: 'future',
      hasVolume: true,
      hasOpenInterest: true,
      session: { start: '09:15', end: '15:30', days: [1, 2, 3, 4, 5] },
    },
    today: {
      date: '2026-09-21',
      open: true,
      isSpecial: false,
      session: { start: '09:15', end: '15:30', days: [1] },
    },
  }
}

/** Lot size by exchange, which is what tells two charts' answers apart. */
let lots: Record<string, number> = {}

beforeEach(() => {
  forgetOpenScriptStudies()
  clearInstrumentFacts()
  lots = { NFO: 25, BFO: 20 }
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
    vi.fn(async (url: string) => {
      const u = new URL(String(url), 'http://host.invalid')
      if (u.pathname === '/openscript/index.json') {
        return {
          ok: true,
          json: async () => Object.keys(SOURCES).map((file) => ({ file, mtime: 1, bytes: 1 })),
        }
      }
      if (u.pathname === '/openscript/instrument') {
        const exchange = u.searchParams.get('exchange') ?? ''
        const lot = lots[exchange]
        return lot === undefined
          ? { ok: false, json: async () => ({}) }
          : { ok: true, json: async () => factsReply(exchange, lot) }
      }
      const file = decodeURIComponent(u.pathname.replace('/openscript/', ''))
      return { ok: true, text: async () => SOURCES[file] ?? '' }
    })
  )
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

/** A chart showing one instrument, with a clock the test sets. */
function chartOf(symbol: string, exchange: string, bars: Bar[], clock = { now: 0 }) {
  const chart = createChart(document.createElement('div'), {
    shortcuts: false,
    timeNavigator: false,
    axisChrome: { clock: () => clock.now },
    raf: {
      schedule: (cb) => {
        cb()
        return 1
      },
      cancel() {},
    },
  })
  chart.applySize(800, 600)
  chart.setDataContext({ symbol, exchange, interval: '1m' })
  const price = chart.addSeries('candlestick')
  price.setData(bars)
  return { chart, price, clock }
}

/** Minute bars from 09:13 IST, one close each. */
function minutes(closes: number[]): Bar[] {
  return closes.map((close, i) => ({
    time: MONDAY_0913 + i * 60,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
  }))
}

/** Lets a fetch that has already been answered finish arriving. */
async function settled(symbol: string, exchange: string) {
  await factsFor(symbol, exchange)
}

describe('instrument facts on the chart', () => {
  it('reads the chart instrument, once its facts arrive, under the id a layout saved', async () => {
    await loadOpenScriptStudies()
    const { chart } = chartOf('NIFTY29SEP26FUT', 'NFO', minutes([99, 99, 99, 99, 99]))
    const study = chart.addIndicator('openscript:probe')

    // Before the facts: exactly what the chart drew before there were any.
    expect(study.values().p0).toEqual([null, null, null, null, null])
    expect(study.values().p1).toEqual([0, 0, 0, 0, 0])

    await settled('NIFTY29SEP26FUT', 'NFO')

    // THE ONE THAT MATTERS. The lot size and the session reach the engine, and
    // the session's first bar is 09:15 IST, the third bar here.
    expect(chart.indicators()[0]).toBe(study)
    expect(study.values().p0).toEqual([25, 25, 25, 25, 25])
    expect(study.values().p1).toEqual([0, 0, 1, 0, 0])
    expect(study.indicatorId).toBe('openscript:probe')
  })

  it('gives two charts of one symbol on two exchanges their own facts', async () => {
    // One registered study, two panes. A symbol is not an instrument: the same
    // name trades on more than one exchange, and each chart states its own.
    await loadOpenScriptStudies()
    const nfo = chartOf('SAMEFUT', 'NFO', minutes([99, 99, 99]))
    const bfo = chartOf('SAMEFUT', 'BFO', minutes([99, 99, 99]))
    const a = nfo.chart.addIndicator('openscript:probe')
    const b = bfo.chart.addIndicator('openscript:probe')

    await settled('SAMEFUT', 'NFO')
    await settled('SAMEFUT', 'BFO')

    expect(a.values().p0).toEqual([25, 25, 25])
    expect(b.values().p0).toEqual([20, 20, 20])
  })

  it('leaves the session out when the chart reads another zone', async () => {
    // The adapter reads the session in the chart's zone. 09:15 read in UTC is
    // 14:45 IST, so a session there is a wrong answer rather than an absent one.
    await loadOpenScriptStudies()
    const { chart } = chartOf('NIFTY29SEP26FUT', 'NFO', minutes([99, 99, 99, 99, 99]))
    chart.setTimezone('UTC')
    const study = chart.addIndicator('openscript:probe')
    await settled('NIFTY29SEP26FUT', 'NFO')

    expect(study.values().p0).toEqual([25, 25, 25, 25, 25])
    expect(study.values().p1).toEqual([0, 0, 0, 0, 0])
  })
})

describe('time inputs', () => {
  it('reads a time input as wall clock in the chart zone', async () => {
    await loadOpenScriptStudies()
    const { chart } = chartOf('NIFTY29SEP26FUT', 'NFO', minutes([99, 99]))
    const study = chart.addIndicator('openscript:probe')
    // 09:15 in Asia/Kolkata, not 09:15 UTC.
    expect(study.values().p2?.[0]).toBe(Date.UTC(2026, 8, 21, 3, 45) / 1000)

    chart.setTimezone('America/New_York')
    chart.indicators()
    // The same wall clock, read in the zone the chart now shows.
    expect(study.values().p2?.[0]).toBe(Date.UTC(2026, 8, 21, 13, 15) / 1000)
  })
})

describe('alerts on a live chart', () => {
  function heard(chart: ReturnType<typeof createChart>) {
    const script: ScriptAlertPayload[] = []
    const chartOwn: unknown[] = []
    chart.on(SCRIPT_ALERT_EVENT, (payload) => script.push(payload as ScriptAlertPayload))
    chart.on('indicator:alert', (payload) => chartOwn.push(payload))
    return { script, chartOwn }
  }

  it('fires a bar-close alert once, when a bar it saw live closes, and never for history', async () => {
    await loadOpenScriptStudies()
    // The history ends on a bar above 100. It closes on the first tick of the
    // next bar, and no live update ever reached it here: it may be yesterday's.
    const history = minutes([99, 99, 101])
    const first = history[2].time
    const { chart, price, clock } = chartOf('NIFTY29SEP26FUT', 'NFO', history, {
      now: first + 10,
    })
    chart.addIndicator('openscript:probe')
    const { script, chartOwn } = heard(chart)

    const last = first + 60
    clock.now = last + 1
    price.update({ time: last, open: 99, high: 99, low: 99, close: 99 })
    chart.indicators()
    expect(script).toEqual([])

    // A tick lifts the forming bar above 100. It is still moving, so the
    // alert is withheld: the language fires on a closed bar.
    clock.now = last + 30
    price.update({ time: last, open: 99, high: 102, low: 98, close: 101 })
    chart.indicators()
    expect(script).toEqual([])

    // The next minute opens. The engine now decides the bar that closed.
    clock.now = last + 61
    price.update({ time: last + 60, open: 99, high: 99, low: 99, close: 99 })
    chart.indicators()
    expect(script).toEqual([
      {
        indicatorId: 'openscript:probe',
        alertId: 'above',
        title: expect.any(String),
        message: 'Above 101.00',
        time: last,
        index: 3,
      },
    ])
    expect(chartOwn).toEqual([])

    // More ticks, and the minute after, fire nothing more for that bar.
    clock.now = last + 70
    price.update({ time: last + 60, open: 99, high: 99, low: 98, close: 98 })
    clock.now = last + 121
    price.update({ time: last + 120, open: 98, high: 98, low: 98, close: 98 })
    chart.indicators()
    expect(script).toHaveLength(1)
  })

  it('fires a moving-bar alert on its first tick or at its close, never both', async () => {
    // `onUnconfirmed = true` lets the alert fire on a moving bar. The chart
    // fires it when the bar first arrives, and only then, so a condition that
    // turns true later in the bar is announced at the close instead.
    await loadOpenScriptStudies()
    const history = minutes([99, 99, 99])
    const start = history[2].time
    const { chart, price, clock } = chartOf('NIFTY29SEP26FUT', 'NFO', history, {
      now: start + 10,
    })
    chart.addIndicator('openscript:eager')
    const { script, chartOwn } = heard(chart)

    // True on its first tick: the chart fires it, and its close repeats nothing.
    clock.now = start + 61
    price.update({ time: start + 60, open: 101, high: 101, low: 101, close: 101 })
    chart.indicators()
    expect(chartOwn).toHaveLength(1)
    clock.now = start + 90
    price.update({ time: start + 60, open: 101, high: 102, low: 101, close: 101.5 })
    clock.now = start + 121
    price.update({ time: start + 120, open: 99, high: 99, low: 99, close: 99 })
    chart.indicators()
    expect(chartOwn).toHaveLength(1)
    expect(script).toEqual([])

    // True only later in the bar: the chart has moved on, so the close says it.
    clock.now = start + 150
    price.update({ time: start + 120, open: 99, high: 102, low: 99, close: 102 })
    clock.now = start + 181
    price.update({ time: start + 180, open: 99, high: 99, low: 99, close: 99 })
    chart.indicators()
    expect(chartOwn).toHaveLength(1)
    expect(script.map((one) => one.message)).toEqual(['Above 102.00'])
  })
})
