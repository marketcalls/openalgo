/**
 * Chart feeds for the strategy builder's two chart tabs.
 *
 * Both wrap the `/strategybuilder/api/` endpoints the page already calls and
 * hand the engine one ordinary bar series. That framing is the whole point of
 * the file, and it is worth saying why, because the obvious alternative does
 * not work.
 *
 * ## Why the numbers have to arrive as bars
 *
 * An indicator reads the chart's **primary price series**: the first
 * price-type series created, which is the one the widget builds from its feed.
 * A host that mounts the chart on a feed returning nothing and then pushes its
 * points onto series it creates afterwards gets a chart that draws correctly,
 * because the time axis is the union of every series' timestamps, and
 * indicators that compute over an empty array. Measured: a 5-period moving
 * average produced 0 finite values that way and 56 of 60 when the same bars
 * arrived through the feed.
 *
 * So the quantity a trader would put a study on is the one that comes back
 * from `getBars`: the combined premium for the strategy chart, the underlying
 * for multi strike OI. Everything else is an overlay the host adds.
 *
 * ## One value per timestamp, so the bars are flat
 *
 * The endpoints return a single number per point, not an open, high, low and
 * close. The bars therefore carry that number in all four fields. A flat bar
 * is an honest representation of a series sampled once per interval, and both
 * tabs open on a line chart type where the distinction does not arise.
 *
 * ## The payload side channel
 *
 * A tab needs more than the primary bars: the overlay points, the entry
 * premium, whether the underlying was available. Rather than fetch twice, the
 * feed publishes the whole response through `onPayload`.
 *
 * That channel needs its own staleness guard. The engine's loading controller
 * discards a response whose request it has already superseded, but it discards
 * it after `getBars` has resolved, and `onPayload` has fired by then. Without
 * the sequence check below, switching the underlying from one instrument to
 * another and having the first request land second would leave the readout
 * quoting the instrument the chart is no longer showing.
 */

import type { Bar, BarsRequest, DataFeed } from 'openalgo-charts'
import {
  type MultiStrikeOIData,
  type StrategyChartData,
  type StrategyChartLegInput,
  strategyChartApi,
} from '@/api/strategy-chart'

/** What the page knows and the endpoints need, minus the timeframe. */
export interface StrategyFeedRequest {
  underlying: string
  exchange: string
  /** Exact quote reference the option-chain backend already resolved. */
  underlyingSymbol?: string
  underlyingExchange?: string
  legs: StrategyChartLegInput[]
}

/**
 * The window the chart asked for, as the IST dates the endpoints take.
 *
 * This is what makes older history page in as the reader scrolls left. The
 * engine asks for successively earlier windows, and a request that could only
 * say "the last N days" would answer every one of them with the same recent
 * slice, so the chart would stop at wherever it first landed.
 *
 * `from` is padded by a day and `to` by a day the other way, because the
 * endpoints work in whole IST dates while the chart works in seconds: a window
 * that opens at 09:20 on a date has to ask for that whole date or the morning
 * is missing. The extra day at each end is trimmed by the engine, which keeps
 * only bars inside the range it asked for.
 *
 * An absent `from` means the chart wants whatever history there is, so nothing
 * is sent and the endpoint's own default lookback applies.
 */
function windowOf(req: BarsRequest): { start_date?: string; end_date?: string } {
  if (req.from === undefined) return {}
  return {
    start_date: istDate(req.from - DAY),
    end_date: req.to === undefined ? undefined : istDate(req.to + DAY),
  }
}

const DAY = 86_400

/** `YYYY-MM-DD` in IST, which is the only form these endpoints accept. */
const IST_YMD = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Kolkata',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

function istDate(utcSeconds: number): string {
  return IST_YMD.format(utcSeconds * 1000)
}

export interface StrategyFeedOptions<TData> {
  /**
   * The current request, read at fetch time rather than captured.
   *
   * This is what keeps the feed's identity stable while the legs and the
   * underlying change underneath it. `OpenAlgoChart`
   * rebuilds its widget whenever the feed prop changes identity, and a rebuild
   * throws away the indicators and drawings the user just placed, so a feed
   * that closed over its parameters would undo the feature this file exists to
   * enable. The host calls `widget.reload()` instead.
   *
   * Returning null means the page has nothing to chart yet.
   */
  read: () => StrategyFeedRequest | null
  /**
   * The full response, or null when there was nothing to fetch.
   *
   * `paging` is true when this answered a scroll into older history rather
   * than a fresh load. The distinction matters because the two mean opposite
   * things to a host: a fresh load replaces what is drawn, while a page carries
   * only the bars before it and has to be merged into it. Replacing on a page
   * shrinks every overlay to the older window while the chart's own series
   * still spans both, and leaves the readout quoting a slice the reader
   * scrolled away from.
   */
  onPayload: (data: TData | null, opts: { paging: boolean }) => void
}

/**
 * Lookback for a request that named no window.
 *
 * Only the very first load is in that position, and the chart asks for one
 * screen of bars right after it, so this covers the gap rather than defining
 * how much history the tab can reach.
 */
const DEFAULT_DAYS = 5

