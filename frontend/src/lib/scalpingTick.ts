/**
 * Pure tick-merge for the scalping terminal.
 *
 * The live WebSocket Quote feed and the REST MultiQuotes fallback each provide a
 * different subset of fields (the WS tick often omits change/change_percent, and
 * high/low for indices; MultiQuotes provides them). Merging FIELD BY FIELD — prefer
 * a FRESH WebSocket value only when that field exists, else MultiQuotes, else the
 * last WS snapshot — keeps prices live during market hours and refreshing after
 * hours WITHOUT blanking fields on every tick (which caused a visible flicker).
 *
 * Kept pure (no React/Date) so it is unit-testable; the caller passes `nowMs`.
 * needsQuotePoll tells the caller when the REST poll can be skipped. A stale WS snapshot
 * still wins over a MultiQuotes answer older than it (mqFetchedAt).
 */
import type { QuotesData } from '@/api/trading'

export interface TickView {
  ltp?: number
  change?: number
  change_percent?: number
  open?: number
  high?: number
  low?: number
}

export interface FeedEntry {
  data?: TickView
  lastUpdate?: number
}

/**
 * True when at least one symbol is not fully covered by a fresh feed tick, so the REST
 * MultiQuotes poll still has something to add. A symbol is covered when its feed entry
 * has a tick younger than staleMs that carries ltp, open, high and low (the fields
 * mergeTick takes from the feed). Ticks written by the feed's own REST fallback count
 * too. change and change_percent are not required: mergeTick derives them from the
 * MultiQuotes prev_close, so the caller must keep polling until a first answer has
 * arrived. An empty symbol list needs no poll.
 */
export function needsQuotePoll(
  symbols: ReadonlyArray<{ symbol: string; exchange: string }>,
  feed: ReadonlyMap<string, FeedEntry>,
  nowMs: number,
  staleMs: number
): boolean {
  return symbols.some(({ symbol, exchange }) => {
    const entry = feed.get(`${exchange}:${symbol}`)
    const d = entry?.data
    const fresh = entry?.lastUpdate != null && nowMs - entry.lastUpdate < staleMs
    return !(fresh && d?.ltp != null && d.open != null && d.high != null && d.low != null)
  })
}

export function mergeTick(
  wsData: TickView | undefined,
  wsLastUpdate: number | undefined,
  mq: QuotesData | undefined,
  nowMs: number,
  staleMs: number,
  mqFetchedAt?: number
): TickView | undefined {
  if (!wsData && !mq) return undefined

  const wsFresh = wsData?.ltp != null && wsLastUpdate != null && nowMs - wsLastUpdate < staleMs
  const wsNewer =
    wsData?.ltp != null && wsLastUpdate != null && mqFetchedAt != null && wsLastUpdate > mqFetchedAt
  const wsPreferred = wsFresh || wsNewer

  // Per field: a fresh (or newer-than-MultiQuotes) WS value if present, else MultiQuotes,
  // else the WS snapshot.
  const pick = (wsVal?: number, mqVal?: number) =>
    wsPreferred && wsVal != null ? wsVal : (mqVal ?? wsVal)

  const ltp = pick(wsData?.ltp, mq?.ltp)
  const prev = mq?.prev_close || 0
  const mqChange = prev && ltp != null ? ltp - prev : undefined
  const mqChangePct = prev && ltp != null ? ((ltp - prev) / prev) * 100 : undefined

  return {
    ltp,
    open: pick(wsData?.open, mq?.open),
    high: pick(wsData?.high, mq?.high),
    low: pick(wsData?.low, mq?.low),
    change: wsPreferred && wsData?.change != null ? wsData.change : (mqChange ?? wsData?.change),
    change_percent:
      wsPreferred && wsData?.change_percent != null
        ? wsData.change_percent
        : (mqChangePct ?? wsData?.change_percent),
  }
}
