/**
 * Backtesting a saved OpenScript strategy, in the browser, over history.
 *
 * **Why there is no server call here beyond fetching bars.** The engine that
 * runs a compiled program is the package this page already imports to compile
 * one, and it is plain arithmetic over data with no dependency of its own. The
 * browser holds the program (it compiled it) and can fetch the bars (the chart
 * does it constantly), so a backtest is a function call rather than a service.
 * The server side of this platform runs a strategy LIVE, which is a different
 * problem with different reasons: a tab that closes must not stop a position.
 *
 * **What a run costs, measured in a browser on a real strategy.** A supertrend
 * that trades, which is an ordinary thing for somebody to backtest:
 *
 * ```
 *  20,000 bars    335ms in the engine,   402ms end to end
 * 100,000 bars  2,333ms in the engine, 2,549ms end to end
 * ```
 *
 * The gap between the two columns is the message crossing threads, which is a
 * copy of the bars in and a copy of the report back: about a fifth of a second
 * at the ceiling, against the seconds it is buying.
 *
 * **Measure in a browser and on a strategy somebody would actually run.** An
 * earlier set of figures taken in Node on a two-average script read about three
 * times faster and made a hundred thousand bars look like a slow button. It is
 * two and a half seconds. On this page the same thread draws a live chart and a
 * live price, so that is not a slow button: it is the terminal stopping while
 * a trader is watching it.
 *
 * **Which is why the run does not happen here when a worker can take it.** See
 * `runBacktestOffThread`: the engine is a pure function over data with no
 * dependency of its own, so it moves to a worker without changing an answer,
 * and the terminal keeps drawing while a hundred thousand bars are folded. This
 * path stays as the fallback for a browser or a test environment with no worker,
 * where a frozen second is still better than no backtest.
 *
 * Re-measure before moving `MAX_BARS` again, in a browser and on a strategy
 * that trades. The cost is close to linear in the bar count and very much not
 * constant per bar across strategies, so a number interpolated from readings
 * taken elsewhere looks convincing and is wrong by a multiple.
 */

import { apiClient } from '@/api/client'
import { foldBacktest } from './backtestFold'
import { runOnWorker, workersAvailable } from './backtestWorker'
import type {
  BacktestMessage,
  BacktestReply,
  RunInstrument,
  RunStop,
} from './backtestWorkerProtocol'
import { factsFor, type InstrumentFacts } from './instrumentFacts'
import { compileSource, type EditorDiagnostic } from './openscriptFiles'
import { languageInterval } from './openscriptIntervals'

export type { RunInstrument, RunStop } from './backtestWorkerProtocol'

/**
 * The most bars a run may cover before it is refused.
 *
 * A hundred thousand, which at a minute a bar is about a year of an Indian
 * session: the longest range somebody testing an intraday strategy asks for
 * before they are really asking a different question.
 *
 * **It is a ceiling and not a default.** The panel reaches back six months, so
 * an ordinary run is well under half of this and costs a fraction of the time;
 * the ceiling is headroom for a trader who widens the dates deliberately. That
 * separation is the point, because a run now also starts on its own when the
 * instrument or the interval changes, and a default that spent the whole
 * ceiling would put a second of work behind every symbol change.
 *
 * The cost at the ceiling is about two and a half seconds of folding on an
 * ordinary strategy, which is why a run goes to a worker where there is one and
 * why the ceiling is not the default. The measurements are in the module note.
 */
export const MAX_BARS = 100000

/** What the history API answers with, one object per bar. */
interface HistoryRow {
  timestamp: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
  oi?: number
}

/** One bar as the engine reads it. Every field may be absent; a hole is a hole. */
export interface EngineBar {
  time: number | null
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
  oi: number | null
}

/**
 * The instrument facts the money depends on.
 *
 * Read from the platform rather than assumed, because a tick size and a lot
 * size that were guessed produce a report that is wrong in a way nobody can see:
 * the trades are right, the shape of the curve is right, and every figure in
 * money is out by a factor. `usedFallback` says when that happened so the panel
 * can tell the reader rather than quietly showing them a number.
 */
export interface Contract {
  currency: string
  symbol: string
  exchange: string
  tickSize: number
  lotSize: number
  pointValue: number
  digits: number
  usedFallback: boolean
}

const FALLBACK_TICK = 0.05
const FALLBACK_LOT = 1

