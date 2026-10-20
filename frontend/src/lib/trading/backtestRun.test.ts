/**
 * The backtest run, held to the things that fail quietly.
 *
 * Every test below names the wrong implementation it catches. The three worth
 * the most are the clock, the instrument facts and the refusal branch: each of
 * them produces a report that looks entirely normal and is wrong, which is the
 * only kind of defect a trader cannot catch by reading the screen.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.fn()
vi.mock('@/api/client', () => ({ apiClient: { post: (...args: unknown[]) => post(...args) } }))

const compileSource = vi.fn()
vi.mock('./openscriptFiles', () => ({
  compileSource: (...args: unknown[]) => compileSource(...args),
}))

const backtest = vi.fn()
const settingsFor = vi.fn((contract: unknown) => ({ contract }))
vi.mock('openalgo-script', () => ({
  backtest: (...args: unknown[]) => backtest(...args),
  settingsFor: (contract: unknown) => settingsFor(contract),
}))

// The instrument facts route. Undefined is the route not answering, which is
// what every test above the facts section runs under.
const factsFor = vi.fn()
vi.mock('./instrumentFacts', () => ({
  factsFor: (...args: unknown[]) => factsFor(...args),
}))

const {
  barsFromHistory,
  contractFor,
  contractFromFacts,
  engineInterval,
  MAX_BARS,
  runBacktest,
  runInstrumentFrom,
} = await import('./backtestRun')

/** One history row as the platform answers it: seconds, not milliseconds. */
function row(at: number) {
  return { timestamp: 1_700_000_000 + at * 60, open: 100, high: 101, low: 99, close: 100, volume: 5 }
}

function aRequest(overrides: Record<string, unknown> = {}) {
  return {
    file: 'x.oscript',
    source: 'strategy("x")',
    symbol: 'AAA',
    exchange: 'XX',
    interval: '1m',
    startDate: '2026-01-01',
    endDate: '2026-02-01',
    apiKey: 'key',
    ...overrides,
  } as Parameters<typeof runBacktest>[0]
}

/** A platform that answers history, then the instrument, in that order. */
function answering(rows: unknown[], instrument: unknown = { lotsize: 50, tick_size: 0.05 }) {
  post.mockImplementation(async (url: string) => {
    if (url === '/history') return { data: { status: 'success', data: rows } }
    if (url === '/symbol') return { data: { status: 'success', data: instrument } }
    return { data: { status: 'error' } }
  })
}

function compiles(extra: Record<string, unknown> = {}) {
  compileSource.mockResolvedValue({
    ok: true,
    kind: 'strategy',
    program: '{"openscript":{}}',
    diagnostics: [],
    ...extra,
  })
}