/** A flat bar: one sampled value, carried in all four fields. */
function flatBar(time: number, value: number): Bar {
  return { time, open: value, high: value, low: value, close: value }
}

/**
 * Points to bars, oldest first.
 *
 * Sorted here rather than trusted from the response, because the data layer
 * indexes by time and a reader cannot tell a mis-ordered payload from a
 * mis-drawn chart. Non-finite values are dropped: a missing premium is a gap in
 * the series, and plotting it as zero would draw a spread collapsing to
 * nothing, which is a number someone might act on.
 */
function toBars<T>(points: readonly T[], time: (p: T) => number, value: (p: T) => number): Bar[] {
  const bars: Bar[] = []
  for (const point of points) {
    const v = value(point)
    if (Number.isFinite(v)) bars.push(flatBar(time(point), v))
  }
  return bars.sort((a, b) => a.time - b.time)
}

/**
 * True when this request is the chart reaching further back rather than
 * loading afresh.
 *
 * The engine marks a page by anchoring it with `before`, the exclusive time it
 * already has bars from. Nothing else in a request distinguishes the two, and
 * the window alone cannot: a fresh load of an old range looks the same.
 */
function isPage(req: BarsRequest): boolean {
  return (req as BarsRequest & { before?: number }).before !== undefined
}

/** The shape both endpoints answer with. */
interface Envelope<TData> {
  status: 'success' | 'error'
  message?: string
  data?: TData
}

/**
 * Shared plumbing: sequence the calls, publish the newest payload only, and
 * turn a structured error body into a rejection.
 *
 * The rejection matters. These endpoints answer 4xx with a message the user can
 * act on, such as an empty history window, and the client resolves those rather
 * than throwing so the message survives. Rejecting here is what puts it in
 * front of the user: the engine renders a failed load with a Retry button,
 * where swallowing it would leave the previous chart on screen with no sign
 * that the new request failed.
 */
function strategyFeed<TData>(
  options: StrategyFeedOptions<TData>,
  call: (
    params: StrategyFeedRequest,
    interval: string,
    window: { start_date?: string; end_date?: string }
  ) => Promise<Envelope<TData>>,
  barsOf: (data: TData) => Bar[],
  failureMessage: string
): DataFeed {
  let sequence = 0

  return {
    async getBars(req: BarsRequest): Promise<Bar[]> {
      const paging = isPage(req)
      const mine = ++sequence
      const params = options.read()
      if (!params || params.legs.length === 0) {
        if (mine === sequence) options.onPayload(null, { paging })
        return []
      }

      const res = await call(params, req.interval, windowOf(req))
      // A newer request has started. Its answer is the one the page should be
      // showing, so this one is published nowhere, whether it succeeded or not.
      if (mine !== sequence) return []

      if (res.status !== 'success' || !res.data) {
        // A page that could not be fetched is no news about the range already
        // drawn, so nothing is cleared: the chart keeps every bar it has and
        // the engine shows its own failed-page row with a retry. Clearing here
        // would blank the overlays and the readout under a chart that is still
        // perfectly good.
        if (!paging) options.onPayload(null, { paging })
        throw new Error(res.message || failureMessage)
      }
      options.onPayload(res.data, { paging })
      return barsOf(res.data)
    },
  }
}

/**
 * The strategy chart: combined premium as the bars, so a study added from the
 * indicator picker is a study of the spread rather than of either leg.
 */
export function createStrategyChartFeed(options: StrategyFeedOptions<StrategyChartData>): DataFeed {
  return strategyFeed(
    options,
    (params, interval, window) =>
      strategyChartApi.getStrategyChart({
        underlying: params.underlying,
        exchange: params.exchange,
        underlying_symbol: params.underlyingSymbol,
        underlying_exchange: params.underlyingExchange,
        legs: params.legs,
        interval,
        days: DEFAULT_DAYS,
        ...window,
      }),
    (data) =>
      toBars(
        data.series,
        (p) => p.time,
        (p) => p.combined_premium
      ),
    'The strategy chart could not be loaded.'
  )
}

/**
 * Multi strike OI: the underlying as the bars.
 *
 * Open interest is not in the engine's bar model, and there are as many OI
 * curves as there are legs, so neither is a candidate for the one primary
 * series. The underlying is: it is a real price, it is what every OI reading is
 * interpreted against, and a moving average or an RSI drawn on it means what a
 * reader expects.
 *
 * When the broker returns no intraday candles for the index the primary comes
 * back empty. The chart still draws every OI curve, because the time axis is
 * the union of all series, and the tab already says so in a banner.
 */
export function createMultiStrikeOIFeed(options: StrategyFeedOptions<MultiStrikeOIData>): DataFeed {
  return strategyFeed(
    options,
    (params, interval, window) =>
      strategyChartApi.getMultiStrikeOI({
        underlying: params.underlying,
        exchange: params.exchange,
        underlying_symbol: params.underlyingSymbol,
        underlying_exchange: params.underlyingExchange,
        legs: params.legs,
        interval,
        days: DEFAULT_DAYS,
        ...window,
      }),
    (data) =>
      toBars(
        data.underlying_series,
        (p) => p.time,
        (p) => p.value
      ),
    'Open interest could not be loaded.'
  )
}
