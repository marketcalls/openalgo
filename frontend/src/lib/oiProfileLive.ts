import type { OIProfileChainItem, OIProfileLeg } from '@/api/oi-profile'
import type { SymbolData } from '@/lib/MarketDataManager'

type Side = 'ce' | 'pe'

/**
 * Lay live open interest from the WebSocket feed over a polled OI Profile.
 *
 * The profile answer is cached on the server and refreshed on a slow beat, so
 * on its own it lags the exchange. A broker whose feed carries `oi` lets the
 * page do better for free: the ticks are already flowing, so nothing extra is
 * asked of the broker. A leg with no live OI keeps its polled number, which is
 * what makes this safe on brokers whose feed never sends it.
 *
 * The change is re-based on the same anchor the server used (`base`), so a
 * live leg moves the change by exactly the amount it moves the OI. A leg with
 * no known base is left out of the change rather than counted as all-new OI.
 */
export function applyLiveOi(
  chain: OIProfileChainItem[],
  live: Map<string, SymbolData>,
  exchange: string
): { chain: OIProfileChainItem[]; liveLegs: number } {
  let liveLegs = 0

  const liveOi = (leg: OIProfileLeg): number | null => {
    const oi = live.get(`${exchange}:${leg.symbol}`)?.data.oi
    // 0 is a feed that does not know, not an emptied contract.
    return typeof oi === 'number' && oi > 0 ? oi : null
  }

  const next = chain.map((row) => {
    const out = { ...row }
    for (const side of ['ce', 'pe'] as Side[]) {
      const legs = row[`${side}_legs`]
      if (!legs?.length) continue

      let total = 0
      let change = 0
      let sawLive = false
      for (const leg of legs) {
        const l = liveOi(leg)
        const oi = l ?? leg.oi
        total += oi
        if (l !== null) {
          sawLive = true
          liveLegs += 1
          if (leg.base !== null) change += l - leg.base
        } else if (leg.base !== null) {
          change += leg.oi - leg.base
        }
      }
      if (!sawLive) continue
      out[`${side}_oi`] = total
      // Only re-base when every leg's change is anchored; a mix of known and
      // unknown bases would understate it.
      if (legs.every((leg) => leg.base !== null)) out[`${side}_oi_change`] = change
    }
    return out
  })

  return { chain: next, liveLegs }
}
