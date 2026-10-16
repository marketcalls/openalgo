// frontend/src/lib/pnlModel.ts
/**
 * Everything the P&L page shows, derived from one fetch and one set of filters
 * (fork-only, SKYSHIELD_PATCHES.md). Pure, so the summary, strategies, curve,
 * calendar and the Day / Week / Month / Scrip views cannot disagree.
 *
 * Two sources feed it:
 *  - closed lots and open positions from GET /pnl/history (every segment);
 *  - for Equity, the daily realized and unrealized series from GET /pnl/curve.
 * With the curve present the series follow the chosen P&L type; without it
 * (other segments) they are realized-only, by the day a lot closed.
 *
 * Filters: `strategies` is an inclusion list, empty meaning "all". The symbol,
 * exchange and product filters narrow the closed lots and open positions; the
 * equity curve gets the symbol on the server and the strategy list here. A
 * lot with no strategy is the strategy "Untagged".
 */
import type { PnlHistoryClosedTrade, PnlHistoryOpenPosition } from '@/api/trading'
import type { PnlTableFilters } from '@/hooks/usePnlFilters'
import {
  type CurveData,
  type CurveLot,
  type CurveMode,
  cumulative,
  curveSeries,
  type DailySeries,
  dailySeries,
  foldCurveStrategies,
  OTHER_STRATEGY,
  strategyOf,
  UNTAGGED,
} from '@/lib/pnlCurve'

/** Marks "no strategy selected" inside the inclusion list. */
export const NO_STRATEGY = '∅'

export interface PnlModelInput {
  closedTrades: PnlHistoryClosedTrade[]
  openPositions: PnlHistoryOpenPosition[]
  unrealizedAvailable: boolean
  curve: CurveData | null
  segment: string
  pnlType: 'realized' | 'unrealized' | 'combined'
  filters: PnlTableFilters
  maxStrategies: number
}

export interface PnlModel {
  /** Which P&L the series carry. Realized only when there is no equity curve. */
  mode: CurveMode
  hasCurve: boolean
  /** Strategy names for colours, in order, then Other and Untagged when present. */
  strategyNames: string[]
  /** Names that get a palette colour (the rest are neutral). */
  coloured: string[]
  /** Every strategy, ignoring the selection (for the chips' own totals). */
  allSeries: DailySeries
  /** The selection. */
  series: DailySeries
  /** The selection's realized-only daily series, whatever the P&L type. */
  realizedSeries: DailySeries
  /** Closed lots and open positions after every filter. */
  lots: PnlHistoryClosedTrade[]
  open: PnlHistoryOpenPosition[]
  /** Cumulative realized and the open level, for the combined plot; null when not combined. */
  splitLines: { realized: number[]; unrealized: number[] } | null
  /** Per selected strategy: realized total and the open level at the end. */
  perStrategy: Map<string, { realized: number; unrealized: number | null }>
  /** Realized and unrealized for the selection, for the Net P&L card. */
  split: { realized: number; unrealized: number | null }
  /** Option lists for the Filters dialog. */
  options: { strategies: string[]; exchanges: string[]; products: string[] }
  isSelected: (name: string) => boolean
  /** True when exchange or product filters are set but cannot narrow the equity series. */
  curveIgnoresFilters: boolean
}

const EMPTY: DailySeries = { dates: [], total: [], byStrategy: new Map() }

function nameOf(strategy: string | null): string {
  return strategy || UNTAGGED
}