export interface BacktestRequest {
  file: string
  source: string
  /**
   * Values for the script's own `input()` declarations, for the run only.
   *
   * Only what a trader changed. An input left alone is absent, so the engine
   * resolves the declaration's own default rather than a copy of it made here.
   */
  inputs?: Readonly<Record<string, unknown>>
  symbol: string
  exchange: string
  interval: string
  startDate: string
  endDate: string
  apiKey: string
  signal?: AbortSignal
}

/** What a run produced, or the one thing that stopped it. */
export interface BacktestOutcome {
  ok: boolean
  /** A failure that is not about the script: no bars, no network, too many bars. */
  problem?: string
  /** The script's own diagnostics, when it is the script that is wrong. */
  diagnostics?: EditorDiagnostic[]
  summary?: Record<string, unknown>
  trades?: readonly Record<string, unknown>[]
  equity?: readonly Record<string, unknown>[]
  markers?: readonly Record<string, unknown>[]
  barCount?: number
  /** How long the engine itself took, which is what the ceiling is about. */
  ranMs?: number
  contract?: Contract
  /** What the engine was told about the instrument beside the contract. */
  instrument?: RunInstrument
  /**
   * The diagnostic that stopped the run on a bar, when one did.
   *
   * The figures still describe the run up to that bar, which is a report of
   * part of the range. Without this beside them they read as the whole of it.
   */
  stopped?: RunStop
  /**
   * The compiled program this run was of.
   *
   * Handed back so the panel can show what the script declares and what it
   * takes as inputs without compiling it a second time.
   */
  program?: unknown
}

function refused(problem: string): BacktestOutcome {
  return { ok: false, problem }
}

/** The stated stand-ins, marked as stand-ins. */
function fallbackContract(symbol: string, exchange: string): Contract {
  return {
    currency: 'INR',
    symbol,
    exchange,
    tickSize: FALLBACK_TICK,
    lotSize: FALLBACK_LOT,
    pointValue: 1,
    digits: 2,
    usedFallback: true,
  }
}

/**
 * The instrument's own facts, or sensible stand-ins with that fact recorded.
 *
 * A failure here is not a failure of the run. An instrument the platform has no
 * row for is still one a trader may want to test against, so the run goes ahead
 * on stated defaults and the panel says which.
 *
 * `runBacktest` asks this only when the instrument facts route could not answer
 * at all. Both read the same master contract row, so asking here as well when
 * that route did answer would be the same lookup made twice.
 */
export async function contractFor(
  symbol: string,
  exchange: string,
  apiKey: string,
  signal?: AbortSignal
): Promise<Contract> {
  const fallback = fallbackContract(symbol, exchange)

  try {
    const res = await apiClient.post<{
      status: string
      data?: { lotsize?: number; tick_size?: number }
    }>('/symbol', { apikey: apiKey, symbol, exchange }, { signal })

    if (res.data?.status !== 'success' || !res.data.data) return fallback

    const tick = Number(res.data.data.tick_size)
    const lot = Number(res.data.data.lotsize)
    if (!Number.isFinite(tick) || tick <= 0) return fallback
    if (!Number.isFinite(lot) || lot <= 0) return fallback

    return { ...fallback, tickSize: tick, lotSize: lot, usedFallback: false }
  } catch {
    return fallback
  }
}

/**
 * The contract, from the instrument facts the run has already fetched.
 *
 * The facts route reads the master contract row through the same lookup as
 * `/symbol`, so a fact it left out is one that lookup has no usable value for,
 * and asking `/symbol` again would get the same nothing. A size it did state is
 * kept and only the missing one stands in, with the stand-in recorded.
 */
export function contractFromFacts(
  symbol: string,
  exchange: string,
  facts: InstrumentFacts
): Contract {
  const fallback = fallbackContract(symbol, exchange)
  const tick = facts.tickSize
  const lot = facts.lotSize
  return {
    ...fallback,
    tickSize: tick ?? fallback.tickSize,
    lotSize: lot ?? fallback.lotSize,
    usedFallback: tick === undefined || lot === undefined,
  }
}

