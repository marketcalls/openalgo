import { type StrategyAttribution, UNATTRIBUTED } from '@/api/trading'
import type { Holding, Position } from '@/types/trading'

/**
 * Narrow holdings to one strategy's share of them: each holding becomes just
 * that strategy's quantity (free/T1/pledged folded into one figure) at the
 * strategy's own average price, marked to the live LTP. Holdings the strategy
 * does not own are dropped. Pass UNATTRIBUTED to see what no strategy claims.
 */
export function narrowHoldingsToStrategy<T extends Holding>(
  holdings: T[],
  attribution: StrategyAttribution | null,
  strategy: string
): T[] {
  if (!attribution) return []
  const byKey = new Map(attribution.rows.map((r) => [`${r.symbol}|${r.exchange}`, r]))
  const narrowed: T[] = []

  for (const holding of holdings) {
    const slice = byKey
      .get(`${holding.symbol}|${holding.exchange}`)
      ?.slices.find((s) => s.strategy === strategy)
    if (!slice || slice.quantity === 0) continue

    const ltp = Number(holding.ltp)
    const hasLtp = Number.isFinite(ltp) && ltp > 0
    const invested = slice.quantity * slice.average_price
    const pnl = hasLtp ? slice.quantity * (ltp - slice.average_price) : 0
    narrowed.push({
      ...holding,
      quantity: slice.quantity,
      t1_quantity: 0,
      pledged_quantity: 0,
      average_price: slice.average_price,
      pnl,
      pnlpercent: hasLtp && invested > 0 ? (pnl / invested) * 100 : 0,
    })
  }
  return narrowed
}

/** A broker position narrowed to one strategy's share of it. */
export type SlicedPosition = Position & { sliced?: boolean; m2mBase?: number }

/** Which P&L a page shows: the broker's own, or today's move only (M2M). */
export type PnlBasis = 'pnl' | 'm2m'

/**
 * Show today's M2M instead of the broker's P&L (services/position_m2m.py). The
 * server returns the part of M2M that does not move with the price
 * (`m2m_fixed`); the live LTP is added here so the figure keeps ticking between
 * polls. A row the server could not compute keeps the broker's own P&L rather
 * than showing a wrong number, and is listed in `fallbackRows`.
 *
 * `m2mBase` is what the percentage is measured against: yesterday's close for a
 * carried position, the average entry price otherwise.
 */
export function applyM2m(
  positions: Position[],
  attribution: StrategyAttribution | null
): { positions: SlicedPosition[]; fallbackRows: number } {
  if (!attribution) return { positions, fallbackRows: positions.length }
  const byKey = new Map(attribution.rows.map((r) => [`${r.symbol}|${r.exchange}|${r.product}`, r]))
  let fallbackRows = 0
  const out = positions.map((pos): SlicedPosition => {
    const row = byKey.get(`${pos.symbol}|${pos.exchange}|${pos.product}`)
    if (!row?.m2m_available || row.m2m_fixed == null) {
      fallbackRows += 1
      return pos
    }
    const qty = Number(pos.quantity) || 0
    const ltp = Number(pos.ltp)
    const live = qty !== 0 && Number.isFinite(ltp) && ltp > 0 ? qty * ltp : 0
    const pnl = row.m2m_fixed + live
    const carried = Math.abs(row.overnight_quantity ?? 0) > 1e-9
    const base = carried ? row.prev_close || 0 : Number(pos.average_price) || 0
    const invested = Math.abs(qty) * base
    return {
      ...pos,
      pnl,
      pnlpercent: invested > 0 ? (pnl / invested) * 100 : 0,
      m2mBase: base,
    }
  })
  return { positions: out, fallbackRows }
}

const isSameContract = (a: Position, b: Position) =>
  a.symbol === b.symbol && a.exchange === b.exchange && a.product === b.product

/**
 * Split each broker position into the strategy slices the backend reported
 * (services/strategy_attribution.py). The broker row stays the truth for the
 * total: slice P&L is marked from the live LTP plus what the strategy realized
 * today, and whatever the slices do not explain stays on Unattributed, so a
 * group's rows always add back up to the broker's own P&L.
 */
