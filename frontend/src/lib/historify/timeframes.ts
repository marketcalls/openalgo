/** Stored-data aggregation with SDK bucket boundaries and confirmed study history. */
import {
  type Bar,
  type BarsRequest,
  type DataFeed,
  intervalParts,
  resolveInterval,
  sharedHistoryRequests,
  type TimeframeFeed,
  timeframeBucketAt,
} from 'openalgo-charts'
import { createTimeframeProvider } from 'openalgo-charts/indicators'
import { createTradingTimeframes, type TradingTimeframeOptions } from '@/lib/trading/timeframeFeed'
import { type CatalogSymbol, findCatalogSymbol } from './catalog'

interface Options
  extends Pick<TradingTimeframeOptions, 'calendar' | 'calendarRevision' | 'prepare' | 'now'> {
  symbols: readonly CatalogSymbol[]
}
const DAY = 86400,
  IST = 19800
function duration(interval: string): number {
  const rule = resolveInterval(interval).bucketing
  return rule.mode === 'interval'
    ? rule.seconds
    : rule.mode === 'calendar'
      ? (rule.count ?? 1) * { month: 31, quarter: 93, year: 366 }[rule.unit] * DAY
      : DAY
}

export function createHistorifyTimeframes(raw: DataFeed, options: Options) {
  const native = createTradingTimeframes(raw, {
    ...options,
    providerId: 'historify',
    nativeIntervals: (request) => [
      ...(findCatalogSymbol(options.symbols, request.symbol, request.exchange)?.sources ?? []),
    ],
  })
  const pool = sharedHistoryRequests(raw)
  const now = options.now ?? (() => Date.now() / 1000)
  const controllers = new Set<AbortController>()
  let closed = false
  const getBars = async (request: BarsRequest): Promise<Bar[]> => {
    if (closed) throw new Error('Local chart data has closed')
    const controller = new AbortController(),
      abort = () => controller.abort()
    controllers.add(controller)
    request.signal?.addEventListener('abort', abort, { once: true })
    if (request.signal?.aborted) abort()
    const timeout = setTimeout(() => controller.abort(), 30_000)
    try {
      return await (async (signal: AbortSignal) => {
        const req = { ...request, signal }
        await options.prepare?.(req)
        if (signal.aborted) throw signal.reason
        const plan = native.feed.resolve(req)
        if (plan.native) return pool.getBars({ ...req, interval: plan.source.interval })
        if (req.from === undefined || req.to === undefined || req.to <= req.from) return []
        const calendar = plan.market.calendar
        if (calendar.timezone !== 'Asia/Kolkata') return native.feed.getBars(req)
        const next = calendar.sessionFrom(req.from)
        const first =
          timeframeBucketAt(plan, req.from) ?? (next && timeframeBucketAt(plan, next.open))
        const last = timeframeBucketAt(plan, req.to - 1)
        const from = first?.from ?? req.from,
          to = last?.to ?? req.to
        const part = intervalParts(req.interval)!
        if (['s', 'm', 'h'].includes(part.unit)) {
          // Regular sessions stay in DuckDB. Special/overnight openings need
          // the calendar-aware SDK path instead of the server's one daily offset.
          const special = Object.entries(calendar.calendar.exceptions ?? {}).some(
            ([date, windows]) =>
              windows.length &&
              Date.parse(date) / 1000 >= from - DAY &&
              Date.parse(date) / 1000 < to + DAY
          )
          const overnight = calendar.calendar.sessions.some(
            (window) => window.slice(0, 4) >= window.slice(5, 9)
          )
          if (special || overnight) return native.feed.getBars(req)
        }
        const code = `${part.multiplier === 1 && /^[DWM]$/.test(part.unit) ? '' : part.multiplier}${part.unit}`
        const bars = await pool.getBars({ ...req, interval: code, from, to })
        // Historify's aggregated calendar labels encode IST wall dates as UTC.
        // Keep its public wire convention; normalize only the chart adapter.
        const calendarPeriod = ['D', 'W', 'M'].includes(part.unit)
        return bars
          .map((bar) => ({ ...bar, time: bar.time - (calendarPeriod ? IST : 0) }))
          .filter((bar) => bar.time >= from && bar.time < to)
      })(controller.signal)
    } finally {
      clearTimeout(timeout)
      controllers.delete(controller)
      request.signal?.removeEventListener('abort', abort)
    }
  }
  const feed: TimeframeFeed = {
    resolve: (req) => native.feed.resolve(req),
    getBars,
    async getBarsPage(req) {
      const plan = native.feed.resolve({ ...req, from: undefined })
      const symbol = findCatalogSymbol(options.symbols, req.symbol, req.exchange)
      const source = plan.source.interval as '1m' | 'D'
      const earliest = symbol?.firstBySource?.[source] ?? Date.UTC(1970, 0, 5) / 1000
      const from = Math.max(
        earliest,
        req.from ?? req.before - duration(req.interval) * req.countBack * 2
      )
      if (from >= req.before) return { bars: [], nextBefore: from, hasMore: false }
      const bars = (await getBars({ ...req, from, to: req.before }))
        .filter((bar) => bar.time < req.before)
        .slice(-req.countBack)
      const nextBefore = bars[0]?.time ?? from
      return { bars, nextBefore, ...(nextBefore <= earliest ? { hasMore: false } : {}) }
    },
    destroy() {
      closed = true
      for (const controller of controllers) controller.abort()
      native.destroy()
    },
  }
  const provider = createTimeframeProvider(feed, {
    now,
    availability(bar, request) {
      const req = { ...request, exchange: request.exchange ?? '' }
      const plan = feed.resolve(req)
      const bucket = timeframeBucketAt(plan, bar.time)
      const symbol = findCatalogSymbol(options.symbols, req.symbol, req.exchange)
      const last = symbol?.lastBySource[plan.source.interval as '1m' | 'D']
      const horizon = last === undefined ? null : plan.source.bounds(last)?.to
      // An old partial download does not become a complete month as time passes.
      // A full final trading session is sufficient across weekends/holidays.
      const next = horizon == null ? null : plan.market.calendar.sessionFrom(horizon)
      const covered =
        bucket !== null &&
        horizon != null &&
        (horizon >= bucket.to || (next !== null && next.open >= bucket.to))
      return { at: bucket?.to ?? null, confirmed: covered && bucket!.to <= now() }
    },
  })
  return { feed, provider, supports: native.supports, destroy: () => feed.destroy() }
}