/**
 * The chart's interval as the engine spells it, or nothing it could read.
 *
 * The two spell a day differently. This platform's intervals, and the chart's,
 * write a day, a week and a month as a bare `D`, `W` and `M`, while the engine
 * reads `stdlib.md` 15.2's count and unit, `1D`, `1W`, `1M`, and has no
 * spelling for a bare letter. Minutes and hours are already written the
 * engine's way. Seconds are not: `host-interface.md` 4.1 takes an interval in
 * 15.2's grammar, which has no unit finer than a minute and against which the
 * engine checks every `req.timeframe` read, so a seconds chart states no
 * interval rather than one outside it, and its interval facts are absent
 * rather than half read.
 *
 * The spelling itself is `languageInterval`'s, the same one the settings
 * dialog stores an interval input in, so a chart and a setting can never
 * disagree about what `D` means.
 */
export function engineInterval(interval: string): string | undefined {
  return languageInterval(interval) ?? undefined
}

/**
 * What the engine is told about the instrument beside the contract.
 *
 * **The interval comes from the chart and the rest from the platform.** The
 * zone and the session are the market calendar's, which an admin can edit, and
 * none of them is written here: an exchange the calendar does not hold states
 * no session, which the engine reads as absent, and that is the honest answer.
 *
 * **The regular session, never today's.** A backtest is history, and the
 * engine holds one window for the whole run, so a special day's window would
 * put every other day of the range outside the session.
 *
 * **A session never goes without its zone.** A session is wall clock, and the
 * engine refuses one with no zone to read it in at load (OS6012), which would
 * stop the whole run over a fact meant to be optional.
 */
export function runInstrumentFrom(
  interval: string,
  facts: InstrumentFacts | undefined
): RunInstrument {
  const code = engineInterval(interval)
  const zone = facts?.timezone
  const session = zone ? facts?.session : undefined
  return {
    ...(code === undefined ? {} : { interval: code }),
    ...(zone ? { timezone: zone } : {}),
    // Copied as plain data, because this crosses to a worker and the helper's
    // own records are frozen.
    ...(session === undefined
      ? {}
      : {
          session: {
            start: session.start,
            end: session.end,
            ...(session.days === undefined ? {} : { days: [...session.days] }),
          },
        }),
    ...(facts?.instrumentType === undefined ? {} : { instrumentType: facts.instrumentType }),
    ...(facts?.hasVolume === undefined ? {} : { hasVolume: facts.hasVolume }),
    ...(facts?.hasOpenInterest === undefined ? {} : { hasOpenInterest: facts.hasOpenInterest }),
  }
}

/**
 * History, as the engine reads it.
 *
 * The one conversion that matters is the clock. This platform's history API
 * counts seconds and the engine counts milliseconds, so a run handed the
 * platform's own numbers would place every bar in January 1970 and report a
 * window that excluded all of them.
 */
export function barsFromHistory(rows: readonly HistoryRow[]): EngineBar[] {
  return rows.map((row) => ({
    time: Number.isFinite(row.timestamp) ? row.timestamp * 1000 : null,
    open: Number.isFinite(row.open) ? row.open : null,
    high: Number.isFinite(row.high) ? row.high : null,
    low: Number.isFinite(row.low) ? row.low : null,
    close: Number.isFinite(row.close) ? row.close : null,
    volume: Number.isFinite(row.volume) ? (row.volume as number) : null,
    oi: Number.isFinite(row.oi) ? (row.oi as number) : null,
  }))
}

/**
 * One backtest, from a saved script and a date range.
 *
 * The order is deliberate: compile first, because a script that does not
 * compile should say so before a trader waits for history, and because the
 * program is what the run is of. Then the bars, then the instrument, then the
 * engine.
 *
 * **The instrument is one lookup.** The facts route answers the contract, the
 * zone, the session and the rest together, and it is asked while the history
 * is being fetched, since neither waits on the other. `/symbol` is asked only
 * when that route could not answer at all, so that the money is still priced
 * on the stored tick and lot size when the session facts are what is missing.
 */