export function groupByStrategy(
  positions: SlicedPosition[],
  attribution: StrategyAttribution | null,
  basis: PnlBasis = 'pnl'
): Record<string, SlicedPosition[]> {
  const byKey = new Map(
    (attribution?.rows ?? []).map((r) => [`${r.symbol}|${r.exchange}|${r.product}`, r])
  )
  const groups: Record<string, SlicedPosition[]> = {}
  const add = (name: string, row: SlicedPosition) => {
    if (!groups[name]) groups[name] = []
    groups[name].push(row)
  }

  for (const pos of positions) {
    const attributed = byKey.get(`${pos.symbol}|${pos.exchange}|${pos.product}`)
    const slices = attributed?.slices ?? []

    if (basis === 'm2m') {
      // The row's M2M (already in pos.pnl) is exact; how it divides between
      // strategies is not recorded anywhere, so an open row is split by each
      // strategy's quantity, and a flat row goes to the one strategy that
      // traded it (or stays Unattributed when that is ambiguous).
      const qty = Number(pos.quantity) || 0
      const openSlices = slices.filter((s) => s.quantity !== 0)
      const weight = openSlices.reduce((sum, s) => sum + Math.abs(s.quantity), 0)
      if (qty !== 0 && weight > 0) {
        for (const slice of openSlices) {
          add(slice.strategy, {
            ...pos,
            quantity: slice.quantity,
            average_price: slice.average_price,
            pnl: (Number(pos.pnl) || 0) * (Math.abs(slice.quantity) / weight),
            sliced: true,
          })
        }
      } else {
        add(attributed?.leftover_owner || UNATTRIBUTED, { ...pos, sliced: true })
      }
      continue
    }

    const ltp = Number(pos.ltp)
    const hasLtp = Number.isFinite(ltp) && ltp > 0
    let explained = 0
    let remainderRow: SlicedPosition | undefined

    for (const slice of slices) {
      const realized = slice.today_realized_pnl || 0
      const pnl = hasLtp ? slice.quantity * (ltp - slice.average_price) + realized : realized
      explained += pnl
      const row: SlicedPosition = {
        ...pos,
        quantity: slice.quantity,
        average_price: slice.average_price,
        pnl,
        pnlpercent: 0,
        sliced: true,
      }
      if (slice.strategy === UNATTRIBUTED) remainderRow = row
      add(slice.strategy, row)
    }

    // Whatever the slices do not explain: a manual trade, an untagged
    // position, or P&L the book never saw. Never dropped, so totals match.
    const leftover = (Number(pos.pnl) || 0) - explained
    if (slices.length === 0) {
      // Nothing explains it, unless the book still shows exactly one strategy
      // holding a position the broker has closed: then it is that strategy's.
      add(attributed?.leftover_owner || UNATTRIBUTED, { ...pos, sliced: true })
    } else if (Math.abs(leftover) >= 0.005) {
      const owner = attributed?.leftover_owner
      const ownerRow = owner ? groups[owner]?.find((r) => isSameContract(r, pos)) : undefined
      if (remainderRow) {
        remainderRow.pnl += leftover
      } else if (ownerRow) {
        ownerRow.pnl += leftover
      } else {
        // A flat position the book still shows one strategy holding: that
        // strategy closed it outside the book, so the realized P&L is its own.
        add(owner || UNATTRIBUTED, {
          ...pos,
          quantity: 0,
          pnl: leftover,
          pnlpercent: 0,
          sliced: true,
        })
      }
    }
  }

  // Percent is relative to what the slice cost (or, for M2M, what the day's move
  // is measured from), so it is set once the P&L is final.
  for (const rows of Object.values(groups)) {
    for (const row of rows) {
      const base = basis === 'm2m' ? row.m2mBase || 0 : row.average_price || 0
      const invested = Math.abs((row.quantity || 0) * base)
      row.pnlpercent = invested > 0 ? (row.pnl / invested) * 100 : 0
    }
  }
  return groups
}