function ran(summary: Record<string, unknown> = { netProfit: 10 }) {
  backtest.mockReturnValue({
    ok: true,
    record: { report: { summary, trades: [], equity: [], markers: [] } },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  factsFor.mockResolvedValue(undefined)
})

describe('the clock', () => {
  it('turns the history API seconds into the milliseconds the engine counts', () => {
    // THE ONE THAT MATTERS MOST. The platform's history API counts seconds and
    // the engine counts milliseconds. Handed the platform's own numbers the
    // engine places every bar in January 1970, the report window excludes all
    // of them, and the run answers a summary of nothing while looking fine.
    const bars = barsFromHistory([row(0), row(1)])

    expect(bars[0].time).toBe(1_700_000_000_000)
    expect(bars[1].time).toBe(1_700_000_060_000)
  })

  it('carries a hole through as absence rather than as a zero', () => {
    // Catches a fold that coerces a missing price to 0. A zero close is a real
    // price the engine will trade against; an absent one propagates.
    const bars = barsFromHistory([
      { timestamp: 1_700_000_000, open: 1, high: 2, low: 0.5, close: Number.NaN },
    ] as never)

    expect(bars[0].close).toBeNull()
    expect(bars[0].volume).toBeNull()
  })
})

describe('the instrument facts', () => {
  it('reads the stored tick and lot size, and says it did not fall back', async () => {
    post.mockResolvedValue({ data: { status: 'success', data: { lotsize: 65, tick_size: 0.05 } } })

    const contract = await contractFor('AAA', 'XX', 'key')

    expect(contract.lotSize).toBe(65)
    expect(contract.tickSize).toBe(0.05)
    expect(contract.usedFallback).toBe(false)
  })

  it('falls back on an instrument the platform has no row for, and records that', async () => {
    // Catches a silent default. Every figure in money rests on the tick and the
    // lot, so a run that guessed them is wrong by a factor with a report that
    // reads perfectly. The flag is what lets the panel say so.
    post.mockResolvedValue({ data: { status: 'error' } })

    const contract = await contractFor('AAA', 'XX', 'key')

    expect(contract.usedFallback).toBe(true)
    expect(contract.lotSize).toBeGreaterThan(0)
  })

  it('treats a zero or negative tick as no answer rather than as a tick', async () => {
    // Catches a truthiness check. A tick of 0 would divide by zero downstream
    // and a negative one would round prices the wrong way.
    post.mockResolvedValue({ data: { status: 'success', data: { lotsize: 1, tick_size: 0 } } })

    expect((await contractFor('AAA', 'XX', 'key')).usedFallback).toBe(true)
  })
})

describe('what stops a run', () => {
  it('refuses a study, because only a strategy has trades', async () => {
    compiles({ kind: 'study' })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toMatch(/study/i)
    expect(post).not.toHaveBeenCalled()
  })

  it('reports the script diagnostics rather than a problem when it does not compile', async () => {
    // Catches the two being folded together. A script error belongs under the
    // editor's own heading; a network fault is not about the script at all, and
    // a reader should not have to work out which they are looking at.
    compileSource.mockResolvedValue({
      ok: false,
      diagnostics: [{ code: 'OS2001', line: 3, column: 1, message: 'nope', severity: 'error' }],
    })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toBeUndefined()
    expect(out.diagnostics?.[0].code).toBe('OS2001')
  })

  it('compiles before it fetches, so a broken script does not cost a history call', async () => {
    compileSource.mockResolvedValue({ ok: false, diagnostics: [] })

    await runBacktest(aRequest())

    expect(post).not.toHaveBeenCalled()
  })

  it('refuses a range with no bars in it rather than reporting an empty run', async () => {
    // Catches a run over zero bars, which the engine answers happily with a
    // summary of nothing. A trader reads that as the strategy taking no trades.
    compiles()
    answering([])

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toMatch(/no bars/i)
    expect(backtest).not.toHaveBeenCalled()
  })

  it('refuses a range past the ceiling, naming the count', async () => {
    // Catches the ceiling being absent. The engine takes over a second at a
    // hundred thousand bars with the whole workspace frozen through it.
    compiles()
    answering(Array.from({ length: MAX_BARS + 1 }, (_, at) => row(at)))

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toContain((MAX_BARS + 1).toLocaleString())
    expect(backtest).not.toHaveBeenCalled()
  })

  it('reports an engine refusal with its code instead of pretending it ran', async () => {
    // THE BRANCH THE TYPECHECKER FOUND. backtest answers a union: a record, or a
    // refusal before the first bar (two cost models, a quantity it cannot size).
    // Reading .record off the refusal is undefined, and the panel would have
    // shown a report of nothing.
    compiles()
    answering([row(0), row(1)])
    backtest.mockReturnValue({
      ok: false,
      diagnostic: { code: 'OS6023', message: 'two cost models at once' },
    })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toContain('OS6023')
  })

  it('answers a history failure as a problem, not as a crash', async () => {
    compiles()
    post.mockRejectedValue(new Error('offline'))

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toMatch(/history/i)
  })
})

describe('a run that works', () => {
  it('hands the engine the converted bars and the instrument it read', async () => {
    compiles()
    answering([row(0), row(1), row(2)])
    ran({ netProfit: 123 })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(true)
    expect(out.summary?.netProfit).toBe(123)
    expect(out.barCount).toBe(3)
    expect(out.contract?.lotSize).toBe(50)

    const handedBars = backtest.mock.calls[0][1] as { time: number }[]
    expect(handedBars[0].time).toBe(1_700_000_000_000)
    expect(settingsFor).toHaveBeenCalledWith(expect.objectContaining({ lotSize: 50, tickSize: 0.05 }))
  })

  it('parses the program from canonical text rather than handing over the string', async () => {
    // Catches the program being passed as text. The engine takes the object; a
    // string reaches it as something with no instructions on it.
    compiles()
    answering([row(0)])
    ran()

    await runBacktest(aRequest())

    expect(backtest.mock.calls[0][0]).toEqual({ openscript: {} })
  })
})

/** The facts route's answer for an instrument, as the helper hands it over. */
function someFacts(overrides: Record<string, unknown> = {}) {
  return Object.freeze({
    exchange: 'XX',
    timezone: 'Asia/Kolkata',
    tickSize: 0.1,
    lotSize: 75,
    instrumentType: 'future',
    hasVolume: true,
    hasOpenInterest: true,
    session: Object.freeze({ start: '09:00', end: '17:00', days: Object.freeze([1, 2, 3]) }),
    ...overrides,
  })
}

describe('the interval, as the engine spells it', () => {
  it('writes a day, a week and a month with the count the engine reads', () => {
    // THE SPELLING THAT DIFFERS. The chart writes a daily bar as a bare "D",
    // which the engine's grammar has no reading for: stated as it is, the
    // interval is unreadable and every fact derived from it is absent.
    expect(engineInterval('D')).toBe('1D')
    expect(engineInterval('W')).toBe('1W')
    expect(engineInterval('M')).toBe('1M')
  })

  it('passes minutes and hours through, since both already agree', () => {
    expect(engineInterval('1m')).toBe('1m')
    expect(engineInterval('15m')).toBe('15m')
    expect(engineInterval('1h')).toBe('1h')
  })

  it('states nothing for seconds, which the engine has no unit for', () => {
    // Catches a seconds chart being handed over as it is. The engine would hold
    // an interval it cannot read, which is a different thing from no interval
    // and not one the specification allows.
    expect(engineInterval('5s')).toBeUndefined()
    expect(engineInterval('')).toBeUndefined()
    expect(engineInterval('0m')).toBeUndefined()
  })
})

describe('what the engine is told beside the contract', () => {
  it('states the interval, the zone, the session and the rest of the facts', () => {
    const told = runInstrumentFrom('D', someFacts())

    expect(told).toEqual({
      interval: '1D',
      timezone: 'Asia/Kolkata',
      session: { start: '09:00', end: '17:00', days: [1, 2, 3] },
      instrumentType: 'future',
      hasVolume: true,
      hasOpenInterest: true,
    })
  })

  it('leaves the contract facts to the contract', () => {
    // The engine's type excludes them because a tick size stated twice is a
    // tick size that can disagree with itself. The compiler holds the type;
    // this holds the value, since spreading the helper's record would pass it.
    const told = runInstrumentFrom('5m', someFacts()) as Record<string, unknown>

    expect(told.tickSize).toBeUndefined()
    expect(told.lotSize).toBeUndefined()
    expect(told.exchange).toBeUndefined()
  })

  it('never states a session without the zone it is read in', () => {
    // THE ONE THAT STOPS A RUN. A session with no zone is refused at load,
    // OS6012, which would turn a missing optional fact into no backtest at all.
    const told = runInstrumentFrom('5m', someFacts({ timezone: undefined }))

    expect(told.session).toBeUndefined()
    expect(told.timezone).toBeUndefined()
    expect(told.interval).toBe('5m')
  })

  it('still states the interval when the facts route did not answer', () => {
    expect(runInstrumentFrom('W', undefined)).toEqual({ interval: '1W' })
  })

  it('hands over a session that is not the helper frozen record', () => {
    // The helper freezes what it caches. The engine is given a copy, so nothing
    // downstream can be refused a write, or make one, on the cached answer.
    const facts = someFacts()
    const told = runInstrumentFrom('5m', facts)

    expect(told.session).not.toBe(facts.session)
    expect(Object.isFrozen(told.session)).toBe(false)
  })
})

describe('one lookup of the instrument', () => {
  it('prices the run on the facts route and does not ask /symbol as well', async () => {
    // THE DOUBLE FETCH. Both routes read the same master contract row, so a run
    // that asked both did the lookup twice for one answer.
    compiles()
    answering([row(0), row(1)])
    ran()
    factsFor.mockResolvedValue(someFacts())

    const out = await runBacktest(aRequest())

    expect(post.mock.calls.map((call) => call[0])).toEqual(['/history'])
    expect(factsFor).toHaveBeenCalledTimes(1)
    expect(factsFor).toHaveBeenCalledWith('AAA', 'XX')
    expect(out.contract).toEqual(
      expect.objectContaining({ tickSize: 0.1, lotSize: 75, usedFallback: false })
    )
    expect(settingsFor).toHaveBeenCalledWith(
      expect.objectContaining({ tickSize: 0.1, lotSize: 75 })
    )
  })

  it('does not ask /symbol for a size the facts route had no value for', async () => {
    // Same row, same lookup: a size the route left out is one /symbol would
    // also have nothing for. The stand-in is recorded so the panel says so.
    compiles()
    answering([row(0)])
    ran()
    factsFor.mockResolvedValue(someFacts({ lotSize: undefined }))

    const out = await runBacktest(aRequest())

    expect(post.mock.calls.map((call) => call[0])).toEqual(['/history'])
    expect(out.contract?.tickSize).toBe(0.1)
    expect(out.contract?.usedFallback).toBe(true)
  })

  it('asks /symbol only when the facts route could not answer at all', async () => {
    compiles()
    answering([row(0)])
    ran()

    const out = await runBacktest(aRequest())

    expect(factsFor).toHaveBeenCalledWith('AAA', 'XX')
    expect(post.mock.calls.map((call) => call[0])).toEqual(['/history', '/symbol'])
    expect(out.contract?.lotSize).toBe(50)
  })

  it('keeps a stated size and stands in only for the missing one', () => {
    const contract = contractFromFacts('AAA', 'XX', someFacts({ tickSize: undefined }))

    expect(contract.lotSize).toBe(75)
    expect(contract.tickSize).toBeGreaterThan(0)
    expect(contract.usedFallback).toBe(true)
  })
})

describe('the facts reach the engine', () => {
  it('passes them as the drive options, not only the contract', async () => {
    // THE DEFECT. The engine was called with the contract and empty options,
    // so it had no interval, no zone and no session: every session fact, every
    // zoned date and every daily read in the strategy was absent on every bar.
    compiles()
    answering([row(0), row(1)])
    ran()
    factsFor.mockResolvedValue(someFacts())

    const out = await runBacktest(aRequest({ interval: 'D' }))

    const options = backtest.mock.calls[0][3] as { instrument?: Record<string, unknown> }
    expect(options.instrument).toEqual({
      interval: '1D',
      timezone: 'Asia/Kolkata',
      session: { start: '09:00', end: '17:00', days: [1, 2, 3] },
      instrumentType: 'future',
      hasVolume: true,
      hasOpenInterest: true,
    })
    expect(out.instrument).toEqual(options.instrument)
  })
})
