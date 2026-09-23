/**
 * Which saved scripts reach the chart's indicator list, and how.
 *
 * **Every saved script reaches it, including a strategy.** A strategy has
 * plots, a title and settings exactly as a study does, and a trader who saved
 * one should find it where they look for it. What differs is the destination:
 * a program needing `orders` is refused by the engine at load with OS6006
 * unless it is given one, so it is run against the language's own simulated
 * venue. Nothing here can place an order; the chart has no route to the
 * platform and is given none.
 *
 * Each test names the wrong implementation it catches.
 */

import type { IndicatorAttachContext } from 'openalgo-charts'
import type {
  ChartAdapterOptions,
  ChartAlertContext,
  ChartBar,
  ChartDescriptor,
  ChartStore,
  ChartValues,
} from 'openalgo-script/adapters/charts'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearInstrumentFacts, factsFor, type InstrumentFacts } from './instrumentFacts'

const registerIndicator = vi.fn()
vi.mock('openalgo-charts', async (importOriginal) => ({
  // The chart's own clock conversions are real: they are what a time input is
  // read with, and a stand-in would test the stand-in.
  ...(await importOriginal<typeof import('openalgo-charts')>()),
  registerIndicator,
}))

const descriptorFor = vi.fn((_program: unknown, options?: ChartAdapterOptions) => ({
  id: options?.id ?? 'probe',
  plots: [],
}))
vi.mock('openalgo-script/adapters/charts', () => ({ descriptorFor }))

/** The options the adapter was handed on its first call. */
const firstOptions = (): ChartAdapterOptions => descriptorFor.mock.calls[0]?.[1] ?? {}

/** A compiled program carrying whatever capability tags a test needs. */
let requires: string[] = ['core.1']
vi.mock('openalgo-script', () => ({
  sourceFile: () => ({}),
  lex: () => [],
  parseTokens: () => ({}),
  check: () => ({}),
  emit: () => ({ program: { requires } }),
  DiagnosticBag: class {
    ordered() {
      return []
    }
  },
  renderDiagnostics: () => '',
}))

const {
  forgetOpenScriptStudies,
  hostedStudy,
  loadOpenScriptStudies,
  SCRIPT_ALERT_EVENT,
  wallClockReader,
} = await import('./openscriptStudies')
const charts = await import('openalgo-charts')

/** The server: an index of one script, then its source. */
function serving(file: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      String(url).includes('index.json')
        ? { ok: true, json: async () => [{ file, mtime: 1 }] }
        : { ok: true, text: async () => 'version 1\nstudy("s")\n' }
    )
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  forgetOpenScriptStudies()
  requires = ['core.1']
})

