/**
 * Build the position book for the scalping terminal.
 *
 * Combines, per (symbol, exchange, product):
 *  - today's BUY/SELL trades (qty + weighted avg)  -> realized P&L, buy/sell cols
 *  - the current open position (net qty, LTP, avg)  -> unrealized P&L
 *  - the active stop-loss                           -> SL column
 *
 * Pure function (no React/network) so it is unit-testable against the acceptance
 * cases. Rows with netQty 0 are retained when there were trades today so realized
 * P&L stays visible until the session/day resets.
 */
import { findLegSL, type SLState } from '@/hooks/useTrailingSL'
import type { ScalpingPositionRow, ScalpingProduct } from '@/types/scalping'
import type { Position, Trade } from '@/types/trading'

interface Agg {
  symbol: string
  exchange: string
  product: string
  buyQty: number
  sellQty: number
  buyValue: number
  sellValue: number
  posQty?: number
  ltp?: number
  posAvg?: number
}

const keyOf = (s: string, e: string, p: string) => `${e}:${s}:${p}`

export function buildPositionRows(
  positions: Position[],
  trades: Trade[],
  slMap: Record<string, SLState>,
  liveLtp?: (symbol: string, exchange: string) => number | undefined,
  // When provided, only instruments in the scalping list (exchange:symbol:product)
  // are included — scopes the book to the scalping strategy, not the whole account.
  trackedKeys?: Set<string>
): ScalpingPositionRow[] {
  const map = new Map<string, Agg>()

  const ensure = (symbol: string, exchange: string, product: string): Agg => {
    const k = keyOf(symbol, exchange, product)
    let rec = map.get(k)
    if (!rec) {
      rec = { symbol, exchange, product, buyQty: 0, sellQty: 0, buyValue: 0, sellValue: 0 }
      map.set(k, rec)
    }
    return rec
  }

  // Aggregate today's trades into buy/sell qty + value (for weighted averages).
  for (const t of trades) {
    const product = (t.product || '').toUpperCase()
    const rec = ensure(t.symbol, t.exchange, product)
    // Coerce broker numeric fields: live brokers can return these as strings.
    const qty = Math.abs(Number(t.quantity) || 0)
    const px = Number(t.average_price) || 0
    if ((t.action || '').toUpperCase() === 'BUY') {
      rec.buyQty += qty
      rec.buyValue += qty * px
    } else if ((t.action || '').toUpperCase() === 'SELL') {
      rec.sellQty += qty
      rec.sellValue += qty * px
    }
  }

  // Merge open positions (authoritative net qty, live LTP, broker avg).
  for (const p of positions) {
    const product = (p.product || '').toUpperCase()
    const rec = ensure(p.symbol, p.exchange, product)
    // Coerce broker numeric fields. The PositionBook API contract returns these
    // as strings (e.g. "83.74") for live brokers, which previously left
    // row.avgPrice a string and crashed the table on avgPrice.toFixed() (#1532).
    // Sandbox returns numbers, where Number() is a no-op.
    rec.posQty = Number(p.quantity) || 0
    rec.ltp = Number(p.ltp) || 0
    rec.posAvg = Number(p.average_price) || 0
  }

  const rows: ScalpingPositionRow[] = []
  for (const rec of map.values()) {
    if (trackedKeys && !trackedKeys.has(keyOf(rec.symbol, rec.exchange, rec.product))) {
      continue // not part of the scalping list — exclude account-wide positions
    }
    const buyAvg = rec.buyQty > 0 ? rec.buyValue / rec.buyQty : 0
    const sellAvg = rec.sellQty > 0 ? rec.sellValue / rec.sellQty : 0
    // The broker positionbook is authoritative for net qty. Open positions ALWAYS
    // appear in it; a closed position is DROPPED from it (posQty undefined) and must
    // read as flat (0). Deriving net from today's trade imbalance (buyQty - sellQty)
    // would show a PHANTOM open position after a close/F6 when the day's trades are
    // unbalanced (e.g. a carried-over position squared off today) — even though
    // /positions correctly shows flat. So trust the positionbook: absent => 0.
    const netQty = rec.posQty ?? 0
    const ltp = liveLtp?.(rec.symbol, rec.exchange) ?? rec.ltp ?? 0

    const realizedQty = Math.min(rec.buyQty, rec.sellQty)
    const realizedPnl = realizedQty > 0 ? (sellAvg - buyAvg) * realizedQty : 0

    let side: 'BUY' | 'SELL' | '-' = '-'
    let avgPrice = 0
    let unrealizedPnl = 0
    // Use the BROKER position average for open positions (authoritative for
    // carried-over / partially-closed legs). Today's trade VWAP (buyAvg/sellAvg)
    // is only a fallback when the broker avg is missing — using it for unrealized
    // P&L would misprice positions opened on a prior day or partially closed today.
    if (netQty > 0) {
      side = 'BUY'
      avgPrice = rec.posAvg && rec.posAvg > 0 ? rec.posAvg : buyAvg
      unrealizedPnl = (ltp - avgPrice) * netQty
    } else if (netQty < 0) {
      side = 'SELL'
      avgPrice = rec.posAvg && rec.posAvg > 0 ? rec.posAvg : sellAvg
      unrealizedPnl = (avgPrice - ltp) * Math.abs(netQty)
    }

    const sl = findLegSL(slMap, rec.symbol, rec.exchange, rec.product as ScalpingProduct)

    rows.push({
      symbol: rec.symbol,
      exchange: rec.exchange,
      product: rec.product as ScalpingProduct,
      side,
      netQty,
      ltp,
      sl: sl ? sl.currentSl : null,
      target: sl && sl.target > 0 ? sl.target : null,
      trailingStep: sl?.trailingEnabled && sl.trailingStep > 0 ? sl.trailingStep : null,
      realizedPnl,
      unrealizedPnl,
      totalPnl: realizedPnl + unrealizedPnl,
      avgPrice,
      buyQty: rec.buyQty,
      buyAvg,
      sellQty: rec.sellQty,
      sellAvg,
    })
  }

  // Open rows first, then alphabetical — keeps the active positions at the top.
  rows.sort(
    (a, b) =>
      (b.netQty !== 0 ? 1 : 0) - (a.netQty !== 0 ? 1 : 0) || a.symbol.localeCompare(b.symbol)
  )
  return rows
}
