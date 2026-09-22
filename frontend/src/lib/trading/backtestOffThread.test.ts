/**
 * Which thread a run happens on, and what happens when that choice fails.
 *
 * The engine answers the same thing either way, so none of this is about
 * results. It is about the two ways the choice can be wrong: a run that is done
 * twice because a refusal was mistaken for a worker that would not start, and a
 * run that never happens because a worker that would not start was mistaken for
 * a refusal.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const post = vi.fn()
vi.mock('@/api/client', () => ({ apiClient: { post: (...args: unknown[]) => post(...args) } }))

const compileSource = vi.fn()
vi.mock('./openscriptFiles', () => ({
  compileSource: (...args: unknown[]) => compileSource(...args),
}))

const backtest = vi.fn()
const settingsFor = vi.fn((contract: unknown) => ({ contract, inputs: {} }))
vi.mock('openalgo-script', () => ({
  backtest: (...args: unknown[]) => backtest(...args),
  settingsFor: (...args: unknown[]) => settingsFor(...args),
}))

const runOnWorker = vi.fn()
const workersAvailable = vi.fn(() => true)
vi.mock('./backtestWorker', () => ({
  runOnWorker: (...args: unknown[]) => runOnWorker(...args),
  workersAvailable: () => workersAvailable(),
}))

const { runBacktest } = await import('./backtestRun')

function row(at: number) {
  return {
    timestamp: 1_700_000_000 + at * 60,
    open: 100,
    high: 101,
    low: 99,
    close: 100,
    volume: 5,
  }
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

/** A report the engine or the worker could have answered. */
function aReport(netProfit = 10) {
  return { summary: { netProfit }, trades: [], equity: [], markers: [] }
}

beforeEach(() => {
  vi.clearAllMocks()
  workersAvailable.mockReturnValue(true)
  compileSource.mockResolvedValue({
    ok: true,
    kind: 'strategy',
    program: '{"openscript":{}}',
    diagnostics: [],
  })
  post.mockImplementation(async (url: string) => {
    if (url === '/history') return { data: { status: 'success', data: [row(0), row(1)] } }
    if (url === '/symbol') {
      return { data: { status: 'success', data: { lotsize: 1, tick_size: 0.05 } } }
    }
    return { data: { status: 'error' } }
  })
})

describe('choosing the thread', () => {
  it('runs on the worker when there is one, and not on the page as well', async () => {
    // Catches the worker being started and its answer thrown away, which shows
    // up as a backtest that is right and twice as slow as before.
    runOnWorker.mockResolvedValue({ ok: true, ranMs: 12, report: aReport(123) })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(true)
    expect(out.summary?.netProfit).toBe(123)
    expect(runOnWorker).toHaveBeenCalledTimes(1)
    expect(backtest).not.toHaveBeenCalled()
  })

  it('runs on the page where the environment has no worker', async () => {
    // A browser without them, or a test environment. The answer is the same and
    // only the page is slower, so a backtest must still happen.
    workersAvailable.mockReturnValue(false)
    backtest.mockReturnValue({ ok: true, record: { report: aReport(7) } })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(true)
    expect(out.summary?.netProfit).toBe(7)
    expect(runOnWorker).not.toHaveBeenCalled()
    expect(backtest).toHaveBeenCalledTimes(1)
  })

  it('falls back to the page when the worker will not start', async () => {
    // THE ONE THAT KEEPS THE FEATURE WORKING. A policy that refuses the file,
    // a browser that will not build it. Reporting this to the trader as a
    // failed backtest would mean the panel stopped working over how the run was
    // scheduled, which is not a thing they can act on.
    runOnWorker.mockRejectedValue(new Error('refused by policy'))
    backtest.mockReturnValue({ ok: true, record: { report: aReport(5) } })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(true)
    expect(out.summary?.netProfit).toBe(5)
    expect(backtest).toHaveBeenCalledTimes(1)
  })
})

describe('a refusal is an answer, not a failure to start', () => {
  it('reports what the worker refused rather than running it again', async () => {
    // THE ONE THAT MATTERS MOST. A run refused before its first bar is the
    // engine's answer and would be the same answer on the page. Treating it as
    // a worker that did not start costs a second full fold, of up to a hundred
    // thousand bars, to be told exactly what we already knew.
    runOnWorker.mockResolvedValue({
      ok: false,
      code: 'OS6023',
      message: 'two cost models at once',
    })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toContain('OS6023')
    expect(backtest).not.toHaveBeenCalled()
  })

  it('reports a refusal from the page path the same way', async () => {
    workersAvailable.mockReturnValue(false)
    backtest.mockReturnValue({
      ok: false,
      diagnostic: { code: 'OS6023', message: 'two cost models at once' },
    })

    const out = await runBacktest(aRequest())

    expect(out.ok).toBe(false)
    expect(out.problem).toContain('OS6023')
  })
})

describe('a run nobody is waiting for', () => {
  it('does not start a second one on the page when it was abandoned', async () => {
    // Catches an abort read as a worker that failed. The run was abandoned
    // because the trader changed instrument, and folding it again on the page
    // is work for an answer that will be discarded, with the freeze that entails.
    const controller = new AbortController()
    runOnWorker.mockImplementation(async () => {
      controller.abort()
      throw new Error('aborted')
    })

    const out = await runBacktest(aRequest({ signal: controller.signal }))

    expect(out.ok).toBe(false)
    expect(backtest).not.toHaveBeenCalled()
  })
})

describe('what is handed across', () => {
  it('sends the parsed program, the converted bars and the instrument facts', async () => {
    // The worker decides nothing, so everything it needs has to be in the
    // message. A field left out is a run that silently differs from the one the
    // page would have done.
    runOnWorker.mockResolvedValue({ ok: true, ranMs: 1, report: aReport() })

    await runBacktest(aRequest({ inputs: { len: 20 } }))

    const sent = runOnWorker.mock.calls[0][0] as {
      program: unknown
      bars: { time: number }[]
      contract: { lotSize: number; tickSize: number }
      inputs: Record<string, unknown>
    }

    expect(sent.program).toEqual({ openscript: {} })
    // Seconds from the history API, milliseconds for the engine.
    expect(sent.bars[0].time).toBe(1_700_000_000_000)
    expect(sent.contract.lotSize).toBe(1)
    expect(sent.contract.tickSize).toBe(0.05)
    expect(sent.inputs).toEqual({ len: 20 })
  })

  it('sends nothing that could not survive being copied to another thread', async () => {
    // A message is structured cloned, which carries plain data and refuses a
    // function or a class instance. Catching it here is cheaper than catching
    // it as a worker that will not accept the message and a run that silently
    // happens on the page every time.
    runOnWorker.mockResolvedValue({ ok: true, ranMs: 1, report: aReport() })

    await runBacktest(aRequest())

    const sent = runOnWorker.mock.calls[0][0]
    expect(() => structuredClone(sent)).not.toThrow()
  })

  it('carries the time the engine took, whichever thread took it', async () => {
    runOnWorker.mockResolvedValue({ ok: true, ranMs: 421, report: aReport() })

    expect((await runBacktest(aRequest())).ranMs).toBe(421)
  })
})