export async function runBacktest(request: BacktestRequest): Promise<BacktestOutcome> {
  const compiled = await compileSource(request.file, request.source)
  if (compiled.problem) return refused(compiled.problem)
  if (!compiled.ok || !compiled.program) {
    return { ok: false, diagnostics: compiled.diagnostics }
  }
  if (compiled.kind !== 'strategy') {
    return refused(
      'This script is a study. Only a strategy places orders, so only a strategy has a backtest.'
    )
  }

  // Never rejects: a failure is an absence, which the lines below handle.
  const factsPending = factsFor(request.symbol, request.exchange)

  let rows: HistoryRow[]
  try {
    const res = await apiClient.post<{ status: string; data?: HistoryRow[]; message?: string }>(
      '/history',
      {
        apikey: request.apiKey,
        symbol: request.symbol,
        exchange: request.exchange,
        interval: request.interval,
        start_date: request.startDate,
        end_date: request.endDate,
      },
      { signal: request.signal }
    )
    if (res.data?.status !== 'success') {
      return refused(res.data?.message || 'History could not be read for this instrument.')
    }
    rows = res.data.data ?? []
  } catch {
    return refused('History could not be reached.')
  }

  if (rows.length === 0) {
    return refused('No bars came back for that instrument over that range.')
  }
  if (rows.length > MAX_BARS) {
    return refused(
      `That range is ${rows.length.toLocaleString()} bars and this runs up to ` +
        `${MAX_BARS.toLocaleString()}. Shorten the range or use a larger interval.`
    )
  }

  const bars = barsFromHistory(rows)
  const facts = await factsPending
  const contract = facts
    ? contractFromFacts(request.symbol, request.exchange, facts)
    : await contractFor(request.symbol, request.exchange, request.apiKey, request.signal)
  const instrument = runInstrumentFrom(request.interval, facts)

  let program: unknown
  try {
    program = JSON.parse(compiled.program)
  } catch {
    return refused('The compiled strategy could not be read back.')
  }

  const priced = {
    currency: contract.currency,
    symbol: contract.symbol,
    exchange: contract.exchange,
    tickSize: contract.tickSize,
    lotSize: contract.lotSize,
    pointValue: contract.pointValue,
    digits: contract.digits,
  }
  const inputs = (request.inputs ?? {}) as Record<string, unknown>

  const folded = await fold({ program, bars, contract: priced, inputs, instrument }, request.signal)
  if (folded === null) return refused('This run was stopped.')

  // A run can be refused before its first bar: a cost model stated twice, a
  // quantity in a unit a backtest cannot size, a schedule it cannot evaluate.
  // That is a diagnostic about the run rather than about the script's text, so
  // it is reported as a problem with its code, not as a line to underline.
  if (!folded.ok) {
    return refused(folded.code ? `${folded.code}: ${folded.message}` : folded.message)
  }

  return {
    ok: true,
    summary: folded.report.summary,
    trades: folded.report.trades as Record<string, unknown>[],
    equity: folded.report.equity as Record<string, unknown>[],
    markers: folded.report.markers as Record<string, unknown>[],
    barCount: bars.length,
    ranMs: folded.ranMs,
    contract,
    instrument,
    ...(folded.stopped ? { stopped: folded.stopped } : {}),
    program,
  }
}

/**
 * Run the engine, on a worker where there is one and on this thread otherwise.
 *
 * **The fallback is not a lesser answer, only a slower page.** The engine is a
 * pure function over data, so both paths compute the same report from the same
 * inputs; what differs is whether the chart keeps drawing while it happens. So
 * a browser that will not start a worker, a policy that refuses the file, a
 * test environment that has none, all still get a backtest.
 *
 * **A worker that fails to start is retried inline; a run it refuses is not.**
 * Those are different things and conflating them is the mistake worth naming: a
 * refusal is the engine's answer and would be the same answer inline, so
 * running it again would cost a second full fold to be told what we already
 * know. Only a worker that never got to run is worth repeating.
 *
 * Answers `null` for a run that was abandoned, which is a run nobody is waiting
 * for rather than a run that failed.
 */
async function fold(
  message: BacktestMessage,
  signal?: AbortSignal
): Promise<BacktestReply | null> {
  if (workersAvailable()) {
    try {
      return await runOnWorker(message, signal)
    } catch (stopped) {
      if (signal?.aborted) return null
      // Logged rather than shown. The trader asked for a backtest, not for a
      // report on how it was scheduled, and the run below answers them.
      console.warn('The backtest worker could not be used; running on this thread.', stopped)
    }
  }

  if (signal?.aborted) return null
  // The same function the worker calls, so this thread states exactly what a
  // worker would have. It freezes the page for as long as it takes; see the
  // module note for what that cost is at each size.
  return foldBacktest(message)
}
