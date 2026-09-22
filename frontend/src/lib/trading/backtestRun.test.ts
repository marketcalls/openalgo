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
  settingsFor: (...args: unknown[]) => settingsFor(...args),
}))

const { barsFromHistory, contractFor, MAX_BARS, runBacktest } = await import('./backtestRun')

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