describe('what reaches the chart', () => {
  it('registers a program the chart tier can run', async () => {
    requires = ['core.1', 'arrays', 'alerts']
    serving('a-study.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toEqual(['a-study.oscript'])
    expect(out.errors).toEqual([])
    expect(registerIndicator).toHaveBeenCalledTimes(1)
  })

  it('registers a strategy, with a destination it can safely have', async () => {
    // THE ONE THAT MATTERS. A strategy has plots, a title and settings exactly
    // as a study does, and none of them reached the chart: a trader who saved
    // one could not find it in the indicator list, so its lines had to come
    // from a separate study kept in step by hand.
    //
    // `simulateOrders` is what makes registering it safe. Without it the engine
    // refuses a program that places orders (OS6006), and with a destination
    // that answered nothing it would run while never learning it holds a
    // position: every close closing nothing, and the plots wrong wherever they
    // read one.
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toEqual(['a-strategy.oscript'])
    expect(registerIndicator).toHaveBeenCalledTimes(1)
    expect(descriptorFor.mock.calls[0][1]).toMatchObject({ simulateOrders: true })
  })

  it('never asks for a destination for a study', async () => {
    // Catches the option passed to everything. A study places no orders, so a
    // venue for it is a thing built and never used, and an option set where it
    // has no meaning is the next reader's question.
    requires = ['core.1']
    serving('a-study.oscript')

    await loadOpenScriptStudies()

    expect(firstOptions().simulateOrders).toBeUndefined()
  })

  it('reports a strategy as loaded and never as an error', async () => {
    requires = ['core.1', 'orders']
    serving('a-strategy.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.errors).toEqual([])
    expect(out.loaded).toEqual(['a-strategy.oscript'])
  })

  it('reads the requirement off the program, not off the word in the source', async () => {
    // Catches a filter written against `strategy(` in the text. `requires` is
    // the same fact the engine tests, so a strategy placing no orders would be
    // drawable and this must follow the program rather than the keyword.
    requires = ['core.1']
    serving('declares-strategy-but-orders-nothing.oscript')

    const out = await loadOpenScriptStudies()

    expect(out.loaded).toHaveLength(1)
    // The name says strategy and the program places nothing, so no venue is
    // built for it. A filter written against the text would get this backwards.
    expect(firstOptions().simulateOrders).toBeUndefined()
  })

  it('hands the adapter a reader for time inputs, under the id a layout names', async () => {
    // Catches the option left out, which is what read 09:15 on an IST chart
    // as 09:15 UTC and put the anchor at 14:45. And a wrapper registering an
    // id of its own: a layout stores the id, so a different one drops the
    // study off every saved chart.
    serving('a-study.oscript')

    await loadOpenScriptStudies()

    expect(registerIndicator.mock.calls[0][0].id).toBe('openscript:a-study')
    expect(firstOptions().resolveTime?.('2026-09-21 09:15', 'Asia/Kolkata')).toBe(
      Date.UTC(2026, 8, 21, 3, 45) / 1000
    )
  })
})

describe('reading a time input', () => {
  const read = wallClockReader(charts)

  it('reads the wall clock in the zone it is given', () => {
    expect(read('2026-09-21 09:15', 'Asia/Kolkata')).toBe(Date.UTC(2026, 8, 21, 3, 45) / 1000)
    expect(read('2026-09-21T09:15:30', 'Asia/Kolkata')).toBe(
      Date.UTC(2026, 8, 21, 3, 45, 30) / 1000
    )
    expect(read('2026-09-21', 'Asia/Kolkata')).toBe(Date.UTC(2026, 8, 20, 18, 30) / 1000)
  })

  it('follows a seasonal clock change rather than a fixed offset', () => {
    // New York is four hours behind UTC in July and five in January. A reader
    // holding one offset gets one of these wrong.
    expect(read('2026-07-01 09:30', 'America/New_York')).toBe(Date.UTC(2026, 6, 1, 13, 30) / 1000)
    expect(read('2026-01-05 09:30', 'America/New_York')).toBe(Date.UTC(2026, 0, 5, 14, 30) / 1000)
  })

  it('refuses what is not a date and time, rather than guessing one', () => {
    expect(() => read('09:15', 'Asia/Kolkata')).toThrow()
    // Date.UTC would roll this into March, a day the trader never typed.
    expect(() => read('2026-02-30 09:15', 'Asia/Kolkata')).toThrow()
    expect(() => read('2026-09-21 25:00', 'Asia/Kolkata')).toThrow()
    expect(() => read('2026-09-21 09:15', 'Not/AZone')).toThrow()
  })

  it('reads a string as UTC where no zone is stated, as the engine does', () => {
    expect(read('2026-09-21 09:15', '')).toBe(Date.UTC(2026, 8, 21, 9, 15) / 1000)
  })
})

/**
 * `hostedStudy`, against descriptors that stand in for the adapter's.
 *
 * Each stand-in computes a column from the lot size it was built with, and
 * holds an engine in the store after a full calculation. Its tail continues
 * whatever engine the store holds, which is what the adapter's own tail does:
 * it checks the settings and the bar times, not which descriptor built the
 * engine. Keeping a tail on the right one is this host's job.
 */
describe('hosting one study on several charts', () => {
  type Built = ChartDescriptor & { instrument?: InstrumentFacts }

  const REPLY = (exchange: string, lotSize: number) => ({
    status: 'success',
    instrument: {
      exchange,
      timezone: 'Asia/Kolkata',
      lotSize,
      hasVolume: true,
      session: { start: '09:15', end: '15:30', days: [1, 2, 3, 4, 5] },
    },
    today: { date: '2026-09-21', open: true, isSpecial: false },
  })

  let lots: Record<string, number> = {}
  let built: Built[] = []

  /** A column per bar: 1 on a confirmed bar that closed above 100, as an alert flag is. */
  const flags = (bars: readonly ChartBar[], from: number) =>
    bars.slice(from).map((bar, i) => (from + i < bars.length - 1 && bar.close > 100 ? 1 : null))

  function build(instrument?: InstrumentFacts): ChartDescriptor {
    const self: Built = {
      id: 'openscript:probe',
      name: 'Probe',
      placement: 'onchart',
      inputs: [],
      plots: [],
      instrument,
      alerts: [
        {
          id: 'above',
          title: 'Above',
          message: (ctx: ChartAlertContext) => `closed at ${ctx.bars[ctx.index]?.close}`,
          when: (ctx: ChartAlertContext) => ctx.values.flag?.[ctx.index] === 1,
        },
      ],
      calc: vi.fn((bars: readonly ChartBar[], _settings, store: ChartStore) => {
        store.held = self
        return { lot: bars.map(() => instrument?.lotSize ?? null), flag: flags(bars, 0) }
      }),
      calcTail: vi.fn(
        (bars: readonly ChartBar[], _settings, from: number, _p, store: ChartStore) =>
          store.held !== undefined
            ? {
                lot: bars.slice(from).map(() => instrument?.lotSize ?? null),
                flag: flags(bars, from),
              }
            : null
      ),
    }
    built.push(self)
    return self
  }

  const bar = (time: number, close = 99): ChartBar => ({
    time,
    open: close,
    high: close,
    low: close,
    close,
  })

  function context(zone = 'Asia/Kolkata') {
    return {
      barState: { isNew: false, isConfirmed: false, isRealtime: false, lastIndex: 0 },
      symbol: 'SAMEFUT',
      interval: '1m',
      timezone: zone,
      now: () => 0,
    }
  }

  function attached(
    study: ReturnType<typeof hostedStudy>,
    exchange: string,
    store: ChartStore = {},
    zone = 'Asia/Kolkata'
  ) {
    const requestRecompute = vi.fn()
    const emit = vi.fn()
    const detach = study.attach({
      store,
      dataContext: () => ({ symbol: 'SAMEFUT', exchange, interval: '1m' }),
      requestRecompute,
      emit,
      timezone: () => zone,
      settings: () => ({}),
      bars: () => [],
    } as unknown as IndicatorAttachContext)
    return { store, requestRecompute, emit, detach }
  }

  beforeEach(() => {
    clearInstrumentFacts()
    built = []
    lots = { NFO: 25, BFO: 20 }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        const exchange = new URL(String(url), 'http://host.invalid').searchParams.get('exchange')
        const lot = exchange ? lots[exchange] : undefined
        return lot === undefined
          ? { ok: false, json: async () => ({}) }
          : { ok: true, json: async () => REPLY(exchange ?? '', lot) }
      })
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('runs as before while facts load, then asks the chart to recompute', async () => {
    const study = hostedStudy('openscript:probe', build)
    const settings = {}
    const bars = [bar(60), bar(120)]
    // The chart's order: one calculation as the study is built, then attach.
    const store: ChartStore = {}
    expect(study.calc(bars, settings, store, context()).lot).toEqual([null, null])
    const { requestRecompute } = attached(study, 'NFO', store)
    expect(requestRecompute).not.toHaveBeenCalled()

    await factsFor('SAMEFUT', 'NFO')

    expect(requestRecompute).toHaveBeenCalledTimes(1)
    expect(study.calc(bars, settings, store, context()).lot).toEqual([25, 25])
  })

  it('keeps a tail on the descriptor that ran the full calculation', async () => {
    const study = hostedStudy('openscript:probe', build)
    const settings = {}
    const { store } = attached(study, 'NFO')
    study.calc([bar(60), bar(120)], settings, store, context())
    await factsFor('SAMEFUT', 'NFO')

    // The facts are here, and the held engine was built without them: a tail
    // now would splice a lot size onto a history computed with none.
    const bars = [bar(60), bar(120), bar(180)]
    expect(study.calcTail?.(bars, settings, 1, {}, store, context())).toBeNull()

    study.calc(bars, settings, store, context())
    const tail = study.calcTail?.([...bars, bar(240)], settings, 2, {}, store, context())
    expect(tail?.lot).toEqual([25, 25])
    // The chart moving to another zone is the same kind of change.
    expect(study.calcTail?.(bars, settings, 2, {}, store, context('UTC'))).toBeNull()
  })

  it('gives each chart the facts of its own instrument', async () => {
    const study = hostedStudy('openscript:probe', build)
    const nfo = attached(study, 'NFO')
    const bfo = attached(study, 'BFO')
    await factsFor('SAMEFUT', 'NFO')
    await factsFor('SAMEFUT', 'BFO')

    const bars = [bar(60)]
    expect(study.calc(bars, {}, nfo.store, context()).lot).toEqual([25])
    expect(study.calc(bars, {}, bfo.store, context()).lot).toEqual([20])
  })

  it('states the regular session, and none where the chart reads another zone', async () => {
    const study = hostedStudy('openscript:probe', build)
    const { store } = attached(study, 'NFO')
    await factsFor('SAMEFUT', 'NFO')

    study.calc([bar(60)], {}, store, context('Asia/Kolkata'))
    expect(built.at(-1)?.instrument?.session).toEqual({
      start: '09:15',
      end: '15:30',
      days: [1, 2, 3, 4, 5],
    })
    study.calc([bar(60)], {}, store, context('Asia/Calcutta'))
    expect(built.at(-1)?.instrument?.session).toBeDefined()
    study.calc([bar(60)], {}, store, context('America/New_York'))
    expect(built.at(-1)?.instrument?.session).toBeUndefined()
    expect(built.at(-1)?.instrument?.lotSize).toBe(25)
  })

  it('calculates a new chart on the exchange last seen for its symbol', async () => {
    // The chart calculates a study once before it attaches it. Without a first
    // guess, every rebuilt chart would calculate every study twice.
    const study = hostedStudy('openscript:probe', build)
    attached(study, 'NFO')
    await factsFor('SAMEFUT', 'NFO')

    const store: ChartStore = {}
    expect(study.calc([bar(60)], {}, store, context()).lot).toEqual([25])
    const { requestRecompute } = attached(study, 'NFO', store)
    expect(requestRecompute).not.toHaveBeenCalled()

    // A guess naming the wrong exchange is put right when the chart says.
    const other: ChartStore = {}
    study.calc([bar(60)], {}, other, context())
    const wrong = attached(study, 'BFO', other)
    await factsFor('SAMEFUT', 'BFO')
    expect(wrong.requestRecompute).toHaveBeenCalled()
  })

  it('stops listening when the chart detaches the study', async () => {
    const study = hostedStudy('openscript:probe', build)
    const store: ChartStore = {}
    study.calc([bar(60)], {}, store, context())
    const { requestRecompute, detach } = attached(study, 'NFO', store)
    detach()
    await factsFor('SAMEFUT', 'NFO')
    expect(requestRecompute).not.toHaveBeenCalled()
  })

  describe('bar-close alerts', () => {
    /** History of three bars, a live tick on the third, then a fourth bar. */
    function live(closes: [number, number]) {
      const study = hostedStudy('openscript:probe', build)
      const settings = {}
      const { store, emit } = attached(study, 'NOWHERE')
      const history = [bar(60), bar(120), bar(180)]
      let values: ChartValues = study.calc(history, settings, store, context())
      const tick = [bar(60), bar(120), bar(180, closes[0])]
      const replaced = study.calcTail?.(tick, settings, 2, values, store, context())
      values = { ...values, flag: [...(values.flag ?? []).slice(0, 2), ...(replaced?.flag ?? [])] }
      const next = [...tick, bar(240, closes[1])]
      return { study, settings, store, emit, values, next }
    }

    it('announces the closed bar, with its own message, when the next bar opens', () => {
      const { study, settings, store, emit, values, next } = live([101, 99])
      study.calcTail?.(next, settings, 2, values, store, context())
      expect(emit).toHaveBeenCalledTimes(1)
      expect(emit).toHaveBeenCalledWith(SCRIPT_ALERT_EVENT, {
        indicatorId: 'openscript:probe',
        alertId: 'above',
        title: 'Above',
        message: 'closed at 101',
        time: 180,
        index: 2,
      })
    })

    it('says nothing for a bar whose condition did not hold at the close', () => {
      const { study, settings, store, emit, values, next } = live([99, 101])
      study.calcTail?.(next, settings, 2, values, store, context())
      expect(emit).not.toHaveBeenCalled()
    })

    it('never announces a bar no live pass reached', () => {
      const study = hostedStudy('openscript:probe', build)
      const settings = {}
      const { store, emit } = attached(study, 'NOWHERE')
      const history = [bar(60), bar(120), bar(180, 101)]
      const values = study.calc(history, settings, store, context())
      study.calcTail?.([...history, bar(240)], settings, 2, values, store, context())
      expect(emit).not.toHaveBeenCalled()
    })

    it('leaves alone a bar and alert the chart already fired', () => {
      const { study, settings, store, emit, values, next } = live([101, 99])
      // The chart judged the bar on its first tick and fired. Only a study
      // that fires on a moving bar can be true there, and it must not repeat.
      const fired = study.alerts?.[0]?.when({
        bars: next,
        values: { flag: [null, null, 1] },
        settings,
        index: 2,
      })
      expect(fired).toBe(true)
      study.calcTail?.(next, settings, 2, values, store, context())
      expect(emit).not.toHaveBeenCalled()
    })
  })
})
