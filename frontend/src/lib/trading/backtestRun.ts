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
 * **Why it runs on the UI thread, measured rather than assumed.** The engine
 * costs about 30ms over a thousand bars, 68ms over five thousand and 211ms over
 * twenty thousand, which is under a click's worth of delay. It reaches 1.3
 * seconds at a hundred thousand bars, which is why `MAX_BARS` is where it is: a
 * run past it is refused with the count rather than freezing the workspace. A
 * worker is the way past that ceiling, and it has to be a served file rather
 * than a blob because this application's content security policy allows scripts
 * from its own origin and nothing else.
 */

import { apiClient } from '@/api/client'
import { compileSource, type EditorDiagnostic } from './openscriptFiles'

/**
 * The most bars a run may cover before it is refused.
 *
 * Twenty thousand costs about a fifth of a second, which a trader reads as the
 * button working. A hundred thousand costs over a second with the workspace
 * frozen through it, which they read as the page having broken.
 */
export const MAX_BARS = 20000

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
}

function refused(problem: string): BacktestOutcome {
  return { ok: false, problem }
}

/**
 * The instrument's own facts, or sensible stand-ins with that fact recorded.
 *
 * A failure here is not a failure of the run. An instrument the platform has no
 * row for is still one a trader may want to test against, so the run goes ahead
 * on stated defaults and the panel says which.
 */
export async function contractFor(
  symbol: string,
  exchange: string,
  apiKey: string,
  signal?: AbortSignal
): Promise<Contract> {
  const fallback: Contract = {
    currency: 'INR',
    symbol,
    exchange,
    tickSize: FALLBACK_TICK,
    lotSize: FALLBACK_LOT,
    pointValue: 1,
    digits: 2,
    usedFallback: true,
  }

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
  const contract = await contractFor(request.symbol, request.exchange, request.apiKey, request.signal)

  try {
    const engine = await import('openalgo-script')
    const settings = engine.settingsFor({
      currency: contract.currency,
      symbol: contract.symbol,
      exchange: contract.exchange,
      tickSize: contract.tickSize,
      lotSize: contract.lotSize,
      pointValue: contract.pointValue,
      digits: contract.digits,
    })

    const started = performance.now()
    const out = engine.backtest(JSON.parse(compiled.program), bars, settings, {})
    const ranMs = performance.now() - started

    // A run can be refused before its first bar: a cost model stated twice, a
    // quantity in a unit a backtest cannot size, a schedule it cannot evaluate.
    // That is a diagnostic about the run rather than about the script's text, so
    // it is reported as a problem with its code, not as a line to underline.
    if (!out.ok) {
      const refusal = out.diagnostic
      return refused(`${refusal.code}: ${refusal.message}`)
    }

    const report = out.record.report
    return {
      ok: true,
      summary: report.summary as unknown as Record<string, unknown>,
      trades: report.trades as unknown as Record<string, unknown>[],
      equity: report.equity as unknown as Record<string, unknown>[],
      markers: report.markers as unknown as Record<string, unknown>[],
      barCount: bars.length,
      ranMs,
      contract,
    }
  } catch (unreachable) {
    return refused(
      unreachable instanceof Error ? unreachable.message : 'The engine could not run this program.'
    )
  }
}
