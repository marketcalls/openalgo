import type { OIProfileChainItem, OIProfileLeg } from '@/api/oi-profile'

type Side = 'ce' | 'pe'

/** The latest open interest a feed tick carried for one contract, and when. */
export interface LiveOi {
  oi: number
  /** Epoch ms the tick arrived. */
  at: number
}

/**
 * Key a live-OI map by exchange and symbol, uppercased the way
 * MarketDataManager normalises both, so a lowercase symbol in a profile answer
 * still finds its ticks.
 */
export const liveOiKey = (exchange: string, symbol: string): string =>
  `${exchange}:${symbol}`.toUpperCase()

/**
 * Lay live open interest from the WebSocket feed over a polled OI Profile.
 *
 * The profile answer is cached on the server and refreshed on a slow beat, so
 * on its own it lags the exchange. A broker whose feed carries `oi` lets the
 * page do better for free: the ticks are already flowing, so nothing extra is
 * asked of the broker. A leg with no usable tick keeps its polled number, which
 * is what makes this safe on brokers whose feed never sends it.
 *
 * - A tick of 0 is treated as unknown: some adapters send 0 when the packet
 *   simply did not carry OI, so 0 cannot be told apart from "not sent".
 * - A tick older than `maxAgeMs` is no longer live. A feed that silently stops
 *   (a dropped socket, a contract that stops trading) then falls back to the
 *   polled number on the next beat instead of freezing on its last tick.
 * - The change is the sum over legs with a known anchor (`base`) of
 *   `oi - base`, which is exactly how the server builds it: a leg without a
 *   base contributes nothing there either, so it never freezes the rest.
 */
export function applyLiveOi(
  chain: OIProfileChainItem[],
  live: Map<string, LiveOi>,
  exchange: string,
  now: number = Date.now(),
  maxAgeMs: number = Number.POSITIVE_INFINITY
): { chain: OIProfileChainItem[]; liveLegs: number } {
  let liveLegs = 0

  const liveOi = (leg: OIProfileLeg): number | null => {
    const tick = live.get(liveOiKey(exchange, leg.symbol))
    if (!tick || !(tick.oi > 0) || now - tick.at > maxAgeMs) return null
    return tick.oi
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
        const tick = liveOi(leg)
        const oi = tick ?? leg.oi
        total += oi
        if (tick !== null) {
          sawLive = true
          liveLegs += 1
        }
        if (leg.base !== null) change += oi - leg.base
      }
      if (!sawLive) continue
      out[`${side}_oi`] = total
      out[`${side}_oi_change`] = change
    }
    return out
  })

  return { chain: next, liveLegs }
}