export function buildPnlModel(input: PnlModelInput): PnlModel {
  const { closedTrades, openPositions, curve, filters, maxStrategies } = input
  const hasCurve = !!curve && input.segment === 'equity'
  const mode: CurveMode = hasCurve ? input.pnlType : 'realized'

  const selectedNames = filters.strategies
  const isSelected = (name: string) => selectedNames.length === 0 || selectedNames.includes(name)

  const needle = filters.symbol.trim().toUpperCase()
  const matchesBase = (symbol: string, exchange: string, product: string | null) => {
    if (needle && !symbol.toUpperCase().includes(needle)) return false
    if (filters.exchanges.length > 0 && !filters.exchanges.includes(exchange)) return false
    if (filters.products.length > 0 && !(product && filters.products.includes(product)))
      return false
    return true
  }

  // Closed lots and open positions after every filter (Scrip view, tables).
  const lots = closedTrades.filter(
    (t) => matchesBase(t.symbol, t.exchange, t.product) && isSelected(nameOf(t.strategy))
  )
  const open = openPositions.filter(
    (p) => matchesBase(p.symbol, p.exchange, p.product) && isSelected(nameOf(p.strategy))
  )

  // Option lists come from the unfiltered data, so a filter never hides its own options.
  const strategyOptions = new Set<string>()
  for (const t of closedTrades) strategyOptions.add(nameOf(t.strategy))
  for (const p of openPositions) strategyOptions.add(nameOf(p.strategy))
  if (curve) for (const name of Object.keys(curve.by_strategy)) strategyOptions.add(name)
  const options = {
    strategies: Array.from(strategyOptions).sort(),
    exchanges: Array.from(
      new Set([...closedTrades.map((t) => t.exchange), ...openPositions.map((p) => p.exchange)])
    ).sort(),
    products: Array.from(
      new Set(
        [...closedTrades.map((t) => t.product), ...openPositions.map((p) => p.product)].filter(
          (p): p is string => !!p
        )
      )
    ).sort(),
  }

  const curveIgnoresFilters =
    hasCurve && (filters.exchanges.length > 0 || filters.products.length > 0)

  if (hasCurve && curve) {
    const folded = foldCurveStrategies(curve.by_strategy, maxStrategies)
    const present = new Set(folded.byName.keys())
    const strategyNames = [
      ...folded.names,
      ...(present.has(OTHER_STRATEGY) ? [OTHER_STRATEGY] : []),
      ...(present.has(UNTAGGED) ? [UNTAGGED] : []),
    ]
    const allSeries = curveSeries(curve.dates, folded.byName, mode)
    const series = curveSeries(curve.dates, folded.byName, mode, isSelected)
    const realizedSeries = curveSeries(curve.dates, folded.byName, 'realized', isSelected)
    const unrealizedLevel = cumulative(
      curveSeries(curve.dates, folded.byName, 'unrealized', isSelected).total
    )
    const perStrategy = new Map<string, { realized: number; unrealized: number | null }>()
    for (const [name, s] of folded.byName) {
      if (!isSelected(name)) continue
      perStrategy.set(name, {
        realized: s.realized.reduce((a, b) => a + b, 0),
        unrealized: s.unrealized.length ? s.unrealized[s.unrealized.length - 1] : 0,
      })
    }
    return {
      mode,
      hasCurve: true,
      strategyNames,
      coloured: folded.names,
      allSeries,
      series,
      realizedSeries,
      perStrategy,
      splitLines:
        mode === 'combined'
          ? { realized: cumulative(realizedSeries.total), unrealized: unrealizedLevel }
          : null,
      lots,
      open,
      split: {
        realized: realizedSeries.total.reduce((a, b) => a + b, 0),
        unrealized: unrealizedLevel.length ? unrealizedLevel[unrealizedLevel.length - 1] : 0,
      },
      options,
      isSelected,
      curveIgnoresFilters,
    }
  }

  // Realized-only: lots narrowed by symbol, exchange and product; the strategy
  // selection is applied on the folded names, as the chips are.
  const baseLots: CurveLot[] = closedTrades
    .filter((t) => matchesBase(t.symbol, t.exchange, t.product))
    .map((t) => ({
      exit_timestamp: t.exit_timestamp,
      realized_pnl: t.realized_pnl,
      strategy: t.strategy,
      symbol: t.symbol,
      exchange: t.exchange,
      product: t.product,
    }))
  const names = Array.from(new Set(baseLots.map(strategyOf)))
    .filter((n) => n !== UNTAGGED)
    .sort()
  const kept = names.slice(0, maxStrategies)
  const foldedLots = baseLots.map((lot) => {
    const name = strategyOf(lot)
    return name === UNTAGGED || kept.includes(name) ? lot : { ...lot, strategy: OTHER_STRATEGY }
  })
  const presentNames = new Set(foldedLots.map(strategyOf))
  const strategyNames = [
    ...kept,
    ...(presentNames.has(OTHER_STRATEGY) ? [OTHER_STRATEGY] : []),
    ...(presentNames.has(UNTAGGED) ? [UNTAGGED] : []),
  ]
  const allSeries = foldedLots.length ? dailySeries(foldedLots) : EMPTY
  const selected = foldedLots.filter((lot) => isSelected(strategyOf(lot)))
  const series = selected.length ? dailySeries(selected) : EMPTY
  const foldName = (strategy: string | null): string => {
    const name = nameOf(strategy)
    return name === UNTAGGED || kept.includes(name) ? name : OTHER_STRATEGY
  }
  const perStrategy = new Map<string, { realized: number; unrealized: number | null }>()
  for (const [name, daily] of series.byStrategy) {
    perStrategy.set(name, {
      realized: daily.reduce((a, b) => a + b, 0),
      unrealized: input.unrealizedAvailable ? 0 : null,
    })
  }
  if (input.unrealizedAvailable) {
    for (const p of open) {
      const row = perStrategy.get(foldName(p.strategy))
      if (row) row.unrealized = (row.unrealized ?? 0) + (p.unrealized_pnl ?? 0)
    }
  }
  const unrealized = input.unrealizedAvailable
    ? open.reduce((sum, p) => sum + (p.unrealized_pnl ?? 0), 0)
    : null
  return {
    mode: 'realized',
    hasCurve: false,
    strategyNames,
    coloured: kept,
    allSeries,
    series,
    realizedSeries: series,
    perStrategy,
    splitLines: null,
    lots,
    open,
    split: { realized: series.total.reduce((a, b) => a + b, 0), unrealized },
    options,
    isSelected,
    curveIgnoresFilters: false,
  }
}
