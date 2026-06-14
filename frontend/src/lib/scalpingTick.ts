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

export function mergeTick(
  wsData: TickView | undefined,
  wsLastUpdate: number | undefined,
  mq: QuotesData | undefined,
  nowMs: number,
  staleMs: number
): TickView | undefined {
  if (!wsData && !mq) return undefined

  const wsFresh = wsData?.ltp != null && wsLastUpdate != null && nowMs - wsLastUpdate < staleMs

  // Per field: a fresh WS value if present, else MultiQuotes, else the WS snapshot.
  const pick = (wsVal?: number, mqVal?: number) =>
    wsFresh && wsVal != null ? wsVal : (mqVal ?? wsVal)

  const ltp = pick(wsData?.ltp, mq?.ltp)
  const prev = mq?.prev_close || 0
  const mqChange = prev && ltp != null ? ltp - prev : undefined
  const mqChangePct = prev && ltp != null ? ((ltp - prev) / prev) * 100 : undefined

  return {
    ltp,
    open: pick(wsData?.open, mq?.open),
    high: pick(wsData?.high, mq?.high),
    low: pick(wsData?.low, mq?.low),
    change: wsFresh && wsData?.change != null ? wsData.change : (mqChange ?? wsData?.change),
    change_percent:
      wsFresh && wsData?.change_percent != null
        ? wsData.change_percent
        : (mqChangePct ?? wsData?.change_percent),
  }
}
