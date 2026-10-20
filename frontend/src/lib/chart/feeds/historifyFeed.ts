/**
 * A chart data feed over Historify's locally downloaded DuckDB store.
 *
 * This is the read-only half of the chart contract and nothing more. It
 * implements `getBars` and deliberately implements neither `subscribeBars` nor
 * `subscribeDepth`, both of which are optional on `DataFeed`. That is what
 * makes a chart built on this feed incapable of live updates: there is no
 * switch to leave on by accident, because there is no subscription to make.
 *
 * It also omits `getBarsPage`. The store has no epoch cursor, only `start_date`
 * and `end_date`, so `DataLoadingController` is left to page by date window
 * through its `pageWindowSec` fallback, which is exactly the shape this route
 * serves.
 *
 * Two things about the wire need correcting here rather than in every caller:
 *
 * - **Numbers arrive as floats on computed intervals.** `1m` and `D` are read
 *   straight from the table and come back as integers, but every aggregated
 *   interval is built with a DuckDB `FLOOR()` that yields a DOUBLE, so the same
 *   field is `1718000100` on one interval and `1718000100.0` on another, and
 *   volume with it.
 * - **The server's date window is computed in its own local timezone**, using a
 *   naive `strptime(...).timestamp()`. On a host that is not IST this shifts the
 *   window by a few hours against the bars it is selecting, which can clip the
 *   first or last candle of a request. The window is padded by a day at each end
 *   so the slop cannot lose a bar; the chart de-duplicates by time, so the
 *   overlap costs nothing.
 */

import type { Bar, BarsRequest, DataFeed } from 'openalgo-charts'
import { type ChartDataRequest, type HistorifyCandle, historifyApi } from '@/api/historify'

/** A day of padding, in seconds, against server-local window arithmetic. */
const WINDOW_PAD_SEC = 86_400

/**
 * The earliest date the store can be asked about, as UTC seconds.
 *
 * `services/historify_service.get_chart_data` converts a date with a naive
 * `datetime.strptime(...).timestamp()`, and on Windows that raises
 * `OSError: [Errno 22] Invalid argument` for anything the local zone puts
 * before the epoch. In IST that is every date up to and including 1970-01-02,
 * which surfaced as `Could not load NIFTY 1m: [Errno 22] Invalid argument`
 * painted across a working chart.
 *
 * No stored candle predates this, so clamping costs nothing and keeps a window
 * that drifts toward zero from reaching the server as a crash.
 */
const EARLIEST_QUERY_SEC = Date.UTC(1970, 0, 5) / 1000

/** Epoch seconds to the `YYYY-MM-DD` the route expects, always read as UTC. */
export function toDateString(utcSeconds: number): string {
  return new Date(utcSeconds * 1000).toISOString().slice(0, 10)
}

/**
 * The padded date window for a bar request.
 *
 * Exported for its test: the padding is the part that is easy to remove by
 * accident and impossible to notice, because losing one edge candle looks like
 * the download simply stopped there.
 */
export function dateWindow(from?: number, to?: number): { startDate?: string; endDate?: string } {
  const floor = (seconds: number) => Math.max(seconds, EARLIEST_QUERY_SEC)
  return {
    ...(Number.isFinite(from)
      ? { startDate: toDateString(floor((from as number) - WINDOW_PAD_SEC)) }
      : {}),
    ...(Number.isFinite(to)
      ? { endDate: toDateString(floor((to as number) + WINDOW_PAD_SEC)) }
      : {}),
  }
}

/**
 * One wire row to one bar, or null if it cannot be trusted.
 *
 * A row missing a finite time or close is dropped rather than drawn: a NaN
 * reaches the renderer as a gap in some places and as a broken autoscale in
 * others, and neither says what went wrong.
 */
export function toBar(row: HistorifyCandle): Bar | null {
  const time = Math.round(Number(row?.timestamp))
  const close = Number(row?.close)
  if (!Number.isFinite(time) || !Number.isFinite(close)) return null

  const open = Number(row.open)
  const high = Number(row.high)
  const low = Number(row.low)
  const volume = Number(row.volume)

  return {
    time,
    open: Number.isFinite(open) ? open : close,
    high: Number.isFinite(high) ? high : close,
    low: Number.isFinite(low) ? low : close,
    close,
    // Rounded because an aggregated interval returns it as a float, and a
    // volume histogram reading 12500.000000001 is not a quantity anyone traded.
    ...(Number.isFinite(volume) ? { volume: Math.round(volume) } : {}),
  }
}

/** Wire rows to bars, dropped where unusable and sorted oldest first. */
export function toBars(rows: readonly HistorifyCandle[]): Bar[] {
  const bars: Bar[] = []
  for (const row of rows) {
    const bar = toBar(row)
    if (bar) bars.push(bar)
  }
  bars.sort((a, b) => a.time - b.time)
  return bars
}

export interface HistorifyFeedOptions {
  /** Injectable for tests; defaults to the real API module. */
  fetchCandles?: (req: ChartDataRequest) => Promise<HistorifyCandle[]>
}

export function createHistorifyFeed(options: HistorifyFeedOptions = {}): DataFeed {
  const fetchCandles = options.fetchCandles ?? historifyApi.chartData

  return {
    async getBars(req: BarsRequest): Promise<Bar[]> {
      if (!req.symbol || !req.exchange) return []

      let rows: HistorifyCandle[]
      try {
        rows = await fetchCandles({
          symbol: req.symbol,
          exchange: req.exchange,
          interval: req.interval,
          ...dateWindow(req.from, req.to),
          signal: req.signal,
        })
      } catch (error) {
        // An aborted request is the chart cancelling its own work, not a
        // failure, and must propagate untouched or it is reported as one.
        if (error instanceof Error && error.name === 'AbortError') throw error
        // Everything else reaches the user: the engine prints a failed load
        // onto the chart's own status line, so whatever is thrown here is read
        // by a trader. The server answers these routes with a rendered Python
        // exception, which is how "[Errno 22] Invalid argument" came to be
        // written across a price chart.
        throw new Error(
          `${req.symbol} could not be read from your local data. Re-download it from Historify if this keeps happening.`
        )
      }

      // An empty window is a normal answer here. A symbol is downloaded for a
      // date range, so paging past its start is how the chart discovers where
      // the data begins, not an error to report.
      return toBars(rows)
    },
  }
}
