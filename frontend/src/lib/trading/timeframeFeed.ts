/** Broker capabilities and exchange sessions for shared SDK resampling and study history. */
import {
  type BarsRequest,
  SessionCalendar as Calendar,
  type DataFeed,
  planTimeframe,
  resolveInterval,
  type SessionCalendar,
  type TimeframeBucket,
  type TimeframeFeed,
  type TimeframeMarket,
  type TimeframePlan,
  timeframeBucketAt,
  utcSecondsToZonedParts,
  withTimeframes,
  zonedWallClockToUtcSeconds,
} from 'openalgo-charts'
import { createTimeframeProvider, type TimeframeProviderOptions } from 'openalgo-charts/indicators'
import { ensureInterval } from '@/lib/chart/intervalRegistry'

export interface TradingTimeframeOptions {
  providerId: string
  nativeIntervals: readonly string[] | ((request: BarsRequest) => readonly string[])
  calendar(request: BarsRequest): SessionCalendar | null
  calendarRevision(): string
  /** Fetch the calendar years needed by a finite history window. */
  prepare?(request: BarsRequest): Promise<void>
  now?: () => number
  historicalSnapshot?: TimeframeProviderOptions['historicalSnapshot']
}

const DAY = 86400
const unknownCalendar = new Calendar({ timezone: 'Asia/Kolkata', sessions: ['0000-0000'] })

function sourceBounds(
  calendar: SessionCalendar | null,
  interval: string,
  time: number
): TimeframeBucket | null {
  if (!calendar) return null
  const rule = resolveInterval(interval).bucketing
  if (rule.mode === 'interval' && rule.seconds === DAY) {
    const day = utcSecondsToZonedParts(time, calendar.timezone)
    const from = zonedWallClockToUtcSeconds(
      day.year,
      day.month,
      day.day,
      0,
      0,
      0,
      calendar.timezone
    )
    const session = calendar.sessionFrom(from)
    if (!session || session.open >= from + DAY) return null
    return { time, from, to: session.close }
  }
  // The same exchange contract applies to native and derived clock periods.
  return timeframeBucketAt({ interval, native: false, market: { calendar } } as TimeframePlan, time)
}

export function createTradingTimeframes(source: DataFeed, options: TradingTimeframeOptions) {
  const now = options.now ?? (() => Date.now() / 1000)
  const market = (request: BarsRequest): TimeframeMarket => {
    if (!ensureInterval(request.interval)) throw new Error('Choose a supported chart interval')
    const calendar = options.calendar(request)
    return {
      key: `${options.providerId}:${options.calendarRevision()}:${request.exchange}:${request.variant?.session ?? 'regular'}`,
      calendar: calendar ?? unknownCalendar,
      sources: (typeof options.nativeIntervals === 'function'
        ? options.nativeIntervals(request)
        : options.nativeIntervals
      )
        .filter(ensureInterval)
        .map((interval) => ({
          interval,
          bounds: (time) =>
            sourceBounds(
              options.calendar({ ...request, from: time, to: time + 1 }),
              interval,
              time
            ),
          // The API uses finite date windows. Split large derived requests without
          // inventing a retention date or promising that a broker has older bars.
          maxSpanSeconds: 30 * DAY,
        })),
    }
  }
  const resampler = withTimeframes(source, { market, now })
  const prepare = async (request: BarsRequest) => {
    if (request.signal?.aborted) throw request.signal.reason
    await options.prepare?.(request)
    if (request.signal?.aborted) throw request.signal.reason
  }
  let destroyed = false
  const controllers = new Set<AbortController>()
  const owned = async <T>(
    request: BarsRequest,
    run: (req: BarsRequest) => Promise<T>
  ): Promise<T> => {
    if (destroyed) throw new Error('Chart data feed has closed')
    const controller = new AbortController()
    const abort = () => controller.abort()
    controllers.add(controller)
    request.signal?.addEventListener('abort', abort, { once: true })
    if (request.signal?.aborted) abort()
    const req = { ...request, signal: controller.signal }
    try {
      await prepare(req)
      return await run(req)
    } finally {
      controllers.delete(controller)
      request.signal?.removeEventListener('abort', abort)
    }
  }
  const feed: TimeframeFeed = {
    ...resampler,
    getBars: (request) => owned(request, (req) => resampler.getBars(req)),
    getBarsPage: (request) => {
      const rule = resolveInterval(request.interval).bucketing
      const duration =
        rule.mode === 'interval'
          ? rule.seconds
          : rule.mode === 'calendar'
            ? (rule.count ?? 1) * { month: 31, quarter: 93, year: 366 }[rule.unit] * DAY
            : DAY
      const from = request.from ?? request.before - duration * request.countBack * 2
      return owned({ ...request, from, to: request.before }, (req) =>
        resampler.getBarsPage!({ ...request, ...req })
      )
    },
    destroy() {
      destroyed = true
      for (const controller of controllers) controller.abort()
      resampler.destroy()
    },
  }
  const provider = createTimeframeProvider(feed, {
    now,
    ...(options.historicalSnapshot ? { historicalSnapshot: options.historicalSnapshot } : {}),
    availability(bar, request) {
      const req = { ...request, exchange: request.exchange ?? '' }
      const bucket = timeframeBucketAt(feed.resolve(req), bar.time)
      return { at: bucket?.to ?? null, confirmed: bucket !== null && bucket.to <= now() }
    },
  })
  return {
    feed,
    provider,
    supports(code: string, request: Partial<BarsRequest> = {}): boolean {
      try {
        planTimeframe(
          { symbol: '', exchange: '', ...request, interval: code },
          market({ symbol: '', exchange: '', ...request, interval: code })
        )
        return true
      } catch {
        return false
      }
    },
    bucketStart(request: BarsRequest, time: number): number {
      const bucket = timeframeBucketAt(feed.resolve(request), time)
      if (!bucket) throw new Error('This tick is outside the exchange session')
      return bucket.time
    },
    destroy: () => feed.destroy(),
  }
}
